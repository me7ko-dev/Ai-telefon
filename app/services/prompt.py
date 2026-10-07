"""Генерира системния промпт и първото съобщение на агента от данните на фирмата."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.models import Business
from app.services.textutil import WEEKDAYS, fmt_date, fmt_price, fmt_time

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "prompts"),
    keep_trailing_newline=True,
    autoescape=False,
)


def assistant_label(b: Business) -> str:
    return f"AI асистентът {b.assistant_name}" if b.assistant_name else "AI асистентът"


def _hours_lines(b: Business) -> list[str]:
    by_day = {w.weekday: w for w in b.working_hours}
    lines = []
    for i, day in enumerate(WEEKDAYS):
        w = by_day.get(i)
        if not w or not w.is_open:
            lines.append(f"{day}: почивен ден")
            continue
        text = f"{day}: {fmt_time(w.open_time)} – {fmt_time(w.close_time)}"
        if w.break_start and w.break_end:
            text += f" (почивка {fmt_time(w.break_start)} – {fmt_time(w.break_end)})"
        lines.append(text)
    return lines


def build_system_prompt(b: Business, today=None) -> str:
    days_off = [d for d in b.days_off if today is None or d.date >= today]
    services = [
        {"name": s.name, "duration_min": s.duration_min, "price_text": fmt_price(s.price, b.currency), "description": s.description}
        for s in b.services
        if s.is_active
    ]
    text = _env.get_template("system_prompt_bg.j2").render(
        b=b,
        assistant=assistant_label(b),
        hours=_hours_lines(b),
        days_off=", ".join(fmt_date(d.date) + (f" ({d.note})" if d.note else "") for d in days_off),
        services=services,
        faqs=b.faqs,
    )
    return text.strip() + "\n"


def build_first_message(b: Business) -> str:
    """Казва се дословно в началото на всеки разговор – така агентът винаги съобщава, че е AI."""
    name = f", казвам се {b.assistant_name}" if b.assistant_name else ""
    first_letter = b.name.lstrip("„\"'« ")[:1].lower()
    preposition = "със" if first_letter in ("с", "з") else "с"
    return f"Здравейте! Свързахте се {preposition} {b.name}. Аз съм AI асистент{name}. С какво мога да Ви помогна?"
