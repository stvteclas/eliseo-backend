"""
Conexión de Microsoft Teams/Outlook Calendar por cuenta (HU-T22), mismo
patrón OAuth que Google Calendar y Mercado Pago, con account_label desde
el vamos (HU-T21): un usuario puede conectar varias cuentas (ej. "banco",
"agencia", "personal"), probablemente de organizaciones distintas — de ahí
ms_tenant="common" por defecto.

  1. GET /connectors/teams_calendar/authorize?account_label=banco (con
     Bearer) devuelve la URL de consentimiento de Microsoft.
  2. Microsoft redirige a GET /connectors/teams_calendar/callback, directo
     desde el navegador del usuario (sin header de auth): el usuario y la
     cuenta se recuperan del parámetro `state`, que va firmado.

Sin la librería msal: el canje del code se hace con httpx, como en
Mercado Pago — con una diferencia importante: el endpoint de token de
Microsoft exige el cuerpo como application/x-www-form-urlencoded, no JSON
(a diferencia del de Mercado Pago). Requiere una app registrada en Azure
(Entra ID) con settings.ms_redirect_uri como redirect URI registrada.
"""

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
from app.core.oauth_pages import oauth_failure_page, oauth_page
from app.core.security import create_oauth_state, decode_oauth_state
from app.models.teams_calendar_credential import TeamsCalendarCredential
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors/teams_calendar", tags=["teams_calendar"])

SERVICE_NAME = "teams_calendar"
SCOPE = "Calendars.Read offline_access"


def _authorize_url() -> str:
    return f"https://login.microsoftonline.com/{settings.ms_tenant}/oauth2/v2.0/authorize"


def _token_url() -> str:
    return f"https://login.microsoftonline.com/{settings.ms_tenant}/oauth2/v2.0/token"


def _exchange_code_for_tokens(code: str) -> dict:
    """Canjea el code por tokens. Devuelve access_token, refresh_token y expires_in."""
    response = httpx.post(
        _token_url(),
        # A diferencia de Mercado Pago: Microsoft exige form-urlencoded, no JSON.
        data={
            "grant_type": "authorization_code",
            "client_id": settings.ms_client_id,
            "client_secret": settings.ms_client_secret,
            "code": code,
            "redirect_uri": settings.ms_redirect_uri,
            "scope": SCOPE,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if response.status_code != 200:
        logger.warning(
            "Microsoft rechazó el canje del code: status=%s redirect_uri=%r tenant=%r body=%s",
            response.status_code,
            settings.ms_redirect_uri,
            settings.ms_tenant,
            response.text[:2000],
        )
        raise httpx.HTTPStatusError(f"Microsoft respondió {response.status_code}", request=response.request, response=response)
    return response.json()


@router.get("/authorize")
def authorize(account_label: str = "default", current_user: User = Depends(get_current_user)) -> dict:
    """account_label (HU-T21) distingue esta cuenta de Teams de otras que el usuario conecte."""
    if not settings.ms_client_id or not settings.ms_client_secret:
        raise HTTPException(status_code=503, detail="Microsoft Teams Calendar no está configurado en el servidor.")

    query = urlencode(
        {
            "client_id": settings.ms_client_id,
            "response_type": "code",
            "redirect_uri": settings.ms_redirect_uri,
            "scope": SCOPE,
            "state": create_oauth_state(current_user.id, account_label),
        }
    )
    return {"authorize_url": f"{_authorize_url()}?{query}"}


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        logger.warning("Callback de Teams Calendar con error=%r", error)
        return oauth_page("No se autorizó el acceso al calendario de Teams. Podés cerrar esta pestaña e intentar de nuevo.", 400)

    decoded = decode_oauth_state(state) if state else None
    if decoded is None or not code:
        return oauth_page("El enlace de autorización no es válido o venció. Volvé a empezar desde la app.", 400)
    user_id, account_label = decoded

    if db.query(User).filter(User.id == user_id).first() is None:
        return oauth_page("El enlace de autorización no es válido.", 400)

    try:
        tokens = _exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
    except Exception:
        logger.exception("Falló el canje del code de Microsoft")
        return oauth_page("No se pudo completar la autorización con Microsoft. Volvé a intentar.", 400)

    try:
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in")
        values = {
            "access_token_encrypted": encrypt(access_token),
            "refresh_token_encrypted": encrypt(refresh_token) if refresh_token else None,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in else None,
        }

        credential = (
            db.query(TeamsCalendarCredential)
            .filter(TeamsCalendarCredential.user_id == user_id, TeamsCalendarCredential.account_label == account_label)
            .first()
        )
        if credential:
            for field, value in values.items():
                setattr(credential, field, value)
        else:
            db.add(TeamsCalendarCredential(user_id=user_id, account_label=account_label, **values))
        db.commit()

        upsert_user_connector(
            db, user_id, SERVICE_NAME, scope="read_only", store_credential=True, account_label=account_label
        )
    except Exception as exc:
        db.rollback()
        # Microsoft ya autorizó en este punto — si esto falla, el usuario cree
        # que quedó conectado, así que hay que loguear fuerte.
        logger.exception(
            "Se autorizó con Microsoft pero no se pudo guardar la conexión (user_id=%s, account_label=%s)",
            user_id,
            account_label,
        )
        return oauth_failure_page(
            "Se autorizó con Microsoft pero no se pudo guardar la conexión. Volvé a intentar.", exc
        )

    return oauth_page("Listo, ya podés cerrar esta pestaña.")
