from fastapi import FastAPI

from app.api.routes import auth, chat, connectors, google_calendar, health, mercadopago
from app.core.config import settings
from app.core.database import Base, engine
from app.models import connector, google_calendar_credential, mercadopago_credential, user  # noqa: F401 — necesario para que create_all vea los modelos

app = FastAPI(title="Eliseo", version="0.1.0")

# Crea las tablas si no existen. Simple y suficiente para esta etapa;
# cuando el modelo de datos crezca (HU-T15 en adelante), conviene migrar
# a Alembic para manejar cambios de esquema sin perder datos.
Base.metadata.create_all(bind=engine)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(connectors.router)
app.include_router(google_calendar.router)
app.include_router(mercadopago.router)


@app.get("/")
def root() -> dict:
    return {"service": "Eliseo backend", "env": settings.env}
