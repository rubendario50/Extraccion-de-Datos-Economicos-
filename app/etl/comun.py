"""Funciones compartidas por los cargadores de cada fuente (FMI, Banco Mundial, ...)."""

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fuente, IndicadorSerieExterna, PaisCodigoExterno

log = logging.getLogger(__name__)


def obtener_json(cliente: httpx.Client, ruta: str, reintentos: int = 3, espera: float = 2.0):
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


def series_de_fuente(
    sesion: Session, fuente: str, nombre: str, codigos: list[str] | None = None
) -> list[IndicadorSerieExterna]:
    """Series externas de una fuente, opcionalmente filtradas por código externo."""
    consulta = (
        select(IndicadorSerieExterna)
        .join(Fuente)
        .where(Fuente.codigo == fuente)
        .order_by(IndicadorSerieExterna.codigo_externo)
    )
    series = list(sesion.scalars(consulta))
    if codigos:
        conocidas = {s.codigo_externo for s in series}
        faltan = sorted(set(codigos) - conocidas)
        if faltan:
            raise ValueError(
                f"Indicadores del {nombre} no definidos en indicadores.csv: {', '.join(faltan)}. "
                "Cargá las semillas o agregalos al CSV."
            )
        series = [s for s in series if s.codigo_externo in codigos]
    return series


def paises_por_codigo(sesion: Session, organismo: str) -> dict[str, int]:
    """Código del país en un organismo -> pais_id."""
    return dict(
        sesion.execute(
            select(PaisCodigoExterno.codigo, PaisCodigoExterno.pais_id).where(
                PaisCodigoExterno.organismo == organismo
            )
        ).all()
    )
