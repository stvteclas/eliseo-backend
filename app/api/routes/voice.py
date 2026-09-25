"""
Endpoints de voz (HU-T07): transcribir, sintetizar, y un turno completo
(STT + chat + TTS) para evitar 3 viajes de red a Vercel.
"""

from __future__ import annotations

import base64
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.orchestrator import ToolServerUnavailable, handle_user_message
from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import prefs as prefs_service
from app.services.voice import synthesize_speech, transcribe_audio

router = APIRouter(prefix="/voice", tags=["voice"])


def _fold_es(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )


def _is_quiet_exit(transcript: str) -> bool:
    """Frases para salir del silencio sin decir el wake name."""
    t = _fold_es(transcript)
    needles = (
        "sali del silencio",
        "sali del modo silencio",
        "salir del silencio",
        "salir del modo silencio",
        "salgo del silencio",
        "desactiva el silencio",
        "desactiva silencio",
        "desactivar silencio",
        "desactiva el modo silencio",
        "apaga el silencio",
        "apaga silencio",
        "quita el silencio",
        "quita silencio",
        "termina el silencio",
        "modo silencio off",
        "no mas silencio",
        "cancelar silencio",
        "basta de silencio",
        "modo normal",
        "escuchame normal",
    )
    return any(n in t for n in needles)


def _is_confirm_phrase(transcript: str) -> bool:
    t = _fold_es(transcript).strip()
    if not t:
        return False
    exact = {
        "dale",
        "si",
        "sí",
        "ok",
        "okay",
        "listo",
        "manda",
        "mandalo",
        "mandala",
        "envia",
        "envialo",
        "confirma",
        "confirmalo",
        "de una",
        "dale nomas",
        "dale nomás",
    }
    if t in exact or _fold_es(t) in {_fold_es(x) for x in exact}:
        return True
    return any(
        p in t
        for p in (
            "dale manda",
            "si dale",
            "manda nomas",
            "confirma y manda",
        )
    )


def _is_cancel_phrase(transcript: str) -> bool:
    t = _fold_es(transcript).strip()
    needles = (
        "cancel",
        "no mand",
        "no envie",
        "no envies",
        "dejalo",
        "dejalo ahi",
        "olvidalo",
        "anul",
    )
    if t in {"no", "para", "basta", "cancelar", "cancelá", "cancela"}:
        return True
    return any(n in t for n in needles)


def _is_continue_phrase(transcript: str) -> bool:
    t = _fold_es(transcript).strip()
    return t in {
        "segui",
        "sigue",
        "continua",
        "continuar",
        "mas",
        "seguí",
        "siguiente",
        "dale segui",
    } or any(p in t for p in ("segui leyendo", "sigue leyendo", "continua leyendo", "leeme mas"))


def _is_stop_read_phrase(transcript: str) -> bool:
    t = _fold_es(transcript).strip()
    return t in {"para", "parado", "basta", "cortala", "corta"} or any(
        p in t for p in ("para de leer", "deja de leer", "no sigas", "corta ahi")
    )


class TranscribeResponse(BaseModel):
    transcript: str
    detected_language: str | None = None


class SpeakRequest(BaseModel):
    text: str
    language: str | None = None


