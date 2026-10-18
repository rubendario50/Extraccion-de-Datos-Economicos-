"""Ingreso con Google (OpenID Connect) usando Authlib.

Si GOOGLE_CLIENT_ID está vacío, las rutas responden 404 y el botón no se muestra.
El `state` y el `nonce` de OAuth viajan en la cookie firmada del SessionMiddleware.
"""

import logging
from functools import lru_cache

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import cuentas
from app.auth.dependencias import destino_segundo_factor
from app.auth.sesiones import crear_sesion
from app.config import get_settings
from app.db import get_db
from app.models import Usuario

router = APIRouter()
log = logging.getLogger(__name__)

URL_METADATOS = "https://accounts.google.com/.well-known/openid-configuration"


@lru_cache
def cliente_google():
    """Cliente OAuth de Authlib para Google (los tests lo reemplazan por uno simulado)."""
    ajustes = get_settings()
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=ajustes.google_client_id,
        client_secret=ajustes.google_client_secret,
        server_metadata_url=URL_METADATOS,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth.google


def _exigir_configuracion() -> None:
    if not get_settings().google_client_id:
        raise HTTPException(404)


def _a_login(aviso: str) -> RedirectResponse:
    return RedirectResponse(f"/login?aviso={aviso}", status_code=303)


@router.get("/auth/google", dependencies=[Depends(_exigir_configuracion)])
async def iniciar(request: Request):
    url_retorno = get_settings().base_url.rstrip("/") + "/auth/google/callback"
    return await cliente_google().authorize_redirect(request, url_retorno)


def usuario_desde_google(db: Session, datos: dict) -> Usuario:
    """Busca o crea el usuario a partir de los datos (`userinfo`) que devuelve Google.

    Lanza ErrorCuenta("google_email") si Google no confirma el email.
    """
    sub = str(datos.get("sub") or "")
    email = cuentas.normalizar_email(str(datos.get("email") or ""))
    if not sub or not email:
        raise cuentas.ErrorCuenta("google")
    usuario = db.scalar(select(Usuario).where(Usuario.google_sub == sub))
    if usuario is not None:
        return usuario
    # Vincular o crear solo con el email verificado: si no, alguien podría quedarse con una
    # cuenta ajena (o con el rol de admin) usando un email que no es suyo.
    if datos.get("email_verified") is not True:
        raise cuentas.ErrorCuenta("google_email")
    usuario = db.scalar(select(Usuario).where(Usuario.email == email))
    if usuario is not None:
        usuario.google_sub = sub
    else:
        nombre = str(datos.get("name") or email.split("@")[0])[:100]
        usuario = Usuario(email=email, nombre=nombre, google_sub=sub, rol=cuentas.rol_inicial(email))
        db.add(usuario)
    db.commit()
    return usuario


@router.get("/auth/google/callback", dependencies=[Depends(_exigir_configuracion)])
async def retorno(request: Request, db: Session = Depends(get_db)):
    try:
        token = await cliente_google().authorize_access_token(request)
    except Exception:  # cancelado por el usuario, state inválido, error de red...
        log.warning("Falló el intercambio con Google", exc_info=True)
        return _a_login("google")
    try:
        usuario = usuario_desde_google(db, token.get("userinfo") or {})
    except cuentas.ErrorCuenta as e:
        return _a_login(str(e))
    respuesta = RedirectResponse(destino_segundo_factor(usuario), status_code=303)
    crear_sesion(db, usuario, request, respuesta)
    return respuesta
