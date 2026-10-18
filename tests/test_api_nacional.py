"""/api/series con indicadores de Uruguay: una sola serie, con fechas en las mensuales y diarias."""

import json
import re
from datetime import date

import pytest

from app.etl.bcu import cargar_bcu
from app.etl.fmi import cargar_fmi
from app.etl.ine import cargar_ine


@pytest.fixture
def con_uruguay(cliente_api, sesion_con_semillas, cliente_ine, cliente_bcu):
    cargar_ine(sesion_con_semillas, cliente_ine, espera=0)
    cargar_bcu(sesion_con_semillas, cliente_bcu, espera=0, hasta=date(2026, 10, 18))
    return cliente_api


def test_serie_mensual_sin_paises(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "IPC_UY"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "INE" and cuerpo["fuentes"] == ["INE"]
    assert cuerpo["indicador"]["alcance"] == "nacional" and cuerpo["indicador"]["frecuencia"] == "mensual"
    (serie,) = cuerpo["series"]
    assert (serie["pais"], serie["nombre"], serie["fuente"]) == ("URY", "Uruguay", "INE")
    assert len(serie["datos"]) == 10
    assert serie["datos"][0] == {"fecha": "1937-07-01", "valor": pytest.approx(1.5944905510e-07)}
    assert {"fecha": "2022-10-01", "valor": 100} in serie["datos"]


def test_rango_por_anios(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "IPC_UY", "paises": "ury", "desde": 2022, "hasta": 2022})
    assert r.status_code == 200
    assert [d["fecha"] for d in r.json()["series"][0]["datos"]] == ["2022-09-01", "2022-10-01", "2022-11-01"]


def test_base_100_toma_el_promedio_del_anio(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "DESEMPLEO_UY", "base": 2006, "desde": 2006, "hasta": 2006})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["base"] == 2006 and "base 100" in cuerpo["indicador"]["unidad"]
    valores = [d["valor"] for d in cuerpo["series"][0]["datos"]]
    assert len(valores) == 12 and sum(valores) / 12 == pytest.approx(100)
    # Enero de 2006 (13,20 %) sobre el promedio de los 12 meses (10,749 %; el "Total 2006" del INE dice 10,751).
    assert valores[0] == pytest.approx(122.72, abs=0.01)


def test_base_sin_datos_en_el_anio_da_422(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "DESEMPLEO_UY", "base": 2010})
    assert r.status_code == 422
    assert "Uruguay" in r.json()["detail"] and "año base 2010" in r.json()["detail"]


def test_serie_diaria_del_bcu(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "DOLAR_INTERBANCARIO"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "BCU" and cuerpo["indicador"]["frecuencia"] == "diaria"
    assert cuerpo["indicador"]["unidad"] == "Pesos uruguayos por dólar"
    datos = cuerpo["series"][0]["datos"]
    assert len(datos) == 11
    assert datos[0] == {"fecha": "2026-10-01", "valor": 40.463} and datos[-1] == {"fecha": "2026-10-16", "valor": 40.097}


def test_otro_pais_da_400(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "IPC_UY", "paises": "URY,ARG"})
    assert r.status_code == 400
    assert "Uruguay" in r.json()["detail"] and "ARG" in r.json()["detail"]


def test_fuente_que_no_publica_el_indicador_nacional(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "IPC_UY", "fuente": "BCU"})
    assert r.status_code == 404
    assert "BCU no publica IPC_UY" in r.json()["detail"]


def test_sin_datos_cargados_devuelve_la_serie_vacia(cliente_api):
    r = cliente_api.get("/api/series", params={"indicador": "DOLAR_INTERBANCARIO"})
    assert r.status_code == 200
    assert r.json()["series"][0]["datos"] == [] and r.json()["fuente"] == "BCU"


def test_los_internacionales_siguen_pidiendo_paises(con_uruguay):
    r = con_uruguay.get("/api/series", params={"indicador": "PBI_USD_CORR"})
    assert r.status_code == 422 and "al menos un país" in r.json()["detail"]


def test_datos_del_panel_con_indicadores_nacionales(con_uruguay, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    html = con_uruguay.get("/").text
    datos = json.loads(re.search(r'<script type="application/json" id="datos-panel">(.*?)</script>', html, re.S).group(1))
    codigos = [i["codigo"] for i in datos["indicadores"]]
    # Primero los internacionales y después los de Uruguay.
    assert codigos[0] == "PBI_USD_CORR" and codigos[-3:] == ["IPC_UY", "DESEMPLEO_UY", "DOLAR_INTERBANCARIO"]
    ipc = next(i for i in datos["indicadores"] if i["codigo"] == "IPC_UY")
    assert (ipc["alcance"], ipc["frecuencia"], ipc["fuente"]) == ("nacional", "mensual", "INE")
    (ine,) = ipc["fuentes"]
    assert (ine["desde"], ine["hasta"], ine["paises"], ine["corto"]) == (1937, 2026, ["URY"], "INE")
    dolar = next(i for i in datos["indicadores"] if i["codigo"] == "DOLAR_INTERBANCARIO")
    assert (dolar["desde"], dolar["hasta"], dolar["fuentes"][0]["corto"]) == (2026, 2026, "BCU")
    # El selector agrupa los indicadores.
    assert '<optgroup label="Internacionales">' in html and '<optgroup label="Uruguay">' in html
