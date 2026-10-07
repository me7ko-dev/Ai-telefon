import secrets

from fastapi import APIRouter, Form, Request

from app.config import get_settings
from app.web import redirect, render

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, password: str = Form("")):
    if secrets.compare_digest(password.encode(), get_settings().admin_password.encode()):
        request.session["logged_in"] = True
        return redirect("/panel")
    return render(request, "login.html", error="Грешна парола.")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")