class TurnResponse(BaseModel):
    transcript: str
    reply: str
    actions: list[dict] = Field(default_factory=list)
    speak_language: str | None = None
    detected_language: str | None = None
    audio_base64: str = ""


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    audio_bytes = await audio.read()
    candidates = None
    if current_user.translator_lang_a and current_user.translator_lang_b:
        candidates = [current_user.translator_lang_a, current_user.translator_lang_b]
    try:
        result = await transcribe_audio(
            audio_bytes,
            content_type=audio.content_type or "audio/mp3",
            detect_language=bool(candidates),
            candidate_languages=candidates,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return TranscribeResponse(
        transcript=result.transcript,
        detected_language=result.language,
    )


@router.post("/speak")
async def speak(
    data: SpeakRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        audio_bytes = await synthesize_speech(
            data.text,
            persona=current_user.persona,
            language=data.language,
            slow=bool(getattr(current_user, "speak_slow", False)),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/turn", response_model=TurnResponse)
async def voice_turn(
    audio: UploadFile = File(...),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    history: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Un solo request: audio → transcript → respuesta → audio TTS.
    Recorta latencia al evitar 2 round-trips extra a Vercel.
    `history` es JSON opcional de turnos previos [{role, content}, ...].
    """
    from app.services.conversation_memory import parse_history_payload

    audio_bytes = await audio.read()
    candidates = None
    if current_user.translator_lang_a and current_user.translator_lang_b:
        candidates = [current_user.translator_lang_a, current_user.translator_lang_b]

    try:
        stt = await transcribe_audio(
            audio_bytes,
            content_type=audio.content_type or "audio/mp3",
            detect_language=bool(candidates),
            candidate_languages=candidates,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    transcript = (stt.transcript or "").strip()
    if not transcript:
        return TurnResponse(transcript="", reply="", audio_base64="")

    # Modo silencio: sin nombre de activación, no correr el agente (evita side-effects).
    # Excepción: frases explícitas para SALIR del silencio (no requieren wake word).
    effective = transcript
    if bool(getattr(current_user, "quiet_mode", False)):
        if _is_quiet_exit(transcript):
            prefs_service.set_quiet_mode(db, current_user.id, False)
            db.refresh(current_user)
            effective = "salí del modo silencio"
        else:
            names = prefs_service.wake_names_for(current_user)
            folded = _fold_es(transcript)
            woke = any(n and _fold_es(n) in folded for n in names)
            if not woke:
                return TurnResponse(transcript=transcript, reply="", audio_base64="")
            for n in names:
                if not n:
                    continue
                effective = re.sub(
                    rf"\b{re.escape(n)}\b[,:]?\s*",
                    "",
                    effective,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
            if not effective:
                effective = "Decime"

    # Atajos sin agente: confirmar / cancelar / seguir leyendo / parar.
    from app.services import pending_confirm
    from app.services import reading as reading_service

    shortcut_reply: str | None = None
    shortcut_actions: list = []
    if pending_confirm.get_pending_label(current_user.id):
        if _is_confirm_phrase(effective):
            shortcut_reply = pending_confirm.confirm_pending(current_user.id)
        elif _is_cancel_phrase(effective):
            shortcut_reply = pending_confirm.cancel_pending(current_user.id)
    if shortcut_reply is None and reading_service.has_session(current_user.id):
        if _is_continue_phrase(effective):
            shortcut_reply = reading_service.continue_reading(current_user.id)
        elif _is_stop_read_phrase(effective):
            shortcut_reply = reading_service.stop_reading(current_user.id)

    if shortcut_reply is not None:
        reply, actions, speak_language = shortcut_reply, shortcut_actions, "es"
    else:
        try:
            reply, actions, speak_language = await handle_user_message(
                effective,
                current_user.id,
                db,
                latitude=latitude,
                longitude=longitude,
                source_language=stt.language,
                history=parse_history_payload(history),
            )
        except ToolServerUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El servidor de herramientas (MCP) no está disponible.",
            )
        # Lecturas largas: partir y pedir «seguí» (excepto modo conductor/ambiente).
        if bool(getattr(current_user, "driver_mode", False)) or bool(
            getattr(current_user, "ambient_mode", False)
        ):
            reading_service.clear(current_user.id)
            text = (reply or "").strip()
            limit = 160 if getattr(current_user, "ambient_mode", False) else 220
            if len(text) > limit:
                cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:")
                reply = cut + "."
        else:
            reply = reading_service.maybe_start_if_long(current_user.id, reply or "")

    try:
        reply_text = (reply or "").strip()
        if not reply_text:
            return TurnResponse(
                transcript=transcript,
                reply=reply or "",
                actions=actions,
                speak_language=speak_language,
                detected_language=stt.language,
                audio_base64="",
            )
        tts_bytes = await synthesize_speech(
            reply_text,
            persona=current_user.persona,
            language=speak_language,
            slow=bool(getattr(current_user, "speak_slow", False)),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return TurnResponse(
        transcript=transcript,
        reply=reply,
        actions=actions,
        speak_language=speak_language,
        detected_language=stt.language,
        audio_base64=base64.b64encode(tts_bytes).decode("ascii"),
    )
