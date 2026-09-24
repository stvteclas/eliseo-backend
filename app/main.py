from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.api.routes import auth, auth_google, chat, connectors, google_calendar, health, mercadopago, teams_calendar, telegram, voice
from app.core.config import settings
from app.core.database import Base, engine
from app.models import (  # noqa: F401 — necesario para que create_all vea los modelos
    connector,
    google_calendar_credential,
    habit,
    mercadopago_credential,
    note,
    teams_calendar_credential,
    telegram_credential,
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
        conn.execute(text("ALTER TABLE users ADD COLUMN persona VARCHAR NOT NULL DEFAULT 'eliseo'"))


_ensure_persona_column()


def _ensure_translator_columns() -> None:
    """Agrega columnas de modo traductor si faltan (create_all no altera tablas)."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "translator_lang_a" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN translator_lang_a VARCHAR"))
        if "translator_lang_b" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN translator_lang_b VARCHAR"))


_ensure_translator_columns()


def _ensure_prefs_and_notes_columns() -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "users" in tables:
        columns = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "wake_name" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN wake_name VARCHAR"))
            if "quiet_mode" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN quiet_mode BOOLEAN DEFAULT 0 NOT NULL"))
            if "confirm_sends" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN confirm_sends BOOLEAN DEFAULT 0 NOT NULL"))
            if "meeting_until" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN meeting_until TIMESTAMP"))
            if "speak_slow" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN speak_slow BOOLEAN DEFAULT 0 NOT NULL"))
    if "notes" in tables:
        ncols = {col["name"] for col in inspector.get_columns("notes")}
        if "done" not in ncols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE notes ADD COLUMN done BOOLEAN DEFAULT 0 NOT NULL"))


_ensure_prefs_and_notes_columns()

app.include_router(health.router, tags=["health"])
app.include_router(auth.router)
app.include_router(auth_google.router)
app.include_router(chat.router)
app.include_router(connectors.router)
app.include_router(google_calendar.router)
app.include_router(mercadopago.router)
app.include_router(teams_calendar.router)
app.include_router(telegram.router)
app.include_router(voice.router)


@app.get("/")
def root() -> dict:
    return {"service": "Eliseo backend", "env": settings.env}
