from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agents.orchestrator import handle_user_message
from app.api.routes.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.post("", response_model=ChatResponse)
async def chat(data: ChatRequest, current_user: User = Depends(get_current_user)):
    """
    Primer endpoint donde Eliseo responde de verdad — pasa el mensaje
    por el motor de orquestación (LangGraph + MCP) en vez de devolver
    algo fijo. Protegido: solo usuarios autenticados.
    """
    reply = await handle_user_message(data.message)
    return ChatResponse(reply=reply)
