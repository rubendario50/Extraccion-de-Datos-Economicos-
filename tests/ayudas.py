"""Funciones de apoyo para los tests de acceso."""

import re
import secrets
import time
from datetime import timedelta

import pyotp
from sqlalchemy.orm import Session

from app.auth.seguridad import hash_token, hashear_password
from app.auth.sesiones import COOKIE_SESION, DURACION, ahora
from app.models import Sesion, Usuario

PASSWORD = "una frase bastante larga"


def csrf_de(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def registrar(cliente, email="ana@example.com", password=PASSWORD, confirmacion=None, nombre="Ana Pérez"):
    token = csrf_de(cliente.get("/registro").text)
    return cliente.post("/registro", data={
        "nombre": nombre, "email": email, "password": password,
        "confirmacion": password if confirmacion is None else confirmacion, "csrf": token,
    })


def ingresar(cliente, email="ana@example.com", password=PASSWORD):
    token = csrf_de(cliente.get("/login").text)
    return cliente.post("/login", data={"email": email, "password": password, "csrf": token})


def secreto_de(html: str) -> str:
    return re.search(r'class="clave"[^>]*>([^<]+)<', html).group(1).replace(" ", "")


def configurar_2fa(cliente) -> tuple[str, list[str]]:
    """Completa /2fa/configurar con un código generado por pyotp. Devuelve el secreto y los códigos de recuperación."""
    pagina = cliente.get("/2fa/configurar")
    secreto = secreto_de(pagina.text)
    r = cliente.post("/2fa/configurar", data={"codigo": pyotp.TOTP(secreto).now(), "csrf": csrf_de(pagina.text)})
    assert r.status_code == 200, r.text
    codigos = re.findall(r"<li>([a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})</li>", r.text)
    return secreto, codigos


def codigo_siguiente(secreto: str) -> str:
    """Código de la ventana siguiente (dentro de la tolerancia), distinto del recién usado."""
    return pyotp.TOTP(secreto).at(time.time() + 30)


def verificar(cliente, codigo: str):
    token = csrf_de(cliente.get("/2fa/verificar").text)
    return cliente.post("/2fa/verificar", data={"codigo": codigo, "csrf": token})


def entrar_directo(cliente, db: Session, email="api@example.com", rol="usuario") -> Usuario:
    """Crea un usuario con una sesión completa en la base y pone la cookie en el cliente."""
    usuario = Usuario(email=email, nombre="Usuaria API", password_hash=hashear_password(PASSWORD),
                      totp_activo=True, rol=rol)
    db.add(usuario)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(Sesion(token_hash=hash_token(token), usuario_id=usuario.id, mfa_ok=True, expira_en=ahora() + DURACION))
    db.commit()
    cliente.cookies.set(COOKIE_SESION, token)
    return usuario


def vencer(db: Session, sesion: Sesion) -> None:
    sesion.expira_en = ahora() - timedelta(minutes=1)
    db.commit()
