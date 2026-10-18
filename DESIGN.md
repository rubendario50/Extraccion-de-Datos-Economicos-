---
name: Datos Económicos
description: Series económicas oficiales para comparar, con identidad futurista oscura.
colors:
  noche: "#070b14"
  superficie: "#0f1626"
  superficie-2: "#151d30"
  superficie-3: "#1c2640"
  vidrio: "rgb(15 22 38 / 0.62)"
  vidrio-borde: "rgb(148 180 255 / 0.13)"
  tinta: "#e8edf7"
  tinta-2: "#a9b4c8"
  tinta-3: "#8a96ad"
  borde-control: "#5d6a85"
  cian: "#22d3ee"
  cian-hover: "#67e8f9"
  cian-texto: "#5ee6f7"
  sobre-cian: "#04121a"
  peligro: "#ff8fa3"
  serie-1: "#22d3ee"
  serie-2: "#ff9f43"
  serie-3: "#4ade80"
  serie-4: "#facc15"
  serie-5: "#f472b6"
  serie-6: "#a78bfa"
  serie-7: "#e2e8f0"
  serie-8: "#ef4444"
  claro-fondo: "#f5f7fb"
  claro-superficie: "#ffffff"
  claro-tinta: "#0b1220"
  claro-tinta-2: "#3c475c"
  claro-tinta-3: "#586379"
  claro-cian-texto: "#0e7490"
typography:
  display:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "clamp(2.25rem, 1.05rem + 2.5vw, 3.5rem)"
    fontWeight: 600
    lineHeight: 1.04
    letterSpacing: "-0.04em"
  titulo-hoja:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  titulo-panel:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  cuerpo:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  rotulo:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.45
  cifras:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  control: "8px"
  tarjeta: "14px"
  grande: "18px"
  ficha: "999px"
spacing:
  e-1: "4px"
  e-2: "8px"
  e-3: "12px"
  e-4: "16px"
  e-5: "24px"
  e-6: "32px"
  e-7: "48px"
  e-8: "64px"
components:
  button-primary:
    backgroundColor: "{colors.cian}"
    textColor: "{colors.sobre-cian}"
    rounded: "{rounded.control}"
    padding: "8px 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.cian-hover}"
  button-secondary:
    backgroundColor: "{colors.superficie-2}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.control}"
    height: "40px"
  input:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.control}"
    height: "40px"
  card:
    backgroundColor: "{colors.vidrio}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.tarjeta}"
    padding: "24px"
  tile-accent:
    backgroundColor: "{colors.cian}"
    textColor: "{colors.sobre-cian}"
    rounded: "{rounded.tarjeta}"
    padding: "16px"
---

# Design System: Datos Económicos

## Overview

Identidad futurista y oscura para una herramienta de economista: noche azul con profundidad, vidrio esmerilado,
un solo acento cian eléctrico y brillos sutiles que solo aparecen donde hay datos o acciones. El neón es acento,
nunca fondo de lectura: todo texto que se lee tiene contraste AA real (tinta 15:1, secundaria 8:1, terciaria
5,9:1 sobre el vidrio). Es una herramienta, no un videojuego: el panel no tiene coreografía de carga y las
transiciones de estado duran 150–250 ms.

La portada (ingreso y registro) muestra el producto trabajando: formulario de vidrio a la izquierda y, a la
derecha, la gráfica real del PBI cuyas líneas se encienden y se dibujan, más un tablero de mosaicos con las
fuentes y sus años. El modo claro es una alternativa digna que la persona elige con el botón de tema
(`tema.js`, guardado en `localStorage`); sin elección, el sitio es oscuro.

## Colors

### Primary
- **Cian eléctrico** (`#22d3ee`): acción principal, foco, serie 1 de toda gráfica y el mosaico de países.
  Texto sobre cian: `#04121a` (10,5:1). Enlaces y textos cian sobre oscuro: `#5ee6f7`.

### Neutral
- **Noche** (`#070b14`) con dos resplandores lejanos (cian y violeta, 8–10 % de opacidad) y una grilla de 48 px
  al 5 % que se desvanece hacia abajo.
