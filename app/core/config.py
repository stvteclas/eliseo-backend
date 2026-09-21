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

    # Voz
    deepgram_api_key: str = ""

    # Calendario
    google_client_id: str = ""
    google_client_secret: str = ""

    # WhatsApp Business
    whatsapp_business_token: str = ""
    whatsapp_phone_number_id: str = ""

    # Mercado Pago
    mp_access_token: str = ""


settings = Settings()
