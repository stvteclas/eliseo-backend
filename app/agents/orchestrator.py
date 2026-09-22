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

from app.core.config import settings
from app.core.crypto import decrypt
from app.models.connector import UserConnector
from app.models.google_calendar_credential import GoogleCalendarCredential
from app.models.mercadopago_credential import MercadoPagoCredential
from app.models.teams_calendar_credential import TeamsCalendarCredential
from app.models.user import User
from app.services.weather import get_weather_report


SYSTEM_PROMPT_TEMPLATE = (
    "Sos {name}, un asistente de voz argentino, cálido y directo. "
    "Respondé corto, como si estuvieras hablando, no escribiendo un informe. "
    "Nunca uses emojis, emoticones ni sus nombres (nada de blush, smile, etc.): "
    "solo texto hablable. "
    "Solo podés usar las herramientas que tenés disponibles: si te piden algo "
    "para lo que no tenés una herramienta conectada, decilo en vez de inventar la respuesta."
)

PERSONA_DISPLAY_NAME = {
    "eliseo": "Eliseo",
    "elisse": "Elisse",
}


def system_prompt_for_persona(persona: str) -> str:
    name = PERSONA_DISPLAY_NAME.get(persona, PERSONA_DISPLAY_NAME["elisse"])
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


GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
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

    def get_upcoming_calendar_events() -> str:
        try:
            service = build("calendar", "v3", credentials=google_credentials, cache_discovery=False)
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=datetime.now(timezone.utc).isoformat(),
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception:
            return "No pude leer el calendario. Puede que la autorización haya vencido y haya que volver a conectarlo."

        events = result.get("items", [])
        if not events:
            return "No hay eventos próximos en el calendario."
        return "\n".join(
            f"{event['start'].get('dateTime', event['start'].get('date'))} — {event.get('summary', '(sin título)')}"
            for event in events
        )

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

    list_description = "Devuelve los próximos eventos del calendario de Google del usuario."
    create_description = (
        "Crea un recordatorio/evento en Google Calendar con notificación popup 10 minutos antes. "
        "Pasá title (texto), when en ISO (ej. 2026-09-23T10:00:00, hora Argentina si no hay zona) "
        "y opcionalmente duration_minutes (default 30)."
    )
    if account_label != "default":
        list_description = f"Devuelve los próximos eventos del calendario de Google de la cuenta '{account_label}'."
        create_description = (
            f"Crea un recordatorio en el calendario de Google de la cuenta '{account_label}' "
            "con aviso popup 10 minutos antes. when en ISO; duration_minutes opcional."
        )

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
            return result["response"]["init_point"]  # cuenta real del usuario: init_point, no sandbox_init_point
        if result.get("status") in (401, 403):
            return reconnect_message
        return "No pude crear el link de pago en este momento."

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


def build_builtin_tools(latitude: float | None = None, longitude: float | None = None) -> list:
    """
    Herramientas siempre disponibles (hora y clima), sin conector.
    Si el request trae GPS, get_weather puede usarlo cuando no pasan ciudad.
    """

    def get_current_datetime() -> str:
        # Hora de Argentina (UTC-3 fijo; suficiente para respuestas habladas).
        now = datetime.now(timezone(timedelta(hours=-3)))
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

    def get_weather(city: str = "") -> str:
        """
        Clima actual. Pasá una ciudad (ej. 'Buenos Aires') o dejá vacío para
        usar la ubicación GPS del usuario si la app la mandó.
        """
        city_arg = city.strip() or None
        return get_weather_report(city=city_arg, latitude=latitude, longitude=longitude)

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
    ]


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

    tools = build_builtin_tools(latitude=latitude, longitude=longitude)
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
    latitude: float | None = None,
    longitude: float | None = None,
):
    tools = await get_tools_for_user(user_id, db, latitude=latitude, longitude=longitude)

    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
    )

    return create_react_agent(model, tools, prompt=system_prompt_for_persona(persona))


async def handle_user_message(
    message: str,
    user_id: int,
    db: Session,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    """Responde un mensaje usando herramientas built-in y las que el usuario conectó."""
    if not settings.anthropic_api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en la configuración.")

    user = db.query(User).filter(User.id == user_id).first()
    persona = user.persona if user is not None else "elisse"

    agent = await _build_agent(
        user_id, db, persona=persona, latitude=latitude, longitude=longitude
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})

    last_message = result["messages"][-1]
    return last_message.content