- **Vidrio** (`rgb(15 22 38 / .62)` + `blur(16px) saturate(140%)`, borde de luz fría al 13 %): tarjetas, barra,
  filtros, formulario, muestra y mosaicos. Sin `backdrop-filter`, el vidrio pasa a 86 % de opacidad; con
  `prefers-reduced-transparency`, a superficie opaca.
- **Superficie opaca** (`#0f1626`): celdas fijas de la tabla, menús desplegables, tooltip y controles.
- Tintas `#e8edf7` / `#a9b4c8` / `#8a96ad`.

### Series de datos
Orden fijo: cian, naranja, verde, amarillo, rosa, violeta, gris claro, rojo (claro: `#0891b2`, `#ea580c`,
`#16a34a`, `#e09b00`, `#d6438a`, `#4f46e5`, `#334155`, `#dc2626`). Validado con simulación de protanopía,
deuteranopía y tritanopía: el par más parecido se separa más que en la paleta anterior.

### Named Rules
- **La regla del acento único:** el cian es el único color de interfaz; el resto del color vive en las series.
- **La regla del dato legible:** el brillo nunca reemplaza al contraste; un neón no se usa para texto de lectura
  sobre fondo claro.

## Typography

Geist para todo el texto; Geist Mono para cifras (tabla, ejes, años, valores de la leyenda, tooltip, códigos).
Ambas alojadas en `app/static/fonts` con licencia OFL.

### Hierarchy
- Display de portada 36–56 px, 600, −0,04 em, dos líneas máximo.
- Título de la tarjeta de acceso 24 px; título del panel 20 px; cuerpo 16 px; rótulos 13 px 500 en tinta-2.
- Cifras 13 px en monoespaciada, tabulares; ejes de la gráfica 12 px.

## Layout

Escala de 4 px (`--e-1` a `--e-8`). Panel: ancho máximo 90 rem, filtros en una tarjeta, gráfica y tabla en
tarjetas separadas (la de la tabla toma el ancho de sus columnas). Portada: 5/12 formulario, 7/12 muestra;
debajo de 1024 px el formulario va primero.

## Elevation & Depth

Profundidad por capas: noche, grilla, resplandores, vidrio. Sombras neutras y largas (`0 24px 48px -24px`)
debajo del vidrio; brillo de color solo en tres lugares: líneas de la gráfica (sombra del color de la serie,
más tenue con más de cuatro series), botón principal al pasar o enfocar, y el mosaico de países.

## Shapes

Radios 8 px (controles), 14 px (tarjetas, mosaicos), 18 px (formulario y muestra), 999 px (marcas de serie).

## Components

### Buttons
Principal cian con texto noche, 600, sombra interna clara; al pasar, cian más claro con resplandor. Presionado
`scale(0.97)` (160 ms). Secundario en superficie-2 con borde frío.

### Cards / Containers
Vidrio con borde de luz fría y brillo interno superior. Nunca tarjetas anidadas.

### Inputs / Fields
Superficie opaca, borde `#5d6a85` (3,7:1), foco con borde cian y halo de 3 px.

### Navigation
Barra de vidrio de 56 px: marca con logo cian brillante, botón de tema, avatar con inicial, «Salir».

### Muestra de la portada
Fragmento real del producto (`data-ui`): leyenda con valores en mono, marcas del eje en HTML repartidas sobre
el alto del dibujo, líneas con brillo que se dibujan una vez (`clip-path`, 1,3 s) y números que cuentan
(`portada.js`). Con movimiento reducido: fundido corto, sin trazo ni conteo.

## Do's and Don'ts

### Do:
- Usar el cian solo para acción, foco, selección y la serie 1.
- Poner las cifras en Geist Mono con números tabulares.
- Mantener el color de cada serie igual en ficha, leyenda, gráfica, tooltip y tabla.
- Respetar `prefers-reduced-motion` y `prefers-reduced-transparency`.

### Don't:
- No usar neón como color de texto de párrafos ni de fondos grandes.
- No animar la carga del panel ni repetir entradas en cada cambio de filtro.
- No anidar tarjetas de vidrio ni apilar vidrio claro sobre vidrio claro.
- No volver al azul petróleo con fondo piedra ni al aire de sistema administrativo.
