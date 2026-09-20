from fastapi import FastAPI

from app.api.routes import health
from app.core.config import settings

app = FastAPI(title="Eliseo", version="0.1.0")

app.include_router(health.router, tags=["health"])


@app.get("/")
def root() -> dict:
    return {"service": "Eliseo backend", "env": settings.env}
