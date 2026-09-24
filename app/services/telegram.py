"""
Telegram cuenta personal vía Telethon (MTProto).

Flujo de voz:
  1. start_login(phone) → Telegram manda código
  2. confirm_code(code) → sesión lista (o pide 2FA)
  3. confirm_password(pwd) → si hay verificación en dos pasos

La StringSession se guarda cifrada en DB; en cada tool se conecta y desconecta
(compatible con Vercel serverless).
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


def configured() -> bool:
    return bool(settings.telegram_api_id) and bool((settings.telegram_api_hash or "").strip())


def normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    # "más cincuenta y cuatro…" no; el agente debería pasar dígitos.
    digits = re.sub(r"[^\d+]", "", s)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits and not digits.startswith("+"):
        # Argentina sin +: asumir +54 si empieza con 9 / 11 / 15…
        if digits.startswith("54"):
            digits = "+" + digits
        else:
            digits = "+54" + digits
    return digits


def normalize_code(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _run(coro):
    """Ejecuta una corrutina desde tools sync (hilo worker de LangGraph)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Ya hay loop (poco frecuente): correr en hilo aparte.
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
        row = TelegramCredential(user_id=user_id, login_stage="none")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def is_connected(db: Session, user_id: int) -> bool:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    return bool(row and row.login_stage == "connected" and row.session_encrypted)


def status_text(db: Session, user_id: int) -> str:
    if not configured():
        return "Telegram no está configurado en el servidor todavía."
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage == "none":
        return (
            "Telegram no está conectado. Decí tu número con código de país "
            "(ej. más 54 9 11…) y te mando el código."
        )
    if row.login_stage == "code":
        return f"Estoy esperando el código que Telegram mandó al {row.phone}."
    if row.login_stage == "password":
        return "Telegram pide la contraseña de verificación en dos pasos."
    name = row.display_name or row.phone or "tu cuenta"
    return f"Telegram conectado como {name}."


def start_login(db: Session, user_id: int, phone: str) -> str:
    phone_n = normalize_phone(phone)
    if len(re.sub(r"\D", "", phone_n)) < 8:
        return "Necesito el número completo con código de país, por ejemplo más 54 9 11…"
    try:
        return _run(_start_login_async(db, user_id, phone_n))
    except Exception as exc:
        return _friendly_error(exc)


def confirm_code(db: Session, user_id: int, code: str) -> str:
    code_n = normalize_code(code)
    if len(code_n) < 4:
        return "Ese código parece corto. Decí los dígitos que te mandó Telegram."
    try:
        return _run(_confirm_code_async(db, user_id, code_n))
    except Exception as exc:
        return _friendly_error(exc)


def confirm_password(db: Session, user_id: int, password: str) -> str:
    pwd = (password or "").strip()
    if not pwd:
        return "Decime la contraseña de verificación en dos pasos de Telegram."
    try:
        return _run(_confirm_password_async(db, user_id, pwd))
    except Exception as exc:
        return _friendly_error(exc)


def disconnect(db: Session, user_id: int) -> str:
    from app.models.connector import UserConnector

    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is not None:
        db.delete(row)
    db.query(UserConnector).filter(
        UserConnector.user_id == user_id,
        UserConnector.service_name == "telegram",
    ).delete()
    db.commit()
    return "Listo, desconecté Telegram."


def list_dialogs(db: Session, user_id: int, limit: int = 15) -> str:
    if not is_connected(db, user_id):
        return "Primero conectá Telegram: decime tu número con código de país."
    try:
        return _run(_list_dialogs_async(db, user_id, limit))
    except Exception as exc:
        return _friendly_error(exc)


def get_messages(db: Session, user_id: int, contact: str, limit: int = 8) -> str:
    if not is_connected(db, user_id):
        return "Primero conectá Telegram."
    if not (contact or "").strip():
        return "Decime el nombre del contacto o chat."
    try:
        return _run(_get_messages_async(db, user_id, contact.strip(), limit))
    except Exception as exc:
        return _friendly_error(exc)


def send_message(db: Session, user_id: int, contact: str, text: str) -> str:
    if not is_connected(db, user_id):
        return "Primero conectá Telegram."
    body = (text or "").strip()
    if not body:
        return "Decime el texto del mensaje."
    if not (contact or "").strip():
        return "Decime a quién."
    try:
        return _run(_send_message_async(db, user_id, contact.strip(), body))
    except Exception as exc:
        return _friendly_error(exc)


