"""Endpoint JSON de series: GET /api/series."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analisis.indices import ErrorIndice, a_base_100
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import DatoInternacionalAnual, Fuente, Indicador, Pais, PaisCodigoExterno

# Toda la API exige sesión con el doble factor completo.
router = APIRouter(prefix="/api", dependencies=[Depends(usuario_actual)])

# Máximo de países por pedido; es lo mismo que permite elegir el panel.
MAX_PAISES = 8


@router.get("/series")
def obtener_series(
    indicador: str = Query(description="Código interno del indicador, por ejemplo PBI_USD_CORR"),
    paises: str = Query(description="Códigos ISO3 o del FMI DataMapper separados por coma: URY,ARG,WEOWORLD"),
    desde: int | None = Query(None, description="Primer año (inclusive)"),
    hasta: int | None = Query(None, description="Último año (inclusive)"),
    base: int | None = Query(None, description="Año base: si se indica, las series se expresan en índice base 100"),
    fuente: str = Query("FMI_DM", description="Código de la fuente"),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.scalar(select(Indicador).where(Indicador.codigo == indicador))
    if ind is None:
        raise HTTPException(404, f"Indicador desconocido: {indicador}")
    if (ind.alcance, ind.frecuencia) != ("internacional", "anual"):
        raise HTTPException(400, f"Por ahora solo hay series internacionales anuales ({indicador} es {ind.alcance} {ind.frecuencia}).")
    fte = db.scalar(select(Fuente).where(Fuente.codigo == fuente))
    if fte is None:
        raise HTTPException(404, f"Fuente desconocida: {fuente}")
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
        if base is not None:
            try:
                valores = a_base_100(valores, base)
            except ErrorIndice as e:
                raise HTTPException(422, f"{pais.nombre}: {e}") from e
        datos = [
            {"anio": anio, "valor": valor}
            for anio, valor in valores.items()
            if (desde is None or anio >= desde) and (hasta is None or anio <= hasta)
        ]
        series.append({"pais": codigo, "codigo": pais.codigo, "nombre": pais.nombre, "datos": datos})

    return {
        "indicador": {
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": "Índice (base 100)" if base is not None else ind.unidad,
            "escala": None if base is not None else ind.escala,
        },
        "fuente": fte.codigo,
        "base": base,
        "series": series,
    }
