"""
Login con Google (OAuth web) separado del conector de Calendar.

  1. GET /auth/google/authorize → URL de Google (openid email profile + PKCE)
  2. Callback GET /auth/google/callback → crea/busca usuario → redirige a
     /auth/google/success?token=JWT para que openAuthSessionAsync lo capture.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.oauth_pages import oauth_failure_page, oauth_page
from app.core.oauth_redirect import safe_app_redirect, with_query
from app.core.security import (
    create_access_token,
    create_login_oauth_state,
    explain_login_oauth_state,
    extract_login_app_redirect,
    extract_login_code_verifier,
    hash_password,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["auth_google"])

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GOOGLE_NO_PASSWORD_PREFIX = "google-oauth:"
AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def resolved_google_login_redirect_uri() -> str:
    """
    URI de callback del login.
    Si en Vercel no configuraron GOOGLE_LOGIN_REDIRECT_URI (queda localhost),
    la derivamos del host de GOOGLE_REDIRECT_URI del Calendar, que ya está en prod.
    """
    login = (settings.google_login_redirect_uri or "").strip()
    cal = (settings.google_redirect_uri or "").strip()
    if login and "localhost" not in login:
        return login
    if cal and "localhost" not in cal and "/connectors/" in cal:
        return cal.split("/connectors/")[0].rstrip("/") + "/auth/google/callback"
    if login:
        return login
    return "http://localhost:8000/auth/google/callback"


def _pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) para OAuth PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _exchange_code_for_access_token(code: str, code_verifier: str | None = None) -> str:
    redirect_uri = resolved_google_login_redirect_uri()
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    with httpx.Client() as client:
        response = client.post(TOKEN_URL, data=data, timeout=20)
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"Google token exchange {response.status_code}: {detail}")
        payload = response.json()
    access = payload.get("access_token")
    if not access:
        raise RuntimeError("Google no devolvió access_token.")
    return access


def _fetch_google_email(access_token: str) -> str:
    with httpx.Client() as client:
        response = client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Google userinfo {response.status_code}: {response.text[:300]}")
        data = response.json()
    email = (data.get("email") or "").strip()
    if not email:
        raise RuntimeError("Google no devolvió un email.")
    return email


def _upsert_google_user(db: Session, email: str) -> User:
    email_norm = email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if user is not None:
        return user
    user = User(
        email=email_norm,
        hashed_password=hash_password(GOOGLE_NO_PASSWORD_PREFIX + secrets.token_urlsafe(16)),
        persona="eliseo",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/authorize")
def authorize_google_login(app_redirect: str | None = Query(default=None)) -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth no está configurado.")
    redirect_uri = resolved_google_login_redirect_uri()
    if not redirect_uri:
        raise HTTPException(status_code=503, detail="Falta GOOGLE_LOGIN_REDIRECT_URI.")

    verifier, challenge = _pkce_pair()
    app_return = safe_app_redirect(app_redirect)
    state = create_login_oauth_state(code_verifier=verifier, app_redirect=app_return)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(LOGIN_SCOPES),
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {
        "authorize_url": f"{AUTH_URL}?{urlencode(params)}",
        "redirect_uri": redirect_uri,
        "app_redirect": app_return,
    }


@router.get("/oauth-uris")
def google_oauth_uris() -> dict:
    """
    URIs exactas que Eliseo manda a Google (para pegarlas en Cloud Console).
    No expone secretos.
    """
    from app.api.routes.google_calendar import resolved_google_calendar_redirect_uri

    client_id = (settings.google_client_id or "").strip()
    return {
        "client_id": client_id,
        "client_id_hint": (client_id[:20] + "…") if len(client_id) > 20 else client_id,
        "redirect_uris": [
            resolved_google_login_redirect_uri(),
            resolved_google_calendar_redirect_uri(),
        ],
        "hint": (
            "En Google Cloud → Credenciales → tu cliente Web, "
            "agregá EXACTAMENTE estas URIs (sin slash final extra)."
        ),
    }


@router.get("/callback")
def google_login_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return oauth_page(
            f"No se autorizó el acceso con Google ({error}). Cerrá e intentá de nuevo.",
            400,
        )
    if not code:
        return oauth_page("Google no devolvió el código de autorización. Volvé a intentar.", 400)

    state_problem = explain_login_oauth_state(state or "")
    if state_problem:
        logger.warning("Login Google: state débil (%s); continúo con el code", state_problem)

    code_verifier = extract_login_code_verifier(state or "")
    try:
        access_token = _exchange_code_for_access_token(code, code_verifier=code_verifier)
        email = _fetch_google_email(access_token)
    except Exception as exc:
        logger.exception("Fallo canje/userinfo en login Google")
        return oauth_failure_page(
            f"No se pudo validar la cuenta de Google. redirect={resolved_google_login_redirect_uri()}",
            exc,
        )

    db = SessionLocal()
    try:
        user = _upsert_google_user(db, email)
        token = create_access_token(user.id)
        app_return = safe_app_redirect(extract_login_app_redirect(state or ""))
        if app_return:
            # Deep link: openAuthSessionAsync cierra el browser al ver esta URL.
            return RedirectResponse(url=with_query(app_return, token=token), status_code=302)
        success = f"{_public_base()}/auth/google/success?{urlencode({'token': token})}"
        return RedirectResponse(url=success, status_code=302)
    except Exception as exc:
        logger.exception("Fallo DB/JWT en login Google")
        return oauth_failure_page("No se pudo crear la sesión de Eliseo.", exc)
    finally:
        db.close()


@router.get("/success")
def google_login_success(token: str | None = None, app: str | None = None):
    if not token:
        return oauth_page("Falta el token. Volvé a la app e iniciá sesión otra vez.", 400)
    app_return = safe_app_redirect(app)
    deep = with_query(app_return, token=token) if app_return else ""
    deep_js = deep.replace("\\", "\\\\").replace("'", "\\'")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Eliseo</title>"
        f"{f'<meta http-equiv=\"refresh\" content=\"0;url={deep}\">' if deep else ''}"
        "</head>"
        "<body style='font-family:sans-serif;padding:2rem'>"
        "<p>Listo. Volviendo a la app…</p>"
        + (
            f"<p><a href='{deep}'>Tocá acá si no vuelve sola</a></p>"
            f"<script>try{{window.location.replace('{deep_js}');}}catch(e){{}}</script>"
            if deep
            else "<p>Cerrá esta ventana y volvé a Eliseo.</p>"
        )
        + "</body></html>"
    )
    return HTMLResponse(html)


def _public_base() -> str:
    uri = resolved_google_login_redirect_uri().rstrip("/")
    if uri.endswith("/auth/google/callback"):
        return uri[: -len("/auth/google/callback")]
    cal = settings.google_redirect_uri.rstrip("/")
    if "/connectors/" in cal:
        return cal.split("/connectors/")[0]
    return "https://eliseo-backend.vercel.app"
