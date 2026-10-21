"""Páginas de acceso: registro, login, doble factor y salida."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import cuentas
from app.auth.csrf import verificar_csrf
from app.auth.dependencias import RUTA_SEGUNDO_FACTOR, sesion_actual, sesion_pendiente
from app.auth.sesiones import borrar_cookie, cerrar_sesion, completar_mfa, crear_sesion
from app.db import get_db
from app.models import Sesion, Usuario
from app.web.plantillas import renderizar
from app.web.portada import datos_portada

router = APIRouter()

# Mensajes que llegan por ?aviso=... (nunca se muestra texto que venga en la URL).
AVISOS = {
    "salida": "Cerraste la sesión.",
    "google": "No se pudo completar el ingreso con Google. Probá de nuevo.",
    "google_email": "Google no confirmó que ese email sea tuyo. Verificalo en tu cuenta de Google o entrá con tu contraseña.",
}
# Problemas al mandar el código, que llegan a /2fa/verificar por ?aviso=...
ERRORES_CODIGO = {
    "envio": cuentas.MENSAJE_ENVIO,
    "limite": f"Ya te mandamos {cuentas.MAX_ENVIOS_POR_HORA} códigos en la última hora. "
              "Usá el último que te llegó o probá de nuevo más tarde.",
}


def _redirigir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _segun_sesion(sesion: Sesion | None) -> RedirectResponse | None:
    """Si ya hay sesión, a dónde mandar al usuario en lugar de mostrarle login o registro."""
    if sesion is None:
        return None
    return _redirigir("/" if sesion.mfa_ok else RUTA_SEGUNDO_FACTOR)


def _al_segundo_factor(db: Session, usuario: Usuario, request: Request) -> RedirectResponse:
    """Abre la sesión pendiente, manda el código al email y lleva a la pantalla para escribirlo."""
    aviso = cuentas.iniciar_segundo_factor(db, usuario)
    respuesta = _redirigir(RUTA_SEGUNDO_FACTOR + (f"?aviso={aviso}" if aviso else ""))
    crear_sesion(db, usuario, request, respuesta)
    return respuesta


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
    return _al_segundo_factor(db, usuario, request)


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
    return _al_segundo_factor(db, usuario, request)


# --- Doble factor: código por email ---

def _pantalla_codigo(request: Request, sesion: Sesion, estado: int = 200, **contexto):
    usuario = sesion.usuario
    if "error" not in contexto and cuentas.minutos_de_bloqueo(usuario):
        contexto["error"] = cuentas.mensaje_bloqueo(usuario)
    minutos = int(cuentas.VIGENCIA_CODIGO.total_seconds() // 60)
    return renderizar(request, "2fa_verificar.html", {"usuario": usuario, "minutos": minutos, **contexto}, estado=estado)


@router.get("/2fa/verificar")
def ver_verificar(request: Request, aviso: str = "", sesion: Sesion = Depends(sesion_pendiente)):
    if sesion.mfa_ok:
        return _redirigir("/")
    if aviso in ERRORES_CODIGO:
        return _pantalla_codigo(request, sesion, error=ERRORES_CODIGO[aviso])
    if aviso == "reenviado":
        return _pantalla_codigo(request, sesion, aviso="Te mandamos un código nuevo. El anterior ya no sirve.")
    return _pantalla_codigo(request, sesion)


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
    try:
        cuentas.verificar_codigo(db, sesion.usuario, codigo)
    except cuentas.ErrorCuenta as e:
        return _pantalla_codigo(request, sesion, estado=400, error=str(e), codigo_invalido=True)
    respuesta = _redirigir("/")
    completar_mfa(db, sesion, respuesta)
    return respuesta


@router.post("/2fa/reenviar")
def reenviar(
    request: Request,
    csrf: str = Form(""),
    sesion: Sesion = Depends(sesion_pendiente),
    db: Session = Depends(get_db),
):
    verificar_csrf(request, csrf)
    if sesion.mfa_ok:
        return _redirigir("/")
    try:
        cuentas.enviar_codigo(db, sesion.usuario)
    except (cuentas.EsperaReenvio, cuentas.LimiteEnvios) as e:
        return _pantalla_codigo(request, sesion, estado=429, error=str(e))
    except cuentas.ErrorCuenta as e:
        return _pantalla_codigo(request, sesion, estado=400, error=str(e))
    return _redirigir(f"{RUTA_SEGUNDO_FACTOR}?aviso=reenviado")


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

