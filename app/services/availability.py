"""Смятане на свободни часове. Работи за всякакъв бизнес: стъпка, капацитет, почивки и т.н. идват от настройките."""

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, Business, DayOff, Service, WorkingHours
from app.services.textutil import InputError, fmt_time


def _m(t: time) -> int:
    return t.hour * 60 + t.minute


def _t(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


# ---------- Намиране на услуга по свободен текст ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def match_service(services: list[Service], query: str) -> Service:
    """Намира услуга по казаното от клиента. При неяснота хвърля InputError със списък на услугите."""
    active = [s for s in services if s.is_active]
    names = ", ".join(s.name for s in active)
    q = _norm(query or "")
    if not q:
        raise InputError(f"Не е посочена услуга. Възможни услуги: {names}.")

    exact = [s for s in active if _norm(s.name) == q]
    if len(exact) == 1:
        return exact[0]

    contains = [s for s in active if q in _norm(s.name) or _norm(s.name) in q]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        options = ", ".join(s.name for s in contains)
        raise InputError(f"Има няколко подобни услуги: {options}. Попитай клиента коя точно.")

    # Съвпадение по думи / близко изписване („подстрижка“ ≈ „подстригване“)
    q_words = q.split()
    scored = []
    for s in active:
        words = _norm(s.name).split()
        score = max(
            (difflib.SequenceMatcher(None, qw, w).ratio() for qw in q_words for w in words),
            default=0,
        )
        score = max(score, difflib.SequenceMatcher(None, q, _norm(s.name)).ratio())
        scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
        return scored[0][1]
    raise InputError(f"Не намерих услуга „{query}“. Възможни услуги: {names}.")


# ---------- Свободни часове ----------

@dataclass
class DaySlots:
    day: date
    times: list[time] = field(default_factory=list)
    reason: str | None = None  # closed | day_off | past | too_far | full


def _working_windows(wh: WorkingHours) -> list[tuple[int, int]]:
    start, end = _m(wh.open_time), _m(wh.close_time)
    if wh.break_start and wh.break_end and start < _m(wh.break_start) < _m(wh.break_end) < end:
        return [(start, _m(wh.break_start)), (_m(wh.break_end), end)]
    return [(start, end)]


def _max_overlap(busy: list[tuple[int, int]], start: int, end: int) -> int:
    """Най-много колко записа се застъпват едновременно в интервала [start, end)."""
    points = [start] + [b_start for b_start, _ in busy if start <= b_start < end]
    return max((sum(1 for b_start, b_end in busy if b_start <= p < b_end) for p in points), default=0)


def _busy_intervals(db: Session, business_id: int, day: date, exclude_id: int | None = None) -> list[tuple[int, int]]:
    q = select(Appointment).where(
        Appointment.business_id == business_id,
        Appointment.date == day,
        Appointment.status == "booked",
    )
    return [(_m(a.start_time), _m(a.end_time)) for a in db.scalars(q) if a.id != exclude_id]


def day_slots(db: Session, business: Business, service: Service, day: date, now: datetime) -> DaySlots:
    today = now.date()
    if day < today:
        return DaySlots(day, reason="past")
    if day > today + timedelta(days=business.booking_horizon_days):
        return DaySlots(day, reason="too_far")
    if db.scalar(select(DayOff.id).where(DayOff.business_id == business.id, DayOff.date == day)):
        return DaySlots(day, reason="day_off")
    wh = next((w for w in business.working_hours if w.weekday == day.weekday()), None)
    if wh is None or not wh.is_open:
        return DaySlots(day, reason="closed")

    step = max(5, business.slot_step_min)
    duration = service.duration_min
    earliest = _m(now.time()) + business.min_notice_min if day == today else 0
    busy = _busy_intervals(db, business.id, day)

    times = []
    for w_start, w_end in _working_windows(wh):
        start = w_start
        while start + duration <= w_end:
            if start >= earliest and _max_overlap(busy, start, start + duration) < max(1, business.capacity):
                times.append(_t(start))
            start += step
    return DaySlots(day, times=times, reason=None if times else "full")


def next_available(db: Session, business: Business, service: Service, after: date, now: datetime, max_days: int = 21) -> DaySlots | None:
    for i in range(1, max_days + 1):
        slots = day_slots(db, business, service, after + timedelta(days=i), now)
        if slots.reason == "too_far":
            return None
        if slots.times:
            return slots
    return None


def summarize_times(times: list[time], step: int) -> str:
    """Свива списъка до диапазони за четене на глас: „9:00–11:30 и 14:00–16:00“."""
    if not times:
        return ""
    mins = [_m(t) for t in times]
    ranges = []
    start = prev = mins[0]
    for m in mins[1:]:
        if m - prev != step:
            ranges.append((start, prev))
            start = m
        prev = m
    ranges.append((start, prev))
    parts = [fmt_time(_t(a)) if a == b else f"от {fmt_time(_t(a))} до {fmt_time(_t(b))}" for a, b in ranges]
    text = ", ".join(parts[:-1]) + " и " + parts[-1] if len(parts) > 1 else parts[0]
    if any(a != b for a, b in ranges):
        text += f" (на всеки {step} минути)"
    return text


def nearest_times(times: list[time], wanted: time, n: int = 3) -> list[time]:
    return sorted(sorted(times, key=lambda t: abs(_m(t) - _m(wanted)))[:n])


def end_time(start: time, duration_min: int) -> time:
    return _t(_m(start) + duration_min)
