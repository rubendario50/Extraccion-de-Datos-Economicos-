from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.etl import __main__ as cli
from app.etl import banco_mundial, bcu, fmi, fred, ine
from app.models import CotizacionDiaria, DatoInternacionalAnual, DatoNacionalMensual, Fuente
from tests.conftest import CLAVE_FRED, transporte_bcu, transporte_bm, transporte_fmi, transporte_fred, transporte_ine


@pytest.fixture
def cli_simulado(sesion, monkeypatch):
    """La CLI usa la base de los tests y las APIs simuladas."""
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=sesion.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(fmi, "crear_cliente", lambda: httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test"))
    monkeypatch.setattr(banco_mundial, "crear_cliente", lambda: httpx.Client(transport=transporte_bm(), base_url="https://bm.test/v2"))
    monkeypatch.setattr(ine, "crear_cliente", lambda: httpx.Client(transport=transporte_ine(), base_url="https://ine.test/documents"))
    monkeypatch.setattr(bcu, "crear_cliente", lambda: httpx.Client(transport=transporte_bcu(), base_url="https://bcu.test/servlet"))
    monkeypatch.setattr(fred, "crear_cliente", lambda: httpx.Client(transport=transporte_fred(), base_url="https://fred.test/fred"))
    monkeypatch.setattr(fred, "clave_api", lambda: CLAVE_FRED)
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
    # FRED: SP500 y WTI con datos (13 días hábiles cada uno), el gas sin datos y el resto sin fixture (0).
    assert "SP500: 13 valores" in salida and "DCOILWTICO: 13 valores" in salida and "DJIA: 0 valores" in salida
    assert por_fuente(cli_simulado) == {"FMI_DM": 33, "BM": 28}
    assert contar(cli_simulado, DatoNacionalMensual) == 42 and contar(cli_simulado, CotizacionDiaria) == 11 + 26


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


def test_bm_con_un_indicador_caido_carga_los_demas_y_sale_con_error(cli_simulado, capsys, monkeypatch):
    base = transporte_bm()

    def responder(pedido):
        if pedido.url.path.endswith("/GC.DOD.TOTL.GD.ZS"):
            return httpx.Response(502)
        return base.handle_request(pedido)

    monkeypatch.setattr(banco_mundial, "crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(responder), base_url="https://bm.test/v2"))
    assert cli.main(["semillas"]) == 0
    assert cli.main(["bm"]) == 1
    salida = capsys.readouterr()
    assert "SP.POP.TOTL: 6 valores" in salida.out
    assert "GC.DOD.TOTL.GD.ZS" in salida.err and "502" in salida.err
    assert por_fuente(cli_simulado) == {"BM": 26}


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
    assert "Fallaron: INE, BCU. Se cargaron: FMI, Banco Mundial, FRED." in salida.err
    assert "Traceback" not in salida.err
    assert por_fuente(cli_simulado) == {"FMI_DM": 33, "BM": 28}
    assert contar(cli_simulado, DatoNacionalMensual) == 0 and contar(cli_simulado, CotizacionDiaria) == 26


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
    for modulo in (fmi, banco_mundial, ine, bcu, fred):
        monkeypatch.setattr(modulo, "crear_cliente", lambda: httpx.Client(transport=caido, base_url="https://caido.test"))
    assert cli.main(["todo"]) == 1
    err = capsys.readouterr().err
    assert "Fallaron: FMI, Banco Mundial, INE, BCU, FRED. No se cargó ninguna fuente." in err
    assert "Se cargaron" not in err and "Traceback" not in err


def test_todo_sin_clave_de_fred_sigue_con_las_demas(cli_simulado, capsys, monkeypatch):
    monkeypatch.setattr(fred, "clave_api", lambda: "")
    assert cli.main(["todo"]) == 1
    err = capsys.readouterr().err
    assert "Error (FRED): Falta la clave de FRED: completá FRED_API_KEY" in err
    assert "https://fredaccount.stlouisfed.org/apikeys" in err
    assert "Fallaron: FRED. Se cargaron: FMI, Banco Mundial, INE, BCU." in err
    assert contar(cli_simulado, CotizacionDiaria) == 11  # el dólar del BCU sí


def test_fred_con_indicadores_y_desde(cli_simulado, capsys):
    assert cli.main(["semillas"]) == 0
    assert cli.main(["fred", "--indicadores", "SP500", "--desde", "2026-01-01"]) == 0
    assert "SP500: 6 valores" in capsys.readouterr().out
    assert min(cli_simulado.scalars(select(CotizacionDiaria.fecha))) == date(2026, 1, 2)


def test_fred_no_escribe_la_clave_en_el_registro(cli_simulado, capsys, caplog):
    assert cli.main(["semillas"]) == 0
    with caplog.at_level("DEBUG"):
        assert cli.main(["fred"]) == 0
    salida = capsys.readouterr()
    assert CLAVE_FRED not in caplog.text + salida.out + salida.err
