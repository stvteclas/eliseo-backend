"""
Clima vía Open-Meteo (sin API key): geocoding + temperatura actual.
"""

from __future__ import annotations

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Códigos WMO simplificados a español hablable.
_WMO_ES = {
    0: "cielo despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna liviana",
    53: "llovizna",
    55: "llovizna intensa",
    61: "lluvia liviana",
    63: "lluvia",
    65: "lluvia intensa",
    71: "nieve liviana",
    73: "nieve",
    75: "nieve intensa",
    80: "chaparrones livianos",
    81: "chaparrones",
    82: "chaparrones intensos",
    95: "tormenta",
    96: "tormenta con granizo",
    99: "tormenta fuerte con granizo",
}


def _describe_code(code: int | None) -> str:
    if code is None:
        return "condiciones desconocidas"
    return _WMO_ES.get(code, f"código de clima {code}")


def geocode_city(city: str) -> tuple[float, float, str] | None:
    """
    Devuelve (lat, lon, nombre_legible) o None si no hay resultados.

    Eliseo es un asistente para usuarios en Argentina, y el geocoding de
    Open-Meteo no siempre ordena por relevancia local: "Villa Allende" (Córdoba)
    devuelve primero una localidad de Chiapas, México, con el mismo nombre.
    Por eso se piden varios resultados y, si hay uno en Argentina, se prioriza
    sobre el resto — el usuario puede seguir pidiendo el clima de otro país
    (ej. "clima en Madrid") sin problema, porque ahí no hay ningún resultado
    argentino entre los candidatos.
    """
    with httpx.Client() as client:
        response = client.get(
            GEOCODE_URL,
            params={"name": city, "count": 10, "language": "es", "format": "json"},
            timeout=20,
        )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        return None
    place = next((r for r in results if r.get("country_code") == "AR"), results[0])
    name_parts = [place.get("name"), place.get("admin1"), place.get("country")]
    label = ", ".join(part for part in name_parts if part)
    return float(place["latitude"]), float(place["longitude"]), label


def fetch_current_weather(latitude: float, longitude: float, place_label: str | None = None) -> str:
    """Temperatura, sensación, humedad y descripción para unas coordenadas."""
    with httpx.Client() as client:
        response = client.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "America/Argentina/Buenos_Aires",
            },
            timeout=20,
        )
    response.raise_for_status()
    current = response.json().get("current") or {}
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    description = _describe_code(current.get("weather_code"))
    where = place_label or f"{latitude:.2f}, {longitude:.2f}"
    return (
        f"Clima en {where}: {description}. "
        f"Temperatura {temp}°C (sensación {feels}°C), "
        f"humedad {humidity}%, viento {wind} km/h."
    )


def get_weather_report(
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    """
    Resuelve ubicación por ciudad o por coords y devuelve un resumen de clima.
    Si no hay ni ciudad ni coords, pide una ciudad.
    """
    place_label = None
    if city and city.strip():
        resolved = geocode_city(city.strip())
        if resolved is None:
            return f"No encontré la ciudad '{city.strip()}'."
        latitude, longitude, place_label = resolved
    elif latitude is None or longitude is None:
        return "Necesito una ciudad o tu ubicación (GPS) para decirte el clima."

    try:
        return fetch_current_weather(latitude, longitude, place_label=place_label)
    except httpx.HTTPError:
        return "No pude consultar el clima en este momento."
