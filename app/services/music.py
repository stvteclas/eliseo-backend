"""Abrir Spotify o YouTube Music por fuera de Eliseo."""

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


def _spotify_open_target(query: str) -> dict | None:
    """Playlist o track reproducible en la app de Spotify."""
    token = _spotify_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    q = query.strip()
    try:
        playlists = httpx.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "playlist", "limit": 5},
            headers=headers,
            timeout=8.0,
        )
        if playlists.status_code == 200:
            for item in (playlists.json().get("playlists") or {}).get("items") or []:
                if item and item.get("id"):
                    pid = item["id"]
                    return {
                        "title": (item.get("name") or q).strip(),
                        "url": f"https://open.spotify.com/playlist/{pid}",
                        "url_alt": f"spotify:playlist:{pid}",
                        "service": "spotify",
                    }
        tracks = httpx.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "track", "limit": 1},
            headers=headers,
            timeout=8.0,
        )
        if tracks.status_code == 200:
            items = (tracks.json().get("tracks") or {}).get("items") or []
            if items and items[0].get("id"):
                track = items[0]
                tid = track["id"]
                name = (track.get("name") or q).strip()
                artists = ", ".join(
                    (a.get("name") or "") for a in (track.get("artists") or []) if a.get("name")
                )
                title = f"{name}" + (f" — {artists}" if artists else "")
                return {
                    "title": title,
                    "url": f"https://open.spotify.com/track/{tid}",
                    "url_alt": f"spotify:track:{tid}",
                    "service": "spotify",
                }
    except Exception:
        logger.exception("Spotify search falló")
    return None


def _deezer_search_label(query: str) -> str | None:
    """Nombre exacto de un tema para armar mejor la búsqueda en Spotify/YT."""
    try:
        response = httpx.get(
            "https://api.deezer.com/search",
            params={"q": query.strip(), "limit": 1},
            timeout=8.0,
        )
        if response.status_code != 200:
            return None
        items = response.json().get("data") or []
        if not items:
            return None
        track = items[0]
        title = (track.get("title") or "").strip()
        artist = ((track.get("artist") or {}).get("name") or "").strip()
        if title and artist:
            return f"{title} {artist}"
        return title or None
    except Exception:
        logger.exception("Deezer search falló")
        return None


def build_music_url(query: str, service: str = "spotify") -> str:
    q = (query or "").strip()
    svc = normalize_service(service)
    if svc == "youtube_music":
        return f"https://music.youtube.com/search?q={quote(q)}"
    return f"https://open.spotify.com/search/{quote(q)}"


def play_music_plan(query: str, service: str = "spotify") -> dict:
    """
    Abre Spotify o YouTube Music en el teléfono (fuera de Eliseo).
    """
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "message": "Decime qué canción, artista o estilo querés escuchar.",
            "url": None,
            "url_alt": None,
            "service": None,
            "label": None,
        }
    if len(q) > 200:
        q = q[:200]

    requested = normalize_service(service)
    label = SERVICE_LABELS[requested]

    if requested == "spotify":
        resolved = _spotify_open_target(q)
        if resolved:
            return {
                "ok": True,
                "message": f"Te abro {label} con «{resolved['title']}».",
                "url": resolved["url"],
                "url_alt": resolved.get("url_alt"),
                "service": "spotify",
                "label": label,
            }

    needle = _deezer_search_label(q) or q
    if requested == "youtube_music":
        url = f"https://music.youtube.com/search?q={quote(needle)}"
        alt = f"https://www.youtube.com/results?search_query={quote(needle)}"
    else:
        url = f"https://open.spotify.com/search/{quote(needle)}"
        alt = f"spotify:search:{quote(needle)}"

    return {
        "ok": True,
        "message": f"Te abro {label} con «{needle}».",
        "url": url,
        "url_alt": alt,
        "service": requested,
        "label": label,
    }
