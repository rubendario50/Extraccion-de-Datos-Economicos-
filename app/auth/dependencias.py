"""Dependencias de FastAPI para exigir sesión y rol."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.sesiones import sesion_de_request
from app.db import get_db
from app.models import Sesion, Usuario


class RequiereIngreso(Exception):
    """No hay sesión completa. Las páginas redirigen a `destino`; la API responde 401."""

    def __init__(self, destino: str = "/login") -> None:
        self.destino = destino


def destino_segundo_factor(usuario: Usuario) -> str:
    return "/2fa/verificar" if usuario.totp_activo else "/2fa/configurar"


def sesion_actual(request: Request, db: Session = Depends(get_db)) -> Sesion | None:
    """La sesión del navegador (con o sin doble factor), o None."""
    return sesion_de_request(db, request)


def sesion_pendiente(sesion: Sesion | None = Depends(sesion_actual)) -> Sesion:
    """Para las pantallas del doble factor: exige una sesión con contraseña o Google hecho."""
    if sesion is None:
        raise RequiereIngreso("/login")
    return sesion


def usuario_actual(sesion: Sesion | None = Depends(sesion_actual)) -> Usuario:
    """Exige una sesión con el doble factor completo."""
    if sesion is None:
        raise RequiereIngreso("/login")
    if not sesion.mfa_ok:
        raise RequiereIngreso(destino_segundo_factor(sesion.usuario))
    return sesion.usuario


def requiere_admin(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if usuario.rol != "admin":
        raise HTTPException(403, "Esta sección es solo para administradores.")
    return usuario
