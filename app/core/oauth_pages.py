"""
Página HTML mínima con la que terminan los callbacks OAuth (Google Calendar,
Mercado Pago): el usuario llega ahí desde el navegador, no desde la app.
"""

from fastapi.responses import HTMLResponse


def oauth_page(message: str, status_code: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Eliseo</title></head>"
        f"<body><p>{message}</p></body></html>"
    )
    return HTMLResponse(html, status_code=status_code)
