"""Carga idempotente de las semillas versionadas en data/seed/."""

import csv
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.etl.upsert import upsert
from app.models import Fuente, Grupo, GrupoPais, Indicador, IndicadorSerieExterna, Pais, PaisCodigoExterno

DIR_SEMILLAS = Path(__file__).resolve().parents[2] / "data" / "seed"

# Columna de paises.csv -> organismo en pais_codigo_externo.
ORGANISMOS = {"iso3": "ISO3", "fmi_dm": "FMI_DM", "fmi_weo": "FMI_WEO", "bm": "BM"}


def _leer_csv(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in fila.items()} for fila in csv.DictReader(f)]


def cargar_paises(sesion: Session, ruta: Path) -> int:
    filas = _leer_csv(ruta)
    upsert(
        sesion,
        Pais,
        [
            {
                "codigo": f["codigo"],
                "nombre": f["nombre"],
                "nombre_en": f["nombre_en"],
                "iso2": f["iso2"] or None,
                "iso3": f["iso3"] or None,
                "es_agregado": f["es_agregado"] == "1",
            }
            for f in filas
        ],
        claves=["codigo"],
    )
    ids = dict(sesion.execute(select(Pais.codigo, Pais.id)).all())
    codigos = [
        {"pais_id": ids[f["codigo"]], "organismo": organismo, "codigo": f[columna]}
        for f in filas
        for columna, organismo in ORGANISMOS.items()
        if f.get(columna)
    ]
    upsert(sesion, PaisCodigoExterno, codigos, claves=["organismo", "codigo"])
    return len(filas)


def cargar_fuentes(sesion: Session, ruta: Path) -> int:
    filas = _leer_csv(ruta)
    upsert(sesion, Fuente, [{**f, "url": f["url"] or None} for f in filas], claves=["codigo"])
    return len(filas)


def cargar_indicadores(sesion: Session, ruta: Path) -> int:
    """Cada fila define un indicador interno y su código en una fuente.

    Un mismo indicador puede repetirse en varias filas con distinta fuente: el nombre, la unidad
    y la escala salen de la primera fila. La columna opcional `factor` lleva el valor de la fuente
    a esa escala (por ejemplo 1e-9 para pasar dólares a miles de millones).
    """
    filas = _leer_csv(ruta)
    campos = ["codigo", "nombre", "unidad", "escala", "alcance", "frecuencia", "descripcion"]
    indicadores: dict[str, dict] = {}
    for f in filas:
        indicadores.setdefault(f["codigo"], {c: f[c] or None for c in campos})
    upsert(sesion, Indicador, list(indicadores.values()), claves=["codigo"])

    ids_indicador = dict(sesion.execute(select(Indicador.codigo, Indicador.id)).all())
    ids_fuente = dict(sesion.execute(select(Fuente.codigo, Fuente.id)).all())
    series = []
    for f in filas:
        if f["fuente"] not in ids_fuente:
            raise ValueError(f"Indicador {f['codigo']}: fuente desconocida {f['fuente']!r}")
        series.append({
            "indicador_id": ids_indicador[f["codigo"]],
            "fuente_id": ids_fuente[f["fuente"]],
            "codigo_externo": f["codigo_externo"],
            "factor": float(f["factor"]) if f.get("factor") else None,
        })
    upsert(sesion, IndicadorSerieExterna, series, claves=["fuente_id", "codigo_externo"])
    return len(indicadores)


def cargar_grupos(sesion: Session, ruta_grupos: Path, ruta_miembros: Path) -> int:
    """Grupos de países y sus miembros (con el código interno del país).

    La columna `iso3` de grupos_paises.csv repite el código ISO del país para leer el archivo sin buscar cada
    código interno; si no coincide con el de paises.csv, la carga falla (así un error de tipeo no mete a otro
    país en el grupo). Los miembros de cada grupo se reemplazan por los del CSV: sacar una fila saca al país.
    """
    grupos = _leer_csv(ruta_grupos)
    upsert(
        sesion,
        Grupo,
        [{"codigo": g["codigo"], "nombre": g["nombre"], "descripcion": g["descripcion"] or None} for g in grupos],
        claves=["codigo"],
    )
    ids_grupo = dict(sesion.execute(select(Grupo.codigo, Grupo.id)).all())
    paises = {p.codigo: p for p in sesion.scalars(select(Pais)).all()}
    miembros = []
    for f in _leer_csv(ruta_miembros):
        if f["grupo"] not in ids_grupo:
            raise ValueError(f"grupos_paises.csv: grupo desconocido {f['grupo']!r}")
        pais = paises.get(f["pais"])
        if pais is None:
            raise ValueError(f"grupos_paises.csv: país desconocido {f['pais']!r} en {f['grupo']}")
        if f.get("iso3") and f["iso3"] != pais.iso3:
            raise ValueError(f"grupos_paises.csv: el país {f['pais']} es {pais.iso3}, no {f['iso3']} ({f['grupo']})")
        miembros.append({"grupo_id": ids_grupo[f["grupo"]], "pais_id": pais.id})
    ids_cargados = [ids_grupo[g["codigo"]] for g in grupos]
    sesion.execute(delete(GrupoPais).where(GrupoPais.grupo_id.in_(ids_cargados)))
    upsert(sesion, GrupoPais, miembros, claves=["grupo_id", "pais_id"])
    return len(grupos)


def cargar_semillas(sesion: Session, directorio: Path = DIR_SEMILLAS) -> dict[str, int]:
    resultado = {
        "paises": cargar_paises(sesion, directorio / "paises.csv"),
        "fuentes": cargar_fuentes(sesion, directorio / "fuentes.csv"),
        "indicadores": cargar_indicadores(sesion, directorio / "indicadores.csv"),
    }
    # Los grupos son opcionales (una carpeta de semillas de prueba puede no tenerlos).
    if (directorio / "grupos.csv").exists():
        resultado["grupos"] = cargar_grupos(sesion, directorio / "grupos.csv", directorio / "grupos_paises.csv")
    sesion.commit()
    return resultado
