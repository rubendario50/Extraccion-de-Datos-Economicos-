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
    for columna in ("fmi_dm", "fmi_weo", "iso3", "bm"):
        valores = [f[columna] for f in filas if f[columna]]
        assert len(valores) == len(set(valores)), f"{columna} repetido"
    por_dm = {f["fmi_dm"]: f for f in filas}
    assert por_dm["URY"]["nombre"] == "Uruguay" and por_dm["URY"]["fmi_weo"] == "298"
    assert por_dm["ARG"]["fmi_weo"] == "213"
    assert por_dm["WEOWORLD"]["nombre"] == "Mundo" and por_dm["WEOWORLD"]["es_agregado"] == "1"
    assert por_dm["EURO"]["nombre"] == "Zona euro"
    # Código del Banco Mundial: el ISO3 en los países, propio en Kosovo y Palestina y en los agregados equivalentes.
    assert por_dm["URY"]["bm"] == "URY" and por_dm["UVK"]["bm"] == "XKX" and por_dm["WBG"]["bm"] == "PSE"
    assert por_dm["WEOWORLD"]["bm"] == "WLD" and por_dm["EURO"]["bm"] == "EMU"
    # El FMI usa SSA para África Subsahariana; en el BM SSA es otro agregado y no se mapea.
    assert por_dm["SSA"]["bm"] == "" and por_dm["WE"]["bm"] == ""


def test_carga_semillas(sesion):
    resultado = cargar_semillas(sesion)
    assert resultado["paises"] == contar(sesion, Pais) > 300
    assert contar(sesion, Fuente) == resultado["fuentes"]
    uruguay = sesion.scalar(select(Pais).where(Pais.iso3 == "URY"))
    assert uruguay.nombre == "Uruguay" and not uruguay.es_agregado
    codigos = {c.organismo: c.codigo for c in uruguay.codigos_externos}
    assert codigos == {"ISO3": "URY", "FMI_DM": "URY", "FMI_WEO": "298", "BM": "URY"}
    serie = sesion.scalar(select(IndicadorSerieExterna).where(IndicadorSerieExterna.codigo_externo == "NGDPD"))
    assert serie.indicador.codigo == "PBI_USD_CORR" and serie.fuente.codigo == "FMI_DM" and serie.factor is None


def test_mismo_indicador_con_dos_fuentes_y_factor(sesion):
    cargar_semillas(sesion)
    pbi = sesion.scalar(select(Indicador).where(Indicador.codigo == "PBI_USD_CORR"))
    series = {s.fuente.codigo: s for s in pbi.series_externas}
    assert set(series) == {"FMI_DM", "BM"}
    assert series["BM"].codigo_externo == "NY.GDP.MKTP.CD" and series["BM"].factor == 1e-9
    assert pbi.escala == "Miles de millones"
    poblacion = sesion.scalar(select(Indicador).where(Indicador.codigo == "POBLACION"))
    assert {s.fuente.codigo: s.factor for s in poblacion.series_externas} == {"FMI_DM": None, "BM": 1e-6}
    # La deuda del gobierno central (BM) es un indicador distinto de la del gobierno general (FMI).
    central = sesion.scalar(select(Indicador).where(Indicador.codigo == "DEUDA_GOB_CENTRAL"))
    assert [s.fuente.codigo for s in central.series_externas] == ["BM"]


def test_metadatos_del_indicador_salen_de_la_primera_fila(sesion, tmp_path):
    for nombre in ("fuentes.csv", "paises.csv"):
        (tmp_path / nombre).write_text((DIR_SEMILLAS / nombre).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "indicadores.csv").write_text(
        "codigo,nombre,unidad,escala,alcance,frecuencia,descripcion,fuente,codigo_externo,factor\n"
        "X,Primero,U,Miles de millones,internacional,anual,,FMI_DM,XX,\n"
        "X,Segundo,U,Unidades,internacional,anual,,BM,X.Y,1e-9\n",
        encoding="utf-8",
    )
    cargar_semillas(sesion, tmp_path)
    ind = sesion.scalar(select(Indicador).where(Indicador.codigo == "X"))
    assert ind.nombre == "Primero" and ind.escala == "Miles de millones"


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


def test_indicadores_de_uruguay(sesion):
    cargar_semillas(sesion)
    nacionales = {
        i.codigo: (i.frecuencia, [(s.fuente.codigo, s.codigo_externo) for s in i.series_externas])
        for i in sesion.scalars(select(Indicador).where(Indicador.alcance == "nacional"))
    }
    assert nacionales == {
        "IPC_UY": ("mensual", [("INE", "IPC_GENERAL")]),
        "DESEMPLEO_UY": ("mensual", [("INE", "ECH0013")]),
        "DOLAR_INTERBANCARIO": ("diaria", [("BCU", "2225")]),
    }
