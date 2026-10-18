"""Panel en un navegador real (Playwright + Chromium): lo que solo se ve con el JavaScript corriendo.

Se saltean si Playwright o su Chromium no están instalados (`pip install playwright && playwright install chromium`).
"""

import secrets
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sync_api = pytest.importorskip("playwright.sync_api")

import app.models  # noqa: F401,E402
from app.auth.seguridad import hash_token, hashear_password  # noqa: E402
from app.auth.sesiones import COOKIE_SESION, DURACION, ahora  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.etl.banco_mundial import cargar_bm  # noqa: E402
from app.etl.fmi import cargar_fmi  # noqa: E402
from app.etl.semillas import cargar_semillas  # noqa: E402
from app.main import app as aplicacion  # noqa: E402
from app.models import Sesion, Usuario  # noqa: E402
from tests.ayudas import PASSWORD  # noqa: E402
from tests.conftest import transporte_bm, transporte_fmi  # noqa: E402

PUERTO = 8799
BASE = f"http://127.0.0.1:{PUERTO}"


@pytest.fixture(scope="module")
def servidor():
    """App con los datos de los fixtures (FMI y BM), servida por uvicorn en un hilo. Devuelve el token de sesión."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Hacer = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Hacer() as s:
        cargar_semillas(s)
        with httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test") as c:
            cargar_fmi(s, c, espera=0)
        with httpx.Client(transport=transporte_bm(), base_url="https://bm.test") as c:
            cargar_bm(s, c, espera=0)
        usuario = Usuario(email="navegador@example.com", nombre="Navegador", password_hash=hashear_password(PASSWORD),
                          totp_activo=True, rol="usuario")
        s.add(usuario)
        s.flush()
        token = secrets.token_urlsafe(32)
        s.add(Sesion(token_hash=hash_token(token), usuario_id=usuario.id, mfa_ok=True, expira_en=ahora() + DURACION))
        s.commit()

    lock = threading.Lock()  # una sola conexión SQLite compartida: un pedido a la vez

    def db():
        with lock, Hacer() as s:
            yield s

    aplicacion.dependency_overrides[get_db] = db
    server = uvicorn.Server(uvicorn.Config(aplicacion, host="127.0.0.1", port=PUERTO, log_level="warning"))
    hilo = threading.Thread(target=server.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield token
    server.should_exit = True
    hilo.join(5)
    aplicacion.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # Chromium de Playwright no instalado
            pytest.skip(f"Chromium no disponible: {e}")
        yield b
        b.close()


@pytest.fixture
def pagina(servidor, navegador):
    ctx = navegador.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_cookies([{"name": COOKIE_SESION, "value": servidor, "url": BASE}])
    pg = ctx.new_page()
    errores = []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    yield pg
    ctx.close()
    assert not errores, errores


def esperar_carga(pg):
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(400)  # el panel agrupa los pedidos con un retardo de 120 ms


def rango(pg):
    return pg.locator("#desde").input_value(), pg.locator("#hasta").input_value()


# --- 1. Series sin datos en la fuente ---

def test_serie_sin_datos_en_la_fuente_no_dibuja_etiqueta(pagina):
    # BRA no tiene PBI en los fixtures del FMI; con 3 series las etiquetas de fin de línea están activas.
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,BRA,ARG")
    esperar_carga(pagina)
    etiquetas = pagina.evaluate(
        """() => echarts.getInstanceByDom(document.getElementById('grafica')).getOption()
                  .series.map((s) => [s.name, s.endLabel.show])"""
    )
    assert dict(etiquetas) == {"Uruguay": True, "Brasil": False, "Argentina": True}
    # En la leyenda figura como "sin datos en esta fuente" y no se puede ocultar (no es un botón).
    vacia = pagina.locator(".leyenda-vacia")
    assert vacia.count() == 1
    assert "Brasil" in vacia.inner_text() and "sin datos en esta fuente" in vacia.inner_text()
    assert pagina.locator("button.leyenda-item").count() == 2
    # También en la tabla y en la nota de arriba de la gráfica.
    assert "sin datos en esta fuente" in pagina.locator("#tabla thead").inner_text()
    assert "no publica datos de Brasil" in pagina.inner_text("#nota-faltantes")


def test_serie_sin_datos_en_el_rango_se_distingue_de_la_fuente(pagina):
    # URY tiene PBI del FMI desde 2000: entre 1980 y 1990 no hay datos, pero la fuente sí lo publica.
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG&desde=1980&hasta=1990")
    esperar_carga(pagina)
    assert "sin datos en este rango" in pagina.locator(".leyenda-vacia").inner_text()
    assert "Sin datos en este rango: Uruguay." in pagina.inner_text("#nota-faltantes")


# --- 2. El rango completo sigue al cambiar de fuente o de indicador ---

def test_rango_completo_pasa_al_de_la_nueva_fuente(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&paises=URY,ARG")
    esperar_carga(pagina)
    assert rango(pagina) == ("1980", "2024")  # rango completo del FMI
    pagina.select_option("#fuente", "BM")
    esperar_carga(pagina)
    assert rango(pagina) == ("2010", "2020")  # el del BM
    pagina.select_option("#fuente", "FMI_DM")
    esperar_carga(pagina)
    assert rango(pagina) == ("1980", "2024")  # antes quedaba acotado a 2010-2020
    assert "desde=1980" in pagina.url and "hasta=2024" in pagina.url


def test_rango_completo_pasa_al_del_nuevo_indicador(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_CRECIMIENTO&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    assert rango(pagina) == ("2000", "2010")
    pagina.select_option("#indicador", "PBI_USD_CORR")
    esperar_carga(pagina)
    assert rango(pagina) == ("1980", "2024")


def test_rango_elegido_a_mano_se_conserva(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG&desde=2012&hasta=2018")
    esperar_carga(pagina)
    pagina.select_option("#fuente", "BM")
    esperar_carga(pagina)
    assert rango(pagina) == ("2012", "2018")


# --- 4. Nombre corto en el selector de fuente ---

def test_selector_de_fuente_con_nombre_corto(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=bm&paises=URY")  # la fuente de la URL ignora mayúsculas
    esperar_carga(pagina)
    assert pagina.locator("#fuente option").all_inner_texts() == ["FMI", "Banco Mundial"]
    assert pagina.locator("#fuente").input_value() == "BM"
    assert pagina.inner_text("#fuente-serie") == "Fuente: Banco Mundial, World Development Indicators"


# --- Casos agregados por el tester ---

def test_todas_las_series_sin_datos_en_la_fuente_sugiere_otra_fuente(pagina):
    # BRA no tiene PBI en el FMI de los fixtures: estado vacío propio, no "No hay datos en ese rango".
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=BRA")
    esperar_carga(pagina)
    assert pagina.locator("#estado").is_visible()
    assert "Sin datos en esta fuente" in pagina.inner_text("#estado-titulo")
    assert "Probá con otra fuente" in pagina.inner_text("#estado-texto")


def test_serie_sin_datos_no_es_enfocable_ni_entra_en_el_tooltip(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,BRA")
    esperar_carga(pagina)
    # La leyenda vacía no es un botón: no recibe foco ni se puede "ocultar".
    assert pagina.locator(".leyenda-vacia").evaluate("e => e.tagName") == "SPAN"
    pagina.locator(".leyenda-vacia").click()
    esperar_carga(pagina)
    assert pagina.locator("button.leyenda-item").count() == 1
    caja = pagina.locator("#grafica").bounding_box()
    pagina.mouse.move(caja["x"] + caja["width"] * 0.6, caja["y"] + caja["height"] * 0.4)
    pagina.wait_for_timeout(400)
    texto = pagina.evaluate(
        "() => [...document.querySelectorAll('#grafica div')].map((d) => d.innerText || '').join(' ')"
    )
    assert "Brasil" not in texto


@pytest.mark.parametrize("fuente", ["", "xyz", "%20bm%20"])
def test_fuente_de_la_url_vacia_desconocida_o_con_espacios(pagina, fuente):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&paises=URY&fuente={fuente}")
    esperar_carga(pagina)
    esperada = "BM" if "bm" in fuente else "FMI_DM"
    assert pagina.locator("#fuente").input_value() == esperada
    assert not pagina.locator("#estado").is_visible()
    assert f"fuente={esperada}" in pagina.url


def test_390px_sin_scroll_horizontal_con_nombres_largos(servidor, navegador):
    ctx = navegador.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    ctx.add_cookies([{"name": COOKIE_SESION, "value": servidor, "url": BASE}])
    pg = ctx.new_page()
    try:
        pg.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=URY,ARG,WEOWORLD,USA")
        esperar_carga(pg)
        assert pg.evaluate("() => document.documentElement.scrollWidth") <= 390
        pg.goto(f"{BASE}/login")
        assert pg.evaluate("() => document.documentElement.scrollWidth") <= 390
    finally:
        ctx.close()


# --- Segunda revisión del tester ---

def test_mensaje_vacio_usa_el_nombre_del_indicador_tal_cual(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=USA")
    esperar_carga(pagina)
    assert pagina.inner_text("#estado-texto").startswith(
        "El Banco Mundial no publica PBI, precios corrientes para Estados Unidos."
    )
    # El mensaje de rango vacío, igual: URY (BM) tiene datos solo entre 2010 y 2020.
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=URY&desde=2012&hasta=2018")
    esperar_carga(pagina)
    assert "No hay datos en ese rango" in pagina.inner_text("#estado-titulo")
    assert "no publica PBI, precios corrientes para Uruguay entre 2012 y 2018" in pagina.inner_text("#estado-texto")


def test_base_100_con_una_serie_vacia_en_la_fuente_dibuja_las_demas(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=URY,USA&base=2010")
    esperar_carga(pagina)
    assert not pagina.locator("#estado").is_visible()
    assert pagina.locator("#usar-base").is_checked()
    assert "sin datos en esta fuente" in pagina.locator(".leyenda-vacia").inner_text()
    assert "Estados Unidos" in pagina.locator(".leyenda-vacia").inner_text()
    filas = pagina.locator("#tabla tbody tr").all_inner_texts()
    assert any(f.startswith("2010") and "100,0" in f for f in filas)


def test_marca_de_la_serie_vacia_es_hueca_y_alineada_con_el_nombre(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=URY,USA")
    esperar_carga(pagina)
    fondo = "e => getComputedStyle(e).backgroundColor"
    hueca = "rgba(0, 0, 0, 0)"
    ficha_usa = pagina.locator('.ficha[data-codigo="USA"] .marca-serie')
    assert ficha_usa.evaluate(fondo) == hueca
    assert pagina.locator('.ficha[data-codigo="URY"] .marca-serie').evaluate(fondo) != hueca
    marca = pagina.locator("#tabla thead .encabezado-vacio .marca-serie")
    assert marca.evaluate(fondo) == hueca
    # Centrada con la primera línea del nombre (no con todo el bloque nombre + nota).
    m = marca.bounding_box()
    nombre = pagina.locator("#tabla thead .encabezado-vacio > span:not(.marca-serie)").evaluate(
        """e => { const r = document.createRange(); r.setStart(e.firstChild, 0); r.setEnd(e.firstChild, 1);
                  const b = r.getBoundingClientRect(); return {y: b.y, height: b.height}; }"""
    )
    centro_marca = m["y"] + m["height"] / 2
    centro_linea = nombre["y"] + nombre["height"] / 2
    assert abs(centro_marca - centro_linea) <= 2, (centro_marca, centro_linea)
