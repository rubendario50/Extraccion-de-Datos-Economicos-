"""Protección CSRF para los formularios POST.

El token del formulario es un HMAC (con SECRET_KEY) del token de la sesión. Antes de
iniciar sesión se usa en su lugar una cookie aleatoria `csrf` que se crea al mostrar el
formulario. Un sitio ajeno no puede leer esas cookies ni calcular el HMAC sin la clave.
"""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

from app.auth.sesiones import COOKIE_SESION
from app.config import get_settings

COOKIE_CSRF = "csrf"


class ErrorCsrf(HTTPException):
    def __init__(self) -> None:
        super().__init__(403, "El formulario venció o no es válido. Recargá la página y probá de nuevo.")


def _firmar(valor: str) -> str:
    clave = get_settings().secret_key.encode()
    return hmac.new(clave, f"csrf:{valor}".encode(), hashlib.sha256).hexdigest()


def token_csrf(request: Request) -> str:
    """Token para el campo oculto `csrf` de un formulario.

    Si el navegador no tiene sesión ni cookie `csrf`, se elige un valor nuevo; la cookie
    se agrega a la respuesta con `guardar_cookie_csrf`.
    """
    base = request.cookies.get(COOKIE_SESION) or request.cookies.get(COOKIE_CSRF)
    if not base:
        base = getattr(request.state, "csrf_nuevo", None) or secrets.token_urlsafe(32)
        request.state.csrf_nuevo = base
    return _firmar(base)


def guardar_cookie_csrf(request: Request, respuesta: Response) -> None:
    nuevo = getattr(request.state, "csrf_nuevo", None)
    if nuevo:
        respuesta.set_cookie(
            COOKIE_CSRF, nuevo, httponly=True, samesite="lax", secure=get_settings().cookie_secure, path="/"
        )


def verificar_csrf(request: Request, token: str | None) -> None:
    base = request.cookies.get(COOKIE_SESION) or request.cookies.get(COOKIE_CSRF)
    if not base or not token or not hmac.compare_digest(_firmar(base), token):
        raise ErrorCsrf()
