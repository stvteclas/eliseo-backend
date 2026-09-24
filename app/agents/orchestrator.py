"""
Motor de orquestación de Eliseo (HU-T03).

Arma un agente de LangGraph (ReAct) sobre Claude, con herramientas
cargadas desde servidores MCP. Solo carga las de los servicios que el
usuario autorizó (manifiesto, HU-T04, tabla user_connectors de HU-T15);
un usuario sin servicios autorizados conversa con el agente sin
herramientas.

Transporte: streamable-http, no stdio. stdio arranca un proceso hijo,
que no sirve en una función serverless como Vercel; con HTTP el servidor
MCP corre como su propio servicio y acá solo se configura su URL
(settings.mcp_sandbox_url).
"""

from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

import math
import re
from datetime import datetime, timedelta, timezone

import httpx
import mercadopago
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.api.routes.google_calendar import GOOGLE_CALENDAR_SCOPES
from app.core.config import settings
from app.core.crypto import decrypt
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.mercadopago_credential import MercadoPagoCredential
from app.models.teams_calendar_credential import TeamsCalendarCredential
from app.models.user import User
from app.agents.builtin_tools import build_builtin_tools  # noqa: F401 — reexport / uso en get_tools
from app.agents.client_actions import drain_client_actions, reset_client_actions
from app.services import gmail as gmail_service
from app.services import google_chat as google_chat_service


SYSTEM_PROMPT_TEMPLATE = (
    "Sos {name}, un asistente de voz argentino, cálido y directo. "
    "Respondé corto, como si estuvieras hablando, no escribiendo un informe. "
    "Nunca uses emojis, emoticones ni sus nombres (nada de blush, smile, etc.): "
    "solo texto hablable. "
    "Las herramientas son para datos o acciones externas "
    "(clima, hora, calendario, mails, Google Chat, pagos, notas, compras, hábitos, "
    "cálculos, tráfico, viaje, noticias, traducción, modo traductor, temporizador, "
    "pomodoro, respiración, avisos, contactos, resumen del día, bandeja, estudio, "
    "música, nombre con el que te llaman, modo silencio, confirmación dale, "
    "modo reunión, repetir, hablar despacio, Telegram, conexiones de servicios). "
    "Si preguntan por tráfico, demora, cuánto tardan o cómo está el camino "
    "hacia un lugar, usá get_travel_time (con GPS si no dan origen). "
    "Si piden estudiar, resumir para un examen, fichas o que los pregunte "
    "sobre un tema o un texto, usá make_study_summary. "
    "Si piden poner música, usá play_music (abre Spotify o YouTube Music en el teléfono). "
    "Si piden parar la música, usá stop_music. "
    "Si piden llamarme de otra forma, usá set_wake_name. "
    "Si dicen dale/confirmá y hay algo pendiente, usá confirm_pending_action. "
    "Si cancelan, usá cancel_pending_action. "
    "Si piden 'qué me escribieron', usá get_inbox_digest. "
    "Si piden 'qué tengo hoy' o buenos días, usá get_today_overview o get_daily_briefing. "
    "Para lista de compras usá add_note/list_notes/check_off_note con list_name=compras. "
    "Si piden leer el correo, mails o bandeja de entrada, usá get_recent_emails "
    "o read_email; si piden mandar un mail, usá send_email "
    "(hace falta haber reconectado Google con permiso de Gmail). "
    "Si piden leer o mandar un Google Chat / Chat a alguien, usá "
    "get_chat_messages o send_chat_message con el nombre O el email del contacto "
    "(se resuelve con Google Contacts y tus chats). "
    "Si no sabés el mail, alcanza con el nombre; si hay varios, preguntá cuál. "
    "Para listar con quién puede chatear, usá list_chat_contacts. "
    "(Hace falta Chat API + People API y haber reconectado Google.) "
    "Google Chat NO es Gmail: no uses send_email para un Chat. "
    "Google Chat NO es Telegram: para Telegram usá connect_telegram / "
    "confirm_telegram_code / get_telegram_messages / send_telegram_message. "
    "Si piden conectar Telegram, pedí el número con código de país y usá "
    "connect_telegram; cuando dicten el código, confirm_telegram_code; "
    "si pide contraseña de dos pasos, confirm_telegram_password. "
    "Si en un turno anterior ya dio el contacto y ahora solo "
    "dice el texto del mensaje, usá ese mismo contacto y llamá send_chat_message "
    "ya: no vuelvas a pedir el mail. "
    "Si en el mismo mensaje trae contacto y texto, llamá la tool de una. "
    "Si el usuario aún no conectó Google Calendar u otro servicio, "
    "usá get_onboarding_status y start_service_connection para guiarlo paso a paso. "
    "Calendar es obligatorio antes de hablar de agenda o recordatorios. "
    "Si te piden que hagas de traductor entre dos idiomas "
    "(ej. español y ruso), usá start_translator_mode. "
    "Para charlar, explicar, inventar, contar un cuento, chistes, trivia o "
    "adivinanzas, respondé vos mismo sin herramientas. "
    "Si te piden un dato externo y no tenés la herramienta, decilo en vez de inventar el dato."
)

