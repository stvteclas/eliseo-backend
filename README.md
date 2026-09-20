# Eliseo — backend

Esqueleto inicial (HU-T01). Motor de orquestación (LangGraph + MCP) todavía
no implementado — ver `app/agents/orchestrator.py` y la HU-T03 en el
documento técnico del proyecto.

## Arrancar en local

```bash
python -m venv venv
source venv/bin/activate          # en Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # completar las API keys reales acá
uvicorn app.main:app --reload
```

Confirmar que anda: abrir http://localhost:8000/health — debe responder
`{"status": "ok"}`.

## Correr los tests

```bash
pytest
```

## Lint

```bash
ruff check .
```

## Desplegar en Railway

1. Crear un nuevo proyecto en Railway desde este repo de GitHub.
2. Agregar un servicio de Postgres al mismo proyecto (Railway arma
   `DATABASE_URL` solo).
3. Cargar las variables de `.env.example` como variables de entorno del
   servicio (con los valores reales).
4. Cada push a `main` dispara un build y deploy automático — no hace
   falta configurar CI/CD aparte.
5. Confirmar `https://<tu-servicio>.up.railway.app/health` después del
   primer deploy.

## Estructura

```
app/
  core/config.py       — configuración desde variables de entorno
  api/routes/           — endpoints HTTP
  agents/orchestrator.py — punto de entrada del motor de orquestación (HU-T03)
  services/             — integraciones externas (Calendar, Deepgram, etc.)
  models/               — modelos de datos (consentimiento, usuarios — HU-T15)
tests/
```
