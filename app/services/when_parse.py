"""Parseo de demoras en español para recordatorios."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

ARGENTINA_TZ = timezone(timedelta(hours=-3))

_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def _fold(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
    )


def _parse_clock(text: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(hs|h|horas?)?\b", text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if "tarde" in text and 1 <= hour <= 7:
        hour += 12
    if "noche" in text and 1 <= hour <= 11:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def seconds_until(when: str, *, now: datetime | None = None) -> int | None:
    """
    Convierte frases tipo «en 10 minutos», «mañana a las 9», «el viernes a las 18»
    en segundos desde ahora. None si no se entiende.
    """
    raw = (when or "").strip()
    if not raw:
        return None
    folded = _fold(raw)
    base = now or datetime.now(ARGENTINA_TZ)
    if base.tzinfo is None:
        base = base.replace(tzinfo=ARGENTINA_TZ)
    else:
        base = base.astimezone(ARGENTINA_TZ)

    # Relativo: en N minutos / segundos / horas
    m = re.search(r"\ben\s+(\d+)\s*(segundos?|secs?|minutos?|mins?|horas?|hs?)\b", folded)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("seg") or unit.startswith("sec"):
            return max(1, n)
        if unit.startswith("min"):
            return max(1, n * 60)
        return max(1, n * 3600)

    m = re.search(r"\b(\d+)\s*(segundos?|minutos?|mins?|horas?)\b", folded)
    if m and ("en " in folded or folded.startswith(m.group(0))):
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("seg"):
            return max(1, n)
        if unit.startswith("min"):
            return max(1, n * 60)
        return max(1, n * 3600)

    clock = _parse_clock(folded) or (9, 0)
    hour, minute = clock

    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if "pasado manana" in folded or "pasado mañana" in raw.lower():
        target = target + timedelta(days=2)
        if target <= base:
            target = target + timedelta(days=1)
    elif "manana" in folded:
        target = (base + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        for name, wd in _WEEKDAYS.items():
            if name in folded or _fold(name) in folded:
                days = (wd - base.weekday()) % 7
                if days == 0 and target <= base:
                    days = 7
                if days == 0 and "proximo" in folded:
                    days = 7
                target = (base + timedelta(days=days)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                break
        else:
            # Solo hora: hoy o mañana
            if target <= base:
                target = target + timedelta(days=1)

    delta = int((target - base).total_seconds())
    if delta < 1:
        return None
    # Tope 14 días
    return min(delta, 14 * 24 * 3600)
