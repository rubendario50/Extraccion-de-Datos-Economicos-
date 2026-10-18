"""Endpoint JSON de series: GET /api/series."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analisis.indices import ErrorIndice, a_base_100
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import DatoInternacionalAnual, Fuente, Indicador, IndicadorSerieExterna, Pais, PaisCodigoExterno

# Toda la API exige sesión con el doble factor completo.
router = APIRouter(prefix="/api", dependencies=[Depends(usuario_actual)])

# Máximo de países por pedido; es lo mismo que permite elegir el panel.
MAX_PAISES = 8


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


def fuente_por_defecto(db: Session, indicador_id: int, fuentes: list[Fuente]) -> Fuente | None:
    """La primera fuente con datos guardados para el indicador (FMI antes que BM); si ninguna tiene, la primera."""
    for fte in fuentes:
        hay = db.scalar(
            select(DatoInternacionalAnual.anio)
            .where(DatoInternacionalAnual.indicador_id == indicador_id, DatoInternacionalAnual.fuente_id == fte.id)
            .limit(1)
        )
        if hay is not None:
            return fte
    return fuentes[0] if fuentes else None


@router.get("/series")
def obtener_series(
    indicador: str = Query(description="Código interno del indicador, por ejemplo PBI_USD_CORR"),
    paises: str = Query(description="Códigos ISO3 o del FMI DataMapper separados por coma: URY,ARG,WEOWORLD"),
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
    if (ind.alcance, ind.frecuencia) != ("internacional", "anual"):
        raise HTTPException(400, f"Por ahora solo hay series internacionales anuales ({indicador} es {ind.alcance} {ind.frecuencia}).")
    # Nunca se mezclan fuentes: todas las series de la respuesta salen de la misma.
    fuentes = fuentes_del_indicador(db, ind.id)
    # Como los países, la fuente no distingue mayúsculas (bm = BM); vacía equivale a no indicarla.
    pedida = (fuente or "").strip()
    if not pedida:
        fte = fuente_por_defecto(db, ind.id, fuentes)
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

    # Los códigos no distinguen mayúsculas (ury = URY) y los repetidos se quitan, conservando el orden.
    escritos: dict[str, str] = {}  # código en mayúsculas -> como lo escribió quien pidió
    for c in paises.split(","):
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
        series.append({"pais": codigo, "codigo": pais.codigo, "nombre": pais.nombre, "fuente": fte.codigo, "datos": datos})

    return {
        "indicador": {
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": "Índice (base 100)" if base is not None else ind.unidad,
            "escala": None if base is not None else ind.escala,
        },
        "fuente": fte.codigo,
        "fuente_nombre": fte.nombre,
        "fuentes": [f.codigo for f in fuentes],
        "base": base,
        "series": series,
    }
