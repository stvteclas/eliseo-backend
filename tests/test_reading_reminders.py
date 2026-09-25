"""Tests de lectura por partes y parseo de recordatorios."""

from app.services import reading as reading_service
from app.services import when_parse


def test_reading_chunks_continue_and_stop():
    uid = 4242
    reading_service.clear(uid)
    long = "Primera frase. " * 40 + "Última."
    first = reading_service.maybe_start_if_long(uid, long, threshold=50)
    assert "seguí" in first.lower() or "segui" in first.lower()
    assert reading_service.has_session(uid)
    nxt = reading_service.continue_reading(uid)
    assert nxt
    if reading_service.has_session(uid):
        stop = reading_service.stop_reading(uid)
        assert "paro" in stop.lower() or "listo" in stop.lower()
    assert not reading_service.has_session(uid)


def test_when_parse_relative_and_weekday():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone(timedelta(hours=-3)))  # viernes
    assert when_parse.seconds_until("en 10 minutos", now=now) == 600
    assert when_parse.seconds_until("en 2 horas", now=now) == 7200
    fri = when_parse.seconds_until("el lunes a las 9", now=now)
    assert fri is not None and fri > 0
    maniana = when_parse.seconds_until("mañana a las 9", now=now)
    assert maniana is not None and maniana > 0
