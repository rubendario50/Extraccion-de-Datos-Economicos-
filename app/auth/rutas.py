"""Páginas de acceso: registro, login, doble factor y salida."""

import segno
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.auth import cuentas, seguridad
from app.auth.csrf import verificar_csrf
from app.auth.dependencias import destino_segundo_factor, sesion_actual, sesion_pendiente
from app.auth.sesiones import borrar_cookie, cerrar_sesion, completar_mfa, crear_sesion
from app.db import get_db
from app.models import Sesion
from app.web.plantillas import renderizar
from app.web.portada import datos_portada

router = APIRouter()

# Mensajes que llegan por ?aviso=... (nunca se muestra texto que venga en la URL).
AVISOS = {
    "salida": "Cerraste la sesión.",
    "google": "No se pudo completar el ingreso con Google. Probá de nuevo.",
    "google_email": "Google no confirmó que ese email sea tuyo. Verificalo en tu cuenta de Google o entrá con tu contraseña.",
}


def _redirigir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _segun_sesion(sesion: Sesion | None) -> RedirectResponse | None:
    """Si ya hay sesión, a dónde mandar al usuario en lugar de mostrarle login o registro."""
    if sesion is None:
        return None
    return _redirigir("/" if sesion.mfa_ok else destino_segundo_factor(sesion.usuario))


# --- Login ---

@router.get("/login")
def ver_login(
    request: Request, aviso: str = "", sesion: Sesion | None = Depends(sesion_actual), db: Session = Depends(get_db)
):
    if (r := _segun_sesion(sesion)) is not None:
        return r
    return renderizar(request, "login.html", {"aviso": AVISOS.get(aviso), "email": "", "portada": datos_portada(db)})


@router.post("/login")
def entrar(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    verificar_csrf(request, csrf)
    try:
        usuario = cuentas.autenticar(db, email, password)
    except cuentas.ErrorCuenta as e:
        return renderizar(
            request, "login.html", {"error": str(e), "email": email.strip(), "portada": datos_portada(db)}, estado=400
        )
    respuesta = _redirigir(destino_segundo_factor(usuario))
    crear_sesion(db, usuario, request, respuesta)
    return respuesta


# --- Registro ---

@router.get("/registro")
def ver_registro(request: Request, sesion: Sesion | None = Depends(sesion_actual), db: Session = Depends(get_db)):
    if (r := _segun_sesion(sesion)) is not None:
        return r
    return renderizar(request, "registro.html", {"errores": {}, "datos": {}, "portada": datos_portada(db)})


@router.post("/registro")
def registrarse(
    request: Request,
    nombre: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirmacion: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    verificar_csrf(request, csrf)
    datos = cuentas.DatosRegistro(nombre=nombre, email=email, password=password, confirmacion=confirmacion)
    errores = cuentas.validar_registro(db, datos)
    if errores:
        return renderizar(
            request, "registro.html",
            {"errores": errores, "datos": {"nombre": nombre.strip(), "email": email.strip()}, "portada": datos_portada(db)},
            estado=400,
        )
    usuario = cuentas.registrar(db, datos)
    respuesta = _redirigir("/2fa/configurar")
    crear_sesion(db, usuario, request, respuesta)
    return respuesta


# --- Doble factor ---

def _contexto_configurar(db: Session, sesion: Sesion) -> dict:
    usuario = sesion.usuario
    secreto = cuentas.secreto_pendiente(db, usuario)
    qr = segno.make(seguridad.uri_totp(secreto, usuario.email), error="m")
    svg = qr.svg_inline(scale=1, border=2, omitsize=True, svgclass="qr", title="Código QR para la app de autenticación")
    clave = " ".join(secreto[i:i + 4] for i in range(0, len(secreto), 4))
    return {"usuario": usuario, "qr": Markup(svg), "clave": clave}


@router.get("/2fa/configurar")
def ver_configurar(request: Request, sesion: Sesion = Depends(sesion_pendiente), db: Session = Depends(get_db)):
    if sesion.mfa_ok:
        return _redirigir("/")
    if sesion.usuario.totp_activo:
        return _redirigir("/2fa/verificar")
    return renderizar(request, "2fa_configurar.html", _contexto_configurar(db, sesion))


@router.post("/2fa/configurar")
def configurar(
    request: Request,
    codigo: str = Form(""),
    csrf: str = Form(""),
    sesion: Sesion = Depends(sesion_pendiente),
    db: Session = Depends(get_db),
):
    verificar_csrf(request, csrf)
    if sesion.mfa_ok or sesion.usuario.totp_activo:
        return _redirigir("/")
    try:
        codigos = cuentas.activar_2fa(db, sesion.usuario, codigo)
    except cuentas.ErrorCuenta as e:
        contexto = _contexto_configurar(db, sesion) | {"error": str(e)}
        return renderizar(request, "2fa_configurar.html", contexto, estado=400)
    respuesta = renderizar(request, "2fa_codigos.html", {"codigos": codigos, "usuario": sesion.usuario})
    completar_mfa(db, sesion, respuesta)
    return respuesta


@router.get("/2fa/verificar")
def ver_verificar(request: Request, sesion: Sesion = Depends(sesion_pendiente)):
    if sesion.mfa_ok:
        return _redirigir("/")
    if not sesion.usuario.totp_activo:
        return _redirigir("/2fa/configurar")
    return renderizar(request, "2fa_verificar.html", {"usuario": sesion.usuario})


@router.post("/2fa/verificar")
def verificar(
    request: Request,
    codigo: str = Form(""),
    csrf: str = Form(""),
    sesion: Sesion = Depends(sesion_pendiente),
    db: Session = Depends(get_db),
):
    verificar_csrf(request, csrf)
    if sesion.mfa_ok:
        return _redirigir("/")
    if not sesion.usuario.totp_activo:
        return _redirigir("/2fa/configurar")
    try:
        cuentas.verificar_segundo_factor(db, sesion.usuario, codigo)
    except cuentas.ErrorCuenta as e:
        return renderizar(request, "2fa_verificar.html", {"usuario": sesion.usuario, "error": str(e)}, estado=400)
    respuesta = _redirigir("/")
    completar_mfa(db, sesion, respuesta)
    return respuesta


# --- Salir ---

@router.get("/salir")
def ver_salir(request: Request, sesion: Sesion | None = Depends(sesion_actual)):
    if sesion is None:
        return _redirigir("/login")
    return renderizar(request, "salir.html", {"usuario": sesion.usuario})


@router.post("/salir")
def salir(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    verificar_csrf(request, csrf)
    cerrar_sesion(db, request)
    respuesta = _redirigir("/login?aviso=salida")
    borrar_cookie(respuesta)
    return respuesta

