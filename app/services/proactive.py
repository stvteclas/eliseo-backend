"""Hints proactivos: un solo aviso útil por ciclo."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.habit import Habit
from app.models.user import User
from app.services import prefs as prefs_service

ARGENTINA_TZ = timezone(timedelta(hours=-3))


def _short(text: str, limit: int = 140) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def build_hint(
    db: Session,
    user: User,
    *,
    announced_event_ids: list[str] | None = None,
) -> dict:
    """
    Devuelve {hint, kind, id} o {hint: null}.
    Prioridad: reunión pronto > hábito pendiente > telegram conectado con chats.
    """
    if user is None:
        return {"hint": None}
    if bool(getattr(user, "quiet_mode", False)) or prefs_service.is_meeting_mode(user):
        return {"hint": None, "suppressed": True}

    driver = bool(getattr(user, "driver_mode", False))
    ambient = bool(getattr(user, "ambient_mode", False))
    announced = {str(x) for x in (announced_event_ids or []) if x}

    # 1) Evento en <15 min
    try:
        from app.api.routes.google_calendar import _google_credentials_for_user
        from googleapiclient.discovery import build

        creds = _google_credentials_for_user(db, user.id, "default")
        if creds is not None:
            now = datetime.now(timezone.utc)
            time_max = now + timedelta(minutes=15)
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=4,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            for event in result.get("items") or []:
                eid = str(event.get("id") or "")
                if not eid or eid in announced:
                    continue
                title = (event.get("summary") or "un evento").strip()
                if driver or ambient:
                    text = f"En unos minutos: {title}."
                else:
                    text = f"Tenés «{title}» en menos de quince minutos."
                return {
                    "hint": _short(text, 120 if driver or ambient else 180),
                    "kind": "calendar",
                    "id": eid,
                }
    except Exception:
        pass

    # 2) Hábito pendiente
    try:
        today = date.today().isoformat()
        rows = (
            db.query(Habit)
            .filter(Habit.user_id == user.id)
            .order_by(Habit.updated_at.desc())
            .limit(8)
            .all()
        )
        pending = [r for r in rows if r.last_done != today]
        if pending:
            label = pending[0].label or pending[0].name
            hid = f"habit:{pending[0].name}:{today}"
            if hid not in announced:
                text = (
                    f"¿Marcamos {label}?"
                    if driver or ambient
                    else f"Todavía no marcaste «{label}» hoy. ¿Lo hacemos?"
                )
                return {
                    "hint": _short(text, 120 if driver or ambient else 180),
                    "kind": "habit",
                    "id": hid,
                }
    except Exception:
        pass

    return {"hint": None}
