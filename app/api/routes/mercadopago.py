"""
Conexión de Mercado Pago por usuario (HU-T20): OAuth 2.0, mismo patrón que
Google Calendar (app/api/routes/google_calendar.py).

  1. GET /connectors/mercadopago/authorize (con Bearer) devuelve la URL de
     autorización de Mercado Pago. El cliente la abre en el navegador.
  2. Mercado Pago redirige a GET /connectors/mercadopago/callback, directo
     desde el navegador del usuario (sin header de auth): el usuario se
     recupera del parámetro `state`, que va firmado.

Guarda los tokens cifrados. Requiere la app de Mercado Pago con
settings.mp_redirect_uri registrada como URL de redireccionamiento.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.api.routes.connectors import upsert_user_connector
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import get_db
from app.core.oauth_pages import oauth_page
from app.core.security import create_oauth_state, decode_oauth_state
from app.models.mercadopago_credential import MercadoPagoCredential
from app.models.user import User

router = APIRouter(prefix="/connectors/mercadopago", tags=["mercadopago"])

SERVICE_NAME = "mercadopago"
AUTH_URL = "https://auth.mercadopago.com.ar/authorization"
TOKEN_URL = "https://api.mercadopago.com/oauth/token"


def _exchange_code_for_tokens(code: str) -> dict:
    """Canjea el code por tokens. Devuelve access_token, refresh_token, user_id y expires_in."""
    response = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": settings.mp_client_id,
            "client_secret": settings.mp_client_secret,
            "code": code,
            "redirect_uri": settings.mp_redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


@router.get("/authorize")
def authorize(current_user: User = Depends(get_current_user)) -> dict:
    if not settings.mp_client_id or not settings.mp_client_secret:
        raise HTTPException(status_code=503, detail="Mercado Pago no está configurado en el servidor.")

    query = urlencode(
        {
            "client_id": settings.mp_client_id,
            "response_type": "code",
            "platform_id": "mp",
            "redirect_uri": settings.mp_redirect_uri,
            "state": create_oauth_state(current_user.id),
        }
    )
    return {"authorize_url": f"{AUTH_URL}?{query}"}


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return oauth_page("No se autorizó el acceso a Mercado Pago. Podés cerrar esta pestaña e intentar de nuevo.", 400)

    user_id = decode_oauth_state(state) if state else None
    if user_id is None or not code:
        return oauth_page("El enlace de autorización no es válido o venció. Volvé a empezar desde la app.", 400)

    if db.query(User).filter(User.id == user_id).first() is None:
        return oauth_page("El enlace de autorización no es válido.", 400)

    try:
        tokens = _exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
        mp_user_id = str(tokens["user_id"])
    except Exception:
        return oauth_page("No se pudo completar la autorización con Mercado Pago. Volvé a intentar.", 400)

    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")
    values = {
        "mp_user_id": mp_user_id,
        "access_token_encrypted": encrypt(access_token),
        "refresh_token_encrypted": encrypt(refresh_token) if refresh_token else None,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in else None,
    }

    credential = db.query(MercadoPagoCredential).filter(MercadoPagoCredential.user_id == user_id).first()
    if credential:
        for field, value in values.items():
            setattr(credential, field, value)
    else:
        db.add(MercadoPagoCredential(user_id=user_id, **values))
    db.commit()

    upsert_user_connector(db, user_id, SERVICE_NAME, scope="read_write", store_credential=True)

    return oauth_page("Listo, ya podés cerrar esta pestaña.")
