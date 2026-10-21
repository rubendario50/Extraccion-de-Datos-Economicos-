"""Usuarios, códigos de ingreso por email (doble factor) y sesiones."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.datos import ahora


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # siempre en minúsculas
    nombre: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None si solo entra con Google
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    rol: Mapped[str] = mapped_column(String(20), default="usuario")  # admin / usuario
    intentos_fallidos: Mapped[int] = mapped_column(default=0)  # contraseña
    # Códigos del segundo factor (por email). Va aparte para que acertar la
    # contraseña no lo reinicie: solo vuelve a 0 al completar el doble factor.
    intentos_2fa: Mapped[int] = mapped_column(default=0, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    ultimo_ingreso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodigoEmail(Base):
    """Código de 6 dígitos mandado por email para el segundo factor. Solo se guarda su hash.

    Solo vale el último de cada usuario, mientras no venza ni se use. Las filas viejas se conservan un
    tiempo para contar los envíos de la última hora.
    """

    __tablename__ = "codigo_email"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256 en hexadecimal
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Cuando se usó o se anuló (al pedir otro, o si no se pudo mandar).
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Sesion(Base):
    """Sesión iniciada. La cookie lleva el token; acá solo se guarda su hash."""

    __tablename__ = "sesion"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 en hexadecimal
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    mfa_ok: Mapped[bool] = mapped_column(default=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    usuario: Mapped[Usuario] = relationship()
