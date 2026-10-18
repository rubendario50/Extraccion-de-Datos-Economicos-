"""Cargador del BCU con respuestas reales del servicio de cotizaciones (tests/fixtures/bcu_*.xml)."""

from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from app.etl.bcu import FECHA_INICIO, cargar_bcu, leer_respuesta, tramos
from app.models import CotizacionDiaria, Fuente
from tests.conftest import FIXTURES, transporte_bcu

HOY = date(2026, 10, 18)  # sábado: la última cotización es la del viernes 16


def cotizaciones(sesion):
    return dict(sesion.execute(select(CotizacionDiaria.fecha, CotizacionDiaria.cierre)).all())


def total(sesion):
    return sesion.scalar(select(func.count()).select_from(CotizacionDiaria))


def test_lee_la_respuesta_del_servicio():
    datos = leer_respuesta((FIXTURES / "bcu_2225_2026-10.xml").read_bytes())
    assert len(datos) == 11  # días hábiles del 1 al 16 de octubre de 2026
    assert datos[date(2026, 10, 1)] == 40.463
    assert datos[date(2026, 10, 16)] == 40.097
    assert date(2026, 10, 3) not in datos  # sábado


def test_sin_cotizaciones_no_es_error():
    assert leer_respuesta((FIXTURES / "bcu_sin_cotizaciones.xml").read_bytes()) == {}


def test_error_del_servicio():
    with pytest.raises(ValueError, match="104.*Rango de fechas excede"):
        leer_respuesta((FIXTURES / "bcu_rango_excedido.xml").read_bytes())


def test_tramos_por_anio_calendario():
    assert tramos(date(2025, 6, 1), date(2026, 2, 1)) == [
        (date(2025, 6, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 2, 1)),
    ]
    assert tramos(date(2026, 1, 1), date(2026, 1, 1)) == [(date(2026, 1, 1), date(2026, 1, 1))]
    # Ningún tramo pasa de 366 días (el límite del servicio).
    assert all((fin - inicio).days <= 365 for inicio, fin in tramos(FECHA_INICIO, HOY))


def test_primera_carga_pide_desde_2000_por_anio(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_bcu(llamadas), base_url="https://bcu.test/servlet") as c:
        assert cargar_bcu(sesion_con_semillas, c, espera=0, hasta=HOY) == {"2225": 11}
    assert len(llamadas) == 27  # 2000 a 2026
    assert llamadas[0] == ("2225", date(2000, 1, 1), date(2000, 12, 31))
    assert llamadas[-1] == ("2225", date(2026, 1, 1), HOY)
    datos = cotizaciones(sesion_con_semillas)
    assert datos[date(2026, 10, 1)] == 40.463 and datos[date(2026, 10, 16)] == 40.097
    fuentes = sesion_con_semillas.scalars(
        select(Fuente.codigo).join(CotizacionDiaria, CotizacionDiaria.fuente_id == Fuente.id).distinct()
    ).all()
    assert fuentes == ["BCU"]


def test_carga_incremental_e_idempotente(sesion_con_semillas, cliente_bcu):
    cargar_bcu(sesion_con_semillas, cliente_bcu, espera=0, hasta=HOY)
    cantidad = total(sesion_con_semillas)
    llamadas = []
    with httpx.Client(transport=transporte_bcu(llamadas), base_url="https://bcu.test/servlet") as c:
        resultado = cargar_bcu(sesion_con_semillas, c, espera=0, hasta=HOY)
    # Retoma 10 días antes de la última cotización guardada (16/10), en un solo pedido.
    assert llamadas == [("2225", date(2026, 10, 6), HOY)]
    assert resultado == {"2225": 8}
    assert total(sesion_con_semillas) == cantidad


def test_desde_explicito(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_bcu(llamadas), base_url="https://bcu.test/servlet") as c:
        assert cargar_bcu(sesion_con_semillas, c, espera=0, desde=date(2026, 10, 14), hasta=date(2026, 10, 15)) == {"2225": 2}
    assert llamadas == [("2225", date(2026, 10, 14), date(2026, 10, 15))]


