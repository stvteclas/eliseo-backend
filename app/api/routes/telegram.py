"""Conector Telegram: estado y desconexión (el login es por voz)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import telegram as telegram_service

router = APIRouter(prefix="/connectors/telegram", tags=["telegram"])


@router.get("/status")
def telegram_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "configured": telegram_service.configured(),
        "connected": telegram_service.is_connected(db, current_user.id),
        "message": telegram_service.status_text(db, current_user.id),
    }


@router.delete("")
def telegram_disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = telegram_service.disconnect(db, current_user.id)
    return {"ok": True, "message": msg}
