"""Traducción rápida vía MyMemory (sin API key para uso liviano)."""

from __future__ import annotations

import httpx

LANG_ALIASES = {
    "español": "es",
    "castellano": "es",
    "ingles": "en",
    "inglés": "en",
    "english": "en",
    "portugues": "pt",
    "portugués": "pt",
    "frances": "fr",
    "francés": "fr",
    "italiano": "it",
    "aleman": "de",
    "alemán": "de",
}


def _code(lang: str, default: str) -> str:
    raw = (lang or "").strip().lower()
    if not raw:
        return default
    if len(raw) == 2:
        return raw
    return LANG_ALIASES.get(raw, raw[:2])


def translate_text(text: str, target_lang: str = "en", source_lang: str = "es") -> str:
    body = (text or "").strip()
    if not body:
        return "Decime qué querés traducir."
    src = _code(source_lang, "es")
    dst = _code(target_lang, "en")
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
        translated = (data.get("responseData") or {}).get("translatedText") or ""
        translated = translated.strip()
        if not translated:
            return "No pude traducir eso ahora."
        return f"En {_label(dst)}: {translated}"
    except httpx.HTTPError:
        return "No pude traducir en este momento."


def _label(code: str) -> str:
    return {
        "es": "español",
        "en": "inglés",
        "pt": "portugués",
        "fr": "francés",
        "it": "italiano",
        "de": "alemán",
    }.get(code, code)
