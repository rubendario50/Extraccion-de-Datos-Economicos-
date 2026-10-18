"""Reglas de las cuentas: registro, login con bloqueo por intentos y doble factor."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import seguridad
from app.auth.sesiones import ahora, con_zona
from app.config import get_settings
from app.models import CodigoRecuperacion, Usuario

MAX_INTENTOS = 5
DURACION_BLOQUEO = timedelta(minutes=15)


class ErrorCuenta(ValueError):
    """Error que se le muestra al usuario tal cual."""


def normalizar_email(email: str) -> str:
    return email.strip().lower()


def email_valido(email: str) -> bool:
    if len(email) > 254 or email.count("@") != 1 or any(c.isspace() for c in email):
        return False
    local, dominio = email.split("@")
    return bool(local) and "." in dominio.strip(".") and not dominio.startswith(".")


def rol_inicial(email: str) -> str:
    admin = normalizar_email(get_settings().admin_email)
    return "admin" if admin and email == admin else "usuario"


@dataclass
class DatosRegistro:
    nombre: str
    email: str
    password: str
    confirmacion: str


def validar_registro(db: Session, datos: DatosRegistro) -> dict[str, str]:
    """Devuelve los errores por campo (vacío si todo está bien)."""
    errores = {}
    if not datos.nombre.strip():
        errores["nombre"] = "Escribí tu nombre."
    elif len(datos.nombre.strip()) > 100:
        errores["nombre"] = "El nombre puede tener hasta 100 caracteres."
    email = normalizar_email(datos.email)
    if not email_valido(email):
        errores["email"] = "Escribí un email válido, por ejemplo nombre@dominio.com."
    elif db.scalar(select(Usuario.id).where(Usuario.email == email)) is not None:
        errores["email"] = "Ya hay una cuenta con ese email. Iniciá sesión o usá otro."
    if len(datos.password) < seguridad.LARGO_MINIMO_PASSWORD:
        errores["password"] = f"La contraseña tiene que tener al menos {seguridad.LARGO_MINIMO_PASSWORD} caracteres."
    elif len(datos.password) > seguridad.LARGO_MAXIMO_PASSWORD:
        errores["password"] = f"La contraseña puede tener hasta {seguridad.LARGO_MAXIMO_PASSWORD} caracteres."
    elif datos.password != datos.confirmacion:
        errores["confirmacion"] = "Las contraseñas no coinciden."
    return errores


def registrar(db: Session, datos: DatosRegistro) -> Usuario:
    email = normalizar_email(datos.email)
    usuario = Usuario(
        email=email,
        nombre=datos.nombre.strip(),
        password_hash=seguridad.hashear_password(datos.password),
        rol=rol_inicial(email),
    )
    db.add(usuario)
    db.commit()
    return usuario


# --- Bloqueo por intentos fallidos ---

def minutos_de_bloqueo(usuario: Usuario) -> int:
    """Minutos que le quedan al bloqueo (0 si la cuenta no está bloqueada)."""
    hasta = con_zona(usuario.bloqueado_hasta)
    if hasta is None or hasta <= ahora():
        return 0
    return max(1, -(-int((hasta - ahora()).total_seconds()) // 60))


def mensaje_bloqueo(usuario: Usuario) -> str:
    minutos = minutos_de_bloqueo(usuario)
    return (
        f"Por seguridad bloqueamos el ingreso tras {MAX_INTENTOS} intentos fallidos. "
        f"Probá de nuevo en {minutos} {'minuto' if minutos == 1 else 'minutos'}."
    )


def registrar_fallo(db: Session, usuario: Usuario) -> None:
    """Fallo de contraseña."""
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= MAX_INTENTOS:
        usuario.bloqueado_hasta = ahora() + DURACION_BLOQUEO
        usuario.intentos_fallidos = 0
    db.commit()


def registrar_fallo_2fa(db: Session, usuario: Usuario) -> None:
    """Fallo de código (TOTP o recuperación). Este contador no lo reinicia la contraseña."""
    usuario.intentos_2fa += 1
    if usuario.intentos_2fa >= MAX_INTENTOS:
        usuario.bloqueado_hasta = ahora() + DURACION_BLOQUEO
        usuario.intentos_2fa = 0
    db.commit()


MENSAJE_LOGIN = "El email o la contraseña no son correctos."


def autenticar(db: Session, email: str, password: str) -> Usuario:
    """Devuelve el usuario si email y contraseña coinciden; si no, lanza ErrorCuenta."""
    usuario = db.scalar(select(Usuario).where(Usuario.email == normalizar_email(email)))
    correcta = seguridad.verificar_password(usuario.password_hash if usuario else None, password)
    if usuario is None:
        raise ErrorCuenta(MENSAJE_LOGIN)
    if minutos_de_bloqueo(usuario):
        raise ErrorCuenta(mensaje_bloqueo(usuario))
    if not correcta:
        registrar_fallo(db, usuario)
        if minutos_de_bloqueo(usuario):
            raise ErrorCuenta(mensaje_bloqueo(usuario))
        raise ErrorCuenta(MENSAJE_LOGIN)
    usuario.intentos_fallidos = 0
    db.commit()
    return usuario


# --- Doble factor ---

def secreto_pendiente(db: Session, usuario: Usuario) -> str:
    """Secreto TOTP a configurar. Se conserva entre recargas para no invalidar un QR ya escaneado."""
    if usuario.totp_secret_cifrado is None:
        usuario.totp_secret_cifrado = seguridad.cifrar(seguridad.nuevo_secreto_totp())
        db.commit()
    return seguridad.descifrar(usuario.totp_secret_cifrado)


def _verificar_totp(db: Session, usuario: Usuario, codigo: str) -> bool:
    paso = seguridad.verificar_totp(
        seguridad.descifrar(usuario.totp_secret_cifrado), codigo, usuario.totp_ultimo_paso
    )
    if paso is None:
        return False
    usuario.totp_ultimo_paso = paso
    db.commit()
    return True


MENSAJE_CODIGO = "El código no es correcto o ya se usó. Esperá a que la app muestre uno nuevo."


def activar_2fa(db: Session, usuario: Usuario, codigo: str) -> list[str]:
    """Confirma la configuración con un código y devuelve los códigos de recuperación (en claro, una sola vez)."""
    if minutos_de_bloqueo(usuario):
        raise ErrorCuenta(mensaje_bloqueo(usuario))
    if usuario.totp_secret_cifrado is None or not _verificar_totp(db, usuario, codigo):
        registrar_fallo_2fa(db, usuario)
        raise ErrorCuenta(mensaje_bloqueo(usuario) if minutos_de_bloqueo(usuario) else MENSAJE_CODIGO)
    codigos = seguridad.nuevos_codigos_recuperacion()
    usuario.codigos_recuperacion = [CodigoRecuperacion(hash=seguridad.hash_codigo_recuperacion(c)) for c in codigos]
    usuario.totp_activo = True
    db.commit()
    return codigos


def verificar_segundo_factor(db: Session, usuario: Usuario, codigo: str) -> str:
    """Acepta un código TOTP o uno de recuperación (que queda usado). Devuelve "totp" o "recuperacion"."""
    if minutos_de_bloqueo(usuario):
        raise ErrorCuenta(mensaje_bloqueo(usuario))
    limpio = codigo.strip()
    if limpio.replace(" ", "").isdigit():
        if _verificar_totp(db, usuario, limpio):
            return "totp"
    else:
        buscado = seguridad.hash_codigo_recuperacion(limpio)
        for guardado in usuario.codigos_recuperacion:
            if guardado.usado_en is None and guardado.hash == buscado:
                guardado.usado_en = ahora()
                db.commit()
                return "recuperacion"
    registrar_fallo_2fa(db, usuario)
    raise ErrorCuenta(mensaje_bloqueo(usuario) if minutos_de_bloqueo(usuario) else
                      "El código no es correcto o ya se usó.")
