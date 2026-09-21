"""
Tests de HU-T04: qué herramientas carga el agente según los conectores del
usuario. Prueban get_tools_for_user directo — no llaman a la API de Anthropic.
"""

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.agents import orchestrator
from app.agents.orchestrator import SERVICE_MCP_REGISTRY, get_tools_for_user
from app.core.database import SessionLocal
from app.main import app
from app.models.connector import UserConnector
from app.models.user import User

SANDBOX_SERVER = Path(__file__).resolve().parent.parent / "mcp_servers" / "sandbox_server.py"


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _new_user(db, *services) -> int:
    """Crea un usuario (email único: la base de test persiste) con los conectores dados."""
    user = User(email=f"test-t04-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    for service in services:
        db.add(UserConnector(user_id=user.id, service_name=service, scope="read_only"))
    db.commit()
    return user.id


@pytest.fixture(scope="module")
def sandbox_mcp():
    """Levanta el servidor MCP de prueba en un puerto libre y apunta el registro a él."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [sys.executable, str(SANDBOX_SERVER)],
        env={**os.environ, "MCP_PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("El servidor MCP de prueba no arrancó.")

        original = SERVICE_MCP_REGISTRY["sandbox"]
        SERVICE_MCP_REGISTRY["sandbox"] = {"url": f"http://127.0.0.1:{port}/mcp", "transport": "streamable_http"}
        yield
        SERVICE_MCP_REGISTRY["sandbox"] = original
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.asyncio
async def test_user_without_connectors_gets_no_tools(db, monkeypatch):
    class FailIfUsed:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Sin conectores no se debería crear ningún cliente MCP.")

    monkeypatch.setattr(orchestrator, "MultiServerMCPClient", FailIfUsed)

    assert await get_tools_for_user(_new_user(db), db) == []


@pytest.mark.asyncio
async def test_user_with_sandbox_connector_gets_datetime_tool(db, sandbox_mcp):
    tools = await get_tools_for_user(_new_user(db, "sandbox"), db)

    assert "get_current_datetime" in [tool.name for tool in tools]


@pytest.mark.asyncio
async def test_connector_not_in_registry_is_ignored(db, monkeypatch):
    class FailIfUsed:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Un conector sin servidor registrado no debería abrir conexión MCP.")

    monkeypatch.setattr(orchestrator, "MultiServerMCPClient", FailIfUsed)

    assert await get_tools_for_user(_new_user(db, "algo_que_no_existe_en_el_registry", "whatsapp"), db) == []


@pytest.mark.asyncio
async def test_tools_are_per_user_and_revocable(db, sandbox_mcp):
    with_sandbox = _new_user(db, "sandbox")
    without = _new_user(db)

    assert await get_tools_for_user(with_sandbox, db)
    assert await get_tools_for_user(without, db) == []  # no hereda las herramientas de otro usuario

    db.query(UserConnector).filter(UserConnector.user_id == with_sandbox).delete()
    db.commit()
    assert await get_tools_for_user(with_sandbox, db) == []  # revocar el conector quita la herramienta


def test_chat_passes_authenticated_user_to_orchestrator(monkeypatch):
    received = {}

    async def fake_handle_user_message(message, user_id, db):
        received.update(message=message, user_id=user_id, db=db)
        return "ok"

    monkeypatch.setattr("app.api.routes.chat.handle_user_message", fake_handle_user_message)

    client = TestClient(app)
    email = f"test-t04-{uuid.uuid4().hex[:8]}@eliseo.dev"
    password = "una-clave-segura-123"
    user_id = client.post("/auth/register", json={"email": email, "password": password}).json()["id"]
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]

    response = client.post("/chat", json={"message": "hola"}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert received["user_id"] == user_id
    assert received["message"] == "hola"
    assert received["db"] is not None
