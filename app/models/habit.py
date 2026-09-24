"""Hábitos diarios por usuario (agua, pastilla, etc.)."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped

from app.core.database import Base


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = Column(String, nullable=False, index=True)  # clave normalizada
    label: Mapped[str] = Column(String, nullable=False)
    last_done: Mapped[str | None] = Column(String, nullable=True)  # YYYY-MM-DD
    streak: Mapped[int] = Column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
