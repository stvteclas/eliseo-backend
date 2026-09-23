"""Abrir Spotify o YouTube Music con una búsqueda / canción."""

from __future__ import annotations

from urllib.parse import quote

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


def build_music_url(query: str, service: str = "spotify") -> str:
    q = (query or "").strip()
    svc = normalize_service(service)
    if svc == "youtube_music":
        return f"https://music.youtube.com/search?q={quote(q)}"
    # HTTPS: en el teléfono suele abrir la app de Spotify si está instalada.
    return f"https://open.spotify.com/search/{quote(q)}"


def play_music_plan(query: str, service: str = "spotify") -> dict:
    """
    Devuelve {ok, message, url, service, label} para que la tool encole open_url.
    """
    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "message": "Decime qué canción, artista o playlist querés escuchar.",
            "url": None,
            "service": None,
            "label": None,
        }
    if len(q) > 200:
        q = q[:200]

    svc = normalize_service(service)
    label = SERVICE_LABELS[svc]
    url = build_music_url(q, svc)
    return {
        "ok": True,
        "message": f"Te abro {label} con «{q}».",
        "url": url,
        "service": svc,
        "label": label,
    }
