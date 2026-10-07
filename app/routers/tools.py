"""Webhook инструментите, които ElevenLabs агентът вика.

Адрес: POST /api/b/{slug}/tools/<инструмент>, заглавка X-Tool-Secret.
Грешки по същество (зает час, непозната услуга…) връщат 200 с ok=false и message,
за да може агентът да прочете обяснението и да продължи разговора.
Всяко извикване се записва в лога (таблица tool_calls), видим в панела.
"""

import json
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import tool_business, verify_tool_secret
from app.models import Business, ToolCall
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
    caller_id: str | None = Field(default=None, description="Номерът на обаждащия се (попълва се от ElevenLabs)")


class TakeMessageIn(BaseModel):
    name: str
    phone: str
    message: str


def log_tool_call(db: Session, business_id: int, tool: str, request: object, response: dict, started: float) -> None:
    db.add(
        ToolCall(
            business_id=business_id,
            tool=tool,
            ok=bool(response.get("ok")),
            request_json=json.dumps(request, ensure_ascii=False, default=str),
            response_json=json.dumps(response, ensure_ascii=False, default=str),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    db.commit()


def _run(db: Session, b: Business, tool: str, body: BaseModel, fn: Callable[[], dict]) -> dict:
    started = time.perf_counter()
    try:
        result = fn()
    except InputError as e:
        result = {"ok": False, "error": "invalid_input", "message": str(e)}
    log_tool_call(db, b.id, tool, body.model_dump(exclude_none=True), result, started)
    return result


@router.post("/check_availability")
def check_availability(body: CheckAvailabilityIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(db, b, "check_availability", body, lambda: booking.check_availability(db, b, body.service, body.date))


@router.post("/book_appointment")
def book_appointment(body: BookAppointmentIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(
        db, b, "book_appointment", body,
        lambda: booking.book_appointment(db, b, body.name, body.phone, body.service, body.date, body.time),
    )


@router.post("/cancel_appointment")
def cancel_appointment(body: CancelAppointmentIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(
        db, b, "cancel_appointment", body,
        lambda: booking.cancel_appointment(db, b, body.phone, body.date, body.time, body.caller_id),
    )


@router.post("/take_message")
def take_message(body: TakeMessageIn, b: Business = Depends(tool_business), db: Session = Depends(get_db)):
    return _run(db, b, "take_message", body, lambda: booking.take_message(db, b, body.name, body.phone, body.message))
