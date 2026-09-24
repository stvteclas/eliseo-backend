"""
Herramientas built-in siempre disponibles (sin conector OAuth).

Incluye hora/clima, notas, cálculo, viaje, noticias, traducción,
acciones del teléfono (timer, push local, llamar, música), resumen del día
y material de estudio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.agents.client_actions import queue_client_action
from app.services import calculator as calculator_service
from app.services import digest as digest_service
from app.services import habits as habits_service
from app.services import music as music_service
from app.services import news as news_service
from app.services import notes as notes_service
from app.services import pending_confirm
from app.services import prefs as prefs_service
from app.services import study as study_service
from app.services import telegram as telegram_service
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
    "check_off_note",
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
    "get_today_overview",
    "get_inbox_digest",
    "make_study_summary",
    "play_music",
    "stop_music",
    "set_wake_name",
    "set_quiet_mode",
    "set_confirm_sends",
    "start_meeting_mode",
    "stop_meeting_mode",
    "mark_habit_done",
    "habit_status",
    "start_pomodoro",
    "start_breathing",
    "confirm_pending_action",
    "cancel_pending_action",
    "repeat_last",
    "speak_slower",
    "speak_normal",
    "broadcast_message",
    "telegram_status",
    "connect_telegram",
    "confirm_telegram_code",
    "confirm_telegram_password",
    "disconnect_telegram",
    "list_telegram_chats",
    "get_telegram_messages",
    "send_telegram_message",
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

    def check_off_note(text: str, list_name: str = "compras") -> str:
        """Tacha un ítem de la lista de compras / encargos."""
        if user_id is None or db is None:
            return "No pude tachar el ítem ahora."
        return notes_service.check_off_note(db, user_id, text, list_name)

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

    def get_daily_briefing(city: str = "", work_destination: str = "") -> str:
        """
        Resumen del día: hora, clima, tráfico opcional al laburo y agenda.
        work_destination ej. 'oficina Microcentro' si querés tráfico.
        """
        if user_id is not None and db is not None:
            return digest_service.today_overview(
                user_id, db, latitude, longitude, work_destination=work_destination
            )
        parts = [f"Ahora es {_format_argentina_now()}."]
        city_arg = city.strip() or None
        parts.append(get_weather_report(city=city_arg, latitude=latitude, longitude=longitude))
        return " ".join(parts)

    def get_today_overview(work_destination: str = "") -> str:
        """Qué tenés hoy: clima, agenda, mails sin leer y tráfico opcional."""
        if user_id is None or db is None:
            return "No pude armar el resumen de hoy."
        return digest_service.today_overview(
            user_id, db, latitude, longitude, work_destination=work_destination
        )

    def get_inbox_digest() -> str:
        """Resumen de mails sin leer y contactos de Chat."""
        if user_id is None or db is None:
            return "No pude mirar la bandeja."
        return digest_service.inbox_digest(user_id, db)

    def set_wake_name(name: str) -> str:
        """Cambia cómo te gusta llamarme (wake word). La app sigue llamándose Eliseo."""
        if user_id is None or db is None:
            return "No pude guardar el nombre."
        return prefs_service.set_wake_name(db, user_id, name)

    def set_quiet_mode(enabled: bool = True) -> str:
        """Modo silencio: solo respondo si me llamás por nombre."""
        if user_id is None or db is None:
            return "No pude cambiar el modo silencio."
        return prefs_service.set_quiet_mode(db, user_id, bool(enabled))

    def set_confirm_sends(enabled: bool = True) -> str:
        """Pide 'dale' antes de mandar mails, chats o pagos."""
        if user_id is None or db is None:
            return "No pude cambiar la confirmación."
        return prefs_service.set_confirm_sends(db, user_id, bool(enabled))

    def start_meeting_mode(minutes: float = 60) -> str:
        """Silencia avisos proactivos por N minutos."""
        if user_id is None or db is None:
            return "No pude activar modo reunión."
        return prefs_service.start_meeting_mode(db, user_id, minutes)

    def stop_meeting_mode() -> str:
        """Sale del modo reunión."""
        if user_id is None or db is None:
            return "No pude salir del modo reunión."
        return prefs_service.stop_meeting_mode(db, user_id)

    def mark_habit_done(name: str) -> str:
        """Marca un hábito de hoy (agua, pastilla, ejercicio…)."""
        if user_id is None or db is None:
            return "No pude marcar el hábito."
        return habits_service.mark_habit_done(db, user_id, name)

    def habit_status(name: str = "") -> str:
        """Consulta hábitos de hoy. name opcional."""
        if user_id is None or db is None:
            return "No pude leer hábitos."
        return habits_service.habit_status(db, user_id, name)

    def start_pomodoro(minutes: float = 25) -> str:
        """Temporizador Pomodoro (default 25 min)."""
        mins = max(1, min(int(minutes or 25), 90))
        return set_timer(minutes=float(mins), seconds=0, label="Pomodoro")

    def start_breathing(minutes: float = 2) -> str:
        """Pausa de respiración guiada (default 2 min) + timer."""
        mins = max(1, min(int(minutes or 2), 10))
        set_timer(minutes=float(mins), seconds=0, label="Respiración")
        return (
            f"Vamos {mins} minuto{'s' if mins != 1 else ''} de respiración: "
            "inhalá por la nariz contando cuatro, sostené cuatro, exhalá seis. "
            "Te aviso cuando termine."
        )

    def confirm_pending_action() -> str:
        """Confirma la acción pendiente (después de 'dale')."""
        if user_id is None:
            return "No hay usuario."
        return pending_confirm.confirm_pending(user_id)

    def cancel_pending_action() -> str:
        """Cancela la acción pendiente."""
        if user_id is None:
            return "No hay usuario."
        return pending_confirm.cancel_pending(user_id)

    def repeat_last() -> str:
        """Pide a la app repetir la última respuesta."""
        queue_client_action({"type": "repeat_last"})
        return "Repito."

    def speak_slower() -> str:
        """Habla más despacio."""
        if user_id is not None and db is not None:
            from app.models.user import User

            user = db.query(User).filter(User.id == user_id).first()
            if user is not None:
                user.speak_slow = True
                db.add(user)
                db.commit()
        queue_client_action({"type": "speak_slow", "enabled": True})
        return "Listo, hablo más despacio."

    def speak_normal() -> str:
        """Vuelve a la velocidad normal de voz."""
        if user_id is not None and db is not None:
            from app.models.user import User

            user = db.query(User).filter(User.id == user_id).first()
            if user is not None:
                user.speak_slow = False
                db.add(user)
                db.commit()
        queue_client_action({"type": "speak_slow", "enabled": False})
        return "Listo, velocidad normal."

    def broadcast_message(contacts: str, text: str, channel: str = "chat") -> str:
        """
        Manda el mismo mensaje a varios contactos.
        contacts: nombres o emails separados por coma.
        channel: chat | email | telegram
        """
        if user_id is None or db is None:
            return "No pude enviar ahora."
        body = (text or "").strip()
        if not body:
            return "Decime el texto del mensaje."
        raw_contacts = [c.strip() for c in (contacts or "").split(",") if c.strip()]
        if not raw_contacts:
            return "Decime a quién: nombres o emails separados por coma."
        ch = (channel or "chat").strip().lower()
        if ch not in {"chat", "email", "mail", "gmail", "telegram", "tg"}:
            ch = "chat"

        def _runner() -> str:
            from app.agents.orchestrator import build_calendar_tools

            results = []
            if ch in {"telegram", "tg"}:
                for c in raw_contacts:
                    results.append(telegram_service.send_message(db, user_id, c, body))
                return " ".join(results)

            tools = {t.name: t for t in build_calendar_tools(user_id, db)}
            if ch == "chat":
                send = tools.get("send_chat_message")
                if send is None:
                    return "Google Chat no está conectado."
                for c in raw_contacts:
                    results.append(send.invoke({"contact": c, "text": body}))
            else:
                send = tools.get("send_email")
                if send is None:
                    return "Gmail no está conectado."
                for c in raw_contacts:
                    results.append(send.invoke({"to": c, "subject": "Mensaje", "body": body}))
            return " ".join(results)

        from app.models.user import User

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.confirm_sends:
            pending_confirm.set_pending(
                user_id,
                f"broadcast {ch} a {', '.join(raw_contacts)}",
                _runner,
            )
            return f"¿Mando ese mensaje por {ch} a {len(raw_contacts)} contactos? Decí dale o cancelá."
        return _runner()

    def telegram_status() -> str:
        """Estado de la conexión de Telegram."""
        if user_id is None or db is None:
            return "No pude revisar Telegram."
        return telegram_service.status_text(db, user_id)

    def connect_telegram(phone: str) -> str:
        """
        Empieza el login de Telegram (cuenta personal).
        phone: número con código de país, ej. +54911…
        """
        if user_id is None or db is None:
            return "No pude conectar Telegram ahora."
        return telegram_service.start_login(db, user_id, phone)

    def confirm_telegram_code(code: str) -> str:
        """Confirma el código que Telegram mandó al teléfono."""
        if user_id is None or db is None:
            return "No pude confirmar el código."
        return telegram_service.confirm_code(db, user_id, code)

    def confirm_telegram_password(password: str) -> str:
        """Contraseña 2FA de Telegram si la pide."""
        if user_id is None or db is None:
            return "No pude confirmar la contraseña."
        return telegram_service.confirm_password(db, user_id, password)

    def disconnect_telegram() -> str:
        """Desconecta Telegram de Eliseo."""
        if user_id is None or db is None:
            return "No pude desconectar."
        return telegram_service.disconnect(db, user_id)

    def list_telegram_chats(limit: float = 15) -> str:
        """Lista chats recientes de Telegram."""
        if user_id is None or db is None:
            return "No pude listar chats."
        return telegram_service.list_dialogs(db, user_id, int(limit or 15))

    def get_telegram_messages(contact: str, limit: float = 8) -> str:
        """Lee mensajes recientes de un chat de Telegram (nombre o @usuario)."""
        if user_id is None or db is None:
            return "No pude leer Telegram."
        return telegram_service.get_messages(db, user_id, contact, int(limit or 8))

    def send_telegram_message(contact: str, text: str) -> str:
        """Envía un mensaje de Telegram a un contacto o @usuario."""
        if user_id is None or db is None:
            return "No pude enviar por Telegram."

        def _send() -> str:
            return telegram_service.send_message(db, user_id, contact, text)

        from app.models.user import User

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.confirm_sends:
            pending_confirm.set_pending(
                user_id,
                f"Telegram a {contact}: {(text or '')[:60]}",
                _send,
            )
            return f"¿Le mando por Telegram a {contact}? Decí dale o cancelá."
        return _send()

    def get_onboarding_status() -> str:
        """Dice qué servicios faltan conectar (Calendar, Mercado Pago, Teams)."""
        if user_id is None or db is None:
            return "No pude revisar tus conexiones ahora."
        from app.services.onboarding import get_onboarding_status as status_fn

        return status_fn(db, user_id)["guide"]

    def start_service_connection(service: str = "google_calendar") -> str:
        """
        Abre en el teléfono el flujo para conectar un servicio.
        service: google_calendar | mercadopago | teams_calendar | telegram
        """
        from app.services.onboarding import ONBOARDING_SERVICES

        key = (service or "google_calendar").strip().lower()
        if key in {"telegram", "tg"}:
            return (
                "Para Telegram no hace falta el navegador. "
                "Decime tu número con código de país (por ejemplo más 54 9 11…) "
                "y uso connect_telegram. Después dictás el código."
            )
        spec = next((s for s in ONBOARDING_SERVICES if s["id"] == key), None)
        if spec is None:
            return (
                "No conozco ese servicio. Probá google_calendar, mercadopago, "
                "teams_calendar o telegram."
            )
        if not spec.get("authorize_path"):
            return f"Para {spec['label']}: {spec['hint']}"
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

    def make_study_summary(material: str, mode: str = "resumen", depth: str = "medio") -> str:
        """
        Arma material de estudio a partir de un tema o de un texto dictado.
        mode: resumen | esquema | fichas | examen
        depth: corto | medio | detallado
        """
        return study_service.make_study_summary(material=material, mode=mode, depth=depth)

    def play_music(query: str, service: str = "spotify") -> str:
        """
        Abre Spotify o YouTube Music en el teléfono (fuera de Eliseo).
        query: canción, artista o estilo. service: spotify | youtube_music.
        """
        plan = music_service.play_music_plan(query, service=service)
        if not plan["ok"] or not plan.get("url"):
            return plan["message"]
        queue_client_action({"type": "stop_audio"})
        action: dict = {"type": "open_url", "url": plan["url"]}
        if plan.get("url_alt"):
            action["url_alt"] = plan["url_alt"]
        queue_client_action(action)
        return plan["message"]

    def stop_music() -> str:
        """
        Para lo que suene en Eliseo. Si la música está en Spotify/YouTube,
        no se puede pausar desde acá.
        """
        queue_client_action({"type": "stop_audio"})
        return (
            "Corté lo que sonaba en Eliseo. "
            "Si sigue Spotify o YouTube Music, pausalo en esa app."
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
            func=check_off_note,
            name="check_off_note",
            description="Tacha un ítem de compras/encargos. text=qué tachar; list_name default compras.",
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
                "Resumen del día: hora, clima, agenda, mails y tráfico opcional. "
                "work_destination opcional (ej. 'oficina'). "
                "Usar ante 'buenos días', 'resumen del día'."
            ),
        ),
        StructuredTool.from_function(
            func=get_today_overview,
            name="get_today_overview",
            description="Qué tengo hoy: clima + agenda + mails. work_destination opcional para tráfico.",
        ),
        StructuredTool.from_function(
            func=get_inbox_digest,
            name="get_inbox_digest",
            description="Resumen de qué me escribieron (mails sin leer + Chat). Usar ante 'qué me escribieron'.",
        ),
        StructuredTool.from_function(
            func=make_study_summary,
            name="make_study_summary",
            description=(
                "Arma resúmenes de estudio, esquemas, fichas o un mini examen. "
                "Pasá material=tema o texto dictado. "
                "mode=resumen|esquema|fichas|examen. depth=corto|medio|detallado. "
                "Usar ante 'haceme un resumen de estudio', 'explicame para rendir', "
                "'armame fichas', 'preguntame de este tema'."
            ),
        ),
        StructuredTool.from_function(
            func=play_music,
            name="play_music",
            description=(
                "Abre Spotify o YouTube Music en el teléfono para escuchar. "
                "query=canción, artista o estilo. service=spotify (default) o youtube_music. "
                "Usar ante 'poné música', 'poné rock', 'abrí Spotify'."
            ),
        ),
        StructuredTool.from_function(
            func=stop_music,
            name="stop_music",
            description=(
                "Intenta parar la música. Corta audio de Eliseo; "
                "si suena en Spotify/YouTube hay que pausar ahí. "
                "Usar ante 'pará la música', 'stop', 'pausá'."
            ),
        ),
        StructuredTool.from_function(
            func=set_wake_name,
            name="set_wake_name",
            description=(
                "Cambia el nombre con el que te llaman (wake word). "
                "Usar ante 'llamame Max', 'quiero llamarte Sofía'. La app sigue siendo Eliseo."
            ),
        ),
        StructuredTool.from_function(
            func=set_quiet_mode,
            name="set_quiet_mode",
            description="Modo silencio on/off. enabled=true solo responde si lo llaman por nombre.",
        ),
        StructuredTool.from_function(
            func=set_confirm_sends,
            name="set_confirm_sends",
            description="Pide 'dale' antes de mails/chats/pagos. enabled=true|false.",
        ),
        StructuredTool.from_function(
            func=start_meeting_mode,
            name="start_meeting_mode",
            description="Silencia avisos N minutos (default 60). Usar ante 'modo reunión'.",
        ),
        StructuredTool.from_function(
            func=stop_meeting_mode,
            name="stop_meeting_mode",
            description="Sale del modo reunión.",
        ),
        StructuredTool.from_function(
            func=mark_habit_done,
            name="mark_habit_done",
            description="Marca hábito de hoy: agua, pastilla, ejercicio…",
        ),
        StructuredTool.from_function(
            func=habit_status,
            name="habit_status",
            description="Consulta hábitos. name opcional.",
        ),
        StructuredTool.from_function(
            func=start_pomodoro,
            name="start_pomodoro",
            description="Temporizador Pomodoro. minutes default 25.",
        ),
        StructuredTool.from_function(
            func=start_breathing,
            name="start_breathing",
            description="Pausa de respiración guiada. minutes default 2.",
        ),
        StructuredTool.from_function(
            func=confirm_pending_action,
            name="confirm_pending_action",
            description="Confirma acción pendiente. Usar cuando el usuario dice 'dale', 'sí, mandalo'.",
        ),
        StructuredTool.from_function(
            func=cancel_pending_action,
            name="cancel_pending_action",
            description="Cancela la acción pendiente. Usar ante 'cancelá', 'no'.",
        ),
        StructuredTool.from_function(
            func=repeat_last,
            name="repeat_last",
            description="Repite la última respuesta. Usar ante 'repetí', 'qué dijiste'.",
        ),
        StructuredTool.from_function(
            func=speak_slower,
            name="speak_slower",
            description="Habla más despacio. Usar ante 'más despacio', 'hablá lento'.",
        ),
        StructuredTool.from_function(
            func=speak_normal,
            name="speak_normal",
            description="Vuelve a velocidad normal de voz.",
        ),
        StructuredTool.from_function(
            func=broadcast_message,
            name="broadcast_message",
            description=(
                "Manda el mismo texto a varios contactos. "
                "contacts=nombres/emails separados por coma; text=mensaje; "
                "channel=chat|email|telegram. Si confirm_sends está on, pide dale."
            ),
        ),
        StructuredTool.from_function(
            func=telegram_status,
            name="telegram_status",
            description="Dice si Telegram está conectado o qué falta (código / 2FA).",
        ),
        StructuredTool.from_function(
            func=connect_telegram,
            name="connect_telegram",
            description=(
                "Empieza login de Telegram con la cuenta personal. "
                "phone=número con código de país (+54911…). "
                "Usar cuando piden conectar Telegram."
            ),
        ),
        StructuredTool.from_function(
            func=confirm_telegram_code,
            name="confirm_telegram_code",
            description=(
                "Confirma el código numérico que Telegram mandó al teléfono. "
                "Usar cuando el usuario dicta el código."
            ),
        ),
        StructuredTool.from_function(
            func=confirm_telegram_password,
            name="confirm_telegram_password",
            description="Contraseña de verificación en dos pasos de Telegram, si la pide.",
        ),
        StructuredTool.from_function(
            func=disconnect_telegram,
            name="disconnect_telegram",
            description="Desconecta Telegram de Eliseo.",
        ),
        StructuredTool.from_function(
            func=list_telegram_chats,
            name="list_telegram_chats",
            description="Lista chats recientes de Telegram.",
        ),
        StructuredTool.from_function(
            func=get_telegram_messages,
            name="get_telegram_messages",
            description=(
                "Lee mensajes recientes de Telegram. contact=nombre del chat o @usuario."
            ),
        ),
        StructuredTool.from_function(
            func=send_telegram_message,
            name="send_telegram_message",
            description=(
                "Envía un mensaje por Telegram (cuenta personal). "
                "contact=nombre o @usuario; text=mensaje. "
                "NO usar send_chat_message (eso es Google Chat)."
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
                "Abre el flujo OAuth en el teléfono, o guía el login por voz de Telegram. "
                "service=google_calendar|mercadopago|teams_calendar|telegram."
            ),
        ),
    ]
