"""Cargador del Banco Mundial, World Development Indicators (https://api.worldbank.org/v2).

Carga en dato_internacional_anual todos los indicadores que en indicadores.csv tienen
fuente BM. Si el BM publica el indicador en otra escala que la del indicador interno
(dólares en vez de miles de millones), la columna `factor` del CSV hace la conversión.

Los países se mapean por la columna `bm` de paises.csv (ISO3 en casi todos los casos).
Los agregados del BM sin equivalente en el FMI (LCN, SSF, grupos de ingreso, ...) se omiten.
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

log = logging.getLogger(__name__)


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


def obtener_todo(cliente: httpx.Client, ruta: str, espera: float = 2.0, por_pagina: int = POR_PAGINA) -> list[dict]:
    """Recorre todas las páginas de un recurso del BM y devuelve las filas juntas."""
    filas, pagina = [], 1
    while True:
        meta, datos = _pagina(cliente, f"{ruta}?format=json&per_page={por_pagina}&page={pagina}", espera)
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
    resultado = {}
    for serie in series:
        codigo = serie.codigo_externo
        factor = serie.factor or 1.0
        datos = obtener_todo(cliente, f"/country/all/indicator/{codigo}", espera, por_pagina)
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
        resultado[codigo] = len(filas)
        log.info("%s: %d valores guardados", codigo, len(filas))
    return resultado
