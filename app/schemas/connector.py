from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConnectorCreate(BaseModel):
    service_name: str
    scope: str
    store_credential: bool = False


class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_name: str
    scope: str
    store_credential: bool
    connected_at: datetime
