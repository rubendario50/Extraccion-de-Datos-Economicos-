# Arquitectura

Documento de referencia para todos los agentes. Los requisitos del cliente están en `docs/cliente/` y resumidos en `CLAUDE.md`.

## Stack

| Capa | Elección | Motivo |
|---|---|---|
| Lenguaje | Python 3.12 | Todo el sistema en un solo lenguaje; buen ecosistema para datos. |
| Web y API | FastAPI + Uvicorn | API JSON y páginas en el mismo servicio. |
| Páginas | Jinja2 renderizado en servidor + JavaScript mínimo sin build | No hace falta Node para compilar el frontend. |
| Gráficas | Apache ECharts 5.5.1, copiado en `app/static/vendor/` | Series largas, zoom por rango de fechas, sin CDN en producción. |
| Base de datos | PostgreSQL 16 (en Podman); SQLite en memoria para los tests | Relacional, cruces entre tablas. |
| ORM y migraciones | SQLAlchemy 2 + Alembic | Mismo modelo para Postgres y SQLite. |
| Contenedores | Podman: `Containerfile` + `compose.yaml`, se levanta con `podman-compose` | Decisión del cliente: no Docker. |
| Tests | pytest; Playwright (Python) para el navegador | |

Dependencias principales: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `jinja2`, `python-multipart`, `pydantic-settings`, `httpx`, `argon2-cffi`, `pyotp`, `segno` (QR en SVG), `authlib` (Google), `cryptography` (cifrado del secreto TOTP), `itsdangerous`, `pycountry` (nombres de países en español).

## Estructura

```
app/
  main.py            # crea la app FastAPI, monta rutas y estáticos
  config.py          # Settings (pydantic-settings) leídos de .env
  db.py              # engine, SessionLocal, Base, get_db
  models/            # modelos SQLAlchemy (paises, indicadores, datos, usuarios)
  etl/               # cargadores por fuente: fmi.py, ...; CLI en __main__.py
  analisis/          # índices base 100 y agrupamientos
  auth/              # registro, login, Google, 2FA, sesiones, CSRF
  api/               # endpoints JSON (/api/...)
  web/               # rutas que devuelven HTML
  templates/
  static/            # css, js, vendor/echarts.min.js
migrations/          # Alembic
data/seed/           # CSV versionados (paises.csv, indicadores.csv)
tests/
Containerfile
compose.yaml
.env.example
pyproject.toml
```

## Modelo de datos

**Países.** Cada país tiene un código interno único de 3 dígitos (`001`, `002`, ...), asignado una sola vez y guardado en `data/seed/paises.csv`. Nunca se renumera: los países nuevos van al final.

- `pais`: `id`, `codigo` (interno, único), `nombre` (español), `nombre_en`, `iso2`, `iso3`, `es_agregado` (Mundo, Zona euro, etc.).
- `pais_codigo_externo`: `pais_id`, `organismo` (`ISO3`, `FMI_DM`, `FMI_WEO`, `BM`), `codigo`. Único por (`organismo`, `codigo`). El FMI DataMapper usa ISO3; el WEO usa los códigos numéricos que están en la planilla del cliente (hoja "Codigos": 512 Afganistán, 213 Argentina, ...).

**Fuentes e indicadores.**

- `fuente`: `codigo` (`FMI_DM`, `BM`, `FRED`), `nombre`, `url`.
- `indicador`: `codigo` interno (`PBI_USD_CORR`, `PBI_CRECIMIENTO`, ...), `nombre`, `unidad`, `escala`, `alcance` (`internacional` / `nacional`), `frecuencia` (`anual` / `mensual` / `diaria`), `descripcion`.
- `indicador_serie_externa`: `indicador_id`, `fuente_id`, `codigo_externo` (por ejemplo `NGDPD`).

**Valores.** Tablas separadas por alcance y frecuencia (decisión del cliente). Todas guardan la fuente de cada valor, porque FMI y Banco Mundial pueden dar cifras distintas para el mismo dato.

