"""
Hash de contraseñas y emisión/verificación de tokens JWT.
"""

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días — ajustar más adelante si hace falta


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
OAUTH_STATE_PURPOSE = "oauth_state"


def create_oauth_state(user_id: int, account_label: str = "default") -> str:
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
        "exp": expire,
    }
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
