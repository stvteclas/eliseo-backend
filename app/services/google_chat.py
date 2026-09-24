"""Google Chat: leer y mandar mensajes con un contacto (DM)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.services import google_contacts as contacts_service

logger = logging.getLogger(__name__)

CHAT_SCOPES = (
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.memberships.readonly",
)


def _chat_service(credentials: Credentials):
    return build("chat", "v1", credentials=credentials, cache_discovery=False)


def _normalize_email(value: str) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    if match:
        return match.group(0)
    if "@" in raw:
        return raw
    return None


def _fold(text: str) -> str:
    raw = (text or "").strip().lower()
    return raw.translate(str.maketrans("áéíóúüñ", "aeiouun"))


def _user_name(email: str) -> str:
    return f"users/{email}"


def _format_when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
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


def _chat_error_message(exc: HttpError) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in {401, 403}:
        return (
            "Falta permiso de Google Chat o Contactos. Habilitá Chat API y People API "
            "en Cloud, reconectá Google aceptando Chat y Contactos, "
            "y asegurate de que el contacto use Google Chat."
        )
    if status == 404:
        return "No encontré un chat con ese contacto."
    return "No pude usar Google Chat ahora. Probá de nuevo en un rato."


def _is_me_member(member_name: str) -> bool:
    name = (member_name or "").strip()
    return name in {"users/me"} or name.endswith("/me")


def _peer_from_messages(service, space_name: str, my_resource: str | None) -> dict[str, str]:
    """Si members falla o no trae nombre, saca el peer del historial reciente."""
    try:
        listed = (
            service.spaces()
            .messages()
            .list(parent=space_name, pageSize=8, orderBy="createTime desc")
            .execute()
        )
    except Exception:
        return {}
    for msg in listed.get("messages") or []:
        if _sender_is_me(msg, my_resource):
            continue
        sender = msg.get("sender") or {}
        label = (sender.get("displayName") or "").strip()
        user = (sender.get("name") or "").strip()
        email = ""
        if user.startswith("users/") and "@" in user:
            email = user.split("/", 1)[1].lower()
        if label or email or user:
            return {
                "name": label or email or user.replace("users/", ""),
                "email": email,
                "user": user,
            }
    return {}


def list_chat_dm_contacts(credentials: Credentials, limit: int = 30) -> list[dict[str, str]]:
    """
    Contactos con los que ya hay un DM en Google Chat.
    [{name, email, space, user}, ...] — email/user pueden faltar; space alcanza para leer/enviar.
    """
    out: list[dict[str, str]] = []
    try:
        service = _chat_service(credentials)
        my_resource = _my_chat_user_name(service)
        page_token = None
        while len(out) < limit:
            kwargs = {
                "filter": 'spaceType = "DIRECT_MESSAGE"',
                "pageSize": min(50, max(10, limit)),
            }
            if page_token:
                kwargs["pageToken"] = page_token
            listed = service.spaces().list(**kwargs).execute()
            for space in listed.get("spaces") or []:
                space_name = (space.get("name") or "").strip()
                if not space_name:
                    continue
                display = (space.get("displayName") or "").strip()
                email = ""
                user = ""
                label = display

                try:
                    members = (
                        service.spaces()
                        .members()
                        .list(parent=space_name, pageSize=10)
                        .execute()
                    )
                except Exception:
                    logger.exception("Chat members.list falló en %s", space_name)
                    members = {}

                for membership in members.get("memberships") or []:
                    member = membership.get("member") or {}
                    if (member.get("type") or "").upper() != "HUMAN":
                        continue
                    mname = (member.get("name") or "").strip()
                    if _is_me_member(mname):
                        continue
                    if my_resource and mname == my_resource:
                        continue
                    user = mname
                    label = (member.get("displayName") or "").strip() or label
                    if mname.startswith("users/") and "@" in mname:
                        email = mname.split("/", 1)[1].lower()
                    break

                if not label or (not email and not user):
                    from_msgs = _peer_from_messages(service, space_name, my_resource)
                    if from_msgs:
                        label = label or from_msgs.get("name") or ""
                        email = email or from_msgs.get("email") or ""
                        user = user or from_msgs.get("user") or ""

                if not label and email:
                    label = email
                if not label and user.startswith("users/"):
                    label = user.split("/", 1)[1]
                # Sin ningún handle usable, igual guardamos el space (último recurso).
                if not label:
                    label = "chat reciente"

                out.append(
                    {
                        "name": label,
                        "email": email,
                        "space": space_name,
                        "user": user,
                    }
                )
                if len(out) >= limit:
                    break
            page_token = listed.get("nextPageToken")
            if not page_token:
                break
    except HttpError:
        logger.exception("Chat spaces.list DMs falló")
    except Exception:
        logger.exception("Chat spaces.list DMs falló")
    return out


def _name_match_score(query_fold: str, candidate_fold: str) -> float:
    if not query_fold or not candidate_fold:
        return 0.0
    score = SequenceMatcher(None, query_fold, candidate_fold).ratio()
    if query_fold == candidate_fold:
        return 1.0
    if query_fold in candidate_fold or candidate_fold in query_fold:
        score = max(score, 0.88)
    q_tokens = [t for t in query_fold.split() if t]
    c_tokens = [t for t in candidate_fold.split() if t]
    if q_tokens and c_tokens:
        # "ana" vs "ana lopez"
        if all(any(qt == ct or qt in ct or ct in qt for ct in c_tokens) for qt in q_tokens):
            score = max(score, 0.9)
        if q_tokens[0] == c_tokens[0]:
            score = max(score, 0.82)
    return score


def resolve_chat_target(
    credentials: Credentials,
    contact: str,
) -> tuple[dict[str, str] | None, str]:
    """
    Resuelve nombre/email a un target de Chat.
    Dict posible: {label, email, space, user}. Basta space O email O user.
    """
    raw = (contact or "").strip()
    if not raw:
        return None, "Decime a quién: un nombre de contacto o un email."

    as_email = _normalize_email(raw)
    if as_email:
        return {"label": as_email, "email": as_email, "space": "", "user": _user_name(as_email)}, ""

    email, err = contacts_service.resolve_email_from_contacts(credentials, raw)
    if email:
        return {"label": raw, "email": email, "space": "", "user": _user_name(email)}, ""
    if err:
        return None, err

    folded = _fold(raw)
    dms = list_chat_dm_contacts(credentials, limit=40)
    scored: list[tuple[float, dict[str, str]]] = []
    for hit in dms:
        name_fold = _fold(hit.get("name") or "")
        email_hit = (hit.get("email") or "").strip().lower()
        user_hit = (hit.get("user") or "").strip()
        score = _name_match_score(folded, name_fold)
        if email_hit:
            score = max(score, _name_match_score(folded, _fold(email_hit.split("@")[0])))
            if folded in email_hit:
                score = max(score, 0.92)
        if user_hit and folded in _fold(user_hit):
            score = max(score, 0.7)
        # Aceptamos match por nombre aunque no haya email: usamos el space del DM.
        if score >= 0.55 and (hit.get("space") or email_hit or user_hit):
            scored.append((score, hit))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, (
            f"No encontré a «{raw}» en Google Contacts ni en tus chats de Google Chat. "
            "Abrí el DM en Chat, o agregalo a contactos de Google, o dictame el email."
        )
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
        options = ", ".join(
            f"{h['name']}" + (f" ({h['email']})" if h.get("email") else "")
            for _, h in scored[:4]
        )
        return None, f"Encontré varios: {options}. ¿Cuál?"

    top = scored[0][1]
    return (
        {
            "label": top.get("name") or raw,
            "email": top.get("email") or "",
            "space": top.get("space") or "",
            "user": top.get("user") or "",
        },
        "",
    )


def resolve_contact(credentials: Credentials, contact: str) -> tuple[str | None, str]:
    """Compat: devuelve email si se puede; si solo hay DM por nombre, string vacío + ok vía target."""
    target, err = resolve_chat_target(credentials, contact)
    if err or not target:
        return None, err or "No encontré el contacto."
    if target.get("email"):
        return target["email"], ""
    # Sin email pero con space/user: señalamos éxito relativo con placeholder.
    if target.get("space") or target.get("user"):
        return target.get("label") or contact, ""
    return None, "No encontré el contacto."


def find_direct_message_space(credentials: Credentials, contact: str) -> tuple[str | None, str]:
    """
    Devuelve (space_name, error_o_ok).
    `contact` puede ser nombre o email. Si ya hay DM, usa ese space sin pedir email.
    """
    target, err = resolve_chat_target(credentials, contact)
    if err or not target:
        return None, err or "Necesito el contacto."

    if target.get("space"):
        return target["space"], ""

    service = _chat_service(credentials)
    user_resource = (target.get("user") or "").strip()
    if not user_resource and target.get("email"):
        user_resource = _user_name(target["email"])

    if user_resource:
        try:
            space = service.spaces().findDirectMessage(name=user_resource).execute()
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

    if not target.get("email") and not user_resource:
        return None, (
            f"Encontré a {target.get('label') or contact} pero no pude abrir el chat. "
            "Dictame el email una vez."
        )

    try:
        created = (
            service.spaces()
            .setup(
                body={
                    "space": {"spaceType": "DIRECT_MESSAGE"},
                    "memberships": [
                        {
                            "member": {
                                "name": user_resource or _user_name(target["email"]),
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


def list_chat_contacts(credentials: Credentials, limit: int = 15) -> str:
    """Lista hablable de contactos Chat + Google Contacts recientes no aplica; solo DMs."""
    dms = list_chat_dm_contacts(credentials, limit=max(1, min(int(limit or 15), 25)))
    if not dms:
        return (
            "No veo chats directos todavía. Podés decirme un nombre de Google Contacts "
            "o el email, o abrir un DM en Google Chat una vez."
        )
    bits = []
    for hit in dms:
        if hit.get("email"):
            bits.append(f"{hit['name']} ({hit['email']})")
        else:
            bits.append(hit["name"])
    return "Tus contactos de Google Chat: " + "; ".join(bits) + "."


def list_chat_messages(
    credentials: Credentials,
    contact: str,
    limit: int = 8,
) -> str:
    """Lee mensajes recientes del DM con contact (nombre o email)."""
    target, resolve_err = resolve_chat_target(credentials, contact)
    if resolve_err or not target:
        return resolve_err or "No encontré el contacto."

    space_name, err = find_direct_message_space(credentials, contact)
    if err or not space_name:
        return err or "No encontré el chat."

    label = target.get("label") or target.get("email") or contact
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
        return f"Todavía no hay mensajes con {label}."

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

    return f"Chat con {label}: " + " | ".join(lines)


def send_chat_message(
    credentials: Credentials,
    contact: str,
    text: str,
) -> str:
    """Envía un mensaje de texto al DM con contact (nombre o email)."""
    body = (text or "").strip()
    if not body:
        return "Decime qué querés mandarle."
    body = body[:3500]

    target, resolve_err = resolve_chat_target(credentials, contact)
    if resolve_err or not target:
        return resolve_err or "No encontré el contacto."

    space_name, err = find_direct_message_space(credentials, contact)
    if err or not space_name:
        return err or "No encontré el chat."

    label = target.get("label") or target.get("email") or contact
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

    preview = body if len(body) <= 80 else body[:77] + "…"
    return f"Listo, le mandé por Google Chat a {label}: «{preview}»."

def _parse_chat_time(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _peer_label_for_space(service, space: dict) -> str:
    display = (space.get("displayName") or "").strip()
    if display:
        return display
    space_name = space.get("name") or ""
    try:
        members = (
            service.spaces()
            .members()
            .list(parent=space_name, pageSize=10)
            .execute()
        )
    except Exception:
        return "alguien"
    for membership in members.get("memberships") or []:
        member = membership.get("member") or {}
        if (member.get("type") or "").upper() != "HUMAN":
            continue
        mname = (member.get("name") or "").strip()
        if mname.endswith("/me") or mname == "users/me":
            continue
        label = (member.get("displayName") or "").strip()
        if label:
            return label
        if mname.startswith("users/") and "@" in mname:
            return mname.split("/", 1)[1]
    return "alguien"


def _sender_is_me(message: dict, my_resource: str | None) -> bool:
    sender = message.get("sender") or {}
    name = (sender.get("name") or "").strip()
    if not name:
        return False
    if name in {"users/me"} or name.endswith("/me"):
        return True
    if my_resource and name == my_resource:
        return True
    return False


def _my_chat_user_name(service) -> str | None:
    try:
        me = service.users().get(name="users/me").execute()
        return (me.get("name") or "").strip() or None
    except Exception:
        return None


def poll_incoming_dm_messages(
    credentials: Credentials,
    since_iso: str | None = None,
    max_spaces: int = 15,
    max_per_space: int = 4,
) -> dict:
    """
    Detecta mensajes nuevos en DMs desde `since_iso`.

    Sin `since` (primer poll): no alerta historial; solo devuelve cursor = ahora.
    Omite mensajes propios cuando se puede detectar el usuario.
    """
    cursor_out = _now_iso()
    since = _parse_chat_time(since_iso)
    if since is None:
        return {"messages": [], "cursor": cursor_out}

    incoming: list[dict] = []
    latest = since

    try:
        service = _chat_service(credentials)
        my_resource = _my_chat_user_name(service)
        page_token = None
        spaces_seen = 0
        while spaces_seen < max_spaces:
            kwargs = {
                "filter": 'spaceType = "DIRECT_MESSAGE"',
                "pageSize": min(50, max(5, max_spaces)),
            }
            if page_token:
                kwargs["pageToken"] = page_token
            listed = service.spaces().list(**kwargs).execute()
            for space in listed.get("spaces") or []:
                if spaces_seen >= max_spaces:
                    break
                spaces_seen += 1
                space_name = space.get("name")
                if not space_name:
                    continue
                peer = _peer_label_for_space(service, space)
                try:
                    msgs = (
                        service.spaces()
                        .messages()
                        .list(
                            parent=space_name,
                            pageSize=max(1, min(int(max_per_space or 4), 10)),
                            orderBy="createTime desc",
                        )
                        .execute()
                    )
                except Exception:
                    logger.exception("Chat poll messages.list falló en %s", space_name)
                    continue
                for msg in msgs.get("messages") or []:
                    created = _parse_chat_time(msg.get("createTime"))
                    if created is None:
                        continue
                    if created > latest:
                        latest = created
                    if created <= since:
                        continue
                    if _sender_is_me(msg, my_resource):
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    text = re.sub(r"\s+", " ", text)[:280]
                    who = _sender_label(msg) or peer
                    incoming.append(
                        {
                            "from": who,
                            "text": text,
                            "create_time": msg.get("createTime") or "",
                            "space": space_name,
                        }
                    )
            page_token = listed.get("nextPageToken")
            if not page_token:
                break
    except HttpError:
        logger.exception("Chat poll spaces.list falló")
        return {"messages": [], "cursor": since_iso or cursor_out, "error": "chat_unavailable"}
    except Exception:
        logger.exception("Chat poll falló")
        return {"messages": [], "cursor": since_iso or cursor_out, "error": "chat_unavailable"}

    # Más viejo → más nuevo para leer en orden
    incoming.sort(key=lambda m: m.get("create_time") or "")
    if incoming:
        cursor_out = incoming[-1]["create_time"] or cursor_out
    elif latest > since:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        cursor_out = latest.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {"messages": incoming, "cursor": cursor_out}
