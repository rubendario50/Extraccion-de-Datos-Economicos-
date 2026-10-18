from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.etl import __main__ as cli
from app.etl import banco_mundial, bcu, fmi, ine
from app.models import CotizacionDiaria, DatoInternacionalAnual, DatoNacionalMensual, Fuente
from tests.conftest import transporte_bcu, transporte_bm, transporte_fmi, transporte_ine


@pytest.fixture
def cli_simulado(sesion, monkeypatch):
    """La CLI usa la base de los tests y las APIs simuladas."""
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=sesion.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(fmi, "crear_cliente", lambda: httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test"))
    monkeypatch.setattr(banco_mundial, "crear_cliente", lambda: httpx.Client(transport=transporte_bm(), base_url="https://bm.test/v2"))
    monkeypatch.setattr(ine, "crear_cliente", lambda: httpx.Client(transport=transporte_ine(), base_url="https://ine.test/documents"))
    monkeypatch.setattr(bcu, "crear_cliente", lambda: httpx.Client(transport=transporte_bcu(), base_url="https://bcu.test/servlet"))
    monkeypatch.setattr("app.etl.comun.time.sleep", lambda s: None)
    return sesion


def por_fuente(sesion):
    return dict(sesion.execute(
        select(Fuente.codigo, func.count()).join(DatoInternacionalAnual, DatoInternacionalAnual.fuente_id == Fuente.id).group_by(Fuente.codigo)
    ).all())


def contar(sesion, modelo):
    return sesion.scalar(select(func.count()).select_from(modelo))


def test_todo_carga_semillas_fmi_bm_ine_y_bcu(cli_simulado, capsys):
    assert cli.main(["todo"]) == 0
    salida = capsys.readouterr().out
    assert "paises:" in salida and "NGDPD: 15 valores" in salida and "SP.POP.TOTL: 6 valores" in salida
    assert "IPC_GENERAL: 10 valores" in salida and "ECH0013: 32 valores" in salida and "2225: 11 valores" in salida
    assert por_fuente(cli_simulado) == {"FMI_DM": 33, "BM": 28}
    assert contar(cli_simulado, DatoNacionalMensual) == 42 and contar(cli_simulado, CotizacionDiaria) == 11


def test_ine_con_indicadores(cli_simulado, capsys):
    assert cli.main(["semillas"]) == 0
    assert cli.main(["ine", "--indicadores", "ECH0013"]) == 0
    assert "ECH0013: 32 valores" in capsys.readouterr().out
    assert contar(cli_simulado, DatoNacionalMensual) == 32


def test_bcu_con_desde(cli_simulado, capsys):
    assert cli.main(["semillas"]) == 0
    assert cli.main(["bcu", "--desde", "2026-10-14"]) == 0
    assert set(cli_simulado.scalars(select(CotizacionDiaria.fecha)).all()) == {
        date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
    }


def test_bcu_fecha_invalida(cli_simulado, capsys):
    with pytest.raises(SystemExit):
        cli.main(["bcu", "--desde", "14/10/2026"])


def test_bm_con_indicadores(cli_simulado, capsys):
    assert cli.main(["semillas"]) == 0
    assert cli.main(["bm", "--indicadores", "SP.POP.TOTL, NY.GDP.MKTP.CD"]) == 0
    assert por_fuente(cli_simulado) == {"BM": 12}


def test_bm_sin_semillas_da_error(cli_simulado, capsys):
    assert cli.main(["bm"]) == 1
    assert "semillas" in capsys.readouterr().err


def test_todo_sigue_si_falla_una_fuente(cli_simulado, capsys, monkeypatch):
    # El INE responde una página HTML en lugar de la planilla y el BCU un XML cortado: se cargan las demás.
    html = httpx.MockTransport(lambda p: httpx.Response(200, text="<html>Mantenimiento</html>"))
    roto = httpx.MockTransport(lambda p: httpx.Response(200, text="<SOAP-ENV:Envelope"))
    monkeypatch.setattr(ine, "crear_cliente", lambda: httpx.Client(transport=html, base_url="https://ine.test/documents"))
    monkeypatch.setattr(bcu, "crear_cliente", lambda: httpx.Client(transport=roto, base_url="https://bcu.test/servlet"))
    assert cli.main(["todo"]) == 1
    salida = capsys.readouterr()
    assert "NGDPD: 15 valores" in salida.out and "SP.POP.TOTL: 6 valores" in salida.out
    assert "Error (INE): INE: el archivo descargado no es un xlsx" in salida.err
    assert "Error (BCU): BCU: respuesta vacía o mal formada" in salida.err
    assert "Fallaron: INE, BCU. Se cargaron: FMI, Banco Mundial." in salida.err
    assert "Traceback" not in salida.err
    assert por_fuente(cli_simulado) == {"FMI_DM": 33, "BM": 28}
    assert contar(cli_simulado, DatoNacionalMensual) == 0 and contar(cli_simulado, CotizacionDiaria) == 0


def test_comando_suelto_que_falla_sale_con_1(cli_simulado, capsys, monkeypatch):
    roto = httpx.MockTransport(lambda p: httpx.Response(200, content=b""))
    monkeypatch.setattr(bcu, "crear_cliente", lambda: httpx.Client(transport=roto, base_url="https://bcu.test/servlet"))
    assert cli.main(["semillas"]) == 0
    assert cli.main(["bcu"]) == 1
    err = capsys.readouterr().err
    assert "BCU: respuesta vacía o mal formada" in err and "Fallaron" not in err


def test_todo_si_fallan_las_semillas_no_carga_nada(cli_simulado, capsys, monkeypatch):
    def falla(sesion):
        raise ValueError("paises.csv roto")

    monkeypatch.setattr(cli, "cargar_semillas", falla)
    assert cli.main(["todo"]) == 1
    err = capsys.readouterr().err
    assert "Error (Semillas): paises.csv roto" in err
    assert "Fallaron las semillas: no se cargó ninguna fuente." in err
    assert "Se cargaron" not in err and "Fallaron:" not in err
    assert por_fuente(cli_simulado) == {}


def test_todo_si_fallan_todas_las_fuentes(cli_simulado, capsys, monkeypatch):
    caido = httpx.MockTransport(lambda p: httpx.Response(503))
    for modulo in (fmi, banco_mundial, ine, bcu):
        monkeypatch.setattr(modulo, "crear_cliente", lambda: httpx.Client(transport=caido, base_url="https://caido.test"))
    assert cli.main(["todo"]) == 1
    err = capsys.readouterr().err
    assert "Fallaron: FMI, Banco Mundial, INE, BCU. No se cargó ninguna fuente." in err
    assert "Se cargaron" not in err and "Traceback" not in err
