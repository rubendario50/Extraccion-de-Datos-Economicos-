import json
import os
from pathlib import Path

# Antes de importar la app: la configuración se lee una sola vez.
# Los tests no leen el .env de la PC (BASE_URL, Google, Gmail, FRED...): usan solo estos valores y los
# predeterminados de Settings. En producción nada cambia: esto solo corre con pytest.
from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None
os.environ.update({
    "SECRET_KEY": "clave-solo-para-los-tests",
    "COOKIE_SECURE": "false",
    "BASE_URL": "http://localhost:8000",
    "ADMIN_EMAIL": "",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "",
    # Aunque la PC tenga Gmail configurado, los tests nunca mandan correo de verdad.
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_FROM": "",
    # Ni la clave real de FRED: los tests que la necesitan pasan una de prueba.
    "FRED_API_KEY": "",
})

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
from tests.ayudas import Buzon, entrar_directo

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

    Respeta `per_page`, `page` y `source` como la API real: [metadatos, filas de la página].
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
        if nombre != "paises":
            # Como la API real: con source=2 responde la base WDI; sin él, a veces otra (sourceid null).
            meta["sourceid"] = pedido.url.params.get("source")
        return httpx.Response(200, json=[meta, todas[(pagina - 1) * por_pagina : pagina * por_pagina] or None])

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_bm():
    with httpx.Client(transport=transporte_bm(), base_url="https://bm.test/v2") as c:
        yield c


@pytest.fixture(autouse=True)
def buzon(monkeypatch):
    """Reemplaza el envío de correo: los códigos quedan en la lista `buzon.enviados`."""
    falso = Buzon()
    monkeypatch.setattr("app.auth.correo.enviar_codigo", falso.enviar_codigo)
    return falso


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


# Planilla del INE (último tramo de la ruta) -> archivo real recortado en tests/fixtures.
PLANILLAS_INE = {
    "IPC gral y variaciones_base 2022.xlsx": "ine_ipc_general.xlsx",
    "ECH0013.xlsx": "ine_ECH0013.xlsx",
}


def transporte_ine(llamadas: list | None = None, planillas: dict[str, bytes] | None = None) -> httpx.MockTransport:
    """Simula www5.ine.gub.uy con las planillas recortadas de tests/fixtures (o con `planillas`, si se pasa)."""

    def responder(pedido: httpx.Request) -> httpx.Response:
        if llamadas is not None:
            llamadas.append(pedido.url.path)
        nombre = pedido.url.path.rsplit("/", 1)[-1]
        if planillas is not None and nombre in planillas:
            return httpx.Response(200, content=planillas[nombre])
        if nombre not in PLANILLAS_INE:
            return httpx.Response(404, text="404 - File or directory not found.")
        return httpx.Response(200, content=(FIXTURES / PLANILLAS_INE[nombre]).read_bytes())

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_ine():
    with httpx.Client(transport=transporte_ine(), base_url="https://ine.test/documents") as c:
        yield c


def transporte_bcu(llamadas: list | None = None) -> httpx.MockTransport:
    """Simula el servicio de cotizaciones del BCU con respuestas reales guardadas en tests/fixtures.

    Solo hay datos de 2225 (dólar billete) del 1 al 16 de octubre de 2026 (bcu_2225_2026-10.xml): responde
    los de ese archivo que caen en el rango pedido; sin ninguno, "No existe cotización" (código 100); y
    con más de 366 días, el error 104, como el servicio real.
    """
    import re
    import xml.etree.ElementTree as ET
    from datetime import date

    ET.register_namespace("SOAP-ENV", "http://schemas.xmlsoap.org/soap/envelope/")

    def responder(pedido: httpx.Request) -> httpx.Response:
        cuerpo = pedido.content.decode()
        desde = date.fromisoformat(re.search(r"<cot:FechaDesde>([^<]+)<", cuerpo).group(1))
        hasta = date.fromisoformat(re.search(r"<cot:FechaHasta>([^<]+)<", cuerpo).group(1))
        moneda = re.search(r"<cot:item>(\d+)<", cuerpo).group(1)
        if llamadas is not None:
            llamadas.append((moneda, desde, hasta))
        if (hasta - desde).days > 365:
            return httpx.Response(200, content=(FIXTURES / "bcu_rango_excedido.xml").read_bytes())
        raiz = ET.fromstring((FIXTURES / "bcu_2225_2026-10.xml").read_bytes())
        lista = raiz.find(".//{Cotiza}datoscotizaciones")
        for dato in list(lista):
            fecha = date.fromisoformat(dato.findtext("{Cotiza}Fecha"))
            if moneda != "2225" or not desde <= fecha <= hasta:
                lista.remove(dato)
        if not len(lista):
            return httpx.Response(200, content=(FIXTURES / "bcu_sin_cotizaciones.xml").read_bytes())
        return httpx.Response(200, content=ET.tostring(raiz, encoding="utf-8"))

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_bcu():
    with httpx.Client(transport=transporte_bcu(), base_url="https://bcu.test/servlet") as c:
        yield c


