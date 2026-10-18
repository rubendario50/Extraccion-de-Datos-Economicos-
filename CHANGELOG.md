# Registro de cambios

Todos los cambios importantes del sistema se anotan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [versionado semántico](https://semver.org/lang/es/).

## [Pendiente]

- Verificación del email al registrarse y recuperación de contraseña.
- Marcar en la gráfica y en la tabla los años que son proyecciones del FMI.
- Datos propios de Uruguay (previsto para la próxima versión).

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

[Pendiente]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/releases/tag/v0.1.0
