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

from app.agents.orchestrator import build_calendar_tool, build_calendar_tools, get_tools_for_user
from app.agents.builtin_tools import BUILTIN_TOOL_NAMES
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


class FakeCalendarList:
    def __init__(self, calendars):
        self._calendars = calendars

    def list(self, pageToken=None):
        calendars = self._calendars

        class Exec:
            def execute(self_inner):
                return {"items": calendars}

        return Exec()


class FakeEventsMultiCalendar:
    def __init__(self, events_by_calendar, broken_calendars=()):
        self._events_by_calendar = events_by_calendar
        self._broken = set(broken_calendars)

    def list(self, calendarId, timeMin=None, maxResults=None, singleEvents=None, orderBy=None):
        if calendarId in self._broken:
            raise RuntimeError(f"sin permiso para leer {calendarId}")

        events = self._events_by_calendar.get(calendarId, [])

        class Exec:
            def execute(self_inner):
                return {"items": events}

        return Exec()


def _fake_multi_calendar_service(calendars, events_by_calendar, broken_calendars=()):
    class FakeService:
        def calendarList(self):
            return FakeCalendarList(calendars)

        def events(self):
            return FakeEventsMultiCalendar(events_by_calendar, broken_calendars)

    return FakeService()


def test_get_upcoming_calendar_events_merges_and_sorts_all_calendars(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    calendars = [
        {"id": "primary", "summary": "pablo@gmail.com", "primary": True},
        {"id": "es.ar#holiday@group.v.calendar.google.com", "summary": "Cumpleaños"},
    ]
    events_by_calendar = {
        "primary": [{"start": {"dateTime": "2026-09-25T10:00:00-03:00"}, "summary": "Dentista"}],
        "es.ar#holiday@group.v.calendar.google.com": [
            {"start": {"dateTime": "2026-09-24T09:00:00-03:00"}, "summary": "Cumple de Juan"}
        ],
    }
    monkeypatch.setattr(
        "app.agents.orchestrator.build",
        lambda *a, **k: _fake_multi_calendar_service(calendars, events_by_calendar),
    )

    tools = {t.name: t for t in build_calendar_tools(user_id, db)}
    result = tools["get_upcoming_calendar_events"].invoke({})

    lines = result.split("\n")
    assert len(lines) == 2
    # Ordenado por fecha: el cumpleaños (24/9) antes que el dentista (25/9).
    assert "Cumple de Juan" in lines[0]
    assert "[Cumpleaños]" in lines[0]  # calendario no-primario, se aclara cuál es
    assert "Dentista" in lines[1]
    assert "[" not in lines[1]  # el calendario primario no lleva etiqueta


def test_get_upcoming_calendar_events_skips_a_broken_calendar(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    calendars = [
        {"id": "primary", "summary": "pablo@gmail.com", "primary": True},
        {"id": "roto@group.calendar.google.com", "summary": "Sin permiso"},
    ]
    events_by_calendar = {
        "primary": [{"start": {"dateTime": "2026-09-25T10:00:00-03:00"}, "summary": "Dentista"}],
    }
    monkeypatch.setattr(
        "app.agents.orchestrator.build",
        lambda *a, **k: _fake_multi_calendar_service(
            calendars, events_by_calendar, broken_calendars={"roto@group.calendar.google.com"}
        ),
    )

    tools = {t.name: t for t in build_calendar_tools(user_id, db)}
    result = tools["get_upcoming_calendar_events"].invoke({})

    assert "Dentista" in result  # el calendario que sí anda no se pierde por el que falla


def test_get_upcoming_calendar_events_falls_back_to_primary_when_calendar_list_is_empty(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    monkeypatch.setattr(
        "app.agents.orchestrator.build",
        lambda *a, **k: _fake_multi_calendar_service(
            [], {"primary": [{"start": {"dateTime": "2026-09-25T10:00:00-03:00"}, "summary": "Dentista"}]}
        ),
    )

    tools = {t.name: t for t in build_calendar_tools(user_id, db)}
    result = tools["get_upcoming_calendar_events"].invoke({})

    assert "Dentista" in result


def test_get_upcoming_calendar_events_no_events_anywhere(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    calendars = [{"id": "primary", "summary": "pablo@gmail.com", "primary": True}]
    monkeypatch.setattr(
        "app.agents.orchestrator.build",
        lambda *a, **k: _fake_multi_calendar_service(calendars, {}),
    )

    tools = {t.name: t for t in build_calendar_tools(user_id, db)}
    result = tools["get_upcoming_calendar_events"].invoke({})

    assert "No hay eventos" in result


def test_build_calendar_tool_without_credential_returns_none(db):
    assert build_calendar_tool(_new_user(db), db) is None


def test_build_calendar_tool_with_credential_builds_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tool = build_calendar_tool(user_id, db)

    assert tool is not None
    assert tool.name == "get_upcoming_calendar_events"


def test_build_calendar_tools_includes_reminder_with_10min_popup(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)
    captured = {}

    class FakeEvents:
        def insert(self, calendarId, body):
            captured["calendarId"] = calendarId
            captured["body"] = body

            class Exec:
                def execute(self_inner):
                    return {"htmlLink": "https://calendar.google.com/event?eid=abc"}

            return Exec()

    class FakeService:
        def events(self):
            return FakeEvents()

    monkeypatch.setattr(
        "app.agents.orchestrator.build",
        lambda *args, **kwargs: FakeService(),
    )

    tools = {t.name: t for t in build_calendar_tools(user_id, db)}
    assert "create_calendar_reminder" in tools

    result = tools["create_calendar_reminder"].invoke(
        {"title": "Dentista", "when": "2026-09-23T10:00:00", "duration_minutes": 30}
    )

    assert "Listo" in result
    assert captured["calendarId"] == "primary"
    assert captured["body"]["summary"] == "Dentista"
    assert captured["body"]["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 10}],
    }
    assert "2026-09-23T10:00:00" in captured["body"]["start"]["dateTime"]


def test_oauth_authorize_requests_events_scope():
    email = f"test-scope-{uuid.uuid4().hex[:8]}@eliseo.dev"
    client.post("/auth/register", json={"email": email, "password": "una-clave-segura-123"})
    token = client.post("/auth/login", json={"email": email, "password": "una-clave-segura-123"}).json()[
        "access_token"
    ]
    response = client.get(
        "/connectors/google_calendar/authorize",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert "calendar.events" in url
    # Necesario para leer TODOS los calendarios de la cuenta, no solo "primary".
    assert "calendar.calendarlist.readonly" in url


@pytest.mark.asyncio
async def test_get_tools_for_user_includes_calendar_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tools = await get_tools_for_user(user_id, db)
    names = [t.name for t in tools]

    assert set(BUILTIN_TOOL_NAMES).issubset(names)
    assert names[-2:] == [
        "get_upcoming_calendar_events",
        "create_calendar_reminder",
    ]


@pytest.mark.asyncio
async def test_calendar_connector_without_credential_gives_no_tool(db):
    user_id = _new_user(db)
    db.add(UserConnector(user_id=user_id, service_name="google_calendar", scope="read_only"))
    db.commit()

    assert sorted(t.name for t in await get_tools_for_user(user_id, db)) == sorted(BUILTIN_TOOL_NAMES)


@pytest.mark.asyncio
async def test_credential_without_connector_gives_no_tool(db):
    """Si el usuario desconectó el servicio, la herramienta no se carga aunque quede la fila."""
    user_id = _new_user(db)
    db.add(GoogleCalendarCredential(user_id=user_id, refresh_token_encrypted=encrypt("x")))
    db.commit()

    assert sorted(t.name for t in await get_tools_for_user(user_id, db)) == sorted(BUILTIN_TOOL_NAMES)

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
    assert query["scope"] == [
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
    ]
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
    assert "cerrar esta pestaña" in response.text or "volver a Eliseo" in response.text

    credential = db.query(GoogleCalendarCredential).filter_by(user_id=user_id).one()
    assert credential.refresh_token_encrypted != "1//token-real"  # no queda en texto plano
    assert decrypt(credential.refresh_token_encrypted) == "1//token-real"

    connector = db.query(UserConnector).filter_by(user_id=user_id, service_name="google_calendar").one()
    assert connector.scope == "read_only"
    assert connector.store_credential is True


def test_callback_redirects_to_app_deep_link_when_present(db, monkeypatch):
    user_id = _new_user(db)
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "1//token-real")
    state = create_oauth_state(user_id, app_redirect="exp://192.168.1.10:8081/--/oauth")

    response = client.get(
        "/connectors/google_calendar/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("exp://192.168.1.10:8081/--/oauth")
    assert "connected=google_calendar" in response.headers["location"]


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


def test_callback_reports_a_clear_error_when_saving_the_credential_fails(db, monkeypatch):
    """
    Regresión: Google ya autorizó (el code se canjeó bien) pero guardar la
    credencial falla después (ej. columna faltante por una migración no
    aplicada) — antes esto tiraba un 500 crudo y el usuario creía que había
    quedado conectado, sin que ninguna fila se guardara.
    """
    user_id = _new_user(db)
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "1//token-real")

    def boom(*args, **kwargs):
        raise RuntimeError("column google_calendar_credentials.account_label does not exist")

    monkeypatch.setattr(google_calendar, "encrypt", boom)

    response = client.get(
        "/connectors/google_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id)}
    )

    assert response.status_code == 400
    assert "no se pudo guardar la conexión" in response.text
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id).count() == 0
    assert db.query(UserConnector).filter_by(user_id=user_id, service_name="google_calendar").count() == 0


def test_callback_shows_the_real_error_when_saving_fails_and_oauth_debug_is_on(db, monkeypatch):
    monkeypatch.setattr(settings, "oauth_debug", True)
    user_id = _new_user(db)
    monkeypatch.setattr(google_calendar, "_exchange_code_for_refresh_token", lambda code: "1//token-real")

    def boom(*args, **kwargs):
        raise RuntimeError("column google_calendar_credentials.account_label does not exist")

    monkeypatch.setattr(google_calendar, "encrypt", boom)

    response = client.get(
        "/connectors/google_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id)}
    )

    assert response.status_code == 400
    assert "account_label does not exist" in response.text


def test_disconnecting_deletes_the_stored_refresh_token(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    response = client.delete("/connectors/google_calendar", headers=_auth_header(user_id))

    assert response.status_code == 200
    db.expire_all()
    assert db.query(GoogleCalendarCredential).filter_by(user_id=user_id).count() == 0
    assert db.query(UserConnector).filter_by(user_id=user_id).count() == 0
