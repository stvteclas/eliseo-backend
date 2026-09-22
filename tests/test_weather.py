"""
Tests de clima (Open-Meteo) y tools built-in de hora/clima.
"""

import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from app.agents.orchestrator import build_builtin_tools
from app.services import weather as weather_service


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data or {}
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_get_weather_report_asks_for_city_without_location():
    msg = weather_service.get_weather_report().lower()
    assert "ciudad" in msg or "ubicación" in msg or "gps" in msg


def test_get_weather_report_by_city(monkeypatch):
    calls = []

    def fake_get(self, url, **kwargs):
        calls.append(url)
        if "geocoding" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "Buenos Aires",
                            "admin1": "Buenos Aires",
                            "country": "Argentina",
                            "latitude": -34.6,
                            "longitude": -58.4,
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "current": {
                    "temperature_2m": 22.5,
                    "apparent_temperature": 21.0,
                    "relative_humidity_2m": 55,
                    "weather_code": 0,
                    "wind_speed_10m": 10,
                }
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    report = weather_service.get_weather_report(city="Buenos Aires")

    assert "Buenos Aires" in report
    assert "22.5" in report
    assert "cielo despejado" in report
    assert any("geocoding" in u for u in calls)
    assert any("forecast" in u for u in calls)


def test_get_weather_report_by_coords(monkeypatch):
    def fake_get(self, url, **kwargs):
        assert "forecast" in url
        return FakeResponse(
            {
                "current": {
                    "temperature_2m": 18.0,
                    "apparent_temperature": 17.0,
                    "relative_humidity_2m": 70,
                    "weather_code": 61,
                    "wind_speed_10m": 5,
                }
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    report = weather_service.get_weather_report(latitude=-34.6, longitude=-58.4)

    assert "18.0" in report
    assert "lluvia liviana" in report


def test_get_weather_report_unknown_city(monkeypatch):
    def fake_get(self, url, **kwargs):
        return FakeResponse({"results": []})

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    assert "No encontré" in weather_service.get_weather_report(city="CiudadQueNoExisteXYZ")


def test_builtin_datetime_tool_returns_argentina_time():
    tools = {t.name: t for t in build_builtin_tools()}
    text = tools["get_current_datetime"].invoke({})
    assert "hora de Argentina" in text


def test_builtin_weather_tool_uses_gps_when_city_empty(monkeypatch):
    monkeypatch.setattr(
        weather_service,
        "get_weather_report",
        lambda city=None, latitude=None, longitude=None: f"ok:{city}:{latitude}:{longitude}",
    )
    # Re-import binding used inside closure — monkeypatch the module the orchestrator imports
    import app.agents.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "get_weather_report",
        lambda city=None, latitude=None, longitude=None: f"ok:{city}:{latitude}:{longitude}",
    )

    tools = {t.name: t for t in orch.build_builtin_tools(latitude=-34.6, longitude=-58.4)}
    result = tools["get_weather"].invoke({"city": ""})
    assert result == "ok:None:-34.6:-58.4"
