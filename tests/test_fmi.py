import httpx
import pytest
from sqlalchemy import func, select

from app.etl.fmi import cargar_fmi, obtener_json
from app.models import DatoInternacionalAnual, Indicador, Pais
from tests.conftest import transporte_fmi


def valor(sesion, iso3_o_dm, indicador, anio):
    return sesion.scalar(
        select(DatoInternacionalAnual.valor)
        .join(Pais, Pais.id == DatoInternacionalAnual.pais_id)
        .join(Indicador, Indicador.id == DatoInternacionalAnual.indicador_id)
        .where(Indicador.codigo == indicador, DatoInternacionalAnual.anio == anio)
        .where((Pais.iso3 == iso3_o_dm) | (Pais.nombre_en == iso3_o_dm))
    )


def total(sesion):
    return sesion.scalar(select(func.count()).select_from(DatoInternacionalAnual))


def test_carga_todos_los_indicadores(sesion_con_semillas, cliente_fmi):
    resultado = cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    # NGDPD: 4 países x 4 años, menos un null (URY 1980); ZZZ no existe y se omite.
    assert resultado == {"NGDPD": 15, "NGDP_RPCH": 4, "GGXWDG_NGDP": 4, "GGXCNL_NGDP": 4, "LP": 6}
    assert valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 1980) == pytest.approx(233.696)
    assert valor(sesion_con_semillas, "USA", "PBI_USD_CORR", 2000) == pytest.approx(10250.95)
    assert valor(sesion_con_semillas, "World", "PBI_USD_CORR", 2024) == pytest.approx(111906.375)
    assert valor(sesion_con_semillas, "URY", "PBI_CRECIMIENTO", 2010) == pytest.approx(7.8)
    assert valor(sesion_con_semillas, "URY", "PBI_USD_CORR", 1980) is None
    assert valor(sesion_con_semillas, "URY", "DEUDA_GOB_GENERAL", 2020) == pytest.approx(68.2)
    assert valor(sesion_con_semillas, "ARG", "RESULTADO_FISCAL", 2020) == pytest.approx(-8.7)
    assert valor(sesion_con_semillas, "URY", "POBLACION", 2010) == pytest.approx(3.397)  # millones


def test_filtra_indicadores(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_fmi(llamadas), base_url="https://fmi.test/api/v1") as c:
        resultado = cargar_fmi(sesion_con_semillas, c, ["NGDP_RPCH"], espera=0)
    assert resultado == {"NGDP_RPCH": 4}
    assert llamadas == ["/api/v1/NGDP_RPCH"]


def test_indicador_no_definido_da_error(sesion_con_semillas, cliente_fmi):
    with pytest.raises(ValueError, match="PPPGDP"):
        cargar_fmi(sesion_con_semillas, cliente_fmi, ["PPPGDP"], espera=0)


def test_sin_semillas_da_error(sesion, cliente_fmi):
    with pytest.raises(ValueError, match="semillas"):
        cargar_fmi(sesion, cliente_fmi, espera=0)


def test_upsert_es_idempotente_y_actualiza(sesion_con_semillas, cliente_fmi):
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    cantidad = total(sesion_con_semillas)
    cargar_fmi(sesion_con_semillas, cliente_fmi, espera=0)
    assert total(sesion_con_semillas) == cantidad

    # El FMI revisa una cifra: la segunda carga la actualiza sin duplicar.
    def revisado(pedido):
        return httpx.Response(200, json={"values": {"NGDPD": {"ARG": {"1980": 240.0}}}})

    with httpx.Client(transport=httpx.MockTransport(revisado), base_url="https://fmi.test") as c:
        cargar_fmi(sesion_con_semillas, c, ["NGDPD"], espera=0)
    sesion_con_semillas.expire_all()
    assert total(sesion_con_semillas) == cantidad
    assert valor(sesion_con_semillas, "ARG", "PBI_USD_CORR", 1980) == 240.0


def test_reintenta_ante_error_del_servidor():
    respuestas = iter([httpx.Response(503), httpx.Response(200, json={"ok": True})])
    with httpx.Client(transport=httpx.MockTransport(lambda p: next(respuestas)), base_url="https://x") as c:
        assert obtener_json(c, "/NGDPD", espera=0) == {"ok": True}


def test_reintenta_ante_error_de_red_y_se_rinde():
    intentos = []

    def falla(pedido):
        intentos.append(1)
        raise httpx.ConnectError("sin conexión", request=pedido)

    with httpx.Client(transport=httpx.MockTransport(falla), base_url="https://x") as c:
        with pytest.raises(httpx.ConnectError):
            obtener_json(c, "/NGDPD", reintentos=3, espera=0)
    assert len(intentos) == 3


def test_error_404_no_se_reintenta():
    intentos = []

    def no_existe(pedido):
        intentos.append(1)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(no_existe), base_url="https://x") as c:
        with pytest.raises(httpx.HTTPStatusError):
            obtener_json(c, "/NADA", espera=0)
    assert len(intentos) == 1


def test_respuesta_vacia_del_fmi_no_guarda_nada(sesion_con_semillas):
    with httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"values": {}})),
                      base_url="https://x") as c:
        assert cargar_fmi(sesion_con_semillas, c, ["NGDPD"], espera=0) == {"NGDPD": 0}
    assert total(sesion_con_semillas) == 0
