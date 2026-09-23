"""Tiempo de viaje y tráfico: Google Directions (con tráfico) o OSRM de respaldo."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
USER_AGENT = "EliseoAssistant/0.1 (personal assistant)"


def _format_duration(seconds: float) -> str:
    minutes = max(1, int(round(float(seconds) / 60)))
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} minutos"


def _traffic_label(typical_sec: float, live_sec: float) -> str:
    if typical_sec <= 0:
        return "tráfico normal"
    ratio = live_sec / typical_sec
    if ratio < 1.08:
        return "tráfico fluido"
    if ratio < 1.25:
        return "algo de tráfico"
    if ratio < 1.5:
        return "bastante congestionado"
    return "mucho tráfico"


def geocode_place(
    place: str,
    near_lat: float | None = None,
    near_lon: float | None = None,
) -> tuple[float, float, str] | None:
    params: dict = {"q": place, "format": "json", "limit": 1}
    if near_lat is not None and near_lon is not None:
        delta = 0.8
        params["viewbox"] = (
            f"{near_lon - delta},{near_lat + delta},{near_lon + delta},{near_lat - delta}"
        )
        params["bounded"] = 0
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers) as client:
        response = client.get(NOMINATIM_URL, params=params, timeout=20)
    response.raise_for_status()
    results = response.json() or []
    if not results:
        return None
    hit = results[0]
    label = hit.get("display_name") or place
    return float(hit["lat"]), float(hit["lon"]), label


def _origin_label_and_param(
    origin: str | None,
    latitude: float | None,
    longitude: float | None,
) -> tuple[str, str] | str:
    """
    Devuelve (label, origin_param) o un mensaje de error str.
    """
    if origin and origin.strip():
        return origin.strip(), origin.strip()
    if latitude is not None and longitude is not None:
        return "tu ubicación", f"{float(latitude)},{float(longitude)}"
    return "Necesito un origen o tu GPS para calcular el viaje."


def _google_travel_report(
    destination: str,
    origin: str | None,
    latitude: float | None,
    longitude: float | None,
) -> str | None:
    key = (settings.google_maps_api_key or "").strip()
    if not key:
        return None

    resolved = _origin_label_and_param(origin, latitude, longitude)
    if isinstance(resolved, str):
        return resolved
    origin_label, origin_param = resolved

    params = {
        "origin": origin_param,
        "destination": destination,
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "language": "es",
        "region": "ar",
        "key": key,
    }
    with httpx.Client(timeout=20) as client:
        response = client.get(GOOGLE_DIRECTIONS_URL, params=params)
        response.raise_for_status()
        data = response.json()

    status = data.get("status")
    if status != "OK":
        logger.info("Google Directions status=%s error=%s", status, data.get("error_message"))
        return None

    routes = data.get("routes") or []
    if not routes:
        return "No encontré una ruta en auto entre esos puntos."
    legs = routes[0].get("legs") or []
    if not legs:
        return "No encontré una ruta en auto entre esos puntos."
    leg = legs[0]

    typical = float((leg.get("duration") or {}).get("value") or 0)
    live = float((leg.get("duration_in_traffic") or leg.get("duration") or {}).get("value") or 0)
    meters = float((leg.get("distance") or {}).get("value") or 0)
    start_addr = leg.get("start_address") or origin_label
    end_addr = leg.get("end_address") or destination
    km = meters / 1000.0

    if live and typical and abs(live - typical) >= 60:
        label = _traffic_label(typical, live)
        return (
            f"Ahora, de {start_addr} a {end_addr}: unos {_format_duration(live)} "
            f"con el tráfico actual ({label}). Sin congestión serían unos "
            f"{_format_duration(typical)}. Son {km:.1f} km."
        )
    if live:
        label = _traffic_label(typical or live, live)
        return (
            f"De {start_addr} a {end_addr}: unos {_format_duration(live)} en auto "
            f"({km:.1f} km). Tráfico: {label}."
        )
    return (
        f"De {start_addr} a {end_addr}: unos {_format_duration(typical)} en auto "
        f"({km:.1f} km)."
    )


def _osrm_travel_report(
    destination: str,
    origin: str | None,
    latitude: float | None,
    longitude: float | None,
) -> str:
    if origin and origin.strip():
        start = geocode_place(origin.strip(), latitude, longitude)
        if start is None:
            return f"No encontré el origen '{origin.strip()}'."
    elif latitude is not None and longitude is not None:
        start = (float(latitude), float(longitude), "tu ubicación")
    else:
        return "Necesito un origen o tu GPS para calcular el viaje."

    end = geocode_place(destination, start[0], start[1])
    if end is None:
        return f"No encontré el destino '{destination}'."

    lon1, lat1 = start[1], start[0]
    lon2, lat2 = end[1], end[0]
    url = f"{OSRM_URL}/{lon1},{lat1};{lon2},{lat2}"
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(url, params={"overview": "false"}, timeout=20)
        response.raise_for_status()
        data = response.json()

    routes = data.get("routes") or []
    if not routes:
        return "No encontré una ruta en auto entre esos puntos."
    seconds = float(routes[0].get("duration") or 0)
    meters = float(routes[0].get("distance") or 0)
    km = meters / 1000.0
    return (
        f"En auto, de {start[2]} a {end[2]}: unos {_format_duration(seconds)} "
        f"({km:.1f} km). Es estimado sin el tráfico en vivo de este momento."
    )


def travel_time_report(
    destination: str,
    origin: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    dest = (destination or "").strip()
    if not dest:
        return "Decime a dónde querés ir."

    try:
        google = _google_travel_report(dest, origin, latitude, longitude)
        if google is not None:
            return google
        return _osrm_travel_report(dest, origin, latitude, longitude)
    except httpx.HTTPError:
        logger.exception("Fallo consultando tiempo de viaje")
        return "No pude calcular el tiempo de viaje ahora."
