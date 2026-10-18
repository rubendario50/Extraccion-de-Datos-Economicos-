import logging

import httpx
import pytest
from sqlalchemy import func, select

from app.etl.banco_mundial import cargar_bm, obtener_todo
from app.etl.fmi import cargar_fmi
from app.models import DatoInternacionalAnual, Fuente, Indicador, Pais
from tests.conftest import transporte_bm


def valor(sesion, iso3_o_nombre, indicador, anio, fuente="BM"):
    return sesion.scalar(
        select(DatoInternacionalAnual.valor)
        .join(Pais, Pais.id == DatoInternacionalAnual.pais_id)
        .join(Indicador, Indicador.id == DatoInternacionalAnual.indicador_id)
        .join(Fuente, Fuente.id == DatoInternacionalAnual.fuente_id)
        .where(Indicador.codigo == indicador, DatoInternacionalAnual.anio == anio, Fuente.codigo == fuente)
        .where((Pais.iso3 == iso3_o_nombre) | (Pais.nombre_en == iso3_o_nombre))
    )


def total(sesion):
    return sesion.scalar(select(func.count()).select_from(DatoInternacionalAnual))


def fila(iso3, anio, valor, codigo="NY.GDP.MKTP.CD", id2="XX"):
    return {"indicator": {"id": codigo, "value": ""}, "country": {"id": id2, "value": ""},
            "countryiso3code": iso3, "date": str(anio), "value": valor}


def test_carga_todos_los_indicadores(sesion_con_semillas, cliente_bm):
    resultado = cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    # ARG, URY y Mundo x 2 años; LCN y el grupo de ingreso sin ISO3 se omiten.
    assert resultado == {
        "GC.DOD.TOTL.GD.ZS": 2,  # Argentina sin datos (null)
        "NE.EXP.GNFS.CD": 4,
        "NE.IMP.GNFS.CD": 4,
        "NY.GDP.MKTP.CD": 6,
        "NY.GDP.MKTP.KD.ZG": 6,
        "SP.POP.TOTL": 6,
    }
    assert valor(sesion_con_semillas, "URY", "PBI_CRECIMIENTO", 2010) == pytest.approx(7.8034096507169)
    assert valor(sesion_con_semillas, "URY", "DEUDA_GOB_CENTRAL", 2020) == pytest.approx(60.4014234820884)
    assert valor(sesion_con_semillas, "ARG", "DEUDA_GOB_CENTRAL", 2020) is None
    assert valor(sesion_con_semillas, "World", "POBLACION", 2020) == pytest.approx(7853.863139)


def test_escala_igual_a_la_del_fmi(sesion_con_semillas, cliente_bm, cliente_fmi):
    """El BM publica dólares y personas; se guardan en miles de millones y millones, como el FMI."""
    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    pbi_bm = valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 2010)
    pbi_fmi = valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 2010, fuente="FMI_DM")
    assert pbi_bm == pytest.approx(423.62742209249)
    assert pbi_bm == pytest.approx(pbi_fmi, rel=0.01)  # 423,6 (BM) contra 424,7 (FMI)
    assert valor(sesion_con_semillas, "URY", "POBLACION", 2010) == pytest.approx(3.31858)
    assert valor(sesion_con_semillas, "URY", "POBLACION", 2010, fuente="FMI_DM") == pytest.approx(3.397)
    assert valor(sesion_con_semillas, "URY", "EXPORTACIONES_USD", 2020) == pytest.approx(14.0262586421459)
    # El crecimiento ya es un porcentaje: no se escala.
    assert valor(sesion_con_semillas, "ARG", "PBI_CRECIMIENTO", 2020) == pytest.approx(-9.9004848136464)


def test_las_dos_fuentes_conviven_sin_pisarse(sesion_con_semillas, cliente_bm, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    antes = total(sesion_con_semillas)
    cargar_bm(sesion_con_semillas, cliente_bm, ["NY.GDP.MKTP.CD"], espera=0)
    assert total(sesion_con_semillas) == antes + 6
    assert valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 2010, fuente="FMI_DM") == pytest.approx(424.729)


