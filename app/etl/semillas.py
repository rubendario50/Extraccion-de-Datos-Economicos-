"""Carga idempotente de las semillas versionadas en data/seed/."""

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.etl.upsert import upsert
from app.models import Fuente, Indicador, IndicadorSerieExterna, Pais, PaisCodigoExterno

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


def cargar_semillas(sesion: Session, directorio: Path = DIR_SEMILLAS) -> dict[str, int]:
    resultado = {
        "paises": cargar_paises(sesion, directorio / "paises.csv"),
        "fuentes": cargar_fuentes(sesion, directorio / "fuentes.csv"),
        "indicadores": cargar_indicadores(sesion, directorio / "indicadores.csv"),
    }
    sesion.commit()
    return resultado
