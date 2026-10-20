"""Portada de las pantallas de ingreso y registro: qué datos hay, con una muestra real.

Todo sale de la base al armar la página (el visitante no tiene sesión, así que no hay pedidos a la API).
Si la base todavía no tiene datos, la portada muestra solo el lema. Las consultas son agregadas y la página
es pública, así que el resultado se guarda unos minutos por base de datos.
"""

import math
import time
import weakref
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analisis.indices import ErrorIndice, a_base_100
from app.api.series import TABLAS, primer_anio_proyectado
from app.models import DatoInternacionalAnual, Fuente, Indicador, Pais, PaisCodigoExterno
from app.web.panel import NOMBRES_CORTOS_FUENTE, NOMBRES_FUENTE

# Muestra: PBI en dólares corrientes del FMI, índice base 100, Uruguay frente a sus vecinos.
MUESTRA_INDICADOR = "PBI_USD_CORR"
MUESTRA_FUENTE = "FMI_DM"
MUESTRA_PAISES = ["URY", "ARG", "BRA"]
MUESTRA_BASE = 2000

# Coordenadas del dibujo (viewBox). El SVG se estira al ancho disponible; los textos van en HTML.
# El eje vertical va de una marca redonda a otra, así las etiquetas (en HTML) quedan parejas.
ANCHO, ALTO = 600.0, 200.0

# Cuánto se guarda la portada ya armada (segundos).
CACHE_SEGUNDOS = 300
_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

FRECUENCIAS = {"anual": ("anual", "anuales"), "mensual": ("mensual", "mensuales"), "diaria": ("diario", "diarios")}


def _anio(periodo) -> int:
    return periodo if isinstance(periodo, int) else periodo.year


def rango(desde: int, hasta: int) -> str:
    """«1980–2025», o un solo año si empieza y termina en el mismo."""
    return str(desde) if desde == hasta else f"{desde}–{hasta}"


def _cobertura(db: Session, hoy: date) -> list[dict]:
    """Por fuente con datos: qué publica (indicadores y frecuencia) y desde/hasta qué año.

    En las tablas anuales, los años posteriores al último cerrado son proyecciones (el FMI publica
    estimaciones hasta varios años adelante): se cuentan aparte para no presentarlas como datos. En el
    FMI el último cerrado es el anterior al primer año proyectado, con la misma regla que la API.
    Las series mensuales y diarias del año en curso sí son datos publicados.
    """
    indicadores = {i.id: i for i in db.scalars(select(Indicador))}
    fuentes = {f.id: f for f in db.scalars(select(Fuente).order_by(Fuente.id))}

    def ultimo_cerrado(fuente_id: int, indicador_id: int) -> int:
        proyectado = primer_anio_proyectado(db, indicador_id, fuentes[fuente_id], hoy)
        return (proyectado if proyectado is not None else hoy.year) - 1

    por_fuente: dict[int, dict] = {}
    for (_, frecuencia), (modelo, col_periodo, col_valor) in TABLAS.items():
        periodo, valor = getattr(modelo, col_periodo), getattr(modelo, col_valor)
        filas = db.execute(
            select(modelo.fuente_id, modelo.indicador_id, func.min(periodo), func.max(periodo))
            .where(valor.is_not(None))
            .group_by(modelo.fuente_id, modelo.indicador_id)
        ).all()
        for fuente_id, indicador_id, desde, hasta in filas:
            desde, hasta = _anio(desde), _anio(hasta)
            cerrado = ultimo_cerrado(fuente_id, indicador_id) if frecuencia == "anual" else None
            proyectado = hasta if cerrado is not None and hasta > cerrado else None
            if proyectado is not None:
                hasta = max(desde, cerrado)
            f = por_fuente.setdefault(fuente_id, {"indicadores": set(), "desde": desde, "hasta": hasta, "proyectado": None})
            f["indicadores"].add(indicador_id)
            f["desde"] = min(f["desde"], desde)
            f["hasta"] = max(f["hasta"], hasta)
            if proyectado is not None:
                f["proyectado"] = max(f["proyectado"] or proyectado, proyectado)

    salida = []
    for fuente_id, f in sorted(por_fuente.items()):
        fte = fuentes[fuente_id]
        inds = sorted((indicadores[i] for i in f["indicadores"]), key=lambda i: i.id)
        partes = []
        for frecuencia in FRECUENCIAS:
            del_tipo = [i for i in inds if i.frecuencia == frecuencia]
            singular, plural = FRECUENCIAS[frecuencia]
            if len(del_tipo) == 1:
                partes.append(f"{del_tipo[0].nombre}, {singular}")
            elif del_tipo:
                partes.append(f"{len(del_tipo)} indicadores {plural}")
        proyectado = f["proyectado"] if f["proyectado"] and f["proyectado"] > f["hasta"] else None
        salida.append({
            "corto": NOMBRES_CORTOS_FUENTE.get(fte.codigo, fte.codigo),
            "nombre": NOMBRES_FUENTE.get(fte.codigo, fte.nombre),
            "que": "; ".join(partes),
            "desde": f["desde"],
            "hasta": f["hasta"],
            "anios": rango(f["desde"], f["hasta"]),
            "proyecciones_hasta": proyectado,
        })
    return salida


