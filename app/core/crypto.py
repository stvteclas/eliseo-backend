"""
Cifrado simétrico (Fernet) para credenciales que Eliseo guarda en la base,
como el refresh token de Google Calendar (HU-T11). La clave vive en
ENCRYPTION_KEY y nunca en la base ni en el repo.
"""

from cryptography.fernet import Fernet

from app.core.config import settings


def _fernet() -> Fernet:
    if not settings.encryption_key:
        raise RuntimeError("Falta ENCRYPTION_KEY en la configuración (ver .env.example).")
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
