"""Fuentes de datos, indicadores internos y su código en cada fuente."""

from sqlalchemy import Double, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Fuente(Base):
    __tablename__ = "fuente"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)  # FMI_DM, BM, FRED
    nombre: Mapped[str] = mapped_column(String(150))
    url: Mapped[str | None] = mapped_column(String(300))


class Indicador(Base):
    __tablename__ = "indicador"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True)  # PBI_USD_CORR, ...
    nombre: Mapped[str] = mapped_column(String(200))
    unidad: Mapped[str] = mapped_column(String(100))
    escala: Mapped[str | None] = mapped_column(String(50))
    alcance: Mapped[str] = mapped_column(String(20))  # internacional / nacional
    frecuencia: Mapped[str] = mapped_column(String(20))  # anual / mensual / diaria
    descripcion: Mapped[str | None] = mapped_column(Text)

    series_externas: Mapped[list["IndicadorSerieExterna"]] = relationship(back_populates="indicador")


class IndicadorSerieExterna(Base):
    """Código con el que una fuente publica un indicador (por ejemplo NGDPD en el FMI)."""

    __tablename__ = "indicador_serie_externa"
    __table_args__ = (UniqueConstraint("fuente_id", "codigo_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    indicador_id: Mapped[int] = mapped_column(ForeignKey("indicador.id", ondelete="CASCADE"), index=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"))
    codigo_externo: Mapped[str] = mapped_column(String(50))
    # Multiplicador que lleva el valor de la fuente a la unidad y escala del indicador interno
    # (por ejemplo 1e-9 para pasar dólares del Banco Mundial a miles de millones). Vacío = 1.
    factor: Mapped[float | None] = mapped_column(Double)
    # Solo FMI: año de la edición del WEO con la que se cargaron los datos ("October 2026" -> 2026).
    # Desde ese año los valores son proyecciones (ver docs/arquitectura.md). Vacío = desconocido.
    proyeccion_desde: Mapped[int | None] = mapped_column(Integer)

    indicador: Mapped[Indicador] = relationship(back_populates="series_externas")
    fuente: Mapped[Fuente] = relationship()
