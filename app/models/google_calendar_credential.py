"""
Refresh token de Google Calendar por usuario (HU-T11), cifrado con Fernet
(ver app/core/crypto.py). Un usuario, un refresh token.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped

from app.core.database import Base


class GoogleCalendarCredential(Base):
    __tablename__ = "google_calendar_credentials"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    refresh_token_encrypted: Mapped[str] = Column(String, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
