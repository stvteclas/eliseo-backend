"""
Voz de Eliseo (HU-T07): transcripción (STT) y síntesis (TTS).

STT: Deepgram nova-3. En modo traductor prueba cada idioma del par y
elige el de mayor confianza (así el ruso no se fuerza a español).
TTS: Deepgram Aura-2 para es/en; edge-tts para ruso y otros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import edge_tts
import httpx

from app.core.config import settings

STT_URL = "https://api.deepgram.com/v1/listen"
TTS_URL = "https://api.deepgram.com/v1/speak"

PERSONA_TTS_MODEL = {
    "elisse": "aura-2-celeste-es",
    "eliseo": "aura-2-sirio-es",
}
DEFAULT_PERSONA = "eliseo"

DEEPGRAM_LANG_MODEL = {
    "es": {
        "eliseo": "aura-2-sirio-es",
        "elisse": "aura-2-celeste-es",
    },
    "en": {
        "eliseo": "aura-2-odysseus-en",
        "elisse": "aura-2-thalia-en",
    },
}
EDGE_TTS_VOICE = {
    "ru": {
        "eliseo": "ru-RU-DmitryNeural",
        "elisse": "ru-RU-SvetlanaNeural",
    },
    "pt": {
        "eliseo": "pt-BR-AntonioNeural",
        "elisse": "pt-BR-FranciscaNeural",
    },
    "fr": {
        "eliseo": "fr-FR-HenriNeural",
        "elisse": "fr-FR-DeniseNeural",
    },
    "de": {
        "eliseo": "de-DE-ConradNeural",
        "elisse": "de-DE-KatjaNeural",
    },
    "it": {
        "eliseo": "it-IT-DiegoNeural",
        "elisse": "it-IT-ElsaNeural",
    },
}

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_SHORTCODE_RE = re.compile(r":[a-z0-9_+\-]+:", flags=re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


@dataclass
class TranscriptResult:
    transcript: str
    language: str | None = None
    confidence: float = 0.0


def text_for_speech(text: str) -> str:
    cleaned = _EMOJI_RE.sub(" ", text or "")
    cleaned = _SHORTCODE_RE.sub(" ", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned or " "


def detect_speech_language(text: str, hint: str | None = None) -> str:
    if hint:
        return hint.strip().lower()[:2]
    if _CYRILLIC_RE.search(text or ""):
        return "ru"
    return "es"


def _auth_headers() -> dict:
    if not settings.deepgram_api_key:
        raise RuntimeError("Falta DEEPGRAM_API_KEY en la configuración.")
    return {"Authorization": f"Token {settings.deepgram_api_key}"}


def tts_model_for_persona(persona: str) -> str:
    return PERSONA_TTS_MODEL.get(persona, PERSONA_TTS_MODEL[DEFAULT_PERSONA])


def _parse_deepgram_listen(payload: dict, fallback_lang: str | None = None) -> TranscriptResult:
    channel = (payload.get("results") or {}).get("channels") or [{}]
    channel0 = channel[0] if channel else {}
    alts = channel0.get("alternatives") or [{}]
    alt0 = alts[0] if alts else {}
    transcript = (alt0.get("transcript") or "").strip()
    confidence = float(alt0.get("confidence") or 0.0)
    detected = channel0.get("detected_language") or payload.get("results", {}).get("detected_language")
    language = (detected or fallback_lang or None)
    if isinstance(language, str):
        language = language.strip().lower()[:2] or None
    return TranscriptResult(transcript=transcript, language=language, confidence=confidence)


async def _listen_once(
    audio_bytes: bytes,
    content_type: str,
    *,
    language: str | None = None,
    detect_language: bool = False,
) -> TranscriptResult:
    params: dict = {"model": "nova-3"}
    if detect_language:
        params["detect_language"] = "true"
    elif language:
        params["language"] = language

    async with httpx.AsyncClient() as client:
        response = await client.post(
            STT_URL,
            params=params,
            headers={**_auth_headers(), "Content-Type": content_type},
            content=audio_bytes,
            timeout=30,
        )
    response.raise_for_status()
    return _parse_deepgram_listen(response.json(), fallback_lang=language)


async def transcribe_audio(
    audio_bytes: bytes,
    content_type: str = "audio/mp3",
    *,
    detect_language: bool = False,
    language: str = "es",
    candidate_languages: list[str] | None = None,
) -> TranscriptResult:
    """
    Transcribe audio.
    Si hay candidate_languages (modo traductor), prueba cada idioma y se queda
    con el transcript de mayor confianza.
    """
    langs = []
    for code in candidate_languages or []:
        c = (code or "").strip().lower()[:2]
        if c and c not in langs:
            langs.append(c)

    if len(langs) >= 2:
        import asyncio

        gathered = await asyncio.gather(
            *[
                _listen_once(audio_bytes, content_type, language=lang, detect_language=False)
                for lang in langs
            ],
            return_exceptions=True,
        )
        best: TranscriptResult | None = None
        for lang, item in zip(langs, gathered):
            if isinstance(item, Exception) or not item.transcript:
                continue
            item.language = lang
            if best is None or item.confidence > best.confidence:
                best = item
        if best is not None:
            return best
        # fallback: detección automática
        return await _listen_once(audio_bytes, content_type, detect_language=True)

    if detect_language:
        return await _listen_once(audio_bytes, content_type, detect_language=True)

    return await _listen_once(audio_bytes, content_type, language=language or "es")


async def _synthesize_deepgram(text: str, model: str) -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TTS_URL,
            params={"model": model},
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"text": text},
            timeout=30,
        )
    response.raise_for_status()
    return response.content


async def _synthesize_edge(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    if not chunks:
        raise RuntimeError("No se pudo sintetizar la voz (edge-tts).")
    return b"".join(chunks)


async def synthesize_speech(
    text: str,
    persona: str = DEFAULT_PERSONA,
    language: str | None = None,
) -> bytes:
    spoken = text_for_speech(text)
    persona_key = persona if persona in ("eliseo", "elisse") else DEFAULT_PERSONA
    lang = detect_speech_language(spoken, language)

    if lang in DEEPGRAM_LANG_MODEL:
        model = DEEPGRAM_LANG_MODEL[lang].get(persona_key) or next(
            iter(DEEPGRAM_LANG_MODEL[lang].values())
        )
        return await _synthesize_deepgram(spoken, model)

    voices = EDGE_TTS_VOICE.get(lang) or EDGE_TTS_VOICE.get("ru")
    voice = (voices or {}).get(persona_key) or "ru-RU-DmitryNeural"
    try:
        return await _synthesize_edge(spoken, voice)
    except Exception:
        return await _synthesize_deepgram(spoken, tts_model_for_persona(persona_key))
