"""Usuarios, códigos de recuperación del doble factor y sesiones."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
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
    totp_secret_cifrado: Mapped[str | None] = mapped_column(String(255))  # Fernet
    totp_activo: Mapped[bool] = mapped_column(default=False)
    totp_ultimo_paso: Mapped[int | None] = mapped_column(BigInteger)  # evita reusar un código
    rol: Mapped[str] = mapped_column(String(20), default="usuario")  # admin / usuario
    intentos_fallidos: Mapped[int] = mapped_column(default=0)  # contraseña
    # Códigos del segundo factor (TOTP o recuperación). Va aparte para que acertar la
    # contraseña no lo reinicie: solo vuelve a 0 al completar el doble factor.
    intentos_2fa: Mapped[int] = mapped_column(default=0, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    ultimo_ingreso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    codigos_recuperacion: Mapped[list["CodigoRecuperacion"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class CodigoRecuperacion(Base):
    """Código de un solo uso para entrar sin la app de autenticación. Solo se guarda su hash."""

    __tablename__ = "codigo_recuperacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    hash: Mapped[str] = mapped_column(String(64))  # SHA-256 en hexadecimal
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(back_populates="codigos_recuperacion")


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
