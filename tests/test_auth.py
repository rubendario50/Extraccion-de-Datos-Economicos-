from datetime import timedelta
from itertools import cycle

import pytest
from sqlalchemy import select

from app.auth import correo, cuentas, seguridad
from app.auth.correo import enviar_codigo as enviar_real  # el de verdad: el buzón falso lo reemplaza en cada test
from app.auth.dependencias import requiere_admin
from app.auth.sesiones import COOKIE_SESION, con_zona
from app.config import get_settings
from app.models import CodigoEmail, Sesion, Usuario
from tests.ayudas import PASSWORD, completar_2fa, csrf_de, ingresar, reenviar, registrar, sin_ocultos, verificar


def usuario(db, email="ana@example.com") -> Usuario:
    return db.scalar(select(Usuario).where(Usuario.email == email))


def envejecer(db, **tiempo) -> None:
    """Corre hacia atrás la fecha de todos los códigos guardados, como si hubiera pasado ese tiempo."""
    delta = timedelta(**tiempo)
    for c in db.scalars(select(CodigoEmail)):
        c.creado_en = con_zona(c.creado_en) - delta
        c.expira_en = con_zona(c.expira_en) - delta
    db.commit()


@pytest.fixture
def codigos_fijos(monkeypatch):
    """Códigos predecibles (111111, 222222, ...) para distinguir el viejo del nuevo."""
    fuente = cycle(f"{d}" * 6 for d in range(1, 10))
    monkeypatch.setattr(seguridad, "nuevo_codigo_email", lambda: next(fuente))


# --- Registro ---

def test_registro_valido(cliente_web, sesion_con_semillas, buzon):
    r = registrar(cliente_web, email="  Ana@Example.COM ")
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar"
    u = usuario(sesion_con_semillas)
    assert u is not None and u.nombre == "Ana Pérez" and u.rol == "usuario"
    assert u.password_hash.startswith("$argon2") and PASSWORD not in u.password_hash
    # Queda con una sesión sin doble factor y con el código mandado al email con el que se registró.
    s = sesion_con_semillas.scalar(select(Sesion))
    assert s.usuario_id == u.id and not s.mfa_ok
    assert cliente_web.cookies[COOKIE_SESION] and s.token_hash == seguridad.hash_token(cliente_web.cookies[COOKIE_SESION])
    assert [(m["destino"], m["nombre"], m["minutos"]) for m in buzon.enviados] == [("ana@example.com", "Ana Pérez", 10)]


def test_registro_contrasena_corta(cliente_web, sesion_con_semillas):
    r = registrar(cliente_web, password="corta123")
    assert r.status_code == 400
    assert "al menos 12 caracteres" in r.text
    assert usuario(sesion_con_semillas) is None


def test_registro_confirmacion_distinta(cliente_web, sesion_con_semillas):
    r = registrar(cliente_web, confirmacion="otra frase bastante larga")
    assert r.status_code == 400 and "no coinciden" in r.text
    assert usuario(sesion_con_semillas) is None


def test_registro_email_repetido(cliente_web, sesion_con_semillas):
    registrar(cliente_web)
    cliente_web.cookies.clear()
    r = registrar(cliente_web, email="ANA@example.com")
    assert r.status_code == 400
    assert "Ya hay una cuenta con ese email" in r.text
    assert len(sesion_con_semillas.scalars(select(Usuario)).all()) == 1


