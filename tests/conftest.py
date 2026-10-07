import os
import tempfile
from datetime import datetime

# Настройките се четат при import на app – затова env се задава преди това.
_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    ADMIN_PASSWORD="test-pass",
    SECRET_KEY="test-secret-key",
    TOOL_SECRET="test-tool-secret",
    PANEL_BUSINESS_SLUG="demo",
    SEED_DEMO="true",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import booking  # noqa: E402
from app.services.seed import seed_demo  # noqa: E402

# Сряда, 7 октомври 2026, 10:00 – всички тестове смятат спрямо този момент.
FIXED_NOW = datetime(2026, 10, 7, 10, 0)
TOOL_HEADERS = {"X-Tool-Secret": "test-tool-secret"}


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    monkeypatch.setattr(booking, "now_local", lambda tz: FIXED_NOW)
    app_db.Base.metadata.drop_all(app_db.engine)
    app_db.init_db()
    with app_db.SessionLocal() as s:
        seed_demo(s)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tool(client):
    def call(tool_name: str, /, **body):
        r = client.post(f"/api/b/demo/tools/{tool_name}", json=body, headers=TOOL_HEADERS)
        assert r.status_code == 200, r.text
        return r.json()

    return call


@pytest.fixture
def panel(client):
    r = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert r.status_code == 303
    return client
