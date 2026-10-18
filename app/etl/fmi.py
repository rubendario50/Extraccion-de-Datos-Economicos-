"""Cargador del FMI DataMapper (https://www.imf.org/external/datamapper/api/v1).

Carga en dato_internacional_anual todos los indicadores que en indicadores.csv
tienen fuente FMI_DM: sumar un indicador nuevo es agregar una fila a ese CSV.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.etl.comun import obtener_json, paises_por_codigo, series_de_fuente
from app.etl.upsert import upsert
from app.models import DatoInternacionalAnual, IndicadorSerieExterna

URL_BASE = "https://www.imf.org/external/datamapper/api/v1"
FUENTE = "FMI_DM"

__all__ = ["cargar_fmi", "crear_cliente", "obtener_json", "series_fmi"]

log = logging.getLogger(__name__)


def crear_cliente() -> httpx.Client:
    return httpx.Client(base_url=URL_BASE, timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)


def series_fmi(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas del FMI DataMapper, opcionalmente filtradas por código (NGDPD, ...)."""
    return series_de_fuente(sesion, FUENTE, "FMI", codigos)


def cargar_fmi(
    sesion: Session,
    cliente: httpx.Client,
    codigos: list[str] | None = None,
    espera: float = 2.0,
) -> dict[str, int]:
    """Descarga y guarda (upsert) los indicadores. Devuelve filas guardadas por código externo."""
    series = series_fmi(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores del FMI definidos: corré primero `python -m app.etl semillas`.")
    paises = paises_por_codigo(sesion, FUENTE)
    resultado = {}
    for serie in series:
        codigo = serie.codigo_externo
        factor = serie.factor or 1.0
        datos = obtener_json(cliente, f"/{codigo}", espera=espera).get("values", {}).get(codigo, {})
        ahora = datetime.now(timezone.utc)
        filas, desconocidos = [], []
        for codigo_pais, valores in datos.items():
            pais_id = paises.get(codigo_pais)
            if pais_id is None:
                desconocidos.append(codigo_pais)
                continue
            for anio, valor in valores.items():
                if valor is None:
                    continue
                filas.append({
                    "pais_id": pais_id,
                    "indicador_id": serie.indicador_id,
                    "fuente_id": serie.fuente_id,
                    "anio": int(anio),
                    "valor": float(valor) * factor,
                    "actualizado_en": ahora,
                })
        if desconocidos:
            log.warning("%s: códigos de país sin mapear (se omiten): %s", codigo, ", ".join(sorted(desconocidos)))
        upsert(sesion, DatoInternacionalAnual, filas, claves=["pais_id", "indicador_id", "fuente_id", "anio"])
        sesion.commit()
        resultado[codigo] = len(filas)
        log.info("%s: %d valores guardados", codigo, len(filas))
    return resultado
