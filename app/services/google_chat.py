"""Google Chat: leer y mandar mensajes con un contacto (DM)."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

CHAT_SCOPES = (
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
)


def _chat_service(credentials: Credentials):
    return build("chat", "v1", credentials=credentials, cache_discovery=False)


def _normalize_email(value: str) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    # "Ana <ana@x.com>" → ana@x.com
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    if match:
        return match.group(0)
    if "@" in raw:
        return raw
    return None


def _user_name(email: str) -> str:
    return f"users/{email}"


def _format_when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        # 2026-09-23T15:00:00.123Z or with offset
        text = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return iso[:16]


def _sender_label(message: dict) -> str:
    sender = message.get("sender") or {}
    name = (sender.get("displayName") or "").strip()
    if name:
        return name
    resource = (sender.get("name") or "").strip()
    if resource.startswith("users/"):
        return resource.split("/", 1)[1]
    return "alguien"


def find_direct_message_space(credentials: Credentials, contact: str) -> tuple[str | None, str]:
    """
    Devuelve (space_name, error_o_ok).
    Busca el DM; si no existe, intenta crearlo.
    """
    email = _normalize_email(contact)
    if not email:
        return None, "Necesito el email del contacto (ej. ana@gmail.com)."

    service = _chat_service(credentials)
    try:
        space = service.spaces().findDirectMessage(name=_user_name(email)).execute()
        name = space.get("name")
        if name:
            return name, ""
    except HttpError as exc:
        if getattr(exc, "resp", None) is None or exc.resp.status != 404:
            logger.exception("Chat findDirectMessage falló")
            return None, _chat_error_message(exc)
    except Exception:
        logger.exception("Chat findDirectMessage falló")
        return None, "No pude abrir el chat con ese contacto. ¿Tenés Google Chat API y permiso reconectado?"

    # No hay DM todavía: crear uno.
    try:
        created = (
            service.spaces()
            .setup(
                body={
                    "space": {"spaceType": "DIRECT_MESSAGE"},
                    "memberships": [
                        {
                            "member": {
                                "name": _user_name(email),
                                "type": "HUMAN",
                            }
                        }
                    ],
                }
            )
            .execute()
        )
        space = created.get("space") or created
        name = space.get("name")
        if name:
            return name, ""
        return None, "Google Chat no devolvió el espacio del mensaje directo."
    except HttpError as exc:
        logger.exception("Chat spaces.setup falló")
        return None, _chat_error_message(exc)
    except Exception:
        logger.exception("Chat spaces.setup falló")
        return None, (
            "No pude crear el chat con ese contacto. "
            "En Google Chat, abrí un mensaje directo con esa persona una vez y reintentá."
        )


def _chat_error_message(exc: HttpError) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in {401, 403}:
        return (
            "Falta permiso de Google Chat. Habilitá Chat API en Cloud, "
            "reconectá Google Calendar aceptando Chat, y asegurate de que el contacto use Google Chat."
        )
    if status == 404:
        return "No encontré un chat con ese contacto."
    return "No pude usar Google Chat ahora. Probá de nuevo en un rato."


def list_chat_messages(
    credentials: Credentials,
    contact: str,
    limit: int = 8,
) -> str:
    """Lee mensajes recientes del DM con contact (email)."""
    space_name, err = find_direct_message_space(credentials, contact)
    if err or not space_name:
        return err or "No encontré el chat."

    max_n = max(1, min(int(limit or 8), 15))
    try:
        service = _chat_service(credentials)
        listed = (
            service.spaces()
            .messages()
            .list(parent=space_name, pageSize=max_n, orderBy="createTime desc")
            .execute()
        )
    except HttpError as exc:
        logger.exception("Chat messages.list falló")
        return _chat_error_message(exc)
    except Exception:
        logger.exception("Chat messages.list falló")
        return "No pude leer los mensajes de Chat."

    messages = listed.get("messages") or []
    if not messages:
        email = _normalize_email(contact) or contact
        return f"Todavía no hay mensajes con {email}."

    # API puede devolver desc; para hablar, del más viejo al más nuevo en el lote.
    messages = list(reversed(messages))
    lines: list[str] = []
    for msg in messages:
        text = (msg.get("text") or "").strip()
        if not text:
            text = "(mensaje sin texto)"
        text = re.sub(r"\s+", " ", text)[:220]
        who = _sender_label(msg)
        when = _format_when(msg.get("createTime"))
        when_bit = f" ({when})" if when else ""
        lines.append(f"{who}{when_bit}: {text}")

    email = _normalize_email(contact) or contact
    return f"Chat con {email}: " + " | ".join(lines)


def send_chat_message(
    credentials: Credentials,
    contact: str,
    text: str,
) -> str:
    """Envía un mensaje de texto al DM con contact."""
    body = (text or "").strip()
    if not body:
        return "Decime qué querés mandarle."
    body = body[:3500]

    space_name, err = find_direct_message_space(credentials, contact)
    if err or not space_name:
        return err or "No encontré el chat."

    try:
        service = _chat_service(credentials)
        service.spaces().messages().create(
            parent=space_name,
            body={"text": body},
        ).execute()
    except HttpError as exc:
        logger.exception("Chat messages.create falló")
        return _chat_error_message(exc)
    except Exception:
        logger.exception("Chat messages.create falló")
        return "No pude enviar el mensaje de Chat."

    email = _normalize_email(contact) or contact
    preview = body if len(body) <= 80 else body[:77] + "…"
    return f"Listo, le mandé por Google Chat a {email}: «{preview}»."
