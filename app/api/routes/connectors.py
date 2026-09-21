from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db
from app.models.connector import UserConnector
from app.models.user import User
from app.schemas.connector import ConnectorCreate, ConnectorOut

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED)
def upsert_connector(
    data: ConnectorCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Crea el conector del usuario para ese servicio, o lo actualiza si ya existe."""
    connector = (
        db.query(UserConnector)
        .filter(UserConnector.user_id == current_user.id, UserConnector.service_name == data.service_name)
        .first()
    )

    if connector:
        connector.scope = data.scope
        connector.store_credential = data.store_credential
        connector.connected_at = datetime.now(timezone.utc)
        response.status_code = status.HTTP_200_OK
    else:
        connector = UserConnector(
            user_id=current_user.id,
            service_name=data.service_name,
            scope=data.scope,
            store_credential=data.store_credential,
        )
        db.add(connector)

    db.commit()
    db.refresh(connector)
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
    db.commit()
    return {"deleted": service_name}