def test_paginacion(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_bm(llamadas), base_url="https://bm.test/v2") as c:
        resultado = cargar_bm(sesion_con_semillas, c, ["NY.GDP.MKTP.CD"], espera=0, por_pagina=3)
    # 10 filas en páginas de 3: 4 pedidos, y se guardan todas las de países mapeados.
    assert resultado == {"NY.GDP.MKTP.CD": 6}
    pedidos = [ll for ll in llamadas if "/indicator/" in ll]
    assert pedidos == [
        f"/v2/country/all/indicator/NY.GDP.MKTP.CD?format=json&per_page=3&page={n}" for n in (1, 2, 3, 4)
    ]


def test_obtener_todo_con_una_sola_pagina():
    filas = [fila("URY", 2000 + i, i) for i in range(5)]
    with httpx.Client(transport=transporte_bm(filas={"X": filas}), base_url="https://bm.test/v2") as c:
        assert obtener_todo(c, "/country/all/indicator/X", espera=0) == filas


def test_paises_sin_mapear_se_avisan_y_agregados_se_omiten(sesion_con_semillas, caplog):
    filas = {"NY.GDP.MKTP.CD": [
        fila("URY", 2020, 5e10),
        fila("ZZZ", 2020, 1.0),         # país que no está en paises.csv: se avisa
        fila("LCN", 2020, 1.0),         # agregado del BM sin equivalente: se omite sin avisar
        fila("", 2020, 1.0, id2="XD"),  # grupo de ingreso, sin ISO3: se omite
    ]}
    with caplog.at_level(logging.INFO, logger="app.etl.banco_mundial"):
        with httpx.Client(transport=transporte_bm(filas=filas), base_url="https://bm.test/v2") as c:
            assert cargar_bm(sesion_con_semillas, c, ["NY.GDP.MKTP.CD"], espera=0) == {"NY.GDP.MKTP.CD": 1}
    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert avisos == ["NY.GDP.MKTP.CD: códigos de país sin mapear (se omiten): ZZZ"]
    assert valor(sesion_con_semillas, "URY", "PBI_USD_CORR", 2020) == pytest.approx(50.0)


def test_codigos_propios_del_bm(sesion_con_semillas):
    """Kosovo es XKX en el BM y UVK en el FMI; el Mundo es WLD en el BM y WEOWORLD en el FMI."""
    filas = {"SP.POP.TOTL": [fila("XKX", 2020, 1_790_000), fila("WLD", 2020, 7.85e9)]}
    with httpx.Client(transport=transporte_bm(filas=filas), base_url="https://bm.test/v2") as c:
        assert cargar_bm(sesion_con_semillas, c, ["SP.POP.TOTL"], espera=0) == {"SP.POP.TOTL": 2}
    assert valor(sesion_con_semillas, "Kosovo", "POBLACION", 2020) == pytest.approx(1.79)
    assert valor(sesion_con_semillas, "World", "POBLACION", 2020) == pytest.approx(7850)


def test_filtra_indicadores(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_bm(llamadas), base_url="https://bm.test/v2") as c:
        assert cargar_bm(sesion_con_semillas, c, ["SP.POP.TOTL"], espera=0) == {"SP.POP.TOTL": 6}
    assert [ll.split("?")[0] for ll in llamadas] == ["/v2/country", "/v2/country/all/indicator/SP.POP.TOTL"]


def test_indicador_no_definido_da_error(sesion_con_semillas, cliente_bm):
    with pytest.raises(ValueError, match="NY.GDP.PCAP.CD"):
        cargar_bm(sesion_con_semillas, cliente_bm, ["NY.GDP.PCAP.CD"], espera=0)


def test_sin_semillas_da_error(sesion, cliente_bm):
    with pytest.raises(ValueError, match="semillas"):
        cargar_bm(sesion, cliente_bm, espera=0)


