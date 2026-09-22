"""
Voz de Eliseo (HU-T07): transcripción (STT) y síntesis (TTS) con Deepgram,
vía su API REST directo con httpx — mismo estilo que Mercado Pago, sin el
SDK de Deepgram. Reemplaza el script suelto de voice-sandbox.

Todavía no se conecta con /chat acá: eso es responsabilidad de T08, del
lado de la app (manda el transcript a /chat, y la respuesta a /voice/speak).
"""

import httpx

from app.core.config import settings

STT_URL = "https://api.deepgram.com/v1/listen"
TTS_URL = "https://api.deepgram.com/v1/speak"

# Persona del usuario -> modelo TTS de Deepgram (español).
PERSONA_TTS_MODEL = {
    "elisse": "aura-2-celeste-es",  # femenina
    "eliseo": "aura-2-aquila-es",  # masculina, español latino (es-419)
}
DEFAULT_PERSONA = "eliseo"


def _auth_headers() -> dict:
    if not settings.deepgram_api_key:
        raise RuntimeError("Falta DEEPGRAM_API_KEY en la configuración.")
    return {"Authorization": f"Token {settings.deepgram_api_key}"}


def tts_model_for_persona(persona: str) -> str:
    return PERSONA_TTS_MODEL.get(persona, PERSONA_TTS_MODEL[DEFAULT_PERSONA])


async def transcribe_audio(audio_bytes: bytes, content_type: str = "audio/mp3") -> str:
    """Transcribe un audio a texto (español) con Deepgram nova-3."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            STT_URL,
            params={"model": "nova-3", "language": "es"},
            headers={**_auth_headers(), "Content-Type": content_type},
            content=audio_bytes,
            timeout=30,
        )
    response.raise_for_status()
    return response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


async def synthesize_speech(text: str, persona: str = DEFAULT_PERSONA) -> bytes:
    """Convierte texto en voz según la persona del usuario. Devuelve el audio en bytes."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TTS_URL,
            params={"model": tts_model_for_persona(persona)},
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"text": text},
            timeout=30,
        )
    response.raise_for_status()
    return response.content
