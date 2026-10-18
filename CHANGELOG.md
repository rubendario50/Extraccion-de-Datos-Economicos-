# Registro de cambios

Todos los cambios importantes del sistema se anotan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [versionado semántico](https://semver.org/lang/es/).

## [Pendiente]

- Verificación del email al registrarse y recuperación de contraseña.
- Marcar en la gráfica y en la tabla los años que son proyecciones del FMI.
- Más indicadores y datos propios de Uruguay (previsto para la v0.2).
- Probar la instalación completa con Podman y PostgreSQL reales.

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

[Pendiente]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rubendario50/Extraccion-de-Datos-Economicos-/releases/tag/v0.1.0
