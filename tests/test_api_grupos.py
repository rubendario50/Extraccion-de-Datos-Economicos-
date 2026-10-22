"""/api/series con grupos de países (agregados calculados con los datos de los miembros)."""

import pytest
from sqlalchemy import delete, select

from app.etl.banco_mundial import cargar_bm
from app.etl.fmi import cargar_fmi
from app.models import DatoInternacionalAnual, Fuente, Grupo, Indicador, Pais


@pytest.fixture
def con_datos(cliente_api, sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    return cliente_api


@pytest.fixture
def grupo_prueba(sesion_con_semillas):
    """Grupo de Uruguay, Argentina y Estados Unidos: los tres tienen PBI en los fixtures del FMI."""
    paises = sesion_con_semillas.scalars(select(Pais).where(Pais.iso3.in_(["URY", "ARG", "USA"]))).all()
    sesion_con_semillas.add(Grupo(codigo="PRUEBA", nombre="Grupo de prueba", paises=list(paises)))
    sesion_con_semillas.commit()


def serie(cliente, **params):
    r = cliente.get("/api/series", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def valores(s):
    return {d["anio"]: d["valor"] for d in s["datos"]}


def test_suma_de_un_grupo(con_datos, grupo_prueba):
    cuerpo = serie(con_datos, indicador="PBI_USD_CORR", paises="URY,ARG,USA", grupos="PRUEBA")
    *paises, grupo = cuerpo["series"]
    assert grupo["grupo"] == "PRUEBA" and grupo["nombre"] == "Grupo de prueba" and grupo["pais"] is None
    assert grupo["fuente"] == "FMI_DM"
    assert grupo["agregado"]["metodo"] == "suma"
    assert "Suma" in grupo["agregado"]["descripcion"]
    assert {m["pais"] for m in grupo["agregado"]["miembros"]} == {"URY", "ARG", "USA"}
    assert grupo["agregado"]["fuera"] == []
    completos = 0
    for anio, total in valores(grupo).items():
        del_anio = [valores(p).get(anio) for p in paises]
        if None in del_anio:  # algún país sin dato ese año: el grupo tampoco tiene
            assert total is None
        else:
            completos += 1
            assert total == pytest.approx(sum(del_anio))
    assert completos >= 2
    # Las proyecciones del FMI se marcan igual que en los países.
    assert all("proyeccion" in d for d in grupo["datos"])


def test_solo_grupos_sin_paises(con_datos, grupo_prueba):
    cuerpo = serie(con_datos, indicador="PBI_USD_CORR", grupos="prueba")  # sin distinguir mayúsculas
    assert [s["grupo"] for s in cuerpo["series"]] == ["PRUEBA"]


def test_anio_incompleto_queda_vacio_y_dice_quien_falta(con_datos, grupo_prueba, sesion_con_semillas):
    usa = sesion_con_semillas.scalar(select(Pais.id).where(Pais.iso3 == "USA"))
    sesion_con_semillas.execute(delete(DatoInternacionalAnual).where(
        DatoInternacionalAnual.pais_id == usa, DatoInternacionalAnual.anio == 2010))
    sesion_con_semillas.commit()
    grupo = serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA")["series"][0]
    datos = {d["anio"]: d for d in grupo["datos"]}
    assert datos[2010]["valor"] is None and datos[2010]["faltan"] == ["USA"]
    assert datos[2000]["valor"] is not None and "faltan" not in datos[2000]
    # Estados Unidos sigue entrando en el grupo: solo le falta un año.
    assert "USA" in {m["pais"] for m in grupo["agregado"]["miembros"]}


def test_miembros_que_la_fuente_no_publica_quedan_fuera(con_datos):
    # Mercosur: en los fixtures del FMI solo hay PBI de Argentina y Uruguay.
    grupo = serie(con_datos, indicador="PBI_USD_CORR", grupos="MERCOSUR")["series"][0]
    assert {m["pais"] for m in grupo["agregado"]["miembros"]} == {"ARG", "URY"}
    assert {m["nombre"] for m in grupo["agregado"]["fuera"]} == {"Bolivia", "Brasil", "Paraguay"}
    arg_ury = serie(con_datos, indicador="PBI_USD_CORR", paises="ARG,URY")["series"]
    assert valores(grupo)[2010] == pytest.approx(sum(valores(s)[2010] for s in arg_ury))


def test_promedio_ponderado_por_el_pbi_de_la_misma_fuente(con_datos):
    cuerpo = serie(con_datos, indicador="DEUDA_GOB_GENERAL", grupos="MERCOSUR")
    grupo = cuerpo["series"][0]
    assert grupo["agregado"]["metodo"] == "promedio_ponderado_pbi"
    deuda = {s["pais"]: valores(s) for s in serie(con_datos, indicador="DEUDA_GOB_GENERAL", paises="ARG,URY")["series"]}
    pbi = {s["pais"]: valores(s) for s in serie(con_datos, indicador="PBI_USD_CORR", paises="ARG,URY")["series"]}
    esperado = sum(deuda[p][2010] * pbi[p][2010] for p in deuda) / sum(pbi[p][2010] for p in deuda)
    datos = {d["anio"]: d for d in grupo["datos"]}
    assert datos[2010]["valor"] == pytest.approx(esperado)
    # En 2020 hay deuda pero no PBI (en los fixtures): sin el peso no se calcula.
    assert datos[2020]["valor"] is None and set(datos[2020]["faltan_pbi"]) == {"ARG", "URY"}
    assert "faltan" not in datos[2020]  # tienen el dato de la deuda; lo que falta es el peso


def test_no_mezcla_fuentes_en_los_pesos(cliente_api, sesion_con_semillas, cliente_fmi, cliente_bm):
    # Deuda del gobierno central (solo BM) ponderada con el PBI del BM, aunque también esté el del FMI.
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    pbi = sesion_con_semillas.scalar(
        select(Indicador.id).where(Indicador.codigo == "PBI_USD_CORR"))
    bm = sesion_con_semillas.scalar(select(Fuente.id).where(Fuente.codigo == "BM"))
    grupo = serie(cliente_api, indicador="DEUDA_GOB_CENTRAL", grupos="MERCOSUR")["series"][0]
    assert grupo["fuente"] == "BM"
    # Argentina no tiene deuda del gobierno central en los fixtures (null): queda fuera; entra solo Uruguay.
    assert [m["pais"] for m in grupo["agregado"]["miembros"]] == ["URY"]
    assert valores(grupo) == pytest.approx({2010: 42.4666388141691, 2020: 60.4014234820884})
    # Sin el PBI del BM, el promedio no se calcula (no toma el del FMI).
    sesion_con_semillas.execute(delete(DatoInternacionalAnual).where(
        DatoInternacionalAnual.indicador_id == pbi, DatoInternacionalAnual.fuente_id == bm))
    sesion_con_semillas.commit()
    grupo = serie(cliente_api, indicador="DEUDA_GOB_CENTRAL", grupos="MERCOSUR")["series"][0]
    assert valores(grupo) == {2010: None, 2020: None}


def test_grupo_en_base_100(con_datos, grupo_prueba):
    cuerpo = serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA", base=2000)
    assert cuerpo["base"] == 2000
    datos = valores(cuerpo["series"][0])
    assert datos[2000] == pytest.approx(100)
    sumas = valores(serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA")["series"][0])
    assert datos[2010] == pytest.approx(sumas[2010] / sumas[2000] * 100)


def test_base_100_en_un_anio_incompleto_dice_quien_falta(con_datos, grupo_prueba, sesion_con_semillas):
    usa = sesion_con_semillas.scalar(select(Pais.id).where(Pais.iso3 == "USA"))
    sesion_con_semillas.execute(delete(DatoInternacionalAnual).where(
        DatoInternacionalAnual.pais_id == usa, DatoInternacionalAnual.anio == 2010))
    sesion_con_semillas.commit()
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "grupos": "PRUEBA", "base": 2010})
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert "Grupo de prueba" in detalle and "año base 2010" in detalle and "Estados Unidos" in detalle


def test_grupo_sin_datos_en_la_fuente_vuelve_vacio(con_datos):
    grupo = serie(con_datos, indicador="PBI_USD_CORR", grupos="BRICS")["series"][0]
    assert grupo["datos"] == [] and grupo["agregado"]["miembros"] == []
    assert len(grupo["agregado"]["fuera"]) == 10


def test_rango_de_anios_en_un_grupo(con_datos, grupo_prueba):
    grupo = serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA", desde=2000, hasta=2010)["series"][0]
    assert list(valores(grupo)) == [2000, 2010]


@pytest.mark.parametrize(
    ("params", "estado", "texto"),
    [
        ({"indicador": "PBI_USD_CORR", "grupos": "MERCOSUR,NOEXISTE"}, 404, "Grupos desconocidos: NOEXISTE"),
        ({"indicador": "PBI_USD_CORR", "paises": "URY,ARG,USA,WEOWORLD,BRA,CHL,PRY", "grupos": "G7,BRICS"}, 400, "países y grupos"),
        ({"indicador": "IPC_UY", "grupos": "MERCOSUR"}, 400, "Uruguay"),
        ({"indicador": "PBI_USD_CORR", "grupos": " , "}, 422, "al menos un país o un grupo"),
    ],
)
def test_errores_con_grupos(con_datos, params, estado, texto):
    r = con_datos.get("/api/series", params=params)
    assert r.status_code == estado
    assert texto in r.json()["detail"]


def test_series_de_paises_no_cambian(con_datos):
    # Sin grupos, la respuesta de un país es la de siempre (sin campos de grupo).
    s = serie(con_datos, indicador="PBI_USD_CORR", paises="URY")["series"][0]
    assert set(s) == {"pais", "codigo", "nombre", "fuente", "datos"}


# --- Casos límite agregados por el tester ---


def test_ocho_series_entre_paises_y_grupos_es_el_limite_permitido(con_datos):
    r = con_datos.get("/api/series", params={
        "indicador": "PBI_USD_CORR", "paises": "URY,ARG,USA,WEOWORLD,BRA,CHL", "grupos": "G7,BRICS"})
    assert r.status_code == 200, r.text
    assert len(r.json()["series"]) == 8


def test_grupo_repetido_vuelve_una_sola_vez(con_datos):
    cuerpo = serie(con_datos, indicador="PBI_USD_CORR", grupos="mercosur,MERCOSUR, Mercosur ")
    assert [s["grupo"] for s in cuerpo["series"]] == ["MERCOSUR"]


def test_pais_desconocido_junto_a_un_grupo_da_404(con_datos):
    r = con_datos.get("/api/series", params={"indicador": "PBI_USD_CORR", "paises": "XXX", "grupos": "MERCOSUR"})
    assert r.status_code == 404 and "XXX" in r.json()["detail"]


def test_indicador_sin_regla_de_agregacion_da_400(con_datos, monkeypatch):
    import app.api.series as api_series

    monkeypatch.delitem(api_series.REGLAS, "POBLACION")
    r = con_datos.get("/api/series", params={"indicador": "POBLACION", "grupos": "MERCOSUR"})
    assert r.status_code == 400 and "POBLACION" in r.json()["detail"]
    # Sin grupos, el mismo indicador sigue andando para países.
    assert con_datos.get("/api/series", params={"indicador": "POBLACION", "paises": "URY"}).status_code == 200


def test_grupo_en_base_100_respeta_el_rango(con_datos, grupo_prueba):
    cuerpo = serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA", base=2000, desde=2010, hasta=2010)
    datos = valores(cuerpo["series"][0])
    sumas = valores(serie(con_datos, indicador="PBI_USD_CORR", grupos="PRUEBA")["series"][0])
    assert list(datos) == [2010]
    assert datos[2010] == pytest.approx(sumas[2010] / sumas[2000] * 100)
