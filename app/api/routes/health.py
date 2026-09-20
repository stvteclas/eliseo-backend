from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """
    Endpoint mínimo para confirmar que el servicio está vivo en producción.
    Definición de terminado de T01: este endpoint debe responder en Railway
    después de cada push a main.
    """
    return {"status": "ok"}
