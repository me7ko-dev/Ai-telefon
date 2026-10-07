"""Дати, часове и телефони на български – разчитане и форматиране."""

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
MONTHS = [
    "януари", "февруари", "март", "април", "май", "юни",
    "юли", "август", "септември", "октомври", "ноември", "декември",
]

# Думи, които агентът понякога подава вместо дата.
_RELATIVE_DAYS = {"днес": 0, "today": 0, "утре": 1, "tomorrow": 1, "вдругиден": 2}
_WEEKDAY_ALIASES = {
    "понеделник": 0, "вторник": 1, "сряда": 2, "четвъртък": 3, "петък": 4, "събота": 5, "неделя": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}


class InputError(ValueError):
    """Грешка във входните данни – съобщението е на български и може да се прочете на клиента."""


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)


def utc_to_local(dt: datetime | None, tz: str) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def parse_date(value: str, today: date) -> date:
    s = (value or "").strip().lower().rstrip(".")
    if not s:
        raise InputError("Липсва дата.")
    s = re.sub(r"^(в|във|на)\s+", "", s)
    if s in _RELATIVE_DAYS:
        return today + timedelta(days=_RELATIVE_DAYS[s])
    if s in _WEEKDAY_ALIASES:
        delta = (_WEEKDAY_ALIASES[s] - today.weekday()) % 7
        return today + timedelta(days=delta)
    year_given = True
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", s)
        if not m:
            raise InputError(f"Не разбрах датата „{value}“. Използвай формат ГГГГ-ММ-ДД.")
        d, mo = int(m.group(1)), int(m.group(2))
        year_given = m.group(3) is not None
        y = int(m.group(3)) if year_given else today.year
        if y < 100:
            y += 2000
    try:
        result = date(y, mo, d)
        if not year_given and result < today:
            result = date(y + 1, mo, d)  # „5.01“, казано през декември = следващата година
    except ValueError:
        raise InputError(f"Датата „{value}“ не съществува.") from None
    return result


def parse_time(value: str) -> time:
    s = (value or "").strip().lower()
    s = re.sub(r"\s*(ч\.?|часа|h)$", "", s)
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", s)
    if not m:
        raise InputError(f"Не разбрах часа „{value}“. Използвай формат ЧЧ:ММ.")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise InputError(f"Часът „{value}“ не е валиден.")
    return time(h, mi)


def fmt_time(t: time) -> str:
    return f"{t.hour}:{t.minute:02d}"


def fmt_date(d: date, today: date | None = None) -> str:
    """„четвъртък, 8 октомври“ (+ „днес“/„утре“, ако е подаден today)."""
    text = f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"
    if today is not None:
        if d == today:
            return f"днес ({text})"
        if d == today + timedelta(days=1):
            return f"утре ({text})"
    return text


def fmt_price(price: float | None, currency: str) -> str:
    if price is None:
        return "по договаряне"
    amount = f"{price:.2f}".rstrip("0").rstrip(".")
    return f"{amount.replace('.', ',')} {currency}"


def normalize_phone(value: str) -> str:
    """Уеднаквява телефонни номера: 0888 123 456 → +359888123456."""
    raw = (value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        result = "+" + digits
    elif digits.startswith("00"):
        result = "+" + digits[2:]
    elif digits.startswith("359") and len(digits) == 12:
        result = "+" + digits
    elif digits.startswith("0") and len(digits) == 10:
        result = "+359" + digits[1:]
    elif len(digits) == 9 and digits[0] in "89":
        result = "+359" + digits
    else:
        result = "+" + digits if len(digits) >= 10 else digits
    if not 8 <= len(result.lstrip("+")) <= 15:
        raise InputError(f"Телефонният номер „{value}“ не изглежда валиден.")
    return result


def phone_for_speech(phone: str) -> str:
    """+359888123456 → 0888 123 456 (както се казва на глас)."""
    if phone.startswith("+359") and len(phone) == 13:
        local = "0" + phone[4:]
        return f"{local[:4]} {local[4:7]} {local[7:]}"
    return phone
