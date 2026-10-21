"""Funciones de apoyo para los tests de acceso."""

import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from app.auth.correo import ErrorCorreo
from app.auth.seguridad import hash_token, hashear_password
from app.auth.sesiones import COOKIE_SESION, DURACION, ahora
from app.models import Sesion, Usuario

PASSWORD = "una frase bastante larga"


def csrf_de(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def sin_ocultos(html: str) -> str:
    """El HTML sin los inputs ocultos: el token CSRF es aleatorio y puede contener cualquier texto corto ("535", "SMTP")."""
    return re.sub(r'<input type="hidden"[^>]*>', "", html)


def registrar(cliente, email="ana@example.com", password=PASSWORD, confirmacion=None, nombre="Ana Pérez"):
    token = csrf_de(cliente.get("/registro").text)
    return cliente.post("/registro", data={
        "nombre": nombre, "email": email, "password": password,
        "confirmacion": password if confirmacion is None else confirmacion, "csrf": token,
    })


def ingresar(cliente, email="ana@example.com", password=PASSWORD):
    token = csrf_de(cliente.get("/login").text)
    return cliente.post("/login", data={"email": email, "password": password, "csrf": token})


@dataclass
class Buzon:
    """Envío de correo falso: guarda los códigos en lugar de mandarlos. Con `falla=True` simula un error SMTP."""

    enviados: list[dict] = field(default_factory=list)
    falla: bool = False

    def enviar_codigo(self, destino: str, nombre: str, codigo: str, minutos: int) -> None:
        if self.falla:
            raise ErrorCorreo("SMTP simulado caído")
        self.enviados.append({"destino": destino, "nombre": nombre, "codigo": codigo, "minutos": minutos})

    def ultimo(self, destino: str | None = None) -> str:
        """El último código mandado (a `destino`, si se indica)."""
        return [m for m in self.enviados if destino in (None, m["destino"])][-1]["codigo"]


def verificar(cliente, codigo: str):
    token = csrf_de(cliente.get("/2fa/verificar").text)
    return cliente.post("/2fa/verificar", data={"codigo": codigo, "csrf": token})


def reenviar(cliente):
    token = csrf_de(cliente.get("/2fa/verificar").text)
    return cliente.post("/2fa/reenviar", data={"csrf": token})


def completar_2fa(cliente, buzon: Buzon):
    """Escribe el último código que llegó por email (después de registrarse o ingresar)."""
    r = verificar(cliente, buzon.ultimo())
    assert r.status_code == 303 and r.headers["location"] == "/", r.text
    return r


def entrar_directo(cliente, db: Session, email="api@example.com", rol="usuario") -> Usuario:
    """Crea un usuario con una sesión completa en la base y pone la cookie en el cliente."""
    usuario = Usuario(email=email, nombre="Usuaria API", password_hash=hashear_password(PASSWORD), rol=rol)
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
