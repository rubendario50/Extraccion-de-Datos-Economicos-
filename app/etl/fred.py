"""Cargador de cotizaciones de bolsa y materias primas desde FRED (Banco de la Reserva Federal de St. Louis).

Dos caminos, con el mismo resultado (un dato por día hábil, el cierre del día, decisión del cliente):

1. Con clave (FRED_API_KEY, gratuita en https://fredaccount.stlouisfed.org/apikeys), la API oficial
   (https://fred.stlouisfed.org/docs/api/fred/):

       GET https://api.stlouisfed.org/fred/series/observations?series_id=SP500&api_key=...&file_type=json

   Responde `{"observations": [{"date", "value"}, ...]}`; los feriados vienen con valor "." y no se
   guardan. Los errores llegan con HTTP 400 y `{"error_code", "error_message"}`: si la serie no existe se
   avisa y se sigue con las demás; si la clave no vale, la carga se corta.

2. Sin clave, la descarga CSV del propio sitio de FRED (el botón "Download" de cada gráfica, no scraping):

       GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2026-01-01&coed=2026-01-31

   Responde `observation_date,SP500` y una fila por día; los feriados vienen vacíos y no se guardan. FRED
   respeta `cosd`/`coed`, pero si la ventana pedida no tiene datos devuelve la serie entera: por eso las
   fechas se filtran también acá. Una serie inexistente da 404 con una página HTML (se avisa y se sigue).
   Si un indicador falla (error HTTP, respuesta que no es el CSV esperado) se sigue con los demás y al
   final se lanza `CargaFREDIncompleta`, como en el Banco Mundial.

Carga en cotizacion_diaria los indicadores que en indicadores.csv tienen fuente FRED; el `codigo_externo`
es el código de la serie en FRED (SP500, DJIA, NASDAQCOM, DCOILWTICO, DCOILBRENTEU, DHHNGSP).

Licencias: los índices de S&P Dow Jones Indices (SP500, DJIA) y de Nasdaq (NASDAQCOM) tienen copyright y
restricciones de redistribución (FRED solo publica los últimos 10 años del S&P 500 y del Dow Jones). Los
precios de energía son de la EIA (gobierno de EE.UU.). Revisar las notas de cada serie (`fred/series`)
antes de publicar abiertamente o cobrar.
"""

import csv
import io
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
# Descarga CSV sin clave. URL absoluta: httpx no le antepone la base del cliente (la de la API).
URL_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
COLUMNAS_FECHA_CSV = ("observation_date", "DATE")  # hoy `observation_date`; antes era `DATE`

log = logging.getLogger(__name__)


class SerieInexistente(ValueError):
    """FRED no tiene la serie pedida."""


class CargaFREDIncompleta(ValueError):
    """Uno o más indicadores de FRED fallaron (descarga CSV); los demás se guardaron.

    `guardados`: filas guardadas por código de FRED. `fallos`: mensaje de error por código.
    """

    def __init__(self, guardados: dict[str, int], fallos: dict[str, str]):
        self.guardados = guardados
        self.fallos = fallos
        detalle = "; ".join(f"{codigo}: {error}" for codigo, error in fallos.items())
        super().__init__(
            f"Fallaron {len(fallos)} indicador(es) de FRED: {', '.join(fallos)}. "
            f"Se guardaron {len(guardados)}. Detalle: {detalle}"
        )


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


def leer_csv(texto: str, serie: str) -> dict[date, float]:
    """{fecha: valor} de una descarga fredgraph.csv. Los días vacíos o con "." se omiten.

    Exige el encabezado `observation_date,<serie>` (o `DATE,<serie>`); si no está (por ejemplo, llegó una
    página HTML) o una fila no tiene fecha y número válidos, lanza ValueError.
    """
    filas = list(csv.reader(io.StringIO(texto.lstrip("﻿"))))
    encabezado = [c.strip() for c in filas[0]] if filas else []
    if len(encabezado) != 2 or encabezado[0] not in COLUMNAS_FECHA_CSV or encabezado[1].upper() != serie.upper():
        inicio = " ".join(texto.split())[:60]
        raise ValueError(
            f"FRED: la descarga CSV de {serie} no tiene la forma esperada "
            f"(encabezado `observation_date,{serie}`); llegó: {inicio!r}"
        )
    valores = {}
    for fila in filas[1:]:
        if not any(c.strip() for c in fila):
            continue
        if len(fila) != 2:
            raise ValueError(f"FRED: fila con formato inesperado en el CSV de {serie}: {fila!r}")
        texto_valor = fila[1].strip()
        if not texto_valor or texto_valor == SIN_DATO:
            continue
        try:
            valores[date.fromisoformat(fila[0].strip())] = float(texto_valor)
        except ValueError as e:
            raise ValueError(f"FRED: fila con formato inesperado en el CSV de {serie}: {fila!r}") from e
    return valores


def obtener_csv(
    cliente: httpx.Client, serie: str, desde: date | None, hasta: date | None, espera: float = 2.0
) -> dict[date, float]:
    """Observaciones de una serie entre `desde` y `hasta` (sin límite si son None) con la descarga CSV."""
    params = {"id": serie}
    if desde:
        params["cosd"] = desde.isoformat()
    if hasta:
        params["coed"] = hasta.isoformat()
    try:
        respuesta = pedir(cliente, "GET", URL_CSV, espera=espera, params=params)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise SerieInexistente(f"FRED no tiene la serie {serie}.") from None
        raise ValueError(f"FRED respondió con el error HTTP {e.response.status_code} en {serie} (descarga CSV).") from None
    valores = leer_csv(respuesta.text, serie)
    # Si la ventana pedida no tiene datos, FRED devuelve la serie entera: se filtra siempre.
    return {f: v for f, v in valores.items() if (not desde or f >= desde) and (not hasta or f <= hasta)}


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
    demás. `clave` es FRED_API_KEY por defecto; si está vacía se usa la descarga CSV, donde un indicador que
    falla tampoco frena a los demás (al final se lanza `CargaFREDIncompleta`).
    """
    clave = clave if clave is not None else clave_api()
    series = series_fred(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores de FRED definidos: corré primero `python -m app.etl semillas`.")
    if not clave:
        log.info("FRED: sin FRED_API_KEY, se usa la descarga CSV de fred.stlouisfed.org (fredgraph.csv).")
    resultado, fallos = {}, {}
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
            if clave:
                valores = obtener_observaciones(cliente, codigo, clave, inicio, hasta, espera)
            else:
                valores = obtener_csv(cliente, codigo, inicio, hasta, espera)
        except SerieInexistente as e:
            log.warning("%s Se sigue con las demás.", e)
            resultado[codigo] = 0
            continue
        except (ValueError, httpx.HTTPError) as e:
            if clave:  # con la API, un error corta la carga (por ejemplo, si la clave no vale)
                raise
            fallos[codigo] = str(e)
            log.error("%s: falló la carga (se sigue con los demás): %s", codigo, e)
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
    if fallos:
        raise CargaFREDIncompleta(resultado, fallos)
    return resultado
