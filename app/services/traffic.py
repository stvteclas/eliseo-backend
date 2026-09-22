"""Tiempo de viaje aproximado vía Nominatim + OSRM (sin API key)."""

from __future__ import annotations

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "EliseoAssistant/0.1 (personal assistant)"


def geocode_place(place: str, near_lat: float | None = None, near_lon: float | None = None) -> tuple[float, float, str] | None:
    params: dict = {"q": place, "format": "json", "limit": 1}
    if near_lat is not None and near_lon is not None:
        # Sesgo suave hacia la ubicación del usuario
        delta = 0.8
        params["viewbox"] = f"{near_lon - delta},{near_lat + delta},{near_lon + delta},{near_lat - delta}"
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
        if origin and origin.strip():
            start = geocode_place(origin.strip(), latitude, longitude)
            if start is None:
                return f"No encontré el origen '{origin.strip()}'."
        elif latitude is not None and longitude is not None:
            start = (float(latitude), float(longitude), "tu ubicación")
        else:
            return "Necesito un origen o tu GPS para calcular el viaje."

        end = geocode_place(dest, start[0], start[1])
        if end is None:
            return f"No encontré el destino '{dest}'."

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
        minutes = max(1, int(round(seconds / 60)))
        km = meters / 1000.0
        hours, mins = divmod(minutes, 60)
        if hours:
            dura = f"{hours} h {mins} min" if mins else f"{hours} h"
        else:
            dura = f"{mins} minutos"
        return (
            f"En auto, de {start[2]} a {end[2]}: unos {dura} "
            f"({km:.1f} km). Es estimado sin tráfico en vivo."
        )
    except httpx.HTTPError:
        return "No pude calcular el tiempo de viaje ahora."
