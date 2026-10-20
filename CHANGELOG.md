# Registro de cambios

Todos los cambios importantes del sistema se anotan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [versionado semántico](https://semver.org/lang/es/).

## [Pendiente]

### Por hacer

- Verificación del email al registrarse y recuperación de contraseña.
- Pedir autorización al BCU antes de redistribuir o cobrar por sus datos: sus
  términos solo permiten la reproducción sin fines de lucro, citando la
  fuente.
- Decidir qué hacer con el error de origen del BCU del 27/04/2000 (venta
  1,905).

## [0.2.5] - 2026-10-20

Proyecciones del FMI marcadas.

### Agregado

- **Proyecciones del FMI marcadas**: en la gráfica, el tramo proyectado de
  cada línea es punteado y una banda «Proyección del FMI» cubre esos años; en
  la tabla, esas filas llevan «proy.» junto al año y una nota que lo explica.
  El tooltip también lo aclara.
- La API (`/api/series`) indica desde qué año proyecta el FMI y marca cada dato
  proyectado. Los datos del Banco Mundial, del INE y del BCU no llevan la marca.
- El FMI no informa por país cuál es su último dato real: se toma como
  proyección todo año desde el de la edición del informe del FMI (World
  Economic Outlook) cargada, o desde el año en curso si es anterior.
- Si el FMI responde de forma inesperada al consultar la edición de su
  informe, la carga de datos sigue igual y la proyección se marca desde el año
  en curso.

### Para actualizar

- Hay que reconstruir la imagen (`podman-compose up -d --build`; si el
  contenedor no cambia, agregar `--force-recreate`) para aplicar la nueva
  migración, y volver a cargar el FMI (`python -m app.etl fmi`) para guardar la
  edición de sus datos.

## [0.2.4] - 2026-10-18

Nueva identidad visual.

### Cambiado

- **Nueva identidad visual futurista**: tema oscuro azul noche por defecto,
  con tarjetas de vidrio, acento cian y tipografía Geist, con las cifras en
  Geist Mono.
- **Modo claro** disponible con un botón; el sistema recuerda la elección.
- **Portada nueva** con la gráfica del PBI animada y mosaicos con las fuentes
  de datos.
- Animaciones suaves que respetan la preferencia de movimiento reducido del
  sistema.

### Corregido

- El eje de la gráfica del IPC mostraba "0" cuando los valores eran chicos.
- La portada aclara que los datos del FMI incluyen proyecciones hasta 2031.
- Un rango de un solo año se muestra como un año y no como un intervalo.
- La portada carga más rápido (los datos se guardan en caché 5 minutos).

## [0.2.3] - 2026-10-18

Mejoras de la portada y de la presentación de los datos.

### Cambiado

- La portada muestra una gráfica real del PBI y la cobertura de cada fuente
  de datos.
- En las series mensuales y diarias, la tabla se agrupa por año y la columna
  del año queda fija al desplazarse.
- Los datos de Uruguay se muestran como una serie única.
- Mejor formato de los números en la gráfica y en la tabla.

## [0.2.2] - 2026-10-18

Primeros datos propios de Uruguay.

### Agregado

- **Datos de Uruguay**, con carga automática desde fuentes oficiales:
  - IPC del INE: índice mensual desde julio de 1937 (base octubre 2022 = 100).
  - Tasa de desempleo del INE: mensual, Total País, desde 2006 (Encuesta
    Continua de Hogares).
  - Dólar interbancario del BCU: cierre de cada día hábil desde enero de
    2000, con actualización incremental.
- **Comandos de carga nuevos**: `python -m app.etl ine` y
  `python -m app.etl bcu`, incluidos también en `python -m app.etl todo`.

### Cambiado

- En el panel, el selector de indicadores se agrupa en **Internacionales** y
  **Uruguay**.
- Las series mensuales y diarias se grafican con eje de fechas. En esas
  series, el índice base 100 usa el promedio del año base.
- Si una fuente falla, `python -m app.etl todo` sigue con las demás y al final
  informa qué se cargó y qué falló.

### Para actualizar

- Hay que reconstruir la imagen con `podman-compose up -d --build`, porque hay
  una dependencia nueva.

## [0.2.1] - 2026-10-18

Mejoras de diseño del panel y correcciones.

### Cambiado

- **Diseño del panel y de las pantallas de ingreso**: más claro y legible, en
  computadora y celular, en modo claro y oscuro.
- Los nombres largos de países y regiones ya no desarman la pantalla.
- El selector de fuente muestra nombres cortos (FMI / Banco Mundial).

### Corregido

- Un país que la fuente elegida no publica ahora se marca como "sin datos en
  esta fuente", en lugar de mostrarse como una serie más con etiquetas
  encimadas.
- Con índice base 100, un país sin datos en la fuente o en el rango ya no deja
  vacía la gráfica entera.
- Al cambiar de fuente o de indicador, el rango de años completo se ajusta al
  de la nueva opción.
- El parámetro de fuente de la API ignora mayúsculas.
- El texto de la pantalla de ingreso nombra las fuentes reales.

## [0.2.0] - 2026-10-18

Más indicadores internacionales y una segunda fuente de datos.

### Agregado

- **Nuevos indicadores del FMI**:
  - Deuda pública bruta del gobierno general (% del PBI).
  - Resultado fiscal (% del PBI).
  - Población (millones de personas).
- **Nueva fuente: el Banco Mundial**:
  - PBI en dólares corrientes.
  - Crecimiento del PBI.
  - Población.
  - Exportaciones e importaciones de bienes y servicios.
  - Deuda del gobierno central (% del PBI).
  - Los valores quedan en la misma escala que los del FMI, para poder
    compararlos directamente.
- **Fuente de cada dato**: cada valor guarda de qué organismo proviene. El
  panel tiene un selector de fuente (FMI / Banco Mundial) y nunca mezcla en
  una misma gráfica cifras de fuentes distintas.
- **Comandos de carga nuevos**: `python -m app.etl bm` carga los datos del
  Banco Mundial y `python -m app.etl todo` carga todas las fuentes.

### Para actualizar

- Hay que reconstruir la imagen con `podman-compose up -d --build` para que
  se aplique la nueva migración de la base de datos.

## [0.1.0] - 2026-10-18

Primera versión funcional del sistema.

### Agregado

- **Datos del FMI**: carga automática del PBI a precios corrientes (en dólares)
  y del crecimiento real del PBI desde la base del FMI, para 229 países y
  regiones, desde 1980.
- **Tabla maestra de países**: cada país o región tiene un código interno único
  y guarda también los códigos que usa el FMI, para poder cruzar fuentes.
- **Panel de consulta**:
  - Gráfica de la serie elegida.
  - Selector de países para comparar varios a la vez.
  - Elección del rango de años.
  - Opción de ver los valores como índice base 100 para comparar la evolución.
  - Tabla con los valores de cada año.
- **Cuentas de usuario**:
  - Registro con email y contraseña.
  - Ingreso con Google (opcional, si está configurado).
  - Doble factor obligatorio con una app de autenticación, y códigos de
    recuperación para entrar si se pierde el teléfono.
- **Instalación con contenedores**: archivos listos para levantar la aplicación
  y la base de datos con Podman.

[Pendiente]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.5...HEAD
[0.2.5]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/releases/tag/v0.1.0
