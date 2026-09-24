"""Hábitos simples: agua, pastilla, etc."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.habit import Habit


def _norm(name: str) -> str:
    return (name or "").strip().lower()[:60]


def mark_habit_done(db: Session, user_id: int, name: str) -> str:
    key = _norm(name)
    if not key:
        return "Decime qué hábito: agua, pastilla, ejercicio…"
    today = date.today().isoformat()
    row = db.query(Habit).filter(Habit.user_id == user_id, Habit.name == key).first()
    if row is None:
        row = Habit(user_id=user_id, name=key, label=(name or key).strip()[:60], streak=0)
        db.add(row)
    if row.last_done == today:
        return f"Hoy ya marcaste «{row.label}»."
    yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
    if row.last_done == yesterday:
        row.streak = int(row.streak or 0) + 1
    else:
        row.streak = 1
    row.last_done = today
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return f"Listo, marqué «{row.label}» por hoy. Racha: {row.streak} día{'s' if row.streak != 1 else ''}."


def habit_status(db: Session, user_id: int, name: str = "") -> str:
    today = date.today().isoformat()
    key = _norm(name)
    if key:
        row = db.query(Habit).filter(Habit.user_id == user_id, Habit.name == key).first()
        if row is None:
            return f"Todavía no registraste «{name}»."
        if row.last_done == today:
            return f"Sí: «{row.label}» ya está marcado hoy. Racha {row.streak}."
        return f"No: «{row.label}» todavía no lo marcaste hoy. Racha previa {row.streak}."
    rows = db.query(Habit).filter(Habit.user_id == user_id).order_by(Habit.name).limit(20).all()
    if not rows:
        return "No tenés hábitos cargados. Decí por ejemplo «marqué agua» o «tomé la pastilla»."
    bits = []
    for row in rows:
        estado = "hecho" if row.last_done == today else "pendiente"
        bits.append(f"{row.label}: {estado} (racha {row.streak})")
    return "Hábitos de hoy: " + "; ".join(bits) + "."