def test_registro_admin(cliente_web, sesion_con_semillas, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_email", "Ruben@Example.com")
    registrar(cliente_web, email="ruben@example.com")
    assert usuario(sesion_con_semillas, "ruben@example.com").rol == "admin"


def test_requiere_admin():
    assert requiere_admin(Usuario(rol="admin")).rol == "admin"
    with pytest.raises(Exception) as e:
        requiere_admin(Usuario(rol="usuario"))
    assert e.value.status_code == 403


# --- Login ---

@pytest.fixture
def cuenta(cliente_web, sesion_con_semillas, buzon):
    """Cuenta registrada que ya completó el doble factor una vez, con la sesión cerrada."""
    registrar(cliente_web)
    completar_2fa(cliente_web, buzon)
    cliente_web.cookies.clear()


def test_login_correcto(cliente_web, sesion_con_semillas, cuenta, buzon):
    r = ingresar(cliente_web, email="ANA@example.com ")
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar"
    assert not sesion_con_semillas.scalar(select(Sesion).order_by(Sesion.id.desc())).mfa_ok
    # Un código nuevo por cada ingreso con la contraseña.
    assert len(buzon.enviados) == 2 and buzon.enviados[-1]["destino"] == "ana@example.com"


@pytest.mark.parametrize(("email", "password"), [("ana@example.com", "contraseña equivocada"), ("nadie@example.com", PASSWORD)])
def test_login_incorrecto_mensaje_generico(cliente_web, cuenta, buzon, email, password):
    r = ingresar(cliente_web, email=email, password=password)
    assert r.status_code == 400
    assert "El email o la contraseña no son correctos." in r.text
    assert COOKIE_SESION not in cliente_web.cookies
    assert len(buzon.enviados) == 1  # solo el del registro: sin contraseña correcta no se manda código


def test_bloqueo_tras_5_fallos(cliente_web, sesion_con_semillas, cuenta):
    for _ in range(4):
        assert "no son correctos" in ingresar(cliente_web, password="mal mal mal mal").text
    r = ingresar(cliente_web, password="mal mal mal mal")
    assert "bloqueamos el ingreso" in r.text and "15 minutos" in r.text
    # Con la contraseña correcta tampoco entra mientras dure el bloqueo.
    r = ingresar(cliente_web)
    assert r.status_code == 400 and "bloqueamos el ingreso" in r.text
    u = usuario(sesion_con_semillas)
    assert u.bloqueado_hasta is not None
    # Pasado el bloqueo, entra.
    u.bloqueado_hasta = None
    sesion_con_semillas.commit()
    assert ingresar(cliente_web).status_code == 303


def test_bloqueo_por_codigos_2fa(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)
    correcto = buzon.ultimo()
    malo = "000000" if correcto != "000000" else "999999"
    for _ in range(4):
        r = verificar(cliente_web, malo)
        assert r.status_code == 400 and "no es correcto" in r.text
    r = verificar(cliente_web, malo)
    assert r.status_code == 400 and "bloqueamos el ingreso" in r.text and "15 minutos" in r.text
    # Bloqueada: ni el código correcto entra, y la pantalla lo avisa.
    r = verificar(cliente_web, correcto)
    assert r.status_code == 400 and "bloqueamos" in r.text
    assert "bloqueamos" in cliente_web.get("/2fa/verificar").text
    # Tampoco se puede pedir otro código mientras dure el bloqueo.
    envejecer(sesion_con_semillas, seconds=61)
    r = reenviar(cliente_web)
    assert r.status_code == 400 and "bloqueamos" in r.text
    assert len(buzon.enviados) == 2


# --- Doble factor por email ---

def test_flujo_completo_2fa(cliente_web, sesion_con_semillas, buzon):
    registrar(cliente_web)
    # Sin el doble factor no se entra al panel.
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"

    pagina = cliente_web.get("/2fa/verificar")
    assert pagina.status_code == 200 and "ana@example.com" in pagina.text and "10 minutos" in pagina.text
    assert 'autocomplete="one-time-code"' in pagina.text and 'inputmode="numeric"' in pagina.text
    assert "Reenviar código" in pagina.text
    # Nada de QR ni códigos de recuperación.
    assert "<svg class=\"qr" not in pagina.text and "recuperación" not in pagina.text

    codigo = buzon.ultimo()
    assert len(codigo) == 6 and codigo.isdigit()
    # En la base solo queda el hash del código (HMAC), nunca el código.
    guardado = sesion_con_semillas.scalar(select(CodigoEmail))
    assert guardado.hash != codigo and codigo not in guardado.hash and len(guardado.hash) == 64
    assert guardado.hash == seguridad.hash_codigo_email(guardado.usuario_id, codigo)
    vence = con_zona(guardado.expira_en) - con_zona(guardado.creado_en)
    assert vence == timedelta(minutes=10)

    # Código equivocado.
    malo = "000000" if codigo != "000000" else "999999"
    r = cliente_web.post("/2fa/verificar", data={"codigo": malo, "csrf": csrf_de(pagina.text)})
    assert r.status_code == 400 and "no es correcto" in r.text and 'aria-invalid="true"' in r.text

    token_antes = cliente_web.cookies[COOKIE_SESION]
    r = cliente_web.post("/2fa/verificar", data={"codigo": codigo, "csrf": csrf_de(pagina.text)})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert sesion_con_semillas.scalar(select(CodigoEmail)).usado_en is not None
    # El token de sesión rota al completar el doble factor; el viejo ya no sirve.
    assert cliente_web.cookies[COOKIE_SESION] != token_antes
    assert cliente_web.get("/").status_code == 200
    assert usuario(sesion_con_semillas).ultimo_ingreso is not None
    viejo = cliente_web.cookies[COOKIE_SESION]
    cliente_web.cookies.set(COOKIE_SESION, token_antes)
    assert cliente_web.get("/").headers["location"] == "/login"
    cliente_web.cookies.set(COOKIE_SESION, viejo)
    # Con el doble factor hecho, la pantalla del código lleva al panel.
    assert cliente_web.get("/2fa/verificar").headers["location"] == "/"


def test_ya_no_existe_la_configuracion_con_qr(cliente_web, sesion_con_semillas):
    registrar(cliente_web)
    assert cliente_web.get("/2fa/configurar").status_code in (404, 405)


def test_codigo_reusado(cliente_web, sesion_con_semillas, codigos_fijos, cuenta, buzon):
    ingresar(cliente_web)
    codigo = buzon.ultimo()
    assert verificar(cliente_web, codigo).status_code == 303
    # El mismo código en otro ingreso: rechazado (ya se usó, y además vale solo el nuevo).
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    assert buzon.ultimo() != codigo
    r = verificar(cliente_web, codigo)
    assert r.status_code == 400 and "no es correcto" in r.text
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"


def test_codigo_de_un_solo_uso(sesion_con_semillas, buzon):
    u = Usuario(email="ana@example.com", nombre="Ana")
    sesion_con_semillas.add(u)
    sesion_con_semillas.commit()
    cuentas.enviar_codigo(sesion_con_semillas, u)
    cuentas.verificar_codigo(sesion_con_semillas, u, buzon.ultimo())
    with pytest.raises(cuentas.ErrorCuenta, match="venció o ya se usó"):
        cuentas.verificar_codigo(sesion_con_semillas, u, buzon.ultimo())
    assert u.intentos_2fa == 0  # sin un código vigente no hay nada que adivinar


def test_codigo_vencido(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)
    envejecer(sesion_con_semillas, minutes=10, seconds=1)
    r = verificar(cliente_web, buzon.ultimo())
    assert r.status_code == 400 and "venció o ya se usó" in r.text and "Reenviar código" in r.text
    assert usuario(sesion_con_semillas).intentos_2fa == 0
    # Con uno nuevo, entra.
    assert reenviar(cliente_web).status_code == 303
    completar_2fa(cliente_web, buzon)


def test_codigo_casi_vencido_todavia_sirve(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)
    envejecer(sesion_con_semillas, minutes=9, seconds=50)
    completar_2fa(cliente_web, buzon)


def test_reenviar_invalida_el_anterior(cliente_web, sesion_con_semillas, codigos_fijos, cuenta, buzon):
    ingresar(cliente_web)
    viejo = buzon.ultimo()
    envejecer(sesion_con_semillas, seconds=61)
    r = reenviar(cliente_web)
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar?aviso=reenviado"
    assert "Te mandamos un código nuevo" in cliente_web.get(r.headers["location"]).text
    nuevo = buzon.ultimo()
    assert nuevo != viejo
    r = verificar(cliente_web, viejo)
    assert r.status_code == 400 and "no es correcto" in r.text
    assert verificar(cliente_web, nuevo).status_code == 303


def test_reenviar_antes_de_60_segundos(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)
    enviados = len(buzon.enviados)
    r = reenviar(cliente_web)
    assert r.status_code == 429 and "Esperá" in r.text and "segundos antes de pedir otro código" in r.text
    assert 'aria-invalid="true"' not in r.text  # el código escrito no tiene nada mal
    assert len(buzon.enviados) == enviados
    envejecer(sesion_con_semillas, seconds=30)
    assert reenviar(cliente_web).status_code == 429
    envejecer(sesion_con_semillas, seconds=31)
    assert reenviar(cliente_web).status_code == 303
    assert len(buzon.enviados) == enviados + 1


def test_reingresar_enseguida_no_manda_otro_codigo(cliente_web, sesion_con_semillas, cuenta, buzon):
    """Dos ingresos seguidos con la contraseña: el segundo no manda otro correo y sigue valiendo el primero."""
    ingresar(cliente_web)
    codigo = buzon.ultimo()
    cliente_web.cookies.clear()
    r = ingresar(cliente_web)
    assert r.headers["location"] == "/2fa/verificar"
    assert len(buzon.enviados) == 2
    assert verificar(cliente_web, codigo).status_code == 303


def test_limite_de_envios_por_hora(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)  # el registro y este: 2 envíos en la última hora
    for _ in range(cuentas.MAX_ENVIOS_POR_HORA - 2):
        envejecer(sesion_con_semillas, seconds=61)
        assert reenviar(cliente_web).status_code == 303
    assert len(buzon.enviados) == cuentas.MAX_ENVIOS_POR_HORA
    envejecer(sesion_con_semillas, seconds=61)
    r = reenviar(cliente_web)
    assert r.status_code == 429 and "en la última hora" in r.text
    # Al ingresar con la contraseña tampoco se manda: la pantalla del código lo explica.
    cliente_web.cookies.clear()
    r = ingresar(cliente_web)
    assert r.headers["location"] == "/2fa/verificar?aviso=limite"
    assert "en la última hora" in cliente_web.get(r.headers["location"]).text
    assert len(buzon.enviados) == cuentas.MAX_ENVIOS_POR_HORA
    # Pasada la hora, se puede pedir de nuevo.
    envejecer(sesion_con_semillas, hours=1)
    assert reenviar(cliente_web).status_code == 303
    completar_2fa(cliente_web, buzon)


def test_falla_el_envio_smtp(cliente_web, sesion_con_semillas, cuenta, buzon):
    buzon.falla = True
    r = ingresar(cliente_web)
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar?aviso=envio"
    pagina = sin_ocultos(cliente_web.get(r.headers["location"]).text)
    assert "No pudimos mandarte el código por email" in pagina
    assert "SMTP" not in pagina and "simulado" not in pagina  # el detalle del error no se muestra
    # El código que no llegó no sirve, y no obliga a esperar para pedir otro.
    assert sesion_con_semillas.scalars(select(CodigoEmail).order_by(CodigoEmail.id.desc())).first().usado_en is not None
    r = reenviar(cliente_web)
    assert r.status_code == 400 and "No pudimos mandarte el código" in r.text
    buzon.falla = False
    assert reenviar(cliente_web).status_code == 303
    completar_2fa(cliente_web, buzon)


def test_volver_a_poner_la_contrasena_no_reinicia_los_intentos_del_codigo(cliente_web, sesion_con_semillas, cuenta):
    """Con la contraseña correcta no se tiene que poder probar códigos sin límite (fuerza bruta del 2FA)."""
    ingresar(cliente_web)
    for _ in range(4):
        assert verificar(cliente_web, "x").status_code == 400
    # Se vuelve a ingresar con la contraseña y se sigue probando códigos.
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    r = verificar(cliente_web, "x")
    assert "bloqueamos" in r.text, "tras 5 códigos fallidos la cuenta debería quedar bloqueada"


def test_pedir_otro_codigo_no_reinicia_los_intentos(cliente_web, sesion_con_semillas, cuenta):
    ingresar(cliente_web)
    for _ in range(4):
        verificar(cliente_web, "x")
    envejecer(sesion_con_semillas, seconds=61)
    assert reenviar(cliente_web).status_code == 303
    assert "bloqueamos" in verificar(cliente_web, "x").text


def test_completar_el_2fa_reinicia_los_intentos(cliente_web, sesion_con_semillas, cuenta, buzon):
    ingresar(cliente_web)
    for _ in range(4):
        verificar(cliente_web, "x")
    assert usuario(sesion_con_semillas).intentos_2fa == 4
    completar_2fa(cliente_web, buzon)
    assert usuario(sesion_con_semillas).intentos_2fa == 0


def test_codigo_con_espacios(cliente_web, cuenta, buzon):
    ingresar(cliente_web)
    codigo = buzon.ultimo()
    assert verificar(cliente_web, f" {codigo[:3]} {codigo[3:]} ").status_code == 303


def test_codigo_vacio_en_verificar(cliente_web, cuenta):
    ingresar(cliente_web)
    r = verificar(cliente_web, "")
    assert r.status_code == 400 and "no es correcto" in r.text


@pytest.mark.parametrize("ruta", ["/2fa/verificar", "/2fa/reenviar"])
def test_csrf_en_pantallas_del_doble_factor(cliente_web, sesion_con_semillas, buzon, ruta):
    registrar(cliente_web)
    assert cliente_web.post(ruta, data={"codigo": "123456"}).status_code == 403
    assert cliente_web.post(ruta, data={"codigo": "123456", "csrf": "x"}).status_code == 403
    u = usuario(sesion_con_semillas)
    assert u.intentos_fallidos == 0 and u.intentos_2fa == 0
    assert len(buzon.enviados) == 1


def test_pantallas_del_codigo_sin_sesion(cliente_web):
    assert cliente_web.get("/2fa/verificar").headers["location"] == "/login"
    assert cliente_web.post("/2fa/reenviar", data={}).status_code in (303, 403)


def test_codigo_aleatorio_y_hash():
    codigos = {seguridad.nuevo_codigo_email() for _ in range(50)}
    assert all(len(c) == 6 and c.isdigit() for c in codigos) and len(codigos) > 40
    h = seguridad.hash_codigo_email(1, "123456")
    assert h != seguridad.hash_codigo_email(2, "123456")  # depende del usuario
    assert seguridad.codigo_email_coincide(h, 1, "123456")
    assert not seguridad.codigo_email_coincide(h, 1, "123457")


# --- Envío del correo ---

class SmtpFalso:
    """Reemplazo de smtplib.SMTP que guarda lo que se le pide."""

    instancias: list["SmtpFalso"] = []
    error: Exception | None = None

    def __init__(self, host, puerto, timeout=None):
        self.host, self.puerto, self.timeout = host, puerto, timeout
        self.pasos, self.mensajes = [], []
        SmtpFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.pasos.append("starttls")

    def login(self, usuario, password):
        self.pasos.append(("login", usuario, password))
        if SmtpFalso.error:
            raise SmtpFalso.error

    def send_message(self, mensaje):
        self.pasos.append("send")
        self.mensajes.append(mensaje)


@pytest.fixture
def smtp(monkeypatch, buzon):
    """El envío real (sin el buzón falso) contra un servidor SMTP simulado y con Gmail configurado."""
    SmtpFalso.instancias, SmtpFalso.error = [], None
    monkeypatch.setattr(correo, "enviar_codigo", enviar_real)
    monkeypatch.setattr(correo.smtplib, "SMTP", SmtpFalso)
    ajustes = get_settings()
    monkeypatch.setattr(ajustes, "smtp_user", "datos.economicos@gmail.com")
    monkeypatch.setattr(ajustes, "smtp_password", "abcd efgh ijkl mnop")
    return SmtpFalso


def test_envio_por_smtp_con_starttls(smtp):
    correo.enviar_codigo("ana@example.com", "Ana", "123456", 10)
    (servidor,) = smtp.instancias
    assert (servidor.host, servidor.puerto) == ("smtp.gmail.com", 587)
    assert servidor.pasos == ["starttls", ("login", "datos.economicos@gmail.com", "abcd efgh ijkl mnop"), "send"]
    (mensaje,) = servidor.mensajes
    assert mensaje["Subject"] == "Tu código de ingreso - Datos Económicos"
    assert mensaje["To"] == "ana@example.com"
    assert "datos.economicos@gmail.com" in mensaje["From"]  # SMTP_FROM vacío: se usa SMTP_USER
    texto = mensaje.get_body(("plain",)).get_content()
    assert "123456" in texto and "10 minutos" in texto and "Si no fuiste vos, ignorá este correo." in texto
    assert "123456" in mensaje.get_body(("html",)).get_content()


def test_envio_con_remitente_propio(smtp, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_from", "avisos@example.com")
    correo.enviar_codigo("ana@example.com", "Ana", "123456", 10)
    assert "avisos@example.com" in smtp.instancias[0].mensajes[0]["From"]


def test_nombre_con_html_en_el_correo(smtp):
    correo.enviar_codigo("ana@example.com", "<b>Ana</b>", "123456", 10)
    html = smtp.instancias[0].mensajes[0].get_body(("html",)).get_content()
    assert "<b>Ana</b>" not in html and "&lt;b&gt;Ana&lt;/b&gt;" in html


def test_falla_smtp_lanza_error_y_lo_registra(smtp, caplog):
    import smtplib

    smtp.error = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    with caplog.at_level("ERROR", logger="app.auth.correo"):
        with pytest.raises(correo.ErrorCorreo):
            correo.enviar_codigo("ana@example.com", "Ana", "123456", 10)
    assert "No se pudo mandar el código" in caplog.text
    assert "abcd efgh ijkl mnop" not in caplog.text  # la contraseña nunca va al registro


def test_falla_smtp_en_el_login(smtp, cliente_web, sesion_con_semillas):
    import smtplib

    smtp.error = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    r = registrar(cliente_web)
    assert r.headers["location"] == "/2fa/verificar?aviso=envio"
    pagina = sin_ocultos(cliente_web.get(r.headers["location"]).text)
    assert "No pudimos mandarte el código por email" in pagina
    assert "Username and Password not accepted" not in pagina and "535" not in pagina


def test_sin_smtp_configurado_el_codigo_va_al_registro(monkeypatch, caplog, cliente_web, sesion_con_semillas):
    """En desarrollo (SMTP_USER y SMTP_PASSWORD vacíos) no se manda nada: el código se escribe en el registro."""
    monkeypatch.setattr(correo, "enviar_codigo", enviar_real)
    monkeypatch.setattr(correo.smtplib, "SMTP", None)  # si intentara conectarse, fallaría
    assert not get_settings().smtp_user and not get_settings().smtp_password
    with caplog.at_level("WARNING", logger="app.auth.correo"):
        r = registrar(cliente_web)
    assert r.headers["location"] == "/2fa/verificar"
    (registro,) = [x for x in caplog.records if x.name == "app.auth.correo"]
    assert registro.levelname == "WARNING"
    mensaje = registro.getMessage()
    assert mensaje.startswith("Correo sin configurar: código para ana@example.com: ")
    codigo = mensaje.rsplit(": ", 1)[1]
    assert len(codigo) == 6 and codigo.isdigit()
    assert verificar(cliente_web, codigo).status_code == 303


# --- Salir ---

def test_salir_borra_la_sesion(cliente_api, sesion_con_semillas):
    pagina = cliente_api.get("/")
    r = cliente_api.post("/salir", data={"csrf": csrf_de(pagina.text)})
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert sesion_con_semillas.scalars(select(Sesion)).all() == []
    assert cliente_api.get("/").headers["location"] == "/login"


# --- Casos límite agregados por el tester ---

def test_registro_campos_vacios(cliente_web, sesion_con_semillas):
    r = registrar(cliente_web, email="", password="", nombre="   ")
    assert r.status_code == 400
    assert "Escribí tu nombre" in r.text and "email válido" in r.text and "al menos 12 caracteres" in r.text
    assert sesion_con_semillas.scalars(select(Usuario)).all() == []


@pytest.mark.parametrize("email", ["ana", "ana@", "@example.com", "ana@example", "ana @example.com",
                                   "ana@@example.com", "ana@.com", "a" * 250 + "@x.com"])
def test_registro_email_invalido(cliente_web, sesion_con_semillas, email):
    r = registrar(cliente_web, email=email)
    assert r.status_code == 400 and "email válido" in r.text
    assert sesion_con_semillas.scalars(select(Usuario)).all() == []


def test_registro_limites_de_largo(cliente_web, sesion_con_semillas):
    assert "hasta 100 caracteres" in registrar(cliente_web, nombre="n" * 101).text
    assert "hasta 256 caracteres" in registrar(cliente_web, password="p" * 257).text
    assert usuario(sesion_con_semillas) is None
    # Justo en el límite: nombre de 100 y contraseña de 12 caracteres.
    r = registrar(cliente_web, nombre="n" * 100, password="p" * 12)
    assert r.status_code == 303
    assert usuario(sesion_con_semillas).nombre == "n" * 100


def test_registro_contrasena_de_11_caracteres(cliente_web, sesion_con_semillas):
    assert registrar(cliente_web, password="p" * 11).status_code == 400


def test_nombre_con_html_se_escapa(cliente_web, sesion_con_semillas, buzon):
    malicioso = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    r = registrar(cliente_web, nombre=malicioso)
    assert r.status_code == 303
    pagina = cliente_web.get("/2fa/verificar").text
    assert "<script>alert(1)" not in pagina and "&lt;script&gt;alert(1)&lt;/script&gt;" in pagina
    completar_2fa(cliente_web, buzon)
    panel = cliente_web.get("/").text
    assert "<script>alert(1)" not in panel and "<img src=x" not in panel
    assert "&lt;script&gt;" in panel
    # Error de validación que vuelve a mostrar el nombre: también escapado.
    cliente_web.cookies.clear()
    r = registrar(cliente_web, nombre='"><script>x()</script>', password="corta")
    assert '"><script>x()' not in r.text


def test_registro_de_email_que_ya_entro_con_google(cliente_web, sesion_con_semillas):
    sesion_con_semillas.add(Usuario(email="ana@gmail.com", nombre="Ana Google", google_sub="123"))
    sesion_con_semillas.commit()
    r = registrar(cliente_web, email=" ANA@gmail.com")
    assert r.status_code == 400 and "Ya hay una cuenta con ese email" in r.text
    u = usuario(sesion_con_semillas, "ana@gmail.com")
    assert u.password_hash is None  # no se le agrega una contraseña a la cuenta de Google
    # Y con contraseña no se puede entrar a esa cuenta.
    r = ingresar(cliente_web, email="ana@gmail.com")
    assert r.status_code == 400 and "no son correctos" in r.text


def test_login_campos_vacios(cliente_web, cuenta):
    r = ingresar(cliente_web, email="", password="")
    assert r.status_code == 400 and "no son correctos" in r.text
    assert COOKIE_SESION not in cliente_web.cookies


def test_sesion_pendiente_dura_15_minutos(cliente_web, sesion_con_semillas):
    from app.auth.sesiones import ahora
    registrar(cliente_web)
    s = sesion_con_semillas.scalar(select(Sesion))
    restante = con_zona(s.expira_en) - ahora()
    assert timedelta(minutes=14) < restante <= timedelta(minutes=15)
    # Vencida, la pantalla del código manda al login.
    from tests.ayudas import vencer
    vencer(sesion_con_semillas, s)
    assert cliente_web.get("/2fa/verificar").headers["location"] == "/login"
