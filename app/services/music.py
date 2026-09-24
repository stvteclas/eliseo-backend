"""Música dentro de Eliseo: previews encadenados (Deezer) para no salir de la app."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SERVICE_LABELS = {
    "spotify": "Spotify",
    "youtube_music": "YouTube Music",
}


def normalize_service(service: str | None) -> str:
    raw = (service or "spotify").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "yt": "youtube_music",
        "youtube": "youtube_music",
        "ytmusic": "youtube_music",
        "youtubemusic": "youtube_music",
        "youtube_music": "youtube_music",
        "music": "spotify",
        "spoti": "spotify",
        "spotify": "spotify",
    }
    return aliases.get(raw, "spotify")


def _spotify_token() -> str | None:
    client_id = (getattr(settings, "spotify_client_id", None) or "").strip()
    client_secret = (getattr(settings, "spotify_client_secret", None) or "").strip()
    if not client_id or not client_secret:
        return None
    try:
        response = httpx.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=8.0,
        )
        if response.status_code != 200:
            return None
        return (response.json().get("access_token") or "").strip() or None
    except Exception:
        logger.exception("Spotify token falló")
        return None


def _spotify_previews(query: str, limit: int = 8) -> dict | None:
    """Tracks con preview_url si hay Client Credentials."""
    token = _spotify_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        tracks = httpx.get(
            "https://api.spotify.com/v1/search",
            params={"q": query.strip(), "type": "track", "limit": max(1, min(limit, 10))},
            headers=headers,
            timeout=8.0,
        )
        if tracks.status_code != 200:
            return None
        items = (tracks.json().get("tracks") or {}).get("items") or []
        previews: list[str] = []
        titles: list[str] = []
        for track in items:
            preview = (track.get("preview_url") or "").strip()
            if not preview:
                continue
            name = (track.get("name") or "").strip()
            artists = ", ".join(
                (a.get("name") or "") for a in (track.get("artists") or []) if a.get("name")
            )
            titles.append(f"{name}" + (f" — {artists}" if artists else ""))
            previews.append(preview)
        if not previews:
            return None
        return {
            "title": titles[0],
            "preview_urls": previews,
            "preview_url": previews[0],
            "service": "spotify",
        }
    except Exception:
        logger.exception("Spotify search falló")
        return None


def _deezer_previews(query: str, limit: int = 8) -> dict | None:
    """API pública: varios MP3 de 30s para reproducir en Eliseo sin salir de la app."""
    try:
        response = httpx.get(
            "https://api.deezer.com/search",
            params={"q": query.strip(), "limit": max(1, min(limit, 12))},
            timeout=8.0,
        )
        if response.status_code != 200:
            return None
        items = response.json().get("data") or []
        previews: list[str] = []
        titles: list[str] = []
        for track in items:
            preview = (track.get("preview") or "").strip()
            if not preview:
                continue
            title = (track.get("title") or query).strip()
            artist = ((track.get("artist") or {}).get("name") or "").strip()
            titles.append(f"{title}" + (f" — {artist}" if artist else ""))
            previews.append(preview)
        if not previews:
            return None
        return {
            "title": titles[0],
            "preview_urls": previews,
            "preview_url": previews[0],
            "count": len(previews),
            "service": "deezer",
        }
    except Exception:
        logger.exception("Deezer search falló")
        return None


def play_music_plan(query: str, service: str = "spotify") -> dict:
    """
    Plan para reproducir DENTRO de Eliseo (cola de previews).
    No abre Spotify/YT: si salís de la app, Eliseo pierde el micrófono.
    """
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "message": "Decime qué canción, artista o estilo querés escuchar.",
            "preview_url": None,
            "preview_urls": [],
            "service": None,
            "label": None,
        }
    if len(q) > 200:
        q = q[:200]

    requested = normalize_service(service)
    resolved = _spotify_previews(q) if requested == "spotify" else None
    if resolved is None:
        resolved = _deezer_previews(q)

    if not resolved:
        return {
            "ok": False,
            "message": f"No encontré música para «{q}». Probá con otro artista o estilo.",
            "preview_url": None,
            "preview_urls": [],
            "service": None,
            "label": None,
        }

    n = len(resolved.get("preview_urls") or [])
    title = resolved["title"]
    if n > 1:
        message = (
            f"Te pongo «{title}» y sigo con temas parecidos. "
            "Seguimos en Eliseo: si me necesitás, decime Eliseo."
        )
    else:
        message = f"Te pongo «{title}». Si me necesitás, decime Eliseo."

    return {
        "ok": True,
        "message": message,
        "preview_url": resolved.get("preview_url"),
        "preview_urls": list(resolved.get("preview_urls") or []),
        "url": None,
        "url_alt": None,
        "service": resolved.get("service") or requested,
        "label": "Eliseo",
    }


def build_music_url(query: str, service: str = "spotify") -> str:
    """Compat tests / fallback de búsqueda externa (ya no se usa para play)."""
    q = (query or "").strip()
    svc = normalize_service(service)
    if svc == "youtube_music":
        return f"https://music.youtube.com/search?q={quote(q)}"
    return f"https://open.spotify.com/search/{quote(q)}"
