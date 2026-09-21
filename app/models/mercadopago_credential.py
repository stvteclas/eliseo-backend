"""
Credenciales de Mercado Pago por usuario (HU-T20), cifradas con Fernet
(ver app/core/crypto.py). Los links de pago se crean con el access token
DEL USUARIO, así que la plata entra a su cuenta y no a una de la app.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped

from app.core.database import Base


class MercadoPagoCredential(Base):
    __tablename__ = "mercadopago_credentials"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    mp_user_id: Mapped[str] = Column(String, nullable=False)  # ID de la cuenta de MP del usuario
    access_token_encrypted: Mapped[str] = Column(String, nullable=False)
    # Hoy no se usa (no hay refresh automático todavía, ver build_mercadopago_tool).
    refresh_token_encrypted: Mapped[str | None] = Column(String, nullable=True)
    expires_at: Mapped[datetime | None] = Column(DateTime, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