# Clave de FRED para los tests (32 letras minúsculas y números, como las reales).
CLAVE_FRED = "clavedepruebaparafred0123456789a"


def transporte_fred(llamadas: list | None = None) -> httpx.MockTransport:
    """Simula fred/series/observations con tests/fixtures/fred_<SERIE>.json (datos reales recortados).

    Como la API real: sin clave o con otra clave responde 400 con `error_message`; una serie sin fixture,
    400 "The series does not exist."; respeta `observation_start` y `observation_end`.

    También simula la descarga sin clave (fred.stlouisfed.org/graph/fredgraph.csv?id=...) con
    tests/fixtures/fred_<SERIE>.csv: una serie sin fixture da 404 con una página HTML; respeta `cosd` y
    `coed`, pero si la ventana no tiene datos devuelve la serie entera, como FRED.
    """
    from datetime import date

    def error(mensaje: str) -> httpx.Response:
        return httpx.Response(400, json={"error_code": 400, "error_message": f"Bad Request.  {mensaje}"})

    def responder_csv(params) -> httpx.Response:
        archivo = FIXTURES / f"fred_{params.get('id')}.csv"
        if not archivo.exists():
            return httpx.Response(404, text="<!DOCTYPE html><html><title>Error - St. Louis Fed</title></html>")
        encabezado, *filas = archivo.read_text(encoding="utf-8").splitlines()
        desde = date.fromisoformat(params.get("cosd", "1600-01-01"))
        hasta = date.fromisoformat(params.get("coed", "9999-12-31"))
        en_rango = [f for f in filas if desde <= date.fromisoformat(f.split(",")[0]) <= hasta]
        texto = "\n".join([encabezado, *(en_rango or filas)]) + "\n"
        return httpx.Response(200, text=texto, headers={"content-type": "application/csv"})

    def responder(pedido: httpx.Request) -> httpx.Response:
        params = pedido.url.params
        if llamadas is not None:
            llamadas.append(dict(params))
        if pedido.url.host == "fred.stlouisfed.org" and pedido.url.path == "/graph/fredgraph.csv":
            return responder_csv(params)
        if not pedido.url.path.endswith("/series/observations"):
            return httpx.Response(404)
        if not params.get("api_key"):
            return error("Variable api_key is not set.  Read https://fred.stlouisfed.org/docs/api/api_key.html for more information.")
        if params["api_key"] != CLAVE_FRED:
            return error("The value for variable api_key is not registered.  Read https://fred.stlouisfed.org/docs/api/api_key.html for more information.")
        archivo = FIXTURES / f"fred_{params.get('series_id')}.json"
        if not archivo.exists():
            return error("The series does not exist.")
        cuerpo = json.loads(archivo.read_text(encoding="utf-8"))
        desde = date.fromisoformat(params.get("observation_start", "1600-01-01"))
        hasta = date.fromisoformat(params.get("observation_end", "9999-12-31"))
        cuerpo["observations"] = [o for o in cuerpo["observations"] if desde <= date.fromisoformat(o["date"]) <= hasta]
        cuerpo["count"] = len(cuerpo["observations"])
        return httpx.Response(200, json=cuerpo)

    return httpx.MockTransport(responder)


@pytest.fixture
def cliente_fred():
    with httpx.Client(transport=transporte_fred(), base_url="https://fred.test/fred") as c:
        yield c
