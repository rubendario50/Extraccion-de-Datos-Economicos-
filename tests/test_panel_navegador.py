"""Panel en un navegador real (Playwright + Chromium): lo que solo se ve con el JavaScript corriendo.

Se saltean si Playwright o su Chromium no están instalados (`pip install playwright && playwright install chromium`).
"""

import re
import secrets
import threading
import time
from datetime import date

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sync_api = pytest.importorskip("playwright.sync_api")

import app.models  # noqa: F401,E402
from app.auth.seguridad import hash_token, hashear_password  # noqa: E402
from app.auth.sesiones import COOKIE_SESION, DURACION, ahora  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.etl.banco_mundial import cargar_bm  # noqa: E402
from app.etl.bcu import cargar_bcu  # noqa: E402
from app.etl.fmi import cargar_fmi  # noqa: E402
from app.etl.ine import cargar_ine  # noqa: E402
from app.etl.semillas import cargar_semillas  # noqa: E402
from app.main import app as aplicacion  # noqa: E402
from app.models import IndicadorSerieExterna, Sesion, Usuario  # noqa: E402
from tests.ayudas import PASSWORD  # noqa: E402
from tests.conftest import transporte_bcu, transporte_bm, transporte_fmi, transporte_ine  # noqa: E402

PUERTO = 8799
BASE = f"http://127.0.0.1:{PUERTO}"


@pytest.fixture(scope="module")
def servidor():
    """App con los datos de los fixtures (FMI, BM, INE y BCU), servida por uvicorn en un hilo. Devuelve el token de sesión."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Hacer = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Hacer() as s:
        cargar_semillas(s)
        with httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test") as c:
            cargar_fmi(s, c, espera=0)
        # Como si el PBI del FMI fuera de la edición del WEO de 2011: su dato de 2024 queda como proyección.
        s.execute(update(IndicadorSerieExterna).where(IndicadorSerieExterna.codigo_externo == "NGDPD")
                  .values(proyeccion_desde=2011))
        with httpx.Client(transport=transporte_bm(), base_url="https://bm.test") as c:
            cargar_bm(s, c, espera=0)
        with httpx.Client(transport=transporte_ine(), base_url="https://ine.test/documents") as c:
            cargar_ine(s, c, espera=0)
        with httpx.Client(transport=transporte_bcu(), base_url="https://bcu.test/servlet") as c:
            cargar_bcu(s, c, espera=0, hasta=date(2026, 10, 18))
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
                  .series.map((s) => [s.name, Boolean(s.endLabel && s.endLabel.show)])"""
    )
    por_pais = {}
    for nombre, visible in etiquetas:
        if nombre != "Proyección del FMI":  # la serie auxiliar de la banda
            por_pais.setdefault(nombre, []).append(visible)
    # El 2024 del PBI es proyección en el servidor de prueba: la etiqueta va al final del tramo punteado.
    assert por_pais == {"Uruguay": [False, True], "Brasil": [False], "Argentina": [False, True]}
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


# --- Series de Uruguay (INE y BCU): una sola serie, eje de fechas ---

def opcion_grafica(pg, js):
    return pg.evaluate(f"() => {{ const o = echarts.getInstanceByDom(document.getElementById('grafica')).getOption(); return {js}; }}")


