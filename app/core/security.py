"""
Hash de contraseñas y emisión/verificación de tokens JWT.
"""

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 horas (antes 7 días)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Devuelve el user_id si el token es válido, o None si no."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        if "purpose" in payload:  # un state de OAuth no vale como access token
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


OAUTH_STATE_EXPIRE_MINUTES = 10
LOGIN_OAUTH_STATE_EXPIRE_MINUTES = 30
OAUTH_STATE_PURPOSE = "oauth_state"
LOGIN_OAUTH_STATE_PURPOSE = "google_login_state"


def create_oauth_state(
    user_id: int,
    account_label: str = "default",
    app_redirect: str | None = None,
) -> str:
    """
    Parámetro `state` del flujo OAuth: firmado y de vida corta. Va en una URL
    (historial, logs), así que NO es el access token del usuario: lleva un
    claim `purpose` y solo sirve para volver del callback de OAuth.

    Lleva también el `account_label` (HU-T21) — qué cuenta puntual del
    servicio se está conectando (ej. "banco", "personal") — para que el
    callback sepa a cuál de las credenciales del usuario corresponde.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "purpose": OAUTH_STATE_PURPOSE,
        "account_label": account_label,
        "exp": int(expire.timestamp()),
    }
    if app_redirect:
        payload["ar"] = app_redirect
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_oauth_state(state: str) -> tuple[int, str] | None:
    """Devuelve (user_id, account_label) si el state es válido, vigente y de OAuth; None si no."""
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[ALGORITHM])
        if payload.get("purpose") != OAUTH_STATE_PURPOSE:
            return None
        return int(payload["sub"]), payload.get("account_label", "default")
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def extract_oauth_app_redirect(state: str) -> str | None:
    """Deep link de la app guardado en el state OAuth de conectores."""
    if not state:
        return None
    try:
        payload = jwt.decode(
            str(state).strip(),
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != OAUTH_STATE_PURPOSE:
        return None
    ar = payload.get("ar")
    return ar if isinstance(ar, str) and ar else None


def create_login_oauth_state(
    code_verifier: str | None = None,
    app_redirect: str | None = None,
) -> str:
    """State firmado para el login con Google (PKCE + deep link de la app)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_OAUTH_STATE_EXPIRE_MINUTES)
    payload = {
        "purpose": LOGIN_OAUTH_STATE_PURPOSE,
        "exp": int(expire.timestamp()),
    }
    if code_verifier:
        payload["cv"] = code_verifier
    if app_redirect:
        payload["ar"] = app_redirect
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def explain_login_oauth_state(state: str) -> str | None:
    """
    None si el state de login es válido.
    Si no, un motivo corto para mostrar en la página de error.
    """
    if not state or not str(state).strip():
        return "state-vacío"
    try:
        payload = jwt.decode(str(state).strip(), settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return "state-expirado"
    except jwt.PyJWTError as exc:
        return f"state-jwt:{type(exc).__name__}"
    if payload.get("purpose") != LOGIN_OAUTH_STATE_PURPOSE:
        return "state-purpose"
    return None


def _login_state_payload(state: str) -> dict | None:
    if not state:
        return None
    try:
        payload = jwt.decode(
            str(state).strip(),
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != LOGIN_OAUTH_STATE_PURPOSE:
        return None
    return payload


def extract_login_code_verifier(state: str) -> str | None:
    """Recupera el code_verifier PKCE guardado en el state de login."""
    payload = _login_state_payload(state)
    if not payload:
        return None
    cv = payload.get("cv")
    return cv if isinstance(cv, str) and cv else None


def extract_login_app_redirect(state: str) -> str | None:
    """Deep link de la app para cerrar openAuthSessionAsync tras el login."""
    payload = _login_state_payload(state)
    if not payload:
        return None
    ar = payload.get("ar")
    return ar if isinstance(ar, str) and ar else None


def decode_login_oauth_state(state: str) -> bool:
    return explain_login_oauth_state(state) is None
