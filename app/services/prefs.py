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
        # sin acentos simples
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
    # únicos preservando orden
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
    # Evitar basura
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
    }
