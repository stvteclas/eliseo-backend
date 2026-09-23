"""Lectura de Gmail (resúmenes hablables) vía API oficial."""

from __future__ import annotations

import base64
import logging
import re
from email.utils import parsedate_to_datetime
from html import unescape

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _header_map(payload: dict) -> dict[str, str]:
    headers = payload.get("headers") or []
    return {h.get("name", "").lower(): h.get("value", "") for h in headers if h.get("name")}


def _decode_body_data(data: str) -> str:
    raw = data.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_plain_body(payload: dict) -> str:
    """Saca texto plano del payload MIME (recursivo)."""
    if not payload:
        return ""
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        return _decode_body_data(data)
    if data and mime.startswith("text/html"):
        return _strip_html(_decode_body_data(data))

    parts = payload.get("parts") or []
    plain_bits: list[str] = []
    html_bits: list[str] = []
    for part in parts:
        part_mime = (part.get("mimeType") or "").lower()
        extracted = _extract_plain_body(part)
        if not extracted:
            continue
        if part_mime.startswith("text/plain"):
            plain_bits.append(extracted)
        elif part_mime.startswith("text/html"):
            html_bits.append(extracted)
        else:
            plain_bits.append(extracted)
    if plain_bits:
        return " ".join(plain_bits)
    if html_bits:
        return " ".join(html_bits)
    return ""


def _format_when(date_header: str) -> str:
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return date_header[:32]


def _gmail_service(credentials: Credentials):
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_recent_emails(
    credentials: Credentials,
    limit: int = 5,
    query: str = "",
) -> str:
    """
    Lista correos recientes. query usa sintaxis Gmail (ej. 'is:unread', 'from:ana').
    Por defecto: bandeja de entrada.
    """
    max_n = max(1, min(int(limit or 5), 10))
    q = (query or "").strip() or "in:inbox"
    try:
        service = _gmail_service(credentials)
        listed = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_n, q=q)
            .execute()
        )
    except Exception:
        logger.exception("Gmail list falló")
        return (
            "No pude leer el correo. Puede faltar permiso de Gmail: "
            "reconectá Google Calendar (ahora pide acceso al mail) "
            "y asegurate de tener Gmail API habilitada en Google Cloud."
        )

    messages = listed.get("messages") or []
    if not messages:
        return f"No encontré mails con «{q}»."

    lines: list[str] = []
    for index, item in enumerate(messages, start=1):
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
        except Exception:
            continue
        headers = _header_map(msg.get("payload") or {})
        subject = headers.get("subject") or "(sin asunto)"
        sender = headers.get("from") or "(desconocido)"
        when = _format_when(headers.get("date", ""))
        snippet = _strip_html(msg.get("snippet") or "")[:160]
        prefix = f"{index}. "
        when_bit = f" ({when})" if when else ""
        lines.append(f"{prefix}De {sender}{when_bit}: {subject}. {snippet}".strip())

    if not lines:
        return "No pude leer el detalle de los mails."
    return "Tus mails recientes: " + " ".join(lines)


def read_email(
    credentials: Credentials,
    message_id: str = "",
    search: str = "",
) -> str:
    """
    Lee un mail completo (texto corto). Pasá message_id o search (toma el primero).
    """
    mid = (message_id or "").strip()
    try:
        service = _gmail_service(credentials)
        if not mid:
            q = (search or "").strip() or "in:inbox"
            listed = (
                service.users()
                .messages()
                .list(userId="me", maxResults=1, q=q)
                .execute()
            )
            messages = listed.get("messages") or []
            if not messages:
                return f"No encontré un mail con «{q}»."
            mid = messages[0]["id"]

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=mid, format="full")
            .execute()
        )
    except Exception:
        logger.exception("Gmail get falló")
        return "No pude abrir ese mail. Probá reconectar Google con permiso de Gmail."

    headers = _header_map(msg.get("payload") or {})
    subject = headers.get("subject") or "(sin asunto)"
    sender = headers.get("from") or "(desconocido)"
    when = _format_when(headers.get("date", ""))
    body = _extract_plain_body(msg.get("payload") or {})
    if not body:
        body = _strip_html(msg.get("snippet") or "")
    body = body[:1200]
    when_bit = f" el {when}" if when else ""
    return f"Mail de {sender}{when_bit}. Asunto: {subject}. Contenido: {body}"