PERSONA_DISPLAY_NAME = {
    "eliseo": "Eliseo",
    "elisse": "Elisse",
}


def system_prompt_for_persona(persona: str, display_name: str | None = None) -> str:
    name = (display_name or "").strip() or PERSONA_DISPLAY_NAME.get(
        persona, PERSONA_DISPLAY_NAME["elisse"]
    )
    return SYSTEM_PROMPT_TEMPLATE.format(name=name)


# service_name -> config de MultiServerMCPClient. Hoy solo "sandbox"; en
# HU-T11 (calendario) y HU-T20 (Mercado Pago) se agregan entradas nuevas,
# sin tocar get_tools_for_user. Un conector cuyo service_name no esté acá
# (ej. "whatsapp") se ignora: todavía no tiene herramientas MCP detrás.
SERVICE_MCP_REGISTRY: dict[str, dict] = {
    "sandbox": {"url": settings.mcp_sandbox_url, "transport": "streamable_http"},
}


class ToolServerUnavailable(Exception):
    """El servidor MCP no responde (caído o URL mal configurada)."""


def _account_suffix(account_label: str) -> str:
    """
    Sufijo de nombre de herramienta para una cuenta no-default (HU-T21):
    "Banco 1" -> "_banco_1". Vacío para "default", así el nombre de la
    herramienta de la única cuenta de un servicio no cambia (T11/T20 siguen
    viéndose igual que antes).
    """
    if account_label == "default":
        return ""
    slug = re.sub(r"[^a-z0-9]+", "_", account_label.lower()).strip("_")
    return f"_{slug}" if slug else ""


ARGENTINA_TZ = timezone(timedelta(hours=-3))


def _parse_event_start(when: str) -> datetime | None:
    """Acepta ISO (con o sin zona). Sin zona se asume hora de Argentina."""
    text = (when or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        start = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=ARGENTINA_TZ)
    return start


