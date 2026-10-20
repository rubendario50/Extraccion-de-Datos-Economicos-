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

Dependencias principales: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `jinja2`, `python-multipart`, `pydantic-settings`, `httpx`, `argon2-cffi`, `pyotp`, `segno` (QR en SVG), `authlib` (Google), `cryptography` (cifrado del secreto TOTP), `itsdangerous`, `pycountry` (nombres de países en español), `openpyxl` (planillas .xlsx del INE).

## Estructura

```
app/
  main.py            # crea la app FastAPI, monta rutas y estáticos
  config.py          # Settings (pydantic-settings) leídos de .env
  db.py              # engine, SessionLocal, Base, get_db
  models/            # modelos SQLAlchemy (paises, indicadores, datos, usuarios)
  etl/               # cargadores por fuente: fmi.py, banco_mundial.py, ine.py, bcu.py; comun.py (HTTP, TLS, mapeos);
                     # certificados/ (intermedio TLS que el INE no envía); CLI en __main__.py
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
- `pais_codigo_externo`: `pais_id`, `organismo` (`ISO3`, `FMI_DM`, `FMI_WEO`, `BM`), `codigo`. Único por (`organismo`, `codigo`). El FMI DataMapper usa ISO3; el WEO usa los códigos numéricos que están en la planilla del cliente (hoja "Codigos": 512 Afganistán, 213 Argentina, ...). El Banco Mundial usa ISO3 para los países (con excepciones como Kosovo `XKX` y Cisjordania y Gaza `PSE`) y códigos propios para sus agregados; solo se mapean los que tienen equivalente en el FMI (`WLD` Mundo, `EMU` zona euro, `EUU` Unión Europea). Columna `bm` de `paises.csv`. Ojo: un mismo código puede significar cosas distintas en cada organismo (`SSA` es África Subsahariana en el FMI y otro agregado en el BM), por eso cada organismo tiene su columna.

**Fuentes e indicadores.**

- `fuente`: `codigo` (`FMI_DM`, `BM`, `FRED`, `INE`, `BCU`), `nombre`, `url`.
- `indicador`: `codigo` interno (`PBI_USD_CORR`, `PBI_CRECIMIENTO`, ...), `nombre`, `unidad`, `escala`, `alcance` (`internacional` / `nacional`), `frecuencia` (`anual` / `mensual` / `diaria`), `descripcion`.
- `indicador_serie_externa`: `indicador_id`, `fuente_id`, `codigo_externo` (por ejemplo `NGDPD`), `factor` (opcional: multiplica el valor de la fuente para llevarlo a la unidad y escala del indicador interno; por ejemplo `1e-9` para el PBI del BM, que viene en dólares, porque `PBI_USD_CORR` está en miles de millones), `proyeccion_desde` (solo FMI: año de la edición del WEO con la que se cargó la serie; ver "Proyecciones del FMI"). Un indicador interno puede tener una serie en cada fuente; sus datos se guardan por separado (la fuente es parte de la clave) y la API y el panel muestran una sola fuente a la vez.

**Valores.** Tablas separadas por alcance y frecuencia (decisión del cliente). Todas guardan la fuente de cada valor, porque FMI y Banco Mundial pueden dar cifras distintas para el mismo dato.

- `dato_internacional_anual`: `pais_id`, `indicador_id`, `fuente_id`, `anio`, `valor`, `actualizado_en`. Clave: (`pais_id`, `indicador_id`, `fuente_id`, `anio`).
- `dato_internacional_mensual`: igual pero con `periodo` (fecha del primer día del mes).
- `dato_nacional_anual` y `dato_nacional_mensual`: datos de Uruguay, sin `pais_id`. Hoy: `IPC_UY` y `DESEMPLEO_UY` (mensuales, INE).
- `cotizacion_diaria`: `indicador_id`, `fuente_id`, `fecha`, `cierre` (cierre del día, decisión del cliente). Hoy: `DOLAR_INTERBANCARIO` (BCU).

La tabla de cada indicador sale de su `alcance` y `frecuencia` (`app/api/series.py`, `TABLAS`): internacional anual, nacional anual, nacional mensual o nacional diaria (cotizaciones).

Las cargas son idempotentes: si el valor ya existe se actualiza (upsert), no se duplica.

## Fuentes

Preferir APIs oficiales antes que scraping. No scrapear sitios que lo prohíben (por ejemplo Investing.com).

- FMI DataMapper: `https://www.imf.org/external/datamapper/api/v1/{indicador}` devuelve todos los países y años, incluidas las proyecciones del WEO (ver "Proyecciones del FMI"). También `/countries`, `/regions`, `/groups`, `/indicators`. Indicadores: `NGDPD` (PBI, miles de millones USD corrientes), `NGDP_RPCH` (crecimiento real %), `GGXWDG_NGDP` (deuda bruta del gobierno general, % PIB), `GGXCNL_NGDP` (préstamo/endeudamiento neto del gobierno general, % PIB), `LP` (población, millones). Pendientes: `PPPGDP`, `NGDPDPC`.
- Banco Mundial (World Development Indicators): `https://api.worldbank.org/v2/country/all/indicator/{codigo}?format=json&per_page=20000&page=N` devuelve `[metadatos, filas]` (se pagina con `pages`); los errores vienen con HTTP 200 y `[{"message": ...}]`. `/v2/country` indica qué códigos son agregados (`region.id == "NA"`). Indicadores: `NY.GDP.MKTP.CD` → `PBI_USD_CORR` (factor 1e-9), `NY.GDP.MKTP.KD.ZG` → `PBI_CRECIMIENTO`, `SP.POP.TOTL` → `POBLACION` (factor 1e-6), `NE.EXP.GNFS.CD` → `EXPORTACIONES_USD` y `NE.IMP.GNFS.CD` → `IMPORTACIONES_USD` (factor 1e-9), `GC.DOD.TOTL.GD.ZS` → `DEUDA_GOB_CENTRAL` (indicador propio: el gobierno central no es el gobierno general del FMI).
- INE (Uruguay): no tiene API. Publica planillas .xlsx con dirección fija en `https://www5.ine.gub.uy/documents/...` (enlazadas desde `https://www.gub.uy/instituto-nacional-estadistica`), que reemplaza en el mismo lugar con cada dato nuevo. Sin robots.txt en www5; los términos de uso de gub.uy consideran pública la información y admiten el acceso "a través de una aplicación informática". El servidor no envía el certificado intermedio de Sectigo: se agrega `app/etl/certificados/sectigo_dv_r36.pem` al contexto TLS (`comun.contexto_tls`), sin desactivar la verificación. Series (`codigo_externo` → planilla y lector en `ine.ARCHIVOS`):
  - `IPC_GENERAL` → `IPC_UY`: "IPC gral y variaciones_base 2022.xlsx", índice general total país, mensual desde julio de 1937, base octubre 2022 = 100 (columnas "Mes y año" e "Índice").
  - `ECH0013` → `DESEMPLEO_UY`: "Tasa de desempleo, por área geográfica" (Encuesta Continua de Hogares), columna "Total País", mensual desde 2006. La planilla intercala meses, trimestres calendario ("Enero - Marzo/06") y el total del año: se guardan solo los meses; trimestres y años se derivan de ellos.
  - Si el INE cambia el formato (no aparecen los encabezados esperados o no quedan datos), la carga falla con un error claro y no guarda nada.
