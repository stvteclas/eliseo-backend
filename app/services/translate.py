"""Traducción y modo traductor bidireccional (MyMemory)."""

from __future__ import annotations

import re

import httpx

LANG_ALIASES = {
    "español": "es",
    "espanol": "es",
    "castellano": "es",
    "spanish": "es",
    "ingles": "en",
    "inglés": "en",
    "english": "en",
    "ruso": "ru",
    "russian": "ru",
    "русский": "ru",
    "portugues": "pt",
    "portugués": "pt",
    "frances": "fr",
    "francés": "fr",
    "italiano": "it",
    "aleman": "de",
    "alemán": "de",
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_EXIT_RE = re.compile(
    r"\b("
    r"sal[ií](\s+del)?\s+modo\s+traductor|"
    r"dej[aá]\s+de\s+traducir|"
    r"cancel[aá]\s+traductor|"
    r"stop\s+translati|"
    r"exit\s+translator|"
    r"хватит|"
    r"стоп\s+перевод"
    r")\b",
    flags=re.IGNORECASE,
)


def normalize_lang(lang: str, default: str = "es") -> str:
    raw = (lang or "").strip().lower()
    if not raw:
        return default
    if len(raw) == 2:
        return raw
    return LANG_ALIASES.get(raw, raw[:2] if len(raw) >= 2 else default)


def _label(code: str) -> str:
    return {
        "es": "español",
        "en": "inglés",
        "ru": "ruso",
        "pt": "portugués",
        "fr": "francés",
        "it": "italiano",
        "de": "alemán",
    }.get(code, code)


def detect_lang_in_pair(text: str, lang_a: str, lang_b: str) -> str:
    """Elige cuál de los dos idiomas del par parece ser el del texto."""
    a = normalize_lang(lang_a)
    b = normalize_lang(lang_b)
    body = (text or "").strip()
    if not body:
        return a

    if a == "ru" or b == "ru":
        if _CYRILLIC_RE.search(body):
            return "ru"
        return a if a != "ru" else b

    # Sin cirílico: heurística simple es vs en
    lowered = body.lower()
    es_markers = (" qué", " que ", "cómo", "como ", "está", "esta ", "hola", "gracias", "por favor")
    en_markers = (" the ", " what", " how ", " is ", "hello", "thanks", "please")
    es_hits = sum(1 for m in es_markers if m in f" {lowered} ")
    en_hits = sum(1 for m in en_markers if m in f" {lowered} ")
    if "es" in (a, b) and "en" in (a, b):
        if es_hits > en_hits:
            return "es"
        if en_hits > es_hits:
            return "en"
    return a


def is_translator_exit(text: str) -> bool:
    return bool(_EXIT_RE.search(text or ""))


def translate_raw(text: str, source_lang: str, target_lang: str) -> str:
    """Devuelve solo el texto traducido (sin prefijos), para modo traductor / TTS."""
    body = (text or "").strip()
    if not body:
        return ""
    src = normalize_lang(source_lang)
    dst = normalize_lang(target_lang)
    if src == dst:
        return body
    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": body[:450], "langpair": f"{src}|{dst}"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        translated = ((data.get("responseData") or {}).get("translatedText") or "").strip()
        return translated or body
    except httpx.HTTPError:
        return ""


def translate_bidirectional(text: str, lang_a: str, lang_b: str) -> tuple[str, str]:
    """
    Detecta idioma del par y traduce al otro.
    Devuelve (texto_traducido, codigo_idioma_destino) para el TTS.
    """
    a = normalize_lang(lang_a)
    b = normalize_lang(lang_b)
    source = detect_lang_in_pair(text, a, b)
    target = b if source == a else a
    translated = translate_raw(text, source, target)
    if not translated:
        return "No pude traducir eso ahora.", a if a != "ru" else "es"
    return translated, target


def translate_text(text: str, target_lang: str = "en", source_lang: str = "es") -> str:
    body = (text or "").strip()
    if not body:
        return "Decime qué querés traducir."
    src = normalize_lang(source_lang, "es")
    dst = normalize_lang(target_lang, "en")
    if src == dst:
        return body
    translated = translate_raw(body, src, dst)
    if not translated:
        return "No pude traducir en este momento."
    return f"En {_label(dst)}: {translated}"
