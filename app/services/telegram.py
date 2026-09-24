"""
Telegram cuenta personal vía Telethon (MTProto).

Flujo de voz:
  1. start_login(phone) → Telegram manda código
  2. confirm_code(code) → sesión lista (o pide 2FA)
  3. confirm_password(pwd) → si hay verificación en dos pasos

Importante: las llamadas a Telethon corren en otro hilo (asyncio.run); la
sesión SQLAlchemy NUNCA se usa desde ese hilo — solo se pasan strings.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.models.telegram_credential import TelegramCredential

_DIGIT_WORDS = {
    "cero": "0",
    "zero": "0",
    "uno": "1",
    "una": "1",
    "dos": "2",
    "tres": "3",
    "cuatro": "4",
    "cinco": "5",
    "seis": "6",
    "siete": "7",
    "ocho": "8",
    "nueve": "9",
}


def configured() -> bool:
    return bool(settings.telegram_api_id) and bool((settings.telegram_api_hash or "").strip())


def normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    digits = re.sub(r"[^\d+]", "", s)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits and not digits.startswith("+"):
        if digits.startswith("54"):
            digits = "+" + digits
        else:
            digits = "+54" + digits
    return digits


def normalize_code(raw: str) -> str:
    """
    Acepta dígitos, o código dictado en español («uno dos tres…»).
    Telegram suele mandar 5 dígitos.
    """
    text = (raw or "").strip().lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    # Quitar frases típicas del STT (no tocar palabras sueltas como «es» / «tres»)
    for junk in (
        "el codigo es",
        "codigo es",
        "el codigo",
        "mi codigo es",
        "el code is",
        "telegram",
    ):
        text = text.replace(junk, " ")

    digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        # Preferir los últimos 5 si el STT agregó basura numérica
        if len(digits) > 6:
            digits = digits[-5:]
        return digits

    parts = re.findall(r"[a-z]+", text)
    out = []
    for p in parts:
        if p in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[p])
    joined = "".join(out)
    if len(joined) >= 4:
        return joined[:6]
    return digits or joined


def _run(coro):
    """Ejecuta una corrutina fuera del event loop de FastAPI/LangGraph."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=55)


def _api() -> tuple[int, str]:
    if not configured():
        raise RuntimeError(
            "Falta TELEGRAM_API_ID / TELEGRAM_API_HASH en el servidor (Vercel)."
        )
    return int(settings.telegram_api_id), (settings.telegram_api_hash or "").strip()


def _get_or_create_cred(db: Session, user_id: int) -> TelegramCredential:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None:
        row = TelegramCredential(user_id=user_id, login_stage="none", account_label="default")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def is_connected(db: Session, user_id: int) -> bool:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    return bool(row and row.login_stage == "connected" and row.session_encrypted)


def saved_phone(db: Session, user_id: int) -> str | None:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None:
        return None
    phone = (row.phone or "").strip()
    return phone if len(re.sub(r"\D", "", phone)) >= 8 else None


def agent_context(db: Session, user_id: int) -> str:
    """Línea fija para el system prompt: el modelo no debe re-pedir el número."""
    if not configured():
        return "Estado Telegram: no configurado en el servidor."
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is not None and row.login_stage == "connected" and row.session_encrypted:
        name = row.display_name or row.phone or "tu cuenta"
        phone = row.phone or ""
        return (
            f"Estado Telegram: YA CONECTADO como {name}"
            + (f" ({phone})" if phone else "")
            + ". NO pidas el número ni vuelvas a conectar. "
            "Usá get_telegram_messages / send_telegram_message / list_telegram_chats."
        )
    if row is not None and row.login_stage == "code" and row.phone:
        return (
            f"Estado Telegram: esperando el código enviado a {row.phone}. "
            "NO pidas el número. Usá confirm_telegram_code con los dígitos."
        )
    if row is not None and row.login_stage == "password":
        return (
            "Estado Telegram: falta la contraseña 2FA. "
            "Usá confirm_telegram_password. NO pidas el número."
        )
    phone = saved_phone(db, user_id)
    if phone:
        return (
            f"Estado Telegram: número guardado {phone}, sesión no activa. "
            "Si piden Telegram, llamá connect_telegram con phone vacío "
            "(usa el guardado). NO vuelvas a preguntar el número."
        )
    return (
        "Estado Telegram: sin número guardado. "
        "Pedí el número con código de país UNA sola vez y usá connect_telegram."
    )


