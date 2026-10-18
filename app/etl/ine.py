"""Cargador del Instituto Nacional de Estadística de Uruguay (INE).

El INE no tiene API: publica sus series como planillas Excel (.xlsx) con dirección fija en
https://www5.ine.gub.uy/documents/..., enlazadas desde https://www.gub.uy/instituto-nacional-estadistica.
Cada planilla se reemplaza en el mismo lugar cuando sale un dato nuevo. Sus términos de uso
consideran pública la información y admiten el acceso "a través de una aplicación informática".

Carga en dato_nacional_mensual los indicadores que en indicadores.csv tienen fuente INE. El
`codigo_externo` de cada uno elige la planilla y la forma de leerla (ver ARCHIVOS):

- IPC_GENERAL: "IPC gral y variaciones_base 2022.xlsx", índice general total país, mensual desde
  julio de 1937 (base octubre 2022 = 100). Columnas "Mes y año" (fecha) e "Índice".
- ECH0013: "Tasa de desempleo, por área geográfica" de la Encuesta Continua de Hogares, columna
  "Total País", desde 2006. La planilla intercala meses, trimestres ("Enero - Marzo/06") y el
  total anual; solo se guardan los meses (los trimestres y el año se derivan de los meses; desde
  2020 son su promedio simple, según la nota (14) de la propia planilla).

Si el INE cambia el formato y no se encuentran las columnas esperadas, la carga falla con un
error claro en lugar de guardar datos equivocados.
"""

import io
import logging
import re
import unicodedata
import zipfile
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import openpyxl
from sqlalchemy.orm import Session

from app.etl.comun import contexto_tls, obtener_bytes, series_de_fuente
from app.etl.upsert import upsert
from app.models import DatoNacionalMensual, IndicadorSerieExterna

URL_BASE = "https://www5.ine.gub.uy/documents"
FUENTE = "INE"
# El servidor del INE no envía el certificado intermedio de Sectigo (ver comun.contexto_tls).
CERTIFICADO_INTERMEDIO = Path(__file__).resolve().parent / "certificados" / "sectigo_dv_r36.pem"

log = logging.getLogger(__name__)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def crear_cliente() -> httpx.Client:
    return httpx.Client(
        base_url=URL_BASE,
        timeout=httpx.Timeout(120.0, connect=15.0),
        follow_redirects=True,
        verify=contexto_tls(CERTIFICADO_INTERMEDIO),
    )


def _normalizar(texto) -> str:
    """Minúsculas, sin tildes ni espacios sobrantes: "Total País " -> "total pais"."""
    sin_tildes = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def _filas(contenido: bytes) -> list[tuple]:
    """Filas de la primera hoja de una planilla .xlsx (solo valores)."""
    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        # Archivo vacío, una página HTML de error o un .xlsx incompleto.
        inicio = contenido[:60].decode("utf-8", "replace").strip() or "(vacío)"
        raise ValueError(f"INE: el archivo descargado no es un xlsx válido (empieza con: {inicio!r}).") from e
    try:
        return list(libro.worksheets[0].iter_rows(values_only=True))
    finally:
        libro.close()


def _columna(filas: list[tuple], encabezado: str, archivo: str) -> tuple[int, int]:
    """Busca la celda con ese encabezado. Devuelve (fila, columna)."""
    buscado = _normalizar(encabezado)
    for i, fila in enumerate(filas):
        for j, celda in enumerate(fila):
            if celda is not None and _normalizar(celda) == buscado:
                return i, j
    raise ValueError(f"INE {archivo}: no se encontró la columna «{encabezado}». ¿Cambió el formato de la planilla?")


def _es_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def leer_ipc(contenido: bytes) -> dict[date, float]:
    """IPC general: {primer día del mes: índice}."""
    filas = _filas(contenido)
    fila_enc, col_fecha = _columna(filas, "Mes y año", "IPC")
    _, col_indice = _columna(filas, "Índice", "IPC")
    valores = {}
    for fila in filas[fila_enc + 1 :]:
        fecha = fila[col_fecha] if col_fecha < len(fila) else None
        valor = fila[col_indice] if col_indice < len(fila) else None
        if isinstance(fecha, datetime) and _es_numero(valor):
            valores[date(fecha.year, fecha.month, 1)] = float(valor)
    return valores


