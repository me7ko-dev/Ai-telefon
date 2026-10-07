import pytest

from conftest import TOOL_HEADERS

THU = "2026-10-08"  # четвъртък, работен ден с почивка 13–14
SUN = "2026-10-11"  # неделя – почивен ден


# ---------- check_availability ----------

def test_availability_working_day(tool):
    r = tool("check_availability", service="мъжко подстригване", date=THU)
    assert r["ok"] and r["service"] == "Мъжко подстригване"
    times = r["available_times"]
    assert times[0] == "9:00" and times[-1] == "17:30"
    assert "13:00" not in times and "13:30" not in times  # обедна почивка
    assert "от 9:00 до 12:30" in r["message"]


def test_availability_long_service_respects_break_and_close(tool):
    r = tool("check_availability", service="Боядисване", date=THU)  # 90 мин.
    times = r["available_times"]
    assert "11:30" in times and "12:00" not in times  # 12:00 + 90 мин. влиза в почивката
    assert times[-1] == "16:30"


def test_availability_today_respects_min_notice(tool):
    r = tool("check_availability", service="Сешоар", date="днес")  # сега е 10:00, минимум 60 мин.
    assert r["available_times"][0] == "11:00"


def test_availability_closed_day_suggests_next(tool):
    r = tool("check_availability", service="Сешоар", date=SUN)
    assert r["available_times"] == [] and r["reason"] == "closed"
    assert r["next_available_date"] == "2026-10-12"
    assert "понеделник, 12 октомври" in r["message"]


def test_availability_past_date(tool):
    r = tool("check_availability", service="Сешоар", date="2026-10-01")
    assert r["reason"] == "past"


def test_availability_unknown_and_ambiguous_service(tool):
    r = tool("check_availability", service="маникюр", date=THU)
    assert not r["ok"] and "Мъжко подстригване" in r["message"]
    r = tool("check_availability", service="подстригване", date=THU)
    assert not r["ok"] and "няколко" in r["message"]


def test_availability_fuzzy_service(tool):
    assert tool("check_availability", service="мъжко", date=THU)["service"] == "Мъжко подстригване"
    assert tool("check_availability", service="боядисванее", date=THU)["service"] == "Боядисване"


def test_day_off(panel, tool):
    panel.post("/panel/days-off", data={"day": THU, "note": "Ремонт"})
    r = tool("check_availability", service="Сешоар", date=THU)
    assert r["reason"] == "day_off" and r["next_available_date"] == "2026-10-09"


# ---------- book_appointment ----------

def _book(tool, **kw):
    body = dict(name="Иван", phone="0888123456", service="Мъжко подстригване", date=THU, time="10:00")
    body.update(kw)
    return tool("book_appointment", **body)


def test_book_and_slot_disappears(tool):
    r = _book(tool)
    assert r["ok"] and r["phone"] == "+359888123456" and r["end_time"] == "10:30"
    assert "0888 123 456" in r["message"]
    times = tool("check_availability", service="Мъжко подстригване", date=THU)["available_times"]
    assert "10:00" not in times and "10:30" in times


def test_double_booking_rejected_with_alternatives(tool):
    assert _book(tool)["ok"]
    r = _book(tool, name="Петър", phone="0899111222")
    assert not r["ok"] and r["error"] == "not_available"
    assert r["alternatives"] and "10:00" not in r["alternatives"]


def test_same_booking_twice_is_idempotent(tool):
    first, second = _book(tool), _book(tool)
    assert second["ok"] and second["appointment_id"] == first["appointment_id"]


def test_long_appointment_blocks_overlapping_slots(tool):
    assert _book(tool, service="Боядисване", time="9:00")["ok"]  # 9:00–10:30
    times = tool("check_availability", service="Сешоар", date=THU)["available_times"]
    assert {"9:00", "9:30", "10:00"}.isdisjoint(times) and "10:30" in times


def test_capacity_two_allows_parallel_bookings(panel, tool):
    page = panel.get("/panel/business")
    assert page.status_code == 200
    form = _business_form(capacity="2")
    panel.post("/panel/business", data=form)
    assert _book(tool)["ok"]
    assert _book(tool, name="Петър", phone="0899111222")["ok"]
    assert not _book(tool, name="Мария", phone="0877000111")["ok"]


def test_book_outside_hours_or_misaligned(tool):
    assert not _book(tool, time="19:00")["ok"]
    assert not _book(tool, time="13:00")["ok"]  # почивка
    assert not _book(tool, time="10:10")["ok"]  # не е от предлаганите часове


