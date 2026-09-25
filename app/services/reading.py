"""Lectura por partes: seguí / pará."""

from __future__ import annotations

import re
import threading
from typing import Any

_lock = threading.Lock()
# user_id -> {chunks: list[str], index: int}
_sessions: dict[int, dict[str, Any]] = {}

_CHUNK_CHARS = 380


def _split_chunks(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return []
    if len(raw) <= size:
        return [raw]

    chunks: list[str] = []
    rest = raw
    while rest:
        if len(rest) <= size:
            chunks.append(rest)
            break
        cut = rest.rfind(". ", 0, size + 1)
        if cut < size // 3:
            cut = rest.rfind(" ", 0, size + 1)
        if cut < size // 3:
            cut = size
        else:
            cut = cut + 1
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [c for c in chunks if c]


def clear(user_id: int) -> None:
    with _lock:
        _sessions.pop(user_id, None)


def start(user_id: int, text: str) -> str:
    chunks = _split_chunks(text)
    if not chunks:
        return ""
    with _lock:
        _sessions[user_id] = {"chunks": chunks, "index": 0}
    first = chunks[0]
    if len(chunks) == 1:
        return first
    return f"{first} Decí seguí para continuar, o pará para cortar."


def maybe_start_if_long(user_id: int, text: str, threshold: int = 450) -> str:
    raw = (text or "").strip()
    if len(raw) <= threshold:
        clear(user_id)
        return raw
    return start(user_id, raw)


def continue_reading(user_id: int) -> str:
    with _lock:
        session = _sessions.get(user_id)
        if not session:
            return "No hay nada para seguir leyendo."
        chunks: list[str] = session["chunks"]
        idx = int(session["index"]) + 1
        if idx >= len(chunks):
            _sessions.pop(user_id, None)
            return "Eso era todo."
        session["index"] = idx
        piece = chunks[idx]
        if idx >= len(chunks) - 1:
            _sessions.pop(user_id, None)
            return piece
        return f"{piece} Seguí cuando quieras."


def stop_reading(user_id: int) -> str:
    with _lock:
        had = user_id in _sessions
        _sessions.pop(user_id, None)
    if not had:
        return "No estaba leyendo nada."
    return "Listo, paro acá."


def has_session(user_id: int) -> bool:
    with _lock:
        return user_id in _sessions
