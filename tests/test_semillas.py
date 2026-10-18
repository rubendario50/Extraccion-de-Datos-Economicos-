import csv

from sqlalchemy import func, select

from app.etl.semillas import DIR_SEMILLAS, cargar_semillas
from app.models import Fuente, Indicador, IndicadorSerieExterna, Pais, PaisCodigoExterno


def contar(sesion, modelo):
    return sesion.scalar(select(func.count()).select_from(modelo))


def test_paises_csv_es_consistente():
    with (DIR_SEMILLAS / "paises.csv").open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    codigos = [f["codigo"] for f in filas]
    assert len(codigos) == len(set(codigos))
    assert all(len(c) == 3 and c.isdigit() for c in codigos)
    for columna in ("fmi_dm", "fmi_weo", "iso3"):
        valores = [f[columna] for f in filas if f[columna]]
        assert len(valores) == len(set(valores)), f"{columna} repetido"
    por_dm = {f["fmi_dm"]: f for f in filas}
    assert por_dm["URY"]["nombre"] == "Uruguay" and por_dm["URY"]["fmi_weo"] == "298"
    assert por_dm["ARG"]["fmi_weo"] == "213"
    assert por_dm["WEOWORLD"]["nombre"] == "Mundo" and por_dm["WEOWORLD"]["es_agregado"] == "1"
    assert por_dm["EURO"]["nombre"] == "Zona euro"


def test_carga_semillas(sesion):
    resultado = cargar_semillas(sesion)
    assert resultado["paises"] == contar(sesion, Pais) > 300
    assert contar(sesion, Fuente) == resultado["fuentes"]
    uruguay = sesion.scalar(select(Pais).where(Pais.iso3 == "URY"))
    assert uruguay.nombre == "Uruguay" and not uruguay.es_agregado
    codigos = {c.organismo: c.codigo for c in uruguay.codigos_externos}
    assert codigos == {"ISO3": "URY", "FMI_DM": "URY", "FMI_WEO": "298"}
    serie = sesion.scalar(select(IndicadorSerieExterna).where(IndicadorSerieExterna.codigo_externo == "NGDPD"))
    assert serie.indicador.codigo == "PBI_USD_CORR" and serie.fuente.codigo == "FMI_DM"


def test_carga_semillas_es_idempotente(sesion):
    cargar_semillas(sesion)
    antes = [contar(sesion, m) for m in (Pais, PaisCodigoExterno, Fuente, Indicador, IndicadorSerieExterna)]
    id_uruguay = sesion.scalar(select(Pais.id).where(Pais.iso3 == "URY"))
    cargar_semillas(sesion)
    despues = [contar(sesion, m) for m in (Pais, PaisCodigoExterno, Fuente, Indicador, IndicadorSerieExterna)]
    assert antes == despues
    assert sesion.scalar(select(Pais.id).where(Pais.iso3 == "URY")) == id_uruguay


def test_semillas_actualizan_cambios(sesion, tmp_path):
    for nombre in ("fuentes.csv", "indicadores.csv"):
        (tmp_path / nombre).write_text((DIR_SEMILLAS / nombre).read_text(encoding="utf-8"), encoding="utf-8")
    encabezado = "codigo,nombre,nombre_en,iso2,iso3,es_agregado,fmi_dm,fmi_weo\n"
    (tmp_path / "paises.csv").write_text(encabezado + "001,Uruguai,Uruguay,UY,URY,0,URY,298\n", encoding="utf-8")
    cargar_semillas(sesion, tmp_path)
    (tmp_path / "paises.csv").write_text(encabezado + "001,Uruguay,Uruguay,UY,URY,0,URY,298\n", encoding="utf-8")
    cargar_semillas(sesion, tmp_path)
    sesion.expire_all()
    assert sesion.scalar(select(Pais.nombre).where(Pais.codigo == "001")) == "Uruguay"
    assert contar(sesion, Pais) == 1
