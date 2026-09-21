# T02 — Autenticación

Estos archivos van DENTRO de tu carpeta `eliseo-backend` existente,
respetando la misma estructura de carpetas (copialos/pegalos encima).

## Archivos nuevos
- `app/core/database.py`
- `app/core/security.py`
- `app/models/user.py`
- `app/schemas/__init__.py` + `app/schemas/user.py`
- `app/api/routes/auth.py`
- `tests/test_auth.py`

## Archivos que REEMPLAZAN a los que ya tenías
- `app/core/config.py` (agrega `jwt_secret` y `mp_access_token`)
- `app/main.py` (incluye el router de auth y crea las tablas al arrancar)
- `requirements.txt` (agrega sqlalchemy, psycopg2-binary, passlib, pyjwt)
- `.env.example` (agrega las variables nuevas)

## Pasos

```bash
cd eliseo-backend
# copiá/pegá los archivos de este zip encima de tu carpeta

# con la venv activada:
pip install -r requirements.txt
```

Generá un `JWT_SECRET` random y ponelo en tu `.env` local (no cualquier
cosa fija — esto firma los tokens, si es débil o se filtra, cualquiera
podría falsificar sesiones):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copiá el resultado a `.env`:
```
JWT_SECRET=el_valor_que_generaste
```

## Correr los tests

```bash
pytest
```

Deberían pasar los 4 checks de `test_auth.py`: registro, registro
duplicado rechazado, login, y ruta protegida con/sin token.

## Probar a mano (opcional)

```bash
uvicorn app.main:app --reload
```

Y en otra terminal:
```bash
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d "{\"email\":\"vos@ejemplo.com\",\"password\":\"algosegura123\"}"
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"vos@ejemplo.com\",\"password\":\"algosegura123\"}"
```

El segundo comando te devuelve un `access_token` — usalo así:
```bash
curl http://localhost:8000/auth/me -H "Authorization: Bearer EL_TOKEN_QUE_TE_DIO"
```

## Antes de deployar a Vercel

SQLite (el default) NO sirve en producción ahí — el filesystem no
persiste entre invocaciones de la función. Hace falta conectar Postgres
(Neon o Supabase desde el marketplace de Vercel) y setear `DATABASE_URL`
como variable de entorno del proyecto antes de que el registro/login
funcione en producción. Local, con SQLite, andás bien para desarrollar.

## Definición de terminado de T02

Los tests pasan en local, y (cuando conectemos Postgres) el mismo flujo
funciona contra el backend desplegado en Vercel.