def test_book_invalid_phone(tool):
    r = _book(tool, phone="12")
    assert not r["ok"] and r["error"] == "invalid_input"


# ---------- cancel_appointment ----------

def test_cancel(tool):
    _book(tool)
    r = tool("cancel_appointment", phone="+359 888 123 456", date=THU)
    assert r["ok"] and "Отменено" in r["message"]
    assert "10:00" in tool("check_availability", service="Мъжко подстригване", date=THU)["available_times"]
    assert not tool("cancel_appointment", phone="0888123456", date=THU)["ok"]


def test_cancel_not_found(tool):
    r = tool("cancel_appointment", phone="0888999999", date=THU)
    assert not r["ok"] and r["error"] == "not_found"


def test_cancel_multiple_needs_time(tool):
    _book(tool, time="10:00")
    _book(tool, time="15:00", service="Сешоар")
    r = tool("cancel_appointment", phone="0888123456", date=THU)
    assert not r["ok"] and r["error"] == "multiple" and r["times"] == ["10:00", "15:00"]
    r = tool("cancel_appointment", phone="0888123456", date=THU, time="15:00")
    assert r["ok"] and "Сешоар" in r["message"]


# ---------- take_message ----------

def test_take_message_shows_in_panel(panel, tool):
    r = tool("take_message", name="Мария", phone="0877 000 111", message="Искам да питам за булчинска прическа.")
    assert r["ok"]
    page = panel.get("/panel/messages").text
    assert "булчинска прическа" in page and "0877 000 111" in page


# ---------- сигурност и валидиране ----------

def test_requires_secret(client):
    r = client.post("/api/b/demo/tools/take_message", json={"name": "a", "phone": "0888123456", "message": "x"})
    assert r.status_code == 401 and r.json()["ok"] is False
    r = client.post("/api/b/demo/tools/take_message", json={}, headers={"X-Tool-Secret": "wrong"})
    assert r.status_code == 401


def test_unknown_business(client):
    r = client.post("/api/b/nyama/tools/check_availability", json={"service": "x", "date": THU}, headers=TOOL_HEADERS)
    assert r.status_code == 404 and r.json()["error"] == "unknown_business"


def test_missing_fields(client):
    r = client.post("/api/b/demo/tools/book_appointment", json={"name": "Иван"}, headers=TOOL_HEADERS)
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and "phone" in body["fields"] and "Липсват" in body["message"]


def _business_form(**overrides):
    form = {
        "name": "Салон „Демо“", "currency": "евро", "slot_step_min": "30", "capacity": "1",
        "min_notice_min": "60", "booking_horizon_days": "60",
    }
    for wd in range(6):
        form |= {f"open_{wd}": "on", f"from_{wd}": "09:00", f"to_{wd}": "18:00"}
        if wd < 5:
            form |= {f"bstart_{wd}": "13:00", f"bend_{wd}": "14:00"}
    form |= {"from_6": "09:00", "to_6": "18:00"}
    form.update(overrides)
    return form


# ---------- етап 2: номер на обаждащия се и лог ----------

def test_cancel_with_caller_id(tool):
    _book(tool)
    r = tool("cancel_appointment", phone="0888123456", date=THU, caller_id="+359899999999")
    assert not r["ok"] and r["error"] == "caller_mismatch"
    r = tool("cancel_appointment", phone="0888123456", date=THU, caller_id="+359888123456")
    assert r["ok"]


@pytest.mark.parametrize("caller_id", ["", "{{system__caller_id}}", "anonymous"])
def test_cancel_ignores_missing_caller_id(tool, caller_id):
    _book(tool)
    assert tool("cancel_appointment", phone="0888123456", date=THU, caller_id=caller_id)["ok"]


def test_tool_calls_are_logged(panel, tool, client):
    tool("check_availability", service="Сешоар", date=THU)
    client.post("/api/b/demo/tools/book_appointment", json={"name": "Иван"}, headers=TOOL_HEADERS)
    page = panel.get("/panel/tool-log").text
    assert "check_availability" in page and "book_appointment" in page
    assert "Липсват или са грешни полета" in page


def test_wrong_secret_is_logged(panel, client):
    client.post("/api/b/demo/tools/take_message", json={"name": "a"}, headers={"X-Tool-Secret": "greshen"})
    page = panel.get("/panel/tool-log").text
    assert "take_message" in page and "Невалиден ключ" in page
