"""Cargador de FRED con respuestas reales recortadas (tests/fixtures/fred_*.json, del 20/12/2025 al 10/01/2026)."""

import json
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from app.etl.fred import cargar_fred, leer_observaciones
from app.models import CotizacionDiaria, Fuente, Indicador
from tests.conftest import CLAVE_FRED, FIXTURES, transporte_fred


def cotizaciones(sesion, codigo):
    return dict(sesion.execute(
        select(CotizacionDiaria.fecha, CotizacionDiaria.cierre)
        .join(Indicador, Indicador.id == CotizacionDiaria.indicador_id)
        .where(Indicador.codigo == codigo)
    ).all())


def total(sesion):
    return sesion.scalar(select(func.count()).select_from(CotizacionDiaria))


def cliente(llamadas=None):
    return httpx.Client(transport=transporte_fred(llamadas), base_url="https://fred.test/fred")


def test_lee_las_observaciones_y_omite_los_puntos():
    datos = leer_observaciones(json.loads((FIXTURES / "fred_SP500.json").read_text(encoding="utf-8")))
    assert len(datos) == 13  # 15 días, menos Navidad y Año Nuevo, que vienen con "."
    assert datos[date(2025, 12, 22)] == 6878.49 and datos[date(2026, 1, 9)] == 6966.28
    assert date(2025, 12, 25) not in datos and date(2026, 1, 1) not in datos


@pytest.mark.parametrize("cuerpo", [{}, {"observations": None}, []])
def test_respuesta_inesperada(cuerpo):
    with pytest.raises(ValueError, match="sin `observations`"):
        leer_observaciones(cuerpo)


def test_observacion_con_formato_raro():
    with pytest.raises(ValueError, match="formato inesperado"):
        leer_observaciones({"observations": [{"date": "2026-01-02", "value": "1.234,5"}]})


def test_primera_carga_baja_toda_la_serie(sesion_con_semillas):
    llamadas = []
    with cliente(llamadas) as c:
        resultado = cargar_fred(sesion_con_semillas, c, espera=0, clave=CLAVE_FRED)
    # Con datos: S&P 500 y WTI. El gas viene sin datos; el resto no tiene fixture (FRED: "no existe").
    assert resultado == {
        "DCOILBRENTEU": 0, "DCOILWTICO": 13, "DHHNGSP": 0, "DJIA": 0, "NASDAQCOM": 0, "SP500": 13,
    }
    assert all("observation_start" not in p for p in llamadas)
    assert all(p["file_type"] == "json" and p["api_key"] == CLAVE_FRED for p in llamadas)
    wti = cotizaciones(sesion_con_semillas, "PETROLEO_WTI")
    assert wti[date(2025, 12, 22)] == 58.18 and wti[date(2026, 1, 9)] == 58.96
    assert cotizaciones(sesion_con_semillas, "SP500")[date(2026, 1, 2)] == 6858.47
    # Las cotizaciones quedan con la fuente FRED.
    fuentes = sesion_con_semillas.scalars(
        select(Fuente.codigo).join(CotizacionDiaria, CotizacionDiaria.fuente_id == Fuente.id).distinct()
    ).all()
    assert fuentes == ["FRED"]


def test_serie_inexistente_o_vacia_se_avisa_y_sigue(sesion_con_semillas, caplog):
    with cliente() as c:
        cargar_fred(sesion_con_semillas, c, espera=0, clave=CLAVE_FRED)
    assert "FRED no tiene la serie DJIA" in caplog.text
    assert "DHHNGSP: FRED no devolvió datos" in caplog.text


def test_carga_incremental_e_idempotente(sesion_con_semillas):
    with cliente() as c:
        cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    antes = total(sesion_con_semillas)
    llamadas = []
    with cliente(llamadas) as c:
        assert cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED) == {"SP500": 8}
    # Retoma 10 días antes de la última fecha guardada (9/1/2026) y no duplica.
    assert llamadas[0]["observation_start"] == "2025-12-30"
    assert total(sesion_con_semillas) == antes == 13


