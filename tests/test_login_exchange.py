"""Códigos de un solo uso para canjear login Google → JWT (sin JWT en la URL)."""

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, decode_access_token
from app.main import app
from app.models.login_exchange import consume_code, issue_code
from app.models.user import User

client = TestClient(app)


def _user() -> User:
    db = SessionLocal()
    try:
        user = User(
            email=f"lex-{uuid.uuid4().hex[:8]}@eliseo.dev",
            hashed_password="x",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_access_token_lifetime_is_twelve_hours():
    assert ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 12
    user = _user()
    token = create_access_token(user.id)
    assert decode_access_token(token) == user.id


def test_issue_and_consume_once():
    user = _user()
    db = SessionLocal()
    try:
        code = issue_code(db, user.id)
        assert code and len(code) >= 20
        assert consume_code(db, code) == user.id
        assert consume_code(db, code) is None  # second use fails
    finally:
        db.close()


def test_consume_rejects_expired_and_garbage():
    user = _user()
    db = SessionLocal()
    try:
        code = issue_code(db, user.id)
        from app.models.login_exchange import LoginExchangeCode

        row = db.query(LoginExchangeCode).filter(LoginExchangeCode.code == code).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(row)
        db.commit()
        assert consume_code(db, code) is None
        assert consume_code(db, "") is None
        assert consume_code(db, "no-existe") is None
    finally:
        db.close()


def test_exchange_endpoint_returns_jwt_once():
    user = _user()
    db = SessionLocal()
    try:
        code = issue_code(db, user.id)
    finally:
        db.close()

    first = client.post("/auth/google/exchange", json={"code": code})
    assert first.status_code == 200
    token = first.json()["access_token"]
    assert decode_access_token(token) == user.id

    second = client.post("/auth/google/exchange", json={"code": code})
    assert second.status_code == 401

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email


def test_exchange_rejects_bad_payload():
    assert client.post("/auth/google/exchange", json={"code": "corto"}).status_code == 422
    assert client.post("/auth/google/exchange", json={}).status_code == 422