def build_calendar_tools(user_id: int, db: Session, account_label: str = "default") -> list:
    """
    Tools de Google Calendar de UNA cuenta (leer próximos + crear recordatorio).
    Lista vacía si esa cuenta no está conectada.
    """
    credential = (
        db.query(GoogleCalendarCredential)
        .filter(GoogleCalendarCredential.user_id == user_id, GoogleCalendarCredential.account_label == account_label)
        .first()
    )
    if credential is None:
        return []

    google_credentials = Credentials(
        token=None,
        refresh_token=decrypt(credential.refresh_token_encrypted),
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GOOGLE_CALENDAR_SCOPES,
    )
    suffix = _account_suffix(account_label)
    account_note = "" if account_label == "default" else f" de la cuenta '{account_label}'"

    def _list_calendars(service) -> list[tuple[str, str, bool]]:
        """(calendar_id, nombre, es_primario) de todos los calendarios de la cuenta, con paginación."""
        calendars = []
        page_token = None
        while True:
            page = service.calendarList().list(pageToken=page_token).execute()
            for item in page.get("items", []):
                calendars.append((item["id"], item.get("summary", item["id"]), bool(item.get("primary"))))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return calendars

    def get_upcoming_calendar_events() -> str:
        try:
            service = build("calendar", "v3", credentials=google_credentials, cache_discovery=False)
            calendars = _list_calendars(service)
        except Exception:
            return "No pude leer el calendario. Puede que la autorización haya vencido y haya que volver a conectarlo."

        if not calendars:
            calendars = [("primary", "primary", True)]

        time_min = datetime.now(timezone.utc).isoformat()
        found = []
        for calendar_id, calendar_name, is_primary in calendars:
            try:
                result = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        maxResults=10,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
            except Exception:
                continue  # un calendario puntual con permisos raros no debería tirar abajo el resto
            for event in result.get("items", []):
                found.append((event, calendar_name, is_primary))

        if not found:
            return "No hay eventos próximos en ningún calendario."

        found.sort(key=lambda f: f[0]["start"].get("dateTime", f[0]["start"].get("date", "")))

        lines = []
        for event, calendar_name, is_primary in found[:10]:
            when = event["start"].get("dateTime", event["start"].get("date"))
            title = event.get("summary", "(sin título)")
            calendar_note = "" if is_primary else f" [{calendar_name}]"
            lines.append(f"{when} — {title}{calendar_note}")
        return "\n".join(lines)

    def create_calendar_reminder(title: str, when: str, duration_minutes: float = 30) -> str:
        """
        Crea un evento/recordatorio en Google Calendar con aviso popup 10 min antes.
        `when` en ISO (ej. 2026-09-23T10:00:00) en hora Argentina si no trae zona.
        """
        start = _parse_event_start(when)
        if start is None:
            return "No entendí la fecha/hora. Pasá `when` en ISO, por ejemplo 2026-09-23T10:00:00."
        if not title or not title.strip():
            return "El recordatorio necesita un título."
        try:
            minutes = int(duration_minutes)
        except (TypeError, ValueError):
            minutes = 30
        if minutes <= 0:
            minutes = 30
        end = start + timedelta(minutes=minutes)

        body = {
            "summary": title.strip(),
            "start": {"dateTime": start.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 10}],
            },
        }
        try:
            service = build("calendar", "v3", credentials=google_credentials, cache_discovery=False)
            created = service.events().insert(calendarId="primary", body=body).execute()
        except Exception:
            return (
                f"No pude crear el recordatorio{account_note}. "
                "Puede que falte permiso de escritura: hay que volver a conectar Google Calendar."
            )

        link = created.get("htmlLink") or ""
        when_label = start.astimezone(ARGENTINA_TZ).strftime("%d/%m/%Y %H:%M")
        msg = f"Listo: recordatorio '{title.strip()}' el {when_label} (aviso 10 min antes)."
        if link:
            msg += f" {link}"
        return msg

    def get_recent_emails(limit: float = 5, query: str = "") -> str:
        """
        Lee mails recientes de Gmail. query opcional (sintaxis Gmail:
        'is:unread', 'from:ana', 'newer_than:2d'). Default: bandeja de entrada.
        """
        return gmail_service.list_recent_emails(
            google_credentials,
            limit=int(limit or 5),
            query=query or "",
        )

    def read_email(search: str = "", message_id: str = "") -> str:
        """
        Lee el contenido de un mail. Pasá search (ej. 'from:banco is:unread')
        o message_id si lo conocés.
        """
        return gmail_service.read_email(
            google_credentials,
            message_id=message_id or "",
            search=search or "",
        )

    def send_email(to: str, subject: str, body: str) -> str:
        """
        Envía un mail. to=email del destinatario, subject=asunto, body=texto.
        """
        def _send() -> str:
            return gmail_service.send_email(
                google_credentials,
                to=to,
                subject=subject,
                body=body,
            )

        from app.models.user import User
        from app.services import pending_confirm

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.confirm_sends:
            pending_confirm.set_pending(
                user_id,
                f"mandar mail a {to} con asunto {subject}",
                _send,
            )
            return f"¿Mando el mail a {to}? Decí dale para confirmar o cancelá."
        return _send()

    def get_chat_messages(contact: str, limit: float = 8) -> str:
        """
        Lee mensajes recientes de Google Chat con un contacto (nombre o email).
        """
        return google_chat_service.list_chat_messages(
            google_credentials,
            contact=contact,
            limit=int(limit or 8),
        )

    def send_chat_message(contact: str, text: str) -> str:
        """
        Envía un mensaje de Google Chat. contact=nombre o email; text=mensaje.
        """
        def _send() -> str:
            return google_chat_service.send_chat_message(
                google_credentials,
                contact=contact,
                text=text,
            )

        from app.models.user import User
        from app.services import pending_confirm

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.confirm_sends:
            preview = (text or "")[:60]
            pending_confirm.set_pending(
                user_id,
                f"mandar Chat a {contact}: {preview}",
                _send,
            )
            return f"¿Le mando a {contact} por Chat? Decí dale para confirmar o cancelá."
        return _send()

    def list_chat_contacts(limit: float = 15) -> str:
        """Lista contactos con los que ya hay Google Chat (DM)."""
        return google_chat_service.list_chat_contacts(
            google_credentials,
            limit=int(limit or 15),
        )

    list_description = "Devuelve los próximos eventos de TODOS los calendarios de Google del usuario (no solo el principal)."
    create_description = (
        "Crea un recordatorio/evento en Google Calendar con notificación popup 10 minutos antes. "
        "Pasá title (texto), when en ISO (ej. 2026-09-23T10:00:00, hora Argentina si no hay zona) "
        "y opcionalmente duration_minutes (default 30)."
    )
    mail_list_description = (
        "Lee mails recientes de Gmail (asunto, de quién, adelanto). "
        "Usar ante 'leé mis mails', 'qué hay en el correo', 'mails sin leer'. "
        "query opcional con sintaxis Gmail; limit default 5."
    )
    mail_read_description = (
        "Lee el contenido de un mail concreto. Pasá search (ej. from:ana asunto) "
        "o message_id. Usar cuando piden 'leé el mail de…' o el detalle de uno."
    )
    mail_send_description = (
        "Envía un mail desde Gmail del usuario. to=dirección, subject=asunto, body=mensaje. "
        "Usar ante 'mandale un mail a…', 'escribile un correo a…'."
    )
    chat_list_description = (
        "Lee mensajes recientes de Google Chat. "
        "contact=nombre de Google Contacts/Chat O email. "
        "NO es Gmail. Usar ante 'qué me escribió Ana en Chat'."
    )
    chat_send_description = (
        "Envía un mensaje por Google Chat (NO Gmail). "
        "contact=nombre O email; text=mensaje. "
        "Preferí el nombre si el usuario no dicta el mail "
        "(se busca en Google Contacts y en DMs de Chat). "
        "Ejemplo: contact='Ana', text='Llego en 10'."
    )
    chat_contacts_description = (
        "Lista con quién ya tenés Google Chat (mensajes directos). "
        "Usar ante 'quiénes son mis contactos de Chat', 'a quién puedo escribir'."
    )
    if account_label != "default":
        list_description = (
            f"Devuelve los próximos eventos de todos los calendarios de Google de la cuenta '{account_label}'."
        )
        create_description = (
            f"Crea un recordatorio en el calendario de Google de la cuenta '{account_label}' "
            "con aviso popup 10 minutos antes. when en ISO; duration_minutes opcional."
        )
        mail_list_description = f"Lee mails recientes de Gmail de la cuenta '{account_label}'."
        mail_read_description = f"Lee un mail de Gmail de la cuenta '{account_label}'."
        mail_send_description = f"Envía un mail desde Gmail de la cuenta '{account_label}'."
        chat_list_description = f"Lee Google Chat de la cuenta '{account_label}' (nombre o email)."
        chat_send_description = f"Envía Google Chat desde la cuenta '{account_label}' (nombre o email)."
        chat_contacts_description = f"Lista contactos de Google Chat de la cuenta '{account_label}'."

    return [
        StructuredTool.from_function(
            func=get_upcoming_calendar_events,
            name=f"get_upcoming_calendar_events{suffix}",
            description=list_description,
        ),
        StructuredTool.from_function(
            func=create_calendar_reminder,
            name=f"create_calendar_reminder{suffix}",
            description=create_description,
        ),
        StructuredTool.from_function(
            func=get_recent_emails,
            name=f"get_recent_emails{suffix}",
            description=mail_list_description,
        ),
        StructuredTool.from_function(
            func=read_email,
            name=f"read_email{suffix}",
            description=mail_read_description,
        ),
        StructuredTool.from_function(
            func=send_email,
            name=f"send_email{suffix}",
            description=mail_send_description,
        ),
        StructuredTool.from_function(
            func=get_chat_messages,
            name=f"get_chat_messages{suffix}",
            description=chat_list_description,
        ),
        StructuredTool.from_function(
            func=send_chat_message,
            name=f"send_chat_message{suffix}",
            description=chat_send_description,
        ),
        StructuredTool.from_function(
            func=list_chat_contacts,
            name=f"list_chat_contacts{suffix}",
            description=chat_contacts_description,
        ),
    ]


