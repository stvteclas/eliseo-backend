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
