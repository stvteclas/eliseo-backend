"""Digest HTTP: ritual matutino para la app."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import digest as digest_service
from app.services import prefs as prefs_service

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/morning")
def morning_digest(
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if bool(getattr(current_user, "quiet_mode", False)) or prefs_service.is_meeting_mode(
        current_user
    ):
        return {"text": "", "suppressed": True}
    text = digest_service.morning_ritual(
        current_user.id, db, latitude, longitude, work_destination=""
    )
    return {"text": text, "morning_hour": int(getattr(current_user, "morning_hour", 8) or 8)}
