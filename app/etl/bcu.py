"""Cargador de cotizaciones del Banco Central del Uruguay (BCU).

Usa el servicio web oficial de cotizaciones (SOAP), el mismo que alimenta la página
https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx:

    POST https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones
    (descripción: ...awsbcucotizaciones?wsdl; lista de monedas: ...awsbcumonedas)

Pide una moneda y un rango de fechas (como máximo 366 días por pedido, si no responde el error
104) y devuelve una cotización por día hábil, la del cierre del día (decisión del cliente). Se
guarda la venta (TCV): en los años recientes compra y venta son iguales, en los primeros años
(2000) difieren en unas milésimas. Datos desde el 3 de enero de 2000. Un rango sin cotizaciones
responde el código 100, que no es un error.

Los valores se guardan tal como los publica el BCU, sin corregirlos. Hay al menos un error de
origen: el 27/04/2000 la venta figura como 1,905 (la compra es 11,900).

Carga en cotizacion_diaria los indicadores que en indicadores.csv tienen fuente BCU; el
`codigo_externo` es el código de moneda del BCU (2225 = DLS. USA BILLETE, interbancario).

Términos de uso del BCU: se puede reproducir citando la fuente y sin fines de lucro; redistribuir o
comercializar requiere autorización expresa del BCU (tenerlo en cuenta antes de publicar o cobrar).
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.etl.comun import pedir, series_de_fuente
from app.etl.upsert import upsert
from app.models import CotizacionDiaria, IndicadorSerieExterna

URL_BASE = "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet"
RUTA = "/awsbcucotizaciones"
FUENTE = "BCU"
FECHA_INICIO = date(2000, 1, 1)
# En una carga incremental se vuelven a pedir los últimos días por si el BCU corrigió alguno.
DIAS_REPASO = 10
SIN_COTIZACIONES = 100  # código de error del BCU: "No existe cotización para la fecha indicada"

NS = {"c": "Cotiza"}

log = logging.getLogger(__name__)


def crear_cliente() -> httpx.Client:
    return httpx.Client(base_url=URL_BASE, timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True)


def _sobre(moneda: str, desde: date, hasta: date) -> str:
    return (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza">'
        "<soapenv:Body><cot:wsbcucotizaciones.Execute><cot:Entrada>"
        f"<cot:Moneda><cot:item>{int(moneda)}</cot:item></cot:Moneda>"
        f"<cot:FechaDesde>{desde.isoformat()}</cot:FechaDesde><cot:FechaHasta>{hasta.isoformat()}</cot:FechaHasta>"
        "<cot:Grupo>0</cot:Grupo>"
        "</cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"
    )


def leer_respuesta(xml: bytes) -> dict[date, float]:
    """Cotizaciones de una respuesta del servicio: {fecha: venta}. Error del BCU -> ValueError."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"BCU: respuesta vacía o mal formada (no es un XML válido: {e}).") from e
    estado = raiz.find(".//c:respuestastatus", NS)
    if estado is None:
        raise ValueError("BCU: respuesta inesperada (sin respuestastatus).")
    if estado.findtext("c:status", namespaces=NS) != "1":
        codigo = int(estado.findtext("c:codigoerror", default="0", namespaces=NS) or 0)
        if codigo == SIN_COTIZACIONES:
            return {}
        mensaje = estado.findtext("c:mensaje", default="", namespaces=NS)
        raise ValueError(f"BCU respondió con el error {codigo}: {mensaje}")
    valores = {}
    for dato in raiz.iterfind(".//c:datoscotizaciones.dato", NS):
        fecha = (dato.findtext("c:Fecha", default="", namespaces=NS) or "").strip()
        venta = (dato.findtext("c:TCV", default="", namespaces=NS) or "").strip()
        if fecha and venta:
            valores[date.fromisoformat(fecha)] = float(venta)
    return valores


def tramos(desde: date, hasta: date) -> list[tuple[date, date]]:
    """Divide el rango en años calendario (el servicio acepta hasta 366 días por pedido)."""
    salida, inicio = [], desde
    while inicio <= hasta:
        fin = min(date(inicio.year, 12, 31), hasta)
        salida.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return salida


def obtener_cotizaciones(
    cliente: httpx.Client, moneda: str, desde: date, hasta: date, espera: float = 2.0
) -> dict[date, float]:
    valores = {}
    for inicio, fin in tramos(desde, hasta):
        respuesta = pedir(
            cliente, "POST", RUTA, espera=espera,
            content=_sobre(moneda, inicio, fin).encode(),
            headers={"Content-Type": "text/xml; charset=utf-8"},
        )
        valores.update(leer_respuesta(respuesta.content))
    return valores


def series_bcu(sesion: Session, codigos: list[str] | None = None) -> list[IndicadorSerieExterna]:
    """Series externas del BCU, opcionalmente filtradas por código de moneda (2225, ...)."""
    return series_de_fuente(sesion, FUENTE, "BCU", codigos)


def cargar_bcu(
    sesion: Session,
    cliente: httpx.Client,
    codigos: list[str] | None = None,
    espera: float = 2.0,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, int]:
    """Descarga y guarda (upsert) las cotizaciones. Devuelve filas guardadas por código de moneda.

    Sin `desde`, la carga es incremental: retoma unos días antes de la última fecha guardada,
    o arranca en 2000 si todavía no hay datos. `hasta` es hoy por defecto.
    """
    series = series_bcu(sesion, codigos)
    if not series:
        raise ValueError("No hay indicadores del BCU definidos: corré primero `python -m app.etl semillas`.")
    hasta = hasta or date.today()
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
            inicio = max(FECHA_INICIO, ultima - timedelta(days=DIAS_REPASO)) if ultima else FECHA_INICIO
        valores = obtener_cotizaciones(cliente, codigo, inicio, hasta, espera)
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
        log.info("%s: %d cotizaciones guardadas (%s a %s)", codigo, len(filas), inicio, hasta)
    return resultado