def test_actualiza_una_cotizacion_corregida(sesion_con_semillas):
    with cliente() as c:
        cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    fecha = date(2026, 1, 9)
    fila = sesion_con_semillas.scalar(select(CotizacionDiaria).where(CotizacionDiaria.fecha == fecha))
    fila.cierre = 1.0
    sesion_con_semillas.commit()
    with cliente() as c:
        cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    sesion_con_semillas.expire_all()
    assert cotizaciones(sesion_con_semillas, "SP500")[fecha] == 6966.28


def test_desde_y_hasta_explicitos(sesion_con_semillas):
    llamadas = []
    with cliente(llamadas) as c:
        resultado = cargar_fred(
            sesion_con_semillas, c, ["DCOILWTICO"], espera=0, clave=CLAVE_FRED,
            desde=date(2025, 12, 29), hasta=date(2025, 12, 31),
        )
    assert resultado == {"DCOILWTICO": 3}
    assert (llamadas[0]["observation_start"], llamadas[0]["observation_end"]) == ("2025-12-29", "2025-12-31")


def test_sin_clave_da_error_claro(sesion_con_semillas):
    with cliente() as c, pytest.raises(ValueError, match="FRED_API_KEY.*fredaccount.stlouisfed.org/apikeys"):
        cargar_fred(sesion_con_semillas, c, espera=0, clave="")
    assert total(sesion_con_semillas) == 0


def test_clave_rechazada_corta_la_carga_sin_mostrar_la_clave(sesion_con_semillas):
    clave = "otraclavequefredno0123456789abcd"
    with cliente() as c, pytest.raises(ValueError, match="rechazó la clave.*not registered") as error:
        cargar_fred(sesion_con_semillas, c, espera=0, clave=clave)
    assert clave not in str(error.value)
    assert total(sesion_con_semillas) == 0


def test_error_http_da_error_claro(sesion_con_semillas, monkeypatch):
    monkeypatch.setattr("app.etl.comun.time.sleep", lambda s: None)
    caido = httpx.MockTransport(lambda p: httpx.Response(503, text="Service Unavailable"))
    with httpx.Client(transport=caido, base_url="https://fred.test/fred") as c:
        with pytest.raises(ValueError, match="error HTTP 503") as error:
            cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    assert CLAVE_FRED not in str(error.value)


def test_respuesta_que_no_es_json(sesion_con_semillas):
    roto = httpx.MockTransport(lambda p: httpx.Response(200, text="<html>Mantenimiento</html>"))
    with httpx.Client(transport=roto, base_url="https://fred.test/fred") as c:
        with pytest.raises(ValueError, match="no es JSON"):
            cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)


def test_pagina_si_la_serie_supera_el_limite(sesion_con_semillas, monkeypatch):
    monkeypatch.setattr("app.etl.fred.LIMITE", 5)
    obs = json.loads((FIXTURES / "fred_SP500.json").read_text(encoding="utf-8"))["observations"]
    offsets = []

    def responder(pedido):
        offset, limite = int(pedido.url.params["offset"]), int(pedido.url.params["limit"])
        offsets.append(offset)
        return httpx.Response(200, json={"observations": obs[offset:offset + limite]})

    with httpx.Client(transport=httpx.MockTransport(responder), base_url="https://fred.test/fred") as c:
        assert cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED) == {"SP500": 13}
    assert offsets == [0, 5, 10, 15]


def test_codigo_no_definido_da_error(sesion_con_semillas, cliente_fred):
    with pytest.raises(ValueError, match="no definidos en indicadores.csv: ORO"):
        cargar_fred(sesion_con_semillas, cliente_fred, ["ORO"], espera=0, clave=CLAVE_FRED)


