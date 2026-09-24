"""CRUD simple de notas / lista de compras / etiquetas."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.note import Note

DEFAULT_LIST = "compras"
MAX_ITEMS = 50


def _normalize_list(list_name: str | None) -> str:
    name = (list_name or DEFAULT_LIST).strip().lower() or DEFAULT_LIST
    return name[:40]


def add_note(db: Session, user_id: int, text: str, list_name: str | None = None) -> str:
    body = (text or "").strip()
    if not body:
        return "Decime qué querés anotar."
    name = _normalize_list(list_name)
    count = db.query(Note).filter(Note.user_id == user_id, Note.list_name == name).count()
    if count >= MAX_ITEMS:
        return f"La lista '{name}' ya tiene {MAX_ITEMS} ítems. Borrá alguno antes."
    note = Note(user_id=user_id, list_name=name, text=body[:500], done=False)
    db.add(note)
    db.commit()
    return f"Listo, agregué '{body}' a {name}."


def list_notes(db: Session, user_id: int, list_name: str | None = None, include_done: bool = True) -> str:
    name = _normalize_list(list_name)
    q = db.query(Note).filter(Note.user_id == user_id, Note.list_name == name)
    if not include_done:
        q = q.filter(Note.done.is_(False))
    rows = q.order_by(Note.done.asc(), Note.id.asc()).limit(MAX_ITEMS).all()
    if not rows:
        return f"La lista '{name}' está vacía."
    lines = []
    for i, row in enumerate(rows, start=1):
        mark = "✓ " if getattr(row, "done", False) else ""
        lines.append(f"{i}. {mark}{row.text}")
    return f"En {name}: " + "; ".join(lines)


def clear_notes(db: Session, user_id: int, list_name: str | None = None) -> str:
    name = _normalize_list(list_name)
    deleted = db.query(Note).filter(Note.user_id == user_id, Note.list_name == name).delete()
    db.commit()
    if deleted == 0:
        return f"La lista '{name}' ya estaba vacía."
    return f"Borré {deleted} ítems de {name}."


def remove_note(db: Session, user_id: int, text: str, list_name: str | None = None) -> str:
    """Borra el primer ítem cuyo texto contenga `text` (case-insensitive)."""
    needle = (text or "").strip().lower()
    if not needle:
        return "Decime qué ítem querés sacar."
    name = _normalize_list(list_name)
    rows = (
        db.query(Note)
        .filter(Note.user_id == user_id, Note.list_name == name)
        .order_by(Note.id.asc())
        .all()
    )
    for row in rows:
        if needle in row.text.lower():
            db.delete(row)
            db.commit()
            return f"Saqué '{row.text}' de {name}."
    return f"No encontré '{text}' en {name}."


def check_off_note(db: Session, user_id: int, text: str, list_name: str | None = None) -> str:
    """Marca como hecho el primer ítem que matchee."""
    needle = (text or "").strip().lower()
    if not needle:
        return "Decime qué ítem tachaste."
    name = _normalize_list(list_name)
    rows = (
        db.query(Note)
        .filter(Note.user_id == user_id, Note.list_name == name, Note.done.is_(False))
        .order_by(Note.id.asc())
        .all()
    )
    for row in rows:
        if needle in row.text.lower():
            row.done = True
            db.add(row)
            db.commit()
            return f"Listo, taché '{row.text}' en {name}."
    return f"No encontré '{text}' pendiente en {name}."
