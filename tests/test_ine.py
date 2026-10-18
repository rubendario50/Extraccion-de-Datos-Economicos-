"""Cargador del INE con planillas reales recortadas (tests/fixtures/ine_*.xlsx)."""

import io
import ssl
from datetime import date

import httpx
import openpyxl
import pytest
from sqlalchemy import func, select

from app.etl import ine
from app.etl.ine import cargar_ine, leer_desempleo, leer_ipc
from app.models import DatoNacionalMensual, Fuente, Indicador
from tests.conftest import FIXTURES, transporte_ine


def valores(sesion, indicador):
    return dict(
        sesion.execute(
            select(DatoNacionalMensual.periodo, DatoNacionalMensual.valor)
            .join(Indicador, Indicador.id == DatoNacionalMensual.indicador_id)
            .where(Indicador.codigo == indicador)
        ).all()
    )


def total(sesion):
    return sesion.scalar(select(func.count()).select_from(DatoNacionalMensual))


def planilla(filas: list[list]) -> bytes:
    libro = openpyxl.Workbook()
    for fila in filas:
        libro.active.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_lee_el_ipc():
    ipc = leer_ipc((FIXTURES / "ine_ipc_general.xlsx").read_bytes())
    assert len(ipc) == 10
    assert min(ipc) == date(1937, 7, 1) and max(ipc) == date(2026, 9, 1)
    assert ipc[date(2022, 10, 1)] == 100  # mes base
    assert ipc[date(2026, 9, 1)] == pytest.approx(119.13131514)
    assert ipc[date(1937, 7, 1)] == pytest.approx(1.5944905510e-07)


def test_lee_el_desempleo_mensual_sin_trimestres_ni_totales():
    desempleo = leer_desempleo((FIXTURES / "ine_ECH0013.xlsx").read_bytes())
    # 2006 y 2018 completos, 2026 hasta agosto (setiembre en adelante todavía vacíos).
    assert len(desempleo) == 12 + 12 + 8
    assert desempleo[date(2006, 1, 1)] == pytest.approx(13.1957312845622)  # "Enero (2)"
    assert desempleo[date(2006, 9, 1)] == pytest.approx(10.4910822093835)  # "Setiembre (2)"
    assert desempleo[date(2018, 6, 1)] == pytest.approx(7.927)  # "Junio " con espacio, año "2018 (9)"
    assert desempleo[date(2026, 8, 1)] == pytest.approx(7.16166411684247)
    assert date(2026, 9, 1) not in desempleo
    # El promedio del trimestre (12,39) y el total anual (10,75) no se guardan como si fueran meses.
    assert 12.3945059724646 not in desempleo.values() and 10.7508795172563 not in desempleo.values()


def test_carga_los_indicadores_del_ine(sesion_con_semillas, cliente_ine):
    resultado = cargar_ine(sesion_con_semillas, cliente_ine, espera=0)
    assert resultado == {"ECH0013": 32, "IPC_GENERAL": 10}
    assert valores(sesion_con_semillas, "IPC_UY")[date(2022, 10, 1)] == 100
    assert valores(sesion_con_semillas, "DESEMPLEO_UY")[date(2018, 1, 1)] == pytest.approx(8.4774)
    # Cada valor guarda su fuente.
    fuentes = sesion_con_semillas.scalars(
        select(Fuente.codigo).join(DatoNacionalMensual, DatoNacionalMensual.fuente_id == Fuente.id).distinct()
    ).all()
    assert fuentes == ["INE"]


def test_filtra_indicadores(sesion_con_semillas):
    llamadas = []
    with httpx.Client(transport=transporte_ine(llamadas), base_url="https://ine.test/documents") as c:
        assert cargar_ine(sesion_con_semillas, c, ["IPC_GENERAL"], espera=0) == {"IPC_GENERAL": 10}
    assert len(llamadas) == 1 and llamadas[0].endswith("/IPC gral y variaciones_base 2022.xlsx")
    assert "/Base Octubre 2022=100/" in llamadas[0]


