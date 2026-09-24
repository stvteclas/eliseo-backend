"""Historial corto de conversación por usuario (voz multi-turno)."""

from __future__ import annotations

import json
from typing import Any

_MAX_MESSAGES = 8  # 4 intercambios
_store: dict[int, list[dict[str, str]]] = {}


def get_history(user_id: int) -> list[dict[str, str]]:
    return list(_store.get(user_id, []))


def remember_turn(user_id: int, user_text: str, assistant_text: str) -> None:
    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if not user_text:
        return
    hist = _store.setdefault(user_id, [])
    hist.append({"role": "user", "content": user_text[:2000]})
    if assistant_text:
        hist.append({"role": "assistant", "content": assistant_text[:2000]})
    _store[user_id] = hist[-_MAX_MESSAGES:]


def parse_history_payload(raw: str | None) -> list[dict[str, str]] | None:
    """
    Historial enviado por la app (JSON). None si no viene o es inválido.
    """
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: list[dict[str, str]] = []
    for item in data[-_MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content.strip()[:2000]})
    return out or None


def merge_history(
    user_id: int,
    client_history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Preferí el historial de la app; si no hay, el del servidor."""
    if client_history:
        return client_history[-_MAX_MESSAGES:]
    return get_history(user_id)


def build_agent_messages(
    history: list[dict[str, str]],
    latest_user: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = list(history)
    # Evitar duplicar si el último del historial ya es este user turn
    if messages and messages[-1].get("role") == "user" and messages[-1].get("content") == latest_user:
        return messages
    messages.append({"role": "user", "content": latest_user})
    return messages
