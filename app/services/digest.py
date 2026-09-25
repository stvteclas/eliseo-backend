"""Resúmenes de bandeja, del día y ritual matutino."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.weather import get_weather_report


def _format_now() -> str:
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=-3))
    now = datetime.now(tz)
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    return (
        f"{weekdays[now.weekday()]} {now.day} de {months[now.month - 1]} "
        f"de {now.year}, {now.hour:02d}:{now.minute:02d}"
    )


def inbox_digest(user_id: int, db: Session) -> str:
    parts: list[str] = []
    try:
        from app.agents.orchestrator import build_calendar_tools

        tools = {t.name: t for t in build_calendar_tools(user_id, db)}
        mail = tools.get("get_recent_emails")
        if mail is not None:
            parts.append(mail.invoke({"limit": 5, "query": "is:unread"}))
        else:
            parts.append("Gmail no está conectado.")
        if tools.get("list_chat_contacts") is not None:
            parts.append(tools["list_chat_contacts"].invoke({"limit": 8}))
    except Exception:
        parts.append("No pude armar el resumen de mensajes ahora.")

    try:
        from app.services import telegram as telegram_service

        if telegram_service.is_connected(db, user_id):
            chats = telegram_service.list_dialogs(db, user_id, limit=6)
            parts.append(chats)
        else:
            parts.append("Telegram no está conectado.")
    except Exception:
        parts.append("No pude mirar Telegram ahora.")

    if not parts:
        return "No hay fuentes de mensajes conectadas."
    return "Lo que te escribieron: " + " ".join(parts)


def today_overview(
    user_id: int,
    db: Session,
    latitude: float | None,
    longitude: float | None,
    work_destination: str = "",
) -> str:
    parts = [f"Hoy. Ahora es {_format_now()}."]
    parts.append(get_weather_report(city=None, latitude=latitude, longitude=longitude))
    dest = (work_destination or "").strip()
    if dest:
        try:
            from app.services import traffic as traffic_service

            parts.append(
                traffic_service.travel_time_report(
                    destination=dest,
                    origin=None,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        except Exception:
            parts.append("No pude mirar el tráfico ahora.")
    try:
        from app.agents.orchestrator import build_calendar_tools

        tools = {t.name: t for t in build_calendar_tools(user_id, db)}
        upcoming = tools.get("get_upcoming_calendar_events")
        if upcoming is not None:
            parts.append(upcoming.invoke({}))
        else:
            parts.append("Sin Calendar conectado.")
        mail = tools.get("get_recent_emails")
        if mail is not None:
            parts.append(mail.invoke({"limit": 3, "query": "is:unread newer_than:1d"}))
    except Exception:
        parts.append("Parte de la agenda no se pudo leer.")
    return " ".join(parts)


def morning_ritual(
    user_id: int,
    db: Session,
    latitude: float | None,
    longitude: float | None,
    work_destination: str = "",
) -> str:
    """
    Ritual estable de buenos días: hora, clima, agenda, mensajes, hábito, memoria.
    Pensado para hablarse en voz, no como informe.
    """
    parts = [f"Buenos días. Ahora es {_format_now()}."]
    parts.append(get_weather_report(city=None, latitude=latitude, longitude=longitude))

    dest = (work_destination or "").strip()
    if not dest:
        # Si la memoria tiene laburo/oficina, el tráfico se puede pedir aparte;
        # acá no bloqueamos el ritual.
        pass
    elif dest:
        try:
            from app.services import traffic as traffic_service

            parts.append(
                traffic_service.travel_time_report(
                    destination=dest,
                    origin=None,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        except Exception:
            pass

    try:
        from app.agents.orchestrator import build_calendar_tools

        tools = {t.name: t for t in build_calendar_tools(user_id, db)}
        upcoming = tools.get("get_upcoming_calendar_events")
        if upcoming is not None:
            agenda = upcoming.invoke({})
            # Acortar para voz
            parts.append(agenda[:500] if isinstance(agenda, str) else str(agenda))
        mail = tools.get("get_recent_emails")
        if mail is not None:
            parts.append(mail.invoke({"limit": 2, "query": "is:unread newer_than:1d"}))
    except Exception:
        parts.append("La agenda no salió completa.")

    try:
        from app.services import telegram as telegram_service

        if telegram_service.is_connected(db, user_id):
            parts.append(telegram_service.list_dialogs(db, user_id, limit=4))
    except Exception:
        pass

    try:
        from app.services import habits as habits_service

        habit_txt = habits_service.habit_status(db, user_id, "")
        if "pendiente" in habit_txt.lower():
            parts.append(habit_txt)
        elif "no tenés hábitos" not in habit_txt.lower():
            parts.append(habit_txt)
    except Exception:
        pass

    try:
        from app.services import memory as memory_service

        facts = memory_service.list_facts(db, user_id, limit=1)
        if facts:
            parts.append(f"Dato útil: {facts[0]}.")
    except Exception:
        pass

    parts.append("Cuando quieras, pedime el detalle.")
    return " ".join(parts)
