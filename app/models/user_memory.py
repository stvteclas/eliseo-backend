"""Memoria personal durable por usuario."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped

from app.core.database import Base


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Clave opcional para upsert (ej. "pareja", "trabajo").
    key: Mapped[str | None] = Column(String(64), nullable=True, index=True)
    fact: Mapped[str] = Column(Text, nullable=False)
    updated_at: Mapped[datetime] = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
