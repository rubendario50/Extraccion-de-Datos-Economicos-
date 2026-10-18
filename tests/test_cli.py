import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.etl import __main__ as cli
from app.etl import banco_mundial, fmi
from app.models import DatoInternacionalAnual, Fuente
from tests.conftest import transporte_bm, transporte_fmi


@pytest.fixture
def cli_simulado(sesion, monkeypatch):
    """La CLI usa la base de los tests y las APIs simuladas."""
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=sesion.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(fmi, "crear_cliente", lambda: httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test"))
    monkeypatch.setattr(banco_mundial, "crear_cliente", lambda: httpx.Client(transport=transporte_bm(), base_url="https://bm.test/v2"))
    monkeypatch.setattr("app.etl.comun.time.sleep", lambda s: None)
    return sesion


def por_fuente(sesion):
    return dict(sesion.execute(
        select(Fuente.codigo, func.count()).join(DatoInternacionalAnual, DatoInternacionalAnual.fuente_id == Fuente.id).group_by(Fuente.codigo)
    ).all())


def test_todo_carga_semillas_fmi_y_bm(cli_simulado, capsys):
    assert cli.main(["todo"]) == 0
    salida = capsys.readouterr().out
    assert "paises:" in salida and "NGDPD: 15 valores" in salida and "SP.POP.TOTL: 6 valores" in salida
    assert por_fuente(cli_simulado) == {"FMI_DM": 33, "BM": 28}


def test_bm_con_indicadores(cli_simulado, capsys):
    assert cli.main(["semillas"]) == 0
    assert cli.main(["bm", "--indicadores", "SP.POP.TOTL, NY.GDP.MKTP.CD"]) == 0
    assert por_fuente(cli_simulado) == {"BM": 12}


def test_bm_sin_semillas_da_error(cli_simulado, capsys):
    assert cli.main(["bm"]) == 1
    assert "semillas" in capsys.readouterr().err
