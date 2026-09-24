"""Acciones pendientes de confirmación («dale»)."""

from __future__ import annotations

import threading
from typing import Any, Callable

_lock = threading.Lock()
# user_id -> {label, runner}
_pending: dict[int, dict[str, Any]] = {}


def set_pending(user_id: int, label: str, runner: Callable[[], str]) -> None:
    with _lock:
        _pending[user_id] = {"label": label, "runner": runner}


def clear_pending(user_id: int) -> None:
    with _lock:
        _pending.pop(user_id, None)


def get_pending_label(user_id: int) -> str | None:
    with _lock:
        item = _pending.get(user_id)
        return (item or {}).get("label")


def confirm_pending(user_id: int) -> str:
    with _lock:
        item = _pending.pop(user_id, None)
    if not item:
        return "No hay nada pendiente de confirmar."
    try:
        return item["runner"]()
    except Exception:
        return "No pude completar esa acción. Probá de nuevo."


def cancel_pending(user_id: int) -> str:
    with _lock:
        item = _pending.pop(user_id, None)
    if not item:
        return "No había nada para cancelar."
    return f"Cancelé: {item.get('label') or 'la acción pendiente'}."