def status_text(db: Session, user_id: int) -> str:
    if not configured():
        return "Telegram no está configurado en el servidor todavía."
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is not None and row.login_stage == "connected" and row.session_encrypted:
        name = row.display_name or row.phone or "tu cuenta"
        return f"Telegram conectado como {name}."
    if row is not None and row.login_stage == "code" and row.phone:
        return (
            f"Estoy esperando el código que Telegram mandó al {row.phone}. "
            "Dictalo dígito por dígito."
        )
    if row is not None and row.login_stage == "password":
        return "Telegram pide la contraseña de verificación en dos pasos."
    phone = saved_phone(db, user_id)
    if phone:
        return (
            f"Tengo tu número {phone} guardado, pero la sesión no está activa. "
            "Decí «conectá Telegram» y te mando el código, sin repetir el número."
        )
    return (
        "Telegram no está conectado. Decí tu número con código de país "
        "una sola vez (ej. más 54 9 11…) y lo guardo."
    )


def start_login(db: Session, user_id: int, phone: str = "") -> str:
    if is_connected(db, user_id):
        row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
        name = (row.display_name if row else None) or "tu cuenta"
        return (
            f"Telegram ya está conectado como {name}. "
            "No hace falta el número otra vez: pedime leer o mandar un mensaje."
        )

    raw = (phone or "").strip()
    if not raw or len(re.sub(r"\D", "", raw)) < 8:
        saved = saved_phone(db, user_id)
        if saved:
            phone_n = saved
        else:
            return (
                "Necesito tu número con código de país una sola vez, "
                "por ejemplo más 54 9 11… Después lo guardo."
            )
    else:
        phone_n = normalize_phone(raw)

    if len(re.sub(r"\D", "", phone_n)) < 8:
        return "Necesito el número completo con código de país, por ejemplo más 54 9 11…"

    try:
        session_str, phone_code_hash = _run(_send_code_net(phone_n))
    except Exception as exc:
        return _friendly_error(exc)

    if not session_str or not phone_code_hash:
        return "Telegram no devolvió un código válido. Probá de nuevo en un minuto."

    row = _get_or_create_cred(db, user_id)
    row.phone = phone_n  # se conserva para siempre (también tras desconectar sesión)
    row.pending_session_encrypted = encrypt(session_str)
    row.phone_code_hash = phone_code_hash
    row.session_encrypted = None
    row.login_stage = "code"
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return (
        f"Te mandé un código de Telegram al {phone_n}. "
        "Cuando te llegue, dictalo dígito por dígito. "
        "El número queda guardado: no te lo vuelvo a pedir."
    )


def confirm_code(db: Session, user_id: int, code: str) -> str:
    code_n = normalize_code(code)
    if len(code_n) < 4:
        return (
            "No entendí bien el código. Dictalo dígito por dígito, "
            "por ejemplo: uno dos tres cuatro cinco."
        )

    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage not in {"code", "password"} or not row.pending_session_encrypted:
        return "No hay un login de Telegram en curso. Empezá diciendo tu número."
    if not row.phone or not row.phone_code_hash:
        return "Falta el número o el hash del código. Empezá de nuevo con tu teléfono."

    try:
        session_str = decrypt(row.pending_session_encrypted)
    except Exception:
        return "No pude leer la sesión pendiente. Decime el número otra vez para reiniciar."

    try:
        outcome = _run(
            _sign_in_with_code_net(
                session_str,
                row.phone,
                code_n,
                row.phone_code_hash,
            )
        )
    except Exception as exc:
        return _friendly_error(exc, heard_code=code_n)

    kind = outcome.get("kind")
    if kind == "password":
        row.pending_session_encrypted = encrypt(outcome["session"])
        row.login_stage = "password"
        row.updated_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        return (
            "Telegram pide tu contraseña de verificación en dos pasos. "
            "Decila ahora."
        )
    if kind == "ok":
        _mark_connected(db, row, outcome["me"], outcome["session"])
        return f"Listo, Telegram quedó conectado como {row.display_name}."
    return "No pude completar el login de Telegram."


