"""Cargador del Banco Mundial, World Development Indicators (https://api.worldbank.org/v2).

Carga en dato_internacional_anual todos los indicadores que en indicadores.csv tienen
fuente BM. Si el BM publica el indicador en otra escala que la del indicador interno
(dólares en vez de miles de millones), la columna `factor` del CSV hace la conversión.

Los países se mapean por la columna `bm` de paises.csv (ISO3 en casi todos los casos).
Los agregados del BM sin equivalente en el FMI (LCN, SSF, grupos de ingreso, ...) se omiten.

Todas las consultas piden explícitamente la base World Development Indicators (`source=2`):
sin ese parámetro la API puede responder con otra base para algunos indicadores (pasó con
NE.EXP.GNFS.CD: 239 filas con `sourceid` null en vez de las ~17.500 de WDI). Por eso además
se exige que cada respuesta de un indicador traiga `sourceid` == "2"; si no, ese indicador
falla en vez de guardar datos parciales.

Si un indicador falla (respuesta de otra base, error del BM, HTTP 502 tras los reintentos, ...)
se sigue con los demás y al final se lanza `CargaBMIncompleta` con la lista de los que fallaron.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.etl.comun import obtener_json, paises_por_codigo, series_de_fuente
from app.etl.upsert import upsert
from app.models import DatoInternacionalAnual, IndicadorSerieExterna

URL_BASE = "https://api.worldbank.org/v2"
FUENTE = "BM"
POR_PAGINA = 20000
# Base del BM que se consulta siempre: 2 = World Development Indicators.
FUENTE_WDI = "2"

log = logging.getLogger(__name__)


class CargaBMIncompleta(ValueError):
    """Uno o más indicadores del BM fallaron; los demás se guardaron.

    `guardados`: filas guardadas por código externo. `fallos`: mensaje de error por código externo.
    """

    def __init__(self, guardados: dict[str, int], fallos: dict[str, str]):
        self.guardados = guardados
        self.fallos = fallos
        detalle = "; ".join(f"{codigo}: {error}" for codigo, error in fallos.items())
        super().__init__(
            f"Fallaron {len(fallos)} indicador(es) del Banco Mundial: {', '.join(fallos)}. "
            f"Se guardaron {len(guardados)}. Detalle: {detalle}"
        )


def crear_cliente() -> httpx.Client:
    return httpx.Client(base_url=URL_BASE, timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True)


def series_bm(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas del Banco Mundial, opcionalmente filtradas por código (NY.GDP.MKTP.CD, ...)."""
    return series_de_fuente(sesion, FUENTE, "Banco Mundial", codigos)


def _pagina(cliente: httpx.Client, ruta: str, espera: float) -> tuple[dict, list]:
    """Pide una página de la API. Devuelve (metadatos, filas).

    El BM responde los errores con HTTP 200 y un cuerpo [{"message": [...]}].
    """
    cuerpo = obtener_json(cliente, ruta, espera=espera)
    if not isinstance(cuerpo, list) or not cuerpo or "message" in cuerpo[0]:
        detalle = cuerpo[0].get("message") if isinstance(cuerpo, list) and cuerpo else cuerpo
        raise ValueError(f"El Banco Mundial respondió con un error para {ruta}: {detalle}")
    return cuerpo[0], (cuerpo[1] if len(cuerpo) > 1 and cuerpo[1] else [])


