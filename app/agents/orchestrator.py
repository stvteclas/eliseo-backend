"""
Motor de orquestación de Eliseo (HU-T03).

Arma un agente de LangGraph (ReAct) sobre Claude, con herramientas
cargadas desde un servidor MCP. Por ahora conecta al servidor de
prueba (mcp_servers/sandbox_server.py) vía stdio — cuando lleguen las
herramientas reales (HU-T04: manifiesto por usuario, HU-T11: calendario,
HU-T20: Mercado Pago), este módulo es el que las va a cargar en vez del
servidor de juguete.

⚠️ Nota de arquitectura para cuando esto se despliegue en Vercel:
MCP sobre stdio arranca un proceso hijo — es el modelo pensado para una
app corriendo en tu propia máquina, no para una función serverless. Antes
de llevar esto a producción, hay que migrar el/los servidor(es) MCP a
transporte HTTP (streamable-http), corriendo como su propio servicio, o
resolver las herramientas reales sin pasar por un proceso MCP separado.
Este cambio es de configuración de MultiServerMCPClient, no de este
módulo ni del resto del código del agente.
"""

import os
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

from app.core.config import settings

SANDBOX_SERVER_PATH = str(Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "sandbox_server.py")

SYSTEM_PROMPT = (
    "Sos Eliseo, un asistente de voz argentino, cálido y directo. "
    "Respondé corto, como si estuvieras hablando, no escribiendo un informe."
)


async def _build_agent():
    client = MultiServerMCPClient(
        {
            "sandbox": {
                "command": "python",
                "args": [SANDBOX_SERVER_PATH],
                "transport": "stdio",
            }
        }
    )
    tools = await client.get_tools()

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
