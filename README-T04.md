# T04 — Manifiesto de conectores por usuario

El agente ya no carga un catálogo fijo de herramientas: `/chat` lee los
conectores que el usuario autorizó (tabla `user_connectors`, HU-T15) y el
orquestador conecta solo a los servidores MCP de esos servicios.

## Piezas
- `app/agents/orchestrator.py`:
  - `SERVICE_MCP_REGISTRY`: qué servicios tienen servidor MCP y cómo
    conectar (hoy solo `sandbox`, por HTTP).
  - `get_tools_for_user(user_id, db)`: lee los conectores del usuario y
    devuelve solo las herramientas de los que están en el registro. No
    llama al modelo. Sin conectores devuelve `[]` sin abrir ninguna
    conexión MCP.
  - `handle_user_message(message, user_id, db)`: arma el agente con esas
    herramientas (si no hay ninguna, conversa sin herramientas).
- `app/api/routes/chat.py`: pasa el usuario autenticado y la sesión de DB.

## Cambio de comportamiento respecto de T03
Para que un usuario tenga la herramienta de hora del servidor de prueba,
tiene que autorizar el servicio `sandbox`:

```
POST /connectors   {"service_name": "sandbox", "scope": "read_only"}
```

Sin eso, Eliseo responde que no tiene esa herramienta (en vez de inventar
la hora). Revocar el conector (`DELETE /connectors/sandbox`) lo saca del
manifiesto en el siguiente mensaje.

## Cómo sumar un servicio real
Registrarlo en `SERVICE_MCP_REGISTRY` con la config de su servidor MCP (HU-T11
calendario, HU-T20 Mercado Pago). Un conector sin servidor registrado
(ej. `whatsapp`) se ignora sin error.

## Fuera de alcance (a propósito)
- `scope` (`read_only` / `read_write`) todavía no filtra herramientas: se
  guarda pero no se aplica. Hace falta cuando existan herramientas que
  escriben.
- `store_credential` no se usa acá: es de T16.
