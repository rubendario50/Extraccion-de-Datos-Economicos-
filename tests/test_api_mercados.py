"""/api/series y el panel con las cotizaciones de bolsa y materias primas (FRED)."""

import json
import re

import pytest

from app.etl.fred import cargar_fred
from tests.conftest import CLAVE_FRED


@pytest.fixture
def con_fred(cliente_api, sesion_con_semillas, cliente_fred):
    cargar_fred(sesion_con_semillas, cliente_fred, espera=0, clave=CLAVE_FRED)
    return cliente_api


def test_serie_diaria_sin_paises(con_fred):
    r = con_fred.get("/api/series", params={"indicador": "PETROLEO_WTI"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["indicador"]["alcance"] == "mercados" and cuerpo["indicador"]["frecuencia"] == "diaria"
    assert cuerpo["indicador"]["unidad"] == "Dólares por barril"
    assert cuerpo["fuente"] == "FRED" and cuerpo["proyeccion_desde"] is None
    (serie,) = cuerpo["series"]
    assert serie["pais"] is None and serie["nombre"] == "Petróleo WTI" and serie["fuente"] == "FRED"
    assert serie["datos"][0] == {"fecha": "2025-12-22", "valor": 58.18}
    assert len(serie["datos"]) == 13  # sin los feriados ("." en FRED)


def test_rango_por_anios(con_fred):
    datos = con_fred.get("/api/series", params={"indicador": "SP500", "desde": 2026}).json()["series"][0]["datos"]
    assert [d["fecha"] for d in datos][0] == "2026-01-02" and len(datos) == 6


def test_base_100_toma_el_promedio_del_anio(con_fred):
    normal = con_fred.get("/api/series", params={"indicador": "SP500"}).json()["series"][0]["datos"]
    del_2026 = [d["valor"] for d in normal if d["fecha"].startswith("2026")]
    promedio = sum(del_2026) / len(del_2026)
    cuerpo = con_fred.get("/api/series", params={"indicador": "SP500", "base": 2026}).json()
    assert cuerpo["base"] == 2026 and "base 100" in cuerpo["indicador"]["unidad"]
    indice = {d["fecha"]: d["valor"] for d in cuerpo["series"][0]["datos"]}
    assert indice["2026-01-02"] == pytest.approx(6858.47 / promedio * 100)


def test_base_sin_datos_da_422(con_fred):
    r = con_fred.get("/api/series", params={"indicador": "SP500", "base": 2010})
    assert r.status_code == 422 and "S&P 500" in r.json()["detail"] and "2010" in r.json()["detail"]


@pytest.mark.parametrize(
    ("params", "texto"),
    [
        ({"indicador": "SP500", "grupos": "G7"}, "cotización de mercado: no se puede pedir por grupos"),
        ({"indicador": "SP500", "paises": "USA"}, "cotización de mercado: no va por países (USA)"),
    ],
)
def test_no_va_por_paises_ni_grupos(con_fred, params, texto):
    r = con_fred.get("/api/series", params=params)
    assert r.status_code == 400 and texto in r.json()["detail"]


def test_sin_datos_cargados_devuelve_la_serie_vacia(cliente_api):
    r = cliente_api.get("/api/series", params={"indicador": "NASDAQ"})
    assert r.status_code == 200
    assert r.json()["series"][0]["datos"] == []


def test_datos_del_panel_con_mercados(con_fred):
    html = con_fred.get("/").text
    datos = json.loads(re.search(r'<script type="application/json" id="datos-panel">(.*?)</script>', html, re.S).group(1))
    sp = next(i for i in datos["indicadores"] if i["codigo"] == "SP500")
    assert (sp["alcance"], sp["frecuencia"], sp["fuente"], sp["agregacion"]) == ("mercados", "diaria", "FRED", None)
    (fred,) = sp["fuentes"]
    assert (fred["desde"], fred["hasta"], fred["corto"], fred["paises"]) == (2025, 2026, "FRED", [])
    assert fred["nombre"] == "FRED, Banco de la Reserva Federal de St. Louis"
    assert '<optgroup label="Bolsa y materias primas">' in html
