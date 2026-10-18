/* Panel de series: controles, gráfica (ECharts) y tabla. Sin build ni dependencias aparte de ECharts. */
"use strict";

(function () {
  const MAX_SERIES = 8;
  const ANIO_INICIAL_PREFERIDO = 1980;
  const datos = JSON.parse(document.getElementById("datos-panel").textContent);
  const porCodigoPais = new Map(datos.paises.map((p) => [p.codigo, p]));
  const porCodigoIndicador = new Map(datos.indicadores.map((i) => [i.codigo, i]));

  const $ = (id) => document.getElementById(id);
  const el = {
    filtros: $("filtros"),
    indicador: $("indicador"),
    fuente: $("fuente"),
    nombreFuente: $("fuente-serie"),
    selector: $("selector-paises"),
    fichas: $("fichas"),
    buscar: $("buscar-pais"),
    opciones: $("opciones-paises"),
    desde: $("desde"),
    hasta: $("hasta"),
    usarBase: $("usar-base"),
    anioBase: $("anio-base"),
    errorAnios: $("error-anios"),
    titulo: $("titulo-serie"),
    unidad: $("unidad-serie"),
    faltantes: $("nota-faltantes"),
    marco: document.querySelector(".grafica-marco"),
    grafica: $("grafica"),
    leyenda: $("leyenda"),
    estado: $("estado"),
    estadoTitulo: $("estado-titulo"),
    estadoTexto: $("estado-texto"),
    reintentar: $("reintentar"),
    notaTabla: $("nota-tabla"),
    tabla: $("tabla"),
  };

  // ---------- Formato de números ----------

  const fmtEje = new Intl.NumberFormat("es-UY", { maximumFractionDigits: 1 });
  let fmtValor = new Intl.NumberFormat("es-UY", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function elegirFormato(series) {
    let maximo = 0;
    for (const s of series) for (const d of s.datos) if (d.valor != null) maximo = Math.max(maximo, Math.abs(d.valor));
    const decimales = maximo < 10 ? 2 : 1;
    fmtValor = new Intl.NumberFormat("es-UY", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  const formatear = (v) => (v == null ? "—" : fmtValor.format(v));

  function escapar(texto) {
    return String(texto).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  const sinTildes = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // ---------- Estado ----------

  const estado = {
    indicador: datos.indicadores.length ? datos.indicadores[0].codigo : "",
    fuente: null,
    paises: [],
    desde: null,
    hasta: null,
    usarBase: false,
    base: null,
  };
  // El color sigue al país: se asigna al agregarlo y no cambia si se quitan otros.
  const ranuras = new Map();
  // Países ocultos con la leyenda (siguen en la tabla).
  const ocultas = new Set();

  function asignarRanura(codigo) {
    if (ranuras.has(codigo)) return;
    const usadas = new Set(ranuras.values());
    for (let i = 1; i <= MAX_SERIES; i++) {
      if (!usadas.has(i)) { ranuras.set(codigo, i); return; }
    }
  }

  function indicadorActual() {
    return porCodigoIndicador.get(estado.indicador);
  }

  // Fuente elegida del indicador actual: años y países con datos de esa fuente.
  function fuenteActual() {
    const ind = indicadorActual();
    if (!ind) return null;
    return ind.fuentes.find((f) => f.codigo === estado.fuente) || null;
  }

  // Arma el selector de fuentes del indicador. Conserva la elegida si el indicador la tiene;
  // si no, usa la fuente por defecto (la primera con datos).
  function prepararFuentes() {
    const ind = indicadorActual();
    el.fuente.replaceChildren();
    if (!ind || !ind.fuentes.length) {
      estado.fuente = null;
      el.fuente.disabled = true;
      return;
    }
    if (!ind.fuentes.some((f) => f.codigo === estado.fuente)) estado.fuente = ind.fuente || ind.fuentes[0].codigo;
    for (const f of ind.fuentes) {
      const o = document.createElement("option");
      o.value = f.codigo;
      o.textContent = f.desde == null ? `${f.nombre} (sin datos)` : f.nombre;
      if (f.codigo === estado.fuente) o.selected = true;
      el.fuente.append(o);
    }
    el.fuente.disabled = ind.fuentes.length < 2;
    el.nombreFuente.textContent = `Fuente: ${fuenteActual().nombre}`;
  }

  function leerUrl() {
    const q = new URLSearchParams(location.search);
    if (porCodigoIndicador.has(q.get("indicador"))) estado.indicador = q.get("indicador");
    if (q.get("fuente")) estado.fuente = q.get("fuente");
    const paises = (q.get("paises") || "").split(",").filter((c) => porCodigoPais.has(c));
    estado.paises = (paises.length ? paises : datos.por_defecto.filter((c) => porCodigoPais.has(c))).slice(0, MAX_SERIES);
    estado.paises.forEach(asignarRanura);
    const num = (n) => (q.has(n) && /^\d{4}$/.test(q.get(n)) ? Number(q.get(n)) : null);
    estado.desde = num("desde");
    estado.hasta = num("hasta");
    estado.base = num("base");
    estado.usarBase = estado.base != null;
  }

  function escribirUrl() {
    const q = new URLSearchParams();
    q.set("indicador", estado.indicador);
    if (estado.fuente) q.set("fuente", estado.fuente);
    q.set("paises", estado.paises.join(","));
    if (estado.desde != null) q.set("desde", estado.desde);
    if (estado.hasta != null) q.set("hasta", estado.hasta);
    if (estado.usarBase && estado.base != null) q.set("base", estado.base);
    history.replaceState(null, "", "?" + q.toString());
  }

  // ---------- Controles de años ----------

  function opcionesAnios(select, desde, hasta, elegido) {
    select.replaceChildren();
    for (let a = desde; a <= hasta; a++) {
      const o = document.createElement("option");
      o.value = String(a);
      o.textContent = String(a);
      if (a === elegido) o.selected = true;
      select.append(o);
    }
  }

  const acotar = (v, min, max) => Math.min(Math.max(v, min), max);

  function prepararAnios() {
    const ind = fuenteActual();
    if (!ind || ind.desde == null) {
      [el.desde, el.hasta, el.anioBase].forEach((s) => { s.replaceChildren(); s.disabled = true; });
      return;
    }
    const min = ind.desde, max = ind.hasta;
    estado.desde = acotar(estado.desde ?? Math.max(min, ANIO_INICIAL_PREFERIDO), min, max);
    estado.hasta = acotar(estado.hasta ?? max, min, max);
    estado.base = acotar(estado.base ?? acotar(2000, min, max), min, max);
    el.desde.disabled = el.hasta.disabled = false;
    opcionesAnios(el.desde, min, max, estado.desde);
    opcionesAnios(el.hasta, min, max, estado.hasta);
    opcionesAnios(el.anioBase, min, max, estado.base);
    el.usarBase.checked = estado.usarBase;
    el.anioBase.disabled = !estado.usarBase;
  }

  function aniosValidos() {
    const ok = estado.desde == null || estado.hasta == null || estado.desde <= estado.hasta;
    el.errorAnios.hidden = ok;
    el.errorAnios.textContent = ok ? "" : "El año «Desde» no puede ser posterior al año «Hasta».";
    el.desde.setAttribute("aria-invalid", String(!ok));
    el.hasta.setAttribute("aria-invalid", String(!ok));
    return ok;
  }

  // ---------- Selector de países ----------

  const ICONO_QUITAR =
    '<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M2.5 2.5l7 7m0-7l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function pintarFichas() {
    el.fichas.replaceChildren();
    for (const codigo of estado.paises) {
      const pais = porCodigoPais.get(codigo);
      const li = document.createElement("li");
      li.className = `ficha serie-${ranuras.get(codigo)}`;
      li.innerHTML =
        `<span class="marca-serie" aria-hidden="true"></span>` +
        `<span class="ficha-nombre">${escapar(pais.nombre)}</span>` +
        `<button type="button" class="ficha-quitar" data-codigo="${escapar(codigo)}" aria-label="Quitar ${escapar(pais.nombre)}">${ICONO_QUITAR}</button>`;
      el.fichas.append(li);
    }
    el.buscar.placeholder = estado.paises.length ? "Agregar…" : "Buscar país o región…";
  }

  let activa = -1;
  let resultados = [];

  function buscarPaises(texto) {
    const fte = fuenteActual();
    const conDatos = new Set(fte ? fte.paises : []);
    const q = sinTildes(texto.trim());
    const elegidos = new Set(estado.paises);
    const lista = datos.paises.filter((p) => conDatos.has(p.codigo) && !elegidos.has(p.codigo));
    if (!q) return lista.sort((a, b) => a.agregado - b.agregado || a.nombre.localeCompare(b.nombre, "es"));
    return lista
      .map((p) => {
        const n = sinTildes(p.nombre);
        const rango = n.startsWith(q) ? 0 : n.includes(" " + q) ? 1 : n.includes(q) || sinTildes(p.codigo) === q ? 2 : -1;
        return [rango, p];
      })
      .filter(([r]) => r >= 0)
      .sort((a, b) => a[0] - b[0] || a[1].agregado - b[1].agregado || a[1].nombre.localeCompare(b[1].nombre, "es"))
      .map(([, p]) => p);
  }

  function abrirOpciones() {
    resultados = estado.paises.length >= MAX_SERIES ? [] : buscarPaises(el.buscar.value).slice(0, 80);
    activa = resultados.length && el.buscar.value.trim() ? 0 : -1;
    el.opciones.replaceChildren();
    if (estado.paises.length >= MAX_SERIES) {
      el.opciones.innerHTML = `<li class="opcion-vacia" role="presentation">Ya elegiste ${MAX_SERIES}. Quitá uno para agregar otro.</li>`;
    } else if (!resultados.length) {
      el.opciones.innerHTML = '<li class="opcion-vacia" role="presentation">No hay países con datos que coincidan.</li>';
    }
    resultados.forEach((p, i) => {
      const li = document.createElement("li");
      li.className = "opcion";
      li.id = `opcion-${i}`;
      li.setAttribute("role", "option");
      li.dataset.codigo = p.codigo;
      li.innerHTML = `<span>${escapar(p.nombre)}</span>${p.agregado ? '<span class="opcion-tipo">Región</span>' : ""}`;
      el.opciones.append(li);
    });
    el.opciones.hidden = false;
    el.buscar.setAttribute("aria-expanded", "true");
    marcarActiva();
  }

  function cerrarOpciones() {
    el.opciones.hidden = true;
    el.buscar.setAttribute("aria-expanded", "false");
    el.buscar.removeAttribute("aria-activedescendant");
    activa = -1;
  }

  function marcarActiva() {
    el.opciones.querySelectorAll(".opcion").forEach((li, i) => li.setAttribute("aria-selected", String(i === activa)));
    if (activa >= 0) {
      const li = $(`opcion-${activa}`);
      el.buscar.setAttribute("aria-activedescendant", li.id);
      li.scrollIntoView({ block: "nearest" });
    } else {
      el.buscar.removeAttribute("aria-activedescendant");
    }
  }

  function agregarPais(codigo) {
    if (estado.paises.includes(codigo) || estado.paises.length >= MAX_SERIES) return;
    estado.paises.push(codigo);
    asignarRanura(codigo);
    el.buscar.value = "";
    pintarFichas();
    abrirOpciones();
    pedirSeries();
  }

  function quitarPais(codigo) {
    estado.paises = estado.paises.filter((c) => c !== codigo);
    ranuras.delete(codigo);
    ocultas.delete(codigo);
    pintarFichas();
    pedirSeries();
  }

  el.selector.addEventListener("click", (e) => {
    const quitar = e.target.closest(".ficha-quitar");
    if (quitar) {
      quitarPais(quitar.dataset.codigo);
      el.buscar.focus();
    } else if (!e.target.closest(".opciones")) {
      el.buscar.focus();
    }
  });
  el.buscar.addEventListener("focus", abrirOpciones);
  el.buscar.addEventListener("input", abrirOpciones);
  el.buscar.addEventListener("blur", () => setTimeout(cerrarOpciones, 120));
  el.buscar.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (el.opciones.hidden) abrirOpciones();
      if (!resultados.length) return;
      const paso = e.key === "ArrowDown" ? 1 : -1;
      activa = (activa + paso + resultados.length) % resultados.length;
      marcarActiva();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activa >= 0 && resultados[activa]) agregarPais(resultados[activa].codigo);
    } else if (e.key === "Escape") {
      cerrarOpciones();
    } else if (e.key === "Backspace" && !el.buscar.value && estado.paises.length) {
      quitarPais(estado.paises[estado.paises.length - 1]);
    }
  });
  el.opciones.addEventListener("mousedown", (e) => e.preventDefault()); // no perder el foco
  el.opciones.addEventListener("click", (e) => {
    const li = e.target.closest(".opcion");
    if (li) agregarPais(li.dataset.codigo);
  });

  // ---------- Resto de los controles ----------

  el.filtros.addEventListener("submit", (e) => e.preventDefault());
  el.indicador.addEventListener("change", () => {
    estado.indicador = el.indicador.value;
    prepararFuentes();
    prepararAnios();
    pedirSeries();
  });
  el.fuente.addEventListener("change", () => {
    estado.fuente = el.fuente.value;
    el.nombreFuente.textContent = `Fuente: ${fuenteActual().nombre}`;
    prepararAnios();
    pedirSeries();
  });
  el.desde.addEventListener("change", () => { estado.desde = Number(el.desde.value); pedirSeries(); });
  el.hasta.addEventListener("change", () => { estado.hasta = Number(el.hasta.value); pedirSeries(); });
  el.usarBase.addEventListener("change", () => {
    estado.usarBase = el.usarBase.checked;
    el.anioBase.disabled = !estado.usarBase;
    pedirSeries();
  });
  el.anioBase.addEventListener("change", () => { estado.base = Number(el.anioBase.value); pedirSeries(); });
  el.reintentar.addEventListener("click", () => pedirSeries());

  // ---------- Estados de la gráfica ----------

  function mostrarEstado(tipo, titulo, texto, reintentar) {
    el.marco.removeAttribute("aria-busy");
    if (tipo !== "cargando") el.leyenda.replaceChildren();
    el.estado.hidden = false;
    el.estado.className = `estado estado-${tipo}`;
    el.estadoTitulo.textContent = titulo;
    el.estadoTexto.textContent = texto || "";
    el.estadoTexto.hidden = !texto;
    el.reintentar.hidden = !reintentar;
  }

  function ocultarEstado() {
    el.estado.hidden = true;
    el.marco.removeAttribute("aria-busy");
  }

  function vaciarTabla(mensaje) {
    el.tabla.tHead.replaceChildren();
    el.tabla.tBodies[0].innerHTML = `<tr><td class="tabla-vacia">${escapar(mensaje)}</td></tr>`;
    el.notaTabla.textContent = "";
  }

  // ---------- Pedido a la API ----------

  let pedidoEnCurso = null;
  let temporizador = null;
  let ultimaRespuesta = null;

  function pedirSeries() {
    clearTimeout(temporizador);
    temporizador = setTimeout(cargar, 120);
  }

  async function cargar() {
    escribirUrl();
    const ind = indicadorActual();
    el.titulo.textContent = ind ? ind.nombre : "Sin indicadores";
    el.faltantes.hidden = true;
    if (!ind) {
      mostrarEstado("vacio", "Todavía no hay indicadores cargados", "Cargá las semillas y los datos del FMI y del Banco Mundial para empezar.");
      return;
    }
    if (!estado.paises.length) {
      grafica && grafica.clear();
      ultimaRespuesta = null;
      el.unidad.textContent = "";
      mostrarEstado("vacio", "Elegí al menos un país", "Usá el buscador de «Países y regiones» para agregar los que quieras comparar.");
      vaciarTabla("Sin países elegidos.");
      return;
    }
    if (!aniosValidos()) {
      mostrarEstado("error", "Revisá el rango de años", "El año «Desde» no puede ser posterior al año «Hasta».");
      return;
    }

    if (pedidoEnCurso) pedidoEnCurso.abort();
    const control = new AbortController();
    pedidoEnCurso = control;
    const q = new URLSearchParams({ indicador: estado.indicador, paises: estado.paises.join(",") });
    if (estado.fuente) q.set("fuente", estado.fuente);
    if (estado.desde != null) q.set("desde", estado.desde);
    if (estado.hasta != null) q.set("hasta", estado.hasta);
    if (estado.usarBase && estado.base != null) q.set("base", estado.base);

    el.marco.setAttribute("aria-busy", "true");
    if (!ultimaRespuesta) mostrarEstado("cargando", "Cargando datos…", "");

    let respuesta;
    try {
      respuesta = await fetch(`/api/series?${q}`, { headers: { Accept: "application/json" }, signal: control.signal });
    } catch (err) {
      if (err.name === "AbortError") return;
      mostrarEstado("error", "No se pudo conectar con el servidor", "Revisá tu conexión y probá de nuevo.", true);
      return;
    }
    if (control !== pedidoEnCurso) return;
    pedidoEnCurso = null;

    if (respuesta.status === 401) {
      location.assign("/login");
      return;
    }
    let cuerpo = null;
    try { cuerpo = await respuesta.json(); } catch (_) { /* cuerpo no JSON */ }
    if (!respuesta.ok) {
      const detalle = cuerpo && typeof cuerpo.detail === "string" ? cuerpo.detail : "";
      if (estado.usarBase && /año base/.test(detalle)) {
        mostrarEstado("error", "No se puede calcular el índice con ese año base", `${detalle} Elegí otro año base.`);
      } else {
        mostrarEstado("error", "No se pudieron cargar los datos", detalle || `El servidor respondió con el error ${respuesta.status}.`, true);
      }
      vaciarTabla("Sin datos para mostrar.");
      return;
    }
    ultimaRespuesta = cuerpo;
    pintar(cuerpo);
  }

  // ---------- Gráfica ----------

  let grafica = null;

  function colores() {
    const css = getComputedStyle(document.documentElement);
    const v = (n) => css.getPropertyValue(n).trim();
    const series = {};
    for (let i = 1; i <= MAX_SERIES; i++) series[i] = v(`--serie-${i}`);
    return {
      series,
      tinta: v("--tinta"),
      tinta2: v("--tinta-2"),
      tinta3: v("--tinta-3"),
      superficie: v("--superficie"),
      superficie2: v("--superficie-2"),
      bordeSuave: v("--borde-suave"),
      grilla: v("--grafica-grilla"),
      eje: v("--grafica-eje"),
      acento: v("--acento"),
      fuente: v("--fuente"),
    };
  }

  function textoUnidad(indicador) {
    return [indicador.unidad, indicador.escala && indicador.escala !== "Unidades" ? indicador.escala : null]
      .filter(Boolean)
      .join(" · ");
  }

  function nombreCorto(fuente) {
    return { FMI_DM: "El FMI", BM: "El Banco Mundial" }[fuente] || "La fuente";
  }

  function pintar(cuerpo) {
    const series = cuerpo.series;
    elegirFormato(series);
    el.unidad.textContent = textoUnidad(cuerpo.indicador) + (cuerpo.base != null ? ` · ${cuerpo.base} = 100` : "");

    const sinDatos = series.filter((s) => !s.datos.some((d) => d.valor != null)).map((s) => s.nombre);
    const conDatos = series.filter((s) => s.datos.some((d) => d.valor != null));
    if (sinDatos.length && conDatos.length) {
      el.faltantes.textContent = `Sin datos en este rango: ${sinDatos.join(", ")}.`;
      el.faltantes.hidden = false;
    }

    const anios = [...new Set(series.flatMap((s) => s.datos.map((d) => d.anio)))].sort((a, b) => a - b);
    if (!conDatos.length) {
      if (grafica) grafica.clear();
      mostrarEstado(
        "vacio",
        "No hay datos en ese rango",
        `${nombreCorto(cuerpo.fuente)} no publica ${cuerpo.indicador.nombre.toLowerCase()} para ${series.map((s) => s.nombre).join(", ")} entre ${estado.desde} y ${estado.hasta}. Probá con otros años.`
      );
      vaciarTabla("Sin datos para mostrar.");
      return;
    }
    ocultarEstado();
    pintarGrafica(cuerpo, anios);
    pintarTabla(cuerpo, anios);
  }

  function pintarGrafica(cuerpo, anios) {
    if (!window.echarts) {
      mostrarEstado("error", "No se pudo cargar la gráfica", "Recargá la página. La tabla de abajo tiene los valores.", false);
      return;
    }
    const c = colores();
    if (!grafica) grafica = echarts.init(el.grafica, null, { renderer: "canvas" });
    const pocas = cuerpo.series.length <= 4;
    const angosto = el.grafica.clientWidth < 560;
    const slot = (s) => ranuras.get(s.pais) || 1;

    const series = cuerpo.series.map((s, i) => {
      const valores = new Map(s.datos.map((d) => [d.anio, d.valor]));
      const serie = {
        type: "line",
        name: s.nombre,
        data: anios.map((a) => (valores.has(a) ? valores.get(a) : null)),
        showSymbol: false,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { width: 2 },
        itemStyle: { color: c.series[slot(s)], borderColor: c.superficie, borderWidth: 2 },
        emphasis: { focus: "series", lineStyle: { width: 2.5 } },
        blur: { lineStyle: { opacity: 0.25 } },
        endLabel: {
          show: pocas && !angosto,
          formatter: "{a}",
          color: c.tinta2,
          fontFamily: c.fuente,
          fontSize: 12,
          distance: 6,
        },
        labelLayout: { moveOverlap: "shiftY" },
      };
      if (i === 0 && cuerpo.base != null) {
        serie.markLine = {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: c.eje, type: [4, 4], width: 1 },
          data: [{ yAxis: 100 }],
        };
      }
      return serie;
    });

    // 180000 -> "180 mil" (el sufijo "k" no se usa en español).
    const formatoEje = (v) => (Math.abs(v) >= 10000 ? `${fmtEje.format(v / 1000)} mil` : fmtEje.format(v));

    grafica.setOption(
      {
        animationDuration: 300,
        animationDurationUpdate: 250,
        animationEasingUpdate: "cubicOut",
        textStyle: { fontFamily: c.fuente, color: c.tinta2 },
        color: cuerpo.series.map((s) => c.series[slot(s)]),
        grid: { left: 8, right: pocas && !angosto ? 112 : 16, top: 16, bottom: 64, containLabel: true },
        // La leyenda va en HTML (arriba de la gráfica) para que nunca tape el eje en pantallas angostas.
        legend: { show: false, selected: Object.fromEntries(cuerpo.series.map((s) => [s.nombre, !ocultas.has(s.pais)])) },
        tooltip: {
          trigger: "axis",
          className: "tooltip-grafica",
          backgroundColor: c.superficie,
          borderColor: c.bordeSuave,
          borderWidth: 1,
          padding: [8, 12],
          textStyle: { color: c.tinta, fontFamily: c.fuente },
          axisPointer: { type: "line", lineStyle: { color: c.eje, width: 1 } },
          formatter: (params) => {
            const filas = params
              .map((p) => {
                const s = cuerpo.series[p.seriesIndex];
                return (
                  `<div class="tt-fila"><span class="marca-serie serie-${slot(s)}"></span>` +
                  `<span class="tt-nombre">${escapar(s.nombre)}</span><span class="tt-valor">${formatear(p.value)}</span></div>`
                );
              })
              .join("");
            return `<div class="tt"><div class="tt-anio">${escapar(params[0].axisValue)}</div>${filas}</div>`;
          },
        },
        xAxis: {
          type: "category",
          data: anios.map(String),
          boundaryGap: false,
          axisLine: { lineStyle: { color: c.eje } },
          axisTick: { show: false },
          axisLabel: { color: c.tinta3, fontSize: 12, hideOverlap: true },
        },
        yAxis: {
          type: "value",
          axisLabel: { color: c.tinta3, fontSize: 12, formatter: formatoEje },
          splitLine: { lineStyle: { color: c.grilla } },
        },
        dataZoom: [
          { type: "inside", xAxisIndex: 0, filterMode: "none" },
          {
            type: "slider",
            xAxisIndex: 0,
            filterMode: "none",
            height: 22,
            bottom: 8,
            borderColor: c.bordeSuave,
            backgroundColor: c.superficie,
            fillerColor: "rgba(127, 140, 150, 0.16)",
            dataBackground: { lineStyle: { color: c.eje, width: 1 }, areaStyle: { color: c.superficie2 } },
            selectedDataBackground: { lineStyle: { color: c.acento, width: 1 }, areaStyle: { color: c.superficie2 } },
            handleStyle: { color: c.superficie, borderColor: c.eje },
            moveHandleStyle: { color: c.superficie2, borderColor: c.eje },
            emphasis: { handleStyle: { borderColor: c.acento }, moveHandleStyle: { color: c.eje } },
            textStyle: { color: c.tinta3, fontFamily: c.fuente, fontSize: 11 },
            brushSelect: false,
          },
        ],
        series,
      },
      { notMerge: true }
    );

    pintarLeyenda(cuerpo);
    const nombres = cuerpo.series.map((s) => s.nombre).join(", ");
    el.grafica.setAttribute(
      "aria-label",
      `Gráfica de líneas: ${cuerpo.indicador.nombre} de ${nombres}, ${anios[0]} a ${anios[anios.length - 1]}. Los valores están en la tabla.`
    );
  }

  // ---------- Leyenda ----------

  function pintarLeyenda(cuerpo) {
    el.leyenda.replaceChildren();
    for (const s of cuerpo.series) {
      const li = document.createElement("li");
      li.innerHTML =
        `<button type="button" class="leyenda-item serie-${ranuras.get(s.pais) || 1}" data-codigo="${escapar(s.pais)}" ` +
        `data-nombre="${escapar(s.nombre)}" aria-pressed="${!ocultas.has(s.pais)}">` +
        `<span class="leyenda-linea" aria-hidden="true"></span>${escapar(s.nombre)}</button>`;
      el.leyenda.append(li);
    }
  }

  el.leyenda.addEventListener("click", (e) => {
    const boton = e.target.closest(".leyenda-item");
    if (!boton || !grafica) return;
    const codigo = boton.dataset.codigo;
    if (ocultas.has(codigo)) ocultas.delete(codigo);
    else ocultas.add(codigo);
    boton.setAttribute("aria-pressed", String(!ocultas.has(codigo)));
    grafica.dispatchAction({ type: "legendToggleSelect", name: boton.dataset.nombre });
  });

  // ---------- Tabla ----------

  function pintarTabla(cuerpo, anios) {
    const thead = el.tabla.tHead;
    const tbody = el.tabla.tBodies[0];
    const cabeza = ['<tr><th scope="col">Año</th>'];
    for (const s of cuerpo.series) {
      cabeza.push(
        `<th scope="col"><span class="encabezado-serie serie-${ranuras.get(s.pais) || 1}">` +
          `<span class="marca-serie" aria-hidden="true"></span>${escapar(s.nombre)}</span></th>`
      );
    }
    cabeza.push("</tr>");
    thead.innerHTML = cabeza.join("");

    const mapas = cuerpo.series.map((s) => new Map(s.datos.map((d) => [d.anio, d.valor])));
    const filas = anios.map((a) => {
      const celdas = mapas.map((m) => {
        const v = m.get(a);
        return v == null ? '<td class="sin-dato">—</td>' : `<td>${formatear(v)}</td>`;
      });
      return `<tr><th scope="row">${a}</th>${celdas.join("")}</tr>`;
    });
    tbody.innerHTML = filas.join("");
    el.notaTabla.textContent = textoUnidad(cuerpo.indicador) + (cuerpo.base != null ? ` (${cuerpo.base} = 100)` : "") + ". «—»: sin dato.";
  }

  // ---------- Arranque ----------

  function alCambiarTema() {
    if (ultimaRespuesta && grafica) pintar(ultimaRespuesta);
  }

  leerUrl();
  el.indicador.value = estado.indicador;
  prepararFuentes();
  prepararAnios();
  pintarFichas();

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", alCambiarTema);
  new ResizeObserver(() => grafica && grafica.resize()).observe(el.grafica);
  // Esperar la fuente para que el canvas no dibuje con la de reserva.
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(cargar);
})();