def test_serie_mensual_de_uruguay_con_eje_de_fechas(pagina):
    pagina.goto(f"{BASE}/?indicador=IPC_UY&desde=1937")
    esperar_carga(pagina)
    assert not pagina.locator("#estado").is_visible()
    # En lugar del buscador de países, la serie fija de Uruguay.
    assert pagina.locator("#serie-fija").is_visible() and not pagina.locator("#selector-paises").is_visible()
    assert pagina.inner_text("#serie-fija") == "Uruguay"
    assert pagina.inner_text("#etiqueta-paises") == "País"
    assert "paises=" not in pagina.evaluate("() => performance.getEntriesByType('resource').filter((r) => r.name.includes('/api/series')).pop().name")
    assert opcion_grafica(pagina, "o.xAxis[0].type") == "time"
    assert opcion_grafica(pagina, "o.series.map((s) => [s.name, s.data.length])") == [["Uruguay", 10]]
    assert pagina.inner_text("#fuente-serie") == "Fuente: Instituto Nacional de Estadística (INE)"
    assert pagina.locator("#fuente option").all_inner_texts() == ["INE"]
    # Tabla por mes: el IPC de 1937 (0,00000016 en base 2022) se ve con cifras significativas, no como 0,0.
    assert pagina.locator("#tabla thead th").first.inner_text() == "Mes"
    filas = pagina.locator("#tabla tbody tr:not(.fila-grupo)").all_inner_texts()
    assert len(filas) == 10
    assert "1937" in filas[0] and "0,000000159" in filas[0]
    assert any("2022" in f and "100,0" in f for f in filas)
    assert "Unidades" not in pagina.inner_text("#unidad-serie")


def test_serie_diaria_del_dolar(pagina):
    pagina.goto(f"{BASE}/?indicador=DOLAR_INTERBANCARIO")
    esperar_carga(pagina)
    assert not pagina.locator("#estado").is_visible()
    assert opcion_grafica(pagina, "o.xAxis[0].type") == "time"
    assert pagina.locator("#tabla thead th").first.inner_text() == "Fecha"
    filas = pagina.locator("#tabla tbody tr:not(.fila-grupo)").all_inner_texts()
    assert len(filas) == 11
    # Con los 3 decimales que publica el BCU.
    assert filas[0].startswith("01/10/2026") and "40,463" in filas[0]
    assert filas[-1].startswith("16/10/2026") and "40,097" in filas[-1]
    assert "Banco Central del Uruguay" in pagina.inner_text("#fuente-serie")
    # El tooltip muestra la fecha, no el instante en milisegundos.
    caja = pagina.locator("#grafica").bounding_box()
    pagina.mouse.move(caja["x"] + caja["width"] * 0.5, caja["y"] + caja["height"] * 0.4)
    pagina.wait_for_timeout(400)
    tooltip = pagina.locator(".tooltip-grafica .tt-anio")
    assert re.fullmatch(r"\d{2}/10/2026", tooltip.inner_text())


def test_base_100_en_serie_de_uruguay(pagina):
    pagina.goto(f"{BASE}/?indicador=IPC_UY&desde=2022&hasta=2026&base=2022")
    esperar_carga(pagina)
    assert not pagina.locator("#estado").is_visible()
    assert "2022 = 100" in pagina.inner_text("#unidad-serie")
    assert opcion_grafica(pagina, "o.series[0].markLine.data[0].yAxis") == 100


