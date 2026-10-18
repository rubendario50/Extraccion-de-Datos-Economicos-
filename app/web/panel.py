"""Panel principal: elegir indicador, países y años, y ver la gráfica con la tabla.

Los indicadores nacionales (Uruguay) tienen una sola serie y no usan el selector de países.
"""

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.series import PAIS_NACIONAL, fuente_por_defecto, fuentes_del_indicador, tabla_de
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import DatoInternacionalAnual, Indicador, Pais, PaisCodigoExterno, Usuario
from app.web.plantillas import renderizar

router = APIRouter()

# Nombre de cada fuente tal como se cita debajo de la gráfica (si no está, se usa el de la tabla fuente).
NOMBRES_FUENTE = {
    "FMI_DM": "FMI, World Economic Outlook (DataMapper)",
    "BM": "Banco Mundial, World Development Indicators",
    "INE": "Instituto Nacional de Estadística (INE)",
    "BCU": "Banco Central del Uruguay (BCU), cotizaciones interbancarias",
}
# Nombre corto para el selector de fuente (el completo no entra en el control).
NOMBRES_CORTOS_FUENTE = {"FMI_DM": "FMI", "BM": "Banco Mundial", "INE": "INE", "BCU": "BCU"}
PAISES_POR_DEFECTO = ["URY", "ARG", "WEOWORLD"]


def datos_del_panel(db: Session) -> dict:
    """Indicadores con sus fuentes, países con datos y años disponibles por fuente, para armar los controles."""
    # Primero los internacionales, después los de Uruguay; solo los que tienen tabla de datos.
    indicadores = sorted(
        (i for i in db.scalars(select(Indicador)).all() if tabla_de(i) is not None),
        key=lambda i: (i.alcance != "internacional", i.id),
    )
    codigos = {
        pais_id: codigo
        for pais_id, codigo in db.execute(
            select(PaisCodigoExterno.pais_id, PaisCodigoExterno.codigo).where(PaisCodigoExterno.organismo == "FMI_DM")
        ).all()
    }
    paises = {p.id: p for p in db.scalars(select(Pais)).all() if p.id in codigos}

    salida = []
    for ind in indicadores:
        fuentes = fuentes_del_indicador(db, ind.id)
        por_defecto = fuente_por_defecto(db, ind, fuentes)
        col_periodo, col_valor, col_indicador, col_fuente = tabla_de(ind)
        lista_fuentes = []
        for fte in fuentes:
            filtro = [col_indicador == ind.id, col_fuente == fte.id, col_valor.is_not(None)]
            desde, hasta = db.execute(select(func.min(col_periodo), func.max(col_periodo)).where(*filtro)).one()
            if ind.alcance == "nacional":
                # Una sola serie (Uruguay); los años del selector salen de las fechas.
                con_datos = [PAIS_NACIONAL] if desde is not None else []
                if ind.frecuencia != "anual" and desde is not None:
                    desde, hasta = desde.year, hasta.year
            else:
                ids = db.scalars(select(DatoInternacionalAnual.pais_id).where(*filtro).distinct()).all()
                con_datos = sorted(codigos[i] for i in ids if i in paises)
            lista_fuentes.append({
                "codigo": fte.codigo,
                "nombre": NOMBRES_FUENTE.get(fte.codigo, fte.nombre),
                "corto": NOMBRES_CORTOS_FUENTE.get(fte.codigo, fte.codigo),
                "desde": desde,
                "hasta": hasta,
                "paises": con_datos,
            })
        elegida = next((f for f in lista_fuentes if por_defecto and f["codigo"] == por_defecto.codigo), None)
        salida.append({
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": ind.unidad,
            "escala": ind.escala,
            "alcance": ind.alcance,
            "frecuencia": ind.frecuencia,
            "fuentes": lista_fuentes,
            "fuente": elegida["codigo"] if elegida else None,
            # Años y países de la fuente por defecto.
            "desde": elegida["desde"] if elegida else None,
            "hasta": elegida["hasta"] if elegida else None,
            "paises": elegida["paises"] if elegida else [],
        })
    lista_paises = sorted(
        ({"codigo": codigos[p.id], "nombre": p.nombre, "agregado": p.es_agregado} for p in paises.values()),
        key=lambda p: p["nombre"],
    )
    primera = next((f for f in salida[0]["fuentes"] if f["codigo"] == salida[0]["fuente"]), None) if salida else None
    return {
        "indicadores": salida,
        "paises": lista_paises,
        "por_defecto": PAISES_POR_DEFECTO,
        # Fuente que se muestra antes de que cargue el JavaScript (la del primer indicador).
        "fuente": primera["nombre"] if primera else NOMBRES_FUENTE["FMI_DM"],
    }


@router.get("/")
def panel(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    datos = datos_del_panel(db)
    # El JSON va en un <script type="application/json">: se escapan "<" para que no pueda cerrar la etiqueta.
    datos_json = json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")
    return renderizar(request, "panel.html", {"usuario": usuario, "datos": datos, "datos_json": datos_json})
