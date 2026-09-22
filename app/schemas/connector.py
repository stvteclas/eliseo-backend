from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConnectorCreate(BaseModel):
    service_name: str
    scope: str
    store_credential: bool = False
    account_label: str = "default"  # HU-T21: distingue varias cuentas del mismo servicio


class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_name: str
    scope: str
    store_credential: bool
    account_label: str
    connected_at: datetime
