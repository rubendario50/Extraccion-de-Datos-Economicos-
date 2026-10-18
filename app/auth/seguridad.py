"""Piezas criptográficas: contraseñas (Argon2), cifrado del secreto TOTP (Fernet),
códigos TOTP y códigos de recuperación."""

import hashlib
import hmac
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

LARGO_MINIMO_PASSWORD = 12
LARGO_MAXIMO_PASSWORD = 256
EMISOR_TOTP = "Datos Económicos"
CANTIDAD_CODIGOS_RECUPERACION = 10
# Sin caracteres que se confunden al copiarlos a mano (0/o, 1/l/i).
ALFABETO_RECUPERACION = "abcdefghjkmnpqrstuvwxyz23456789"

_hasher = PasswordHasher()
# Hash de una contraseña cualquiera: se verifica contra él cuando el email no existe,
# para que el login tarde lo mismo y no delate qué emails tienen cuenta.
_HASH_FICTICIO = _hasher.hash("contraseña-ficticia-para-igualar-tiempos")


class ErrorConfiguracion(RuntimeError):
    """Falta o es inválida una variable de entorno necesaria."""


# --- Contraseñas ---

def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(hash_guardado: str | None, password: str) -> bool:
    try:
        return _hasher.verify(hash_guardado or _HASH_FICTICIO, password) and hash_guardado is not None
    except (VerificationError, InvalidHashError):
        return False


# --- Cifrado del secreto TOTP ---

MENSAJE_CLAVE = (
    "Falta APP_ENCRYPTION_KEY o no es una clave Fernet válida. Agregala al .env; se genera con:\n"
    '    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def _fernet() -> Fernet:
    clave = get_settings().app_encryption_key.strip()
    try:
        return Fernet(clave)
    except (ValueError, TypeError) as e:
        raise ErrorConfiguracion(MENSAJE_CLAVE) from e


def verificar_configuracion() -> None:
    """Se llama al arrancar la app: falla con un mensaje claro si falta la clave de cifrado."""
    _fernet()


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(texto: str) -> str:
    try:
        return _fernet().decrypt(texto.encode()).decode()
    except InvalidToken as e:
        raise ErrorConfiguracion("No se pudo descifrar el secreto del doble factor: ¿cambió APP_ENCRYPTION_KEY?") from e


# --- TOTP ---

def nuevo_secreto_totp() -> str:
    return pyotp.random_base32()


def uri_totp(secreto: str, email: str) -> str:
    return pyotp.TOTP(secreto).provisioning_uri(name=email, issuer_name=EMISOR_TOTP)


def verificar_totp(secreto: str, codigo: str, ultimo_paso: int | None, ahora: float | None = None) -> int | None:
    """Verifica un código de 6 dígitos con tolerancia de ±1 ventana de 30 s.

    Devuelve el paso (número de ventana) que coincidió, o None si el código no sirve.
    Un paso igual o anterior al último usado se rechaza: así un código no se puede usar dos veces.
    """
    codigo = codigo.replace(" ", "")
    if len(codigo) != 6 or not codigo.isdigit():
        return None
    totp = pyotp.TOTP(secreto)
    paso_actual = int((time.time() if ahora is None else ahora) // totp.interval)
    for paso in (paso_actual - 1, paso_actual, paso_actual + 1):
        if hmac.compare_digest(totp.at(paso * totp.interval), codigo):
            if ultimo_paso is not None and paso <= ultimo_paso:
                return None
            return paso
    return None


# --- Códigos de recuperación y tokens ---

def nuevos_codigos_recuperacion() -> list[str]:
    """Diez códigos con el formato xxxx-xxxx-xxxx (unos 59 bits de azar cada uno)."""
    codigos = []
    for _ in range(CANTIDAD_CODIGOS_RECUPERACION):
        c = "".join(secrets.choice(ALFABETO_RECUPERACION) for _ in range(12))
        codigos.append(f"{c[:4]}-{c[4:8]}-{c[8:]}")
    return codigos


def normalizar_codigo_recuperacion(codigo: str) -> str:
    return "".join(ch for ch in codigo.lower() if ch.isalnum())


def hash_codigo_recuperacion(codigo: str) -> str:
    return hashlib.sha256(normalizar_codigo_recuperacion(codigo).encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
