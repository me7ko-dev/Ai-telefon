"""Webhook инструментите, които ElevenLabs агентът вика.

Адрес: POST /api/b/{slug}/tools/<инструмент>, заглавка X-Tool-Secret.
Грешки по същество (зает час, непозната услуга…) връщат 200 с ok=false и message,
за да може агентът да прочете обяснението и да продължи разговора.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import tool_business, verify_tool_secret
from app.models import Business
from app.services import booking
from app.services.textutil import InputError

router = APIRouter(prefix="/api/b/{slug}/tools", tags=["tools"], dependencies=[Depends(verify_tool_secret)])


class CheckAvailabilityIn(BaseModel):
    service: str = Field(description="Услугата, както я е казал клиентът")
    date: str = Field(description="Дата във формат ГГГГ-ММ-ДД")


class BookAppointmentIn(BaseModel):
    name: str
    phone: str
    service: str
    date: str = Field(description="ГГГГ-ММ-ДД")
    time: str = Field(description="ЧЧ:ММ")


class CancelAppointmentIn(BaseModel):
    phone: str
    date: str = Field(description="ГГГГ-ММ-ДД")
    time: str | None = Field(default=None, description="ЧЧ:ММ – само ако има няколко записа в деня")


class TakeMessageIn(BaseModel):
    name: str
    phone: str
    message: str


def _run(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except InputError as e:
        return {"ok": False, "error": "invalid_input", "message": str(e)}


@router.post("/check_availability")
def check_availability(body: CheckAvailabilityIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(lambda: booking.check_availability(db, b, body.service, body.date))


@router.post("/book_appointment")
def book_appointment(body: BookAppointmentIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(lambda: booking.book_appointment(db, b, body.name, body.phone, body.service, body.date, body.time))


@router.post("/cancel_appointment")
def cancel_appointment(body: CancelAppointmentIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(lambda: booking.cancel_appointment(db, b, body.phone, body.date, body.time))


@router.post("/take_message")
def take_message(body: TakeMessageIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(lambda: booking.take_message(db, b, body.name, body.phone, body.message))
