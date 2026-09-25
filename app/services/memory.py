"""Hechos durables que Eliseo recuerda entre turnos."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user_memory import UserMemory

_MAX_FACTS = 40
_CONTEXT_FACTS = 12


def _norm_key(key: str | None) -> str | None:
    raw = (key or "").strip().lower()
    if not raw:
        return None
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^a-z0-9_áéíóúüñ]", "", raw)
    return (raw[:64] or None)


def remember(db: Session, user_id: int, fact: str, key: str | None = None) -> str:
    text = re.sub(r"\s+", " ", (fact or "").strip())
    if not text:
        return "Decime qué querés que recuerde."
    if len(text) > 400:
        return "Eso es muy largo. Resumilo en una frase."

    k = _norm_key(key)
    row = None
    if k:
        row = (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id, UserMemory.key == k)
            .first()
        )
    if row is None:
        # Evitar duplicados casi idénticos
        existing = (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(_MAX_FACTS)
            .all()
        )
        fold = text.lower()
        for e in existing:
            if (e.fact or "").strip().lower() == fold:
                e.updated_at = datetime.now(timezone.utc)
                db.add(e)
                db.commit()
                return f"Ya lo tenía: {e.fact}."
        # Cap: borrar el más viejo si hay demasiados
        if len(existing) >= _MAX_FACTS:
            oldest = (
                db.query(UserMemory)
                .filter(UserMemory.user_id == user_id)
                .order_by(UserMemory.updated_at.asc())
                .first()
            )
            if oldest is not None:
                db.delete(oldest)
                db.commit()
        row = UserMemory(user_id=user_id, key=k, fact=text)
    else:
        row.fact = text
        row.updated_at = datetime.now(timezone.utc)

    db.add(row)
    db.commit()
    return f"Listo, me acuerdo: {text}."


def recall(db: Session, user_id: int, query: str = "") -> str:
    q = (query or "").strip().lower()
    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id)
        .order_by(UserMemory.updated_at.desc())
        .limit(_MAX_FACTS)
        .all()
    )
    if not rows:
        return "Todavía no guardé nada sobre vos."
    if q:
        matched = [r for r in rows if q in (r.fact or "").lower() or (r.key and q in r.key)]
        if not matched:
            return f"No encontré nada sobre «{query}»."
        rows = matched[:8]
    else:
        rows = rows[:10]
    lines = [r.fact for r in rows if r.fact]
    return "Me acuerdo de esto: " + "; ".join(lines) + "."


def forget(db: Session, user_id: int, query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "Decime qué olvidar."
    q_low = q.lower()
    k = _norm_key(q)
    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id)
        .order_by(UserMemory.updated_at.desc())
        .all()
    )
    deleted = 0
    for r in rows:
        if (k and r.key == k) or q_low in (r.fact or "").lower():
            db.delete(r)
            deleted += 1
    if deleted:
        db.commit()
        return f"Listo, olvidé {deleted} cosa{'s' if deleted != 1 else ''} sobre eso."
    return f"No encontré nada parecido a «{q}»."


def list_facts(db: Session, user_id: int, limit: int = _CONTEXT_FACTS) -> list[str]:
    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id)
        .order_by(UserMemory.updated_at.desc())
        .limit(max(1, min(int(limit or _CONTEXT_FACTS), _CONTEXT_FACTS)))
        .all()
    )
    return [r.fact for r in rows if (r.fact or "").strip()]


def agent_context(db: Session, user_id: int) -> str:
    facts = list_facts(db, user_id, _CONTEXT_FACTS)
    if not facts:
        return ""
    joined = "; ".join(facts)
    return (
        "MEMORIA PERSONAL (usala sin preguntar de nuevo; si contradice algo nuevo, actualizá con remember_fact):\n"
        f"{joined}"
    )
