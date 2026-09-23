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
    Página de error para un callback OAuth cuando algo falla DESPUÉS de que
    el proveedor ya autorizó (guardar la credencial, escribir el conector).
    El caller es responsable de loguear la excepción real (logger.exception);
    acá solo se agrega su texto a la página cuando OAUTH_DEBUG=true, para
    depurar una falla puntual sin dejarlo prendido en producción.
    """
    detail = ""
    if exc is not None and settings.oauth_debug:
        detail = f" [debug] {type(exc).__name__}: {html_module.escape(str(exc))[:500]}"
    # En login Google también mostramos un hint corto sin secretos, para
    # diagnosticar en prueba (token exchange / DB) sin prender OAUTH_DEBUG.
    elif exc is not None:
        detail = f" ({html_module.escape(type(exc).__name__)})"
    return oauth_page(message + detail, 400)
