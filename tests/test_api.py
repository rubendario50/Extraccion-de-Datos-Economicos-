import pytest

from app.etl.fmi import cargar_fmi


@pytest.fixture
def con_datos(cliente_api, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    return cliente_api


def test_salud(cliente_api):
    r = cliente_api.get("/salud")
    assert r.status_code == 200 and r.json() == {"estado": "ok"}


def test_series(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,ARG", "desde": 2000, "hasta": 2010})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["indicador"]["codigo"] == "PBI_USD_CORR" and cuerpo["fuente"] == "FMI_DM" and cuerpo["base"] is None
    assert [s["pais"] for s in cuerpo["series"]] == ["URY", "ARG"]
    arg = cuerpo["series"][1]
    assert arg["nombre"] == "Argentina"
    assert arg["datos"] == [{"anio": 2000, "valor": 317.759}, {"anio": 2010, "valor": 424.729}]


def test_series_agregado_y_minusculas(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "WEOWORLD,usa"})
    assert r.status_code == 200
    mundo, eeuu = r.json()["series"]
    assert mundo["nombre"] == "Mundo" and len(mundo["datos"]) == 4
    assert eeuu["nombre"] == "Estados Unidos"


def test_series_base_100(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "desde": 2010, "base": 2000})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["base"] == 2000 and "base 100" in cuerpo["indicador"]["unidad"]
    datos = {d["anio"]: d["valor"] for d in cuerpo["series"][0]["datos"]}
    assert set(datos) == {2010, 2024}  # el año base puede quedar fuera del rango pedido
    assert datos[2010] == pytest.approx(424.729 / 317.759 * 100)


def test_series_base_sin_dato(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG,URY", "base": 1980})
    assert r.status_code == 422
    assert "Uruguay" in r.json()["detail"] and "1980" in r.json()["detail"]


@pytest.mark.parametrize(
    ("params", "estado", "texto"),
    [
        ({"indicador": "NO_EXISTE", "paises": "URY"}, 404, "Indicador desconocido"),
        ({"indicador": "PBI_USD_CORR", "paises": "URY,XXX"}, 404, "XXX"),
        ({"indicador": "PBI_USD_CORR", "paises": " , "}, 422, "al menos un país"),
        ({"indicador": "PBI_USD_CORR", "paises": "URY", "desde": 2010, "hasta": 2000}, 422, "desde"),
        ({"indicador": "PBI_USD_CORR", "paises": "URY", "fuente": "OTRA"}, 404, "Fuente"),
    ],
)
def test_series_errores(con_datos, params, estado, texto):
    r = con_datos.get("/api/series", params=params)
    assert r.status_code == estado
    assert texto in r.json()["detail"]


def test_series_faltan_parametros(cliente_api):
    assert cliente_api.get("/api/series").status_code == 422


# --- Casos límite agregados por el tester ---

@pytest.mark.parametrize("base", [1800, 2100, 2005])
def test_series_base_fuera_del_rango_de_datos(con_datos, base):
    # 2005 está dentro del rango de años pero no hay dato en el fixture.
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "base": base})
    assert r.status_code == 422
    assert str(base) in r.json()["detail"]


def test_series_desde_igual_a_hasta(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "desde": 2010, "hasta": 2010})
    assert r.status_code == 200
    assert r.json()["series"][0]["datos"] == [{"anio": 2010, "valor": 424.729}]


def test_series_rango_sin_datos(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "desde": 1900, "hasta": 1950})
    assert r.status_code == 200
    assert r.json()["series"][0]["datos"] == []


def test_series_base_100_en_el_anio_base_vale_100(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,ARG,WEOWORLD", "base": 2010})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["indicador"]["escala"] is None
    for serie in cuerpo["series"]:
        datos = {d["anio"]: d["valor"] for d in serie["datos"]}
        assert datos[2010] == pytest.approx(100)


def test_series_pais_repetido_no_duplica(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,URY, URY "})
    assert r.status_code == 200
    assert [s["pais"] for s in r.json()["series"]] == ["URY"]


@pytest.mark.parametrize("params", [
    {"desde": "dosmil"}, {"hasta": "2000.5"}, {"base": "abc"},
])
def test_series_anios_no_numericos(con_datos, params):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY"} | params)
    assert r.status_code == 422


def test_series_paises_vacio(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": ""})
    assert r.status_code == 422


def test_series_indicador_nacional_da_400(con_datos, sesion_con_semillas):
    from app.models import Indicador

    sesion_con_semillas.add(Indicador(codigo="UY_IPC", nombre="IPC", unidad="Índice", alcance="nacional", frecuencia="mensual"))
    sesion_con_semillas.commit()
    r = con_datos.get("/api/series", params={"indicador": "UY_IPC", "paises": "URY"})
    assert r.status_code == 400


def test_series_varios_paises_inexistentes_los_lista(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "XXX,URY,<script>"})
    assert r.status_code == 404
    assert "XXX" in r.json()["detail"] and "<script>" in r.json()["detail"]
    assert r.headers["content-type"].startswith("application/json")


def test_series_mismo_pais_en_minusculas_no_duplica(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,ury,arg,Ury"})
    assert r.status_code == 200
    assert [s["pais"] for s in r.json()["series"]] == ["URY", "ARG"]


def test_series_codigo_del_fmi_con_minusculas(con_datos, sesion_con_semillas):
    from sqlalchemy import select

    from app.models import PaisCodigoExterno

    codigo = sesion_con_semillas.scalar(select(PaisCodigoExterno.codigo).where(PaisCodigoExterno.codigo == "FAD_EuroArea"))
    assert codigo is not None
    for pedido in ["FAD_EuroArea", "fad_euroarea"]:
        r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": pedido})
        assert r.status_code == 200 and r.json()["series"][0]["pais"] == "FAD_EuroArea"


def test_series_maximo_8_paises(con_datos):
    ocho = "URY,ARG,BRA,CHL,USA,WEOWORLD,PRY,MEX"
    assert con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": ocho}).status_code == 200
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": ocho + ",PER"})
    assert r.status_code == 400 and "hasta 8 países" in r.json()["detail"]


def test_api_sin_cache(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY"})
    assert r.headers["cache-control"] == "no-store"
    assert con_datos.get("/api/no-existe").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_sin_documentacion_publica(cliente_web, cliente_api, ruta):
    assert cliente_api.get(ruta).status_code == 404


def test_series_repetidos_no_cuentan_para_el_maximo(con_datos):
    # 20 veces Uruguay + Argentina = 2 países distintos: no supera el máximo.
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": ",".join(["URY", "ury"] * 10 + ["ARG"])})
    assert r.status_code == 200
    assert [s["pais"] for s in r.json()["series"]] == ["URY", "ARG"]
