"""Tests del modo traductor bidireccional."""

import os
import uuid

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from app.agents.builtin_tools import BUILTIN_TOOL_NAMES, build_builtin_tools
from app.agents.orchestrator import handle_user_message
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import User
from app.services import translate as translate_service


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _user(db) -> User:
    user = User(email=f"tr-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_builtin_includes_translator_mode_tools():
    assert "start_translator_mode" in BUILTIN_TOOL_NAMES
    assert "stop_translator_mode" in BUILTIN_TOOL_NAMES


def test_detect_russian_vs_spanish():
    assert translate_service.detect_lang_in_pair("Привет как дела", "es", "ru") == "ru"
    assert translate_service.detect_lang_in_pair("Hola cómo estás", "es", "ru") == "es"


def test_exit_phrase():
    assert translate_service.is_translator_exit("salí del modo traductor")
    assert not translate_service.is_translator_exit("traducime esto")


def test_start_and_stop_translator_mode(db):
    user = _user(db)
    tools = {t.name: t for t in build_builtin_tools(user_id=user.id, db=db)}
    msg = tools["start_translator_mode"].invoke({"lang_a": "español", "lang_b": "ruso"})
    db.refresh(user)
    assert "traductor" in msg.lower()
    assert user.translator_lang_a == "es"
    assert user.translator_lang_b == "ru"

    tools["stop_translator_mode"].invoke({})
    db.refresh(user)
    assert user.translator_lang_a is None
    assert user.translator_lang_b is None


@pytest.mark.asyncio
async def test_handle_message_in_translator_mode(db, monkeypatch):
    user = _user(db)
    user.translator_lang_a = "es"
    user.translator_lang_b = "ru"
    db.add(user)
    db.commit()

    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    monkeypatch.setattr(
        translate_service,
        "translate_raw",
        lambda text, src, dst: "привет" if dst == "ru" else "hola",
    )

    reply, actions, speak_lang = await handle_user_message("Hola amigo", user.id, db)
    assert reply == "привет"
    assert speak_lang == "ru"
    assert actions == []


@pytest.mark.asyncio
async def test_handle_message_exits_translator_mode(db, monkeypatch):
    user = _user(db)
    user.translator_lang_a = "es"
    user.translator_lang_b = "ru"
    db.add(user)
    db.commit()
    monkeypatch.setattr(settings, "anthropic_api_key", "x")

    reply, _, speak_lang = await handle_user_message("salí del modo traductor", user.id, db)
    db.refresh(user)
    assert "salí" in reply.lower() or "modo" in reply.lower()
    assert user.translator_lang_a is None
    assert speak_lang == "es"
