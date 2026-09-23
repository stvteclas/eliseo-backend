"""Tests de onboarding y login Google (sin pegarle a Google real)."""

import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User
from app.services.onboarding import get_onboarding_status

client = TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _user(db) -> User:
    user = User(email=f"ob-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_onboarding_requires_calendar(db):
    user = _user(db)
    status = get_onboarding_status(db, user.id)
    assert status["ready"] is False
    assert status["next_step"]["id"] == "google_calendar"
    assert "Calendar" in status["guide"] or "calendar" in status["guide"].lower()


def test_onboarding_ready_when_calendar_connected(db):
    user = _user(db)
    db.add(
        UserConnector(
            user_id=user.id,
            service_name="google_calendar",
            scope="read_write",
            store_credential=True,
        )
    )
    db.add(
        GoogleCalendarCredential(
            user_id=user.id,
            refresh_token_encrypted=encrypt("x"),
            account_label="default",
        )
    )
    db.commit()
    status = get_onboarding_status(db, user.id)
    assert status["ready"] is True
    assert status["missing_required"] == []


def test_onboarding_endpoint(db):
    user = _user(db)
    response = client.get("/auth/onboarding", headers=_auth(user.id))
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert "guide" in body
    assert isinstance(body["services"], list)


def test_google_login_authorize_requires_config(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    assert client.get("/auth/google/authorize").status_code == 503


def test_google_login_authorize_returns_url(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(
        settings, "google_login_redirect_uri", "https://example.com/auth/google/callback"
    )
    response = client.get("/auth/google/authorize")
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert "accounts.google.com" in url