def confirm_password(db: Session, user_id: int, password: str) -> str:
    pwd = (password or "").strip()
    if not pwd:
        return "Decime la contraseña de verificación en dos pasos de Telegram."

    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage != "password" or not row.pending_session_encrypted:
        return "No estoy esperando la contraseña de Telegram. Si hace falta, empezá con el número."

    try:
        session_str = decrypt(row.pending_session_encrypted)
    except Exception:
        return "No pude leer la sesión. Empezá de nuevo con tu número."

    try:
        outcome = _run(_sign_in_password_net(session_str, pwd))
    except Exception as exc:
        return _friendly_error(exc)

    _mark_connected(db, row, outcome["me"], outcome["session"])
    return f"Listo, Telegram quedó conectado como {row.display_name}."


def disconnect(db: Session, user_id: int) -> str:
    """Cierra la sesión pero conserva el número para no pedirlo otra vez."""
    from app.models.connector import UserConnector

    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    phone = None
    if row is not None:
        phone = row.phone
        row.session_encrypted = None
        row.pending_session_encrypted = None
        row.phone_code_hash = None
        row.login_stage = "none"
        row.display_name = None
        row.telegram_user_id = None
        row.phone = phone  # conservar
        row.updated_at = datetime.now(timezone.utc)
        db.add(row)
    db.query(UserConnector).filter(
        UserConnector.user_id == user_id,
        UserConnector.service_name == "telegram",
    ).delete()
    db.commit()
    if phone:
        return (
            f"Desconecté la sesión de Telegram. Tu número {phone} sigue guardado: "
            "la próxima vez solo pedí conectar y el código."
        )
    return "Listo, desconecté Telegram."


def list_dialogs(db: Session, user_id: int, limit: int = 15) -> str:
    session_str = _session_for_user(db, user_id)
    if not session_str:
        return "Primero conectá Telegram: decime tu número con código de país."
    try:
        return _run(_list_dialogs_net(session_str, limit))
    except Exception as exc:
        return _friendly_error(exc)


def get_messages(db: Session, user_id: int, contact: str, limit: int = 8) -> str:
    session_str = _session_for_user(db, user_id)
    if not session_str:
        return "Primero conectá Telegram."
    if not (contact or "").strip():
        return "Decime el nombre del contacto o chat."
    try:
        return _run(_get_messages_net(session_str, contact.strip(), limit))
    except Exception as exc:
        return _friendly_error(exc)


def send_message(db: Session, user_id: int, contact: str, text: str) -> str:
    session_str = _session_for_user(db, user_id)
    if not session_str:
        return "Primero conectá Telegram."
    body = (text or "").strip()
    if not body:
        return "Decime el texto del mensaje."
    if not (contact or "").strip():
        return "Decime a quién."
    try:
        return _run(_send_message_net(session_str, contact.strip(), body))
    except Exception as exc:
        return _friendly_error(exc)


def _session_for_user(db: Session, user_id: int) -> str | None:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage != "connected" or not row.session_encrypted:
        return None
    try:
        return decrypt(row.session_encrypted)
    except Exception:
        return None


def _friendly_error(exc: Exception, heard_code: str | None = None) -> str:
    name = type(exc).__name__
    msg = str(exc) or name
    if "TELEGRAM_API" in msg or "configurar" in msg.lower():
        return msg
    if "ENCRYPTION_KEY" in msg or "Fernet" in name:
        return "Falta o está mal ENCRYPTION_KEY en el servidor. Sin eso no puedo guardar la sesión."
    if "FloodWait" in name or "flood" in msg.lower():
        return "Telegram me pidió esperar un rato por demasiados intentos. Probá en unos minutos."
    if "PhoneCodeInvalid" in name or "phone code invalid" in msg.lower():
        heard = f" (yo escuché {heard_code})" if heard_code else ""
        return (
            f"Ese código no coincidió{heard}. "
            "Volvé a dictarlo dígito por dígito, despacio. "
            "No pidas otro código todavía: el actual sigue valiendo unos minutos."
        )
    if "PhoneCodeExpired" in name or "expired" in msg.lower():
        return "El código venció. Decime el número de nuevo para pedirte otro."
    if "Password" in name and "invalid" in msg.lower():
        return "La contraseña de dos pasos no coincide. Probá de nuevo."
    if "AuthKey" in name or "unauthorized" in msg.lower():
        return "La sesión de Telegram expiró. Conectala de nuevo diciendo tu número."
    return f"No pude hablar con Telegram ahora ({name})."


