"""
Configuración central de Eliseo.
Nunca hardcodear API keys acá — todo viene de variables de entorno,
que en local se leen desde el archivo .env (ver .env.example) y en
Railway se configuran desde el panel del proyecto.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Entorno
    env: str = "development"

    # Base de datos (Railway provisiona esta URL automáticamente
    # al conectar un servicio de Postgres al proyecto)
    database_url: str = "sqlite:///./eliseo.db"

    # LLM (motor de orquestación)
    anthropic_api_key: str = ""

    # Voz
    deepgram_api_key: str = ""

    # Calendario
    google_client_id: str = ""
    google_client_secret: str = ""

    # WhatsApp Business (número nuevo dentro de la cuenta de la agencia)
    whatsapp_business_token: str = ""
    whatsapp_phone_number_id: str = ""


settings = Settings()
