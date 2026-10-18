"""Panel principal: elegir indicador, países y años, y ver la gráfica con la tabla."""

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.series import fuente_por_defecto, fuentes_del_indicador
from app.auth.dependencias import usuario_actual
from app.db import get_db
from app.models import DatoInternacionalAnual, Indicador, Pais, PaisCodigoExterno, Usuario
from app.web.plantillas import renderizar

router = APIRouter()

# Nombre de cada fuente tal como se cita debajo de la gráfica (si no está, se usa el de la tabla fuente).
NOMBRES_FUENTE = {
    "FMI_DM": "FMI, World Economic Outlook (DataMapper)",
    "BM": "Banco Mundial, World Development Indicators",
}
PAISES_POR_DEFECTO = ["URY", "ARG", "WEOWORLD"]


def datos_del_panel(db: Session) -> dict:
    """Indicadores con sus fuentes, países con datos y años disponibles por fuente, para armar los controles."""
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
        fuentes = fuentes_del_indicador(db, ind.id)
        por_defecto = fuente_por_defecto(db, ind.id, fuentes)
        lista_fuentes = []
        for fte in fuentes:
            filtro = [
                DatoInternacionalAnual.indicador_id == ind.id,
                DatoInternacionalAnual.fuente_id == fte.id,
                DatoInternacionalAnual.valor.is_not(None),
            ]
            con_datos = db.scalars(select(DatoInternacionalAnual.pais_id).where(*filtro).distinct()).all()
            desde, hasta = db.execute(
                select(func.min(DatoInternacionalAnual.anio), func.max(DatoInternacionalAnual.anio)).where(*filtro)
            ).one()
            lista_fuentes.append({
                "codigo": fte.codigo,
                "nombre": NOMBRES_FUENTE.get(fte.codigo, fte.nombre),
                "desde": desde,
                "hasta": hasta,
                "paises": sorted(codigos[i] for i in con_datos if i in paises),
            })
        elegida = next((f for f in lista_fuentes if por_defecto and f["codigo"] == por_defecto.codigo), None)
        salida.append({
            "codigo": ind.codigo,
            "nombre": ind.nombre,
            "unidad": ind.unidad,
            "escala": ind.escala,
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
