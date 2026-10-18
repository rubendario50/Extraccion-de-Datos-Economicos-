"""Funciones compartidas por los cargadores de cada fuente (FMI, Banco Mundial, ...)."""

import logging
import ssl
import time
from pathlib import Path

import certifi
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fuente, IndicadorSerieExterna, PaisCodigoExterno

log = logging.getLogger(__name__)


def contexto_tls(*certificados: Path) -> ssl.SSLContext:
    """Contexto TLS con las autoridades de certifi más certificados intermedios propios.

    Algunos sitios del Estado uruguayo no envían completa la cadena de certificados; en lugar de
    desactivar la verificación se agrega el intermedio que falta (guardado en app/etl/certificados/).
    """
    contexto = ssl.create_default_context(cafile=certifi.where())
    for certificado in certificados:
        contexto.load_verify_locations(cafile=str(certificado))
    return contexto


def pedir(cliente: httpx.Client, metodo: str, ruta: str, reintentos: int = 3, espera: float = 2.0, **opciones) -> httpx.Response:
    """Pedido HTTP con reintentos simples ante errores de red o respuestas 5xx / 429."""
    for intento in range(1, reintentos + 1):
        try:
            respuesta = cliente.request(metodo, ruta, **opciones)
            if respuesta.status_code < 500 and respuesta.status_code != 429:
                respuesta.raise_for_status()
                return respuesta
            error: Exception = httpx.HTTPStatusError(
                f"HTTP {respuesta.status_code}", request=respuesta.request, response=respuesta
            )
        except httpx.TransportError as e:
            error = e
        log.warning("Falló %s (intento %d/%d): %s", ruta, intento, reintentos, error)
        if intento < reintentos:
            time.sleep(espera * intento)
    raise error


def obtener_json(cliente: httpx.Client, ruta: str, reintentos: int = 3, espera: float = 2.0):
    """GET de un JSON, con reintentos (ver `pedir`)."""
    return pedir(cliente, "GET", ruta, reintentos, espera).json()


def obtener_bytes(cliente: httpx.Client, ruta: str, reintentos: int = 3, espera: float = 2.0) -> bytes:
    """GET de un archivo (planilla, etc.), con reintentos (ver `pedir`)."""
    return pedir(cliente, "GET", ruta, reintentos, espera).content


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
