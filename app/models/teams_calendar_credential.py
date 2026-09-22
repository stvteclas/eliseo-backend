"""
Credenciales de Microsoft Teams/Outlook Calendar por usuario y cuenta
(HU-T22), cifradas con Fernet (ver app/core/crypto.py). Nace ya con
account_label (HU-T21): un usuario puede conectar varias cuentas de
organizaciones distintas (ej. "banco", "agencia", "personal").
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.database import Base


class TeamsCalendarCredential(Base):
    __tablename__ = "teams_calendar_credentials"
    __table_args__ = (UniqueConstraint("user_id", "account_label", name="uq_teams_calendar_credentials_user_account"),)

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_label: Mapped[str] = Column(String, nullable=False, default="default")
    access_token_encrypted: Mapped[str] = Column(String, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = Column(String, nullable=True)
    expires_at: Mapped[datetime | None] = Column(DateTime, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
