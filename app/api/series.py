"""Endpoint JSON de series: GET /api/series."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analisis.indices import ErrorIndice, a_base_100, a_base_100_promedio
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import (
    CotizacionDiaria,
    DatoInternacionalAnual,
    DatoNacionalAnual,
    DatoNacionalMensual,
    Fuente,
    Indicador,
    IndicadorSerieExterna,
    Pais,
    PaisCodigoExterno,
)

# Toda la API exige sesión con el doble factor completo.
router = APIRouter(prefix="/api", dependencies=[Depends(usuario_actual)])

# Máximo de países por pedido; es lo mismo que permite elegir el panel.
MAX_PAISES = 8

# (alcance, frecuencia) -> (tabla, columna del período, columna del valor). Las series anuales usan
# el año; las mensuales y diarias, una fecha (primer día del mes en las mensuales).
TABLAS = {
    ("internacional", "anual"): (DatoInternacionalAnual, "anio", "valor"),
    ("nacional", "anual"): (DatoNacionalAnual, "anio", "valor"),
    ("nacional", "mensual"): (DatoNacionalMensual, "periodo", "valor"),
    ("nacional", "diaria"): (CotizacionDiaria, "fecha", "cierre"),
}
# Las series nacionales son de Uruguay: una sola serie, con este código de país.
PAIS_NACIONAL = "URY"
# Fuentes que publican proyecciones (los años desde la edición del WEO). El BM, el INE y el BCU no.
FUENTES_CON_PROYECCIONES = {"FMI_DM"}


def primer_anio_proyectado(db: Session, indicador_id: int, fte: Fuente, hoy: date | None = None) -> int | None:
    """Primer año que la fuente publica como proyección, o None si la fuente no proyecta.

    Regla conservadora (docs/arquitectura.md, "Proyecciones del FMI"): el menor entre el año de la
    edición del WEO con la que se cargó la serie y el año en curso; sin edición conocida, el año en curso.
    """
    if fte.codigo not in FUENTES_CON_PROYECCIONES:
        return None
    anio = (hoy or date.today()).year
    edicion = db.scalar(
        select(IndicadorSerieExterna.proyeccion_desde).where(
            IndicadorSerieExterna.indicador_id == indicador_id, IndicadorSerieExterna.fuente_id == fte.id
        )
    )
    return min(edicion, anio) if edicion else anio


def tabla_de(ind: Indicador):
    """Columnas (período, valor, indicador_id, fuente_id) de la tabla del indicador, o None si no hay tabla."""
    tabla = TABLAS.get((ind.alcance, ind.frecuencia))
    if tabla is None:
        return None
    modelo, periodo, valor = tabla
    return getattr(modelo, periodo), getattr(modelo, valor), modelo.indicador_id, modelo.fuente_id


def fuentes_del_indicador(db: Session, indicador_id: int) -> list[Fuente]:
    """Fuentes que publican el indicador (según indicadores.csv), en el orden de fuentes.csv."""
    return list(
        db.scalars(
            select(Fuente)
            .join(IndicadorSerieExterna, IndicadorSerieExterna.fuente_id == Fuente.id)
            .where(IndicadorSerieExterna.indicador_id == indicador_id)
            .distinct()
            .order_by(Fuente.id)
        )
    )


def fuente_por_defecto(db: Session, ind: Indicador, fuentes: list[Fuente]) -> Fuente | None:
    """La primera fuente con datos guardados para el indicador (FMI antes que BM); si ninguna tiene, la primera."""
    columnas = tabla_de(ind)
    if columnas:
        periodo, _, col_indicador, col_fuente = columnas
        for fte in fuentes:
            hay = db.scalar(select(periodo).where(col_indicador == ind.id, col_fuente == fte.id).limit(1))
            if hay is not None:
                return fte
    return fuentes[0] if fuentes else None


@router.get("/series")
def obtener_series(
    indicador: str = Query(description="Código interno del indicador, por ejemplo PBI_USD_CORR"),
    paises: str | None = Query(
        None,
        description="Códigos ISO3 o del FMI DataMapper separados por coma: URY,ARG,WEOWORLD. "
        "Obligatorio en los indicadores internacionales; los nacionales son siempre de Uruguay",
    ),
    desde: int | None = Query(None, description="Primer año (inclusive)"),
    hasta: int | None = Query(None, description="Último año (inclusive)"),
    base: int | None = Query(None, description="Año base: si se indica, las series se expresan en índice base 100"),
    fuente: str | None = Query(
        None, description="Código de la fuente (FMI_DM, BM; sin distinguir mayúsculas). Vacío o ausente: la primera con datos"
    ),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.scalar(select(Indicador).where(Indicador.codigo == indicador))
    if ind is None:
        raise HTTPException(404, f"Indicador desconocido: {indicador}")
    if tabla_de(ind) is None:
        raise HTTPException(400, f"Todavía no se pueden consultar series de {indicador} ({ind.alcance}, {ind.frecuencia}).")
    # Nunca se mezclan fuentes: todas las series de la respuesta salen de la misma.
    fuentes = fuentes_del_indicador(db, ind.id)
    # Como los países, la fuente no distingue mayúsculas (bm = BM); vacía equivale a no indicarla.
    pedida = (fuente or "").strip()
    if not pedida:
        fte = fuente_por_defecto(db, ind, fuentes)
        if fte is None:
            raise HTTPException(404, f"El indicador {indicador} no tiene fuentes definidas.")
    else:
        fte = db.scalar(select(Fuente).where(func.upper(Fuente.codigo) == pedida.upper()))
        if fte is None:
            raise HTTPException(404, f"Fuente desconocida: {pedida}")
        if fte not in fuentes:
            disponibles = ", ".join(f.codigo for f in fuentes) or "ninguna"
            raise HTTPException(404, f"La fuente {fte.codigo} no publica {indicador} (disponibles: {disponibles}).")
    if desde is not None and hasta is not None and desde > hasta:
        raise HTTPException(422, "`desde` no puede ser mayor que `hasta`.")

    if ind.alcance == "nacional":
        serie = serie_nacional(db, ind, fte, paises, desde, hasta, base)
        return respuesta(ind, fte, fuentes, base, [serie], None)
    proyeccion = primer_anio_proyectado(db, ind.id, fte)

    # Los códigos no distinguen mayúsculas (ury = URY) y los repetidos se quitan, conservando el orden.
    escritos: dict[str, str] = {}  # código en mayúsculas -> como lo escribió quien pidió
    for c in (paises or "").split(","):
        if c.strip():
            escritos.setdefault(c.strip().upper(), c.strip())
    pedidos = list(escritos)
    if not pedidos:
        raise HTTPException(422, "Indicá al menos un país.")
    if len(pedidos) > MAX_PAISES:
        raise HTTPException(400, f"Se pueden pedir hasta {MAX_PAISES} países a la vez (pediste {len(pedidos)}).")
    # Algunos códigos del FMI tienen minúsculas (FAD_EuroArea): se compara en mayúsculas y se
    # responde con el código tal como está guardado (el del FMI DataMapper si hay dos).
    por_codigo: dict[str, tuple[str, Pais]] = {}
    for organismo, codigo, pais in db.execute(
        select(PaisCodigoExterno.organismo, PaisCodigoExterno.codigo, Pais)
        .join(Pais)
        .where(PaisCodigoExterno.organismo.in_(["ISO3", "FMI_DM"]))
        .where(func.upper(PaisCodigoExterno.codigo).in_(pedidos))
        .order_by(PaisCodigoExterno.organismo)  # FMI_DM antes que ISO3
    ).all():
        por_codigo.setdefault(codigo.upper(), (codigo, pais))
    faltan = [escritos[c] for c in pedidos if c not in por_codigo]
    if faltan:
        raise HTTPException(404, f"Países desconocidos: {', '.join(faltan)}")
    encontrados = list(dict.fromkeys(por_codigo[c] for c in pedidos))  # (código, país) sin repetir

    series = []
    for codigo, pais in encontrados:
        valores = dict(
            db.execute(
                select(DatoInternacionalAnual.anio, DatoInternacionalAnual.valor)
                .where(
                    DatoInternacionalAnual.pais_id == pais.id,
                    DatoInternacionalAnual.indicador_id == ind.id,
                    DatoInternacionalAnual.fuente_id == fte.id,
                )
                .order_by(DatoInternacionalAnual.anio)
            ).all()
        )
        en_rango = lambda anio: (desde is None or anio >= desde) and (hasta is None or anio <= hasta)  # noqa: E731
        # Una serie sin ningún dato en el rango (o en la fuente) vuelve vacía y no participa del índice:
        # el panel la muestra como "sin datos". El 422 queda para la que tiene datos pero no el año base.
        if base is not None and any(v is not None for a, v in valores.items() if en_rango(a)):
            try:
                valores = a_base_100(valores, base)
            except ErrorIndice as e:
                raise HTTPException(422, f"{pais.nombre}: {e}") from e
        datos = [{"anio": anio, "valor": valor} for anio, valor in valores.items() if en_rango(anio)]
        if proyeccion is not None:  # solo las fuentes que proyectan llevan la marca
            for d in datos:
                d["proyeccion"] = d["anio"] >= proyeccion
        series.append({"pais": codigo, "codigo": pais.codigo, "nombre": pais.nombre, "fuente": fte.codigo, "datos": datos})

    return respuesta(ind, fte, fuentes, base, series, proyeccion)


def serie_nacional(
    db: Session, ind: Indicador, fte: Fuente, paises: str | None, desde: int | None, hasta: int | None, base: int | None
) -> dict:
    """La única serie de un indicador nacional (Uruguay). `desde`, `hasta` y `base` son años.

    En las series mensuales y diarias cada dato lleva la fecha ISO ("2024-03-01") en lugar del año, y
    el índice base 100 toma como 100 el promedio del año base.
    """
    otros = sorted({c.strip() for c in (paises or "").split(",") if c.strip() and c.strip().upper() != PAIS_NACIONAL})
    if otros:
        raise HTTPException(400, f"{ind.codigo} es un indicador de Uruguay: no hay series de {', '.join(otros)}.")
    uruguay = db.scalar(select(Pais).where(Pais.iso3 == PAIS_NACIONAL))
    col_periodo, col_valor, col_indicador, col_fuente = tabla_de(ind)
    valores = dict(
        db.execute(
            select(col_periodo, col_valor)
            .where(col_indicador == ind.id, col_fuente == fte.id)
            .order_by(col_periodo)
        ).all()
    )
    anio_de = (lambda p: p.year) if ind.frecuencia != "anual" else (lambda p: p)  # noqa: E731
    en_rango = lambda p: (desde is None or anio_de(p) >= desde) and (hasta is None or anio_de(p) <= hasta)  # noqa: E731
    nombre = uruguay.nombre if uruguay else "Uruguay"
    if base is not None and any(v is not None for p, v in valores.items() if en_rango(p)):
        try:
            valores = a_base_100(valores, base) if ind.frecuencia == "anual" else a_base_100_promedio(valores, base)
        except ErrorIndice as e:
            raise HTTPException(422, f"{nombre}: {e}") from e
    clave = "anio" if ind.frecuencia == "anual" else "fecha"
    datos = [
        {clave: p.isoformat() if isinstance(p, date) else p, "valor": v} for p, v in valores.items() if en_rango(p)
    ]
    return {
        "pais": PAIS_NACIONAL,
        "codigo": uruguay.codigo if uruguay else None,
        "nombre": nombre,
        "fuente": fte.codigo,
        "datos": datos,
    }


def respuesta(
    ind: Indicador, fte: Fuente, fuentes: list[Fuente], base: int | None, series: list[dict], proyeccion: int | None
) -> dict:
    """`proyeccion_desde`: primer año que la fuente publica como proyección (None si la fuente no proyecta)."""
    return {
        "indicador": {
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": "Índice (base 100)" if base is not None else ind.unidad,
            "escala": None if base is not None else ind.escala,
            "alcance": ind.alcance,
            "frecuencia": ind.frecuencia,
        },
        "fuente": fte.codigo,
        "fuente_nombre": fte.nombre,
        "fuentes": [f.codigo for f in fuentes],
        "base": base,
        "proyeccion_desde": proyeccion,
        "series": series,
    }
