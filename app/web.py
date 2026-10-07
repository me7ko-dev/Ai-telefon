"""Шаблони и помощни функции за панела."""

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.textutil import WEEKDAYS, fmt_date, fmt_price, fmt_time, phone_for_speech, utc_to_local

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters.update(
    hm=lambda t: fmt_time(t) if t else "",
    hm_input=lambda t: t.strftime("%H:%M") if t else "",
    bgdate=fmt_date,
    price=fmt_price,
    phone=phone_for_speech,
    local=lambda dt, tz="Europe/Sofia": utc_to_local(dt, tz).strftime("%d.%m.%Y %H:%M") if dt else "",
)
templates.env.globals["WEEKDAYS"] = WEEKDAYS


def flash(request: Request, text: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"text": text, "kind": kind})


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)
