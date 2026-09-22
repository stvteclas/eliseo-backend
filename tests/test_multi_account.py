"""
Tests de HU-T21 (multi-cuenta): un usuario puede conectar más de una cuenta
del mismo servicio (ej. Calendar "personal" y "banco"), distinguidas por
account_label. No le pegan a Google ni a Mercado Pago reales.
"""

import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.agents.orchestrator import build_calendar_tool, get_tools_for_user
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _new_user(db) -> int:
    user = User(email=f"test-t21-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    return user.id


def _add_calendar_account(db, user_id: int, account_label: str, refresh_token: str = "refresh-de-prueba"):
    db.add(
        GoogleCalendarCredential(
            user_id=user_id, account_label=account_label, refresh_token_encrypted=encrypt(refresh_token)
        )
    )
    db.add(
        UserConnector(
            user_id=user_id,
            service_name="google_calendar",
            account_label=account_label,
            scope="read_only",
            store_credential=True,
        )
    )
    db.commit()


def _auth_header(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# 1. Conectar el mismo servicio dos veces con labels distintos crea 2 filas


def test_connecting_same_service_with_different_labels_creates_two_rows(db):
    user_id = _new_user(db)
    headers = _auth_header(user_id)

    personal = client.post(
        "/connectors", json={"service_name": "google_calendar", "scope": "read_only", "account_label": "personal"}, headers=headers
    )
    banco = client.post(
        "/connectors", json={"service_name": "google_calendar", "scope": "read_only", "account_label": "banco"}, headers=headers
    )

    assert personal.status_code == 201
    assert banco.status_code == 201  # no pisa a "personal": es una fila nueva, no un update

    connectors = client.get("/connectors", headers=headers).json()
    assert sorted(c["account_label"] for c in connectors) == ["banco", "personal"]
    assert len({c["id"] for c in connectors}) == 2


def test_connecting_same_service_and_label_twice_updates_instead_of_duplicating(db):
    user_id = _new_user(db)
    headers = _auth_header(user_id)

    client.post(
        "/connectors", json={"service_name": "google_calendar", "scope": "read_only", "account_label": "banco"}, headers=headers
    )
    response = client.post(
        "/connectors", json={"service_name": "google_calendar", "scope": "read_write", "account_label": "banco"}, headers=headers
    )

    assert response.status_code == 200  # update, no create
    connectors = client.get("/connectors", headers=headers).json()
    assert len(connectors) == 1
    assert connectors[0]["scope"] == "read_write"


def test_default_account_label_keeps_old_behavior(db):
    """Sin especificar account_label, sigue siendo "default" — Calendar/MP de una sola cuenta no cambian."""
    user_id = _new_user(db)
    headers = _auth_header(user_id)

    response = client.post("/connectors", json={"service_name": "google_calendar", "scope": "read_only"}, headers=headers)

    assert response.status_code == 201
    assert response.json()["account_label"] == "default"


# 2. get_tools_for_user devuelve 2 tools de calendario, con nombres distintos


@pytest.mark.asyncio
async def test_get_tools_for_user_returns_one_tool_per_account(db):
    user_id = _new_user(db)
    _add_calendar_account(db, user_id, "personal")
    _add_calendar_account(db, user_id, "banco")

    tools = await get_tools_for_user(user_id, db)

    assert sorted(t.name for t in tools) == [
        "get_current_datetime",
        "get_upcoming_calendar_events_banco",
        "get_upcoming_calendar_events_personal",
        "get_weather",
    ]
    assert len({t.name for t in tools}) == 4  # nombres únicos: el agente puede elegir cuál usar


def test_calendar_tool_default_label_keeps_the_original_name(db):
    user_id = _new_user(db)
    _add_calendar_account(db, user_id, "default")

    tool = build_calendar_tool(user_id, db, "default")

    assert tool.name == "get_upcoming_calendar_events"  # sin sufijo: T11 no cambia para la única cuenta


def test_calendar_tool_for_missing_account_label_returns_none(db):
    user_id = _new_user(db)
    _add_calendar_account(db, user_id, "personal")

    assert build_calendar_tool(user_id, db, "banco") is None  # esa cuenta puntual no está conectada


# 3. DELETE con account_label borra solo esa cuenta


def test_deleting_one_account_keeps_the_other(db):
    user_id = _new_user(db)
    headers = _auth_header(user_id)
    _add_calendar_account(db, user_id, "personal")
    _add_calendar_account(db, user_id, "banco")

    response = client.delete("/connectors/google_calendar", params={"account_label": "banco"}, headers=headers)

    assert response.status_code == 200
    remaining = client.get("/connectors", headers=headers).json()
    assert [c["account_label"] for c in remaining] == ["personal"]

    db.expire_all()
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id, account_label="banco").count() == 0
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id, account_label="personal").count() == 1


def test_deleting_an_account_that_does_not_exist_is_404(db):
    user_id = _new_user(db)
    headers = _auth_header(user_id)
    _add_calendar_account(db, user_id, "personal")

    response = client.delete("/connectors/google_calendar", params={"account_label": "banco"}, headers=headers)

    assert response.status_code == 404
    # la cuenta que sí existe no se ve afectada por el intento fallido
    assert len(client.get("/connectors", headers=headers).json()) == 1


# --- OAuth: el account_label viaja en el state y llega intacto al callback


def test_authorize_with_account_label_encodes_it_in_the_state(db, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    user_id = _new_user(db)

    from urllib.parse import parse_qs, urlparse

    from app.core.security import decode_oauth_state

    response = client.get(
        "/connectors/google_calendar/authorize", params={"account_label": "banco"}, headers=_auth_header(user_id)
    )

    state = parse_qs(urlparse(response.json()["authorize_url"]).query)["state"][0]
    assert decode_oauth_state(state) == (user_id, "banco")


def test_callback_stores_the_credential_under_its_account_label(db, monkeypatch):
    from app.api.routes import google_calendar
    from app.core.security import create_oauth_state

    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "refresh-token-banco")
    user_id = _new_user(db)

    response = client.get(
        "/connectors/google_calendar/callback",
        params={"code": "abc", "state": create_oauth_state(user_id, "banco")},
    )

    assert response.status_code == 200
    credential = db.query(GoogleCalendarCredential).filter_by(user_id=user_id).one()
    assert credential.account_label == "banco"
    connector = db.query(UserConnector).filter_by(user_id=user_id, service_name="google_calendar").one()
    assert connector.account_label == "banco"


def test_connecting_two_accounts_via_oauth_does_not_collide(db, monkeypatch):
    """Regresión del motivo de ser de T21: antes de esto, la segunda cuenta pisaba a la primera."""
    from app.api.routes import google_calendar
    from app.core.security import create_oauth_state

    tokens = iter(["refresh-personal", "refresh-banco"])
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: next(tokens))
    user_id = _new_user(db)

    client.get(
        "/connectors/google_calendar/callback",
        params={"code": "abc", "state": create_oauth_state(user_id, "personal")},
    )
    client.get(
        "/connectors/google_calendar/callback",
        params={"code": "def", "state": create_oauth_state(user_id, "banco")},
    )

    credentials = db.query(GoogleCalendarCredential).filter_by(user_id=user_id).all()
    assert {c.account_label for c in credentials} == {"personal", "banco"}