def _mark_connected(db: Session, row: TelegramCredential, me: Any, session_str: str) -> None:
    from app.api.routes.connectors import upsert_user_connector

    first = getattr(me, "first_name", None) or ""
    last = getattr(me, "last_name", None) or ""
    uname = getattr(me, "username", None)
    display = (f"{first} {last}".strip() or uname or row.phone or "Telegram").strip()
    row.session_encrypted = encrypt(session_str)
    row.pending_session_encrypted = None
    row.phone_code_hash = None
    row.login_stage = "connected"
    row.telegram_user_id = str(getattr(me, "id", "") or "")
    row.display_name = display[:80]
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    upsert_user_connector(
        db,
        row.user_id,
        "telegram",
        scope="read_write",
        store_credential=True,
        account_label="default",
    )


# --- Solo red Telethon (sin Session de SQLAlchemy) ---


async def _client_from_session(session_str: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    return client


async def _send_code_net(phone: str) -> tuple[str, str]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        session_str = client.session.save()
        return session_str, sent.phone_code_hash
    finally:
        await client.disconnect()


async def _sign_in_with_code_net(
    session_str: str,
    phone: str,
    code: str,
    phone_code_hash: str,
) -> dict:
    from telethon.errors import SessionPasswordNeededError

    client = await _client_from_session(session_str)
    try:
        try:
            await client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            return {"kind": "password", "session": client.session.save()}
        me = await client.get_me()
        return {"kind": "ok", "session": client.session.save(), "me": me}
    finally:
        await client.disconnect()


async def _sign_in_password_net(session_str: str, password: str) -> dict:
    client = await _client_from_session(session_str)
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        return {"kind": "ok", "session": client.session.save(), "me": me}
    finally:
        await client.disconnect()


async def _resolve_dialog(client, contact: str):
    needle = contact.lower().strip()
    needle_fold = (
        needle.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    if needle.startswith("@"):
        return await client.get_entity(needle)

    best = None
    async for dialog in client.iter_dialogs(limit=80):
        name = (dialog.name or "").lower()
        name_fold = (
            name.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ñ", "n")
        )
        if needle_fold == name_fold or needle_fold in name_fold:
            if needle_fold == name_fold:
                return dialog.entity
            if best is None:
                best = dialog.entity
    if best is not None:
        return best
    try:
        return await client.get_entity(contact)
    except Exception:
        return None


async def _list_dialogs_net(session_str: str, limit: int) -> str:
    client = await _client_from_session(session_str)
    try:
        names = []
        async for dialog in client.iter_dialogs(limit=max(1, min(int(limit or 15), 30))):
            if dialog.name:
                names.append(dialog.name)
        if not names:
            return "No encontré chats recientes en Telegram."
        return "Chats de Telegram: " + "; ".join(names) + "."
    finally:
        await client.disconnect()


async def _get_messages_net(session_str: str, contact: str, limit: int) -> str:
    client = await _client_from_session(session_str)
    try:
        entity = await _resolve_dialog(client, contact)
        if entity is None:
            return f"No encontré el chat «{contact}» en Telegram."
        n = max(1, min(int(limit or 8), 20))
        msgs = await client.get_messages(entity, limit=n)
        if not msgs:
            return f"No hay mensajes recientes con {contact}."
        lines = []
        for m in reversed(list(msgs)):
            if not m or not (m.message or "").strip():
                continue
            who = "Vos" if m.out else (contact.split()[0] if contact else "Ellos")
            lines.append(f"{who}: {m.message.strip()}")
        if not lines:
            return f"Solo había mensajes sin texto con {contact}."
        return f"Telegram con {contact}: " + " | ".join(lines)
    finally:
        await client.disconnect()


async def _send_message_net(session_str: str, contact: str, text: str) -> str:
    client = await _client_from_session(session_str)
    try:
        entity = await _resolve_dialog(client, contact)
        if entity is None:
            return f"No encontré a «{contact}» en Telegram."
        await client.send_message(entity, text)
        return f"Listo, le mandé por Telegram a {contact}."
    finally:
        await client.disconnect()
