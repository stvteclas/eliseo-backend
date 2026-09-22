"""
Modelo de usuario. Todavía mínimo a propósito — el manifiesto de
conectores, el consentimiento por servicio, etc. (HU-T15) se agregan
como tablas separadas más adelante, relacionadas a este user_id.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Mapped

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    email: Mapped[str] = Column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = Column(String, nullable=False)
    # eliseo = voz masculina latina (default); elisse = voz femenina
    persona: Mapped[str] = Column(String, nullable=False, default="eliseo")
    # Modo traductor bidireccional: códigos ISO (es, ru, en...). Null = apagado.
    translator_lang_a: Mapped[str | None] = Column(String, nullable=True, default=None)
    translator_lang_b: Mapped[str | None] = Column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
