"""
Motor de orquestación de Eliseo (HU-T03).

Arma un agente de LangGraph (ReAct) sobre Claude, con herramientas
cargadas desde servidores MCP. Solo carga las de los servicios que el
usuario autorizó (manifiesto, HU-T04, tabla user_connectors de HU-T15);
un usuario sin servicios autorizados conversa con el agente sin
herramientas.

Transporte: streamable-http, no stdio. stdio arranca un proceso hijo,
que no sirve en una función serverless como Vercel; con HTTP el servidor
MCP corre como su propio servicio y acá solo se configura su URL
(settings.mcp_sandbox_url).
"""

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential

SYSTEM_PROMPT = (
    "Sos Eliseo, un asistente de voz argentino, cálido y directo. "
    "Respondé corto, como si estuvieras hablando, no escribiendo un informe. "
    "Solo podés usar las herramientas que tenés disponibles: si te piden algo "
    "para lo que no tenés una herramienta conectada, decilo en vez de inventar la respuesta."
)


# service_name -> config de MultiServerMCPClient. Hoy solo "sandbox"; en
# HU-T11 (calendario) y HU-T20 (Mercado Pago) se agregan entradas nuevas,
# sin tocar get_tools_for_user. Un conector cuyo service_name no esté acá
# (ej. "whatsapp") se ignora: todavía no tiene herramientas MCP detrás.
SERVICE_MCP_REGISTRY: dict[str, dict] = {
    "sandbox": {"url": settings.mcp_sandbox_url, "transport": "streamable_http"},
}


class ToolServerUnavailable(Exception):
    """El servidor MCP no responde (caído o URL mal configurada)."""


def build_calendar_tool(user_id: int, db: Session):
    """
    Herramienta de Google Calendar del usuario, armada con SUS credenciales
    (HU-T11). No es un servidor MCP: cada usuario tiene su propio refresh
    token, así que la herramienta se construye por usuario. Devuelve None si
    el usuario no conectó su calendario.
    """
    credential = db.query(GoogleCalendarCredential).filter(GoogleCalendarCredential.user_id == user_id).first()
    if credential is None:
        return None

    google_credentials = Credentials(
        token=None,
        refresh_token=decrypt(credential.refresh_token_encrypted),
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )

    @tool
    def get_upcoming_calendar_events() -> str:
        """Devuelve los próximos eventos del calendario de Google del usuario."""
        try:
            service = build("calendar", "v3", credentials=google_credentials, cache_discovery=False)
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=datetime.now(timezone.utc).isoformat(),
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception:
            return "No pude leer el calendario. Puede que la autorización haya vencido y haya que volver a conectarlo."

        events = result.get("items", [])
        if not events:
            return "No hay eventos próximos en el calendario."
        return "\n".join(
            f"{event['start'].get('dateTime', event['start'].get('date'))} — {event.get('summary', '(sin título)')}"
            for event in events
        )

    return get_upcoming_calendar_events


async def get_tools_for_user(user_id: int, db: Session) -> list:
    """Herramientas de los servicios que el usuario conectó: MCP + calendario (no llama al modelo)."""
    services = [name for (name,) in db.query(UserConnector.service_name).filter(UserConnector.user_id == user_id)]
    servers = {name: SERVICE_MCP_REGISTRY[name] for name in services if name in SERVICE_MCP_REGISTRY}

    tools = []
    if servers:
        client = MultiServerMCPClient(servers)
        try:
            tools = await client.get_tools()
        except Exception as exc:  # los errores de conexión llegan como ExceptionGroup
            raise ToolServerUnavailable(", ".join(servers)) from exc

    if "google_calendar" in services:
        calendar_tool = build_calendar_tool(user_id, db)
        if calendar_tool is not None:
            tools.append(calendar_tool)

    return tools


async def _build_agent(user_id: int, db: Session):
    tools = await get_tools_for_user(user_id, db)

    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
    )

    return create_react_agent(model, tools, prompt=SYSTEM_PROMPT)


async def handle_user_message(message: str, user_id: int, db: Session) -> str:
    """Responde un mensaje usando solo las herramientas que ese usuario conectó."""
    if not settings.anthropic_api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en la configuración.")

    agent = await _build_agent(user_id, db)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})

    last_message = result["messages"][-1]
    return last_message.content
