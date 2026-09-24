"""
Acciones que ejecuta la app (timer, notificación local, llamar, open_url).

Las tools del backend encolan un dict acá; /chat y /voice/turn lo devuelven
junto con el texto hablado para que Expo lo ejecute en el teléfono.

Importante: LangGraph suele correr tools sync en un thread pool. ContextVar
NO se propaga ahí, así que usamos un bucket compartido por request (lock).
Concurrencia real multi-usuario en el mismo worker es rara en Eliseo voz;
si crece, pasar el bucket por closure a las tools.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_bucket: list[dict[str, Any]] | None = None


def reset_client_actions() -> None:
    global _bucket
    with _lock:
        _bucket = []


def queue_client_action(action: dict[str, Any]) -> None:
    global _bucket
    with _lock:
        if _bucket is None:
            _bucket = []
        _bucket.append(action)


def drain_client_actions() -> list[dict[str, Any]]:
    global _bucket
    with _lock:
        actions = list(_bucket or [])
        _bucket = []
        return actions