def leer_desempleo(contenido: bytes) -> dict[date, float]:
    """Tasa de desempleo mensual, total país: {primer día del mes: porcentaje}."""
    filas = _filas(contenido)
    fila_enc, col_total = _columna(filas, "Total País", "ECH0013")
    valores, anio = {}, None
    for fila in filas[fila_enc + 1 :]:
        etiqueta = fila[0] if fila else None
        if etiqueta is None:
            continue
        # Fila de año: 2007, o un texto que empieza con el año ("2018 (9)", "2020 (12) (13)").
        if _es_numero(etiqueta) and 1900 < etiqueta < 2200:
            anio = int(etiqueta)
            continue
        texto = _normalizar(etiqueta)
        if m := re.fullmatch(r"(\d{4})( \(\d+\))*", texto):
            anio = int(m.group(1))
            continue
        # Fila de mes: "Enero", "Junio ", "Abril (10)". Los trimestres llevan guion y el año empieza con "total".
        mes = MESES.get(texto.split(" ")[0])
        if mes is None or "-" in texto or anio is None:
            continue
        valor = fila[col_total] if col_total < len(fila) else None
        if _es_numero(valor):
            valores[date(anio, mes, 1)] = float(valor)
    return valores


# Código externo (columna codigo_externo de indicadores.csv) -> (planilla dentro de URL_BASE, lector).
ARCHIVOS: dict[str, tuple[str, Callable[[bytes], dict[date, float]]]] = {
    "IPC_GENERAL": (
        "/Estadísticaseconómicas/SERIES Y OTROS/IPC/Base Octubre 2022=100/IPC gral y variaciones_base 2022.xlsx",
        leer_ipc,
    ),
    "ECH0013": (
        "/DemografíayEESS/SERIES Y OTROS/ECH/Series históricas/Actividad, empleo y desempleo/ECH0013.xlsx",
        leer_desempleo,
    ),
}


def series_ine(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas del INE, opcionalmente filtradas por código (IPC_GENERAL, ECH0013)."""
    return series_de_fuente(sesion, FUENTE, "INE", codigos)


def cargar_ine(
    sesion: Session,
    cliente: httpx.Client,
    codigos: list[str] | None = None,
    espera: float = 2.0,
) -> dict[str, int]:
    """Descarga las planillas y guarda (upsert) los valores. Devuelve filas guardadas por código externo."""
    series = series_ine(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores del INE definidos: corré primero `python -m app.etl semillas`.")
    resultado = {}
    for serie in series:
        codigo = serie.codigo_externo
        if codigo not in ARCHIVOS:
            raise ValueError(f"INE: no hay lector para el código {codigo!r} (definidos: {', '.join(ARCHIVOS)}).")
        ruta, lector = ARCHIVOS[codigo]
        valores = lector(obtener_bytes(cliente, ruta, espera=espera))
        if not valores:
            raise ValueError(f"INE {codigo}: la planilla no tiene datos reconocibles. ¿Cambió el formato?")
        factor = serie.factor or 1.0
        ahora = datetime.now(timezone.utc)
        filas = [
            {
                "indicador_id": serie.indicador_id,
                "fuente_id": serie.fuente_id,
                "periodo": periodo,
                "valor": valor * factor,
                "actualizado_en": ahora,
            }
            for periodo, valor in sorted(valores.items())
        ]
        upsert(sesion, DatoNacionalMensual, filas, claves=["indicador_id", "fuente_id", "periodo"])
        sesion.commit()
        resultado[codigo] = len(filas)
        log.info("%s: %d valores guardados (%s a %s)", codigo, len(filas), filas[0]["periodo"], filas[-1]["periodo"])
    return resultado
