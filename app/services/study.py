"""Resúmenes y material de estudio (vía Claude Haiku)."""

from __future__ import annotations

import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

_STUDY_SYSTEM = """\
Sos un tutor de estudio argentino. Tu salida se lee en voz alta: frases cortas,
sin emojis, sin markdown (nada de #, *, ni guiones largos). Numerá con "uno,",
"dos,", etc. cuando haga falta.

Según el modo pedido, respondé SOLO con estas secciones, en este orden:

modo resumen:
1) Idea central: una o dos oraciones.
2) Puntos clave: entre 3 y 6 ideas breves.
3) Términos: hasta 5, cada uno con definición de una línea (omití si no aplica).
4) Para practicar: 3 preguntas cortas; después de cada una, la respuesta en una línea.

modo esquema:
Un esquema oral del tema en niveles (tema, subtemas, detalles), máximo 12 ítems.

modo fichas:
Entre 4 y 6 fichas. Cada ficha: "Pregunta: ... Respuesta: ..." en dos oraciones.

modo examen:
5 preguntas de práctica (sin revelar respuestas primero), y al final un bloque
"Respuestas:" con las 5 respuestas numeradas, una por línea.

Profundidad {depth}: corto = lo mínimo; medio = equilibrado; detallado = un poco más,
pero nunca un monólogo largo. Si el material es un tema sin texto, enseñalo bien
con lo esencial. Si es un texto largo, resumí ese texto (no inventes datos que no estén).
"""


def _normalize_mode(mode: str) -> str:
    raw = (mode or "resumen").strip().lower()
    aliases = {
        "summary": "resumen",
        "outline": "esquema",
        "flashcards": "fichas",
        "cards": "fichas",
        "quiz": "examen",
        "preguntas": "examen",
        "test": "examen",
    }
    raw = aliases.get(raw, raw)
    if raw not in {"resumen", "esquema", "fichas", "examen"}:
        return "resumen"
    return raw


def _normalize_depth(depth: str) -> str:
    raw = (depth or "medio").strip().lower()
    if raw in {"corto", "breve", "short"}:
        return "corto"
    if raw in {"detallado", "largo", "deep", "full"}:
        return "detallado"
    return "medio"


def make_study_summary(
    material: str,
    mode: str = "resumen",
    depth: str = "medio",
) -> str:
    """
    Genera material de estudio a partir de un tema o de un texto dictado.
    mode: resumen | esquema | fichas | examen
    depth: corto | medio | detallado
    """
    text = (material or "").strip()
    if not text:
        return "Decime el tema o dictame el texto que querés estudiar."
    if len(text) > 12000:
        text = text[:12000] + "…"

    if not settings.anthropic_api_key:
        return "No tengo el motor de estudio configurado ahora."

    study_mode = _normalize_mode(mode)
    study_depth = _normalize_depth(depth)
    system = _STUDY_SYSTEM.format(depth=study_depth)

    try:
        llm = ChatAnthropic(
            model="claude-haiku-4-5",
            api_key=settings.anthropic_api_key,
            max_tokens=900 if study_depth != "detallado" else 1400,
            temperature=0.3,
        )
        result = llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(
                    content=(
                        f"Modo: {study_mode}.\n"
                        f"Material o tema del usuario:\n{text}"
                    )
                ),
            ]
        )
        content = getattr(result, "content", None)
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif hasattr(block, "text"):
                    parts.append(str(block.text))
            content = " ".join(p for p in parts if p).strip()
        else:
            content = str(content or "").strip()
        if not content:
            return "No pude armar el material de estudio. Probá de nuevo."
        return content
    except Exception:
        logger.exception("Fallo make_study_summary")
        return "No pude armar el resumen de estudio ahora."