def obtener_todo(
    cliente: httpx.Client,
    ruta: str,
    espera: float = 2.0,
    por_pagina: int = POR_PAGINA,
    exigir_wdi: bool = False,
) -> list[dict]:
    """Recorre todas las páginas de un recurso del BM (siempre de la base WDI) y devuelve las filas juntas.

    Con `exigir_wdi`, cada página debe declarar `sourceid` == FUENTE_WDI (las respuestas de
    indicadores lo traen; la lista de países no).
    """
    filas, pagina = [], 1
    while True:
        consulta = f"{ruta}?format=json&per_page={por_pagina}&page={pagina}&source={FUENTE_WDI}"
        meta, datos = _pagina(cliente, consulta, espera)
        if exigir_wdi and str(meta.get("sourceid")) != FUENTE_WDI:
            raise ValueError(
                f"El Banco Mundial respondió {ruta} con la base sourceid={meta.get('sourceid')!r} "
                f"(total={meta.get('total')}) en vez de WDI (sourceid={FUENTE_WDI!r}): no se guarda nada"
            )
        filas.extend(datos)
        if pagina >= int(meta.get("pages") or 1):
            return filas
        pagina += 1


def agregados_bm(cliente: httpx.Client, espera: float = 2.0) -> set[str]:
    """Códigos de los agregados del BM (regiones, grupos de ingreso, ...): región "NA"."""
    return {
        p["id"]
        for p in obtener_todo(cliente, "/country", espera, por_pagina=1000)
        if (p.get("region") or {}).get("id") == "NA"
    }


def cargar_bm(
    sesion: Session,
    cliente: httpx.Client,
    codigos: list[str] | None = None,
    espera: float = 2.0,
    por_pagina: int = POR_PAGINA,
) -> dict[str, int]:
    """Descarga y guarda (upsert) los indicadores. Devuelve filas guardadas por código externo."""
    series = series_bm(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores del Banco Mundial definidos: corré primero `python -m app.etl semillas`.")
    paises = paises_por_codigo(sesion, FUENTE)
    agregados = agregados_bm(cliente, espera)
    resultado, fallos = {}, {}
    for serie in series:
        codigo = serie.codigo_externo
        try:
            resultado[codigo] = _cargar_serie(sesion, cliente, serie, paises, agregados, espera, por_pagina)
        except (ValueError, httpx.HTTPError) as e:
            sesion.rollback()
            fallos[codigo] = str(e)
            log.error("%s: falló la carga (se sigue con los demás): %s", codigo, e)
    if fallos:
        raise CargaBMIncompleta(resultado, fallos)
    return resultado


def _cargar_serie(
    sesion: Session,
    cliente: httpx.Client,
    serie: IndicadorSerieExterna,
    paises: dict[str, int],
    agregados: set[str],
    espera: float,
    por_pagina: int,
) -> int:
    """Descarga y guarda un indicador. Devuelve la cantidad de filas guardadas."""
    codigo = serie.codigo_externo
    factor = serie.factor or 1.0
    datos = obtener_todo(cliente, f"/country/all/indicator/{codigo}", espera, por_pagina, exigir_wdi=True)
    ahora = datetime.now(timezone.utc)
    filas, desconocidos, omitidos = [], set(), set()
    for d in datos:
        # Los grupos de ingreso no tienen código ISO3: se omiten igual que los demás agregados.
        codigo_pais = d.get("countryiso3code") or ""
        pais_id = paises.get(codigo_pais)
        if pais_id is None:
            if not codigo_pais or codigo_pais in agregados:
                omitidos.add(codigo_pais or (d.get("country") or {}).get("id", ""))
            else:
                desconocidos.add(codigo_pais)
            continue
        if d.get("value") is None:
            continue
        filas.append({
            "pais_id": pais_id,
            "indicador_id": serie.indicador_id,
            "fuente_id": serie.fuente_id,
            "anio": int(d["date"]),
            "valor": float(d["value"]) * factor,
            "actualizado_en": ahora,
        })
    if desconocidos:
        log.warning("%s: códigos de país sin mapear (se omiten): %s", codigo, ", ".join(sorted(desconocidos)))
    if omitidos:
        log.info("%s: %d agregados del BM sin equivalente (se omiten)", codigo, len(omitidos))
    upsert(sesion, DatoInternacionalAnual, filas, claves=["pais_id", "indicador_id", "fuente_id", "anio"])
    sesion.commit()
    log.info("%s: %d valores guardados", codigo, len(filas))
    return len(filas)
