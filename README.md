# Extracción de Datos Económicos

Plataforma de recopilación, análisis y difusión de datos económicos internacionales y de Uruguay.

## Objetivo

- Recopilar series económicas con la mayor extensión de tiempo posible (PBI, deuda pública, población, déficit fiscal, comercio exterior, cotizaciones como Dow Jones y oro).
- Automatizar su actualización desde fuentes públicas.
- Comparar series mediante índices base 100 y agrupamientos.
- Publicar los datos con gráficas en una web con acceso por usuario.

## Estado

Versión actual: 0.2.6 (ver `CHANGELOG.md`).

Desde la 0.1: base de datos PostgreSQL en Podman, tabla maestra de países (`data/seed/paises.csv`), carga del PBI del FMI DataMapper (PBI en dólares corrientes y crecimiento real) y una web con login (contraseña o Google, doble factor obligatorio) donde se eligen indicador, países y años y se ven la gráfica y la tabla, con opción de índice base 100. La arquitectura está en `docs/arquitectura.md`.

Desde la 0.2: más indicadores internacionales anuales del FMI (deuda bruta y resultado fiscal del gobierno general, población) y del Banco Mundial (PBI, crecimiento, población, exportaciones, importaciones y deuda del gobierno central). Cuando un mismo dato viene de las dos fuentes se guardan ambas cifras por separado, y el panel y la API dejan elegir la fuente.

Desde la 0.2.2, primeros datos de Uruguay: IPC mensual (INE, desde 1937), tasa de desempleo mensual (INE, Encuesta Continua de Hogares, desde 2006) y dólar interbancario billete diario (BCU, cierre del día, desde 2000). En el panel aparecen en el grupo "Uruguay" del selector de indicadores, con una sola serie y eje de fechas.

## Levantar el proyecto con Podman

Requisitos: Git, Podman y `podman-compose`.

### Linux Mint

```bash
sudo apt install podman python3-pip pipx
pipx install podman-compose          # o: pip install --user podman-compose

git clone https://github.com/rubendario50/Extraccion-de-Datos-Economicos-.git
cd Extraccion-de-Datos-Economicos-
cp .env.example .env                 # editar .env: POSTGRES_PASSWORD, SECRET_KEY y SMTP_* (ver "Claves")
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
copy .env.example .env               # editar .env: POSTGRES_PASSWORD, SECRET_KEY y SMTP_* (ver "Claves")
podman-compose up -d
```

### Claves

Antes del primer arranque hay que completar `SECRET_KEY` en el `.env`. Se genera con Python, en cualquier PC:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
```

(En Windows, `py` en lugar de `python`.)

`ADMIN_EMAIL` define qué email queda como administrador al registrarse.

### Correo (código de ingreso)

El doble factor es un código que se manda al email de cada usuario, así que la app necesita una cuenta de Gmail para mandar correos. Se usa una **contraseña de aplicación** (no la contraseña normal de la cuenta):

1. En la cuenta de Gmail que va a mandar los correos, activar la **verificación en 2 pasos** (https://myaccount.google.com/security).
2. Entrar a https://myaccount.google.com/apppasswords, crear una contraseña de aplicación (por ejemplo «Datos Económicos») y copiar los 16 caracteres.
3. Completar en el `.env`:

```
SMTP_USER=la-cuenta@gmail.com
SMTP_PASSWORD=los 16 caracteres de la contraseña de aplicación
SMTP_FROM=                # opcional; vacío = SMTP_USER
```

`SMTP_HOST` y `SMTP_PORT` ya vienen con `smtp.gmail.com` y `587` (STARTTLS). Después de cambiar el `.env`, recrear el contenedor: `podman-compose up -d --force-recreate app`.

Si `SMTP_USER` o `SMTP_PASSWORD` quedan vacíos (para probar en la PC), no se manda ningún correo: el código aparece en el registro de la app (`podman-compose logs app`) como `Correo sin configurar: código para <email>: 123456`.

### Cargar los datos

Al arrancar, el contenedor `app` aplica las migraciones de Alembic. Después hay que cargar las semillas (países, fuentes, indicadores) y los datos del FMI, del Banco Mundial, del INE y del BCU (los comandos son iguales en Linux y Windows):

```bash
podman-compose exec app python -m app.etl todo                      # semillas + FMI + Banco Mundial + INE + BCU

