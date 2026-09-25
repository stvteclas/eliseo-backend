"""Preferencias de voz y comportamiento del asistente por usuario."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import User

ARGENTINA_TZ = timezone(timedelta(hours=-3))


def display_name_for(user: User | None, persona: str | None = None) -> str:
    if user is not None and (user.wake_name or "").strip():
        return (user.wake_name or "").strip()[:40]
    key = (persona or (user.persona if user else None) or "eliseo").lower()
    return "Elisse" if key == "elisse" else "Eliseo"


def wake_names_for(user: User | None, persona: str | None = None) -> list[str]:
    """Nombres que activan al asistente (custom + Eliseo/Elisse)."""
    names = ["eliseo", "elisse", "elise"]
    custom = display_name_for(user, persona).strip().lower()
    if custom:
        folded = (
            custom.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ü", "u")
            .replace("ñ", "n")
        )
        names.insert(0, folded)
        if custom not in names:
            names.insert(0, custom)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def is_meeting_mode(user: User | None) -> bool:
    if user is None or user.meeting_until is None:
        return False
    until = user.meeting_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > datetime.now(timezone.utc)


def set_wake_name(db: Session, user_id: int, name: str) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    raw = (name or "").strip()
    if not raw:
        user.wake_name = None
        db.add(user)
        db.commit()
        return f"Listo, volvé a llamarme {display_name_for(user)}."
    if len(raw) > 40:
        return "Ese nombre es muy largo. Probá con una o dos palabras."
    if any(c.isdigit() for c in raw) and len(raw) < 3:
        return "Elegí un nombre más claro."
    user.wake_name = raw[:40]
    db.add(user)
    db.commit()
    return f"Perfecto, a partir de ahora llamame {raw}. La app sigue siendo Eliseo."


def set_quiet_mode(db: Session, user_id: int, enabled: bool) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.quiet_mode = bool(enabled)
    db.add(user)
    db.commit()
    if enabled:
        return (
            "Modo silencio activado: solo te respondo si me llamás por nombre. "
            "Tampoco te interrumpo con avisos hasta que me digas."
        )
    return "Listo, salí del modo silencio. Te escucho normal."


def set_confirm_sends(db: Session, user_id: int, enabled: bool) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.confirm_sends = bool(enabled)
    if not enabled and bool(getattr(user, "privacy_mode", False)):
        user.privacy_mode = False
    db.add(user)
    db.commit()
    if enabled:
        return "Listo: antes de mandar mails, chats o pagos te voy a pedir que digas dale."
    return "Listo, mando sin pedir confirmación."


def start_meeting_mode(db: Session, user_id: int, minutes: float = 60) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    mins = max(5, min(int(minutes or 60), 240))
    user.meeting_until = datetime.now(timezone.utc) + timedelta(minutes=mins)
    db.add(user)
    db.commit()
    return f"Modo reunión por {mins} minutos: no te interrumpo con avisos. Decí salí de modo reunión para cortarlo antes."


def stop_meeting_mode(db: Session, user_id: int) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.meeting_until = None
    db.add(user)
    db.commit()
    return "Listo, salí del modo reunión."


def set_driver_mode(db: Session, user_id: int, enabled: bool) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.driver_mode = bool(enabled)
    db.add(user)
    db.commit()
    if enabled:
        return "Modo conductor: respuestas bien cortas. Decí salí del modo conductor para volver."
    return "Listo, salí del modo conductor."


def set_privacy_mode(db: Session, user_id: int, enabled: bool) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.privacy_mode = bool(enabled)
    if enabled:
        user.confirm_sends = True
    db.add(user)
    db.commit()
    if enabled:
        return (
            "Modo privado activado: no mando mails, chats, Telegram ni pagos "
            "sin que me digas dale. Estoy de tu lado."
        )
    return "Listo, salí del modo privado."


def set_ambient_mode(db: Session, user_id: int, enabled: bool) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    user.ambient_mode = bool(enabled)
    db.add(user)
    db.commit()
    if enabled:
        return (
            "Modo ambiente: te escucho en el parlante, respondo corto "
            "y te aviso cosas útiles sin pedirte el nombre. "
            "Decí salí del modo ambiente para volver."
        )
    return "Listo, salí del modo ambiente."


def set_morning_hour(db: Session, user_id: int, hour: float = 8) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "No encontré tu usuario."
    h = int(hour if hour is not None else 8)
    if h < 5 or h > 11:
        return "Elegí una hora entre las 5 y las 11 de la mañana."
    user.morning_hour = h
    db.add(user)
    db.commit()
    return f"Listo, el ritual de buenos días queda alrededor de las {h}:00."


def prefs_public(user: User) -> dict:
    return {
        "persona": user.persona,
        "wake_name": (user.wake_name or "").strip() or None,
        "display_name": display_name_for(user),
        "quiet_mode": bool(user.quiet_mode),
        "confirm_sends": bool(getattr(user, "confirm_sends", False)),
        "meeting_mode": is_meeting_mode(user),
        "speak_slow": bool(getattr(user, "speak_slow", False)),
        "driver_mode": bool(getattr(user, "driver_mode", False)),
        "privacy_mode": bool(getattr(user, "privacy_mode", False)),
        "ambient_mode": bool(getattr(user, "ambient_mode", False)),
        "morning_hour": int(getattr(user, "morning_hour", 8) or 8),
    }
