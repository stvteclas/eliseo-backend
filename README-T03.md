# T03 — Motor de orquestación (LangGraph + MCP)

## Archivos nuevos
- `mcp_servers/sandbox_server.py` — servidor MCP de juguete (una sola
  herramienta: la hora actual), para probar el mecanismo sin depender
  de una integración real todavía.
- `app/agents/orchestrator.py` — arma el agente LangGraph + carga las
  herramientas del MCP.
- `app/api/routes/chat.py` — el endpoint `POST /chat`, protegido por
  autenticación.

## Archivos que REEMPLAZAN a los que ya tenías
- `app/main.py` (incluye el router de chat)
- `requirements.txt` (agrega langgraph, langchain-mcp-adapters,
  langchain-anthropic, mcp)

## Instalar

```bash
pip install -r requirements.txt
```

Confirmá que tu `.env` tiene `ANTHROPIC_API_KEY` con un valor real (no
vacío) — sin eso, `/chat` va a fallar con un error claro en vez de
colgarse.

## Probar en local

El servidor MCP corre como servicio HTTP aparte (puerto 8001), así que hay
que levantar **dos procesos**, cada uno en su terminal:

```bash
# Terminal 1 — servidor MCP (herramientas)
python mcp_servers/sandbox_server.py

# Terminal 2 — backend
uvicorn app.main:app --reload
```

La URL del MCP se configura con `MCP_SANDBOX_URL` (por defecto
`http://127.0.0.1:8001/mcp`). Si el servidor MCP está caído, `/chat`
responde 503 con un mensaje claro.

Primero necesitás un token (usá un usuario que ya hayas registrado con
T02, o registrá uno nuevo):

**PowerShell:**
```powershell
$login = Invoke-RestMethod -Uri "http://localhost:8000/auth/login" -Method Post -ContentType "application/json" -Body '{"email":"vos@ejemplo.com","password":"algosegura123"}'
$token = $login.access_token

Invoke-RestMethod -Uri "http://localhost:8000/chat" -Method Post -ContentType "application/json" -Headers @{Authorization="Bearer $token"} -Body '{"message":"¿qué hora es?"}'
```

## Qué tiene que pasar

Eliseo tiene que responder con la hora actual, en una frase — eso
confirma que: el agente recibió el mensaje, decidió que necesitaba usar
la herramienta del servidor MCP (no la inventó de memoria), la llamó, y
armó una respuesta con el resultado. Es el primer momento en que Eliseo
"piensa" en vez de solo devolver algo fijo.

Si en cambio responde una hora inventada o dice que no puede saberlo,
algo en la conexión con el MCP no está andando — revisá que
`SANDBOX_SERVER_PATH` en `orchestrator.py` apunte bien al archivo
`sandbox_server.py` (usa una ruta relativa al propio archivo, así que
debería resolver sola, pero vale la pena confirmarlo si falla).

## Transporte HTTP (ya migrado)

El MCP usa `streamable-http` en vez de stdio, con `stateless_http=True`
(cada request es independiente, sin sesión en memoria). Para desplegar,
el servidor MCP tiene que correr como su propio servicio y
`MCP_SANDBOX_URL` tiene que apuntar a su URL pública. Eso queda para
cuando lleguen las herramientas reales: el servidor de prueba solo
existe para validar el mecanismo.

## Definición de terminado de T03

`/chat` responde correctamente en local, usando la herramienta del
servidor MCP de prueba (no inventando la respuesta).
