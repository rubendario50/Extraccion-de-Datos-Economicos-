# Extracción de Datos Económicos

Plataforma de recopilación, análisis y difusión de datos económicos internacionales y de Uruguay.

## Objetivo

- Recopilar series económicas con la mayor extensión de tiempo posible (PBI, deuda pública, población, déficit fiscal, comercio exterior, cotizaciones como Dow Jones y oro).
- Automatizar su actualización desde fuentes públicas.
- Comparar series mediante índices base 100 y agrupamientos.
- Publicar los datos con gráficas en una web con acceso por usuario.

## Estado

Versión actual: 0.2.1 (ver `CHANGELOG.md`).

Desde la 0.1: base de datos PostgreSQL en Podman, tabla maestra de países (`data/seed/paises.csv`), carga del PBI del FMI DataMapper (PBI en dólares corrientes y crecimiento real) y una web con login (contraseña o Google, doble factor obligatorio) donde se eligen indicador, países y años y se ven la gráfica y la tabla, con opción de índice base 100. La arquitectura está en `docs/arquitectura.md`.

Desde la 0.2: más indicadores internacionales anuales del FMI (deuda bruta y resultado fiscal del gobierno general, población) y del Banco Mundial (PBI, crecimiento, población, exportaciones, importaciones y deuda del gobierno central). Cuando un mismo dato viene de las dos fuentes se guardan ambas cifras por separado, y el panel y la API dejan elegir la fuente.

## Levantar el proyecto con Podman

Requisitos: Git, Podman y `podman-compose`.

### Linux Mint

```bash
sudo apt install podman python3-pip pipx
pipx install podman-compose          # o: pip install --user podman-compose

git clone https://github.com/rubendario50/Extraccion-de-Datos-Economicos-.git
cd Extraccion-de-Datos-Economicos-
cp .env.example .env                 # editar .env: POSTGRES_PASSWORD, SECRET_KEY y APP_ENCRYPTION_KEY (ver "Claves")
podman-compose up -d                 # construye la imagen, levanta la base y la web
```

### Windows

En PowerShell:

```powershell
winget install -e --id RedHat.Podman
podman machine init
podman machine start
pip install podman-compose

git clone https://github.com/rubendario50/Extraccion-de-Datos-Economicos-.git
cd Extraccion-de-Datos-Economicos-
copy .env.example .env               # editar .env: POSTGRES_PASSWORD, SECRET_KEY y APP_ENCRYPTION_KEY (ver "Claves")
podman-compose up -d
```

### Claves

Antes del primer arranque hay que completar dos claves en el `.env` (la app no arranca sin `APP_ENCRYPTION_KEY`). Se generan con Python, en cualquier PC:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                               # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # APP_ENCRYPTION_KEY
```

(En Windows, `py` en lugar de `python`. La segunda necesita el paquete `cryptography`; si no está, se puede correr dentro del contenedor: `podman-compose run --rm app python -c "..."`.)

`APP_ENCRYPTION_KEY` cifra el secreto del doble factor de cada usuario: si se pierde o se cambia, hay que volver a configurar el doble factor de todos. `ADMIN_EMAIL` define qué email queda como administrador al registrarse.

### Cargar los datos

Al arrancar, el contenedor `app` aplica las migraciones de Alembic. Después hay que cargar las semillas (países, fuentes, indicadores) y los datos del FMI y del Banco Mundial (los comandos son iguales en Linux y Windows):

```bash
podman-compose exec app python -m app.etl todo                      # semillas + FMI + Banco Mundial