def test_es_idempotente_y_actualiza_revisiones(sesion_con_semillas, cliente_ine):
    cargar_ine(sesion_con_semillas, cliente_ine, espera=0)
    cantidad = total(sesion_con_semillas)
    cargar_ine(sesion_con_semillas, cliente_ine, espera=0)
    assert total(sesion_con_semillas) == cantidad

    # El INE revisa la tasa de enero de 2026: la carga siguiente la actualiza sin duplicar.
    revisada = planilla([
        ["Año, Trimestre y Mes", "Total País"],
        [2026, None],
        ["Enero", 7.5],
    ])
    transporte = transporte_ine(planillas={"ECH0013.xlsx": revisada})
    with httpx.Client(transport=transporte, base_url="https://ine.test/documents") as c:
        assert cargar_ine(sesion_con_semillas, c, ["ECH0013"], espera=0) == {"ECH0013": 1}
    sesion_con_semillas.expire_all()
    assert total(sesion_con_semillas) == cantidad
    assert valores(sesion_con_semillas, "DESEMPLEO_UY")[date(2026, 1, 1)] == 7.5


def test_formato_cambiado_da_error_claro(sesion_con_semillas):
    otra = planilla([["Período", "Tasa"], ["Enero 2026", 7.4]])
    transporte = transporte_ine(planillas={"ECH0013.xlsx": otra})
    with httpx.Client(transport=transporte, base_url="https://ine.test/documents") as c:
        with pytest.raises(ValueError, match="Total País.*formato"):
            cargar_ine(sesion_con_semillas, c, ["ECH0013"], espera=0)
    assert total(sesion_con_semillas) == 0


def test_planilla_sin_datos_da_error(sesion_con_semillas):
    vacia = planilla([["Mes y año", "Índice"], [None, None]])
    transporte = transporte_ine(planillas={"IPC gral y variaciones_base 2022.xlsx": vacia})
    with httpx.Client(transport=transporte, base_url="https://ine.test/documents") as c:
        with pytest.raises(ValueError, match="sin datos|no tiene datos"):
            cargar_ine(sesion_con_semillas, c, ["IPC_GENERAL"], espera=0)


def test_planilla_que_no_existe_da_error_http(sesion_con_semillas, monkeypatch):
    monkeypatch.setitem(ine.ARCHIVOS, "IPC_GENERAL", ("/movida/IPC.xlsx", leer_ipc))
    with httpx.Client(transport=transporte_ine(), base_url="https://ine.test/documents") as c:
        with pytest.raises(httpx.HTTPStatusError):
            cargar_ine(sesion_con_semillas, c, ["IPC_GENERAL"], espera=0)


def test_codigo_sin_lector_da_error(sesion_con_semillas, cliente_ine, monkeypatch):
    monkeypatch.delitem(ine.ARCHIVOS, "ECH0013")
    with pytest.raises(ValueError, match="no hay lector"):
        cargar_ine(sesion_con_semillas, cliente_ine, ["ECH0013"], espera=0)


def test_sin_semillas_da_error(sesion, cliente_ine):
    with pytest.raises(ValueError, match="semillas"):
        cargar_ine(sesion, cliente_ine, espera=0)


def test_cliente_verifica_tls_con_el_intermedio_del_ine():
    # El servidor del INE no manda el intermedio de Sectigo: se agrega al contexto, sin desactivar la verificación.
    assert ine.CERTIFICADO_INTERMEDIO.exists()
    contexto = ine.contexto_tls(ine.CERTIFICADO_INTERMEDIO)
    assert contexto.verify_mode == ssl.CERT_REQUIRED and contexto.check_hostname
    sujetos = [dict(x[0] for x in c["subject"]).get("commonName") for c in contexto.get_ca_certs()]
    assert "Sectigo Public Server Authentication CA DV R36" in sujetos


# --- Casos agregados por el tester ---

@pytest.mark.parametrize("contenido", [b"", b"<html>Pagina no encontrada</html>"], ids=["vacio", "html"])
def test_archivo_que_no_es_xlsx_da_error_claro(sesion_con_semillas, contenido):
    transporte = transporte_ine(planillas={"IPC gral y variaciones_base 2022.xlsx": contenido})
    with httpx.Client(transport=transporte, base_url="https://ine.test/documents") as c:
        with pytest.raises(ValueError, match="INE"):
            cargar_ine(sesion_con_semillas, c, ["IPC_GENERAL"], espera=0)
    assert total(sesion_con_semillas) == 0
