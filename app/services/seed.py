"""Създаване на фирма с работно време по подразбиране + демо данни за тест."""

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business, Faq, Service, WorkingHours


def create_business(db: Session, slug: str, name: str, **fields) -> Business:
    """Нова фирма с работно време пон–пет 9–18, съб 10–14, нед почивен. Ползва се и за нови акаунти."""
    b = Business(slug=slug, name=name, **fields)
    for wd in range(7):
        if wd < 5:
            b.working_hours.append(WorkingHours(weekday=wd, is_open=True, open_time=time(9), close_time=time(18)))
        elif wd == 5:
            b.working_hours.append(WorkingHours(weekday=wd, is_open=True, open_time=time(10), close_time=time(14)))
        else:
            b.working_hours.append(WorkingHours(weekday=wd, is_open=False, open_time=time(9), close_time=time(18)))
    db.add(b)
    return b


def seed_demo(db: Session, slug: str = "demo") -> Business | None:
    if db.scalar(select(Business.id).where(Business.slug == slug)):
        return None
    b = create_business(
        db,
        slug=slug,
        name="Салон „Демо“",
        business_type="фризьорски салон",
        description="Малък квартален фризьорски салон за дами и господа.",
        address="гр. София, ул. „Примерна“ 1",
        extra_info="Плащане в брой или с карта. Има паркинг пред салона.",
        assistant_name="Мира",
    )
    for wd in range(5):  # обедна почивка в делнични дни
        b.working_hours[wd].break_start = time(13)
        b.working_hours[wd].break_end = time(14)
    b.services = [
        Service(name="Мъжко подстригване", duration_min=30, price=20, position=1),
        Service(name="Дамско подстригване", duration_min=60, price=35, position=2),
        Service(name="Боядисване", duration_min=90, price=60, description="Цената е без боята за дълга коса.", position=3),
        Service(name="Сешоар", duration_min=30, price=15, position=4),
    ]
    b.faqs = [
        Faq(question="Може ли без предварително записване?", answer="Да, ако има свободен час, но препоръчваме да се запишете.", position=1),
        Faq(question="Има ли паркинг?", answer="Да, пред салона има безплатен паркинг.", position=2),
        Faq(question="Може ли плащане с карта?", answer="Да, приемаме карти.", position=3),
    ]
    db.commit()
    return b
