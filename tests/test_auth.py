import pyotp
import pytest
from sqlalchemy import select

from app.auth import seguridad
from app.auth.dependencias import requiere_admin
from app.auth.sesiones import COOKIE_SESION
from app.config import get_settings
from app.models import CodigoRecuperacion, Sesion, Usuario
from tests.ayudas import (
    PASSWORD, codigo_siguiente, configurar_2fa, csrf_de, ingresar, registrar, secreto_de, verificar,
)


def usuario(db, email="ana@example.com") -> Usuario:
    return db.scalar(select(Usuario).where(Usuario.email == email))


# --- Registro ---

def test_registro_valido(cliente_web, sesion_con_semillas):
    r = registrar(cliente_web, email="  Ana@Example.COM ")
    assert r.status_code == 303 and r.headers["location"] == "/2fa/configurar"
    u = usuario(sesion_con_semillas)
    assert u is not None and u.nombre == "Ana Pérez" and u.rol == "usuario"
    assert u.password_hash.startswith("$argon2") and PASSWORD not in u.password_hash
    # Queda con una sesión sin doble factor.
    s = sesion_con_semillas.scalar(select(Sesion))
    assert s.usuario_id == u.id and not s.mfa_ok
    assert cliente_web.cookies[COOKIE_SESION] and s.token_hash == seguridad.hash_token(cliente_web.cookies[COOKIE_SESION])


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
def cuenta(cliente_web, sesion_con_semillas):
    """Cuenta registrada con el doble factor configurado y la sesión cerrada."""
    registrar(cliente_web)
    secreto, codigos = configurar_2fa(cliente_web)
    cliente_web.cookies.clear()
    return secreto, codigos


def test_login_correcto(cliente_web, sesion_con_semillas, cuenta):
    r = ingresar(cliente_web, email="ANA@example.com ")
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar"
    assert not sesion_con_semillas.scalar(select(Sesion).order_by(Sesion.id.desc())).mfa_ok


@pytest.mark.parametrize(("email", "password"), [("ana@example.com", "contraseña equivocada"), ("nadie@example.com", PASSWORD)])
def test_login_incorrecto_mensaje_generico(cliente_web, cuenta, email, password):
    r = ingresar(cliente_web, email=email, password=password)
    assert r.status_code == 400
    assert "El email o la contraseña no son correctos." in r.text
    assert COOKIE_SESION not in cliente_web.cookies


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


def test_bloqueo_por_codigos_2fa(cliente_web, sesion_con_semillas, cuenta):
    ingresar(cliente_web)
    for _ in range(5):
        r = verificar(cliente_web, "000000")
    assert r.status_code == 400 and "bloqueamos el ingreso" in r.text
    secreto, _ = cuenta
    r = verificar(cliente_web, codigo_siguiente(secreto))
    assert r.status_code == 400 and "bloqueamos" in r.text


# --- Doble factor ---

def test_flujo_completo_2fa(cliente_web, sesion_con_semillas):
    registrar(cliente_web)
    # Sin el doble factor no se entra al panel.
    assert cliente_web.get("/").headers["location"] == "/2fa/configurar"

    pagina = cliente_web.get("/2fa/configurar")
    assert pagina.status_code == 200 and "<svg" in pagina.text
    secreto = secreto_de(pagina.text)
    # El QR se mantiene entre recargas y el secreto se guarda cifrado.
    assert secreto_de(cliente_web.get("/2fa/configurar").text) == secreto
    u = usuario(sesion_con_semillas)
    assert secreto not in u.totp_secret_cifrado and seguridad.descifrar(u.totp_secret_cifrado) == secreto

    # Código equivocado.
    r = cliente_web.post("/2fa/configurar", data={"codigo": "123456", "csrf": csrf_de(pagina.text)})
    assert r.status_code == 400 and "no es correcto" in r.text

    token_antes = cliente_web.cookies[COOKIE_SESION]
    r = cliente_web.post("/2fa/configurar", data={"codigo": pyotp.TOTP(secreto).now(), "csrf": csrf_de(pagina.text)})
    assert r.status_code == 200 and "Es la única vez" in r.text
    codigos = [c for c in r.text.split("<li>")[1:]]
    assert len(codigos) == 10
    assert len(sesion_con_semillas.scalars(select(CodigoRecuperacion)).all()) == 10
    # El token de sesión rota al completar el doble factor; el viejo ya no sirve.
    assert cliente_web.cookies[COOKIE_SESION] != token_antes
    assert cliente_web.get("/").status_code == 200
    viejo = cliente_web.cookies[COOKIE_SESION]
    cliente_web.cookies.set(COOKIE_SESION, token_antes)
    assert cliente_web.get("/").headers["location"] == "/login"
    cliente_web.cookies.set(COOKIE_SESION, viejo)
    # Ya configurado, /2fa/configurar no vuelve a mostrar el QR.
    assert cliente_web.get("/2fa/configurar").headers["location"] == "/"


