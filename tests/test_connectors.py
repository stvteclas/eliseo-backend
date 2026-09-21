import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _login_new_user() -> dict:
    """Registra un usuario nuevo (email único: la base de test persiste) y devuelve su header de auth."""
    email = f"test-t15-{uuid.uuid4().hex[:8]}@eliseo.dev"
    password = "una-clave-segura-123"
    assert client.post("/auth/register", json={"email": email, "password": password}).status_code == 201
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_connectors_crud():
    # 1. Sin login
    response = client.post("/connectors", json={"service_name": "google_calendar", "scope": "read_only"})
    assert response.status_code in (401, 403)

    headers = _login_new_user()

    # 2. Crear
    response = client.post(
        "/connectors", json={"service_name": "google_calendar", "scope": "read_only"}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["service_name"] == "google_calendar"
    assert body["scope"] == "read_only"
    assert body["store_credential"] is False
    assert body["connected_at"]
    connector_id = body["id"]

    # 3. Mismo servicio con otro scope: actualiza, no duplica
    response = client.post(
        "/connectors",
        json={"service_name": "google_calendar", "scope": "read_write", "store_credential": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == connector_id
    assert response.json()["scope"] == "read_write"
    assert response.json()["store_credential"] is True

    # 4. Listar
    response = client.get("/connectors", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["scope"] == "read_write"

    # 5. Borrar, y la lista queda vacía
    response = client.delete("/connectors/google_calendar", headers=headers)
    assert response.status_code == 200
    assert client.get("/connectors", headers=headers).json() == []

    # 6. Borrar algo que no existe
    response = client.delete("/connectors/google_calendar", headers=headers)
    assert response.status_code == 404


def test_connectors_are_per_user():
    headers_a = _login_new_user()
    headers_b = _login_new_user()

    client.post("/connectors", json={"service_name": "mercadopago", "scope": "read_only"}, headers=headers_a)

    assert client.get("/connectors", headers=headers_b).json() == []
    assert client.delete("/connectors/mercadopago", headers=headers_b).status_code == 404
    assert len(client.get("/connectors", headers=headers_a).json()) == 1
