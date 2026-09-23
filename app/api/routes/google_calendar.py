"""
Conexión de Google Calendar por usuario (HU-T11): flujo OAuth 2.0 web.

  1. GET /connectors/google_calendar/authorize (con Bearer) devuelve la URL
     de consentimiento de Google. El cliente la abre en el navegador.
  2. Google redirige a GET /connectors/google_calendar/callback, directo
     desde el navegador del usuario (sin header de auth): el usuario se
     recupera del parámetro `state`, que va firmado.

Guarda solo el refresh token, cifrado. Requiere una credencial OAuth tipo
"Web application" en Google Cloud con settings.google_redirect_uri
registrada como URI de redirección autorizada.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.api.routes.connectors import upsert_user_connector
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import get_db
from app.core.oauth_pages import oauth_failure_page, oauth_page
from app.core.security import create_oauth_state, decode_oauth_state
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors/google_calendar", tags=["google_calendar"])

SERVICE_NAME = "google_calendar"

# Única fuente de verdad para estos scopes: orchestrator.py los importa de acá
# para reconstruir las credenciales guardadas. Antes había dos listas
# separadas (una acá, otra en orchestrator.py) que se desincronizaron: se
# agregó calendarlist.readonly en una sola, así que el consentimiento nunca
# llegaba a pedirle a Google ese permiso.
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    # Para poder leer TODOS los calendarios de la cuenta (no solo "primary"),
    # ej. calendarios que el usuario agregó/se suscribió aparte del propio.
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
SCOPES = GOOGLE_CALENDAR_SCOPES


def resolved_google_calendar_redirect_uri() -> str:
    """Misma URI en authorize y callback; sin espacios ni slash final raro."""
    return (settings.google_redirect_uri or "").strip().rstrip("/")


def _build_flow() -> Flow:
    redirect_uri = resolved_google_calendar_redirect_uri()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    # Sin PKCE: el callback llega en otro request y arma un Flow nuevo, que
    # no tendría el code_verifier de este. Como cliente "Web application" con
    # client_secret, el canje del code ya está protegido.
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def _exchange_code_for_refresh_token(code: str) -> str | None:
    """Canjea el code de Google por tokens y devuelve el refresh token."""
    flow = _build_flow()
    flow.fetch_token(code=code)
    return flow.credentials.refresh_token


@router.get("/authorize")
def authorize(account_label: str = "default", current_user: User = Depends(get_current_user)) -> dict:
    """account_label (HU-T21) distingue esta cuenta de Calendar de otras que el usuario conecte."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google Calendar no está configurado en el servidor.")
    redirect_uri = resolved_google_calendar_redirect_uri()
    if not redirect_uri:
        raise HTTPException(status_code=503, detail="Falta GOOGLE_REDIRECT_URI.")
    if settings.env == "production" and "localhost" in redirect_uri:
        raise HTTPException(
            status_code=503,
            detail=f"GOOGLE_REDIRECT_URI inválida en producción: {redirect_uri!r}",
        )

    authorize_url, _ = _build_flow().authorization_url(
        access_type="offline",  # para que Google devuelva un refresh token
        prompt="consent",  # y lo devuelva siempre, aunque el usuario ya haya autorizado antes
        state=create_oauth_state(current_user.id, account_label),
    )
    return {"authorize_url": authorize_url, "redirect_uri": redirect_uri}


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return oauth_page("No se autorizó el acceso al calendario. Podés cerrar esta pestaña e intentar de nuevo.", 400)

    decoded = decode_oauth_state(state) if state else None
    if decoded is None or not code:
        return oauth_page("El enlace de autorización no es válido o venció. Volvé a empezar desde la app.", 400)
    user_id, account_label = decoded

    if db.query(User).filter(User.id == user_id).first() is None:
        return oauth_page("El enlace de autorización no es válido.", 400)

    try:
        refresh_token = _exchange_code_for_refresh_token(code)
    except Exception:
        return oauth_page("No se pudo completar la autorización con Google. Volvé a intentar.", 400)
    if not refresh_token:
        return oauth_page("Google no entregó el permiso necesario. Volvé a intentar.", 400)

    try:
        credential = (
            db.query(GoogleCalendarCredential)
            .filter(GoogleCalendarCredential.user_id == user_id, GoogleCalendarCredential.account_label == account_label)
            .first()
        )
        if credential:
            credential.refresh_token_encrypted = encrypt(refresh_token)
        else:
            db.add(
                GoogleCalendarCredential(
                    user_id=user_id, account_label=account_label, refresh_token_encrypted=encrypt(refresh_token)
                )
            )
        db.commit()

        upsert_user_connector(
            db, user_id, SERVICE_NAME, scope="read_only", store_credential=True, account_label=account_label
        )
    except Exception as exc:
        db.rollback()
        # Google ya autorizó en este punto (el code se canjeó bien) — si esto falla,
        # el usuario cree que quedó conectado, así que hay que loguear fuerte.
        logger.exception(
            "Se autorizó con Google pero no se pudo guardar la conexión (user_id=%s, account_label=%s)",
            user_id,
            account_label,
        )
        return oauth_failure_page(
            "Se autorizó con Google pero no se pudo guardar la conexión. Volvé a intentar.", exc
        )

    return oauth_page("Listo, ya podés cerrar esta pestaña.")
