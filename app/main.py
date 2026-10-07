import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.deps import LoginRequired
from app.models import Business
from app.routers import auth, panel, tools
from app.routers.tools import log_tool_call
from app.services.seed import seed_demo
from app.web import redirect

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.warn_if_insecure()
    init_db()
    if settings.seed_demo:
        with SessionLocal() as db:
            if seed_demo(db, settings.panel_business_slug):
                logging.getLogger(__name__).info("Създадена е демо фирма „%s“.", settings.panel_business_slug)
    yield


app = FastAPI(title="AI Рецепционист", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key, max_age=30 * 24 * 3600, same_site="lax")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(panel.router)
app.include_router(tools.router)


@app.exception_handler(LoginRequired)
async def _login_required(_request: Request, _exc: LoginRequired):
    return redirect("/login")


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    # Грешките на инструментите са плосък JSON {ok, error, message} – същият формат като успешните отговори.
    if isinstance(exc.detail, dict):
        if exc.status_code == 401:
            _log_rejected_tool_call(request, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
    return await http_exception_handler(request, exc)


_TOOL_PATH = re.compile(r"^/api/b/([^/]+)/tools/([a-z_]+)$")


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
    content = {
        "ok": False,
        "error": "invalid_request",
        "message": f"Липсват или са грешни полета: {', '.join(fields)}." if fields else "Невалидна заявка.",
        "fields": fields,
    }
    _log_rejected_tool_call(request, content, exc.body)
    return JSONResponse(status_code=422, content=content)


def _log_rejected_tool_call(request: Request, response: dict, body: object = None) -> None:
    """Грешно настроен инструмент в ElevenLabs (грешен ключ, липсващи полета) – записваме го в лога на панела."""
    if m := _TOOL_PATH.match(request.url.path):
        with SessionLocal() as db:
            business_id = db.scalar(select(Business.id).where(Business.slug == m.group(1)))
            if business_id:
                log_tool_call(db, business_id, m.group(2), body, response, time.perf_counter())


@app.get("/")
def index():
    return redirect("/panel")


@app.get("/health")
def health():
    return {"ok": True}
