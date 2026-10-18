"""Acceso al panel y a la API según la sesión, CSRF y cabeceras de seguridad."""

import json
import re

import pytest
from sqlalchemy import select

from app.etl.fmi import cargar_fmi
from app.models import Sesion
from tests.ayudas import configurar_2fa, csrf_de, registrar, vencer

PARAMS = {"indicador": "PBI_USD_CORR", "paises": "URY"}


# --- Acceso según la sesión ---

def test_sin_sesion(cliente_web):
    r = cliente_web.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = cliente_web.get("/api/series", params=PARAMS)
    assert r.status_code == 401 and "Iniciá sesión" in r.json()["detail"]


def test_sesion_sin_2fa(cliente_web):
    registrar(cliente_web)
    assert cliente_web.get("/").headers["location"] == "/2fa/configurar"
    assert cliente_web.get("/api/series", params=PARAMS).status_code == 401


def test_sesion_completa(cliente_web, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    registrar(cliente_web)
    configurar_2fa(cliente_web)
    r = cliente_web.get("/")
    assert r.status_code == 200 and "Ana Pérez" in r.text
    assert cliente_web.get("/api/series", params=PARAMS).status_code == 200
    # Con sesión completa, login y registro llevan al panel.
    assert cliente_web.get("/login").headers["location"] == "/"
    assert cliente_web.get("/registro").headers["location"] == "/"


def test_sesion_vencida(cliente_api, sesion_con_semillas):
    vencer(sesion_con_semillas, sesion_con_semillas.scalar(select(Sesion)))
    assert cliente_api.get("/api/series", params=PARAMS).status_code == 401
    assert sesion_con_semillas.scalars(select(Sesion)).all() == []


def test_cookie_de_sesion(cliente_web):
    r = registrar(cliente_web)
    cookie = r.headers["set-cookie"]
    assert "sesion=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # COOKIE_SECURE=false en los tests


def test_datos_del_panel(cliente_api, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    html = cliente_api.get("/").text
    datos = json.loads(re.search(r'<script type="application/json" id="datos-panel">(.*?)</script>', html, re.S).group(1))
    pbi = next(i for i in datos["indicadores"] if i["codigo"] == "PBI_USD_CORR")
    assert {"URY", "ARG", "WEOWORLD"} <= set(pbi["paises"])
    assert pbi["desde"] <= 2000 and pbi["hasta"] >= 2024
    assert datos["por_defecto"] == ["URY", "ARG", "WEOWORLD"]
    nombres = {p["codigo"]: p["nombre"] for p in datos["paises"]}
    assert nombres["URY"] == "Uruguay" and nombres["WEOWORLD"] == "Mundo"
    assert "Fuente: FMI, World Economic Outlook (DataMapper)" in html
    assert '<script src="/static/vendor/echarts.min.js' in html


def test_datos_del_panel_con_dos_fuentes(cliente_api, sesion_con_semillas, cliente_fmi, cliente_bm):
    from app.etl.banco_mundial import cargar_bm

    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    html = cliente_api.get("/").text
    datos = json.loads(re.search(r'<script type="application/json" id="datos-panel">(.*?)</script>', html, re.S).group(1))
    indicadores = {i["codigo"]: i for i in datos["indicadores"]}
    pbi = indicadores["PBI_USD_CORR"]
    assert pbi["fuente"] == "FMI_DM"
    fmi, bm = pbi["fuentes"]
    assert (fmi["codigo"], bm["codigo"]) == ("FMI_DM", "BM")
    assert (fmi["desde"], fmi["hasta"]) == (1980, 2024) and (bm["desde"], bm["hasta"]) == (2010, 2020)
    assert bm["nombre"] == "Banco Mundial, World Development Indicators"
    # El selector usa el nombre corto; el completo va en el texto de la fuente.
    assert (fmi["corto"], bm["corto"]) == ("FMI", "Banco Mundial")
    assert set(bm["paises"]) == {"ARG", "URY", "WEOWORLD"} and "USA" in fmi["paises"]
    # Los años y países de nivel superior son los de la fuente por defecto.
    assert (pbi["desde"], pbi["paises"]) == (fmi["desde"], fmi["paises"])
    central = indicadores["DEUDA_GOB_CENTRAL"]
    assert central["fuente"] == "BM" and [f["codigo"] for f in central["fuentes"]] == ["BM"]
    assert central["paises"] == ["URY"]  # Argentina no tiene datos (null)
    assert '<select id="fuente"' in html


# --- CSRF ---

def test_csrf_rechazado(cliente_web, sesion_con_semillas):
    cliente_web.get("/login")  # crea la cookie csrf
    datos = {"nombre": "Ana", "email": "ana@example.com", "password": "x" * 12, "confirmacion": "x" * 12}
    assert cliente_web.post("/registro", data=datos).status_code == 403
    r = cliente_web.post("/registro", data=datos | {"csrf": "inventado"})
    assert r.status_code == 403 and "venció o no es válido" in r.text
    assert cliente_web.post("/login", data={"email": "a@b.com", "password": "x", "csrf": "inventado"}).status_code == 403


def test_csrf_de_otro_navegador(cliente_web, sesion_con_semillas):
    token = csrf_de(cliente_web.get("/registro").text)
    cliente_web.cookies.clear()
    cliente_web.get("/registro")  # otra cookie csrf
    r = cliente_web.post("/registro", data={"nombre": "Ana", "email": "a@b.com", "password": "x" * 12,
                                            "confirmacion": "x" * 12, "csrf": token})
    assert r.status_code == 403


def test_csrf_en_salir(cliente_api, sesion_con_semillas):
    assert cliente_api.post("/salir", data={"csrf": "x"}).status_code == 403
    assert len(sesion_con_semillas.scalars(select(Sesion)).all()) == 1


# --- Cabeceras de seguridad ---

@pytest.mark.parametrize("ruta", ["/login", "/salud", "/static/css/estilos.css"])
def test_cabeceras_de_seguridad(cliente_web, ruta):
    r = cliente_web.get(ruta)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "http" not in csp


def test_paginas_sin_scripts_en_linea(cliente_api):
    html = cliente_api.get("/").text
    for etiqueta in re.findall(r"<script[^>]*>", html):
        assert "src=" in etiqueta or 'type="application/json"' in etiqueta
    assert " style=" not in html and "<style" not in html


def test_lema_de_acceso_menciona_las_fuentes_reales(cliente_web):
    html = cliente_web.get("/login").text
    assert "Series del FMI y del Banco Mundial, y de Uruguay del INE y el BCU" in html


def test_portada_sin_datos_muestra_solo_el_lema(cliente_web):
    html = cliente_web.get("/login").text
    assert "acceso-portada" not in html and "acceso-con-portada" not in html


def test_portada_con_muestra_real_y_cobertura(cliente_web, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    for ruta in ("/login", "/registro"):
        html = cliente_web.get(ruta).text
        assert 'class="acceso-portada"' in html
        # Índice base 100 calculado con los datos guardados (fixture: URY 24,892 en 2000 y 82,323 en 2024).
        assert "PBI en dólares corrientes, índice 2000 = 100" in html
        assert re.search(r"Uruguay <strong>331</strong>", html) and re.search(r"Argentina <strong>201</strong>", html)
        assert html.count('class="muestra-linea') == 2
        assert re.search(r"<abbr[^>]*>FMI</abbr>", html) and "1980–2024" in html
        assert " style=" not in html and "<style" not in html
    # Con error en el formulario, la portada sigue.
    r = cliente_web.post("/login", data={"email": "x@example.com", "password": "mal", "csrf": csrf_de(html)})
    assert r.status_code == 400 and 'class="acceso-portada"' in r.text


def test_portada_no_va_en_las_pantallas_del_doble_factor(cliente_web, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    registrar(cliente_web)
    assert "acceso-portada" not in cliente_web.get("/2fa/configurar").text


def test_datos_portada_hasta_el_ultimo_anio_cerrado(sesion_con_semillas, cliente_fmi):
    from datetime import date

    from app.web.portada import datos_portada

    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    # En 2011 el último año cerrado es 2010: no entran los valores de 2024 (proyecciones, para esa fecha).
    m = datos_portada(sesion_con_semillas, hoy=date(2011, 6, 1))["muestra"]
    assert m["hasta"] == 2010 and [s["anio_final"] for s in m["series"]] == [2010, 2010]
    # Sin el año base no hay muestra, pero sí la cobertura.
    p = datos_portada(sesion_con_semillas, hoy=date(2000, 6, 1))
    assert p["muestra"] is None and p["fuentes"][0]["corto"] == "FMI"


def test_portada_separa_las_proyecciones_del_fmi(sesion_con_semillas, cliente_fmi):
    from datetime import date

    from app.web.portada import datos_portada

    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    # En 2011 los años 2011 a 2024 del fixture son proyecciones: el rango llega al último año cerrado.
    fmi = datos_portada(sesion_con_semillas, hoy=date(2011, 6, 1))["fuentes"][0]
    assert fmi["anios"] == "1980–2010" and fmi["proyecciones_hasta"] == 2024
    # Con todos los años cerrados no hay nada que aclarar.
    fmi = datos_portada(sesion_con_semillas, hoy=date(2026, 6, 1))["fuentes"][0]
    assert fmi["anios"] == "1980–2024" and fmi["proyecciones_hasta"] is None


def test_portada_aclara_las_proyecciones_en_la_pagina(cliente_web, sesion_con_semillas, cliente_fmi, monkeypatch):
    from datetime import date

    from app.web import portada

    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)

    class Hoy(date):
        @classmethod
        def today(cls):
            return date(2011, 6, 1)

    monkeypatch.setattr(portada, "date", Hoy)
    html = cliente_web.get("/login").text
    assert "1980–2010" in html and "proyecciones hasta 2024" in html and "1980–2024" not in html


def test_rango_de_un_solo_anio():
    from app.web.portada import rango

    assert rango(2026, 2026) == "2026"
    assert rango(2000, 2026) == "2000–2026"


def test_datos_portada_se_guardan_unos_minutos(sesion_con_semillas, cliente_fmi, monkeypatch):
    from app.web import portada

    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    llamadas = []
    original = portada._armar
    monkeypatch.setattr(portada, "_armar", lambda db, hoy: llamadas.append(hoy) or original(db, hoy))
    reloj = [1000.0]
    monkeypatch.setattr(portada.time, "monotonic", lambda: reloj[0])

    primero = portada.datos_portada(sesion_con_semillas)
    assert portada.datos_portada(sesion_con_semillas) is primero and len(llamadas) == 1
    reloj[0] += portada.CACHE_SEGUNDOS + 1  # vencido: se vuelve a consultar
    portada.datos_portada(sesion_con_semillas)
    assert len(llamadas) == 2
