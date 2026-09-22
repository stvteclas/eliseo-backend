"""Notas y lista de compras por usuario."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped

from app.core.database import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # "compras", "notas", u otra lista corta
    list_name: Mapped[str] = Column(String, nullable=False, default="compras", index=True)
    text: Mapped[str] = Column(String, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
