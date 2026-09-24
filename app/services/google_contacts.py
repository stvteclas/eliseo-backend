"""Contactos de Google (People API) para resolver nombre → email."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"


def _people_service(credentials: Credentials):
    return build("people", "v1", credentials=credentials, cache_discovery=False)


def _fold(text: str) -> str:
    raw = (text or "").strip().lower()
    repl = str.maketrans(
        "áéíóúüñ",
        "aeiouun",
    )
    return raw.translate(repl)


def _best_email(person: dict) -> str | None:
    emails = person.get("emailAddresses") or []
    for item in emails:
        value = (item.get("value") or "").strip().lower()
        if value and "@" in value:
            return value
    return None


def _display_name(person: dict) -> str:
    names = person.get("names") or []
    if not names:
        return ""
    n = names[0]
    return (n.get("displayName") or n.get("givenName") or "").strip()


def search_contacts_by_name(
    credentials: Credentials,
    query: str,
    limit: int = 5,
) -> list[dict[str, str]]:
    """
    Busca en Google Contacts. Devuelve [{name, email}, ...].
    """
    q = (query or "").strip()
    if not q or "@" in q:
        return []

    try:
        service = _people_service(credentials)
        # searchContacts cubre la agenda del usuario
        result = (
            service.people()
            .searchContacts(
                query=q,
                readMask="names,emailAddresses",
                pageSize=max(1, min(int(limit or 5), 10)),
            )
            .execute()
        )
    except HttpError:
        logger.exception("People searchContacts falló")
        return []
    except Exception:
        logger.exception("People searchContacts falló")
        return []

    hits: list[dict[str, str]] = []
    for item in result.get("results") or []:
        person = item.get("person") or {}
        email = _best_email(person)
        if not email:
            continue
        name = _display_name(person) or email
        hits.append({"name": name, "email": email})
    return hits


def resolve_email_from_contacts(
    credentials: Credentials,
    query: str,
) -> tuple[str | None, str]:
    """
    (email, mensaje_error_o_vacio).
    Si hay varias coincidencias, pide desambiguar.
    """
    q = (query or "").strip()
    if not q:
        return None, "Decime el nombre del contacto."

    hits = search_contacts_by_name(credentials, q, limit=8)
    if not hits:
        return None, ""

    folded = _fold(q)
    exact = [h for h in hits if folded in _fold(h["name"]) or _fold(h["name"]).startswith(folded)]
    pool = exact or hits

    if len(pool) == 1:
        return pool[0]["email"], ""

    # Mejor score
    scored = sorted(
        pool,
        key=lambda h: SequenceMatcher(None, folded, _fold(h["name"])).ratio(),
        reverse=True,
    )
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if second is None or SequenceMatcher(None, folded, _fold(top["name"])).ratio() >= 0.72:
        if second and SequenceMatcher(None, folded, _fold(top["name"])).ratio() - SequenceMatcher(
            None, folded, _fold(second["name"])
        ).ratio() < 0.08:
            options = ", ".join(f"{h['name']} ({h['email']})" for h in scored[:4])
            return None, f"Encontré varios contactos: {options}. ¿Cuál?"
        return top["email"], ""

    options = ", ".join(f"{h['name']} ({h['email']})" for h in scored[:4])
    return None, f"Encontré varios contactos: {options}. ¿Cuál?"
