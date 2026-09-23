"""
Login con Google (OAuth web) separado del conector de Calendar.

  1. GET /auth/google/authorize → URL de Google (openid email profile)
  2. Callback GET /auth/google/callback → crea/busca usuario → redirige a
     /auth/google/success?token=JWT para que openAuthSessionAsync lo capture.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.oauth_pages import oauth_failure_page, oauth_page
from app.core.security import (
    create_access_token,
    create_login_oauth_state,
    decode_login_oauth_state,
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


def _login_flow() -> Flow:
    redirect_uri = resolved_google_login_redirect_uri()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URL,
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=LOGIN_SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def _exchange_code_for_access_token(code: str) -> str:
    """Canje manual del code: evita fallos de scope de google-auth-oauthlib."""
    redirect_uri = resolved_google_login_redirect_uri()
    with httpx.Client() as client:
        response = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"Google token exchange {response.status_code}: {detail}")
        data = response.json()
    access = data.get("access_token")
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
def authorize_google_login() -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth no está configurado.")
    redirect_uri = resolved_google_login_redirect_uri()
    if not redirect_uri:
        raise HTTPException(status_code=503, detail="Falta GOOGLE_LOGIN_REDIRECT_URI.")

    flow = _login_flow()
    authorize_url, _ = flow.authorization_url(
        access_type="online",
        prompt="select_account",
        state=create_login_oauth_state(),
    )
    return {"authorize_url": authorize_url, "redirect_uri": redirect_uri}


@router.get("/callback")
def google_login_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return oauth_page("No se autorizó el acceso con Google. Cerrá esta pestaña e intentá de nuevo.", 400)
    if not code or not state or not decode_login_oauth_state(state):
        return oauth_page("El enlace de login no es válido o venció. Volvé a intentar desde la app.", 400)

    db = SessionLocal()
    try:
        access_token = _exchange_code_for_access_token(code)
        email = _fetch_google_email(access_token)
        user = _upsert_google_user(db, email)
        token = create_access_token(user.id)
        success = f"{_public_base()}/auth/google/success?{urlencode({'token': token})}"
        return RedirectResponse(url=success, status_code=302)
    except Exception as exc:
        logger.exception("Fallo en callback de login Google")
        return oauth_failure_page("No se pudo completar el login con Google.", exc)
    finally:
        db.close()


@router.get("/success")
def google_login_success(token: str | None = None):
    """
    Landing mínima: la app cierra el browser al llegar acá y lee ?token=.
    También muestra un mensaje por si el usuario abrió el link a mano.
    """
    if not token:
        return oauth_page("Falta el token. Volvé a la app e iniciá sesión otra vez.", 400)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Eliseo</title></head>"
        "<body style='font-family:sans-serif;padding:2rem'>"
        "<p>Listo. Ya podés volver a la app.</p>"
        "</body></html>"
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
