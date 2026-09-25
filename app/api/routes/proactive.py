"""Endpoint de hints proactivos (un aviso útil por poll)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import proactive as proactive_service

router = APIRouter(prefix="/proactive", tags=["proactive"])


@router.get("/hints")
def proactive_hints(
    announced: str | None = Query(
        default=None,
        description="IDs ya anunciados separados por coma (eventos/hábitos).",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ids = [p.strip() for p in (announced or "").split(",") if p.strip()]
    return proactive_service.build_hint(db, current_user, announced_event_ids=ids)
