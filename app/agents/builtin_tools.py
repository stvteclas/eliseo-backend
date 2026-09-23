"""
Herramientas built-in siempre disponibles (sin conector OAuth).

Incluye hora/clima, notas, cálculo, viaje, noticias, traducción,
acciones del teléfono (timer, push local, llamar) y resumen del día.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.agents.client_actions import queue_client_action
from app.services import calculator as calculator_service
from app.services import news as news_service
from app.services import notes as notes_service
from app.services import traffic as traffic_service
from app.services import translate as translate_service
from app.services.weather import get_weather_report

ARGENTINA_TZ = timezone(timedelta(hours=-3))

BUILTIN_TOOL_NAMES = [
    "get_current_datetime",
    "get_weather",
    "set_timer",
    "add_note",
    "list_notes",
    "remove_note",
    "clear_notes",
    "calculate",
    "convert_currency",
    "get_travel_time",
    "get_news_headlines",
    "translate_text",
    "start_translator_mode",
    "stop_translator_mode",
    "schedule_local_reminder",
    "call_contact",
    "get_daily_briefing",
    "get_onboarding_status",
    "start_service_connection",
]


def _format_argentina_now() -> str:
    now = datetime.now(ARGENTINA_TZ)
    weekdays = (
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    )
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
        f"de {now.year}, {now.hour:02d}:{now.minute:02d} (hora de Argentina)"
    )


def _parse_duration_seconds(minutes: float = 0, seconds: float = 0) -> int | None:
    total = int(round(float(minutes or 0) * 60 + float(seconds or 0)))
    if total <= 0:
        return None
    return min(total, 24 * 3600)  # tope 24 h


def build_builtin_tools(
    user_id: int | None = None,
    db: Session | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list:
    def get_current_datetime() -> str:
        return _format_argentina_now()

    def get_weather(city: str = "") -> str:
        """
        Clima actual. Pasá una ciudad (ej. 'Buenos Aires') o dejá vacío para
        usar la ubicación GPS del usuario si la app la mandó.
        """
        city_arg = city.strip() or None
        return get_weather_report(city=city_arg, latitude=latitude, longitude=longitude)

    def set_timer(minutes: float = 0, seconds: float = 0, label: str = "") -> str:
        """
        Programa un temporizador en el teléfono del usuario.
        Usá minutes y/o seconds. label es opcional (ej. 'pasta').
        """
        total = _parse_duration_seconds(minutes, seconds)
        if total is None:
            return "Decime cuántos minutos o segundos querés en el temporizador."
        title = (label or "Temporizador").strip()[:80] or "Temporizador"
        queue_client_action({"type": "timer", "seconds": total, "label": title})
        if total < 60:
            human = f"{total} segundos"
        else:
            m, s = divmod(total, 60)
            human = f"{m} minutos" if s == 0 else f"{m} minutos y {s} segundos"
        return f"Listo, puse un temporizador de {human}" + (f" para {title}." if label else ".")

    def add_note(text: str, list_name: str = "compras") -> str:
        """Agrega un ítem a una lista (por defecto 'compras')."""
        if user_id is None or db is None:
            return "No pude guardar la nota ahora."
        return notes_service.add_note(db, user_id, text, list_name)

    def list_notes(list_name: str = "compras") -> str:
        """Lee los ítems de una lista (por defecto 'compras')."""
        if user_id is None or db is None:
            return "No pude leer la lista ahora."
        return notes_service.list_notes(db, user_id, list_name)

    def remove_note(text: str, list_name: str = "compras") -> str:
        """Saca un ítem de la lista si el texto coincide."""
        if user_id is None or db is None:
            return "No pude modificar la lista ahora."
        return notes_service.remove_note(db, user_id, text, list_name)

    def clear_notes(list_name: str = "compras") -> str:
        """Vacía una lista completa."""
        if user_id is None or db is None:
            return "No pude vaciar la lista ahora."
        return notes_service.clear_notes(db, user_id, list_name)

    def calculate(expression: str) -> str:
        """Calcula una expresión (ej. '12*15', '15% de 2400')."""
        return calculator_service.evaluate_expression(expression)

    def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
        """Convierte monedas (ej. amount=100, from_currency='USD', to_currency='ARS')."""
        return calculator_service.convert_currency(amount, from_currency, to_currency)

    def get_travel_time(destination: str, origin: str = "") -> str:
        """
        Tráfico y tiempo en auto hasta destination (ej. 'Obelisco', 'aeropuerto Ezeiza').
        Usala si preguntan por tráfico, demora, cuánto tardan o cómo está el camino.
        origin opcional; si está vacío usa el GPS del usuario.
        """
        return traffic_service.travel_time_report(
            destination=destination,
            origin=origin or None,
            latitude=latitude,
            longitude=longitude,
        )

    def get_news_headlines(limit: float = 5, topic: str = "") -> str:
        """Titulares breves de Argentina. topic opcional para filtrar."""
        return news_service.get_headlines(limit=int(limit or 5), query=topic)

    def translate_text(text: str, target_lang: str = "en", source_lang: str = "es") -> str:
        """Traduce text al idioma target_lang (código o nombre: en, inglés, pt...)."""
        return translate_service.translate_text(text, target_lang=target_lang, source_lang=source_lang)

    def start_translator_mode(lang_a: str, lang_b: str) -> str:
        """
        Activa modo traductor bidireccional entre lang_a y lang_b
        (ej. 'español' y 'ruso', o 'es' y 'ru').
        Todo lo que diga el usuario se traduce al otro idioma hasta que lo apague.
        """
        if user_id is None or db is None:
            return "No pude activar el traductor ahora."
        a = translate_service.normalize_lang(lang_a)
        b = translate_service.normalize_lang(lang_b)
        if a == b:
            return "Necesito dos idiomas distintos, por ejemplo español y ruso."
        from app.models.user import User

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return "No encontré tu usuario."
        user.translator_lang_a = a
        user.translator_lang_b = b
        db.add(user)
        db.commit()
        return (
            f"Listo, modo traductor entre {translate_service._label(a)} y "
            f"{translate_service._label(b)}. Hablame en uno y te lo digo en el otro. "
            f"Para salir, decí salí del modo traductor."
        )

    def stop_translator_mode() -> str:
        """Apaga el modo traductor bidireccional."""
        if user_id is None or db is None:
            return "No pude apagar el traductor ahora."
        from app.models.user import User

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return "No encontré tu usuario."
        user.translator_lang_a = None
        user.translator_lang_b = None
        db.add(user)
        db.commit()
        return "Listo, salí del modo traductor."

    def schedule_local_reminder(message: str, minutes: float = 0, seconds: float = 0) -> str:
        """
        Programa una notificación local en el teléfono (push local).
        minutes/seconds = demora desde ahora. message = texto del aviso.
        """
        total = _parse_duration_seconds(minutes, seconds)
        body = (message or "").strip()
        if total is None:
            return "Decime en cuánto tiempo querés el aviso."
        if not body:
            return "Decime qué te tengo que recordar."
        queue_client_action(
            {
                "type": "local_notification",
                "seconds": total,
                "title": "Eliseo",
                "body": body[:200],
            }
        )
        if total < 60:
            human = f"{total} segundos"
        else:
            m, s = divmod(total, 60)
            human = f"{m} minutos" if s == 0 else f"{m} minutos y {s} segundos"
        return f"Dale, en {human} te aviso: {body}."

    def call_contact(name: str) -> str:
        """
        Pide a la app que busque un contacto por nombre y abra el marcador.
        """
        query = (name or "").strip()
        if not query:
            return "Decime a quién querés llamar."
        queue_client_action({"type": "call_contact", "query": query})
        return f"Busco a {query} en tus contactos y abro el teléfono."

    def get_daily_briefing(city: str = "") -> str:
        """
        Resumen del día: hora, clima y próximos eventos del calendario si hay.
        """
        parts = [f"Ahora es {_format_argentina_now()}."]
        city_arg = city.strip() or None
        parts.append(get_weather_report(city=city_arg, latitude=latitude, longitude=longitude))

        if user_id is not None and db is not None:
            try:
                from app.agents.orchestrator import build_calendar_tools

                cal_tools = build_calendar_tools(user_id, db)
                by_name = {t.name: t for t in cal_tools}
                upcoming = by_name.get("get_upcoming_calendar_events")
                if upcoming is not None:
                    parts.append(upcoming.invoke({}))
                else:
                    parts.append("No tenés Google Calendar conectado para ver la agenda.")
            except Exception:
                parts.append("No pude leer la agenda ahora.")
        return " ".join(parts)

    def get_onboarding_status() -> str:
        """Dice qué servicios faltan conectar (Calendar, Mercado Pago, Teams)."""
        if user_id is None or db is None:
            return "No pude revisar tus conexiones ahora."
        from app.services.onboarding import get_onboarding_status as status_fn

        return status_fn(db, user_id)["guide"]

    def start_service_connection(service: str = "google_calendar") -> str:
        """
        Abre en el teléfono el flujo para conectar un servicio.
        service: google_calendar | mercadopago | teams_calendar
        """
        from app.services.onboarding import ONBOARDING_SERVICES

        key = (service or "google_calendar").strip().lower()
        spec = next((s for s in ONBOARDING_SERVICES if s["id"] == key), None)
        if spec is None:
            return "No conozco ese servicio. Probá google_calendar, mercadopago o teams_calendar."
        queue_client_action(
            {
                "type": "connect_service",
                "service": spec["id"],
                "authorize_path": spec["authorize_path"],
                "label": spec["label"],
            }
        )
        return (
            f"Te abro la conexión de {spec['label']}. "
            f"{spec['hint']} Cuando termines en el navegador, volvé y avisame."
        )

    return [
        StructuredTool.from_function(
            func=get_current_datetime,
            name="get_current_datetime",
            description="Devuelve la fecha y hora actual en Argentina.",
        ),
        StructuredTool.from_function(
            func=get_weather,
            name="get_weather",
            description=(
                "Devuelve el clima actual. Pasá city con el nombre de una ciudad, "
                "o dejá city vacío para usar la ubicación GPS del usuario si está disponible."
            ),
        ),
        StructuredTool.from_function(
            func=set_timer,
            name="set_timer",
            description=(
                "Programa un temporizador en el teléfono. "
                "Pasá minutes y/o seconds. label opcional."
            ),
        ),
        StructuredTool.from_function(
            func=add_note,
            name="add_note",
            description="Agrega un ítem a una lista (default list_name='compras').",
        ),
        StructuredTool.from_function(
            func=list_notes,
            name="list_notes",
            description="Lee los ítems de una lista (default 'compras').",
        ),
        StructuredTool.from_function(
            func=remove_note,
            name="remove_note",
            description="Saca un ítem de la lista buscando por texto.",
        ),
        StructuredTool.from_function(
            func=clear_notes,
            name="clear_notes",
            description="Vacía por completo una lista.",
        ),
        StructuredTool.from_function(
            func=calculate,
            name="calculate",
            description="Calcula una expresión aritmética o un porcentaje (ej. '15% de 2400').",
        ),
        StructuredTool.from_function(
            func=convert_currency,
            name="convert_currency",
            description="Convierte monedas (amount, from_currency, to_currency), ej. USD a ARS.",
        ),
        StructuredTool.from_function(
            func=get_travel_time,
            name="get_travel_time",
            description=(
                "Tráfico y tiempo en auto hasta un destino. Usar ante preguntas "
                "de tráfico, demora, 'cuánto tardo' o 'cómo está el camino'. "
                "destination obligatorio; origin opcional (si falta usa GPS)."
            ),
        ),
        StructuredTool.from_function(
            func=get_news_headlines,
            name="get_news_headlines",
            description="Titulares breves de Argentina. topic opcional.",
        ),
        StructuredTool.from_function(
            func=translate_text,
            name="translate_text",
            description="Traduce un texto puntual. target_lang por defecto 'en' (inglés).",
        ),
        StructuredTool.from_function(
            func=start_translator_mode,
            name="start_translator_mode",
            description=(
                "Activa modo traductor continuo entre dos idiomas (lang_a, lang_b), "
                "ej. español y ruso. Usar cuando piden 'haceme de traductor'."
            ),
        ),
        StructuredTool.from_function(
            func=stop_translator_mode,
            name="stop_translator_mode",
            description="Apaga el modo traductor continuo.",
        ),
        StructuredTool.from_function(
            func=schedule_local_reminder,
            name="schedule_local_reminder",
            description=(
                "Notificación local en el teléfono dentro de minutes/seconds. "
                "Usar para 'avisame en X minutos' cuando no hace falta el calendario."
            ),
        ),
        StructuredTool.from_function(
            func=call_contact,
            name="call_contact",
            description="Busca un contacto por nombre en el teléfono y abre el marcador para llamar.",
        ),
        StructuredTool.from_function(
            func=get_daily_briefing,
            name="get_daily_briefing",
            description=(
                "Resumen del día: hora + clima + próximos eventos. "
                "Usar ante 'buenos días', 'resumen del día', etc."
            ),
        ),
        StructuredTool.from_function(
            func=get_onboarding_status,
            name="get_onboarding_status",
            description="Revisa qué servicios faltan conectar y cómo guiar al usuario.",
        ),
        StructuredTool.from_function(
            func=start_service_connection,
            name="start_service_connection",
            description=(
                "Abre el flujo OAuth en el teléfono para conectar un servicio. "
                "service=google_calendar (obligatorio), mercadopago o teams_calendar."
            ),
        ),
    ]
