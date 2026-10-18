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


# --- Dos fuentes para el mismo indicador ---

@pytest.fixture
def con_dos_fuentes(con_datos, sesion_con_semillas, cliente_bm):
    from app.etl.banco_mundial import cargar_bm

    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    return con_datos


def test_series_por_defecto_usa_el_fmi_sin_mezclar(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG,WEOWORLD"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "FMI_DM" and cuerpo["fuentes"] == ["FMI_DM", "BM"]
    assert all(s["fuente"] == "FMI_DM" for s in cuerpo["series"])
    arg = {d["anio"]: d["valor"] for d in cuerpo["series"][0]["datos"]}
    assert arg == {1980: 233.696, 2000: 317.759, 2010: 424.729, 2024: 637.744}  # solo los años del FMI


def test_series_con_fuente_bm(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG,WEOWORLD", "fuente": "BM"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "BM" and cuerpo["fuente_nombre"] == "Banco Mundial"
    assert cuerpo["indicador"]["escala"] == "Miles de millones"
    assert all(s["fuente"] == "BM" for s in cuerpo["series"])
    arg, mundo = ({d["anio"]: d["valor"] for d in s["datos"]} for s in cuerpo["series"])
    assert set(arg) == {2010, 2020}
    assert arg[2010] == pytest.approx(423.62742209249)  # misma escala que el FMI (424,729)
    assert mundo[2020] == pytest.approx(86388.5028672892)


def test_series_base_100_con_fuente_bm(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "POBLACION", "paises": "URY", "fuente": "BM", "base": 2010})
    assert r.status_code == 200
    datos = {d["anio"]: d["valor"] for d in r.json()["series"][0]["datos"]}
    assert datos[2010] == pytest.approx(100) and datos[2020] == pytest.approx(3398968 / 3318580 * 100)


def test_series_indicador_solo_del_bm_usa_el_bm_por_defecto(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "DEUDA_GOB_CENTRAL", "paises": "URY"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "BM" and cuerpo["fuentes"] == ["BM"]
    assert cuerpo["series"][0]["datos"] == [{"anio": 2010, "valor": pytest.approx(42.4666388141691)},
                                            {"anio": 2020, "valor": pytest.approx(60.4014234820884)}]


def test_series_sin_datos_del_fmi_usa_la_primera_fuente_con_datos(cliente_api, sesion_con_semillas, cliente_bm):
    from app.etl.banco_mundial import cargar_bm

    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)  # solo el BM cargado
    r = cliente_api.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY"})
    assert r.status_code == 200 and r.json()["fuente"] == "BM"


def test_series_fuente_que_no_publica_el_indicador(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "DEUDA_GOB_CENTRAL", "paises": "URY", "fuente": "FMI_DM"})
    assert r.status_code == 404
    assert "FMI_DM no publica DEUDA_GOB_CENTRAL" in r.json()["detail"] and "BM" in r.json()["detail"]


# --- Casos límite del selector de fuente (agregados por el tester) ---

def test_series_fuente_desconocida_da_404(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY", "fuente": "XYZ"})
    assert r.status_code == 404
    assert "Fuente desconocida: XYZ" in r.json()["detail"]


def test_series_fuente_existente_sin_series_del_indicador_da_404(con_dos_fuentes):
    """FRED está en fuentes.csv pero no publica ningún indicador: 404 con las fuentes disponibles."""
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY", "fuente": "FRED"})
    assert r.status_code == 404
    assert "FRED no publica PBI_USD_CORR" in r.json()["detail"]
    assert "FMI_DM, BM" in r.json()["detail"]


def test_series_fmi_explicito_no_trae_datos_del_bm(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "POBLACION", "paises": "URY,WEOWORLD", "fuente": "FMI_DM"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "FMI_DM" and all(s["fuente"] == "FMI_DM" for s in cuerpo["series"])
    ury = {d["anio"]: d["valor"] for d in cuerpo["series"][0]["datos"]}
    assert ury[2010] == pytest.approx(3.397)  # el valor del FMI, no el del BM (3,31858)


def test_series_indicador_sin_datos_en_ninguna_fuente_usa_la_primera(cliente_api, sesion_con_semillas):
    r = cliente_api.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "FMI_DM" and cuerpo["fuentes"] == ["FMI_DM", "BM"]
    assert cuerpo["series"][0]["datos"] == []


def test_series_fuente_bm_con_rango_y_pais_sin_datos(con_dos_fuentes):
    """USA tiene PBI en el FMI pero no en los fixtures del BM: con fuente BM vuelve vacío, sin caer al FMI."""
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "USA", "fuente": "BM"})
    assert r.status_code == 200
    assert r.json()["series"][0]["datos"] == []


def test_series_fuente_sin_distinguir_mayusculas(con_dos_fuentes):
    """Como los países: bm = Bm = BM, y la respuesta trae el código tal como está guardado."""
    for escrita in ("bm", "Bm", " BM "):
        r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "fuente": escrita})
        assert r.status_code == 200, escrita
        assert r.json()["fuente"] == "BM" and r.json()["series"][0]["fuente"] == "BM"
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "fuente": "fmi_dm"})
    assert r.status_code == 200 and r.json()["fuente"] == "FMI_DM"


@pytest.mark.parametrize("vacia", ["", "   "])
def test_series_fuente_vacia_usa_la_fuente_por_defecto(con_dos_fuentes, vacia):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG", "fuente": vacia})
    assert r.status_code == 200
    assert r.json()["fuente"] == "FMI_DM"
    r = con_dos_fuentes.get("/api/series", params={"indicador": "DEUDA_GOB_CENTRAL", "paises": "URY", "fuente": vacia})
    assert r.status_code == 200 and r.json()["fuente"] == "BM"


def test_series_fuente_desconocida_en_minusculas_conserva_lo_escrito(con_dos_fuentes):
    r = con_dos_fuentes.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY", "fuente": "xyz"})
    assert r.status_code == 404 and "Fuente desconocida: xyz" in r.json()["detail"]


def test_series_base_100_ignora_la_serie_sin_datos_en_la_fuente(con_dos_fuentes):
    """USA no tiene PBI en el BM: vuelve vacía y no impide calcular el índice de URY (antes daba 422)."""
    r = con_dos_fuentes.get(
        "/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,USA", "fuente": "BM", "base": 2010}
    )
    assert r.status_code == 200, r.text
    ury, usa = r.json()["series"]
    assert {d["anio"]: d["valor"] for d in ury["datos"]}[2010] == pytest.approx(100)
    assert usa["datos"] == []


def test_series_base_100_ignora_la_serie_sin_datos_en_el_rango(con_datos):
    """URY (FMI) tiene datos desde 2000: entre 1980 y 1990 vuelve vacía aunque no tenga el año base 1980."""
    r = con_datos.get(
        "/api/series", params={"indicador": "PBI_USD_CORR", "paises": "ARG,URY", "desde": 1980, "hasta": 1990, "base": 1980}
    )
    assert r.status_code == 200, r.text
    arg, ury = r.json()["series"]
    assert arg["datos"] == [{"anio": 1980, "valor": pytest.approx(100)}]
    assert all(d["valor"] is None for d in ury["datos"])


def test_series_base_100_con_datos_pero_sin_anio_base_sigue_dando_422(con_dos_fuentes):
    r = con_dos_fuentes.get(
        "/api/series", params={"indicador": "PBI_USD_CORR", "paises": "URY,USA", "fuente": "FMI_DM", "base": 2015}
    )
    assert r.status_code == 422 and "año base 2015" in r.json()["detail"]
