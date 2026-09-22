"""
Tests de HU-T07 (voz en el backend: Deepgram STT/TTS). No le pegan a
Deepgram real: se reemplaza httpx.AsyncClient.post.
"""

import os
import uuid

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.services.voice import synthesize_speech, transcribe_audio

client = TestClient(app)


@pytest.fixture(autouse=True)
def deepgram_key(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "deepgram-key-de-prueba")


def _auth_header() -> dict:
    from app.core.database import SessionLocal

    db = SessionLocal()
    user = User(email=f"test-t07-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="no-se-usa")
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return {"Authorization": f"Bearer {token}"}


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def _mock_post(monkeypatch, response: FakeResponse):
    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


DEEPGRAM_TRANSCRIBE_BODY = {
    "results": {"channels": [{"alternatives": [{"transcript": "¿qué hora es?"}]}]}
}


# --- servicio (sin pasar por la ruta)


@pytest.mark.asyncio
async def test_transcribe_audio_returns_the_transcript(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(json_data=DEEPGRAM_TRANSCRIBE_BODY))

    transcript = await transcribe_audio(b"bytes-de-audio", content_type="audio/wav")

    assert transcript == "¿qué hora es?"
    call = calls[0]
    assert call["url"] == "https://api.deepgram.com/v1/listen"
    assert call["params"] == {"model": "nova-3", "language": "es"}
    assert call["headers"]["Authorization"] == "Token deepgram-key-de-prueba"
    assert call["headers"]["Content-Type"] == "audio/wav"
    assert call["content"] == b"bytes-de-audio"


@pytest.mark.asyncio
async def test_synthesize_speech_returns_audio_bytes(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(content=b"bytes-de-audio-mp3"))

    audio = await synthesize_speech("Son las 12 del mediodía.")

    assert audio == b"bytes-de-audio-mp3"
    call = calls[0]
    assert call["url"] == "https://api.deepgram.com/v1/speak"
    assert call["params"] == {"model": "aura-2-aquila-es"}
    assert call["json"] == {"text": "Son las 12 del mediodía."}
    assert call["headers"]["Authorization"] == "Token deepgram-key-de-prueba"


@pytest.mark.asyncio
async def test_synthesize_speech_uses_masculine_voice_for_eliseo(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(content=b"bytes-mp3"))

    await synthesize_speech("Hola", persona="eliseo")

    assert calls[0]["params"] == {"model": "aura-2-aquila-es"}


@pytest.mark.asyncio
async def test_synthesize_speech_uses_feminine_voice_for_elisse(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(content=b"bytes-mp3"))

    await synthesize_speech("Hola", persona="elisse")

    assert calls[0]["params"] == {"model": "aura-2-celeste-es"}


@pytest.mark.asyncio
async def test_transcribe_without_deepgram_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "")

    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        await transcribe_audio(b"x")


@pytest.mark.asyncio
async def test_transcribe_propagates_deepgram_errors(monkeypatch):
    _mock_post(monkeypatch, FakeResponse(status_code=400))

    with pytest.raises(httpx.HTTPStatusError):
        await transcribe_audio(b"x")


# --- rutas


def test_transcribe_requires_login():
    response = client.post("/voice/transcribe", files={"audio": ("audio.wav", b"x", "audio/wav")})
    assert response.status_code in (401, 403)


def test_speak_requires_login():
    assert client.post("/voice/speak", json={"text": "hola"}).status_code in (401, 403)


def test_transcribe_endpoint_returns_the_transcript(monkeypatch):
    _mock_post(monkeypatch, FakeResponse(json_data=DEEPGRAM_TRANSCRIBE_BODY))
    headers = _auth_header()

    response = client.post(
        "/voice/transcribe", files={"audio": ("audio.wav", b"bytes-de-audio", "audio/wav")}, headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "¿qué hora es?"}


def test_speak_endpoint_returns_audio_mpeg(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(content=b"bytes-de-audio-mp3"))
    headers = _auth_header()

    response = client.post("/voice/speak", json={"text": "hola"}, headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"bytes-de-audio-mp3"
    # Usuario nuevo default = eliseo → Aquila (latino masculino)
    assert calls[0]["params"] == {"model": "aura-2-aquila-es"}


def test_speak_endpoint_uses_user_persona_voice(monkeypatch):
    calls = _mock_post(monkeypatch, FakeResponse(content=b"bytes-mp3"))
    headers = _auth_header()

    patched = client.patch("/auth/me", json={"persona": "eliseo"}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["persona"] == "eliseo"

    response = client.post("/voice/speak", json={"text": "hola"}, headers=headers)
    assert response.status_code == 200
    assert calls[-1]["params"] == {"model": "aura-2-aquila-es"}


def test_transcribe_without_deepgram_configured_is_503(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    headers = _auth_header()

    response = client.post(
        "/voice/transcribe", files={"audio": ("audio.wav", b"x", "audio/wav")}, headers=headers
    )

    assert response.status_code == 503


def test_speak_without_deepgram_configured_is_503(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    headers = _auth_header()

    assert client.post("/voice/speak", json={"text": "hola"}, headers=headers).status_code == 503
