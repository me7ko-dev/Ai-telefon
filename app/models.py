"""Таблици. Всяка таблица с данни на фирма има business_id – подготовка за много фирми (етап 4)."""

from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    business_type: Mapped[str] = mapped_column(String(100), default="")  # напр. „фризьорски салон“, „автосервиз“
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    extra_info: Mapped[str] = mapped_column(Text, default="")  # паркинг, плащане и др.
    assistant_name: Mapped[str] = mapped_column(String(100), default="")  # празно = „AI асистент“
    currency: Mapped[str] = mapped_column(String(20), default="евро")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Sofia")

    # Правила за записване – общи за всякакъв бизнес
    slot_step_min: Mapped[int] = mapped_column(Integer, default=30)  # през колко минути се предлагат часове
    capacity: Mapped[int] = mapped_column(Integer, default=1)  # колко клиента едновременно (работни места)
    min_notice_min: Mapped[int] = mapped_column(Integer, default=60)  # най-малко колко минути напред
    booking_horizon_days: Mapped[int] = mapped_column(Integer, default=60)  # най-много колко дни напред

    working_hours: Mapped[list["WorkingHours"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", order_by="WorkingHours.weekday"
    )
    services: Mapped[list["Service"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", order_by="Service.position, Service.id"
    )
    faqs: Mapped[list["Faq"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", order_by="Faq.position, Faq.id"
    )
    days_off: Mapped[list["DayOff"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", order_by="DayOff.date"
    )


class WorkingHours(Base):
    __tablename__ = "working_hours"
    __table_args__ = (UniqueConstraint("business_id", "weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = понеделник … 6 = неделя
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    open_time: Mapped[time] = mapped_column(Time, default=time(9, 0))
    close_time: Mapped[time] = mapped_column(Time, default=time(18, 0))
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    business: Mapped[Business] = relationship(back_populates="working_hours")


class DayOff(Base):
    __tablename__ = "days_off"
    __table_args__ = (UniqueConstraint("business_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(200), default="")

    business: Mapped[Business] = relationship(back_populates="days_off")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    business: Mapped[Business] = relationship(back_populates="services")


class Faq(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    business: Mapped[Business] = relationship(back_populates="faqs")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    service_name: Mapped[str] = mapped_column(String(200))  # копие – остава, дори услугата да се изтрие
    customer_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[str] = mapped_column(String(20), default="booked")  # booked | cancelled
    source: Mapped[str] = mapped_column(String(20), default="agent")  # agent | panel
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentConfig(Base):
    """Връзката на фирмата с нейния ElevenLabs агент (по един ред на фирма)."""

    __tablename__ = "agent_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(100), default="")
    public_base_url: Mapped[str] = mapped_column(String(300), default="")  # празно = PUBLIC_BASE_URL от .env
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True)  # изпращай промпта след всяка промяна
    cancel_only_own_number: Mapped[bool] = mapped_column(Boolean, default=False)  # при реални обаждания

    # Попълват се от синхронизацията
    secret_id: Mapped[str] = mapped_column(String(100), default="")
    secret_fingerprint: Mapped[str] = mapped_column(String(32), default="")
    tool_ids: Mapped[str] = mapped_column(Text, default="{}")  # JSON {име на инструмент: id в ElevenLabs}
    tools_url: Mapped[str] = mapped_column(String(300), default="")  # адресът, с който са създадени инструментите
    pushed_prompt_hash: Mapped[str] = mapped_column(String(64), default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_sync_message: Mapped[str] = mapped_column(Text, default="")


class ToolCall(Base):
    """Лог на всяко извикване на инструмент – за отстраняване на проблеми при тест с глас."""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(50))
    ok: Mapped[bool] = mapped_column(Boolean)
    request_json: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