def build_calendar_tool(user_id: int, db: Session, account_label: str = "default"):
    """Compat: devuelve la tool de listar, o None si no hay cuenta."""
    tools = build_calendar_tools(user_id, db, account_label)
    return tools[0] if tools else None


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:  # SQLite devuelve las fechas sin zona; se guardan en UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires_at


def build_mercadopago_tool(user_id: int, db: Session, account_label: str = "default"):
    """
    Herramienta de Mercado Pago de UNA cuenta puntual del usuario, armada con
    SU access token (HU-T20; varias cuentas por usuario desde HU-T21): los
    links de pago cobran a favor de esa cuenta. Devuelve None si esa cuenta
    no está conectada.

    Pendiente a propósito: los access tokens de MP expiran (expires_at). Por
    ahora, si venció, la herramienta pide reconectar; renovarlo solo con el
    refresh_token guardado es una mejora para más adelante.
    """
    credential = (
        db.query(MercadoPagoCredential)
        .filter(MercadoPagoCredential.user_id == user_id, MercadoPagoCredential.account_label == account_label)
        .first()
    )
    if credential is None:
        return None

    access_token = decrypt(credential.access_token_encrypted)
    expires_at = credential.expires_at
    account_note = "" if account_label == "default" else f" de la cuenta '{account_label}'"
    reconnect_message = (
        f"La conexión con Mercado Pago{account_note} venció. Hay que volver a conectarla para crear links de pago."
    )

    def create_payment_link(title: str, amount: float, description: str) -> str:
        if _is_expired(expires_at):
            return reconnect_message
        if not math.isfinite(amount) or amount <= 0:
            return "El monto del link de pago tiene que ser mayor a cero."

        def _create() -> str:
            try:
                result = (
                    mercadopago.SDK(access_token)
                    .preference()
                    .create(
                        {
                            "items": [
                                {
                                    "title": title,
                                    "description": description,
                                    "quantity": 1,
                                    "currency_id": "ARS",
                                    "unit_price": amount,
                                }
                            ]
                        }
                    )
                )
            except Exception:
                return "No pude crear el link de pago en este momento."

            if result.get("status") in (200, 201):
                return result["response"]["init_point"]
            if result.get("status") in (401, 403):
                return reconnect_message
            return "No pude crear el link de pago en este momento."

        from app.models.user import User
        from app.services import pending_confirm

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.confirm_sends:
            pending_confirm.set_pending(
                user_id,
                f"crear link de pago de {amount} por {title}",
                _create,
            )
            return f"¿Creo el link de pago de {amount} por {title}? Decí dale o cancelá."
        return _create()

    description = f"Crea un link de pago de Mercado Pago (en pesos) que cobra a favor{account_note or ' del usuario'} y devuelve la URL."

    return StructuredTool.from_function(
        func=create_payment_link,
        name=f"create_payment_link{_account_suffix(account_label)}",
        description=description,
    )


