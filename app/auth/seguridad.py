"""Piezas criptográficas: contraseñas (Argon2), código de ingreso por email y tokens."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

LARGO_MINIMO_PASSWORD = 12
LARGO_MAXIMO_PASSWORD = 256

_hasher = PasswordHasher()
# Hash de una contraseña cualquiera: se verifica contra él cuando el email no existe,
# para que el login tarde lo mismo y no delate qué emails tienen cuenta.
_HASH_FICTICIO = _hasher.hash("contraseña-ficticia-para-igualar-tiempos")


# --- Contraseñas ---

def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(hash_guardado: str | None, password: str) -> bool:
    try:
        return _hasher.verify(hash_guardado or _HASH_FICTICIO, password) and hash_guardado is not None
    except (VerificationError, InvalidHashError):
        return False


# --- Código de ingreso por email ---

def nuevo_codigo_email() -> str:
    """Seis dígitos al azar (con `secrets`, no con `random`)."""
    return f"{secrets.randbelow(10**6):06d}"


def hash_codigo_email(usuario_id: int, codigo: str) -> str:
    """HMAC-SHA256 con SECRET_KEY: con solo la base no se pueden probar el millón de códigos posibles."""
    clave = get_settings().secret_key.encode()
    return hmac.new(clave, f"{usuario_id}:{codigo}".encode(), hashlib.sha256).hexdigest()


def codigo_email_coincide(hash_guardado: str, usuario_id: int, codigo: str) -> bool:
    return hmac.compare_digest(hash_guardado, hash_codigo_email(usuario_id, codigo))


# --- Tokens ---

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
