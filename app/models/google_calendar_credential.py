"""
Refresh token de Google Calendar por usuario y cuenta (HU-T11, multi-cuenta
desde HU-T21), cifrado con Fernet (ver app/core/crypto.py). Un usuario puede
tener más de una cuenta conectada, distinguidas por account_label.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.database import Base


class GoogleCalendarCredential(Base):
    __tablename__ = "google_calendar_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "account_label", name="uq_google_calendar_credentials_user_account"),
    )

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_label: Mapped[str] = Column(String, nullable=False, default="default")
    refresh_token_encrypted: Mapped[str] = Column(String, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
