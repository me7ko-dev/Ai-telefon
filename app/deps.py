import secrets

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Business
from app.services.seed import create_business


class LoginRequired(Exception):
    pass


def require_login(request: Request) -> None:
    if not request.session.get("logged_in"):
        raise LoginRequired


def panel_business(db: Session = Depends(get_db)) -> Business:
    """Фирмата, която панелът управлява. В етап 4 ще се определя от акаунта на потребителя."""
    slug = get_settings().panel_business_slug
    b = db.scalar(select(Business).where(Business.slug == slug))
    if b is None:
        b = create_business(db, slug=slug, name="Моята фирма")
        db.commit()
    return b


def tool_business(slug: str, db: Session = Depends(get_db)) -> Business:
    b = db.scalar(select(Business).where(Business.slug == slug))
    if b is None:
        raise HTTPException(404, detail={"ok": False, "error": "unknown_business", "message": "Непозната фирма."})
    return b


def verify_tool_secret(x_tool_secret: str | None = Header(default=None)) -> None:
    expected = get_settings().tool_secret
    if not x_tool_secret or not secrets.compare_digest(x_tool_secret.encode(), expected.encode()):
        raise HTTPException(401, detail={"ok": False, "error": "unauthorized", "message": "Невалиден ключ."})
