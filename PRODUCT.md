# Product

<!-- impeccable:product-schema 1 -->

> Fuente: CLAUDE.md del proyecto, el código existente y el pedido de rediseño del cliente transmitido por
> la conversación principal (octubre 2026). No hubo ronda de preguntas directa con el cliente: lo marcado
> como *(inferido)* sale del pedido y debe confirmarse.

## Platform

web

## Users

- **Rubén, economista** (dueño del producto): recopila y compara series económicas internacionales y de
  Uruguay para su trabajo y para asesorar a sus clientes. Usa el panel para armar comparaciones (países,
  rangos de años, índices base 100) y leer los valores exactos.
- **Sus clientes**: entran con una cuenta propia a consultar las mismas series. A futuro pagan por el
  acceso. *(inferido: perfil profesional, no técnico, que valora claridad y confianza en la fuente.)*

## Product Purpose

Plataforma SaaS de datos económicos: reúne en un solo lugar series oficiales (FMI, Banco Mundial, INE,
BCU), las guarda con su fuente y deja compararlas en gráficas y tablas con selector de rango de fechas.
Éxito: que un usuario arme en segundos la comparación que necesita y confíe en de dónde sale cada número.

## Positioning

Cada valor conserva su fuente: cuando el FMI y el Banco Mundial dan cifras distintas para el mismo dato,
se guardan las dos y el usuario elige; nunca se mezclan en una misma gráfica. Series largas de Uruguay
(IPC desde 1937, dólar interbancario diario desde 2000) junto a los indicadores internacionales.

## Operating Context

- Sistema cerrado con login (contraseña o Google) y doble factor obligatorio.
- Portada pública = pantallas de ingreso y registro; muestran una muestra real de los datos.
- Panel: indicador, fuente, países (hasta 8), rango de años, índice base 100; gráfica (ECharts) y tabla.
- Se usa en escritorio en horario de oficina y también desde el celular.

## Capabilities and Constraints

- Indicadores anuales internacionales (PBI, crecimiento, deuda, resultado fiscal, población, comercio
  exterior) y series de Uruguay mensuales y diarias.
- El FMI publica proyecciones: los años posteriores al último cerrado son estimaciones.
- Sin build de JavaScript; CSP estricta (`default-src 'self'`, sin estilos ni scripts en línea, sin CDNs):
  fuentes, librerías y estilos se sirven desde `app/static`.
- Contenedores con Podman. Comportamiento de login, registro y 2FA fijo.
- Cobro con pasarela de pago: decidido a futuro, sin precio ni planes definidos todavía.

## Brand Commitments

- Nombre: «Datos Económicos». Idioma: español rioplatense (voseo).
- Estética pedida por el cliente (octubre 2026, reemplaza el pedido anterior «tipo Stripe o Linear»):
  **futurista**. Modo oscuro como identidad principal (azul noche casi negro, con profundidad), acentos
  eléctricos usados solo como acento, brillos sutiles en bordes y líneas de las gráficas, vidrio esmerilado
  en tarjetas, grilla de fondo tenue, tipografía geométrica o técnica con una monoespaciada para cifras,
  microanimaciones de entrada y de datos. El modo claro queda como alternativa secundaria.
- Límites del cliente: los datos se leen con contraste AA real; es una herramienta para un economista,
  no un videojuego.
- Rechazado: el estilo anterior (azul petróleo oscuro con fondo piedra, «anticuado») y cualquier aire de
  «sistema administrativo».

## Evidence on Hand

- Datos reales en la base: cobertura por fuente, cantidad de países y regiones, índice del PBI calculado
  (`app/web/portada.py`).
- No hay clientes, testimonios, precios ni métricas comerciales: no inventarlos.

## Product Principles

1. La fuente de cada número siempre a la vista.
2. Comparar es la tarea central: países, años e índices en pocos pasos.
3. Mostrar datos reales antes que promesas, también en la portada.
4. Claridad de producto profesional: nada que parezca un formulario de oficina pública.

## Accessibility & Inclusion

WCAG 2.1 AA en los dos temas (claro y oscuro), foco visible, `prefers-reduced-motion` respetado, series
de la gráfica distinguibles con daltonismo (orden fijo y validado).
