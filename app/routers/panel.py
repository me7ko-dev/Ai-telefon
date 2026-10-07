"""Панелът на собственика. Всяка заявка работи само с данните на текущата фирма (business_id)."""

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import panel_business, require_login
from app.models import Appointment, Business, DayOff, Faq, Message, Service, ToolCall
from app.services import booking
from app.services import elevenlabs as el
from app.services.agent_tools import tool_specs
from app.services.elevenlabs import auto_push
from app.services.textutil import WEEKDAYS, InputError, now_local
from app.web import flash, redirect, render

router = APIRouter(prefix="/panel", tags=["panel"], dependencies=[Depends(require_login)])


# ---------- помощни ----------

def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return min(hi, max(lo, int(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _time(value) -> time | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _price(value) -> float | None:
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _get_owned(db: Session, model, obj_id: int, b: Business):
    obj = db.get(model, obj_id)
    return obj if obj is not None and obj.business_id == b.id else None


# ---------- табло ----------

@router.get("")
def dashboard(request: Request, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    today = now_local(b.timezone).date()
    todays = db.scalars(
        select(Appointment)
        .where(Appointment.business_id == b.id, Appointment.date == today, Appointment.status == "booked")
        .order_by(Appointment.start_time)
    ).all()
    upcoming = db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.business_id == b.id, Appointment.date > today, Appointment.status == "booked"
        )
    )
    unread = db.scalar(select(func.count(Message.id)).where(Message.business_id == b.id, Message.is_read.is_(False)))
    return render(request, "dashboard.html", b=b, today=today, todays=todays, upcoming=upcoming, unread=unread)


# ---------- фирма и работно време ----------

@router.get("/business")
def business_form(request: Request, b: Business = Depends(panel_business)):
    today = now_local(b.timezone).date()
    days_off = [d for d in b.days_off if d.date >= today]
    return render(request, "business.html", b=b, days_off=days_off, today=today)


@router.post("/business")
async def business_save(request: Request, bg: BackgroundTasks, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        flash(request, "Името на фирмата е задължително.", "error")
        return redirect("/panel/business")
    b.name = name
    for field in ("business_type", "description", "address", "extra_info", "assistant_name"):
        setattr(b, field, (form.get(field) or "").strip())
    b.currency = (form.get("currency") or "").strip() or "евро"
    b.slot_step_min = _int(form.get("slot_step_min"), 30, 5, 240)
    b.capacity = _int(form.get("capacity"), 1, 1, 50)
    b.min_notice_min = _int(form.get("min_notice_min"), 60, 0, 7 * 24 * 60)
    b.booking_horizon_days = _int(form.get("booking_horizon_days"), 60, 1, 365)

    errors = []
    for wh in b.working_hours:
        wd = wh.weekday
        wh.is_open = form.get(f"open_{wd}") == "on"
        start, end = _time(form.get(f"from_{wd}")), _time(form.get(f"to_{wd}"))
        bs, be = _time(form.get(f"bstart_{wd}")), _time(form.get(f"bend_{wd}"))
        if start and end:
            if end <= start:
                errors.append(f"{WEEKDAYS[wd].capitalize()}: краят трябва да е след началото.")
                continue
            wh.open_time, wh.close_time = start, end
        if bs and be and wh.open_time < bs < be < wh.close_time:
            wh.break_start, wh.break_end = bs, be
        else:
            if bs or be:
                errors.append(f"{WEEKDAYS[wd].capitalize()}: почивката трябва да е в рамките на работното време.")
            wh.break_start = wh.break_end = None
    db.commit()
    for e in errors:
        flash(request, e, "error")
    flash(request, "Запазено.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/business")


@router.post("/days-off")
def day_off_add(
    request: Request, bg: BackgroundTasks,
    day: date = Form(...),
    note: str = Form(""),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    if any(d.date == day for d in b.days_off):
        flash(request, "Тази дата вече е добавена.", "error")
    else:
        db.add(DayOff(business_id=b.id, date=day, note=note.strip()))
        db.commit()
        flash(request, "Почивният ден е добавен.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/business#days-off")


@router.post("/days-off/{item_id}/delete")
def day_off_delete(request: Request, bg: BackgroundTasks, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    if obj := _get_owned(db, DayOff, item_id, b):
        db.delete(obj)
        db.commit()
        flash(request, "Изтрито.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/business#days-off")


# ---------- услуги ----------

@router.get("/services")
def services_list(request: Request, b: Business = Depends(panel_business)):
    return render(request, "services.html", b=b)


@router.post("/services")
def service_add(
    request: Request, bg: BackgroundTasks,
    name: str = Form(""),
    duration_min: str = Form("30"),
    price: str = Form(""),
    description: str = Form(""),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    if not name.strip():
        flash(request, "Въведи име на услугата.", "error")
        return redirect("/panel/services")
    pos = max((s.position for s in b.services), default=0) + 1
    db.add(
        Service(
            business_id=b.id,
            name=name.strip(),
            duration_min=_int(duration_min, 30, 5, 600),
            price=_price(price),
            description=description.strip(),
            position=pos,
        )
    )
    db.commit()
    flash(request, "Услугата е добавена.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/services")


@router.post("/services/{item_id}")
def service_update(
    request: Request, bg: BackgroundTasks,
    item_id: int,
    name: str = Form(""),
    duration_min: str = Form("30"),
    price: str = Form(""),
    description: str = Form(""),
    is_active: str | None = Form(None),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    s = _get_owned(db, Service, item_id, b)
    if s and name.strip():
        s.name = name.strip()
        s.duration_min = _int(duration_min, s.duration_min, 5, 600)
        s.price = _price(price)
        s.description = description.strip()
        s.is_active = is_active == "on"
        db.commit()
        flash(request, f"„{s.name}“ е запазена.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/services")


@router.post("/services/{item_id}/delete")
def service_delete(request: Request, bg: BackgroundTasks, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    if s := _get_owned(db, Service, item_id, b):
        db.delete(s)
        db.commit()
        flash(request, "Услугата е изтрита. Старите записи остават.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/services")


# ---------- въпроси ----------

@router.get("/faqs")
def faqs_list(request: Request, b: Business = Depends(panel_business)):
    return render(request, "faqs.html", b=b)


@router.post("/faqs")
def faq_add(
    request: Request, bg: BackgroundTasks,
    question: str = Form(""),
    answer: str = Form(""),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    if not question.strip() or not answer.strip():
        flash(request, "Попълни и въпрос, и отговор.", "error")
        return redirect("/panel/faqs")
    pos = max((f.position for f in b.faqs), default=0) + 1
    db.add(Faq(business_id=b.id, question=question.strip(), answer=answer.strip(), position=pos))
    db.commit()
    flash(request, "Въпросът е добавен.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/faqs")


@router.post("/faqs/{item_id}")
def faq_update(
    request: Request, bg: BackgroundTasks,
    item_id: int,
    question: str = Form(""),
    answer: str = Form(""),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    f = _get_owned(db, Faq, item_id, b)
    if f and question.strip() and answer.strip():
        f.question, f.answer = question.strip(), answer.strip()
        db.commit()
        flash(request, "Запазено.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/faqs")


@router.post("/faqs/{item_id}/delete")
def faq_delete(request: Request, bg: BackgroundTasks, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    if f := _get_owned(db, Faq, item_id, b):
        db.delete(f)
        db.commit()
        flash(request, "Изтрито.")
    bg.add_task(auto_push, b.id)
    return redirect("/panel/faqs")


# ---------- записани часове ----------

@router.get("/appointments")
def appointments_list(
    request: Request, show: str = "upcoming", b: Business = Depends(panel_business), db: Session = Depends(get_db)
):
    today = now_local(b.timezone).date()
    q = select(Appointment).where(Appointment.business_id == b.id)
    if show == "past":
        q = q.where(Appointment.date < today, Appointment.status == "booked").order_by(
            Appointment.date.desc(), Appointment.start_time.desc()
        )
    elif show == "cancelled":
        q = q.where(Appointment.status == "cancelled").order_by(Appointment.cancelled_at.desc())
    else:
        show = "upcoming"
        q = q.where(Appointment.date >= today, Appointment.status == "booked").order_by(
            Appointment.date, Appointment.start_time
        )
    items = db.scalars(q.limit(300)).all()
    return render(request, "appointments.html", b=b, items=items, show=show, today=today,
                  tomorrow=today + timedelta(days=1))


@router.post("/appointments")
def appointment_add(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    service: str = Form(""),
    day: str = Form(""),
    start: str = Form(""),
    note: str = Form(""),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    try:
        res = booking.book_appointment(db, b, name, phone, service, day, start, source="panel", note=note.strip())
    except InputError as e:
        res = {"ok": False, "message": str(e)}
    flash(request, res["message"], "ok" if res["ok"] else "error")
    return redirect("/panel/appointments")


@router.post("/appointments/{item_id}/cancel")
def appointment_cancel(request: Request, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    a = _get_owned(db, Appointment, item_id, b)
    if a and a.status == "booked":
        a.status = "cancelled"
        a.cancelled_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        flash(request, f"Часът на {a.customer_name} е отменен.")
    return redirect("/panel/appointments")


# ---------- съобщения ----------

@router.get("/messages")
def messages_list(request: Request, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    items = db.scalars(
        select(Message).where(Message.business_id == b.id).order_by(Message.is_read, Message.created_at.desc()).limit(300)
    ).all()
    return render(request, "messages.html", b=b, items=items)


@router.post("/messages/{item_id}/read")
def message_read(request: Request, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    if m := _get_owned(db, Message, item_id, b):
        m.is_read = not m.is_read
        db.commit()
    return redirect("/panel/messages")


@router.post("/messages/{item_id}/delete")
def message_delete(request: Request, item_id: int, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    if m := _get_owned(db, Message, item_id, b):
        db.delete(m)
        db.commit()
        flash(request, "Съобщението е изтрито.")
    return redirect("/panel/messages")


# ---------- агент (ElevenLabs) ----------

@router.get("/prompt")
def agent_page(request: Request, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    cfg = el.get_config(db, b)
    system_prompt, first_message = el.prompt_texts(b)
    url = el.tools_url(cfg, b)
    synced = cfg.tool_ids not in ("", "{}")
    return render(
        request,
        "prompt.html",
        b=b,
        cfg=cfg,
        system_prompt=system_prompt,
        first_message=first_message,
        tools_url=url,
        specs=tool_specs(cfg.cancel_only_own_number),
        has_api_key=bool(get_settings().elevenlabs_api_key),
        synced=synced,
        prompt_outdated=synced and cfg.pushed_prompt_hash != el.prompt_hash(b),
        url_changed=synced and cfg.tools_url != url,
    )


@router.post("/agent")
def agent_save(
    request: Request,
    agent_id: str = Form(""),
    public_base_url: str = Form(""),
    auto_sync: str | None = Form(None),
    cancel_only_own_number: str | None = Form(None),
    b: Business = Depends(panel_business),
    db: Session = Depends(get_db),
):
    cfg = el.get_config(db, b)
    cfg.agent_id = agent_id.strip()
    cfg.public_base_url = public_base_url.strip().rstrip("/")
    cfg.auto_sync = auto_sync == "on"
    cfg.cancel_only_own_number = cancel_only_own_number == "on"
    db.commit()
    flash(request, "Настройките на агента са запазени. Натисни „Изпрати към ElevenLabs“, за да се приложат.")
    return redirect("/panel/prompt")


@router.post("/agent/sync")
def agent_sync(request: Request, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    client = el.make_client()
    if client is None:
        flash(request, "Липсва ELEVENLABS_API_KEY в .env – добави го и рестартирай сървъра, или настрой агента ръчно.", "error")
        return redirect("/panel/prompt")
    try:
        flash(request, el.sync_all(db, b, client))
    except el.ElevenLabsError as e:
        flash(request, str(e), "error")
    return redirect("/panel/prompt")


@router.get("/tool-log")
def tool_log(request: Request, b: Business = Depends(panel_business), db: Session = Depends(get_db)):
    items = db.scalars(
        select(ToolCall).where(ToolCall.business_id == b.id).order_by(ToolCall.id.desc()).limit(100)
    ).all()
    return render(request, "tool_log.html", b=b, items=items)
