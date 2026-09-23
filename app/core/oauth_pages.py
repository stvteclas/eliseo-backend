"""
Página HTML mínima con la que terminan los callbacks OAuth (Google Calendar,
Mercado Pago, Teams Calendar): el usuario llega ahí desde el navegador, no
desde la app.
"""

import html as html_module

from fastapi.responses import HTMLResponse

from app.core.config import settings


def oauth_page(message: str, status_code: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Eliseo</title></head>"
        f"<body><p>{message}</p></body></html>"
    )
    return HTMLResponse(html, status_code=status_code)


def oauth_failure_page(message: str, exc: Exception | None = None) -> HTMLResponse:
    """
    Página de error para un callback OAuth. En prueba mostramos tipo + mensaje
    corto del error para poder diagnosticar sin mirar logs de Vercel.
    """
    detail = ""
    if exc is not None:
        raw = f"{type(exc).__name__}: {exc}"
        detail = f" [debug] {html_module.escape(raw)[:500]}"
    return oauth_page(message + detail, 400)
