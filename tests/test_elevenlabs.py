"""Синхронизация с ElevenLabs срещу фалшив сървър (httpx.MockTransport) – без реални заявки."""

import json

import httpx
import pytest

from app import db as app_db
from app.models import AgentConfig, Business
from app.services import elevenlabs as el

PUBLIC = "https://test-tunnel.trycloudflare.com"


class FakeElevenLabs:
    def __init__(self, agent_tool_ids=None, language="bg"):
        self.requests: list[tuple[str, str, dict | None]] = []
        self.tools: dict[str, dict] = {}
        self.agent = {
            "agent_id": "agent_123",
            "name": "Тест",
            "conversation_config": {
                "agent": {"language": language, "prompt": {"prompt": "стар", "tool_ids": agent_tool_ids or []}},
                "tts": {"model_id": "eleven_flash_v2_5"},
            },
        }
        self.secret_count = 0
        self.tool_counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path, method = request.url.path, request.method
        self.requests.append((method, path, body))
        assert request.headers["xi-api-key"] == "test-key"
        if method == "POST" and path == "/v1/convai/secrets":
            self.secret_count += 1
            return httpx.Response(200, json={"type": "stored", "secret_id": f"sec_{self.secret_count}", "name": body["name"]})
        if method == "POST" and path == "/v1/convai/tools":
            self.tool_counter += 1
            tool_id = f"tool_{self.tool_counter}"
            self.tools[tool_id] = body["tool_config"]
            return httpx.Response(200, json={"id": tool_id, "tool_config": body["tool_config"]})
        if method == "PATCH" and path.startswith("/v1/convai/tools/"):
            tool_id = path.rsplit("/", 1)[1]
            if tool_id not in self.tools:
                return httpx.Response(404, json={"detail": "not found"})
            self.tools[tool_id] = body["tool_config"]
            return httpx.Response(200, json={"id": tool_id, "tool_config": body["tool_config"]})
        if path == "/v1/convai/agents/agent_123":
            if method == "GET":
                return httpx.Response(200, json=self.agent)
            if method == "PATCH":
                a = self.agent["conversation_config"]["agent"]
                new = body["conversation_config"]["agent"]
                a["first_message"] = new["first_message"]
                a["prompt"].update(new["prompt"])
                return httpx.Response(200, json=self.agent)
        return httpx.Response(404, json={"detail": "not found"})

    def client(self):
        return el.ElevenLabsClient("test-key", "https://api.elevenlabs.test", transport=httpx.MockTransport(self.handler))


def _setup(agent_id="agent_123", public=PUBLIC, **kw):
    with app_db.SessionLocal() as db:
        b = db.query(Business).filter_by(slug="demo").one()
        cfg = el.get_config(db, b)
        cfg.agent_id, cfg.public_base_url = agent_id, public
        for k, v in kw.items():
            setattr(cfg, k, v)
        db.commit()
        return b.id


def _sync(fake):
    with app_db.SessionLocal() as db:
        b = db.query(Business).filter_by(slug="demo").one()
        return el.sync_all(db, b, fake.client())


def _cfg():
    with app_db.SessionLocal() as db:
        return db.query(AgentConfig).one()


def test_full_sync_creates_secret_tools_and_updates_agent():
    _setup()
    fake = FakeElevenLabs(agent_tool_ids=["tool_owner_own"])
    msg = _sync(fake)
    assert "обновен" in msg
    assert fake.secret_count == 1
    assert {t["name"] for t in fake.tools.values()} == {
        "check_availability", "book_appointment", "cancel_appointment", "take_message"}
    book = next(t for t in fake.tools.values() if t["name"] == "book_appointment")
    schema = book["api_schema"]
    assert schema["url"] == f"{PUBLIC}/api/b/demo/tools/book_appointment"
    assert schema["method"] == "POST"
    assert schema["request_headers"] == {"X-Tool-Secret": {"secret_id": "sec_1"}}
    assert set(schema["request_body_schema"]["required"]) == {"name", "phone", "service", "date", "time"}
    assert book["type"] == "webhook"

    a = fake.agent["conversation_config"]["agent"]
    assert "Салон „Демо“" in a["prompt"]["prompt"]
    assert a["prompt"]["timezone"] == "Europe/Sofia"
    assert "AI асистент" in a["first_message"]
    # инструментът, добавен ръчно от собственика, остава
    assert a["prompt"]["tool_ids"][0] == "tool_owner_own" and len(a["prompt"]["tool_ids"]) == 5
    cfg = _cfg()
    assert cfg.last_sync_ok and cfg.pushed_prompt_hash


