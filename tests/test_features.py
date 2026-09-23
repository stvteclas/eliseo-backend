"""
Tests de las features built-in nuevas (notas, cálculo, acciones cliente, etc.).
"""

import os
import uuid

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from app.agents.builtin_tools import BUILTIN_TOOL_NAMES, build_builtin_tools
from app.agents.client_actions import drain_client_actions, reset_client_actions
from app.core.database import SessionLocal
from app.models.user import User
from app.services import calculator as calculator_service
from app.services import notes as notes_service
from app.services import news as news_service
from app.services import translate as translate_service


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _user(db) -> int:
    user = User(email=f"feat-{uuid.uuid4().hex[:8]}@eliseo.dev", hashed_password="x")
    db.add(user)
    db.commit()
    return user.id


def test_builtin_tool_names_cover_the_ten_features():
    assert "set_timer" in BUILTIN_TOOL_NAMES
    assert "add_note" in BUILTIN_TOOL_NAMES
    assert "calculate" in BUILTIN_TOOL_NAMES
    assert "convert_currency" in BUILTIN_TOOL_NAMES
    assert "get_travel_time" in BUILTIN_TOOL_NAMES
    assert "get_news_headlines" in BUILTIN_TOOL_NAMES
    assert "get_daily_briefing" in BUILTIN_TOOL_NAMES
    assert "make_study_summary" in BUILTIN_TOOL_NAMES
    assert "start_translator_mode" in BUILTIN_TOOL_NAMES
    assert "start_service_connection" in BUILTIN_TOOL_NAMES
    assert "schedule_local_reminder" in BUILTIN_TOOL_NAMES
    assert "call_contact" in BUILTIN_TOOL_NAMES
    assert "get_daily_briefing" in BUILTIN_TOOL_NAMES


def test_calculate_expression_and_percent():
    assert "36" in calculator_service.evaluate_expression("12*3")
    assert "360" in calculator_service.evaluate_expression("15% de 2400")


def test_notes_add_list_remove_clear(db):
    user_id = _user(db)
    assert "leche" in notes_service.add_note(db, user_id, "leche").lower()
    listed = notes_service.list_notes(db, user_id)
    assert "leche" in listed.lower()
    assert "Saqué" in notes_service.remove_note(db, user_id, "leche")
    assert "vacía" in notes_service.list_notes(db, user_id).lower()
    notes_service.add_note(db, user_id, "pan")
    assert "Borré" in notes_service.clear_notes(db, user_id)


def test_set_timer_queues_client_action(db):
    user_id = _user(db)
    reset_client_actions()
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    msg = tools["set_timer"].invoke({"minutes": 5, "label": "pasta"})
    actions = drain_client_actions()
    assert "5 minutos" in msg
    assert actions == [{"type": "timer", "seconds": 300, "label": "pasta"}]


def test_schedule_reminder_and_call_contact_queue_actions(db):
    user_id = _user(db)
    reset_client_actions()
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    tools["schedule_local_reminder"].invoke({"message": "sacar la torta", "minutes": 10})
    tools["call_contact"].invoke({"name": "mamá"})
    actions = drain_client_actions()
    assert actions[0]["type"] == "local_notification"
    assert actions[0]["seconds"] == 600
    assert actions[1] == {"type": "call_contact", "query": "mamá"}


def test_translate_text(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"responseData": {"translatedText": "Hello"}}

    def fake_get(self, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    assert "Hello" in translate_service.translate_text("Hola", target_lang="en")


def test_news_headlines(monkeypatch):
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>Titular uno</title></item>
      <item><title>Titular dos</title></item>
    </channel></rss>"""

    class FakeResponse:
        status_code = 200
        text = xml

        def raise_for_status(self):
            return None

    def fake_get(self, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    report = news_service.get_headlines(limit=2)
    assert "Titular uno" in report
    assert "Titular dos" in report


def test_daily_briefing_includes_time_and_weather(db, monkeypatch):
    user_id = _user(db)

    def fake_weather(**kwargs):
        return "Clima en casa: soleado. Temperatura 20°C."

    monkeypatch.setattr("app.agents.builtin_tools.get_weather_report", fake_weather)
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    text = tools["get_daily_briefing"].invoke({})
    assert "hora de Argentina" in text.lower() or "de 20" in text or "Ahora es" in text
    assert "soleado" in text.lower() or "20" in text


def test_travel_time_google_with_traffic(monkeypatch):
    from app.services import traffic as traffic_service

    monkeypatch.setattr(traffic_service.settings, "google_maps_api_key", "test-key")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "OK",
                "routes": [
                    {
                        "legs": [
                            {
                                "duration": {"value": 1200, "text": "20 mins"},
                                "duration_in_traffic": {"value": 1800, "text": "30 mins"},
                                "distance": {"value": 10000, "text": "10 km"},
                                "start_address": "tu ubicación",
                                "end_address": "Obelisco, Buenos Aires",
                            }
                        ]
                    }
                ],
            }

    def fake_get(self, url, **kwargs):
        assert "maps.googleapis.com" in str(url)
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    report = traffic_service.travel_time_report(
        destination="Obelisco",
        latitude=-34.6,
        longitude=-58.4,
    )
    assert "30" in report or "minutos" in report.lower()
    assert "tráfico" in report.lower() or "congest" in report.lower()


def test_travel_time_falls_back_to_osrm(monkeypatch):
    from app.services import traffic as traffic_service

    monkeypatch.setattr(traffic_service.settings, "google_maps_api_key", "")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [{"lat": "-34.6", "lon": "-58.38", "display_name": "Obelisco"}]

    class FakeOsrm:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": [{"duration": 900, "distance": 5000}]}

    def fake_get(self, url, **kwargs):
        if "nominatim" in str(url):
            return FakeResponse()
        return FakeOsrm()

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    report = traffic_service.travel_time_report(
        destination="Obelisco",
        latitude=-34.6,
        longitude=-58.4,
    )
    assert "15 minutos" in report
    assert "sin el tráfico en vivo" in report


def test_make_study_summary_uses_llm(monkeypatch):
    from app.services import study as study_service

    monkeypatch.setattr(study_service.settings, "anthropic_api_key", "test-key")

    class FakeLLM:
        def invoke(self, messages):
            class R:
                content = (
                    "Idea central: la fotosíntesis convierte luz en energía. "
                    "Puntos clave: uno, necesita clorofila."
                )

            return R()

    monkeypatch.setattr(study_service, "ChatAnthropic", lambda **kwargs: FakeLLM())
    text = study_service.make_study_summary("fotosíntesis", mode="resumen", depth="corto")
    assert "fotosíntesis" in text.lower() or "Idea central" in text


def test_make_study_summary_requires_material(monkeypatch):
    from app.services import study as study_service

    monkeypatch.setattr(study_service.settings, "anthropic_api_key", "test-key")
    assert "tema" in study_service.make_study_summary("").lower()
