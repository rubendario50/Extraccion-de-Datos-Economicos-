"""Tabla maestra de países y sus códigos en cada organismo."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Pais(Base):
    __tablename__ = "pais"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(3), unique=True)  # interno: 001, 002, ...
    nombre: Mapped[str] = mapped_column(String(150))
    nombre_en: Mapped[str] = mapped_column(String(150))
    iso2: Mapped[str | None] = mapped_column(String(2))
    iso3: Mapped[str | None] = mapped_column(String(3))
    es_agregado: Mapped[bool] = mapped_column(default=False)

    codigos_externos: Mapped[list["PaisCodigoExterno"]] = relationship(back_populates="pais")


class PaisCodigoExterno(Base):
    """Código del país en un organismo: ISO3, FMI_DM, FMI_WEO, BM."""

    __tablename__ = "pais_codigo_externo"
    __table_args__ = (UniqueConstraint("organismo", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pais_id: Mapped[int] = mapped_column(ForeignKey("pais.id", ondelete="CASCADE"), index=True)
    organismo: Mapped[str] = mapped_column(String(20))
    codigo: Mapped[str] = mapped_column(String(30))

    pais: Mapped[Pais] = relationship(back_populates="codigos_externos")
