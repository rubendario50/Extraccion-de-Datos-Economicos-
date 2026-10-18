"""Configuración de la aplicación, leída de variables de entorno o del archivo .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://datos:datos@localhost:5432/datos"
    secret_key: str = "cambiar-en-produccion"
    app_encryption_key: str = ""
    cookie_secure: bool = False
    admin_email: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
