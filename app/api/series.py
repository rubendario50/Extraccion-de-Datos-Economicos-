"""Endpoint JSON de series: GET /api/series."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analisis.agrupamientos import DESCRIPCIONES, INDICADOR_PESO, PROMEDIO_PONDERADO_PBI, REGLAS, agregar
from app.analisis.indices import ErrorIndice, a_base_100, a_base_100_promedio
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import (
    CotizacionDiaria,
    DatoInternacionalAnual,
    DatoNacionalAnual,
    DatoNacionalMensual,
    Fuente,
    Grupo,
    Indicador,
    IndicadorSerieExterna,
    Pais,
    PaisCodigoExterno,
)

# Toda la API exige sesión con el doble factor completo.
router = APIRouter(prefix="/api", dependencies=[Depends(usuario_actual)])

# Máximo de series (países más grupos) por pedido; es lo mismo que permite elegir el panel.
MAX_PAISES = 8

# (alcance, frecuencia) -> (tabla, columna del período, columna del valor). Las series anuales usan
# el año; las mensuales y diarias, una fecha (primer día del mes en las mensuales).
TABLAS = {
    ("internacional", "anual"): (DatoInternacionalAnual, "anio", "valor"),
    ("nacional", "anual"): (DatoNacionalAnual, "anio", "valor"),
    ("nacional", "mensual"): (DatoNacionalMensual, "periodo", "valor"),
    ("nacional", "diaria"): (CotizacionDiaria, "fecha", "cierre"),
    ("mercados", "diaria"): (CotizacionDiaria, "fecha", "cierre"),
}
# Las series nacionales son de Uruguay: una sola serie, con este código de país.
PAIS_NACIONAL = "URY"
# Alcances con una sola serie (no se eligen países ni grupos): Uruguay y los mercados (bolsa y materias
# primas, cotizaciones de FRED).
SERIE_UNICA = {"nacional", "mercados"}
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
        "En los indicadores internacionales hace falta al menos un país o un grupo; los nacionales son siempre de "
        "Uruguay y los de mercados (bolsa y materias primas) no van por país",
    ),
    grupos: str | None = Query(
        None,
        description="Códigos de grupos de países separados por coma: MERCOSUR,G7. Cada grupo vuelve como una "
        "serie agregada de sus miembros (suma o promedio ponderado por el PBI, según el indicador)",
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

    if ind.alcance in SERIE_UNICA:
        if (grupos or "").strip():
            tipo = "un indicador de Uruguay" if ind.alcance == "nacional" else "una cotización de mercado"
            raise HTTPException(400, f"{ind.codigo} es {tipo}: no se puede pedir por grupos.")
        serie = serie_nacional(db, ind, fte, paises, desde, hasta, base)
        return respuesta(ind, fte, fuentes, base, [serie], None)
    proyeccion = primer_anio_proyectado(db, ind.id, fte)

    escritos = codigos_pedidos(paises)
    pedidos = list(escritos)
    escritos_grupos = codigos_pedidos(grupos)
    pedidos_grupos = list(escritos_grupos)
    if not pedidos and not pedidos_grupos:
        raise HTTPException(422, "Indicá al menos un país o un grupo.")
    total = len(pedidos) + len(pedidos_grupos)
    if total > MAX_PAISES:
        raise HTTPException(400, f"Se pueden pedir hasta {MAX_PAISES} países y grupos a la vez (pediste {total}).")
    # Algunos códigos del FMI tienen minúsculas (FAD_EuroArea): se compara en mayúsculas y se
    # responde con el código tal como está guardado (el del FMI DataMapper si hay dos).
    por_codigo: dict[str, tuple[str, Pais]] = {}
    if pedidos:
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

    lista_grupos: list[Grupo] = []
    if pedidos_grupos:
        if ind.codigo not in REGLAS:
            raise HTTPException(400, f"Todavía no está definido cómo agregar {ind.codigo} por grupos.")
        por_grupo = {
            g.codigo.upper(): g
            for g in db.scalars(select(Grupo).where(func.upper(Grupo.codigo).in_(pedidos_grupos))).all()
        }
        faltan = [escritos_grupos[c] for c in pedidos_grupos if c not in por_grupo]
        if faltan:
            raise HTTPException(404, f"Grupos desconocidos: {', '.join(faltan)}")
        lista_grupos = [por_grupo[c] for c in pedidos_grupos]

    en_rango = lambda anio: (desde is None or anio >= desde) and (hasta is None or anio <= hasta)  # noqa: E731

    def datos_de(valores: dict[int, float | None], nombre: str, por_que=lambda anio: "") -> list[dict]:
        """Pasa a base 100 (si se pidió), recorta al rango y marca las proyecciones.

        `por_que(año)`: aclaración para el error de año base sin dato (en los grupos, quién falta).
        """
        # Una serie sin ningún dato en el rango (o en la fuente) vuelve vacía y no participa del índice:
        # el panel la muestra como "sin datos". El 422 queda para la que tiene datos pero no el año base.
        if base is not None and any(v is not None for a, v in valores.items() if en_rango(a)):
            try:
                valores = a_base_100(valores, base)
            except ErrorIndice as e:
                raise HTTPException(422, f"{nombre}: {e}{por_que(base)}") from e
        datos = [{"anio": anio, "valor": valor} for anio, valor in valores.items() if en_rango(anio)]
        if proyeccion is not None:  # solo las fuentes que proyectan llevan la marca
            for d in datos:
                d["proyeccion"] = d["anio"] >= proyeccion
        return datos

    series = []
    for codigo, pais in encontrados:
        valores = valores_por_pais(db, ind.id, fte.id, [pais.id]).get(pais.id, {})
        series.append({
            "pais": codigo, "codigo": pais.codigo, "nombre": pais.nombre, "fuente": fte.codigo,
            "datos": datos_de(valores, pais.nombre),
        })
    for grupo in lista_grupos:
        series.append(serie_de_grupo(db, ind, fte, grupo, datos_de))

    return respuesta(ind, fte, fuentes, base, series, proyeccion)


def codigos_pedidos(texto: str | None) -> dict[str, str]:
    """Códigos separados por coma, sin distinguir mayúsculas (ury = URY) y sin repetidos, en orden.

    Devuelve {código en mayúsculas: como lo escribió quien pidió}.
    """
    escritos: dict[str, str] = {}
    for c in (texto or "").split(","):
        if c.strip():
            escritos.setdefault(c.strip().upper(), c.strip())
    return escritos


def valores_por_pais(
    db: Session, indicador_id: int, fuente_id: int, pais_ids: list[int]
) -> dict[int, dict[int, float | None]]:
    """{pais_id: {año: valor}} de un indicador internacional anual en una fuente, en orden de año."""
    salida: dict[int, dict[int, float | None]] = {}
    for pais_id, anio, valor in db.execute(
        select(DatoInternacionalAnual.pais_id, DatoInternacionalAnual.anio, DatoInternacionalAnual.valor)
        .where(
            DatoInternacionalAnual.pais_id.in_(pais_ids),
            DatoInternacionalAnual.indicador_id == indicador_id,
            DatoInternacionalAnual.fuente_id == fuente_id,
        )
        .order_by(DatoInternacionalAnual.anio)
    ).all():
        salida.setdefault(pais_id, {})[anio] = valor
    return salida


def codigos_de_api(db: Session, pais_ids: list[int]) -> dict[int, str]:
    """Código con el que la API nombra a cada país: el del FMI DataMapper (o el ISO3 si no tiene)."""
    salida: dict[int, str] = {}
    for pais_id, codigo in db.execute(
        select(PaisCodigoExterno.pais_id, PaisCodigoExterno.codigo)
        .where(PaisCodigoExterno.pais_id.in_(pais_ids), PaisCodigoExterno.organismo.in_(["FMI_DM", "ISO3"]))
        .order_by(PaisCodigoExterno.organismo)  # FMI_DM antes que ISO3
    ).all():
        salida.setdefault(pais_id, codigo)
    return salida


def serie_de_grupo(db: Session, ind: Indicador, fte: Fuente, grupo: Grupo, datos_de) -> dict:
    """Serie agregada de un grupo con los datos de sus miembros en la fuente elegida.

    La regla (suma o promedio ponderado por el PBI, y qué años tienen valor) está en
    app/analisis/agrupamientos.py. `agregado` dice cómo se calculó y qué miembros entraron; los años sin
    valor llevan `faltan` (los miembros sin dato ese año) o `faltan_pbi` (los que no tienen el PBI para
    ponderar, en los promedios).
    """
    metodo = REGLAS[ind.codigo]
    ids = [p.id for p in grupo.paises]
    pesos = None
    if metodo == PROMEDIO_PONDERADO_PBI:
        # El PBI de la misma fuente: nunca se mezclan fuentes, tampoco en los pesos.
        id_peso = db.scalar(select(Indicador.id).where(Indicador.codigo == INDICADOR_PESO))
        pesos = valores_por_pais(db, id_peso, fte.id, ids) if id_peso is not None else {}
    leidos = valores_por_pais(db, ind.id, fte.id, ids)
    resultado = agregar(metodo, {i: leidos.get(i, {}) for i in ids}, pesos)

    codigos = codigos_de_api(db, ids)
    nombres = {p.id: p.nombre for p in grupo.paises}

    def describir(lista: list[int]) -> list[dict]:
        return [{"pais": codigos.get(i), "nombre": nombres[i]} for i in lista]

    def por_que(anio: int) -> str:
        texto = ""
        if anio in resultado.faltan:
            texto += f" Falta el dato de {', '.join(nombres[i] for i in resultado.faltan[anio])}."
        if anio in resultado.faltan_pbi:
            texto += f" Falta el PBI de {', '.join(nombres[i] for i in resultado.faltan_pbi[anio])}."
        return texto

    datos = datos_de(resultado.valores, grupo.nombre, por_que)
    for d in datos:
        for clave, faltantes in (("faltan", resultado.faltan), ("faltan_pbi", resultado.faltan_pbi)):
            if d["anio"] in faltantes:
                d[clave] = [codigos.get(i) for i in faltantes[d["anio"]]]
    return {
        "pais": None,
        "grupo": grupo.codigo,
        "codigo": grupo.codigo,
        "nombre": grupo.nombre,
        "fuente": fte.codigo,
        "agregado": {
            "metodo": metodo,
            "descripcion": DESCRIPCIONES[metodo],
            "miembros": describir(resultado.miembros),
            "fuera": describir(resultado.fuera),
        },
        "datos": datos,
    }


def serie_nacional(
    db: Session, ind: Indicador, fte: Fuente, paises: str | None, desde: int | None, hasta: int | None, base: int | None
) -> dict:
    """La única serie de un indicador nacional (Uruguay) o de mercado (FRED). `desde`, `hasta` y `base` son años.

    En las series mensuales y diarias cada dato lleva la fecha ISO ("2024-03-01") en lugar del año, y
    el índice base 100 toma como 100 el promedio del año base. Las de mercado no son de un país: van con
    `"pais": null` y el nombre del indicador.
    """
    mercado = ind.alcance == "mercados"
    escritos = sorted({c.strip() for c in (paises or "").split(",") if c.strip()})
    otros = escritos if mercado else [c for c in escritos if c.upper() != PAIS_NACIONAL]
    if otros and mercado:
        raise HTTPException(400, f"{ind.codigo} es una cotización de mercado: no va por países ({', '.join(otros)}).")
    if otros:
        raise HTTPException(400, f"{ind.codigo} es un indicador de Uruguay: no hay series de {', '.join(otros)}.")
    uruguay = None if mercado else db.scalar(select(Pais).where(Pais.iso3 == PAIS_NACIONAL))
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
    nombre = ind.nombre if mercado else uruguay.nombre if uruguay else "Uruguay"
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
        "pais": None if mercado else PAIS_NACIONAL,
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
