"""Логиката зад инструментите на агента. Всяка функция връща речник с ok и message (на български)."""

import threading
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, Business, Message
from app.services.availability import (
    day_slots,
    end_time,
    match_service,
    nearest_times,
    next_available,
    summarize_times,
)
from app.services.textutil import (
    InputError,
    fmt_date,
    fmt_time,
    normalize_phone,
    now_local,
    parse_date,
    parse_time,
    phone_for_speech,
)

# Проверката „свободно ли е“ и записът стават под ключ, за да няма двоен запис.
# Достатъчно е при един процес (uvicorn без --workers). За няколко процеса – виж README.
_booking_lock = threading.Lock()

_REASONS = {
    "past": "Тази дата е минала.",
    "too_far": "Още не записваме толкова напред.",
    "day_off": "В този ден не работим.",
    "closed": "В този ден от седмицата не работим.",
    "full": "За този ден няма свободни часове.",
}


def check_availability(db: Session, business: Business, service_q: str, date_q: str) -> dict:
    now = now_local(business.timezone)
    today = now.date()
    service = match_service(business.services, service_q)
    day = parse_date(date_q, today)
    slots = day_slots(db, business, service, day, now)

    result = {
        "ok": True,
        "today": today.isoformat(),
        "service": service.name,
        "duration_min": service.duration_min,
        "date": day.isoformat(),
        "date_spoken": fmt_date(day, today),
        "available_times": [fmt_time(t) for t in slots.times],
    }
    if slots.times:
        result["message"] = (
            f"{service.name} ({service.duration_min} мин.), {fmt_date(day, today)} – "
            f"свободни начални часове: {summarize_times(slots.times, business.slot_step_min)}. "
            "Предложи на клиента 2–3 от тях."
        )
        return result

    result["reason"] = slots.reason
    message = _REASONS[slots.reason]
    nxt = next_available(db, business, service, day, now) if slots.reason != "too_far" else None
    if nxt:
        result["next_available_date"] = nxt.day.isoformat()
        result["next_available_times"] = [fmt_time(t) for t in nxt.times]
        message += (
            f" Най-близкият ден със свободни часове е {fmt_date(nxt.day, today)}: "
            f"{summarize_times(nxt.times, business.slot_step_min)}."
        )
    result["message"] = message
    return result


def book_appointment(
    db: Session,
    business: Business,
    name: str,
    phone: str,
    service_q: str,
    date_q: str,
    time_q: str,
    source: str = "agent",
    note: str = "",
) -> dict:
    name = (name or "").strip()
    if not name:
        raise InputError("Липсва име на клиента.")
    phone_n = normalize_phone(phone)
    now = now_local(business.timezone)
    today = now.date()
    service = match_service(business.services, service_q)
    day = parse_date(date_q, today)
    start = parse_time(time_q)

    with _booking_lock:
        existing = db.scalar(
            select(Appointment).where(
                Appointment.business_id == business.id,
                Appointment.phone == phone_n,
                Appointment.date == day,
                Appointment.start_time == start,
                Appointment.service_id == service.id,
                Appointment.status == "booked",
            )
        )
        if existing:  # повторно извикване със същите данни – не правим втори запис
            return _booking_result(existing, today, already=True)

        slots = day_slots(db, business, service, day, now)
        if start not in slots.times:
            reason = _REASONS.get(slots.reason, "Този час не е свободен.") if not slots.times else "Този час не е свободен."
            data = {"ok": False, "error": "not_available", "message": reason}
            if slots.times:
                near = nearest_times(slots.times, start)
                data["alternatives"] = [fmt_time(t) for t in near]
                data["message"] += f" Най-близките свободни часове на {fmt_date(day, today)}: {', '.join(data['alternatives'])}."
            return data

        appt = Appointment(
            business_id=business.id,
            service_id=service.id,
            service_name=service.name,
            customer_name=name,
            phone=phone_n,
            date=day,
            start_time=start,
            end_time=end_time(start, service.duration_min),
            source=source,
            note=note,
        )
        db.add(appt)
        db.commit()
    return _booking_result(appt, today)


def _booking_result(appt: Appointment, today, already: bool = False) -> dict:
    when = f"{fmt_date(appt.date, today)} от {fmt_time(appt.start_time)}"
    prefix = "Този час вече е записан" if already else "Записано"
    return {
        "ok": True,
        "appointment_id": appt.id,
        "service": appt.service_name,
        "date": appt.date.isoformat(),
        "time": fmt_time(appt.start_time),
        "end_time": fmt_time(appt.end_time),
        "name": appt.customer_name,
        "phone": appt.phone,
        "message": f"{prefix}: {appt.service_name}, {when}, на името на {appt.customer_name}, "
        f"телефон {phone_for_speech(appt.phone)}.",
    }


def cancel_appointment(db: Session, business: Business, phone: str, date_q: str, time_q: str | None = None) -> dict:
    phone_n = normalize_phone(phone)
    now = now_local(business.timezone)
    today = now.date()
    day = parse_date(date_q, today)

    q = select(Appointment).where(
        Appointment.business_id == business.id,
        Appointment.phone == phone_n,
        Appointment.date == day,
        Appointment.status == "booked",
    ).order_by(Appointment.start_time)
    found = list(db.scalars(q))
    if time_q:
        wanted = parse_time(time_q)
        found = [a for a in found if a.start_time == wanted]

    if not found:
        return {
            "ok": False,
            "error": "not_found",
            "message": f"Не намерих активен запис на телефон {phone_for_speech(phone_n)} за {fmt_date(day, today)}"
            + (f" в {time_q}" if time_q else "")
            + ". Провери номера и датата с клиента.",
        }
    if len(found) > 1:
        times = [fmt_time(a.start_time) for a in found]
        return {
            "ok": False,
            "error": "multiple",
            "times": times,
            "message": f"На този телефон има {len(found)} записа за {fmt_date(day, today)}: "
            f"{', '.join(f'{fmt_time(a.start_time)} ({a.service_name})' for a in found)}. Попитай кой да отменя.",
        }
    appt = found[0]
    if datetime.combine(appt.date, appt.start_time) < now:
        return {"ok": False, "error": "past", "message": "Този час вече е минал и не може да се отмени."}
    appt.status = "cancelled"
    appt.cancelled_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return {
        "ok": True,
        "appointment_id": appt.id,
        "message": f"Отменено: {appt.service_name}, {fmt_date(appt.date, today)} от {fmt_time(appt.start_time)}, "
        f"на името на {appt.customer_name}.",
    }


def take_message(db: Session, business: Business, name: str, phone: str, text: str) -> dict:
    name, text = (name or "").strip(), (text or "").strip()
    if not text:
        raise InputError("Липсва текст на съобщението.")
    try:
        phone_n = normalize_phone(phone)
    except InputError:
        phone_n = (phone or "").strip()  # съобщението е по-важно от формата на номера
    msg = Message(business_id=business.id, name=name or "Неизвестен", phone=phone_n, text=text)
    db.add(msg)
    db.commit()
    return {
        "ok": True,
        "message_id": msg.id,
        "message": "Съобщението е записано и ще бъде предадено на собственика.",
    }