def test_verificar_y_codigo_reutilizado(cliente_web, sesion_con_semillas, cuenta):
    secreto, _ = cuenta
    ingresar(cliente_web)
    codigo = codigo_siguiente(secreto)
    r = verificar(cliente_web, codigo)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert cliente_web.get("/").status_code == 200
    assert usuario(sesion_con_semillas).ultimo_ingreso is not None

    # Mismo código en otro ingreso: rechazado.
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    r = verificar(cliente_web, codigo)
    assert r.status_code == 400 and "ya se usó" in r.text
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"


def test_codigo_de_recuperacion_de_un_solo_uso(cliente_web, sesion_con_semillas, cuenta):
    _, codigos = cuenta
    assert len(codigos) == 10
    ingresar(cliente_web)
    r = verificar(cliente_web, codigos[3].upper())  # no distingue mayúsculas
    assert r.status_code == 303 and r.headers["location"] == "/"
    usados = sesion_con_semillas.scalars(select(CodigoRecuperacion).where(CodigoRecuperacion.usado_en.is_not(None))).all()
    assert len(usados) == 1

    cliente_web.cookies.clear()
    ingresar(cliente_web)
    r = verificar(cliente_web, codigos[3])
    assert r.status_code == 400 and "ya se usó" in r.text
    assert verificar(cliente_web, codigos[4]).status_code == 303


def test_totp_tolerancia_una_ventana():
    secreto = pyotp.random_base32()
    t = 1_700_000_000
    totp = pyotp.TOTP(secreto)
    assert seguridad.verificar_totp(secreto, totp.at(t - 30), None, ahora=t) is not None
    assert seguridad.verificar_totp(secreto, totp.at(t + 30), None, ahora=t) is not None
    assert seguridad.verificar_totp(secreto, totp.at(t - 90), None, ahora=t) is None
    paso = seguridad.verificar_totp(secreto, totp.at(t), None, ahora=t)
    assert seguridad.verificar_totp(secreto, totp.at(t), paso, ahora=t) is None
    assert seguridad.verificar_totp(secreto, "12a456", None, ahora=t) is None


