from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.mercadopago_credential import MercadoPagoCredential
from app.models.teams_calendar_credential import TeamsCalendarCredential
from app.models.user import User
from app.schemas.connector import ConnectorCreate, ConnectorOut

router = APIRouter(prefix="/connectors", tags=["connectors"])

# Servicios que guardan credenciales propias: al desconectarlos se borran también.
CREDENTIAL_MODELS = {
    "google_calendar": GoogleCalendarCredential,
    "mercadopago": MercadoPagoCredential,
    "teams_calendar": TeamsCalendarCredential,
}


def upsert_user_connector(
    db: Session, user_id: int, service_name: str, scope: str, store_credential: bool, account_label: str = "default"
) -> tuple[UserConnector, bool]:
    """
    Crea el conector del usuario para esa cuenta puntual de ese servicio, o
    la actualiza si ya existe. Devuelve (conector, creado). Conectar el mismo
    servicio con un account_label nuevo crea una fila nueva, no pisa la
    anterior (HU-T21).
    """
    connector = (
        db.query(UserConnector)
        .filter(
            UserConnector.user_id == user_id,
            UserConnector.service_name == service_name,
            UserConnector.account_label == account_label,
        )
        .first()
    )
    created = connector is None

    if created:
        connector = UserConnector(
            user_id=user_id,
            service_name=service_name,
            account_label=account_label,
            scope=scope,
            store_credential=store_credential,
        )
        db.add(connector)
    else:
        connector.scope = scope
        connector.store_credential = store_credential
        connector.connected_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(connector)
    return connector, created


@router.post("", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED)
def upsert_connector(
    data: ConnectorCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connector, created = upsert_user_connector(
        db, current_user.id, data.service_name, data.scope, data.store_credential, data.account_label
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return connector


@router.get("", response_model=list[ConnectorOut])
def list_connectors(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(UserConnector).filter(UserConnector.user_id == current_user.id).order_by(UserConnector.id).all()


@router.delete("/{service_name}")
def delete_connector(
    service_name: str,
    account_label: str = "default",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connector = (
        db.query(UserConnector)
        .filter(
            UserConnector.user_id == current_user.id,
            UserConnector.service_name == service_name,
            UserConnector.account_label == account_label,
        )
        .first()
    )
    if connector is None:
        raise HTTPException(status_code=404, detail="Esa cuenta de ese servicio no está conectada.")

    db.delete(connector)
    credential_model = CREDENTIAL_MODELS.get(service_name)
    if credential_model is not None:
        # Desconectar también borra los tokens guardados de ESA cuenta puntual, no solo el permiso.
        db.query(credential_model).filter(
            credential_model.user_id == current_user.id, credential_model.account_label == account_label
        ).delete()
    db.commit()
    return {"deleted": service_name, "account_label": account_label}
