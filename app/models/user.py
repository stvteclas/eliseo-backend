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
    # elisse = voz femenina (default); eliseo = voz masculina
    persona: Mapped[str] = Column(String, nullable=False, default="elisse")
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
