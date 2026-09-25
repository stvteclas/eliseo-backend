"""Tests de memoria, prefs nuevas y parseos."""

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "AsHA6SP0CHfNHvA-9cyJ8XDV27JtGlxaDxbebocgQrE=",
)

from app.agents.builtin_tools import BUILTIN_TOOL_NAMES, build_builtin_tools
from app.core.database import SessionLocal
from app.models.user import User
from app.services import memory as memory_service
from app.services import prefs as prefs_service
import pytest


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _user(db) -> int:
    user = User(email=f"mem-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="x")
    db.add(user)
    db.commit()
    return user.id


def test_memory_tools_registered():
    for name in (
        "remember_fact",
        "recall_memory",
        "forget_fact",
        "run_morning_ritual",
        "set_privacy_mode",
        "set_ambient_mode",
        "set_morning_hour",
    ):
        assert name in BUILTIN_TOOL_NAMES


def test_remember_recall_forget(db):
    user_id = _user(db)
    msg = memory_service.remember(db, user_id, "Mi pareja es Ana", key="pareja")
    assert "ana" in msg.lower()
    listed = memory_service.recall(db, user_id, "Ana")
    assert "ana" in listed.lower()
    ctx = memory_service.agent_context(db, user_id)
    assert "MEMORIA" in ctx and "Ana" in ctx
    gone = memory_service.forget(db, user_id, "pareja")
    assert "olvid" in gone.lower()


def test_privacy_and_ambient_prefs(db):
    user_id = _user(db)
    assert "privado" in prefs_service.set_privacy_mode(db, user_id, True).lower()
    user = db.query(User).filter(User.id == user_id).first()
    assert user.privacy_mode is True
    assert user.confirm_sends is True
    assert "ambiente" in prefs_service.set_ambient_mode(db, user_id, True).lower()
    assert "8" in prefs_service.set_morning_hour(db, user_id, 8).lower()


def test_morning_ritual_runs(db):
    user_id = _user(db)
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    text = tools["run_morning_ritual"].invoke({})
    assert "buenos días" in text.lower() or "ahora es" in text.lower()
