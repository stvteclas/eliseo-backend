"""
Servidor MCP de prueba — expone una sola herramienta trivial (la hora
actual) para confirmar que el mecanismo agente-MCP funciona de punta a
punta, antes de conectar herramientas reales (calendario en HU-T11,
Mercado Pago en HU-T20, etc.).

Corre con transporte stdio: pensado para procesos locales, no para
producción en Vercel. Cuando conectemos herramientas reales, hay que
evaluar pasarlas a transporte HTTP — ver nota en orchestrator.py.
"""

from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("EliseoToolsSandbox")


@mcp.tool()
def get_current_datetime() -> str:
    """Devuelve la fecha y hora actual, en formato legible."""
    return datetime.now().strftime("%A %d de %B de %Y, %H:%M")


if __name__ == "__main__":
    mcp.run(transport="stdio")
