"""Códigos de un solo uso para canjear el login Google por JWT (no van en la URL)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Mapped, Session

from app.core.database import Base

CODE_TTL_MINUTES = 3


class LoginExchangeCode(Base):
    __tablename__ = "login_exchange_codes"

    code: Mapped[str] = Column(String(64), primary_key=True)
    user_id: Mapped[int] = Column(Integer, nullable=False, index=True)
    expires_at: Mapped[datetime] = Column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = Column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


def issue_code(db: Session, user_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    row = LoginExchangeCode(
        code=raw,
        user_id=int(user_id),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES),
    )
    db.add(row)
    db.commit()
    return raw


def consume_code(db: Session, code: str) -> int | None:
    """
    Canjea el código una sola vez. Devuelve user_id o None.
    """
    raw = (code or "").strip()
    if not raw or len(raw) > 80:
        return None
    row = db.query(LoginExchangeCode).filter(LoginExchangeCode.code == raw).first()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if row.used_at is not None:
        return None
    if exp < now:
        return None
    row.used_at = now
    db.add(row)
    db.commit()
    return int(row.user_id)


def purge_expired(db: Session, older_than_hours: int = 24) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, older_than_hours))
    q = db.query(LoginExchangeCode).filter(LoginExchangeCode.created_at < cutoff)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n
