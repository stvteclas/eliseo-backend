"""
Endpoints de voz (HU-T07): transcribir audio y sintetizar voz. Todavía no
hablan con /chat — eso lo arma la app en T08, encadenando estas dos
llamadas alrededor de /chat.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.models.user import User
from app.services.voice import synthesize_speech, transcribe_audio

router = APIRouter(prefix="/voice", tags=["voice"])


class TranscribeResponse(BaseModel):
    transcript: str


class SpeakRequest(BaseModel):
    text: str


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    audio_bytes = await audio.read()
    try:
        transcript = await transcribe_audio(audio_bytes, content_type=audio.content_type or "audio/mp3")
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return TranscribeResponse(transcript=transcript)


@router.post("/speak")
async def speak(
    data: SpeakRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        audio_bytes = await synthesize_speech(data.text, persona=current_user.persona)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return Response(content=audio_bytes, media_type="audio/mpeg")
