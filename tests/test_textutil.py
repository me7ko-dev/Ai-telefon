from datetime import date, time

import pytest

from app.services.textutil import InputError, fmt_date, normalize_phone, parse_date, parse_time

TODAY = date(2026, 10, 7)  # сряда


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-09", date(2026, 10, 9)),
        ("9.10.2026", date(2026, 10, 9)),
        ("09/10", date(2026, 10, 9)),
        ("5.01", date(2027, 1, 5)),  # минала дата без година → следващата година
        ("днес", TODAY),
        ("утре", date(2026, 10, 8)),
        ("вдругиден", date(2026, 10, 9)),
        ("петък", date(2026, 10, 9)),
        ("в понеделник", date(2026, 10, 12)),
        ("сряда", TODAY),
    ],
)
def test_parse_date(value, expected):
    assert parse_date(value, TODAY) == expected


@pytest.mark.parametrize("value", ["", "някога", "2026-02-30", "32.01"])
def test_parse_date_invalid(value):
    with pytest.raises(InputError):
        parse_date(value, TODAY)


@pytest.mark.parametrize(
    "value, expected",
    [("10:30", time(10, 30)), ("9", time(9)), ("14.15", time(14, 15)), ("11 ч.", time(11)), ("08:00", time(8))],
)
def test_parse_time(value, expected):
    assert parse_time(value) == expected


@pytest.mark.parametrize("value", ["25:00", "10:75", "сутринта"])
def test_parse_time_invalid(value):
    with pytest.raises(InputError):
        parse_time(value)


@pytest.mark.parametrize(
    "value",
    ["0888 123 456", "+359 888 123 456", "00359888123456", "359888123456", "888123456", "(0888) 12-34-56"],
)
def test_normalize_phone_bg(value):
    assert normalize_phone(value) == "+359888123456"


def test_normalize_phone_invalid():
    with pytest.raises(InputError):
        normalize_phone("123")


def test_fmt_date():
    assert fmt_date(date(2026, 10, 8)) == "четвъртък, 8 октомври"
    assert fmt_date(date(2026, 10, 8), TODAY).startswith("утре")
