"""
Tests de HU-T22 (Microsoft Teams/Outlook Calendar, multi-cuenta desde el
vamos). No le pegan a Microsoft real: el canje del code y la llamada a
Graph se reemplazan.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.agents import orchestrator
from app.agents.orchestrator import build_teams_calendar_tool, get_tools_for_user
from app.api.routes import teams_calendar as teams_routes
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal
from app.core.security import create_access_token, create_oauth_state, decode_oauth_state
from app.main import app
from app.models.connector import UserConnector
from app.models.teams_calendar_credential import TeamsCalendarCredential
from app.models.user import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def ms_settings(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "ms_client_id", "ms-client-id-de-prueba")
    monkeypatch.setattr(settings, "ms_client_secret", "ms-client-secret-de-prueba")
    monkeypatch.setattr(settings, "ms_tenant", "common")


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _new_user(db) -> int:
    user = User(email=f"test-t22-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    return user.id


def _add_credential(db, user_id: int, account_label: str = "default", expires_at=None, access_token: str = "eyJ.access.de-prueba"):
    db.add(
        TeamsCalendarCredential(
            user_id=user_id,
            account_label=account_label,
            access_token_encrypted=encrypt(access_token),
            refresh_token_encrypted=encrypt("refresh-de-prueba"),
            expires_at=expires_at or datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db.add(
        UserConnector(
            user_id=user_id, service_name="teams_calendar", account_label=account_label, scope="read_only", store_credential=True
        )
    )
    db.commit()


def _auth_header(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


class FakeGraphResponse:
    def __init__(self, status_code=200, events=None):
        self.status_code = status_code
        self._events = events or []

    def json(self):
        return {"value": self._events}


@pytest.fixture
def fake_graph(monkeypatch):
    state = {"response": FakeGraphResponse(), "calls": []}

    def fake_get(url, **kwargs):
        state["calls"].append({"url": url, **kwargs})
        return state["response"]

    monkeypatch.setattr(orchestrator.httpx, "get", fake_get)
    return state


# --- herramienta del agente (los 4 casos de la spec)


# 1. Usuario sin TeamsCalendarCredential para un account_label -> None
def test_build_teams_calendar_tool_without_credential_returns_none(db):
    assert build_teams_calendar_tool(_new_user(db), db) is None
    assert build_teams_calendar_tool(_new_user(db), db, "banco") is None


# 2. Usuario CON una fila de prueba -> devuelve algo no-None
def test_build_teams_calendar_tool_with_credential_builds_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tool = build_teams_calendar_tool(user_id, db)

    assert tool is not None
    assert tool.name == "get_teams_calendar_events"  # "default": sin sufijo


# 3. Usuario con 2 filas (labels distintos) -> get_tools_for_user da 2 tools nombradas distinto
@pytest.mark.asyncio
async def test_get_tools_for_user_returns_one_tool_per_teams_account(db):
    user_id = _new_user(db)
    _add_credential(db, user_id, "banco")
    _add_credential(db, user_id, "agencia")

    tools = await get_tools_for_user(user_id, db)

    assert sorted(t.name for t in tools) == [
        "get_current_datetime",
        "get_teams_calendar_events_agencia",
        "get_teams_calendar_events_banco",
        "get_weather",
    ]


# 4. Token vencido -> la tool devuelve un mensaje pidiendo reconectar esa cuenta, no rompe el agente
def test_teams_tool_asks_to_reconnect_when_token_expired(db, fake_graph):
    user_id = _new_user(db)
    _add_credential(db, user_id, "banco", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    result = build_teams_calendar_tool(user_id, db, "banco").invoke({})

    assert "volver a conectar" in result
    assert "'banco'" in result
    assert fake_graph["calls"] == []  # ni siquiera intenta llamar a Microsoft


# --- comportamiento de la herramienta contra Graph


def test_teams_tool_returns_events_formatted_as_text(db, fake_graph):
    user_id = _new_user(db)
    _add_credential(db, user_id, access_token="el-token-del-usuario")
    fake_graph["response"] = FakeGraphResponse(
        200,
        [
            {"start": {"dateTime": "2026-09-25T14:00:00.0000000"}, "subject": "Reunión de equipo"},
            {"start": {"dateTime": "2026-09-26T09:30:00.0000000"}, "subject": "Dentista"},
        ],
    )

    result = build_teams_calendar_tool(user_id, db).invoke({})

    assert result == "2026-09-25T14:00:00.0000000 — Reunión de equipo\n2026-09-26T09:30:00.0000000 — Dentista"
    call = fake_graph["calls"][0]
    assert call["url"] == "https://graph.microsoft.com/v1.0/me/calendarview"
    assert call["headers"]["Authorization"] == "Bearer el-token-del-usuario"
    assert call["params"]["$orderby"] == "start/dateTime"


def test_teams_tool_no_events(db, fake_graph):
    user_id = _new_user(db)
    _add_credential(db, user_id)
    fake_graph["response"] = FakeGraphResponse(200, [])

    assert "No hay eventos" in build_teams_calendar_tool(user_id, db).invoke({})


@pytest.mark.parametrize(
    "status_code, expected",
    [
        (401, "volver a conectar"),  # token revocado desde Microsoft
        (403, "volver a conectar"),
        (500, "No pude leer el calendario de Teams"),
    ],
)
def test_teams_tool_handles_graph_errors(db, fake_graph, status_code, expected):
    user_id = _new_user(db)
    _add_credential(db, user_id)
    fake_graph["response"] = FakeGraphResponse(status_code)

    assert expected in build_teams_calendar_tool(user_id, db).invoke({})


def test_teams_tool_handles_connection_failure(db, monkeypatch):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    def boom(url, **kwargs):
        raise ConnectionError("timeout")

    monkeypatch.setattr(orchestrator.httpx, "get", boom)

    assert "No pude leer el calendario de Teams" in build_teams_calendar_tool(user_id, db).invoke({})


# --- desconectar borra la credencial guardada


def test_disconnecting_deletes_the_stored_credential(db):
    user_id = _new_user(db)
    _add_credential(db, user_id, "banco")

    response = client.delete("/connectors/teams_calendar", params={"account_label": "banco"}, headers=_auth_header(user_id))

    assert response.status_code == 200
    db.expire_all()
    assert db.query(TeamsCalendarCredential).filter_by(user_id=user_id, account_label="banco").count() == 0
    assert db.query(UserConnector).filter_by(user_id=user_id, service_name="teams_calendar").count() == 0


# --- rutas OAuth


def test_authorize_requires_login():
    assert client.get("/connectors/teams_calendar/authorize").status_code in (401, 403)


def test_authorize_returns_microsoft_url_with_signed_state_and_account_label(db):
    user_id = _new_user(db)

    response = client.get(
        "/connectors/teams_calendar/authorize", params={"account_label": "agencia"}, headers=_auth_header(user_id)
    )

    assert response.status_code == 200
    url = urlparse(response.json()["authorize_url"])
    query = parse_qs(url.query)
    assert url.netloc == "login.microsoftonline.com"
    assert url.path == "/common/oauth2/v2.0/authorize"
    assert query["client_id"] == ["ms-client-id-de-prueba"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [settings.ms_redirect_uri]
    assert query["scope"] == ["Calendars.Read offline_access"]
    assert decode_oauth_state(query["state"][0]) == (user_id, "agencia")


def test_authorize_uses_the_configured_tenant(db, monkeypatch):
    monkeypatch.setattr(settings, "ms_tenant", "mi-org.onmicrosoft.com")
    response = client.get("/connectors/teams_calendar/authorize", headers=_auth_header(_new_user(db)))

    assert "/mi-org.onmicrosoft.com/oauth2/v2.0/authorize" in response.json()["authorize_url"]


def test_authorize_without_microsoft_configured_is_503(db, monkeypatch):
    monkeypatch.setattr(settings, "ms_client_id", "")

    assert client.get("/connectors/teams_calendar/authorize", headers=_auth_header(_new_user(db))).status_code == 503


def test_callback_stores_the_credential_under_its_account_label(db, monkeypatch):
    user_id = _new_user(db)
    monkeypatch.setattr(
        teams_routes,
        "_exchange_code_for_tokens",
        lambda code: {"access_token": "token-real", "refresh_token": "refresh-real", "expires_in": 3600},
    )

    response = client.get(
        "/connectors/teams_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id, "banco")}
    )

    assert response.status_code == 200
    assert "cerrar esta pestaña" in response.text

    credential = db.query(TeamsCalendarCredential).filter_by(user_id=user_id).one()
    assert credential.account_label == "banco"
    assert "token-real" not in credential.access_token_encrypted  # nada en texto plano
    assert decrypt(credential.access_token_encrypted) == "token-real"
    assert decrypt(credential.refresh_token_encrypted) == "refresh-real"

    connector = db.query(UserConnector).filter_by(user_id=user_id, service_name="teams_calendar").one()
    assert connector.account_label == "banco"
    assert connector.scope == "read_only"


def test_connecting_two_teams_accounts_does_not_collide(db, monkeypatch):
    tokens = iter([{"access_token": "token-banco"}, {"access_token": "token-agencia"}])
    monkeypatch.setattr(teams_routes, "_exchange_code_for_tokens", lambda code: next(tokens))
    user_id = _new_user(db)

    client.get("/connectors/teams_calendar/callback", params={"code": "a", "state": create_oauth_state(user_id, "banco")})
    client.get("/connectors/teams_calendar/callback", params={"code": "b", "state": create_oauth_state(user_id, "agencia")})

    credentials = {c.account_label: decrypt(c.access_token_encrypted) for c in db.query(TeamsCalendarCredential).filter_by(user_id=user_id)}
    assert credentials == {"banco": "token-banco", "agencia": "token-agencia"}


@pytest.mark.parametrize(
    "params",
    [
        {"code": "abc"},  # sin state
        {"code": "abc", "state": "falsificado"},  # state inválido
        {"state": "se-completa-abajo"},  # sin code
        {"error": "access_denied"},  # el usuario canceló en Microsoft
    ],
)
def test_callback_rejects_invalid_requests(db, monkeypatch, params):
    user_id = _new_user(db)
    monkeypatch.setattr(teams_routes, "_exchange_code_for_tokens", lambda code: {"access_token": "no-deberia-usarse"})
    if params.get("state") == "se-completa-abajo":
        params = {"state": create_oauth_state(user_id)}

    response = client.get("/connectors/teams_calendar/callback", params=params)

    assert response.status_code == 400
    assert db.query(TeamsCalendarCredential).filter_by(user_id=user_id).count() == 0


def test_callback_microsoft_failure_is_400_and_stores_nothing(db, monkeypatch):
    user_id = _new_user(db)

    def boom(code):
        raise RuntimeError("Microsoft rechazó el code")

    monkeypatch.setattr(teams_routes, "_exchange_code_for_tokens", boom)

    response = client.get(
        "/connectors/teams_calendar/callback", params={"code": "abc", "state": create_oauth_state(user_id)}
    )

    assert response.status_code == 400
    assert db.query(TeamsCalendarCredential).filter_by(user_id=user_id).count() == 0


def test_code_exchange_uses_form_encoded_body_not_json(monkeypatch):
    """Microsoft exige application/x-www-form-urlencoded en /token — a diferencia de Mercado Pago (JSON)."""
    sent = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"access_token": "x"}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch.setattr(teams_routes.httpx, "post", fake_post)

    teams_routes._exchange_code_for_tokens("el-code")

    assert sent["url"] == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    assert "json" not in sent  # nada de JSON
    assert sent["data"] == {
        "grant_type": "authorization_code",
        "client_id": "ms-client-id-de-prueba",
        "client_secret": "ms-client-secret-de-prueba",
        "code": "el-code",
        "redirect_uri": settings.ms_redirect_uri,
        "scope": "Calendars.Read offline_access",
    }
