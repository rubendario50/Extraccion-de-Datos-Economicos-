"""Casos borde y de seguridad del doble factor por código enviado al email (escritos por el tester)."""

import logging
import smtplib

import pytest
from sqlalchemy import select

from app.auth import correo, cuentas
from app.auth.correo import enviar_codigo as enviar_real
from app.auth.sesiones import COOKIE_SESION
from app.config import get_settings
from app.models import CodigoEmail, Sesion, Usuario
from tests.ayudas import PASSWORD, csrf_de, ingresar, registrar, reenviar, verificar
from tests.test_google import datos_google


def usuario(db, email="ana@example.com") -> Usuario:
    return db.scalar(select(Usuario).where(Usuario.email == email))


def _sin_acceso_a_lo_protegido(cliente):
    assert cliente.get("/").headers["location"] == "/2fa/verificar"
    r = cliente.get("/api/series", params={"indicador": "PBI"})
    assert r.status_code == 401
    assert cliente.get("/login").headers["location"] == "/2fa/verificar"
    assert cliente.get("/registro").headers["location"] == "/2fa/verificar"


# --- Saltar el segundo factor ---

def test_sesion_pendiente_por_login_no_entra(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    _sin_acceso_a_lo_protegido(cliente_web)


def test_sesion_pendiente_por_registro_no_entra(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    _sin_acceso_a_lo_protegido(cliente_web)


def test_sesion_pendiente_por_google_no_entra(cliente_web, sesion_con_semillas, buzon, monkeypatch):
    from app.auth import google
    from tests.test_google import GoogleFalso

    monkeypatch.setattr(get_settings(), "google_client_id", "x.apps.googleusercontent.com")
    falso = GoogleFalso(userinfo=datos_google())
    monkeypatch.setattr(google, "cliente_google", lambda: falso)
    r = cliente_web.get("/auth/google/callback")
    assert r.headers["location"] == "/2fa/verificar"
    _sin_acceso_a_lo_protegido(cliente_web)
    assert len(buzon.enviados) == 1 and buzon.enviados[0]["destino"] == "ana@gmail.com"


def test_token_pendiente_no_sirve_despues_de_completar(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    viejo = cliente_web.cookies.get(COOKIE_SESION)
    assert verificar(cliente_web, buzon.ultimo()).headers["location"] == "/"
    nuevo = cliente_web.cookies.get(COOKIE_SESION)
    assert nuevo and nuevo != viejo
    cliente_web.cookies.clear()
    cliente_web.cookies.set(COOKIE_SESION, viejo)
    assert cliente_web.get("/").headers["location"] == "/login"


# --- Código: reuso, otro usuario, bloqueo ---

def test_codigo_de_otro_usuario_no_sirve(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web, email="ana@example.com")
    codigo_ana = buzon.ultimo("ana@example.com")
    cliente_web.cookies.clear()
    registrar(cliente_web, email="beto@example.com", nombre="Beto")
    if buzon.ultimo("beto@example.com") == codigo_ana:
        pytest.skip("coincidencia de códigos al azar (1 en un millón)")
    r = verificar(cliente_web, codigo_ana)
    assert r.status_code == 400
    assert usuario(sesion_con_semillas, "beto@example.com").intentos_2fa == 1


def test_codigo_correcto_no_entra_si_la_cuenta_quedo_bloqueada(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    bueno = buzon.ultimo()
    malo = "000000" if bueno != "000000" else "111111"
    for _ in range(cuentas.MAX_INTENTOS):
        verificar(cliente_web, malo)
    r = verificar(cliente_web, bueno)
    assert r.status_code == 400 and "bloqueamos" in r.text
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"
    # También queda bloqueado el login con la contraseña correcta.
    cliente_web.cookies.clear()
    r = ingresar(cliente_web)
    assert r.status_code == 400 and "bloqueamos" in r.text


def test_reenviar_con_cuenta_bloqueada_no_manda(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    for _ in range(cuentas.MAX_INTENTOS):
        verificar(cliente_web, "abcdef")
    antes = len(buzon.enviados)
    r = reenviar(cliente_web)
    assert r.status_code == 400 and "bloqueamos" in r.text
    assert len(buzon.enviados) == antes


@pytest.mark.parametrize("codigo", ["", "12345", "1234567", "abcdef", "١٢٣٤٥٦", "12 34 5", "x" * 5000])
def test_entradas_raras_cuentan_como_fallo_y_no_rompen(cliente_web, sesion_con_semillas, buzon, codigo):
    registrar(cliente_web)
    r = verificar(cliente_web, codigo)
    assert r.status_code == 400
    assert usuario(sesion_con_semillas).intentos_2fa == 1


def test_intentos_sin_codigo_vigente_no_abren_nada(cliente_web, sesion_con_semillas, buzon):
    """Si el código venció, ningún valor entra (ni el viejo) y tampoco se cuenta el intento."""
    registrar(cliente_web)
    viejo = buzon.ultimo()
    for c in sesion_con_semillas.scalars(select(CodigoEmail)):
        c.usado_en = c.creado_en  # anulado
    sesion_con_semillas.commit()
    for intento in (viejo, "000000", "999999"):
        r = verificar(cliente_web, intento)
        assert r.status_code == 400 and "venció o ya se usó" in r.text
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"


# --- Límite de envíos por cuenta (no por sesión) ---

def test_limite_por_hora_es_por_cuenta_aunque_cambie_la_sesion(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    db = sesion_con_semillas
    for _ in range(cuentas.MAX_ENVIOS_POR_HORA + 3):
        # Esquivar la espera de 60 s envejeciendo los códigos 61 s, pero manteniéndolos en la última hora.
        for c in db.scalars(select(CodigoEmail)):
            c.creado_en = c.creado_en.replace() - cuentas.ESPERA_REENVIO - cuentas.ESPERA_REENVIO / 60
        db.commit()
        cliente_web.cookies.clear()
        ingresar(cliente_web)
    assert len(buzon.enviados) == cuentas.MAX_ENVIOS_POR_HORA
    r = reenviar(cliente_web)
    assert r.status_code == 429


# --- Registro: no se filtran el código ni la contraseña SMTP ---

class SmtpOk:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m):
        pass


class SmtpAuthFalla(SmtpOk):
    def login(self, u, p):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")


@pytest.mark.parametrize("servidor", [SmtpOk, SmtpAuthFalla])
def test_con_smtp_configurado_no_se_registran_codigo_ni_password(
    monkeypatch, caplog, cliente_web, sesion_con_semillas, codigos_fijos, servidor
):
    monkeypatch.setattr(correo, "enviar_codigo", enviar_real)
    monkeypatch.setattr(correo.smtplib, "SMTP", servidor)
    monkeypatch.setattr(get_settings(), "smtp_user", "remitente@gmail.com")
    monkeypatch.setattr(get_settings(), "smtp_password", "clave-secreta-app")
    with caplog.at_level(logging.DEBUG):
        registrar(cliente_web)
    texto = caplog.text + "".join(str(r.exc_info) for r in caplog.records if r.exc_info)
    assert "111111" not in texto
    assert "clave-secreta-app" not in texto
    if servidor is SmtpAuthFalla:
        assert any(r.levelname == "ERROR" for r in caplog.records)
        assert sesion_con_semillas.scalar(select(CodigoEmail)).usado_en is not None  # anulado


@pytest.fixture
def codigos_fijos(monkeypatch):
    from app.auth import seguridad

    monkeypatch.setattr(seguridad, "nuevo_codigo_email", lambda: "111111")


# --- Enumeración ---

def test_login_no_delata_emails_ni_manda_correo(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    cliente_web.cookies.clear()
    antes = len(buzon.enviados)
    sesiones_antes = len(list(sesion_con_semillas.scalars(select(Sesion))))
    r1 = ingresar(cliente_web, email="nadie@example.com")
    r2 = ingresar(cliente_web, password=PASSWORD + "x")
    assert r1.status_code == r2.status_code == 400
    assert cuentas.MENSAJE_LOGIN in r1.text and cuentas.MENSAJE_LOGIN in r2.text
    assert len(buzon.enviados) == antes
    assert len(list(sesion_con_semillas.scalars(select(Sesion)))) == sesiones_antes
