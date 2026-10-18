"""Tablas de valores, separadas por alcance (internacional / nacional) y frecuencia.

Todas guardan la fuente de cada valor: FMI y Banco Mundial pueden dar cifras distintas.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class _ConActualizacion:
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)


class DatoInternacionalAnual(_ConActualizacion, Base):
    __tablename__ = "dato_internacional_anual"

    pais_id: Mapped[int] = mapped_column(ForeignKey("pais.id"), primary_key=True)
    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id"), primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"), primary_key=True)
    anio: Mapped[int] = mapped_column(primary_key=True)
    valor: Mapped[float | None] = mapped_column(Double)


class DatoInternacionalMensual(_ConActualizacion, Base):
    __tablename__ = "dato_internacional_mensual"

    pais_id: Mapped[int] = mapped_column(ForeignKey("pais.id"), primary_key=True)
    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id"), primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"), primary_key=True)
    periodo: Mapped[date] = mapped_column(Date, primary_key=True)  # primer día del mes
    valor: Mapped[float | None] = mapped_column(Double)


class DatoNacionalAnual(_ConActualizacion, Base):
    """Datos de Uruguay."""

    __tablename__ = "dato_nacional_anual"

    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id"), primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"), primary_key=True)
    anio: Mapped[int] = mapped_column(primary_key=True)
    valor: Mapped[float | None] = mapped_column(Double)


class DatoNacionalMensual(_ConActualizacion, Base):
    """Datos de Uruguay."""

    __tablename__ = "dato_nacional_mensual"

    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id"), primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"), primary_key=True)
    periodo: Mapped[date] = mapped_column(Date, primary_key=True)  # primer día del mes
    valor: Mapped[float | None] = mapped_column(Double)


class CotizacionDiaria(_ConActualizacion, Base):
    """Cierre del día de cotizaciones de bolsa y materias primas (decisión del cliente)."""

    __tablename__ = "cotizacion_diaria"

    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id"), primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"), primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    cierre: Mapped[float | None] = mapped_column(Double)