def test_ida_y_vuelta_entre_internacional_y_uruguay(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    pagina.select_option("#indicador", "DESEMPLEO_UY")
    esperar_carga(pagina)
    assert pagina.locator("#serie-fija").is_visible() and not pagina.locator("#selector-paises").is_visible()
    assert pagina.locator("#fuente").input_value() == "INE"
    assert opcion_grafica(pagina, "o.series.length") == 1
    assert rango(pagina) == ("2006", "2026")
    pagina.select_option("#indicador", "PBI_USD_CORR")
    esperar_carga(pagina)
    # Vuelven el buscador y los países elegidos antes.
    assert pagina.locator("#selector-paises").is_visible() and not pagina.locator("#serie-fija").is_visible()
    assert pagina.locator("#fichas .ficha").count() == 2
    assert opcion_grafica(pagina, "o.xAxis[0].type") == "category"
    assert pagina.inner_text("#etiqueta-paises") == "Países y regiones"


def test_390px_serie_diaria_sin_scroll_horizontal(servidor, navegador):
    ctx = navegador.new_context(viewport={"width": 390, "height": 844})
    ctx.add_cookies([{"name": COOKIE_SESION, "value": servidor, "url": BASE}])
    pg = ctx.new_page()
    try:
        pg.goto(f"{BASE}/?indicador=DOLAR_INTERBANCARIO")
        esperar_carga(pg)
        assert pg.evaluate("() => document.documentElement.scrollWidth") <= 390
    finally:
        ctx.close()


def test_tabla_de_serie_mensual_agrupada_por_anio_con_el_anio_fijo(pagina):
    pagina.goto(f"{BASE}/?indicador=IPC_UY&desde=1937")
    esperar_carga(pagina)
    datos = pagina.locator("#tabla tbody tr:not(.fila-grupo) th").all_inner_texts()
    anios = sorted({re.search(r"\d{4}", d).group(0) for d in datos})
    # Un <tbody> por año, encabezado por una fila con el año (scope="rowgroup"), sin perder filas.
    grupos = pagina.locator("#tabla tbody .fila-grupo th[scope=rowgroup]")
    assert grupos.all_inner_texts() == anios
    assert pagina.locator("#tabla tbody").count() == len(anios)
    for tb in pagina.locator("#tabla tbody").all():
        anio = tb.locator(".fila-grupo th").inner_text()
        assert all(anio in t for t in tb.locator("tr:not(.fila-grupo) th").all_inner_texts())
    # El año queda fijo justo debajo del encabezado al desplazar la tabla.
    alto_cabeza = pagina.locator("#tabla thead").evaluate("e => e.offsetHeight")
    estilo = grupos.first.evaluate("e => [getComputedStyle(e).position, getComputedStyle(e).top]")
    assert estilo == ["sticky", f"{alto_cabeza}px"]
    # Cifras significativas con ceros finales: la columna se lee pareja.
    assert all(re.fullmatch(r"\d+,\d+", v) for v in pagina.locator("#tabla tbody td").all_inner_texts())


def test_series_anuales_sin_grupos_por_anio(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    assert pagina.locator("#tabla .fila-grupo").count() == 0
    assert pagina.locator("#tabla tbody").count() == 1


def test_serie_de_uruguay_sin_leyenda_ni_etiqueta_final(pagina):
    pagina.goto(f"{BASE}/?indicador=DESEMPLEO_UY")
    esperar_carga(pagina)
    # Una sola serie fija: ocultarla con la leyenda dejaría la gráfica vacía, y el nombre ya está en el control.
    assert pagina.locator("#leyenda li").count() == 0 and not pagina.locator("#leyenda").is_visible()
    assert opcion_grafica(pagina, "o.series[0].endLabel.show") is False
    # Fuente única: se muestra como dato fijo y sin la ayuda de "las fuentes no se mezclan".
    assert pagina.locator("#fuente").is_disabled()
    assert not pagina.locator("#ayuda-fuente").is_visible()
    pagina.select_option("#indicador", "PBI_USD_CORR")
    esperar_carga(pagina)
    assert pagina.locator("#leyenda button.leyenda-item").count() >= 1
    assert pagina.locator("#ayuda-fuente").is_visible()


def test_eje_y_legible_con_valores_chicos_del_ipc(pagina):
    # El IPC de 1937 vale ~0,00000016 (base 2022): el eje no puede mostrar todas las marcas como "0".
    pagina.goto(f"{BASE}/?indicador=IPC_UY&desde=1937&hasta=1937")
    esperar_carga(pagina)
    etiquetas = pagina.evaluate(
        """() => {
            const g = echarts.getInstanceByDom(document.getElementById('grafica'));
            const eje = g.getModel().getComponent('yAxis', 0).axis;
            const fmt = g.getOption().yAxis[0].axisLabel.formatter;
            return eje.scale.getTicks().map((t) => fmt(t.value));
        }"""
    )
    assert len(set(etiquetas)) == len(etiquetas), etiquetas


def test_tema_oscuro_por_defecto_y_claro_recordado(pagina):
    # La identidad es oscura aunque el sistema pida claro; el botón cambia al claro y la elección queda guardada.
    pagina.emulate_media(color_scheme="light")
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&paises=URY")
    esperar_carga(pagina)
    assert pagina.evaluate("() => document.documentElement.dataset.tema") == "oscuro"
    boton = pagina.locator(".barra [data-cambiar-tema]")
    assert boton.get_attribute("aria-pressed") == "false"
    fondo_oscuro = pagina.evaluate("() => getComputedStyle(document.body).backgroundColor")
    boton.click()
    assert pagina.evaluate("() => document.documentElement.dataset.tema") == "claro"
    assert boton.get_attribute("aria-pressed") == "true"
    assert pagina.evaluate("() => getComputedStyle(document.body).backgroundColor") != fondo_oscuro
    pagina.goto(f"{BASE}/login")
    assert pagina.evaluate("() => document.documentElement.dataset.tema") == "claro"


# --- Proyecciones del FMI (en el servidor de prueba, el PBI del FMI se proyecta desde 2011: su 2024 lo es) ---

def series_de_la_grafica(pg):
    return opcion_grafica(pg, """o.series.map((s) => ({
        nombre: s.name, data: s.data, punteada: Array.isArray(s.lineStyle && s.lineStyle.type),
        banda: s.markArea && s.markArea.data && s.markArea.data.length ? s.markArea.data[0].map((p) => p.xAxis) : null }))""")


def test_proyecciones_del_fmi_en_la_grafica(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    assert opcion_grafica(pagina, "o.xAxis[0].data") == ["1980", "2000", "2010", "2024"]
    series = series_de_la_grafica(pagina)
    # Primero la serie auxiliar de la banda: va del último año real (donde arranca el punteado) al final.
    assert series[0]["nombre"] == "Proyección del FMI" and series[0]["banda"] == ["2010", "2024"]
    tramos = {(s["nombre"], s["punteada"]): s["data"] for s in series[1:]}
    assert tramos[("Argentina", False)] == [233.696, 317.759, 424.729, None]
    assert tramos[("Argentina", True)] == [None, None, 424.729, 637.744]
    assert ("Uruguay", True) in tramos
    # Clave en la leyenda (no es un botón) y descripción para lectores de pantalla.
    assert pagina.inner_text(".leyenda-proyeccion") == "Proyección del FMI desde 2024"
    assert pagina.locator("button.leyenda-item").count() == 2
    assert "Desde 2024, proyección del FMI (línea punteada)." in pagina.get_attribute("#grafica", "aria-label")


def test_proyecciones_del_fmi_en_el_tooltip_y_la_leyenda(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    xy = pagina.evaluate("""() => { const g = echarts.getInstanceByDom(document.getElementById('grafica'));
        const r = document.getElementById('grafica').getBoundingClientRect();
        const [x, y] = g.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, ['2024', 300]); return [r.x + x, r.y + y]; }""")
    pagina.mouse.move(xy[0] - 40, xy[1])
    pagina.mouse.move(xy[0], xy[1], steps=5)
    pagina.wait_for_timeout(400)
    assert pagina.inner_text(".tooltip-grafica .tt-proyeccion") == "Proyección del FMI"
    # Un renglón por país aunque cada uno tenga dos tramos.
    assert pagina.locator(".tooltip-grafica .tt-fila").count() == 2
    # Ocultar un país con la leyenda oculta sus dos tramos (van por nombre).
    pagina.locator('button.leyenda-item[data-codigo="ARG"]').click()
    assert opcion_grafica(pagina, "o.legend[0].selected['Argentina']") is False


def test_proyecciones_del_fmi_en_la_tabla(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
    esperar_carga(pagina)
    filas = pagina.locator("#tabla tbody tr")
    assert filas.count() == 4
    proyectadas = pagina.locator("#tabla tbody tr.fila-proyeccion")
    assert proyectadas.count() == 1 and proyectadas.locator("th").inner_text().startswith("2024")
    # Marcada con texto, no solo con color: «proy.» a la vista y "(proyección)" para lectores de pantalla.
    assert proyectadas.locator(".marca-proyeccion").inner_text() == "proy."
    assert proyectadas.locator(".oculto-visual").inner_text().strip() == "(proyección)"
    assert "inicio-proyeccion" in proyectadas.get_attribute("class")
    assert "«proy.»: proyección del FMI, desde 2024." in pagina.inner_text("#nota-tabla")
    # El fondo de la fila proyectada se distingue del de las reales.
    fondo = "e => getComputedStyle(e).backgroundColor"
    assert proyectadas.locator("td").first.evaluate(fondo) != filas.first.locator("td").first.evaluate(fondo)


def test_proyecciones_fuera_del_rango_no_se_marcan(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG&hasta=2010")
    esperar_carga(pagina)
    assert pagina.locator(".leyenda-proyeccion").count() == 0
    assert pagina.locator("#tabla .fila-proyeccion").count() == 0
    assert all(s["banda"] is None and not s["punteada"] for s in series_de_la_grafica(pagina))


def test_banco_mundial_sin_proyecciones(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=BM&paises=URY,ARG")
    esperar_carga(pagina)
    assert pagina.locator(".leyenda-proyeccion").count() == 0
    assert pagina.locator("#tabla .fila-proyeccion").count() == 0
    assert "proy." not in pagina.inner_text("#nota-tabla")
    assert [s["nombre"] for s in series_de_la_grafica(pagina)] == ["Uruguay", "Argentina"]


# --- Proyecciones: casos agregados por el tester ---

def textos_dibujados(pg):
    """Textos que ECharts dibujó de verdad en el lienzo (no solo los que están en la opción)."""
    return pg.evaluate("""() => echarts.getInstanceByDom(document.getElementById('grafica')).getZr().storage
        .getDisplayList().map((e) => e.style && e.style.text).filter(Boolean)""")


def test_banda_se_dibuja_aunque_la_primera_serie_no_tenga_datos(pagina):
    # BRA no tiene PBI del FMI y va primero: la serie auxiliar de la banda copia sus datos (todos vacíos).
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=BRA,URY,ARG")
    esperar_carga(pagina)
    assert pagina.inner_text(".leyenda-proyeccion") == "Proyección del FMI desde 2024"
    assert "Proyección del FMI" in textos_dibujados(pagina)


def test_una_sola_serie_con_proyeccion(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=ARG")
    esperar_carga(pagina)
    series = series_de_la_grafica(pagina)
    assert [(s["nombre"], s["punteada"]) for s in series] == [
        ("Proyección del FMI", False), ("Argentina", False), ("Argentina", True)]
    assert pagina.locator("#tabla tbody tr.fila-proyeccion").count() == 1


def test_base_100_en_un_anio_proyectado(pagina):
    pagina.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG&base=2024")
    esperar_carga(pagina)
    assert not pagina.locator("#estado").is_visible()
    assert pagina.inner_text(".leyenda-proyeccion") == "Proyección del FMI desde 2024"
    fila = pagina.locator("#tabla tbody tr.fila-proyeccion")
    assert fila.count() == 1 and "100,0" in fila.inner_text()
    # La línea del 100 sigue en la primera serie real (no en la auxiliar de la banda).
    assert opcion_grafica(pagina, "o.series.filter((s) => s.markLine && s.markLine.data.some((d) => d.yAxis === 100)).map((s) => s.name)") == ["Uruguay"]


def test_390px_con_proyecciones_sin_scroll_horizontal(servidor, navegador):
    for tema in ("oscuro", "claro"):
        ctx = navegador.new_context(viewport={"width": 390, "height": 844})
        ctx.add_cookies([{"name": COOKIE_SESION, "value": servidor, "url": BASE}])
        ctx.add_init_script(f"localStorage.setItem('tema', '{tema}')")
        pg = ctx.new_page()
        try:
            pg.goto(f"{BASE}/?indicador=PBI_USD_CORR&fuente=FMI_DM&paises=URY,ARG")
            esperar_carga(pg)
            assert pg.evaluate("() => document.documentElement.scrollWidth") <= 390
            assert pg.locator(".leyenda-proyeccion").is_visible()
        finally:
            ctx.close()
