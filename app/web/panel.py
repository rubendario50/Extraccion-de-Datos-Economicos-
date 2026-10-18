"""Panel principal: elegir indicador, países y años, y ver la gráfica con la tabla."""

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import DatoInternacionalAnual, Fuente, Indicador, Pais, PaisCodigoExterno, Usuario
from app.web.plantillas import renderizar

router = APIRouter()

FUENTE = "FMI_DM"
NOMBRE_FUENTE = "FMI, World Economic Outlook (DataMapper)"
PAISES_POR_DEFECTO = ["URY", "ARG", "WEOWORLD"]


def datos_del_panel(db: Session) -> dict:
    """Indicadores, países con datos y años disponibles, para armar los controles."""
    fuente = db.scalar(select(Fuente).where(Fuente.codigo == FUENTE))
    indicadores = db.scalars(
        select(Indicador)
        .where(Indicador.alcance == "internacional", Indicador.frecuencia == "anual")
        .order_by(Indicador.id)
    ).all()
    codigos = {
        pais_id: codigo
        for pais_id, codigo in db.execute(
            select(PaisCodigoExterno.pais_id, PaisCodigoExterno.codigo).where(PaisCodigoExterno.organismo == "FMI_DM")
        ).all()
    }
    paises = {p.id: p for p in db.scalars(select(Pais)).all() if p.id in codigos}

    salida = []
    for ind in indicadores:
        filtro = [DatoInternacionalAnual.indicador_id == ind.id, DatoInternacionalAnual.valor.is_not(None)]
        if fuente is not None:
            filtro.append(DatoInternacionalAnual.fuente_id == fuente.id)
        con_datos = db.scalars(select(DatoInternacionalAnual.pais_id).where(*filtro).distinct()).all()
        desde, hasta = db.execute(
            select(func.min(DatoInternacionalAnual.anio), func.max(DatoInternacionalAnual.anio)).where(*filtro)
        ).one()
        salida.append({
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": ind.unidad,
            "escala": ind.escala,
            "desde": desde,
            "hasta": hasta,
            "paises": sorted(codigos[i] for i in con_datos if i in paises),
        })
    lista_paises = sorted(
        ({"codigo": codigos[p.id], "nombre": p.nombre, "agregado": p.es_agregado} for p in paises.values()),
        key=lambda p: p["nombre"],
    )
    return {
        "indicadores": salida,
        "paises": lista_paises,
        "por_defecto": PAISES_POR_DEFECTO,
        "fuente": NOMBRE_FUENTE,
    }


@router.get("/")
def panel(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    datos = datos_del_panel(db)
    # El JSON va en un <script type="application/json">: se escapan "<" para que no pueda cerrar la etiqueta.
    datos_json = json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")
    return renderizar(request, "panel.html", {"usuario": usuario, "datos": datos, "datos_json": datos_json})
