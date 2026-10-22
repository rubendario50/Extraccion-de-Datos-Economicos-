"""Grupos de países (Mercosur, G7, BRICS, ...) para calcular agregados propios.

No son las regiones que publica cada fuente (esas están en `pais` con `es_agregado`): el valor de un grupo
se calcula a partir de los datos de sus miembros (`app/analisis/agrupamientos.py`).
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.paises import Pais


class GrupoPais(Base):
    """Pertenencia de un país a un grupo. La composición es la actual y vale para todos los años."""

    __tablename__ = "grupo_pais"

    grupo_id: Mapped[int] = mapped_column(ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True)
    pais_id: Mapped[int] = mapped_column(ForeignKey("pais.id", ondelete="CASCADE"), primary_key=True, index=True)


class Grupo(Base):
    __tablename__ = "grupo"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)  # interno: MERCOSUR, G7, BRICS, ...
    nombre: Mapped[str] = mapped_column(String(150))
    # Qué países entran y desde cuándo (por ejemplo, quién se incorporó y quién quedó afuera).
    descripcion: Mapped[str | None] = mapped_column(Text)

    paises: Mapped[list[Pais]] = relationship(secondary="grupo_pais", order_by=Pais.nombre)
