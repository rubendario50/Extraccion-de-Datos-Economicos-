"""Modelos SQLAlchemy. Importar desde acá para que Alembic vea todas las tablas."""

from app.models.datos import (
    CotizacionDiaria,
    DatoInternacionalAnual,
    DatoInternacionalMensual,
    DatoNacionalAnual,
    DatoNacionalMensual,
)
from app.models.indicadores import Fuente, Indicador, IndicadorSerieExterna
from app.models.paises import Pais, PaisCodigoExterno
from app.models.usuarios import CodigoEmail, Sesion, Usuario

__all__ = [
    "CodigoEmail",
    "CotizacionDiaria",
    "DatoInternacionalAnual",
    "DatoInternacionalMensual",
    "DatoNacionalAnual",
    "DatoNacionalMensual",
    "Fuente",
    "Indicador",
    "IndicadorSerieExterna",
    "Pais",
    "PaisCodigoExterno",
    "Sesion",
    "Usuario",
]
