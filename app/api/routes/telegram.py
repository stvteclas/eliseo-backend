"""Conector Telegram: estado, desconexión y poll de mensajes nuevos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import prefs as prefs_service
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


@router.get("/updates")
def telegram_updates(
    since: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Poll de mensajes nuevos en Telegram.
    Sin `since`: inicializa cursor (ahora) sin devolver historial.
    Con `since`: mensajes entrantes posteriores a ese instante.
    Respeta modo silencio / reunión (no avisa).
    """
    if bool(getattr(current_user, "quiet_mode", False)) or prefs_service.is_meeting_mode(
        current_user
    ):
        return {"messages": [], "cursor": since, "connected": telegram_service.is_connected(db, current_user.id), "suppressed": True}

    if not telegram_service.is_connected(db, current_user.id):
        return {"messages": [], "cursor": None, "connected": False}

    return telegram_service.poll_incoming_messages(db, current_user.id, since_iso=since)


@router.delete("")
def telegram_disconnect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = telegram_service.disconnect(db, current_user.id)
    return {"ok": True, "message": msg}