- `dato_internacional_anual`: `pais_id`, `indicador_id`, `fuente_id`, `anio`, `valor`, `actualizado_en`. Clave: (`pais_id`, `indicador_id`, `fuente_id`, `anio`).
- `dato_internacional_mensual`: igual pero con `periodo` (fecha del primer día del mes).
- `dato_nacional_anual` y `dato_nacional_mensual`: datos de Uruguay, sin `pais_id`.
- `cotizacion_diaria`: `indicador_id`, `fuente_id`, `fecha`, `cierre` (cierre del día, decisión del cliente).

Las cargas son idempotentes: si el valor ya existe se actualiza (upsert), no se duplica.

## Fuentes

Preferir APIs oficiales antes que scraping. No scrapear sitios que lo prohíben (por ejemplo Investing.com).

- FMI DataMapper: `https://www.imf.org/external/datamapper/api/v1/{indicador}` devuelve todos los países y años. También `/countries`, `/regions`, `/groups`, `/indicators`. Indicadores de v0.1: `NGDPD` (PBI, miles de millones USD corrientes), `NGDP_RPCH` (crecimiento real %). v0.2: `PPPGDP`, `NGDPDPC`, `GGXWDG_NGDP` (deuda % PIB), `LP` (población), `GGXCNL_NGDP` (déficit/superávit % PIB).
- v0.2: Banco Mundial (PBI constante, comercio exterior), FRED (Dow Jones, oro), Uruguay (BCU, INE).

Ejecución: `python -m app.etl fmi` (CLI). Los tests no llaman a internet: usan `httpx.MockTransport` con respuestas de ejemplo en `tests/fixtures/`.

## Autenticación

Sistema cerrado: todo dato requiere sesión iniciada con doble factor.

- **Registro** con nombre, email y contraseña (mínimo 12 caracteres, hash Argon2).
- **Google** con OpenID Connect (Authlib). Si `GOOGLE_CLIENT_ID` no está configurado, el botón no se muestra. URI de redirección mientras no haya dominio: `http://localhost:8000/auth/google/callback`.
- **Doble factor obligatorio (TOTP)** para todos, incluidos los que entran con Google: al primer ingreso se muestra un QR para Google Authenticator / Authy, se confirma con un código y se entregan 10 códigos de recuperación de un solo uso (guardados con hash). El secreto TOTP se guarda cifrado con `APP_ENCRYPTION_KEY` (Fernet).
- **Sesiones** en la tabla `sesion` (token aleatorio en cookie HttpOnly, SameSite=Lax, `Secure` configurable con `COOKIE_SECURE`; en la base solo el hash del token). La sesión tiene un estado `mfa_ok`; sin él solo se puede acceder a las pantallas del segundo factor.
- **CSRF**: token por sesión en todos los formularios POST.
- **Fuerza bruta**: tras 5 intentos fallidos de contraseña o de código, bloqueo de 15 minutos para esa cuenta.
- Roles `admin` y `usuario`. El email de `ADMIN_EMAIL` queda como admin al registrarse.

Pendiente para más adelante: verificación de email y recuperación de contraseña (requieren un servidor SMTP), pasarela de pago, contenido público.

## Web

- `/login`, `/registro`, `/2fa/configurar`, `/2fa/verificar`, `/salir`.
- `/` panel: elegir indicador, uno o varios países y un rango de años; ver gráfica de líneas y tabla.
- Opción de índice base 100: el usuario elige el año base y todas las series pasan a valer 100 en ese año.
- Interfaz en español rioplatense, sobria y enfocada en los datos. Usar las skills de diseño del proyecto (`.claude/skills/impeccable`, `design-taste-frontend`, `emil-design-eng`).

## Configuración (`.env`)

`DATABASE_URL`, `SECRET_KEY`, `APP_ENCRYPTION_KEY`, `COOKIE_SECURE`, `ADMIN_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BASE_URL` (por ahora `http://localhost:8000`). `.env.example` documenta cada una; `.env` nunca se commitea.