def _paises(db: Session) -> dict:
    """Cuántos países y regiones tienen algún dato internacional."""
    filas = db.execute(
        select(Pais.es_agregado, func.count(func.distinct(DatoInternacionalAnual.pais_id)))
        .join(Pais, Pais.id == DatoInternacionalAnual.pais_id)
        .where(DatoInternacionalAnual.valor.is_not(None))
        .group_by(Pais.es_agregado)
    ).all()
    conteo = {bool(agregado): n for agregado, n in filas}
    return {"paises": conteo.get(False, 0), "regiones": conteo.get(True, 0)}


def _muestra(db: Session, hoy: date) -> dict | None:
    """Líneas del índice base 100 (hasta el último año cerrado, sin proyecciones). None si faltan datos."""
    ind = db.scalar(select(Indicador).where(Indicador.codigo == MUESTRA_INDICADOR))
    fte = db.scalar(select(Fuente).where(Fuente.codigo == MUESTRA_FUENTE))
    if ind is None or fte is None:
        return None
    ultimo = primer_anio_proyectado(db, ind.id, fte, hoy) - 1
    series = []
    for codigo in MUESTRA_PAISES:
        pais = db.scalar(
            select(Pais).join(PaisCodigoExterno, PaisCodigoExterno.pais_id == Pais.id)
            .where(PaisCodigoExterno.organismo == MUESTRA_FUENTE, PaisCodigoExterno.codigo == codigo)
        )
        if pais is None:
            continue
        valores = dict(db.execute(
            select(DatoInternacionalAnual.anio, DatoInternacionalAnual.valor).where(
                DatoInternacionalAnual.pais_id == pais.id,
                DatoInternacionalAnual.indicador_id == ind.id,
                DatoInternacionalAnual.fuente_id == fte.id,
                DatoInternacionalAnual.anio.between(MUESTRA_BASE, ultimo),
                DatoInternacionalAnual.valor.is_not(None),
            )
        ).all())
        try:
            indice = a_base_100(valores, MUESTRA_BASE)
        except ErrorIndice:
            continue
        if len(indice) >= 2:
            series.append({"nombre": pais.nombre, "puntos": dict(sorted(indice.items()))})
    if len(series) < 2:
        return None

    desde = MUESTRA_BASE
    hasta = max(max(s["puntos"]) for s in series)
    todos = [v for s in series for v in s["puntos"].values()] + [100.0]
    marcas = _marcas(min(todos), max(todos))
    minimo, maximo = marcas[0], marcas[-1]

    def x(anio: int) -> float:
        return round((anio - desde) / (hasta - desde) * ANCHO, 1)

    def y(v: float) -> float:
        return round((maximo - v) / (maximo - minimo) * ALTO, 1)

    for i, s in enumerate(series, start=1):
        s["ranura"] = i
        s["trazo"] = " ".join(f"{x(a)},{y(v)}" for a, v in s["puntos"].items())
        s["anio_final"], s["final"] = max(s["puntos"].items())
        s["final_texto"] = f"{s['final']:,.0f}".replace(",", ".")
    descripcion = ", ".join(f"{s['nombre']} {s['final_texto']}" for s in series)
    return {
        "series": series,
        "desde": desde,
        "hasta": hasta,
        "base": MUESTRA_BASE,
        "y_base": y(100.0),
        # De arriba hacia abajo, como se leen las etiquetas del eje.
        "marcas": [{"y": y(m), "texto": f"{m:,.0f}".replace(",", ".")} for m in reversed(marcas)],
        "ancho": ANCHO,
        "alto": ALTO,
        "descripcion": f"Índice del PBI en dólares corrientes, {MUESTRA_BASE} = 100, de {desde} a {hasta}: {descripcion}.",
    }


def _marcas(minimo: float, maximo: float, cuantas: int = 4) -> list[float]:
    """Marcas redondas del eje (1, 2 o 5 por una potencia de 10) que cubren [minimo, maximo]."""
    crudo = (maximo - minimo) / cuantas or 1.0
    potencia = 10 ** math.floor(math.log10(crudo))
    paso = next(m * potencia for m in (1, 2, 5, 10) if m * potencia >= crudo)
    desde, hasta = math.floor(minimo / paso) * paso, math.ceil(maximo / paso) * paso
    return [desde + i * paso for i in range(round((hasta - desde) / paso) + 1)]


def _armar(db: Session, hoy: date) -> dict | None:
    cobertura = _cobertura(db, hoy)
    if not cobertura:
        return None
    return {"fuentes": cobertura, "muestra": _muestra(db, hoy), **_paises(db)}


def datos_portada(db: Session, hoy: date | None = None) -> dict | None:
    """Muestra, fuentes y cobertura para la portada; None si la base no tiene datos todavía.

    Sin `hoy` (el caso de las páginas), el resultado se guarda CACHE_SEGUNDOS por base de datos.
    """
    if hoy is not None:
        return _armar(db, hoy)
    motor, hoy, ahora = db.get_bind(), date.today(), time.monotonic()
    guardado = _cache.get(motor)
    if guardado and guardado[0] > ahora and guardado[1] == hoy:
        return guardado[2]
    datos = _armar(db, hoy)
    _cache[motor] = (ahora + CACHE_SEGUNDOS, hoy, datos)
    return datos
