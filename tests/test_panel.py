from test_tools import THU, _business_form


def test_login_required(client):
    r = client.get("/panel", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_wrong_password(client):
    r = client.post("/login", data={"password": "greshna"})
    assert "Грешна парола" in r.text


def test_all_pages_render(panel):
    for url in ["/panel", "/panel/business", "/panel/services", "/panel/faqs", "/panel/appointments",
                "/panel/appointments?show=past", "/panel/appointments?show=cancelled", "/panel/messages", "/panel/prompt"]:
        r = panel.get(url)
        assert r.status_code == 200, url


def test_add_service_updates_prompt(panel):
    panel.post("/panel/services", data={"name": "Маникюр", "duration_min": "45", "price": "25,50"})
    assert "Маникюр" in panel.get("/panel/services").text
    prompt = panel.get("/panel/prompt").text
    assert "Маникюр – 45 мин., 25,5 евро" in prompt


def test_faq_in_prompt(panel):
    panel.post("/panel/faqs", data={"question": "Работите ли на празници?", "answer": "Не."})
    assert "Работите ли на празници?" in panel.get("/panel/prompt").text


def test_business_hours_saved(panel):
    form = _business_form(name="Сервиз „Тест“", business_type="автосервиз")
    form.pop("open_5")  # събота – почивен
    panel.post("/panel/business", data=form)
    prompt = panel.get("/panel/prompt").text
    assert "Сервиз „Тест“ – автосервиз" in prompt or "Сервиз „Тест“" in prompt
    assert "събота: почивен ден" in prompt
    assert "AI асистент" in prompt


def test_manual_booking_and_cancel(panel):
    r = panel.post("/panel/appointments", data={
        "service": "Сешоар", "day": THU, "start": "11:00", "name": "Ани", "phone": "0888555666"})
    assert "Записано" in r.text
    page = panel.get("/panel/appointments").text
    assert "Ани" in page and "ръчно" in page


def test_first_message_says_ai(panel):
    assert "Аз съм AI асистент" in panel.get("/panel/prompt").text


def test_first_message_preposition():
    from types import SimpleNamespace

    from app.services.prompt import build_first_message

    assert "се със Салон" in build_first_message(SimpleNamespace(name="Салон „Демо“", assistant_name=""))
    assert "се с Автосервиз" in build_first_message(SimpleNamespace(name="Автосервиз Иванов", assistant_name="Ани"))
    assert "казвам се Ани" in build_first_message(SimpleNamespace(name="Автосервиз Иванов", assistant_name="Ани"))