# o por partes:
podman-compose exec app python -m app.etl semillas
podman-compose exec app python -m app.etl fmi                       # todos los indicadores del FMI
podman-compose exec app python -m app.etl fmi --indicadores NGDPD   # solo algunos
podman-compose exec app python -m app.etl bm                        # todos los indicadores del Banco Mundial
podman-compose exec app python -m app.etl bm --indicadores NY.GDP.MKTP.CD,SP.POP.TOTL
podman-compose exec app python -m app.etl ine                       # IPC y desempleo (planillas del INE)
podman-compose exec app python -m app.etl ine --indicadores ECH0013 # solo el desempleo
podman-compose exec app python -m app.etl bcu                       # dólar interbancario (servicio web del BCU)
podman-compose exec app python -m app.etl bcu --desde 2000-01-01    # volver a bajar toda la serie
```

La primera carga del BCU baja la serie desde 2000 (un pedido por año, porque el servicio acepta hasta 366 días por pedido); las siguientes retoman 10 días antes de la última cotización guardada. El INE se baja entero cada vez (las planillas son chicas y el INE revisa cifras pasadas).

Los códigos de país que la fuente publica y no están en `paises.csv` se avisan en el registro (`WARNING ... sin mapear`). Los agregados del Banco Mundial sin equivalente en el FMI (regiones propias del BM, grupos de ingreso) se omiten.

Las cargas son idempotentes: se pueden repetir para actualizar los valores sin duplicarlos.

Si una fuente falla (sin conexión, respuesta vacía, planilla con otro formato), se muestra `Error (FUENTE): ...` y no se guarda nada de esa fuente. En `todo` se sigue con las demás, al final se listan las que fallaron y el comando sale con código 1.

Comprobar que funciona:

- http://localhost:8000/salud debe responder `{"estado": "ok"}`.
- http://localhost:8000/ lleva al ingreso. Creá una cuenta en "Creá una", escribí el código de 6 dígitos que llega a tu email (o, sin correo configurado, el que aparece en `podman-compose logs app`) y vas a ver el panel.
- Con la sesión iniciada, http://localhost:8000/api/series?indicador=PBI_USD_CORR&paises=URY,ARG&desde=2000&hasta=2025 devuelve las series; agregando `&base=2010` las devuelve en índice base 100. Sin sesión responde 401.

Otros comandos útiles:

```bash
podman-compose logs -f app       # ver los registros de la web
podman-compose down              # detener (los datos quedan en el volumen datos_pg)
podman-compose up -d --build     # reconstruir la imagen después de cambiar el código
```

## API

Toda la API exige una sesión iniciada con el doble factor completo (la cookie del navegador); sin ella responde 401. No hay `/docs` ni `/openapi.json` públicos porque el sistema es cerrado.

`GET /api/series` devuelve series internacionales anuales (por país) y series de Uruguay (anuales, mensuales o diarias). Parámetros:

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `indicador` | sí | Código interno. Internacionales: `PBI_USD_CORR`, `PBI_CRECIMIENTO`, `POBLACION`, `DEUDA_GOB_GENERAL`, `RESULTADO_FISCAL`, `EXPORTACIONES_USD`, `IMPORTACIONES_USD`, `DEUDA_GOB_CENTRAL`. De Uruguay: `IPC_UY`, `DESEMPLEO_UY` (mensuales), `DOLAR_INTERBANCARIO` (diaria). |
| `paises` | en los internacionales | Códigos ISO3 o del FMI DataMapper separados por coma (`URY,ARG,WEOWORLD`). No distingue mayúsculas; los repetidos se ignoran. Hasta 8. En los indicadores de Uruguay se omite (o solo `URY`). |
| `desde`, `hasta` | no | Primer y último año (inclusive), también en las series mensuales y diarias. |
| `base` | no | Año base: las series se expresan en índice base 100. En las mensuales y diarias vale 100 el promedio del año base. |
| `fuente` | no | `FMI_DM`, `BM`, `INE` o `BCU`. Por defecto, la primera fuente con datos para ese indicador (el FMI antes que el Banco Mundial). |

Las fuentes nunca se mezclan: todas las series de una respuesta salen de la misma fuente, aunque el indicador tenga datos de las dos. Las cifras de ambas están en la misma unidad y escala (por ejemplo, el PBI en miles de millones de dólares y la población en millones).

Respuesta: `{"indicador": {codigo, nombre, unidad, escala, alcance, frecuencia}, "fuente", "fuente_nombre", "fuentes", "base", "proyeccion_desde", "series": [{"pais", "codigo", "nombre", "fuente", "datos": [{"anio", "valor"}]}]}`, donde `fuentes` lista las fuentes que publican el indicador. Con la fuente `FMI_DM`, `proyeccion_desde` es el primer año que el FMI publica como proyección y cada dato trae además `"proyeccion": true` o `false`; con las demás fuentes (que no publican proyecciones), `proyeccion_desde` es `null` y los datos no llevan la marca. Cómo se decide el año: `docs/arquitectura.md`, "Proyecciones del FMI". En las series mensuales y diarias cada dato trae `fecha` (ISO, `"2024-03-01"`; en las mensuales, el primer día del mes) en lugar de `anio`, y hay una sola serie, `"pais": "URY"`. Ejemplo: `/api/series?indicador=DOLAR_INTERBANCARIO&desde=2024`. Errores: 404 (indicador, fuente o país desconocido, o fuente que no publica ese indicador), 400 (más de 8 países, u otro país en un indicador de Uruguay), 422 (parámetros inválidos o año base sin dato), con el motivo en `detail`.

## Acceso y seguridad

- Registro con nombre, email y contraseña (mínimo 12 caracteres, guardada con Argon2), o ingreso con Google.
- Doble factor obligatorio para todos, también para los que entran con Google: después de la contraseña (o de Google) se manda un código de 6 dígitos al email de la cuenta. Vence a los 10 minutos, sirve una sola vez y al pedir otro el anterior deja de valer. En la base solo se guarda su hash. Ver "Correo (código de ingreso)" para configurar el envío.
- "Reenviar código" manda uno nuevo; hay que esperar 60 segundos entre envíos y se mandan hasta 5 por hora por cuenta.
- Tras 5 intentos fallidos (contraseña o código) la cuenta queda bloqueada 15 minutos.
- La sesión dura 12 horas. "Salir" la cierra.
- Todavía no hay recuperación de contraseña.

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

Los tests usan SQLite en memoria, respuestas de ejemplo del FMI, del Banco Mundial, del INE (planillas reales recortadas) y del BCU (`tests/fixtures/`) y un Google simulado: no necesitan Podman, PostgreSQL ni internet. Requieren Python 3.12 o superior.

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

En el BCU el código es el de la moneda en su servicio de cotizaciones (por ejemplo `2230`, promedio del dólar fondo; la lista sale de `awsbcumonedas`), y alcanza con la fila del CSV. En el INE cada planilla tiene su propio formato: además de la fila hay que agregar en `app/etl/ine.py` la ruta del archivo y una función que lo lea (`ARCHIVOS`).

Si es el mismo dato en las dos fuentes, se repite el código interno en dos filas, una por fuente; el nombre, la unidad y la escala salen de la primera. Si una fuente lo publica en otra escala, la columna `factor` convierte su valor a la del indicador: por ejemplo `1e-9` para pasar los dólares del Banco Mundial a miles de millones, o `1e-6` para pasar personas a millones.

## Tabla de países

`data/seed/paises.csv` es la fuente de verdad de los códigos internos de países y agregados, y se versiona. Se generó con `scripts/generar_paises.py`, que cruza el FMI DataMapper con los códigos WEO de la planilla del cliente. La columna `bm` tiene el código del Banco Mundial: el ISO3 en los países (salvo Kosovo `XKX`, Cisjordania y Gaza `PSE`, Isla de Man `IMN`, San Martín `MAF`), y `WLD`, `EMU` y `EUU` para el Mundo, la zona euro y la Unión Europea. Si se vuelve a correr, respeta los códigos ya asignados y agrega los países nuevos al final.