- BCU (Uruguay): servicio web SOAP oficial de cotizaciones, `POST https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones` (WSDL en `?wsdl`; lista de monedas en `awsbcumonedas`). Hasta 366 días por pedido (si no, error 104); un rango sin cotizaciones responde el código 100, que no es un error. Una cotización por día hábil, la del cierre (la página del BCU la titula "cotizaciones interbancarias, cierre del día"); se guarda la venta (`TCV`). Datos desde el 3/1/2000. `codigo_externo` = código de moneda: `2225` (DLS. USA BILLETE) → `DOLAR_INTERBANCARIO`. Otras disponibles: `2230` promedio fondo, `2224` cable, `9800` unidad indexada. La carga es incremental: retoma 10 días antes de la última fecha guardada (`--desde` fuerza otro inicio). Los valores se guardan como los publica el BCU (hay al menos un error de origen: venta 1,905 el 27/04/2000). Términos de uso del BCU: reproducción sin fines de lucro citando la fuente; redistribuir o comercializar requiere autorización expresa del BCU (pendiente antes de publicar abiertamente o cobrar).
- Próximos: FRED (Dow Jones, oro).

### Proyecciones del FMI

El DataMapper publica los datos del World Economic Outlook (WEO), que incluyen proyecciones varios años hacia adelante (en la edición de octubre de 2026, hasta 2031). La API **no informa qué años son proyección**: ni `/{indicador}` ni `/{indicador}/{país}` traen ese dato, y `?meta=1` solo devuelve textos de la interfaz del sitio (revisado el 19/10/2026). El WEO completo (las bases que se descargan aparte) sí trae por país y por indicador el último año con dato real ("Estimates Start After"), pero el DataMapper no lo expone, así que no se inventa un año por país.

