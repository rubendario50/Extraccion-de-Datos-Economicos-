"""Reglas de las cuentas: registro, login con bloqueo por intentos y doble factor por email."""

import math
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import correo, seguridad
from app.auth.sesiones import ahora, con_zona
from app.config import get_settings
from app.models import CodigoEmail, Sesion, Usuario

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
    """Devuelve los errores por campo (vacío si todo está bien).

    Que el email ya tenga cuenta no es un error: la pantalla no lo revela (ver `registrar_repetido`).
    """
    errores = {}
    if not datos.nombre.strip():
        errores["nombre"] = "Escribí tu nombre."
    elif len(datos.nombre.strip()) > 100:
        errores["nombre"] = "El nombre puede tener hasta 100 caracteres."
    email = normalizar_email(datos.email)
    if not email_valido(email):
        errores["email"] = "Escribí un email válido, por ejemplo nombre@dominio.com."
    if len(datos.password) < seguridad.LARGO_MINIMO_PASSWORD:
        errores["password"] = f"La contraseña tiene que tener al menos {seguridad.LARGO_MINIMO_PASSWORD} caracteres."
    elif len(datos.password) > seguridad.LARGO_MAXIMO_PASSWORD:
        errores["password"] = f"La contraseña puede tener hasta {seguridad.LARGO_MAXIMO_PASSWORD} caracteres."
    elif datos.password != datos.confirmacion:
        errores["confirmacion"] = "Las contraseñas no coinciden."
    return errores


def buscar_por_email(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == normalizar_email(email)))


ESPERA_AVISO_REGISTRO = timedelta(minutes=15)
CONSERVAR_REGISTROS_REPETIDOS = timedelta(days=1)


def registrar_repetido(db: Session, datos: DatosRegistro, cuenta: Usuario) -> Usuario:
    """Registro con el email de `cuenta`, que ya existe. Para no revelarlo, se crea un usuario «pendiente»
    que recorre lo mismo que uno nuevo (sesión pendiente, códigos, intentos, bloqueo y límites de envío)
    pero que ningún código completa; a la cuenta real, que no se toca, le llega un aviso en lugar del código.
    """
    seguridad.hashear_password(datos.password)  # lo mismo que tarda un registro nuevo; no se guarda
    limite = ahora() - CONSERVAR_REGISTROS_REPETIDOS
    viejos = list(db.scalars(
        select(Usuario.id).where(Usuario.cuenta_de_id.is_not(None), Usuario.creado_en < limite)
    ))
    if viejos:
        db.execute(delete(Sesion).where(Sesion.usuario_id.in_(viejos)))
        db.execute(delete(CodigoEmail).where(CodigoEmail.usuario_id.in_(viejos)))
        db.execute(delete(Usuario).where(Usuario.id.in_(viejos)))
    pendiente = Usuario(
        email=f"pendiente-{secrets.token_hex(16)}@registro.invalid",  # nadie puede ingresar con este email
        nombre=datos.nombre.strip(),
        password_hash=None,
        rol="usuario",
        cuenta_de_id=cuenta.id,
    )
    db.add(pendiente)
    db.commit()
    return pendiente


def _sin_esperar(nombre: str, *args) -> None:
    """Manda un correo después de responder. Si falla, ya quedó en el registro (log) de `correo`."""
    try:
        getattr(correo, nombre)(*args)
    except correo.ErrorCorreo:
        pass


def _avisar_cuenta_existente(db: Session, cuenta: Usuario, tareas: BackgroundTasks | None) -> None:
    """Aviso de «ya tenés cuenta» a `cuenta`, como máximo uno cada ESPERA_AVISO_REGISTRO, para que el
    registro no sirva para inundar un buzón (si ya se mandó uno hace menos, no se manda nada)."""
    momento = ahora()
    anterior = con_zona(cuenta.ultimo_aviso_registro)
    if anterior is not None and momento - anterior < ESPERA_AVISO_REGISTRO:
        return
    cuenta.ultimo_aviso_registro = momento
    db.commit()
    if tareas is not None:
        tareas.add_task(_sin_esperar, "enviar_aviso_cuenta_existente", cuenta.email, cuenta.nombre)
    else:
        _sin_esperar("enviar_aviso_cuenta_existente", cuenta.email, cuenta.nombre)


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
    """Fallo del código del email. Este contador no lo reinicia la contraseña."""
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


# --- Doble factor: código por email ---

VIGENCIA_CODIGO = timedelta(minutes=10)
ESPERA_REENVIO = timedelta(seconds=60)
MAX_ENVIOS_POR_HORA = 5
CONSERVAR_CODIGOS = timedelta(days=1)  # las filas más viejas se borran al mandar uno nuevo

MENSAJE_CODIGO = "El código no es correcto. Revisalo en el correo o pedí uno nuevo."
MENSAJE_SIN_CODIGO = "Ese código venció o ya se usó. Pedí uno nuevo con «Reenviar código»."
MENSAJE_ENVIO = (
    "No pudimos mandarte el código por email. Probá de nuevo en unos minutos con «Reenviar código»."
)


class EsperaReenvio(ErrorCuenta):
    """Se pidió otro código antes de que pasara ESPERA_REENVIO desde el anterior."""


class LimiteEnvios(ErrorCuenta):
    """Se mandaron MAX_ENVIOS_POR_HORA códigos en la última hora."""


