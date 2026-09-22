"""
Acciones que ejecuta la app (timer, notificación local, llamar).

Las tools del backend encolan un dict acá; /chat lo devuelve junto con el
texto hablado para que Expo lo ejecute en el teléfono.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_pending: ContextVar[list[dict[str, Any]] | None] = ContextVar("eliseo_client_actions", default=None)


def reset_client_actions() -> None:
    _pending.set([])


def queue_client_action(action: dict[str, Any]) -> None:
    actions = _pending.get()
    if actions is None:
        actions = []
        _pending.set(actions)
    actions.append(action)


def drain_client_actions() -> list[dict[str, Any]]:
    actions = list(_pending.get() or [])
    _pending.set([])
    return actions
