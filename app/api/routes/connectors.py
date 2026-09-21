from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.user import User
from app.schemas.connector import ConnectorCreate, ConnectorOut

router = APIRouter(prefix="/connectors", tags=["connectors"])


def upsert_user_connector(
    db: Session, user_id: int, service_name: str, scope: str, store_credential: bool
) -> tuple[UserConnector, bool]:
    """Crea el conector del usuario para ese servicio, o lo actualiza. Devuelve (conector, creado)."""
    connector = (
        db.query(UserConnector)
        .filter(UserConnector.user_id == user_id, UserConnector.service_name == service_name)
        .first()
    )
    created = connector is None

    if created:
        connector = UserConnector(
            user_id=user_id, service_name=service_name, scope=scope, store_credential=store_credential
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
        db, current_user.id, data.service_name, data.scope, data.store_credential
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connector = (
        db.query(UserConnector)
        .filter(UserConnector.user_id == current_user.id, UserConnector.service_name == service_name)
        .first()
    )
    if connector is None:
        raise HTTPException(status_code=404, detail="Ese servicio no está conectado.")

    db.delete(connector)
    if service_name == "google_calendar":
        # Desconectar también borra el refresh token guardado, no solo el permiso.
        db.query(GoogleCalendarCredential).filter(GoogleCalendarCredential.user_id == current_user.id).delete()
    db.commit()
    return {"deleted": service_name}
