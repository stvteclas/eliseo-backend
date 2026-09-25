"""Tests del conector Telegram (sin red real a Telegram)."""

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")
# Fernet: 32 bytes url-safe base64
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "AsHA6SP0CHfNHvA-9cyJ8XDV27JtGlxaDxbebocgQrE=",
)

from app.main import app  # noqa: F401
from app.agents.builtin_tools import BUILTIN_TOOL_NAMES, build_builtin_tools
from app.core.database import SessionLocal
from app.models.user import User
from app.services import telegram as telegram_service
import pytest


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _user(db) -> int:
    user = User(email=f"tg-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="x")
    db.add(user)
    db.commit()
    return user.id


def test_telegram_tools_registered():
    for name in (
        "connect_telegram",
        "confirm_telegram_code",
        "confirm_telegram_password",
        "get_telegram_messages",
        "send_telegram_message",
        "list_telegram_chats",
        "telegram_status",
        "disconnect_telegram",
    ):
        assert name in BUILTIN_TOOL_NAMES


def test_normalize_phone_and_code():
    assert telegram_service.normalize_phone("+54 9 11 1234-5678") == "+5491112345678"
    assert telegram_service.normalize_phone("5491112345678").startswith("+")
    assert telegram_service.normalize_code("1 2 3 4 5") == "12345"
    assert telegram_service.normalize_code("uno dos tres cuatro cinco") == "12345"
    assert telegram_service.normalize_code("el código es 48291") == "48291"


def test_telegram_status_without_config(db, monkeypatch):
    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 0)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "")
    user_id = _user(db)
    msg = telegram_service.status_text(db, user_id)
    assert "configurado" in msg.lower() or "servidor" in msg.lower()


def test_telegram_status_not_connected(db, monkeypatch):
    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    assert telegram_service.is_connected(db, user_id) is False
    assert "no está conectado" in telegram_service.status_text(db, user_id).lower()


def test_agent_context_and_saved_phone(db, monkeypatch):
    from app.models.telegram_credential import TelegramCredential

    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    ctx = telegram_service.agent_context(db, user_id)
    assert "sin número" in ctx.lower()

    row = TelegramCredential(
        user_id=user_id,
        account_label="default",
        phone="+5491112345678",
        login_stage="none",
    )
    db.add(row)
    db.commit()
    assert telegram_service.saved_phone(db, user_id) == "+5491112345678"
    ctx2 = telegram_service.agent_context(db, user_id)
    assert "guardado" in ctx2.lower()
    assert "NO vuelvas a preguntar" in ctx2 or "NO" in ctx2

    row.login_stage = "connected"
    row.session_encrypted = "x"
    row.display_name = "Roberto"
    db.add(row)
    db.commit()
    ctx3 = telegram_service.agent_context(db, user_id)
    assert "YA CONECTADO" in ctx3


def test_connect_telegram_tool_asks_for_phone(db, monkeypatch):
    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    msg = tools["connect_telegram"].invoke({"phone": "12"})
    assert "número" in msg.lower() or "país" in msg.lower()


def test_start_service_connection_telegram_voice_hint(db):
    user_id = _user(db)
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    msg = tools["start_service_connection"].invoke({"service": "telegram"})
    assert "número" in msg.lower() or "telegram" in msg.lower()


def test_poll_incoming_not_connected(db, monkeypatch):
    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    out = telegram_service.poll_incoming_messages(db, user_id, since_iso=None)
    assert out["connected"] is False
    assert out["messages"] == []


def test_poll_incoming_first_cursor_no_history(db, monkeypatch):
    from app.core.crypto import encrypt
    from app.models.telegram_credential import TelegramCredential

    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    row = TelegramCredential(
        user_id=user_id,
        login_stage="connected",
        session_encrypted=encrypt("fake-session"),
        account_label="default",
    )
    db.add(row)
    db.commit()

    out = telegram_service.poll_incoming_messages(db, user_id, since_iso=None)
    assert out["connected"] is True
    assert out["messages"] == []
    assert out["cursor"]


def test_poll_incoming_filters_new(db, monkeypatch):
    from app.core.crypto import encrypt
    from app.models.telegram_credential import TelegramCredential

    monkeypatch.setattr(telegram_service.settings, "telegram_api_id", 35059468)
    monkeypatch.setattr(telegram_service.settings, "telegram_api_hash", "fakehash")
    user_id = _user(db)
    row = TelegramCredential(
        user_id=user_id,
        login_stage="connected",
        session_encrypted=encrypt("fake-session"),
        account_label="default",
    )
    db.add(row)
    db.commit()

    async def fake_poll(*_a, **_k):
        return {
            "messages": [
                {
                    "from": "Ana",
                    "text": "hola",
                    "chat": "Ana",
                    "id": "1",
                    "create_time": "2026-09-25T12:00:00Z",
                }
            ],
            "cursor": "2026-09-25T12:00:00Z",
            "connected": True,
        }

    monkeypatch.setattr(telegram_service, "_poll_incoming_net", fake_poll)
    out = telegram_service.poll_incoming_messages(
        db, user_id, since_iso="2026-09-25T11:00:00Z"
    )
    assert len(out["messages"]) == 1
    assert out["messages"][0]["from"] == "Ana"
