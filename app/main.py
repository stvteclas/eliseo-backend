from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.api.routes import auth, chat, connectors, google_calendar, health, mercadopago, teams_calendar, voice
from app.core.config import settings
from app.core.database import Base, engine
from app.models import (  # noqa: F401 — necesario para que create_all vea los modelos
    connector,
    google_calendar_credential,
    mercadopago_credential,
    teams_calendar_credential,
    user,
)

app = FastAPI(title="Eliseo", version="0.1.0")

# Crea las tablas si no existen. Simple y suficiente para esta etapa;
# cuando el modelo de datos crezca (HU-T15 en adelante), conviene migrar
# a Alembic para manejar cambios de esquema sin perder datos.
Base.metadata.create_all(bind=engine)


def _ensure_persona_column() -> None:
    """create_all no altera tablas existentes: agrega users.persona si falta."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "persona" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN persona VARCHAR NOT NULL DEFAULT 'elisse'"))


_ensure_persona_column()

app.include_router(health.router, tags=["health"])
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(connectors.router)
app.include_router(google_calendar.router)
app.include_router(mercadopago.router)
app.include_router(teams_calendar.router)
app.include_router(voice.router)


@app.get("/")
def root() -> dict:
    return {"service": "Eliseo backend", "env": settings.env}
