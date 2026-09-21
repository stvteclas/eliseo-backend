"""
Motor de orquestación de Eliseo (HU-T03).

Arma un agente de LangGraph (ReAct) sobre Claude, con herramientas
cargadas desde un servidor MCP. Por ahora conecta al servidor de
prueba (mcp_servers/sandbox_server.py) vía HTTP — cuando lleguen las
herramientas reales (HU-T04: manifiesto por usuario, HU-T11: calendario,
HU-T20: Mercado Pago), este módulo es el que las va a cargar en vez del
servidor de juguete.

Transporte: streamable-http, no stdio. stdio arranca un proceso hijo,
que no sirve en una función serverless como Vercel; con HTTP el servidor
MCP corre como su propio servicio y acá solo se configura su URL
(settings.mcp_sandbox_url).
"""

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from app.core.config import settings

SYSTEM_PROMPT = (
    "Sos Eliseo, un asistente de voz argentino, cálido y directo. "
    "Respondé corto, como si estuvieras hablando, no escribiendo un informe."
)


class ToolServerUnavailable(Exception):
    """El servidor MCP no responde (caído o URL mal configurada)."""


async def _build_agent():
    client = MultiServerMCPClient(
        {
            "sandbox": {
                "url": settings.mcp_sandbox_url,
                "transport": "streamable_http",
            }
        }
    )
    try:
        tools = await client.get_tools()
    except Exception as exc:  # los errores de conexión llegan como ExceptionGroup
        raise ToolServerUnavailable(settings.mcp_sandbox_url) from exc

    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
    )

    return create_react_agent(model, tools, prompt=SYSTEM_PROMPT)


async def handle_user_message(message: str) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en la configuración.")

    agent = await _build_agent()
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})

    last_message = result["messages"][-1]
    return last_message.content
