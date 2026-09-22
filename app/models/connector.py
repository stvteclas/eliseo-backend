"""
Manifiesto de conectores (HU-T15): qué servicio autorizó cada usuario,
con qué alcance, y si Eliseo guarda o no la credencial.

Es la base de HU-T04 (el orquestador carga solo las herramientas que el
usuario autorizó) y del onboarding granular. Por ahora service_name y
scope son strings libres, sin enum ni lista cerrada.

account_label (HU-T21) distingue varias cuentas del mismo servicio (ej.
3 cuentas de Teams: "banco", "agencia", "personal"). Sin especificar,
vale "default" — así los servicios de una sola cuenta (Calendar, Mercado
Pago) siguen funcionando sin que el usuario tenga que hacer nada distinto.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.database import Base


class UserConnector(Base):
    __tablename__ = "user_connectors"
    __table_args__ = (
        # HU-T21: un usuario puede tener más de una cuenta del mismo servicio
        # (ej. 3 cuentas de Teams), distinguidas por account_label.
        UniqueConstraint("user_id", "service_name", "account_label", name="uq_user_connectors_user_service_account"),
    )

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    service_name: Mapped[str] = Column(String, nullable=False)
    account_label: Mapped[str] = Column(String, nullable=False, default="default")
    scope: Mapped[str] = Column(String, nullable=False)
    store_credential: Mapped[bool] = Column(Boolean, default=False, nullable=False)
    connected_at: Mapped[datetime] = Column(DateTime, default=lambda: datetime.now(timezone.utc))
