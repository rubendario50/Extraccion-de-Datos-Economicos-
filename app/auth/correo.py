"""Envío del código de ingreso (y del aviso de cuenta ya existente) por email (SMTP con STARTTLS; pensado para Gmail con contraseña de aplicación).

Si SMTP_USER o SMTP_PASSWORD están vacíos (desarrollo), no se manda nada: el código se escribe en el
registro con un aviso, para poder probar el ingreso en la PC.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from markupsafe import escape

from app.config import get_settings

log = logging.getLogger(__name__)

ASUNTO = "Tu código de ingreso - Datos Económicos"
ASUNTO_CUENTA_EXISTENTE = "Ya tenés una cuenta - Datos Económicos"
NOMBRE_REMITENTE = "Datos Económicos"
ESPERA_SMTP = 15  # segundos


class ErrorCorreo(RuntimeError):
    """No se pudo mandar el correo. El detalle queda en el registro, no se le muestra al usuario."""


def _encabezados(asunto: str, destino: str, remitente: str) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = remitente if "<" in remitente else formataddr((NOMBRE_REMITENTE, remitente))
    mensaje["To"] = destino
    return mensaje


def armar_mensaje(destino: str, nombre: str, codigo: str, minutos: int, remitente: str) -> EmailMessage:
    mensaje = _encabezados(ASUNTO, destino, remitente)
    mensaje.set_content(
        f"Hola, {nombre}:\n\n"
        f"Tu código para entrar a Datos Económicos es:\n\n"
        f"    {codigo}\n\n"
        f"Vence en {minutos} minutos y sirve una sola vez.\n\n"
        f"Si no fuiste vos, ignorá este correo.\n"
    )
    mensaje.add_alternative(
        f"""<!doctype html>
<html lang="es">
<body style="font-family: system-ui, sans-serif; color: #0b1220; line-height: 1.5;">
  <p>Hola, {escape(nombre)}:</p>
  <p>Tu código para entrar a Datos Económicos es:</p>
  <p style="font-family: ui-monospace, monospace; font-size: 28px; font-weight: 600; letter-spacing: 0.15em;">{codigo}</p>
  <p>Vence en {minutos} minutos y sirve una sola vez.</p>
  <p style="color: #586379;">Si no fuiste vos, ignorá este correo.</p>
</body>
</html>
""",
        subtype="html",
    )
    return mensaje


def armar_aviso_cuenta_existente(destino: str, nombre: str, url_ingreso: str, remitente: str) -> EmailMessage:
    """Correo para quien intentó registrarse con un email que ya tiene cuenta (en lugar del código)."""
    mensaje = _encabezados(ASUNTO_CUENTA_EXISTENTE, destino, remitente)
    mensaje.set_content(
        f"Hola, {nombre}:\n\n"
        f"Alguien intentó crear una cuenta en Datos Económicos con este email, pero ya tenés una.\n\n"
        f"Para entrar, usá tu contraseña (o «Entrar con Google», si entrás así) en:\n\n"
        f"    {url_ingreso}\n\n"
        f"Si no fuiste vos, ignorá este correo: tu cuenta sigue igual.\n"
    )
    mensaje.add_alternative(
        f"""<!doctype html>
<html lang="es">
<body style="font-family: system-ui, sans-serif; color: #0b1220; line-height: 1.5;">
  <p>Hola, {escape(nombre)}:</p>
  <p>Alguien intentó crear una cuenta en Datos Económicos con este email, pero ya tenés una.</p>
  <p>Para entrar, usá tu contraseña (o «Entrar con Google», si entrás así) en
     <a href="{escape(url_ingreso)}">{escape(url_ingreso)}</a>.</p>
  <p style="color: #586379;">Si no fuiste vos, ignorá este correo: tu cuenta sigue igual.</p>
</body>
</html>
""",
        subtype="html",
    )
    return mensaje


def enviar_codigo(destino: str, nombre: str, codigo: str, minutos: int) -> None:
    """Manda el código a `destino`. Lanza ErrorCorreo si el servidor SMTP falla."""
    ajustes = get_settings()
    if not ajustes.smtp_user or not ajustes.smtp_password:
        log.warning("Correo sin configurar: código para %s: %s", destino, codigo)
        return
    _mandar(armar_mensaje(destino, nombre, codigo, minutos, ajustes.smtp_from or ajustes.smtp_user), destino)


def enviar_aviso_cuenta_existente(destino: str, nombre: str) -> None:
    """Avisa a `destino` que ya tiene cuenta. Lanza ErrorCorreo si el servidor SMTP falla."""
    ajustes = get_settings()
    url_ingreso = ajustes.base_url.rstrip("/") + "/login"
    if not ajustes.smtp_user or not ajustes.smtp_password:
        log.warning("Correo sin configurar: aviso de cuenta existente para %s", destino)
        return
    remitente = ajustes.smtp_from or ajustes.smtp_user
    _mandar(armar_aviso_cuenta_existente(destino, nombre, url_ingreso, remitente), destino)


def _mandar(mensaje: EmailMessage, destino: str) -> None:
    ajustes = get_settings()
    try:
        with smtplib.SMTP(ajustes.smtp_host, ajustes.smtp_port, timeout=ESPERA_SMTP) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(ajustes.smtp_user, ajustes.smtp_password)
            smtp.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as e:  # OSError: sin conexión, tiempo agotado, certificado...
        log.error("No se pudo mandar el código o el aviso a %s por %s:%s", destino, ajustes.smtp_host, ajustes.smtp_port,
                  exc_info=True)
        raise ErrorCorreo("No se pudo mandar el correo.") from e