def test_sin_semillas_da_error(sesion, cliente_fred):
    with pytest.raises(ValueError, match="semillas"):
        cargar_fred(sesion, cliente_fred, espera=0, clave=CLAVE_FRED)


def test_indicadores_de_mercados_en_las_semillas(sesion_con_semillas):
    mercados = {
        i.codigo: (i.frecuencia, i.unidad, [(s.fuente.codigo, s.codigo_externo) for s in i.series_externas])
        for i in sesion_con_semillas.scalars(select(Indicador).where(Indicador.alcance == "mercados"))
    }
    assert mercados == {
        "SP500": ("diaria", "Puntos de índice", [("FRED", "SP500")]),
        "DOW_JONES": ("diaria", "Puntos de índice", [("FRED", "DJIA")]),
        "NASDAQ": ("diaria", "Puntos de índice (5 de febrero de 1971 = 100)", [("FRED", "NASDAQCOM")]),
        "PETROLEO_WTI": ("diaria", "Dólares por barril", [("FRED", "DCOILWTICO")]),
        "PETROLEO_BRENT": ("diaria", "Dólares por barril", [("FRED", "DCOILBRENTEU")]),
        "GAS_HENRY_HUB": ("diaria", "Dólares por millón de BTU", [("FRED", "DHHNGSP")]),
    }


# --- Casos agregados por el tester ---


def test_error_400_generico_no_muestra_la_clave_ni_la_url(sesion_con_semillas):
    malo = httpx.MockTransport(lambda p: httpx.Response(
        400, json={"error_code": 400, "error_message": "Bad Request.  Variable observation_start is not valid."}))
    with httpx.Client(transport=malo, base_url="https://fred.test/fred") as c:
        with pytest.raises(ValueError, match="error HTTP 400 en SP500: Bad Request") as error:
            cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    assert CLAVE_FRED not in str(error.value) and "api_key" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_error_404_sin_json_da_error_sin_detalle(sesion_con_semillas):
    malo = httpx.MockTransport(lambda p: httpx.Response(404, text="<html>Not Found</html>"))
    with httpx.Client(transport=malo, base_url="https://fred.test/fred") as c:
        with pytest.raises(ValueError, match="error HTTP 404 en SP500: sin detalle") as error:
            cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED)
    assert CLAVE_FRED not in str(error.value)


def test_429_se_reintenta_y_no_registra_la_clave(sesion_con_semillas, monkeypatch, caplog):
    monkeypatch.setattr("app.etl.comun.time.sleep", lambda s: None)
    real = transporte_fred()
    pedidos = []

    def responder(pedido):
        pedidos.append(pedido)
        if len(pedidos) == 1:
            return httpx.Response(429, json={"error_code": 429, "error_message": "Too Many Requests."})
        return real.handle_request(pedido)

    with caplog.at_level("DEBUG"), httpx.Client(transport=httpx.MockTransport(responder), base_url="https://fred.test/fred") as c:
        assert cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED) == {"SP500": 13}
    assert len(pedidos) == 2
    assert "HTTP 429" in caplog.text
    # El registro de httpx (INFO "HTTP Request: GET ...?api_key=...") lo silencia el CLI, no el cargador;
    # acá se controla solo lo que escribe la aplicación.
    assert CLAVE_FRED not in "".join(r.getMessage() for r in caplog.records if not r.name.startswith("http"))


def test_todos_los_dias_sin_dato_no_guarda_nada(sesion_con_semillas):
    vacio = httpx.MockTransport(lambda p: httpx.Response(200, json={"observations": [
        {"date": "2026-01-01", "value": "."}, {"date": "2026-01-02", "value": " "}]}))
    with httpx.Client(transport=vacio, base_url="https://fred.test/fred") as c:
        assert cargar_fred(sesion_con_semillas, c, ["SP500"], espera=0, clave=CLAVE_FRED) == {"SP500": 0}
    assert total(sesion_con_semillas) == 0