def test_second_sync_updates_instead_of_duplicating():
    _setup()
    fake = FakeElevenLabs()
    _sync(fake)
    _sync(fake)
    assert fake.secret_count == 1 and len(fake.tools) == 4
    assert fake.agent["conversation_config"]["agent"]["prompt"]["tool_ids"] == ["tool_1", "tool_2", "tool_3", "tool_4"]


def test_deleted_tool_is_recreated():
    _setup()
    fake = FakeElevenLabs()
    _sync(fake)
    del fake.tools["tool_2"]
    _sync(fake)
    assert len(fake.tools) == 4 and "tool_5" in fake.tools


def test_cancel_only_own_number_adds_caller_id_variable():
    _setup(cancel_only_own_number=True)
    fake = FakeElevenLabs()
    _sync(fake)
    cancel = next(t for t in fake.tools.values() if t["name"] == "cancel_appointment")
    props = cancel["api_schema"]["request_body_schema"]["properties"]
    assert props["caller_id"] == {"type": "string", "dynamic_variable": "system__caller_id"}


def test_language_warning():
    _setup()
    assert "Bulgarian" in _sync(FakeElevenLabs(language="en"))


@pytest.mark.parametrize("public", ["http://localhost:8000", "", "http://example.com"])
def test_refuses_unreachable_url(public, monkeypatch):
    monkeypatch.setattr(el.get_settings(), "public_base_url", "http://localhost:8000")
    _setup(public=public)
    fake = FakeElevenLabs()
    with pytest.raises(el.ElevenLabsError, match="Cloudflare"):
        _sync(fake)
    assert fake.requests == [] and _cfg().last_sync_ok is False


def test_unknown_agent():
    _setup(agent_id="agent_404")
    with pytest.raises(el.ElevenLabsError, match="не е намерен"):
        _sync(FakeElevenLabs())


def test_bad_api_key():
    _setup()
    client = el.ElevenLabsClient("x", "https://api.elevenlabs.test",
                                 transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with app_db.SessionLocal() as db:
        b = db.query(Business).filter_by(slug="demo").one()
        with pytest.raises(el.ElevenLabsError, match="API ключа"):
            el.sync_all(db, b, client)


def test_auto_push_after_panel_change(panel, monkeypatch):
    _setup()
    fake = FakeElevenLabs()
    _sync(fake)
    monkeypatch.setattr(el, "make_client", fake.client)
    patches_before = sum(1 for m, p, _ in fake.requests if m == "PATCH" and "agents" in p)
    panel.post("/panel/services", data={"name": "Маникюр", "duration_min": "45", "price": "25"})
    assert "Маникюр" in fake.agent["conversation_config"]["agent"]["prompt"]["prompt"]
    # Без промяна – без нова заявка
    el.auto_push(_cfg().business_id)
    patches_after = sum(1 for m, p, _ in fake.requests if m == "PATCH" and "agents" in p)
    assert patches_after == patches_before + 1


def test_auto_push_respects_setting(panel, monkeypatch):
    _setup()
    fake = FakeElevenLabs()
    _sync(fake)
    with app_db.SessionLocal() as db:
        db.query(AgentConfig).one().auto_sync = False
        db.commit()
    monkeypatch.setattr(el, "make_client", fake.client)
    panel.post("/panel/services", data={"name": "Маникюр", "duration_min": "45", "price": "25"})
    assert "Маникюр" not in fake.agent["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "още не са изпратени" in panel.get("/panel/prompt").text


def test_agent_page_and_settings(panel):
    r = panel.post("/panel/agent", data={"agent_id": " agent_123 ", "public_base_url": PUBLIC + "/", "auto_sync": "on"})
    assert r.status_code == 200
    page = panel.get("/panel/prompt").text
    assert f"{PUBLIC}/api/b/demo/tools/book_appointment" in page and "agent_123" in page
    cfg = _cfg()
    assert cfg.agent_id == "agent_123" and cfg.public_base_url == PUBLIC and not cfg.cancel_only_own_number


def test_sync_button_without_api_key(panel):
    r = panel.post("/panel/agent/sync")
    assert "ELEVENLABS_API_KEY" in r.text