# o por partes:
podman-compose exec app python -m app.etl semillas
podman-compose exec app python -m app.etl fmi                       # todos los indicadores del FMI
podman-compose exec app python -m app.etl fmi --indicadores NGDPD   # solo algunos
podman-compose exec app python -m app.etl bm                        # todos los indicadores del Banco Mundial
podman-compose exec app python -m app.etl bm --indicadores NY.GDP.MKTP.CD,SP.POP.TOTL
```

Los códigos de país que la fuente publica y no están en `paises.csv` se avisan en el registro (`WARNING ... sin mapear`). Los agregados del Banco Mundial sin equivalente en el FMI (regiones propias del BM, grupos de ingreso) se omiten.

Las cargas son idempotentes: se pueden repetir para actualizar los valores sin duplicarlos.

Comprobar que funciona:

- http://localhost:8000/salud debe responder `{"estado": "ok"}`.
- http://localhost:8000/ lleva al ingreso. Creá una cuenta en "Creá una", configurá el doble factor con Google Authenticator, Authy o similar (guardá los 10 códigos de recuperación) y vas a ver el panel.
- Con la sesión iniciada, http://localhost:8000/api/series?indicador=PBI_USD_CORR&paises=URY,ARG&desde=2000&hasta=2025 devuelve las series; agregando `&base=2010` las devuelve en índice base 100. Sin sesión responde 401.

Otros comandos útiles:

```bash
podman-compose logs -f app       # ver los registros de la web
podman-compose down              # detener (los datos quedan en el volumen datos_pg)
podman-compose up -d --build     # reconstruir la imagen después de cambiar el código
```

## API

Toda la API exige una sesión iniciada con el doble factor completo (la cookie del navegador); sin ella responde 401. No hay `/docs` ni `/openapi.json` públicos porque el sistema es cerrado.

`GET /api/series` devuelve series internacionales anuales. Parámetros:

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `indicador` | sí | Código interno: `PBI_USD_CORR`, `PBI_CRECIMIENTO`, `POBLACION`, `DEUDA_GOB_GENERAL`, `RESULTADO_FISCAL`, `EXPORTACIONES_USD`, `IMPORTACIONES_USD`, `DEUDA_GOB_CENTRAL`. |
| `paises` | sí | Códigos ISO3 o del FMI DataMapper separados por coma (`URY,ARG,WEOWORLD`). No distingue mayúsculas; los repetidos se ignoran. Hasta 8. |
| `desde`, `hasta` | no | Primer y último año (inclusive). |
| `base` | no | Año base: las series se expresan en índice base 100. |
| `fuente` | no | `FMI_DM` o `BM`. Por defecto, la primera fuente con datos para ese indicador (el FMI antes que el Banco Mundial). |

Las fuentes nunca se mezclan: todas las series de una respuesta salen de la misma fuente, aunque el indicador tenga datos de las dos. Las cifras de ambas están en la misma unidad y escala (por ejemplo, el PBI en miles de millones de dólares y la población en millones).

Respuesta: `{"indicador": {codigo, nombre, unidad, escala}, "fuente", "fuente_nombre", "fuentes", "base", "series": [{"pais", "codigo", "nombre", "fuente", "datos": [{"anio", "valor"}]}]}`, donde `fuentes` lista las fuentes que publican el indicador. Errores: 404 (indicador, fuente o país desconocido, o fuente que no publica ese indicador), 400 (más de 8 países), 422 (parámetros inválidos o año base sin dato), con el motivo en `detail`.

## Acceso y seguridad

- Registro con nombre, email y contraseña (mínimo 12 caracteres, guardada con Argon2), o ingreso con Google.
- Doble factor obligatorio para todos: el primer ingreso muestra un QR para la app de autenticación y entrega 10 códigos de recuperación de un solo uso.
- Tras 5 intentos fallidos (contraseña o código) la cuenta queda bloqueada 15 minutos.
- La sesión dura 12 horas. "Salir" la cierra.
- Todavía no hay recuperación de contraseña ni verificación de email (necesitan un servidor de correo).

### Ingreso con Google

Es opcional: si `GOOGLE_CLIENT_ID` está vacío, el botón no aparece. Para activarlo:

1. Entrar a https://console.cloud.google.com/ y crear un proyecto (o elegir uno).
2. En **APIs y servicios → Pantalla de consentimiento de OAuth** (en la consola nueva: **Google Auth Platform → Branding**): tipo de usuario **Externo**, nombre de la aplicación, email de asistencia y email de contacto del desarrollador. Los permisos que se usan son los básicos (`openid`, `email`, `profile`), que no requieren verificación de Google. Mientras la app esté en modo "Prueba", solo pueden entrar los emails agregados en **Usuarios de prueba**; para abrirla a todos, **Publicar la aplicación**.
3. En **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - Tipo de aplicación: **Aplicación web**.
   - Orígenes autorizados de JavaScript: `http://localhost:8000`
   - URI de redireccionamiento autorizados: `http://localhost:8000/auth/google/callback`
4. Copiar el **ID de cliente** y el **Secreto del cliente** en `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` del `.env`, y reiniciar la app (`podman-compose up -d`).

Cuando la app tenga dominio propio (por ejemplo `https://datos.ejemplo.com`), agregar en la misma credencial el origen `https://datos.ejemplo.com` y la URI `https://datos.ejemplo.com/auth/google/callback`, y en el `.env` poner `BASE_URL=https://datos.ejemplo.com` y `COOKIE_SECURE=true`.

Si el email de Google ya tiene una cuenta con contraseña, se vinculan las dos (solo si Google confirma que el email está verificado). Quien entra con Google también pasa por el doble factor.

## Correr los tests en local

Los tests usan SQLite en memoria, respuestas de ejemplo del FMI y del Banco Mundial (`tests/fixtures/`) y un Google simulado: no necesitan Podman, PostgreSQL ni internet. Requieren Python 3.12 o superior.

Linux Mint:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest
```

## Agregar un indicador

Agregar una fila en `data/seed/indicadores.csv` con el código interno, sus datos, la fuente (`FMI_DM` o `BM`) y el código en esa fuente (por ejemplo `LP` en el FMI o `SP.POP.TOTL` en el Banco Mundial), y volver a correr `python -m app.etl semillas` y `python -m app.etl fmi` o `bm`.

Si es el mismo dato en las dos fuentes, se repite el código interno en dos filas, una por fuente; el nombre, la unidad y la escala salen de la primera. Si una fuente lo publica en otra escala, la columna `factor` convierte su valor a la del indicador: por ejemplo `1e-9` para pasar los dólares del Banco Mundial a miles de millones, o `1e-6` para pasar personas a millones.

## Tabla de países

`data/seed/paises.csv` es la fuente de verdad de los códigos internos de países y agregados, y se versiona. Se generó con `scripts/generar_paises.py`, que cruza el FMI DataMapper con los códigos WEO de la planilla del cliente. La columna `bm` tiene el código del Banco Mundial: el ISO3 en los países (salvo Kosovo `XKX`, Cisjordania y Gaza `PSE`, Isla de Man `IMN`, San Martín `MAF`), y `WLD`, `EMU` y `EUU` para el Mundo, la zona euro y la Unión Europea. Si se vuelve a correr, respeta los códigos ya asignados y agrega los países nuevos al final.
