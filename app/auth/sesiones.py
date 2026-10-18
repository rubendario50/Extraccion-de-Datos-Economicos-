"""Sesiones guardadas en la tabla `sesion`: la cookie lleva un token aleatorio y la base, su hash."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.seguridad import hash_token
from app.config import get_settings
from app.models import Sesion, Usuario

COOKIE_SESION = "sesion"
DURACION = timedelta(hours=12)
# Una sesión que todavía no pasó el doble factor dura poco.
DURACION_PENDIENTE = timedelta(minutes=15)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def con_zona(momento: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona horaria: se interpretan como UTC."""
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def poner_cookie(respuesta: Response, token: str) -> None:
    respuesta.set_cookie(
        COOKIE_SESION,
        token,
        max_age=int(DURACION.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def borrar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE_SESION, path="/", httponly=True, samesite="lax", secure=get_settings().cookie_secure)


def crear_sesion(db: Session, usuario: Usuario, request: Request, respuesta: Response) -> Sesion:
    """Abre una sesión sin doble factor y borra la anterior del mismo navegador, si había."""
    cerrar_sesion(db, request)
    token = secrets.token_urlsafe(32)
    sesion = Sesion(
        token_hash=hash_token(token),
        usuario_id=usuario.id,
        mfa_ok=False,
        expira_en=ahora() + DURACION_PENDIENTE,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
    )
    db.add(sesion)
    db.commit()
    poner_cookie(respuesta, token)
    return sesion


def completar_mfa(db: Session, sesion: Sesion, respuesta: Response) -> None:
    """Marca la sesión con el doble factor hecho y rota el token (el anterior deja de servir)."""
    token = secrets.token_urlsafe(32)
    sesion.token_hash = hash_token(token)
    sesion.mfa_ok = True
    sesion.expira_en = ahora() + DURACION
    sesion.usuario.ultimo_ingreso = ahora()
    sesion.usuario.intentos_fallidos = 0
    sesion.usuario.intentos_2fa = 0
    db.commit()
    poner_cookie(respuesta, token)


def sesion_de_request(db: Session, request: Request) -> Sesion | None:
    """La sesión vigente del navegador, o None. Borra la sesión si ya venció."""
    token = request.cookies.get(COOKIE_SESION)
    if not token:
        return None
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == hash_token(token)))
    if sesion is None:
        return None
    if con_zona(sesion.expira_en) <= ahora():
        db.delete(sesion)
        db.commit()
        return None
    return sesion


def cerrar_sesion(db: Session, request: Request) -> None:
    token = request.cookies.get(COOKIE_SESION)
    if token:
        db.execute(delete(Sesion).where(Sesion.token_hash == hash_token(token)))
        db.commit()
