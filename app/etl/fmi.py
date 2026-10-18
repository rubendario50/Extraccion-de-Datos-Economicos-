"""Cargador del FMI DataMapper (https://www.imf.org/external/datamapper/api/v1).

Carga en dato_internacional_anual todos los indicadores que en indicadores.csv
tienen fuente FMI_DM: sumar un indicador nuevo es agregar una fila a ese CSV.
"""

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.etl.upsert import upsert
from app.models import DatoInternacionalAnual, Fuente, IndicadorSerieExterna, PaisCodigoExterno

URL_BASE = "https://www.imf.org/external/datamapper/api/v1"
FUENTE = "FMI_DM"

log = logging.getLogger(__name__)


def crear_cliente() -> httpx.Client:
    return httpx.Client(base_url=URL_BASE, timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)


def obtener_json(cliente: httpx.Client, ruta: str, reintentos: int = 3, espera: float = 2.0) -> dict:
    """GET con reintentos simples ante errores de red o respuestas 5xx / 429."""
    for intento in range(1, reintentos + 1):
        try:
            respuesta = cliente.get(ruta)
            if respuesta.status_code < 500 and respuesta.status_code != 429:
                respuesta.raise_for_status()
                return respuesta.json()
            error: Exception = httpx.HTTPStatusError(
                f"HTTP {respuesta.status_code}", request=respuesta.request, response=respuesta
            )
        except httpx.TransportError as e:
            error = e
        log.warning("Falló %s (intento %d/%d): %s", ruta, intento, reintentos, error)
        if intento < reintentos:
            time.sleep(espera * intento)
    raise error


def series_fmi(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas del FMI DataMapper, opcionalmente filtradas por código (NGDPD, ...)."""
    consulta = (
        select(IndicadorSerieExterna)
        .join(Fuente)
        .where(Fuente.codigo == FUENTE)
        .order_by(IndicadorSerieExterna.codigo_externo)
    )
    series = list(sesion.scalars(consulta))
    if codigos:
        conocidas = {s.codigo_externo for s in series}
        faltan = sorted(set(codigos) - conocidas)
        if faltan:
            raise ValueError(
                f"Indicadores del FMI no definidos en indicadores.csv: {', '.join(faltan)}. "
                "Cargá las semillas o agregalos al CSV."
            )
        series = [s for s in series if s.codigo_externo in codigos]
    return series


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
    paises = dict(
        sesion.execute(
            select(PaisCodigoExterno.codigo, PaisCodigoExterno.pais_id).where(
                PaisCodigoExterno.organismo == FUENTE
            )
        ).all()
    )
    resultado = {}
    for serie in series:
        codigo = serie.codigo_externo
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
                    "valor": float(valor),
                    "actualizado_en": ahora,
                })
        if desconocidos:
            log.warning("%s: códigos de país sin mapear (se omiten): %s", codigo, ", ".join(sorted(desconocidos)))
        upsert(sesion, DatoInternacionalAnual, filas, claves=["pais_id", "indicador_id", "fuente_id", "anio"])
        sesion.commit()
        resultado[codigo] = len(filas)
        log.info("%s: %d valores guardados", codigo, len(filas))
    return resultado
