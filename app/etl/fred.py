"""Cargador de cotizaciones de bolsa y materias primas desde FRED (Banco de la Reserva Federal de St. Louis).

Usa la API oficial (https://fred.stlouisfed.org/docs/api/fred/):

    GET https://api.stlouisfed.org/fred/series/observations?series_id=SP500&api_key=...&file_type=json

Pide una clave gratuita (variable FRED_API_KEY; se saca en https://fredaccount.stlouisfed.org/apikeys).
Sin clave la carga falla con un mensaje claro. Responde `{"observations": [{"date", "value"}, ...]}`, un
dato por día hábil (el cierre del día, decisión del cliente); los feriados vienen con valor "." y no se
guardan. Los errores llegan con HTTP 400 y `{"error_code", "error_message"}`: si la serie no existe se
avisa y se sigue con las demás; si la clave no vale, la carga se corta.

Carga en cotizacion_diaria los indicadores que en indicadores.csv tienen fuente FRED; el `codigo_externo`
es el código de la serie en FRED (SP500, DJIA, NASDAQCOM, DCOILWTICO, DCOILBRENTEU, DHHNGSP).

Licencias: los índices de S&P Dow Jones Indices (SP500, DJIA) y de Nasdaq (NASDAQCOM) tienen copyright y
restricciones de redistribución (FRED solo publica los últimos 10 años del S&P 500 y del Dow Jones). Los
precios de energía son de la EIA (gobierno de EE.UU.). Revisar las notas de cada serie (`fred/series`)
antes de publicar abiertamente o cobrar.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.etl.comun import pedir, series_de_fuente
from app.etl.upsert import upsert
from app.models import CotizacionDiaria, IndicadorSerieExterna

URL_BASE = "https://api.stlouisfed.org/fred"
RUTA = "/series/observations"
FUENTE = "FRED"
# En una carga incremental se vuelven a pedir los últimos días por si FRED corrigió alguno.
DIAS_REPASO = 10
# Máximo de observaciones por pedido que acepta la API; las series más largas (Nasdaq desde 1971, unas
# 14 mil) entran en uno, pero se pagina por las dudas.
LIMITE = 100000
SIN_DATO = "."  # así marca FRED un día sin valor (feriado)
URL_CLAVE = "https://fredaccount.stlouisfed.org/apikeys"

log = logging.getLogger(__name__)


class SerieInexistente(ValueError):
    """FRED no tiene la serie pedida."""


def crear_cliente() -> httpx.Client:
    return httpx.Client(base_url=URL_BASE, timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)


def clave_api() -> str:
    return get_settings().fred_api_key.strip()


def leer_observaciones(cuerpo: dict) -> dict[date, float]:
    """{fecha: valor} de una respuesta de fred/series/observations. Los "." (sin dato) se omiten."""
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("observations"), list):
        raise ValueError("FRED: respuesta inesperada (sin `observations`).")
    valores = {}
    for obs in cuerpo["observations"]:
        texto = str(obs.get("value", "")).strip()
        if not texto or texto == SIN_DATO:
            continue
        try:
            valores[date.fromisoformat(obs["date"])] = float(texto)
        except (KeyError, ValueError) as e:
            raise ValueError(f"FRED: observación con formato inesperado: {obs!r}") from e
    return valores


def _mensaje_de_error(respuesta: httpx.Response) -> str:
    try:
        return str(respuesta.json().get("error_message") or "").strip()
    except ValueError:
        return ""


def obtener_observaciones(
    cliente: httpx.Client, serie: str, clave: str, desde: date | None, hasta: date | None, espera: float = 2.0
) -> dict[date, float]:
    """Todas las observaciones de una serie entre `desde` y `hasta` (sin límite si son None)."""
    params = {"series_id": serie, "api_key": clave, "file_type": "json", "sort_order": "asc", "limit": LIMITE}
    if desde:
        params["observation_start"] = desde.isoformat()
    if hasta:
        params["observation_end"] = hasta.isoformat()
    valores: dict[date, float] = {}
    offset = 0
    while True:
        try:
            respuesta = pedir(cliente, "GET", RUTA, espera=espera, params={**params, "offset": offset})
        except httpx.HTTPStatusError as e:
            # El mensaje de httpx incluye la URL con la clave: se arma uno propio con el error de FRED.
            mensaje = _mensaje_de_error(e.response)
            if "does not exist" in mensaje:
                raise SerieInexistente(f"FRED no tiene la serie {serie}.") from None
            if "api_key" in mensaje:
                raise ValueError(f"FRED rechazó la clave (FRED_API_KEY): {mensaje} Sacá una en {URL_CLAVE}.") from None
            raise ValueError(f"FRED respondió con el error HTTP {e.response.status_code} en {serie}: {mensaje or 'sin detalle'}") from None
        try:
            cuerpo = respuesta.json()
        except ValueError as e:
            raise ValueError(f"FRED: respuesta vacía o mal formada en {serie} (no es JSON).") from e
        valores.update(leer_observaciones(cuerpo))
        cantidad = len(cuerpo["observations"])
        if cantidad < LIMITE:
            return valores
        offset += cantidad


def series_fred(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas de FRED, opcionalmente filtradas por código (SP500, ...)."""
    return series_de_fuente(sesion, FUENTE, "FRED", codigos)


def cargar_fred(
    sesion: Session,
    cliente: httpx.Client,
    codigos: list[str] | None = None,
    espera: float = 2.0,
    desde: date | None = None,
    hasta: date | None = None,
    clave: str | None = None,
) -> dict[str, int]:
    """Descarga y guarda (upsert) las cotizaciones. Devuelve filas guardadas por código de FRED.

    Sin `desde`, la carga es incremental: retoma unos días antes de la última fecha guardada, o baja toda
    la serie si todavía no hay datos. Una serie que FRED no tiene, o sin datos, se avisa y no frena a las
    demás. `clave` es FRED_API_KEY por defecto.
    """
    clave = clave if clave is not None else clave_api()
    if not clave:
        raise ValueError(
            f"Falta la clave de FRED: completá FRED_API_KEY en el .env (es gratuita, se saca en {URL_CLAVE})."
        )
    series = series_fred(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores de FRED definidos: corré primero `python -m app.etl semillas`.")
    resultado = {}
    for serie in series:
        codigo = serie.codigo_externo
        inicio = desde
        if inicio is None:
            ultima = sesion.scalar(
                select(func.max(CotizacionDiaria.fecha)).where(
                    CotizacionDiaria.indicador_id == serie.indicador_id, CotizacionDiaria.fuente_id == serie.fuente_id
                )
            )
            inicio = ultima - timedelta(days=DIAS_REPASO) if ultima else None
        try:
            valores = obtener_observaciones(cliente, codigo, clave, inicio, hasta, espera)
        except SerieInexistente as e:
            log.warning("%s Se sigue con las demás.", e)
            resultado[codigo] = 0
            continue
        if not valores:
            log.warning("%s: FRED no devolvió datos (%s a %s).", codigo, inicio or "inicio", hasta or "hoy")
        factor = serie.factor or 1.0
        ahora = datetime.now(timezone.utc)
        filas = [
            {
                "indicador_id": serie.indicador_id,
                "fuente_id": serie.fuente_id,
                "fecha": fecha,
                "cierre": valor * factor,
                "actualizado_en": ahora,
            }
            for fecha, valor in sorted(valores.items())
        ]
        upsert(sesion, CotizacionDiaria, filas, claves=["indicador_id", "fuente_id", "fecha"])
        sesion.commit()
        resultado[codigo] = len(filas)
        log.info("%s: %d cotizaciones guardadas", codigo, len(filas))
    return resultado
