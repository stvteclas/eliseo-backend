"""Catálogo de onboarding: qué debe conectar cada usuario nuevo."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.connector import UserConnector

# Servicios que Eliseo puede guiar a conectar (mismo set que ya usás vos).
ONBOARDING_SERVICES: list[dict] = [
    {
        "id": "google_calendar",
        "label": "Google Calendar",
        "required": True,
        "authorize_path": "/connectors/google_calendar/authorize",
        "hint": "Para agenda, recordatorios y leer o mandar mails de Gmail.",
    },
    {
        "id": "mercadopago",
        "label": "Mercado Pago",
        "required": False,
        "authorize_path": "/connectors/mercadopago/authorize",
        "hint": "Para generar links de pago.",
    },
    {
        "id": "teams_calendar",
        "label": "Teams o Outlook",
        "required": False,
        "authorize_path": "/connectors/teams_calendar/authorize",
        "hint": "Para leer el calendario de Microsoft.",
    },
]


def get_onboarding_status(db: Session, user_id: int) -> dict:
    connected_names = {
        c.service_name
        for c in db.query(UserConnector).filter(UserConnector.user_id == user_id).all()
    }
    services = []
    missing_required = []
    missing_optional = []
    next_step = None

    for spec in ONBOARDING_SERVICES:
        connected = spec["id"] in connected_names
        item = {
            "id": spec["id"],
            "label": spec["label"],
            "required": spec["required"],
            "connected": connected,
            "authorize_path": spec["authorize_path"],
            "hint": spec["hint"],
        }
        services.append(item)
        if connected:
            continue
        if spec["required"]:
            missing_required.append(item)
        else:
            missing_optional.append(item)
        if next_step is None:
            next_step = item

    ready = len(missing_required) == 0
    return {
        "ready": ready,
        "services": services,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "next_step": next_step,
        "guide": _build_guide(ready, missing_required, missing_optional, next_step),
    }


def _build_guide(
    ready: bool,
    missing_required: list[dict],
    missing_optional: list[dict],
    next_step: dict | None,
) -> str:
    if ready and not missing_optional:
        return "Ya tenés todo conectado. Preguntame lo que quieras."
    if ready and missing_optional:
        names = ", ".join(s["label"] for s in missing_optional)
        return (
            f"Google Calendar ya está. Si querés, después podemos conectar {names}. "
            "Por ahora ya podés usarme normal."
        )
    if next_step:
        return (
            f"Para empezar necesito que conectes {next_step['label']}. "
            f"{next_step['hint']} "
            "Tocá el cuadrado o pedime que te abra la conexión."
        )
    return "Hay servicios pendientes de conectar."
