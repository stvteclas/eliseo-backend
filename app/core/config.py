"""
Configuración central de Eliseo.
Nunca hardcodear API keys acá — todo viene de variables de entorno,
que en local se leen desde el archivo .env (ver .env.example) y en
Vercel se configuran desde el dashboard del proyecto.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Entorno
    env: str = "development"

    # Base de datos (en producción: Postgres vía Neon/Supabase desde Vercel)
    database_url: str = "sqlite:///./eliseo.db"

    # Autenticación
    jwt_secret: str = "cambiar-esto-en-produccion"

    # LLM (motor de orquestación)
    anthropic_api_key: str = ""

    # Servidor MCP (herramientas del agente). Transporte HTTP: en local el
    # servidor de prueba corre aparte (python mcp_servers/sandbox_server.py);
    # en producción apunta al servicio MCP desplegado.
    mcp_sandbox_url: str = "http://127.0.0.1:8001/mcp"

    # Voz
    deepgram_api_key: str = ""

    # Calendario (HU-T11): credencial OAuth tipo "Web application" de Google Cloud.
    # En producción google_redirect_uri es la URL de Vercel + el mismo path.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/connectors/google_calendar/callback"
    # Login con Google (scopes openid/email/profile). Hay que agregarlo como
    # URI autorizada en la misma credencial OAuth web de Google Cloud.
    google_login_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Directions API (tráfico en vivo). Misma Cloud Console; habilitar
    # "Directions API" y crear una API key restringida.
    google_maps_api_key: str = ""

    # Solo para depurar los callbacks OAuth: muestra en la página el error que devolvió
    # el proveedor (Mercado Pago). Dejar en false salvo mientras se investiga una falla.
    oauth_debug: bool = False

    # Clave Fernet para cifrar credenciales guardadas (refresh tokens). Generar con:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # WhatsApp Business
    whatsapp_business_token: str = ""
    whatsapp_phone_number_id: str = ""

    # Mercado Pago (HU-T20): app "EliseoMP" con OAuth por usuario. mp_access_token es
    # solo el token de prueba del sandbox: el flujo real no lo usa.
    mp_access_token: str = ""
    mp_client_id: str = ""
    mp_client_secret: str = ""
    mp_redirect_uri: str = "http://localhost:8000/connectors/mercadopago/callback"

    # Microsoft Teams/Outlook Calendar (HU-T22): app registrada en Azure (Entra ID).
    # ms_tenant="common" acepta cuentas de cualquier organización, no solo una — importante
    # porque las cuentas que un usuario conecta (banco, agencia, personal) suelen ser de
    # organizaciones distintas.
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_redirect_uri: str = "http://localhost:8000/connectors/teams_calendar/callback"
    ms_tenant: str = "common"


settings = Settings()
