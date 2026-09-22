"""Titulares breves vía RSS de Google News (Argentina)."""

from __future__ import annotations

from urllib.parse import quote
import xml.etree.ElementTree as ET

import httpx

NEWS_RSS = "https://news.google.com/rss?hl=es-419&gl=AR&ceid=AR:es"


def get_headlines(limit: int = 5, query: str = "") -> str:
    """Devuelve titulares cortos para leer en voz alta."""
    n = max(1, min(int(limit or 5), 8))
    q = (query or "").strip()
    url = NEWS_RSS
    if q:
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote(q)}&hl=es-419&gl=AR&ceid=AR:es"
        )
    try:
        with httpx.Client() as client:
            response = client.get(url, timeout=20, follow_redirects=True)
            response.raise_for_status()
            xml_text = response.text
        root = ET.fromstring(xml_text)
        titles: list[str] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if title:
                titles.append(title)
            if len(titles) >= n:
                break
        if not titles:
            return "No encontré titulares ahora."
        numbered = [f"{i}. {t}" for i, t in enumerate(titles, start=1)]
        topic = f" sobre {q}" if q else ""
        return f"Titulares{topic}: " + " ".join(numbered)
    except (httpx.HTTPError, ET.ParseError):
        return "No pude leer las noticias en este momento."
