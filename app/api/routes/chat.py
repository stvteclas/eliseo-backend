from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.orchestrator import ToolServerUnavailable, handle_user_message
from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    latitude: float | None = None
    longitude: float | None = None


class ChatResponse(BaseModel):
    reply: str
    actions: list[dict] = Field(default_factory=list)
    speak_language: str | None = None


@router.post("", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Primer endpoint donde Eliseo responde de verdad — pasa el mensaje
    por el motor de orquestación (LangGraph + MCP) en vez de devolver
    algo fijo. Protegido: solo usuarios autenticados.
    """
    try:
        reply, actions, speak_language = await handle_user_message(
            data.message,
            current_user.id,
            db,
            latitude=data.latitude,
            longitude=data.longitude,
        )
    except ToolServerUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servidor de herramientas (MCP) no está disponible.",
        )
    return ChatResponse(reply=reply, actions=actions, speak_language=speak_language)