Lo único que da la API es la edición: `/indicators` trae para cada indicador `"source": "World Economic Outlook (October 2026)"`. Regla (`app/api/series.py`, `primer_anio_proyectado`):

- Al cargar (`python -m app.etl fmi`), se guarda el año de esa edición en `indicador_serie_externa.proyeccion_desde`. Si `/indicators` falla o no trae un año, queda vacío y la carga sigue.
- El primer año proyectado es el **menor entre el año de la edición y el año en curso** (sin edición conocida, el año en curso). Desde ese año, todos los valores del FMI son proyección, para todos los países.
- Es conservadora: en la edición de octubre el año en curso todavía no terminó, así que no puede ser un dato cerrado; si los datos no se actualizan en meses, la edición vieja sigue marcando como proyección los años que publicó como tales. Lo que no marca: en algunos países el WEO trae como "estimación" el año anterior a la edición (cuentas nacionales atrasadas). Para eso haría falta la base completa del WEO.
- El Banco Mundial, el INE y el BCU publican solo datos observados: sus series no llevan la marca.

La API la expone en `/api/series` (`proyeccion_desde` y `proyeccion` en cada dato del FMI), el panel la dibuja (tramo punteado, banda "Proyección del FMI", «proy.» en la tabla) y la portada usa la misma regla para cortar la muestra y la cobertura en el último año real.

Ejecución (CLI): `python -m app.etl fmi`, `bm`, `ine`, `bcu [--desde AAAA-MM-DD]`, o `python -m app.etl todo` (semillas + FMI + BM + INE + BCU). Los tests no llaman a internet: usan `httpx.MockTransport` con respuestas de ejemplo en `tests/fixtures/` (`fmi_<código>.json`, `bm_<código>.json`, `bm_paises.json`, `ine_*.xlsx` (planillas reales recortadas) y `bcu_*.xml` (respuestas reales del servicio)).

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
- `/` panel: elegir indicador, fuente (si el indicador tiene más de una; por defecto la primera con datos), uno o varios países y un rango de años; ver gráfica de líneas y tabla. Los años y países disponibles dependen de la fuente elegida.
- Proyecciones del FMI: el tramo proyectado de cada línea es punteado y una banda con el rótulo "Proyección del FMI" cubre esos años; el tooltip lo aclara y la tabla marca esas filas con «proy.» (texto, no solo color) y una nota. Ver "Proyecciones del FMI".
- Opción de índice base 100: el usuario elige el año base y todas las series pasan a valer 100 en ese año (en las mensuales y diarias, el promedio de ese año vale 100).
- Indicadores de Uruguay: van en el grupo "Uruguay" del selector. Tienen una sola serie (en lugar del buscador de países se muestra "Uruguay" fijo), el rango se elige igual por años y la gráfica usa un eje de fechas (ECharts `time`) con el zoom de abajo para acotar el período. La API los devuelve con `fecha` ISO en lugar de `anio`. La tabla muestra una fila por mes o por día; las cotizaciones diarias, con 3 decimales.
- Interfaz en español rioplatense, sobria y enfocada en los datos. Usar las skills de diseño del proyecto (`.claude/skills/impeccable`, `design-taste-frontend`, `emil-design-eng`).

## Configuración (`.env`)

`DATABASE_URL`, `SECRET_KEY`, `APP_ENCRYPTION_KEY`, `COOKIE_SECURE`, `ADMIN_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BASE_URL` (por ahora `http://localhost:8000`). `.env.example` documenta cada una; `.env` nunca se commitea.
