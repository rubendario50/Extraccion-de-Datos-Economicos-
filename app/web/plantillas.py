"""Renderizado de plantillas Jinja2 con el token CSRF ya incluido."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from app import __version__
from app.auth.csrf import guardar_cookie_csrf, token_csrf
from app.config import get_settings

plantillas = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


def renderizar(request: Request, nombre: str, contexto: dict | None = None, estado: int = 200) -> HTMLResponse:
    datos = {
        "csrf": token_csrf(request),
        "version": __version__,
        "google_activo": bool(get_settings().google_client_id),
        **(contexto or {}),
    }
    respuesta = plantillas.TemplateResponse(request, nombre, datos, status_code=estado)
    respuesta.headers["Cache-Control"] = "no-store"
    guardar_cookie_csrf(request, respuesta)
    return respuesta