def build_teams_calendar_tool(user_id: int, db: Session, account_label: str = "default"):
    """
    Herramienta de Microsoft Teams/Outlook Calendar de UNA cuenta puntual del
    usuario (HU-T22, multi-cuenta desde el vamos). Devuelve None si esa
    cuenta no está conectada.

    Sin SDK (msal): llama a Microsoft Graph directo con httpx. Igual que
    Mercado Pago, si el token venció, la tool pide reconectar esa cuenta en
    vez de refrescarlo sola — el refresh automático con refresh_token queda
    para más adelante (no bloquea esta tarea).
    """
    credential = (
        db.query(TeamsCalendarCredential)
        .filter(TeamsCalendarCredential.user_id == user_id, TeamsCalendarCredential.account_label == account_label)
        .first()
    )
    if credential is None:
        return None

    access_token = decrypt(credential.access_token_encrypted)
    expires_at = credential.expires_at
    account_note = "" if account_label == "default" else f" de la cuenta '{account_label}'"
    reconnect_message = f"La conexión con el calendario de Teams{account_note} venció. Hay que volver a conectarla."

    def get_teams_calendar_events() -> str:
        if _is_expired(expires_at):
            return reconnect_message

        now = datetime.now(timezone.utc)
        try:
            response = httpx.get(
                "https://graph.microsoft.com/v1.0/me/calendarview",
                params={
                    "startDateTime": now.isoformat(),
                    "endDateTime": (now + timedelta(days=7)).isoformat(),
                    "$orderby": "start/dateTime",
                },
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
        except Exception:
            return "No pude leer el calendario de Teams en este momento."

        if response.status_code in (401, 403):
            return reconnect_message
        if response.status_code != 200:
            return "No pude leer el calendario de Teams en este momento."

        events = response.json().get("value", [])
        if not events:
            return "No hay eventos próximos en ese calendario de Teams."
        return "\n".join(
            f"{event['start']['dateTime']} — {event.get('subject', '(sin título)')}" for event in events
        )

    description = "Devuelve los próximos eventos del calendario de Microsoft Teams/Outlook del usuario."
    if account_label != "default":
        description = f"Devuelve los próximos eventos del calendario de Teams de la cuenta '{account_label}'."

    return StructuredTool.from_function(
        func=get_teams_calendar_events,
        name=f"get_teams_calendar_events{_account_suffix(account_label)}",
        description=description,
    )


# service_name -> función que arma la tool de esa cuenta (HU-T21: multi-cuenta).
# get_tools_for_user itera todas las filas de UserConnector, no una por
# servicio: un usuario con 3 conectores "teams_calendar" (HU-T22) termina
# con 3 tools distintas, una por cuenta.
ACCOUNT_TOOL_BUILDERS = {
    "google_calendar": build_calendar_tools,
    "mercadopago": build_mercadopago_tool,
    "teams_calendar": build_teams_calendar_tool,
}


async def get_tools_for_user(
    user_id: int,
    db: Session,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list:
    """Herramientas built-in + las de los servicios que el usuario conectó."""
    connectors = db.query(UserConnector).filter(UserConnector.user_id == user_id).all()

    # Los servidores MCP (ej. "sandbox") no son por cuenta: alcanza con saber
    # qué service_names están conectados, sin importar cuántas filas haya.
    service_names = {c.service_name for c in connectors}
    servers = {name: SERVICE_MCP_REGISTRY[name] for name in service_names if name in SERVICE_MCP_REGISTRY}

    tools = build_builtin_tools(
        user_id=user_id,
        db=db,
        latitude=latitude,
        longitude=longitude,
    )
    if servers:
        client = MultiServerMCPClient(servers)
        try:
            tools = tools + await client.get_tools()
        except Exception as exc:  # los errores de conexión llegan como ExceptionGroup
            raise ToolServerUnavailable(", ".join(servers)) from exc

    for connector in connectors:
        build_tool = ACCOUNT_TOOL_BUILDERS.get(connector.service_name)
        if build_tool is None:
            continue
        account_tool = build_tool(user_id, db, connector.account_label)
        if account_tool is None:
            continue
        if isinstance(account_tool, list):
            tools.extend(account_tool)
        else:
            tools.append(account_tool)

    return tools


async def _build_agent(
    user_id: int,
    db: Session,
    persona: str = "elisse",
    display_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
):
    tools = await get_tools_for_user(user_id, db, latitude=latitude, longitude=longitude)

    model = ChatAnthropic(
        # Haiku: mucho más rápido para charla por voz (sonnet ~10–20s extra).
        model="claude-haiku-4-5",
        api_key=settings.anthropic_api_key,
    )

    return create_react_agent(
        model, tools, prompt=system_prompt_for_persona(persona, display_name=display_name)
    )


async def handle_user_message(
    message: str,
    user_id: int,
    db: Session,
    latitude: float | None = None,
    longitude: float | None = None,
    source_language: str | None = None,
    history: list[dict] | None = None,
) -> tuple[str, list, str | None]:
    """
    Responde un mensaje usando herramientas built-in y las que el usuario conectó.
    Devuelve (texto_hablado, acciones_para_la_app, idioma_tts_opcional).
    `history` son turnos previos {role, content} para multi-turno por voz.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en la configuración.")

    from app.services import conversation_memory as memory
    from app.services import translate as translate_service

    user = db.query(User).filter(User.id == user_id).first()
    persona = user.persona if user is not None else "elisse"
    from app.services import prefs as prefs_service

    display_name = prefs_service.display_name_for(user, persona)

    reset_client_actions()

    # Modo traductor activo: traduce al otro idioma sin pasar por el agente,
    # salvo que pidan salir.
    if (
        user is not None
        and user.translator_lang_a
        and user.translator_lang_b
    ):
        if translate_service.is_translator_exit(message):
            user.translator_lang_a = None
            user.translator_lang_b = None
            db.add(user)
            db.commit()
            return "Listo, salí del modo traductor.", [], "es"

        translated, speak_lang = translate_service.translate_bidirectional(
            message,
            user.translator_lang_a,
            user.translator_lang_b,
            source_hint=source_language,
        )
        memory.remember_turn(user_id, message, translated)
        return translated, [], speak_lang

    agent = await _build_agent(
        user_id,
        db,
        persona=persona,
        display_name=display_name,
        latitude=latitude,
        longitude=longitude,
    )
    prior = memory.merge_history(user_id, history)
    agent_messages = memory.build_agent_messages(prior, message)
    result = await agent.ainvoke({"messages": agent_messages})

    last_message = result["messages"][-1]
    reply = last_message.content
    if isinstance(reply, list):
        parts = []
        for block in reply:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
        reply = " ".join(p for p in parts if p).strip()
    else:
        reply = str(reply or "").strip()

    memory.remember_turn(user_id, message, reply)
    return reply, drain_client_actions(), None
