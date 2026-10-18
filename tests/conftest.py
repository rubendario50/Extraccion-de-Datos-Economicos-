import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

# Antes de importar la app: la configuración se lee una sola vez.
os.environ.setdefault("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "clave-solo-para-los-tests")
os.environ.setdefault("COOKIE_SECURE", "false")

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db import Base, get_db
from app.etl.semillas import cargar_semillas
from app.main import app as aplicacion
from tests.ayudas import entrar_directo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sesion():
    """Base SQLite en memoria, nueva para cada test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Sesion() as s:
        yield s
    engine.dispose()


@pytest.fixture
def sesion_con_semillas(sesion):
    cargar_semillas(sesion)
    return sesion


def transporte_fmi(llamadas: list | None = None) -> httpx.MockTransport:
    """Simula la API del FMI respondiendo con los JSON de tests/fixtures/fmi_<CODIGO>.json."""

    def responder(pedido: httpx.Request) -> httpx.Response:
        if llamadas is not None:
            llamadas.append(pedido.url.path)
        codigo = pedido.url.path.rsplit("/", 1)[-1]
        archivo = FIXTURES / f"fmi_{codigo}.json"
        if not archivo.exists():
            return httpx.Response(404, json={"error": "no existe"})
        return httpx.Response(200, json=json.loads(archivo.read_text(encoding="utf-8")))

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_fmi():
    with httpx.Client(transport=transporte_fmi(), base_url="https://fmi.test/api/v1") as c:
        yield c


def transporte_bm(llamadas: list | None = None, filas: dict[str, list] | None = None) -> httpx.MockTransport:
    """Simula la API del Banco Mundial con tests/fixtures/bm_<CODIGO>.json (o con `filas`, si se pasa).

    Respeta `per_page` y `page` como la API real: [metadatos, filas de la página].
    """

    def responder(pedido: httpx.Request) -> httpx.Response:
        if llamadas is not None:
            llamadas.append(f"{pedido.url.path}?{pedido.url.query.decode()}")
        ruta = pedido.url.path
        if ruta.endswith("/country"):
            nombre = "paises"
        elif "/indicator/" in ruta:
            nombre = ruta.rsplit("/", 1)[-1]
        else:
            return httpx.Response(404)
        if filas is not None and nombre in filas:
            todas = filas[nombre]
        else:
            archivo = FIXTURES / f"bm_{nombre}.json"
            if not archivo.exists():
                # Así responde el BM a un indicador inexistente: HTTP 200 con un mensaje de error.
                return httpx.Response(200, json=[{"message": [{"id": "120", "key": "Invalid value", "value": "The provided parameter value is not valid"}]}])
            todas = json.loads(archivo.read_text(encoding="utf-8"))
        por_pagina = int(pedido.url.params.get("per_page", 50))
        pagina = int(pedido.url.params.get("page", 1))
        paginas = max(1, -(-len(todas) // por_pagina))
        meta = {"page": pagina, "pages": paginas, "per_page": por_pagina, "total": len(todas)}
        return httpx.Response(200, json=[meta, todas[(pagina - 1) * por_pagina : pagina * por_pagina] or None])

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_bm():
    with httpx.Client(transport=transporte_bm(), base_url="https://bm.test/v2") as c:
        yield c


@pytest.fixture
def cliente_web(sesion_con_semillas):
    """Cliente sin sesión. No sigue redirecciones, para poder revisarlas."""
    aplicacion.dependency_overrides[get_db] = lambda: sesion_con_semillas
    with TestClient(aplicacion, follow_redirects=False) as c:
        yield c
    aplicacion.dependency_overrides.clear()


@pytest.fixture
def cliente_api(cliente_web, sesion_con_semillas):
    """Cliente con una sesión completa (contraseña y doble factor)."""
    entrar_directo(cliente_web, sesion_con_semillas)
    return cliente_web
