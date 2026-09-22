import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_register_login_and_me():
    # Email único por corrida: la base de test persiste entre ejecuciones.
    email = f"test-t02-{uuid.uuid4().hex[:8]}@eliseo.dev"
    password = "una-clave-segura-123"

    # Registro
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    assert response.json()["email"] == email

    # Registrar el mismo email de nuevo debe fallar
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 400

    # Login
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert token

    # Ruta protegida sin token
    response = client.get("/auth/me")
    assert response.status_code in (401, 403)

    # Ruta protegida con token
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["persona"] == "elisse"


def test_patch_me_updates_persona():
    email = f"test-persona-{uuid.uuid4().hex[:8]}@eliseo.dev"
    password = "una-clave-segura-123"

    assert client.post("/auth/register", json={"email": email, "password": password}).status_code == 201
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch("/auth/me", json={"persona": "eliseo"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["persona"] == "eliseo"

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["persona"] == "eliseo"

    bad = client.patch("/auth/me", json={"persona": "otro"}, headers=headers)
    assert bad.status_code == 422
