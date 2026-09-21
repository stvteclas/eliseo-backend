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

import html
import logging
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors/mercadopago", tags=["mercadopago"])

SERVICE_NAME = "mercadopago"
AUTH_URL = "https://auth.mercadopago.com.ar/authorization"
TOKEN_URL = "https://api.mercadopago.com/oauth/token"


class MercadoPagoTokenError(Exception):
    """Mercado Pago rechazó el canje del code. `body` es su respuesta, con el error y el motivo."""

    def __init__(self, status_code: int, body: str):
        super().__init__(f"Mercado Pago respondió {status_code}")
        self.status_code = status_code
        self.body = body


def _redirect_uri() -> str:
    """
    redirect_uri que se manda a Mercado Pago. Tiene que ser CARÁCTER POR CARÁCTER
    el mismo en /authorize, en el canje del code y en el registrado en la app de
    Mercado Pago (barra final, http vs https, mayúsculas...), por eso los dos
    pasos salen de acá. El strip cubre un espacio o salto de línea pegado por
    error en la variable de entorno.
    """
    return settings.mp_redirect_uri.strip()


def _exchange_code_for_tokens(code: str) -> dict:
    """Canjea el code por tokens. Devuelve access_token, refresh_token, user_id y expires_in."""
    redirect_uri = _redirect_uri()
    response = httpx.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": settings.mp_client_id,
            "client_secret": settings.mp_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if response.status_code != 200:
        # El cuerpo trae el error real (invalid_grant si el code ya se usó o venció,
        # mismatch de redirect_uri, credenciales incorrectas...). Solo se loguea en
        # caso de falla: el cuerpo de un canje exitoso trae los tokens.
        logger.warning(
            "Mercado Pago rechazó el canje del code: status=%s redirect_uri=%r client_id=%r body=%s",
            response.status_code,
            redirect_uri,
            settings.mp_client_id,
            response.text[:2000],
        )
        raise MercadoPagoTokenError(response.status_code, response.text)
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
            "redirect_uri": _redirect_uri(),
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
        logger.warning("Callback de Mercado Pago con error=%r", error)
        return oauth_page("No se autorizó el acceso a Mercado Pago. Podés cerrar esta pestaña e intentar de nuevo.", 400)

    user_id = decode_oauth_state(state) if state else None
    if user_id is None or not code:
        logger.warning("Callback de Mercado Pago con state inválido o vencido, o sin code (hay state: %s, hay code: %s)", bool(state), bool(code))
        return oauth_page("El enlace de autorización no es válido o venció. Volvé a empezar desde la app.", 400)

    if db.query(User).filter(User.id == user_id).first() is None:
        logger.warning("Callback de Mercado Pago para un usuario que no existe (user_id=%s)", user_id)
        return oauth_page("El enlace de autorización no es válido.", 400)

    failure = "No se pudo completar la autorización con Mercado Pago. Volvé a intentar."
    try:
        tokens = _exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
        mp_user_id = str(tokens["user_id"])
    except MercadoPagoTokenError as exc:
        # Ya quedó logueado el cuerpo. Con OAUTH_DEBUG=true también se muestra acá (temporal, para depurar).
        detail = f" [debug] Mercado Pago respondió {exc.status_code}: {html.escape(exc.body[:2000])}" if settings.oauth_debug else ""
        return oauth_page(failure + detail, 400)
    except Exception:
        logger.exception("Falló el canje del code de Mercado Pago (error inesperado)")
        return oauth_page(failure, 400)

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
