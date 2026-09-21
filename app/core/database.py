"""
Conexión a la base de datos.

En local, sin configurar nada, usa un archivo SQLite (eliseo.db) — sirve
para desarrollar y probar. En producción (Vercel), hay que setear
DATABASE_URL a un Postgres real (Neon o Supabase desde el marketplace
de Vercel) — SQLite no sirve ahí porque el filesystem no persiste entre
invocaciones de la función serverless.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency de FastAPI: abre una sesión de DB por request y la cierra al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
