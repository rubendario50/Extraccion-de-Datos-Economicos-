"""Configuración de la aplicación, leída de variables de entorno o del archivo .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://datos:datos@localhost:5432/datos"
    secret_key: str = "cambiar-en-produccion"
    cookie_secure: bool = False
    admin_email: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"
    # Correo saliente (código del doble factor). Sin usuario y contraseña, el código va al registro.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # vacío: se usa SMTP_USER


@lru_cache
def get_settings() -> Settings:
    return Settings()