def _codigos(db: Session, usuario: Usuario) -> list[CodigoEmail]:
    """Los códigos del usuario, del más nuevo al más viejo."""
    return list(db.scalars(
        select(CodigoEmail).where(CodigoEmail.usuario_id == usuario.id).order_by(CodigoEmail.id.desc())
    ))


def _vigente(codigos: list[CodigoEmail], momento) -> CodigoEmail | None:
    """Solo vale el último código, si no se usó ni venció."""
    if codigos and codigos[0].usado_en is None and con_zona(codigos[0].expira_en) > momento:
        return codigos[0]
    return None


def enviar_codigo(db: Session, usuario: Usuario, tareas: BackgroundTasks | None = None) -> None:
    """Genera un código nuevo (el anterior deja de valer) y lo manda al email del usuario.

    Lanza EsperaReenvio o LimiteEnvios si hay que esperar, y ErrorCuenta si la cuenta está bloqueada
    o no se pudo mandar el correo.

    Con `tareas`, el correo sale después de responder: la respuesta no espera al servidor SMTP (y un
    error de envío solo queda en el registro). En un registro repetido el código no se manda a nadie:
    a la cuenta real le llega el aviso de que ya tiene cuenta.
    """
    if minutos_de_bloqueo(usuario):
        raise ErrorCuenta(mensaje_bloqueo(usuario))
    momento = ahora()
    codigos = _codigos(db, usuario)
    vigente = _vigente(codigos, momento)
    if vigente is not None:
        falta = math.ceil((con_zona(vigente.creado_en) + ESPERA_REENVIO - momento).total_seconds())
        if falta > 0:
            raise EsperaReenvio(f"Esperá {falta} {'segundo' if falta == 1 else 'segundos'} antes de pedir otro código.")
    hace_una_hora = momento - timedelta(hours=1)
    recientes = [c for c in codigos if con_zona(c.creado_en) > hace_una_hora]
    if len(recientes) >= MAX_ENVIOS_POR_HORA:
        minutos = max(1, -(-int((con_zona(recientes[-1].creado_en) - hace_una_hora).total_seconds()) // 60))
        raise LimiteEnvios(
            f"Ya te mandamos {MAX_ENVIOS_POR_HORA} códigos en la última hora. "
            f"Probá de nuevo en {minutos} {'minuto' if minutos == 1 else 'minutos'}."
        )
    for c in codigos:
        if con_zona(c.creado_en) < momento - CONSERVAR_CODIGOS:
            db.delete(c)
        elif c.usado_en is None:
            c.usado_en = momento  # anulado: solo vale el nuevo
    codigo = seguridad.nuevo_codigo_email()
    fila = CodigoEmail(
        usuario_id=usuario.id,
        hash=seguridad.hash_codigo_email(usuario.id, codigo),
        creado_en=momento,
        expira_en=momento + VIGENCIA_CODIGO,
    )
    db.add(fila)
    db.commit()
    if usuario.cuenta_de is not None:
        _avisar_cuenta_existente(db, usuario.cuenta_de, tareas)
        return
    minutos = int(VIGENCIA_CODIGO.total_seconds() // 60)
    if tareas is not None:
        tareas.add_task(_sin_esperar, "enviar_codigo", usuario.email, usuario.nombre, codigo, minutos)
        return
    try:
        correo.enviar_codigo(usuario.email, usuario.nombre, codigo, minutos)
    except correo.ErrorCorreo:
        fila.usado_en = ahora()  # nunca llegó: no sirve ni frena el próximo pedido (sí cuenta para el límite)
        db.commit()
        raise ErrorCuenta(MENSAJE_ENVIO) from None


def iniciar_segundo_factor(db: Session, usuario: Usuario, tareas: BackgroundTasks | None = None) -> str | None:
    """Al entrar con contraseña o con Google: manda el código. Devuelve un aviso (clave) si no se pudo.

    Si hace menos de un minuto ya se mandó uno que sigue vigente, no se manda otro: vale ese.
    """
    try:
        enviar_codigo(db, usuario, tareas)
    except EsperaReenvio:
        return None
    except LimiteEnvios:
        return "limite"
    except ErrorCuenta:
        # Cuenta bloqueada (la pantalla del código lo explica) o falló el correo.
        return None if minutos_de_bloqueo(usuario) else "envio"
    return None


def verificar_codigo(db: Session, usuario: Usuario, codigo: str) -> None:
    """Acepta el último código mandado, una sola vez y dentro de su vigencia. Si no, lanza ErrorCuenta."""
    if minutos_de_bloqueo(usuario):
        raise ErrorCuenta(mensaje_bloqueo(usuario))
    momento = ahora()
    vigente = _vigente(_codigos(db, usuario), momento)
    if vigente is None:
        # Sin un código vigente no hay nada que adivinar: no cuenta como intento fallido.
        raise ErrorCuenta(MENSAJE_SIN_CODIGO)
    limpio = "".join(codigo.split())
    # Un registro repetido (cuenta_de_id) cuenta los intentos igual, pero ningún código lo completa.
    if (usuario.cuenta_de_id is None and len(limpio) == 6 and limpio.isdigit()
            and seguridad.codigo_email_coincide(vigente.hash, usuario.id, limpio)):
        vigente.usado_en = momento
        db.commit()
        return
    registrar_fallo_2fa(db, usuario)
    raise ErrorCuenta(mensaje_bloqueo(usuario) if minutos_de_bloqueo(usuario) else MENSAJE_CODIGO)