def test_error_del_bm_con_http_200(sesion_con_semillas):
    """El BM responde los errores con HTTP 200 y un mensaje: no se guarda nada y se informa."""
    def error(pedido):
        if pedido.url.path.endswith("/country"):
            return httpx.Response(200, json=[{"page": 1, "pages": 1}, []])
        return httpx.Response(200, json=[{"message": [{"id": "120", "value": "Invalid value"}]}])

    with httpx.Client(transport=httpx.MockTransport(error), base_url="https://bm.test/v2") as c:
        with pytest.raises(ValueError, match="Invalid value"):
            cargar_bm(sesion_con_semillas, c, ["SP.POP.TOTL"], espera=0)
    assert total(sesion_con_semillas) == 0


def test_respuesta_vacia_no_guarda_nada(sesion_con_semillas):
    with httpx.Client(transport=transporte_bm(filas={"SP.POP.TOTL": []}), base_url="https://bm.test/v2") as c:
        assert cargar_bm(sesion_con_semillas, c, ["SP.POP.TOTL"], espera=0) == {"SP.POP.TOTL": 0}
    assert total(sesion_con_semillas) == 0


def test_upsert_es_idempotente_y_actualiza(sesion_con_semillas, cliente_bm):
    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    cantidad = total(sesion_con_semillas)
    cargar_bm(sesion_con_semillas, cliente_bm, espera=0)
    assert total(sesion_con_semillas) == cantidad

    revisado = {"NY.GDP.MKTP.CD": [fila("ARG", 2010, 430e9)]}
    with httpx.Client(transport=transporte_bm(filas=revisado), base_url="https://bm.test/v2") as c:
        cargar_bm(sesion_con_semillas, c, ["NY.GDP.MKTP.CD"], espera=0)
    sesion_con_semillas.expire_all()
    assert total(sesion_con_semillas) == cantidad
    assert valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 2010) == pytest.approx(430.0)


def test_reintenta_ante_error_del_servidor(sesion_con_semillas):
    respuestas = iter([httpx.Response(503)])
    base = transporte_bm()

    def responder(pedido):
        if "/indicator/" in pedido.url.path:
            r = next(respuestas, None)
            if r is not None:
                return r
        return base.handle_request(pedido)

    with httpx.Client(transport=httpx.MockTransport(responder), base_url="https://bm.test/v2") as c:
        assert cargar_bm(sesion_con_semillas, c, ["SP.POP.TOTL"], espera=0) == {"SP.POP.TOTL": 6}


# --- Casos límite (agregados por el tester) ---

def test_importaciones_en_miles_de_millones(sesion_con_semillas, cliente_bm):
    cargar_bm(sesion_con_semillas, cliente_bm, ["NE.IMP.GNFS.CD"], espera=0)
    assert valor(sesion_con_semillas, "URY", "IMPORTACIONES_USD", 2010) == pytest.approx(10.6369514850362)


def test_factor_vacio_no_escala(sesion_con_semillas):
    """Las series sin factor en indicadores.csv (porcentajes, FMI) quedan con factor None, que equivale a 1."""
    from app.models import IndicadorSerieExterna

    factores = dict(sesion_con_semillas.execute(
        select(IndicadorSerieExterna.codigo_externo, IndicadorSerieExterna.factor)
    ).all())
    assert factores["NGDPD"] is None and factores["LP"] is None and factores["GC.DOD.TOTL.GD.ZS"] is None
    assert factores["NY.GDP.MKTP.CD"] == pytest.approx(1e-9)
    assert factores["SP.POP.TOTL"] == pytest.approx(1e-6)
    assert factores["NE.EXP.GNFS.CD"] == pytest.approx(1e-9)


def test_valor_cero_se_guarda(sesion_con_semillas):
    """Un 0 del BM es un dato (no se confunde con null)."""
    filas = {"NY.GDP.MKTP.KD.ZG": [fila("URY", 2015, 0, codigo="NY.GDP.MKTP.KD.ZG")]}
    with httpx.Client(transport=transporte_bm(filas=filas), base_url="https://bm.test/v2") as c:
        assert cargar_bm(sesion_con_semillas, c, ["NY.GDP.MKTP.KD.ZG"], espera=0) == {"NY.GDP.MKTP.KD.ZG": 1}
    assert valor(sesion_con_semillas, "URY", "PBI_CRECIMIENTO", 2015) == 0
