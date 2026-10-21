"""Ingreso con Google, simulando el cliente de Authlib (sin internet)."""

import pytest
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth import google
from app.config import get_settings
from app.models import Sesion, Usuario
from tests.ayudas import completar_2fa, registrar, verificar


class GoogleFalso:
    def __init__(self, userinfo: dict | None = None, error: Exception | None = None):
        self.userinfo = userinfo or {}
        self.error = error
        self.redirect_uri = None

    async def authorize_redirect(self, request, redirect_uri):
        self.redirect_uri = redirect_uri
        return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?redirect_uri={redirect_uri}", 302)

    async def authorize_access_token(self, request):
        if self.error:
            raise self.error
        return {"access_token": "x", "userinfo": self.userinfo}


@pytest.fixture
def con_google(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "cliente-de-prueba.apps.googleusercontent.com")
    monkeypatch.setattr(get_settings(), "google_client_secret", "secreto")

    def usar(**kwargs) -> GoogleFalso:
        falso = GoogleFalso(**kwargs)
        monkeypatch.setattr(google, "cliente_google", lambda: falso)
        return falso

    return usar


def datos_google(**cambios) -> dict:
    return {"sub": "1234567890", "email": "Ana@Gmail.com", "email_verified": True, "name": "Ana Google"} | cambios


def test_boton_oculto_sin_configuracion(cliente_web, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    assert "Continuar con Google" not in cliente_web.get("/login").text
    assert "Continuar con Google" not in cliente_web.get("/registro").text
    assert cliente_web.get("/auth/google").status_code == 404
    assert cliente_web.get("/auth/google/callback").status_code == 404


def test_boton_visible_e_inicio(cliente_web, con_google):
    falso = con_google()
    assert "Continuar con Google" in cliente_web.get("/login").text
    r = cliente_web.get("/auth/google")
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    assert falso.redirect_uri == "http://localhost:8000/auth/google/callback"


def test_cuenta_nueva(cliente_web, sesion_con_semillas, con_google, buzon):
    con_google(userinfo=datos_google())
    r = cliente_web.get("/auth/google/callback?code=abc&state=xyz")
    assert r.status_code == 303 and r.headers["location"] == "/2fa/verificar"
    u = sesion_con_semillas.scalar(select(Usuario))
    assert (u.email, u.nombre, u.google_sub, u.password_hash) == ("ana@gmail.com", "Ana Google", "1234567890", None)
    assert not sesion_con_semillas.scalar(select(Sesion)).mfa_ok
    # También tiene que pasar por el doble factor: el código va al email de la cuenta.
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"
    assert [m["destino"] for m in buzon.enviados] == ["ana@gmail.com"]
    assert cliente_web.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY"}).status_code == 401
    malo = "000000" if buzon.ultimo() != "000000" else "999999"
    assert verificar(cliente_web, malo).status_code == 400
    completar_2fa(cliente_web, buzon)
    assert cliente_web.get("/").status_code == 200


def test_google_con_cuenta_bloqueada(cliente_web, sesion_con_semillas, con_google, buzon):
    from datetime import timedelta

    from app.auth.sesiones import ahora

    con_google(userinfo=datos_google())
    sesion_con_semillas.add(Usuario(email="ana@gmail.com", nombre="Ana", google_sub="1234567890",
                                    bloqueado_hasta=ahora() + timedelta(minutes=10)))
    sesion_con_semillas.commit()
    r = cliente_web.get("/auth/google/callback?code=abc")
    assert r.headers["location"] == "/2fa/verificar"
    assert buzon.enviados == []  # bloqueada: no se manda código
    assert "bloqueamos el ingreso" in cliente_web.get("/2fa/verificar").text
    assert cliente_web.get("/").headers["location"] == "/2fa/verificar"


def test_vincula_cuenta_existente_con_email_verificado(cliente_web, sesion_con_semillas, con_google):
    registrar(cliente_web, email="ana@gmail.com")
    cliente_web.cookies.clear()
    con_google(userinfo=datos_google())
    r = cliente_web.get("/auth/google/callback?code=abc")
    assert r.status_code == 303
    usuarios = sesion_con_semillas.scalars(select(Usuario)).all()
    assert len(usuarios) == 1
    assert usuarios[0].google_sub == "1234567890" and usuarios[0].password_hash is not None
    assert usuarios[0].nombre == "Ana Pérez"  # no se pisa el nombre


def test_rechaza_vincular_sin_email_verificado(cliente_web, sesion_con_semillas, con_google):
    registrar(cliente_web, email="ana@gmail.com")
    cliente_web.cookies.clear()
    con_google(userinfo=datos_google(email_verified=False))
    r = cliente_web.get("/auth/google/callback?code=abc")
    assert r.status_code == 303 and r.headers["location"] == "/login?aviso=google_email"
    assert sesion_con_semillas.scalar(select(Usuario)).google_sub is None
    assert len(sesion_con_semillas.scalars(select(Sesion)).all()) == 1  # solo la del registro
    assert "Google no confirmó" in cliente_web.get(r.headers["location"]).text


def test_error_de_google(cliente_web, sesion_con_semillas, con_google):
    con_google(error=RuntimeError("state inválido"))
    r = cliente_web.get("/auth/google/callback?error=access_denied")
    assert r.headers["location"] == "/login?aviso=google"
    assert sesion_con_semillas.scalars(select(Usuario)).all() == []


def test_ingreso_repetido_usa_el_sub(cliente_web, sesion_con_semillas, con_google):
    con_google(userinfo=datos_google())
    cliente_web.get("/auth/google/callback?code=1")
    cliente_web.cookies.clear()
    # Aunque cambie el email en Google, se reconoce por el `sub`.
    con_google(userinfo=datos_google(email="otro@gmail.com"))
    assert cliente_web.get("/auth/google/callback?code=2").status_code == 303
    assert len(sesion_con_semillas.scalars(select(Usuario)).all()) == 1
