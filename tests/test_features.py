"""
Tests de las features built-in nuevas (notas, cálculo, acciones cliente, etc.).
"""

import os
import uuid

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_eliseo.db")

from app.main import app  # noqa: F401 — create_all + migraciones de columnas
from app.agents.builtin_tools import BUILTIN_TOOL_NAMES, build_builtin_tools
from app.agents.client_actions import drain_client_actions, queue_client_action, reset_client_actions
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
    assert "play_music" in BUILTIN_TOOL_NAMES
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


def test_play_music_queues_open_url(db, monkeypatch):
    from app.services import music as music_service

    user_id = _user(db)
    reset_client_actions()
    monkeypatch.setattr(
        music_service,
        "play_music_plan",
        lambda query, service="spotify": {
            "ok": True,
            "message": "Te abro Spotify con «Cerati».",
            "url": "https://open.spotify.com/search/Cerati",
            "url_alt": "spotify:search:Cerati",
            "service": "spotify",
            "label": "Spotify",
        },
    )
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    msg = tools["play_music"].invoke({"query": "Gustavo Cerati", "service": "spotify"})
    actions = drain_client_actions()
    assert "Spotify" in msg
    assert actions[0]["type"] == "stop_audio"
    assert actions[1]["type"] == "open_url"
    assert "open.spotify.com" in actions[1]["url"]


def test_play_music_spotify_track_when_api_resolves(db, monkeypatch):
    from app.services import music as music_service

    user_id = _user(db)
    reset_client_actions()
    monkeypatch.setattr(
        music_service,
        "_spotify_open_target",
        lambda q: {
            "title": "Crimen",
            "url": "https://open.spotify.com/track/tid",
            "url_alt": "spotify:track:tid",
            "service": "spotify",
        },
    )
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    msg = tools["play_music"].invoke({"query": "Cerati", "service": "spotify"})
    actions = drain_client_actions()
    assert "Spotify" in msg
    assert actions[-1]["type"] == "open_url"
    assert "open.spotify.com/track" in actions[-1]["url"]


def test_stop_music_queues_action(db):
    user_id = _user(db)
    reset_client_actions()
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    assert "stop_music" in tools
    msg = tools["stop_music"].invoke({})
    actions = drain_client_actions()
    assert "eliseo" in msg.lower() or "spotify" in msg.lower() or "youtube" in msg.lower()
    assert actions == [{"type": "stop_audio"}]


def test_client_actions_survive_worker_thread():
    """LangGraph corre tools sync en otro hilo; las actions no se pueden perder."""
    import threading

    reset_client_actions()

    def worker():
        queue_client_action({"type": "open_url", "url": "https://example.com"})

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    actions = drain_client_actions()
    assert actions == [{"type": "open_url", "url": "https://example.com"}]


def test_prefs_wake_quiet_meeting_confirm(db):
    from app.services import prefs as prefs_service

    user_id = _user(db)
    assert "Perfecto" in prefs_service.set_wake_name(db, user_id, "Max")
    user = db.query(User).filter(User.id == user_id).first()
    assert prefs_service.display_name_for(user) == "Max"
    assert "max" in prefs_service.wake_names_for(user)
    assert "silencio" in prefs_service.set_quiet_mode(db, user_id, True).lower()
    assert "dale" in prefs_service.set_confirm_sends(db, user_id, True).lower()
    assert "reunión" in prefs_service.start_meeting_mode(db, user_id, 30).lower()
    db.refresh(user)
    assert prefs_service.is_meeting_mode(user) is True
    assert "salí" in prefs_service.stop_meeting_mode(db, user_id).lower()
    db.refresh(user)
    assert prefs_service.is_meeting_mode(user) is False


def test_habits_mark_and_status(db):
    from app.services import habits as habits_service

    user_id = _user(db)
    msg = habits_service.mark_habit_done(db, user_id, "agua")
    assert "agua" in msg.lower()
    assert "racha" in msg.lower()
    again = habits_service.mark_habit_done(db, user_id, "agua")
    assert "ya marcaste" in again.lower()
    status = habits_service.habit_status(db, user_id, "agua")
    assert "hecho" in status.lower() or "marcado" in status.lower()


def test_notes_check_off_and_list_tag(db):
    user_id = _user(db)
    notes_service.add_note(db, user_id, "leche", "compras")
    notes_service.add_note(db, user_id, "llamá a mamá", "ideas")
    assert "taché" in notes_service.check_off_note(db, user_id, "leche", "compras").lower()
    listed = notes_service.list_notes(db, user_id, "compras")
    assert "leche" in listed.lower()
    assert "✓" in listed
    ideas = notes_service.list_notes(db, user_id, "ideas")
    assert "mamá" in ideas.lower()


def test_pending_confirm_dale(db):
    from app.services import pending_confirm

    user_id = _user(db)
    called = {"ok": False}

    def runner():
        called["ok"] = True
        return "Mandado."

    pending_confirm.set_pending(user_id, "mail a Ana", runner)
    assert pending_confirm.get_pending_label(user_id) == "mail a Ana"
    assert pending_confirm.confirm_pending(user_id) == "Mandado."
    assert called["ok"] is True
    assert "nada pendiente" in pending_confirm.confirm_pending(user_id).lower()


def test_new_feature_tools_registered(db):
    user_id = _user(db)
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    for name in (
        "set_wake_name",
        "set_quiet_mode",
        "set_confirm_sends",
        "start_meeting_mode",
        "stop_meeting_mode",
        "get_today_overview",
        "get_inbox_digest",
        "start_pomodoro",
        "start_breathing",
        "confirm_pending_action",
        "repeat_last",
        "speak_slower",
        "broadcast_message",
        "check_off_note",
        "mark_habit_done",
    ):
        assert name in tools, name


def test_pomodoro_and_repeat_queue_actions(db):
    user_id = _user(db)
    reset_client_actions()
    tools = {t.name: t for t in build_builtin_tools(user_id=user_id, db=db)}
    tools["start_pomodoro"].invoke({"minutes": 25})
    tools["repeat_last"].invoke({})
    tools["speak_slower"].invoke({})
    actions = drain_client_actions()
    types = [a["type"] for a in actions]
    assert "timer" in types or "local_notification" in types
    assert "repeat_last" in types
    assert "speak_slow" in types
