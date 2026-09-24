"""Sesión de Telegram (Telethon StringSession) cifrada por usuario."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.database import Base


class TelegramCredential(Base):
    __tablename__ = "telegram_credentials"
    __table_args__ = (UniqueConstraint("user_id", "account_label", name="uq_telegram_credentials_user_account"),)

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_label: Mapped[str] = Column(String, nullable=False, default="default")
    phone: Mapped[str | None] = Column(String, nullable=True)
    # StringSession de Telethon cifrada (cuando login_stage == "connected")
    session_encrypted: Mapped[str | None] = Column(Text, nullable=True)
    # Durante el login: sesión temporal + hash del código
    pending_session_encrypted: Mapped[str | None] = Column(Text, nullable=True)
    phone_code_hash: Mapped[str | None] = Column(Text, nullable=True)
    # none | code | password | connected
    login_stage: Mapped[str] = Column(String, nullable=False, default="none")
    telegram_user_id: Mapped[str | None] = Column(String, nullable=True)
    display_name: Mapped[str | None] = Column(String, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
