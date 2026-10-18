"""Aplicación FastAPI."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api import series
from app.auth import google, rutas
from app.auth.csrf import ErrorCsrf
from app.auth.dependencias import RequiereIngreso
from app.auth.seguridad import verificar_configuracion
from app.config import get_settings
from app.web import panel
from app.web.plantillas import renderizar

DIR_ESTATICOS = Path(__file__).resolve().parent / "static"

# Solo recursos propios: nada de CDN ni scripts o estilos en línea.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
}


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    verificar_configuracion()  # falla al arrancar si falta APP_ENCRYPTION_KEY
    yield


ajustes = get_settings()
# Sistema cerrado: sin /docs, /redoc ni /openapi.json públicos (la API está descrita en el README).
app = FastAPI(
    title="Extracción de Datos Económicos",
    version=__version__,
    lifespan=ciclo_de_vida,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Cookie firmada solo para el `state` y el `nonce` del ingreso con Google.
app.add_middleware(
    SessionMiddleware,
    secret_key=ajustes.secret_key,
    session_cookie="oauth",
    max_age=600,
    same_site="lax",
    https_only=ajustes.cookie_secure,
)


@app.middleware("http")
async def cabeceras_de_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    for nombre, valor in CABECERAS_SEGURIDAD.items():
        respuesta.headers.setdefault(nombre, valor)
    if request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"  # datos de una sesión cerrada
    return respuesta


@app.exception_handler(RequiereIngreso)
async def sin_sesion(request: Request, exc: RequiereIngreso):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Iniciá sesión (con el doble factor) para usar la API."}, status_code=401)
    return RedirectResponse(exc.destino, status_code=303)


@app.exception_handler(ErrorCsrf)
async def csrf_invalido(request: Request, exc: ErrorCsrf):
    return renderizar(request, "error.html", {"titulo": "No se pudo enviar el formulario", "mensaje": exc.detail}, 403)


app.mount("/static", StaticFiles(directory=DIR_ESTATICOS), name="static")
app.include_router(rutas.router)
app.include_router(google.router)
app.include_router(panel.router)
app.include_router(series.router)


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok"}