def test_falta_clave_de_cifrado(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_encryption_key", "")
    with pytest.raises(seguridad.ErrorConfiguracion, match="APP_ENCRYPTION_KEY"):
        seguridad.verificar_configuracion()


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


def test_nombre_con_html_se_escapa(cliente_web, sesion_con_semillas):
    malicioso = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    r = registrar(cliente_web, nombre=malicioso)
    assert r.status_code == 303
    pagina = cliente_web.get("/2fa/configurar").text
    assert "<script>alert(1)" not in pagina and "&lt;script&gt;alert(1)&lt;/script&gt;" in pagina
    configurar_2fa(cliente_web)
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
    from datetime import timedelta

    from app.auth.sesiones import ahora, con_zona
    registrar(cliente_web)
    s = sesion_con_semillas.scalar(select(Sesion))
    restante = con_zona(s.expira_en) - ahora()
    assert timedelta(minutes=14) < restante <= timedelta(minutes=15)
    # Vencida, las pantallas del doble factor mandan al login.
    from tests.ayudas import vencer
    vencer(sesion_con_semillas, s)
    assert cliente_web.get("/2fa/configurar").headers["location"] == "/login"


def test_totp_fuera_de_la_tolerancia():
    secreto = pyotp.random_base32()
    t = 1_700_000_000
    totp = pyotp.TOTP(secreto)
    assert seguridad.verificar_totp(secreto, totp.at(t - 60), None, ahora=t) is None
    assert seguridad.verificar_totp(secreto, totp.at(t + 60), None, ahora=t) is None
    # Un código de la ventana anterior no sirve si ya se usó uno de la actual.
    paso = seguridad.verificar_totp(secreto, totp.at(t), None, ahora=t)
    assert seguridad.verificar_totp(secreto, totp.at(t - 30), paso, ahora=t) is None
    assert seguridad.verificar_totp(secreto, "", None, ahora=t) is None
    assert seguridad.verificar_totp(secreto, "1234567", None, ahora=t) is None


def test_verificar_con_espacios_y_codigo_de_ventana_anterior(cliente_web, cuenta):
    import time
    secreto, _ = cuenta
    ingresar(cliente_web)
    # La configuración usó el código actual; el de la ventana siguiente con un espacio en el medio sirve.
    codigo = codigo_siguiente(secreto)
    r = verificar(cliente_web, f"{codigo[:3]} {codigo[3:]}")
    assert r.status_code == 303
    # Ya usado el de la ventana siguiente, el de la anterior queda rechazado.
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    r = verificar(cliente_web, pyotp.TOTP(secreto).at(time.time() - 30))
    assert r.status_code == 400


def test_codigo_de_recuperacion_sin_guiones(cliente_web, cuenta):
    _, codigos = cuenta
    ingresar(cliente_web)
    assert verificar(cliente_web, " " + codigos[0].replace("-", "") + " ").status_code == 303


def test_codigo_vacio_en_verificar(cliente_web, cuenta):
    ingresar(cliente_web)
    r = verificar(cliente_web, "")
    assert r.status_code == 400 and "no es correcto" in r.text


def test_bloqueo_por_codigos_al_configurar(cliente_web, sesion_con_semillas):
    registrar(cliente_web)
    pagina = cliente_web.get("/2fa/configurar")
    for _ in range(5):
        r = cliente_web.post("/2fa/configurar", data={"codigo": "000000", "csrf": csrf_de(pagina.text)})
    assert r.status_code == 400 and "bloqueamos" in r.text
    secreto = secreto_de(pagina.text)
    r = cliente_web.post("/2fa/configurar", data={"codigo": pyotp.TOTP(secreto).now(), "csrf": csrf_de(pagina.text)})
    assert r.status_code == 400 and not usuario(sesion_con_semillas).totp_activo


def test_volver_a_poner_la_contrasena_no_reinicia_los_intentos_del_codigo(cliente_web, sesion_con_semillas, cuenta):
    """Con la contraseña correcta no se tiene que poder probar códigos sin límite (fuerza bruta del 2FA)."""
    ingresar(cliente_web)
    for _ in range(4):
        assert verificar(cliente_web, "000000").status_code == 400
    # Se vuelve a ingresar con la contraseña y se sigue probando códigos.
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    r = verificar(cliente_web, "000000")
    assert "bloqueamos" in r.text, "tras 5 códigos fallidos la cuenta debería quedar bloqueada"


@pytest.mark.parametrize("ruta", ["/2fa/configurar", "/2fa/verificar"])
def test_csrf_en_pantallas_del_doble_factor(cliente_web, sesion_con_semillas, ruta):
    registrar(cliente_web)
    if ruta == "/2fa/verificar":
        configurar_2fa(cliente_web)
        cliente_web.cookies.clear()
        ingresar(cliente_web)
    assert cliente_web.post(ruta, data={"codigo": "123456"}).status_code == 403
    assert cliente_web.post(ruta, data={"codigo": "123456", "csrf": "x"}).status_code == 403
    u = usuario(sesion_con_semillas)
    assert u.intentos_fallidos == 0 and u.intentos_2fa == 0


def test_contrasena_correcta_no_reinicia_intentos_con_codigos_de_recuperacion(cliente_web, sesion_con_semillas, cuenta):
    ingresar(cliente_web)
    for _ in range(3):
        assert verificar(cliente_web, "aaaa-bbbb-cccc").status_code == 400
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    assert verificar(cliente_web, "000000").status_code == 400
    r = verificar(cliente_web, "zzzz-zzzz-zzzz")
    assert "bloqueamos" in r.text


def test_contrasena_correcta_no_reinicia_intentos_al_configurar(cliente_web, sesion_con_semillas):
    registrar(cliente_web)
    pagina = cliente_web.get("/2fa/configurar")
    for _ in range(4):
        cliente_web.post("/2fa/configurar", data={"codigo": "000000", "csrf": csrf_de(pagina.text)})
    cliente_web.cookies.clear()
    ingresar(cliente_web)
    pagina = cliente_web.get("/2fa/configurar")
    r = cliente_web.post("/2fa/configurar", data={"codigo": "000000", "csrf": csrf_de(pagina.text)})
    assert "bloqueamos" in r.text


def test_completar_el_2fa_reinicia_los_intentos(cliente_web, sesion_con_semillas, cuenta):
    secreto, _ = cuenta
    ingresar(cliente_web)
    for _ in range(4):
        verificar(cliente_web, "000000")
    assert usuario(sesion_con_semillas).intentos_2fa == 4
    assert verificar(cliente_web, codigo_siguiente(secreto)).status_code == 303
    assert usuario(sesion_con_semillas).intentos_2fa == 0


def test_mezclar_totp_y_recuperacion_tambien_bloquea(cliente_web, sesion_con_semillas, cuenta):
    secreto, codigos = cuenta
    malos = [["000000", "aaaa-bbbb-cccc"], ["111111", "zzzz-zzzz-zzzz"], ["x"]]
    for ronda in malos:
        cliente_web.cookies.clear()
        assert ingresar(cliente_web).status_code == 303
        for codigo in ronda:
            r = verificar(cliente_web, codigo)
    assert r.status_code == 400 and "bloqueamos" in r.text
    # Bloqueada: ni un código de recuperación válido entra.
    assert "bloqueamos" in verificar(cliente_web, codigos[0]).text
