"""
Servidor MCP de prueba — expone una sola herramienta trivial (la hora
actual) para confirmar que el mecanismo agente-MCP funciona de punta a
punta, antes de conectar herramientas reales (calendario en HU-T11,
Mercado Pago en HU-T20, etc.).

Corre como servicio HTTP (streamable-http) en su propio proceso, no como
proceso hijo del backend: así funciona igual en local y desplegado.

    python mcp_servers/sandbox_server.py     # escucha en :8001/mcp

El backend lo encuentra por MCP_SANDBOX_URL (ver app/core/config.py).
"""

import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# stateless_http: cada request es independiente, sin sesión en memoria —
# necesario para que no dependa de que un mismo proceso atienda toda la charla.
mcp = FastMCP(
    "EliseoToolsSandbox",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8001")),
    stateless_http=True,
)


@mcp.tool()
def get_current_datetime() -> str:
    """Devuelve la fecha y hora actual, en formato legible."""
    return datetime.now().strftime("%A %d de %B de %Y, %H:%M")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