def test_actualiza_una_cotizacion_corregida(sesion_con_semillas, cliente_bcu):
    cargar_bcu(sesion_con_semillas, cliente_bcu, espera=0, hasta=HOY)
    cantidad = total(sesion_con_semillas)
    corregida = (FIXTURES / "bcu_2225_2026-10.xml").read_text(encoding="utf-8").replace("40.097000", "40.111000")
    with httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, text=corregida)),
                      base_url="https://bcu.test/servlet") as c:
        cargar_bcu(sesion_con_semillas, c, espera=0, hasta=HOY)
    sesion_con_semillas.expire_all()
    assert total(sesion_con_semillas) == cantidad
    assert cotizaciones(sesion_con_semillas)[date(2026, 10, 16)] == 40.111


def test_pedido_soap(sesion_con_semillas):
    pedidos = []

    def responder(pedido):
        pedidos.append(pedido)
        return httpx.Response(200, content=(FIXTURES / "bcu_sin_cotizaciones.xml").read_bytes())

    with httpx.Client(transport=httpx.MockTransport(responder), base_url="https://bcu.test/servlet") as c:
        assert cargar_bcu(sesion_con_semillas, c, espera=0, desde=date(2026, 10, 17), hasta=HOY) == {"2225": 0}
    pedido = pedidos[0]
    assert pedido.method == "POST" and pedido.url.path == "/servlet/awsbcucotizaciones"
    assert pedido.headers["content-type"].startswith("text/xml")
    cuerpo = pedido.content.decode()
    assert "<cot:item>2225</cot:item>" in cuerpo
    assert "<cot:FechaDesde>2026-10-17</cot:FechaDesde>" in cuerpo and "<cot:FechaHasta>2026-10-18</cot:FechaHasta>" in cuerpo


def test_error_del_servicio_corta_la_carga(sesion_con_semillas):
    error = (FIXTURES / "bcu_rango_excedido.xml").read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=error)),
                      base_url="https://bcu.test/servlet") as c:
        with pytest.raises(ValueError, match="BCU respondió con el error 104"):
            cargar_bcu(sesion_con_semillas, c, espera=0, hasta=HOY)
    assert total(sesion_con_semillas) == 0


def test_moneda_no_definida_da_error(sesion_con_semillas, cliente_bcu):
    with pytest.raises(ValueError, match="1111"):
        cargar_bcu(sesion_con_semillas, cliente_bcu, ["1111"], espera=0, hasta=HOY)


def test_sin_semillas_da_error(sesion, cliente_bcu):
    with pytest.raises(ValueError, match="semillas"):
        cargar_bcu(sesion, cliente_bcu, espera=0, hasta=HOY)


# --- Casos agregados por el tester: respuestas rotas deben dar un error claro (ValueError) ---

@pytest.mark.parametrize(
    "contenido",
    [b"", b"<html><body>Servicio en mantenimiento</body></html>", b"<?xml version='1.0'?><a>"],
    ids=["vacia", "html", "xml-cortado"],
)
def test_respuesta_rota_da_error_claro(sesion_con_semillas, contenido):
    with httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=contenido)),
                      base_url="https://bcu.test/servlet") as c:
        with pytest.raises(ValueError, match="BCU"):
            cargar_bcu(sesion_con_semillas, c, espera=0, desde=date(2026, 10, 1), hasta=HOY)
    assert total(sesion_con_semillas) == 0


def test_cotizacion_con_formato_raro_da_error_claro():
    xml = (FIXTURES / "bcu_2225_2026-10.xml").read_bytes().replace(b"<TCV>40.463000", b"<TCV>40,463000")
    # Cualquier ValueError sirve: el CLI lo muestra como "Error: ..." en lugar de un traceback.
    with pytest.raises(ValueError):
        leer_respuesta(xml)


def test_desde_posterior_a_hasta_no_pide_nada(sesion_con_semillas):
    pedidos = []
    with httpx.Client(transport=httpx.MockTransport(lambda p: pedidos.append(p) or httpx.Response(500)),
                      base_url="https://bcu.test/servlet") as c:
        assert cargar_bcu(sesion_con_semillas, c, espera=0, desde=date(2026, 10, 20), hasta=HOY) == {"2225": 0}
    assert pedidos == []
