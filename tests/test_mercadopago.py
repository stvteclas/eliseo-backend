"""
Tests de HU-T20 (Mercado Pago por usuario). No le pegan a la API real de
Mercado Pago: el canje del code y el SDK se reemplazan.
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
from app.agents.orchestrator import build_mercadopago_tool, get_tools_for_user
from app.api.routes import mercadopago as mp_routes
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal
from app.core.security import create_access_token, create_oauth_state, decode_oauth_state
from app.main import app
from app.models.connector import UserConnector
from app.models.mercadopago_credential import MercadoPagoCredential
from app.models.user import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def mp_settings(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "mp_client_id", "mp-client-id-de-prueba")
    monkeypatch.setattr(settings, "mp_client_secret", "mp-client-secret-de-prueba")


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


class FakeSDK:
    """Reemplaza mercadopago.SDK: registra qué se le pidió y devuelve la respuesta configurada."""

    result: dict = {}
    token: str | None = None
    created: list = []

    def __init__(self, access_token):
        FakeSDK.token = access_token

    def preference(self):
        return self

    def create(self, data):
        FakeSDK.created.append(data)
        return FakeSDK.result


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeSDK.created = []
    FakeSDK.token = None
    FakeSDK.result = {"status": 201, "response": {"init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=123"}}
    monkeypatch.setattr(orchestrator.mercadopago, "SDK", FakeSDK)
    return FakeSDK


def _new_user(db) -> int:
    user = User(email=f"test-t20-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    return user.id


def _add_credential(db, user_id: int, expires_at=None, access_token: str = "APP_USR-token-de-prueba"):
    db.add(
        MercadoPagoCredential(
            user_id=user_id,
            mp_user_id="123456",
            access_token_encrypted=encrypt(access_token),
            refresh_token_encrypted=encrypt("TG-refresh-de-prueba"),
            expires_at=expires_at or datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    db.add(UserConnector(user_id=user_id, service_name="mercadopago", scope="read_write", store_credential=True))
    db.commit()


def _auth_header(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# --- herramienta del agente


def test_build_mercadopago_tool_without_credential_returns_none(db):
    assert build_mercadopago_tool(_new_user(db), db) is None


def test_build_mercadopago_tool_with_credential_builds_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    tool = build_mercadopago_tool(user_id, db)

    assert tool is not None
    assert tool.name == "create_payment_link"


@pytest.mark.asyncio
async def test_get_tools_for_user_includes_payment_tool(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    assert [t.name for t in await get_tools_for_user(user_id, db)] == ["create_payment_link"]


@pytest.mark.asyncio
async def test_payment_connector_without_credential_gives_no_tool(db):
    user_id = _new_user(db)
    db.add(UserConnector(user_id=user_id, service_name="mercadopago", scope="read_write"))
    db.commit()

    assert await get_tools_for_user(user_id, db) == []


def test_disconnecting_deletes_the_stored_tokens(db):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    response = client.delete("/connectors/mercadopago", headers=_auth_header(user_id))

    assert response.status_code == 200
    db.expire_all()
    assert db.query(MercadoPagoCredential).filter_by(user_id=user_id).count() == 0
    assert db.query(UserConnector).filter_by(user_id=user_id).count() == 0


def test_payment_tool_creates_link_with_the_users_own_token(db, fake_sdk):
    user_id = _new_user(db)
    _add_credential(db, user_id, access_token="APP_USR-del-usuario")

    link = build_mercadopago_tool(user_id, db).invoke({"title": "Asado", "amount": 12500.5, "description": "Parte de la carne"})

    assert link == "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=123"
    assert fake_sdk.token == "APP_USR-del-usuario"  # cobra a favor del usuario, no de una cuenta de la app
    assert fake_sdk.created == [
        {
            "items": [
                {
                    "title": "Asado",
                    "description": "Parte de la carne",
                    "quantity": 1,
                    "currency_id": "ARS",
                    "unit_price": 12500.5,
                }
            ]
        }
    ]


def test_payment_tool_asks_to_reconnect_when_token_expired(db, fake_sdk):
    user_id = _new_user(db)
    _add_credential(db, user_id, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    result = build_mercadopago_tool(user_id, db).invoke({"title": "Asado", "amount": 100, "description": "x"})

    assert "volver a conectar" in result
    assert fake_sdk.created == []  # ni siquiera intenta llamar a Mercado Pago


@pytest.mark.parametrize("amount", [0, -50, float("inf"), float("nan")])
def test_payment_tool_rejects_invalid_amounts(db, fake_sdk, amount):
    user_id = _new_user(db)
    _add_credential(db, user_id)

    result = build_mercadopago_tool(user_id, db).invoke({"title": "Asado", "amount": amount, "description": "x"})

    assert "mayor a cero" in result
    assert fake_sdk.created == []


@pytest.mark.parametrize(
    "sdk_result, expected",
    [
        ({"status": 401, "response": {}}, "volver a conectar"),  # token revocado desde Mercado Pago
        ({"status": 500, "response": {}}, "No pude crear el link"),
    ],
)
def test_payment_tool_handles_mercadopago_errors(db, fake_sdk, sdk_result, expected):
    user_id = _new_user(db)
    _add_credential(db, user_id)
    fake_sdk.result = sdk_result

    result = build_mercadopago_tool(user_id, db).invoke({"title": "Asado", "amount": 100, "description": "x"})

    assert expected in result


# --- rutas OAuth


def test_authorize_requires_login():
    assert client.get("/connectors/mercadopago/authorize").status_code in (401, 403)


def test_authorize_returns_mercadopago_url_with_signed_state(db):
    user_id = _new_user(db)

    response = client.get("/connectors/mercadopago/authorize", headers=_auth_header(user_id))

    assert response.status_code == 200
    url = urlparse(response.json()["authorize_url"])
    query = parse_qs(url.query)
    assert url.netloc == "auth.mercadopago.com.ar"
    assert query["client_id"] == ["mp-client-id-de-prueba"]
    assert query["response_type"] == ["code"]
    assert query["platform_id"] == ["mp"]
    assert query["redirect_uri"] == [settings.mp_redirect_uri]
    assert decode_oauth_state(query["state"][0]) == user_id


def test_authorize_without_mercadopago_configured_is_503(db, monkeypatch):
    monkeypatch.setattr(settings, "mp_client_id", "")

    assert client.get("/connectors/mercadopago/authorize", headers=_auth_header(_new_user(db))).status_code == 503


def test_callback_stores_encrypted_tokens_and_connects_service(db, monkeypatch):
    user_id = _new_user(db)
    monkeypatch.setattr(
        mp_routes,
        "_exchange_code_for_tokens",
        lambda code: {"access_token": "APP_USR-real", "refresh_token": "TG-real", "user_id": 987654, "expires_in": 15552000},
    )

    response = client.get("/connectors/mercadopago/callback", params={"code": "abc", "state": create_oauth_state(user_id)})

    assert response.status_code == 200
    assert "cerrar esta pestaña" in response.text

    credential = db.query(MercadoPagoCredential).filter_by(user_id=user_id).one()
    assert credential.mp_user_id == "987654"
    assert "APP_USR-real" not in credential.access_token_encrypted  # nada en texto plano
    assert "TG-real" not in credential.refresh_token_encrypted
    assert decrypt(credential.access_token_encrypted) == "APP_USR-real"
    assert decrypt(credential.refresh_token_encrypted) == "TG-real"
    expires_in = credential.expires_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(days=179) < expires_in < timedelta(days=181)

    connector = db.query(UserConnector).filter_by(user_id=user_id, service_name="mercadopago").one()
    assert connector.scope == "read_write"
    assert connector.store_credential is True


def test_callback_twice_updates_instead_of_duplicating(db, monkeypatch):
    user_id = _new_user(db)
    tokens = iter(["APP_USR-primero", "APP_USR-segundo"])
    monkeypatch.setattr(
        mp_routes, "_exchange_code_for_tokens", lambda code: {"access_token": next(tokens), "user_id": 1, "expires_in": 100}
    )
    params = {"code": "abc", "state": create_oauth_state(user_id)}

    assert client.get("/connectors/mercadopago/callback", params=params).status_code == 200
    assert client.get("/connectors/mercadopago/callback", params=params).status_code == 200

    credential = db.query(MercadoPagoCredential).filter_by(user_id=user_id).one()
    assert decrypt(credential.access_token_encrypted) == "APP_USR-segundo"
    assert credential.refresh_token_encrypted is None  # esta vez MP no mandó refresh token
    assert db.query(UserConnector).filter_by(user_id=user_id, service_name="mercadopago").count() == 1


@pytest.mark.parametrize(
    "params",
    [
        {"code": "abc"},  # sin state
        {"code": "abc", "state": "falsificado"},  # state inválido
        {"state": "se-completa-abajo"},  # sin code
        {"error": "access_denied"},  # el usuario canceló en Mercado Pago
    ],
)
def test_callback_rejects_invalid_requests(db, monkeypatch, params):
    user_id = _new_user(db)
    monkeypatch.setattr(
        mp_routes, "_exchange_code_for_tokens", lambda code: {"access_token": "no-deberia-usarse", "user_id": 1}
    )
    if params.get("state") == "se-completa-abajo":
        params = {"state": create_oauth_state(user_id)}

    response = client.get("/connectors/mercadopago/callback", params=params)

    assert response.status_code == 400
    assert db.query(MercadoPagoCredential).filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize("failure", ["error", "sin_access_token"])
def test_callback_mercadopago_failure_is_400_and_stores_nothing(db, monkeypatch, failure):
    user_id = _new_user(db)

    def exchange(code):
        if failure == "error":
            raise RuntimeError("Mercado Pago rechazó el code")
        return {"user_id": 1}  # respuesta sin access_token

    monkeypatch.setattr(mp_routes, "_exchange_code_for_tokens", exchange)

    response = client.get("/connectors/mercadopago/callback", params={"code": "abc", "state": create_oauth_state(user_id)})

    assert response.status_code == 400
    assert db.query(MercadoPagoCredential).filter_by(user_id=user_id).count() == 0


def test_code_exchange_sends_the_expected_request(monkeypatch):
    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "APP_USR-x", "user_id": 1}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch.setattr(mp_routes.httpx, "post", fake_post)

    assert mp_routes._exchange_code_for_tokens("el-code")["access_token"] == "APP_USR-x"
    assert sent["url"] == "https://api.mercadopago.com/oauth/token"
    assert sent["json"] == {
        "grant_type": "authorization_code",
        "client_id": "mp-client-id-de-prueba",
        "client_secret": "mp-client-secret-de-prueba",
        "code": "el-code",
        "redirect_uri": settings.mp_redirect_uri,
    }