def _friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc) or name
    if "TELEGRAM_API" in msg or "configurar" in msg.lower():
        return msg
    if "FloodWait" in name or "flood" in msg.lower():
        return "Telegram me pidió esperar un rato por demasiados intentos. Probá en unos minutos."
    if "PhoneCodeInvalid" in name or "phone code" in msg.lower():
        return "Ese código no es válido. Pedime que te mande otro o dictalo de nuevo."
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


async def _client_from_session(session_str: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    return client


async def _start_login_async(db: Session, user_id: int, phone: str) -> str:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        session_str = client.session.save()
        row = _get_or_create_cred(db, user_id)
        row.phone = phone
        row.pending_session_encrypted = encrypt(session_str)
        row.phone_code_hash = sent.phone_code_hash
        row.session_encrypted = None
        row.login_stage = "code"
        row.updated_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        return (
            f"Te mandé un código de Telegram al {phone}. "
            "Cuando te llegue, decímelo (solo los números)."
        )
    finally:
        await client.disconnect()


async def _confirm_code_async(db: Session, user_id: int, code: str) -> str:
    from telethon.errors import SessionPasswordNeededError

    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage not in {"code", "password"} or not row.pending_session_encrypted:
        return "No hay un login de Telegram en curso. Empezá diciendo tu número."
    if not row.phone or not row.phone_code_hash:
        return "Falta el número o el hash del código. Empezá de nuevo con tu teléfono."

    session_str = decrypt(row.pending_session_encrypted)
    client = await _client_from_session(session_str)
    try:
        try:
            await client.sign_in(
                phone=row.phone,
                code=code,
                phone_code_hash=row.phone_code_hash,
            )
        except SessionPasswordNeededError:
            # Guardar sesión intermedia (ya autenticada parcialmente)
            mid = client.session.save()
            row.pending_session_encrypted = encrypt(mid)
            row.login_stage = "password"
            row.updated_at = datetime.now(timezone.utc)
            db.add(row)
            db.commit()
            return (
                "Telegram pide tu contraseña de verificación en dos pasos. "
                "Decila ahora (o deletreala despacio)."
            )
        me = await client.get_me()
        _mark_connected(db, row, me, client.session.save())
        return f"Listo, Telegram quedó conectado como {row.display_name}."
    finally:
        await client.disconnect()


async def _confirm_password_async(db: Session, user_id: int, password: str) -> str:
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or row.login_stage != "password" or not row.pending_session_encrypted:
        return "No estoy esperando la contraseña de Telegram. Si hace falta, empezá con el número."

    session_str = decrypt(row.pending_session_encrypted)
    client = await _client_from_session(session_str)
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        _mark_connected(db, row, me, client.session.save())
        return f"Listo, Telegram quedó conectado como {row.display_name}."
    finally:
        await client.disconnect()


async def _with_user_client(db: Session, user_id: int):
    row = db.query(TelegramCredential).filter(TelegramCredential.user_id == user_id).first()
    if row is None or not row.session_encrypted or row.login_stage != "connected":
        raise RuntimeError("Telegram no está conectado.")
    session_str = decrypt(row.session_encrypted)
    return await _client_from_session(session_str), row


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
    # Username @foo
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
    # Último intento: get_entity por username sin @
    try:
        return await client.get_entity(contact)
    except Exception:
        return None


async def _list_dialogs_async(db: Session, user_id: int, limit: int) -> str:
    client, _row = await _with_user_client(db, user_id)
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


async def _get_messages_async(db: Session, user_id: int, contact: str, limit: int) -> str:
    client, _row = await _with_user_client(db, user_id)
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


async def _send_message_async(db: Session, user_id: int, contact: str, text: str) -> str:
    client, _row = await _with_user_client(db, user_id)
    try:
        entity = await _resolve_dialog(client, contact)
        if entity is None:
            return f"No encontré a «{contact}» en Telegram."
        await client.send_message(entity, text)
        return f"Listo, le mandé por Telegram a {contact}."
    finally:
        await client.disconnect()
