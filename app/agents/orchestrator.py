"""
Punto de entrada del motor de orquestación de Eliseo.

Todavía no implementado — esto es el placeholder para la HU-T03
(LangGraph + MCP integrado). Cuando llegue esa historia, acá va:

  1. El grafo de LangGraph que decide qué herramienta llamar.
  2. La carga del manifiesto de conectores MCP del usuario (HU-T04) —
     nunca un catálogo abierto, solo lo que ese usuario autorizó.
  3. El model routing barato/caro (HU-T06).

Por ahora, esta función solo existe para que el resto del esqueleto
(rutas, config) tenga un lugar hacia el cual crecer sin reordenar
carpetas más adelante.
"""


def handle_user_request(user_id: str, message: str) -> str:
    raise NotImplementedError(
        "Motor de orquestación pendiente — ver HU-T03 en el documento técnico."
    )
