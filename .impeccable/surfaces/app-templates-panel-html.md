---
version: 1
slug: "app-templates-panel-html"
primary_target: "app/templates/panel.html"
related_targets: ["app/static/js/panel.js"]
---

# Panel de series

Modo: Operate. Tarea: elegir indicador, fuente, países (hasta 8), años e índice base 100; leer la gráfica y
la tabla. Frecuencia: diaria, en escritorio y celular. Estados: cargando, sin países, sin datos en la fuente o
el rango, error con reintento, series vacías, ocho series, series de miles de filas (dólar diario).
Hereda el mundo de la portada (ver DESIGN.md): tipografía, paleta, densidad y una firma.
Firma: cada serie conserva su color en ficha, leyenda, gráfica (con brillo suave en el tema oscuro),
tooltip y encabezado de la tabla; la serie 1 es el cian del producto; las cifras van en Geist Mono.
Barra superior de vidrio, filtros en una tarjeta de herramientas, gráfica y tabla en tarjetas separadas.
Sin coreografía de carga: transiciones de 150–250 ms solo de estado.
