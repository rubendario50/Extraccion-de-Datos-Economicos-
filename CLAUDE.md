# Extracción de Datos Económicos

Plataforma que recopila series económicas internacionales y de Uruguay, las compara (índices base 100, agrupamientos) y las publica con gráficas en una web con login.

## Decisiones del cliente (Rubén)

- Cotizaciones de bolsa y materias primas: guardar el **cierre del día**.
- PBI, deuda, población, déficit, comercio exterior: valores **anuales**.
- Tablas separadas por alcance (internacional / nacional) y frecuencia (anual / mensual), cruzables entre sí.
- Cada país tiene un **código interno único**, mapeado a los códigos de cada organismo (FMI, Banco Mundial, ISO).
- Guardar la fuente de cada valor: FMI y Banco Mundial pueden dar cifras distintas para el mismo dato.
- Prioridad: primero datos internacionales (empezando por el PBI del FMI), después Uruguay.
- Gráficas con selector de rango de fechas.
- Sistema cerrado con login; se puede publicar abiertamente lo que se elija. A futuro, cobro con pasarela de pago.
- Fuentes: preferir APIs oficiales (FMI DataMapper, Banco Mundial, FRED) antes que scraping. No scrapear sitios que lo prohíben (por ejemplo Investing.com).

## Entorno

- Contenedores con **Podman** (no Docker): usar `Containerfile` y `compose.yaml`, y levantar con `podman-compose`.
- Trabajo en la rama `main` del repo https://github.com/rubendario50/Extraccion-de-Datos-Economicos-

## Flujo con agentes

Los agentes del proyecto están en `.claude/agents/`:

1. `programador` implementa cada tarea con sus tests.
2. `tester` verifica (tests + navegador con Playwright) y responde APROBADO o RECHAZADO. Si rechaza, vuelve al programador.
3. `publicador` saca la versión (semver, CHANGELOG, commit y tag) solo con aprobación del tester.

La conversación principal coordina: divide el trabajo en tareas y llama a cada agente.

## Plan de versiones

- v0.1: base de datos en Podman, tabla maestra de países, carga del PBI del FMI.
- v0.2: resto de indicadores internacionales, después Uruguay.
- v0.3: índices base 100 y agrupamientos.
- v0.4: web con gráficas y login.
- v1.0: actualización automática y publicación.

## Puesta en marcha en una PC nueva

1. Instalar Git, Node.js, Python y Podman (`winget install -e --id RedHat.Podman`), luego `podman machine init` y `podman machine start`, y `pip install podman-compose`.
2. Clonar el repo y abrirlo con Claude Code: toma del repo los agentes, las skills de diseño (`.claude/skills/`: impeccable, design-taste-frontend y el paquete de Emil Kowalski) y los servidores MCP (`.mcp.json`: Playwright y Figma). Figma pide iniciar sesión la primera vez (`/mcp`).
