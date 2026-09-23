"""
Endpoints de voz (HU-T07): transcribir, sintetizar, y un turno completo
(STT + chat + TTS) para evitar 3 viajes de red a Vercel.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.orchestrator import ToolServerUnavailable, handle_user_message
from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.voice import synthesize_speech, transcribe_audio

router = APIRouter(prefix="/voice", tags=["voice"])


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
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/turn", response_model=TurnResponse)
async def voice_turn(
    audio: UploadFile = File(...),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Un solo request: audio → transcript → respuesta → audio TTS.
    Recorta latencia al evitar 2 round-trips extra a Vercel.
    """
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

    try:
        reply, actions, speak_language = await handle_user_message(
            transcript,
            current_user.id,
            db,
            latitude=latitude,
            longitude=longitude,
            source_language=stt.language,
        )
    except ToolServerUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servidor de herramientas (MCP) no está disponible.",
        )

    try:
        tts_bytes = await synthesize_speech(
            reply,
            persona=current_user.persona,
            language=speak_language,
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
