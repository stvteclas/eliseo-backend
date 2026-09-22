"""
Tests de HU-T11 (Google Calendar por usuario). No llaman a Google ni abren
navegador: el canje del code se reemplaza y la herramienta solo se construye.
"""

import os
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.agents.orchestrator import build_calendar_tool, get_tools_for_user
from app.api.routes import google_calendar
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal
from app.core.security import create_access_token, create_oauth_state, decode_access_token, decode_oauth_state
from app.main import app
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def google_settings(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_client_id", "client-id-de-prueba")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret-de-prueba")


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _new_user(db) -> int:
    user = User(email=f"test-t11-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    return user.id


def _add_credential(db, user_id: int, refresh_token: str = "refresh-token-de-prueba"):
    db.add(GoogleCalendarCredential(user_id=user_id, refresh_token_encrypted=encrypt(refresh_token)))
    db.add(UserConnector(user_id=user_id, service_name="google_calendar", scope="read_only", store_credential=True))
    db.commit()


def _auth_header(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# --- crypto


def test_encrypt_decrypt_roundtrip():
    secret = "1//refresh-token-secreto"
    encrypted = encrypt(secret)

    assert encrypted != secret
    assert decrypt(encrypted) == secret


def test_encrypt_without_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "")

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        encrypt("algo")


# --- herramienta del agente


def test_build_calendar_tool_without_credential_returns_none(db):
    assert build_calendar_tool(_new_user(db), db) is None


def test_build_calendar_tool_with_credential_builds_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tool = build_calendar_tool(user_id, db)

    assert tool is not None
    assert tool.name == "get_upcoming_calendar_events"


@pytest.mark.asyncio
async def test_get_tools_for_user_includes_calendar_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tools = await get_tools_for_user(user_id, db)

    assert [t.name for t in tools] == [
        "get_current_datetime",
        "get_weather",
        "get_upcoming_calendar_events",
    ]


@pytest.mark.asyncio
async def test_calendar_connector_without_credential_gives_no_tool(db):
    user_id = _new_user(db)
    db.add(UserConnector(user_id=user_id, service_name="google_calendar", scope="read_only"))
    db.commit()

    assert sorted(t.name for t in await get_tools_for_user(user_id, db)) == [
        "get_current_datetime",
        "get_weather",
    ]


@pytest.mark.asyncio
async def test_credential_without_connector_gives_no_tool(db):
    """Si el usuario desconectó el servicio, la herramienta no se carga aunque quede la fila."""
    user_id = _new_user(db)
    db.add(GoogleCalendarCredential(user_id=user_id, refresh_token_encrypted=encrypt("x")))
    db.commit()

    assert sorted(t.name for t in await get_tools_for_user(user_id, db)) == [
        "get_current_datetime",
        "get_weather",
    ]

# --- state firmado


def test_oauth_state_is_not_an_access_token_and_vice_versa():
    state = create_oauth_state(42)

    assert decode_oauth_state(state) == (42, "default")  # account_label (HU-T21), "default" si no se especifica
    assert decode_access_token(state) is None  # el state no sirve para autenticarse
    assert decode_oauth_state(create_access_token(42)) is None  # ni un access token como state
    assert decode_oauth_state("basura") is None


def test_oauth_state_carries_the_account_label():
    state = create_oauth_state(42, account_label="banco")

    assert decode_oauth_state(state) == (42, "banco")


# --- rutas OAuth


def test_authorize_requires_login():
    assert client.get("/connectors/google_calendar/authorize").status_code in (401, 403)


def test_authorize_returns_google_url_with_signed_state(db):
    user_id = _new_user(db)

    response = client.get("/connectors/google_calendar/authorize", headers=_auth_header(user_id))

    assert response.status_code == 200
    url = urlparse(response.json()["authorize_url"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id-de-prueba"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert query["redirect_uri"] == [settings.google_redirect_uri]
    assert "code_challenge" not in query  # sin PKCE: el callback no tendría el verifier
    assert decode_oauth_state(query["state"][0]) == (user_id, "default")


def test_authorize_without_google_configured_is_503(db, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")

    response = client.get("/connectors/google_calendar/authorize", headers=_auth_header(_new_user(db)))

    assert response.status_code == 503


def test_callback_stores_encrypted_token_and_connects_service(db, monkeypatch):
    user_id = _new_user(db)
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "1//token-real")

    response = client.get(
        "/connectors/google_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id)}
    )

    assert response.status_code == 200
    assert "cerrar esta pestaña" in response.text

    credential = db.query(GoogleCalendarCredential).filter_by(user_id=user_id).one()
    assert credential.refresh_token_encrypted != "1//token-real"  # no queda en texto plano
    assert decrypt(credential.refresh_token_encrypted) == "1//token-real"

    connector = db.query(UserConnector).filter_by(user_id=user_id, service_name="google_calendar").one()
    assert connector.scope == "read_only"
    assert connector.store_credential is True


def test_callback_twice_updates_instead_of_duplicating(db, monkeypatch):
    user_id = _new_user(db)
    tokens = iter(["1//primero", "1//segundo"])
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: next(tokens))
    params = {"code": "abc", "state": create_oauth_state(user_id)}

    assert client.get("/connectors/google_calendar/callback", params=params).status_code == 200
    assert client.get("/connectors/google_calendar/callback", params=params).status_code == 200

    credential = db.query(GoogleCalendarCredential).filter_by(user_id=user_id).one()
    assert decrypt(credential.refresh_token_encrypted) == "1//segundo"
    assert db.query(UserConnector).filter_by(user_id=user_id, service_name="google_calendar").count() == 1


@pytest.mark.parametrize(
    "params",
    [
        {"code": "abc"},  # sin state
        {"code": "abc", "state": "falsificado"},  # state inválido
        {"state": "se-completa-abajo"},  # sin code
        {"error": "access_denied"},  # el usuario canceló en Google
    ],
)
def test_callback_rejects_invalid_requests(db, monkeypatch, params):
    user_id = _new_user(db)
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "1//no-deberia-usarse")
    if params.get("state") == "se-completa-abajo":
        params = {"state": create_oauth_state(user_id)}

    response = client.get("/connectors/google_calendar/callback", params=params)

    assert response.status_code == 400
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id).count() == 0


def test_callback_google_failure_is_400_and_stores_nothing(db, monkeypatch):
    user_id = _new_user(db)

    def boom(code):
        raise RuntimeError("Google rechazó el code")

    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", boom)

    response = client.get(
        "/connectors/google_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id)}
    )

    assert response.status_code == 400
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id).count() == 0


def test_disconnecting_deletes_the_stored_refresh_token(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    response = client.delete("/connectors/google_calendar", headers=_auth_header(user_id))

    assert response.status_code == 200
    db.expire_all()
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id).count() == 0
    assert db.query(UserConnector).filter_by(user_id=user_id).count() == 0
