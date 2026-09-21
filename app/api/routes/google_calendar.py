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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.api.routes.connectors import upsert_user_connector
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import get_db
from app.core.security import create_oauth_state, decode_oauth_state
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User

router = APIRouter(prefix="/connectors/google_calendar", tags=["google_calendar"])

SERVICE_NAME = "google_calendar"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _build_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    # Sin PKCE: el callback llega en otro request y arma un Flow nuevo, que
    # no tendría el code_verifier de este. Como cliente "Web application" con
    # client_secret, el canje del code ya está protegido.
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=False,
    )


def _exchange_code_for_refresh_token(code: str) -> str | None:
    """Canjea el code de Google por tokens y devuelve el refresh token."""
    flow = _build_flow()
    flow.fetch_token(code=code)
    return flow.credentials.refresh_token


def _page(message: str, status_code: int = 200) -> HTMLResponse:
    html = f"<!doctype html><html><head><meta charset='utf-8'><title>Eliseo</title></head><body><p>{message}</p></body></html>"
    return HTMLResponse(html, status_code=status_code)


@router.get("/authorize")
def authorize(current_user: User = Depends(get_current_user)) -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google Calendar no está configurado en el servidor.")

    authorize_url, _ = _build_flow().authorization_url(
        access_type="offline",  # para que Google devuelva un refresh token
        prompt="consent",  # y lo devuelva siempre, aunque el usuario ya haya autorizado antes
        state=create_oauth_state(current_user.id),
    )
    return {"authorize_url": authorize_url}


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return _page("No se autorizó el acceso al calendario. Podés cerrar esta pestaña e intentar de nuevo.", 400)

    user_id = decode_oauth_state(state) if state else None
    if user_id is None or not code:
        return _page("El enlace de autorización no es válido o venció. Volvé a empezar desde la app.", 400)

    if db.query(User).filter(User.id == user_id).first() is None:
        return _page("El enlace de autorización no es válido.", 400)

    try:
        refresh_token = _exchange_code_for_refresh_token(code)
    except Exception:
        return _page("No se pudo completar la autorización con Google. Volvé a intentar.", 400)
    if not refresh_token:
        return _page("Google no entregó el permiso necesario. Volvé a intentar.", 400)

    credential = db.query(GoogleCalendarCredential).filter(GoogleCalendarCredential.user_id == user_id).first()
    if credential:
        credential.refresh_token_encrypted = encrypt(refresh_token)
    else:
        db.add(GoogleCalendarCredential(user_id=user_id, refresh_token_encrypted=encrypt(refresh_token)))
    db.commit()

    upsert_user_connector(db, user_id, SERVICE_NAME, scope="read_only", store_credential=True)

    return _page("Listo, ya podés cerrar esta pestaña.")
