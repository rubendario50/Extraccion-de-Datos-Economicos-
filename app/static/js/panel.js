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
    ayudaFuente: $("ayuda-fuente"),
    nombreFuente: $("fuente-serie"),
    selector: $("selector-paises"),
    serieFija: $("serie-fija"),
    etiquetaPaises: $("etiqueta-paises"),
    ayudaPaises: $("ayuda-paises"),
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
    marcoTabla: document.querySelector(".tabla-marco"),
  };

  // ---------- Formato de números ----------

  // Marcas del eje: son números redondos, así que alcanza con no redondearlas (hasta 6 cifras significativas).
  const fmtEje = new Intl.NumberFormat("es-UY", { maximumSignificantDigits: 6 });
  let fmtValor = new Intl.NumberFormat("es-UY", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  // Las cotizaciones diarias (dólar del BCU) se publican con 3 decimales; el resto, según su tamaño.
  function elegirFormato(series, frecuencia) {
    let maximo = 0;
    for (const s of series) for (const d of s.datos) if (d.valor != null) maximo = Math.max(maximo, Math.abs(d.valor));
    const decimales = frecuencia === "diaria" ? 3 : maximo < 10 ? 2 : 1;
    fmtValor = new Intl.NumberFormat("es-UY", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  // Valores muy chicos (el IPC de los años 40 vale 0,0000002 en base 2022) con cifras significativas.
  // Siempre 3 cifras (0,00680 y no 0,0068) para que la columna se lea pareja.
  const fmtChico = new Intl.NumberFormat("es-UY", { minimumSignificantDigits: 3, maximumSignificantDigits: 3 });
  const formatear = (v) => (v == null ? "—" : v !== 0 && Math.abs(v) < 0.01 ? fmtChico.format(v) : fmtValor.format(v));

  // Eje vertical. 180000 -> "180 mil" (el sufijo "k" no se usa en español). Los valores muy chicos
  // (el IPC de 1937) van con cifras significativas, como en la tabla: al menos 3 (0,000000160) y las que
  // hagan falta para que marcas vecinas no se lean iguales (0,0000001595 y 0,000000160).
  const fmtChicoEje = new Intl.NumberFormat("es-UY", { minimumSignificantDigits: 3, maximumSignificantDigits: 6 });
  const formatoEje = (v) =>
    Math.abs(v) >= 10000 ? `${fmtEje.format(v / 1000)} mil` : v !== 0 && Math.abs(v) < 0.01 ? fmtChicoEje.format(v) : fmtEje.format(v);

  // ---------- Fechas (series mensuales y diarias de Uruguay) ----------

  // Las series anuales traen `anio`; las mensuales y diarias, `fecha` ISO ("2024-03-01").
  const clave = (d) => d.anio ?? d.fecha;
  const fmtMes = new Intl.DateTimeFormat("es-UY", { month: "short", year: "numeric" });
  const fmtMesLargo = new Intl.DateTimeFormat("es-UY", { month: "long", year: "numeric" });
  const fmtDia = new Intl.DateTimeFormat("es-UY", { day: "2-digit", month: "2-digit", year: "numeric" });
  const fmtMesEje = new Intl.DateTimeFormat("es-UY", { month: "short" });
  const fmtDiaEje = new Intl.DateTimeFormat("es-UY", { day: "numeric", month: "short" });

  // "2024-03-01" -> fecha local (sin corrimiento por zona horaria).
  function aFecha(iso) {
    const [a, m, d] = iso.split("-").map(Number);
    return new Date(a, m - 1, d);
  }

  // Texto de un período para la tabla, el tooltip y la descripción de la gráfica.
  // `c` es un año (series anuales), una fecha ISO o un instante en milisegundos (eje de tiempo).
  function textoPeriodo(c, frecuencia, largo) {
    if (!frecuencia || frecuencia === "anual") return String(c);
    const f = typeof c === "string" ? aFecha(c) : new Date(c);
    if (frecuencia === "mensual") return (largo ? fmtMesLargo : fmtMes).format(f);
    return fmtDia.format(f);
  }

  // Etiquetas del eje de tiempo: el año en enero, si no el mes, y el día si hay zoom.
  function etiquetaEjeTiempo(v) {
    const f = new Date(v);
    if (f.getDate() !== 1) return fmtDiaEje.format(f);
    return f.getMonth() === 0 ? String(f.getFullYear()) : fmtMesEje.format(f).toLowerCase();
  }

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

  // Indicador de Uruguay: una sola serie, sin selector de países.
  function esNacional() {
    const ind = indicadorActual();
    return Boolean(ind && ind.alcance === "nacional");
  }

  function prepararPaises() {
    const nacional = esNacional();
    el.selector.hidden = nacional;
    el.serieFija.hidden = !nacional;
    el.etiquetaPaises.textContent = nacional ? "País" : "Países y regiones";
    el.ayudaPaises.textContent = nacional ? "Los indicadores de Uruguay tienen una sola serie." : `Hasta ${MAX_SERIES} a la vez.`;
    if (nacional) cerrarOpciones();
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
      el.ayudaFuente.hidden = true;
      return;
    }
    if (!ind.fuentes.some((f) => f.codigo === estado.fuente)) estado.fuente = ind.fuente || ind.fuentes[0].codigo;
    for (const f of ind.fuentes) {
      const o = document.createElement("option");
      o.value = f.codigo;
      // Nombre corto en el control (el completo no entra); el completo va debajo de la gráfica.
      const corto = f.corto || f.nombre;
      o.textContent = f.desde == null ? `${corto} (sin datos)` : corto;
      o.title = f.nombre;
      if (f.codigo === estado.fuente) o.selected = true;
      el.fuente.append(o);
    }
    el.fuente.disabled = ind.fuentes.length < 2;
    // Con una sola fuente no hay nada que elegir ni que mezclar.
    el.ayudaFuente.hidden = ind.fuentes.length < 2;
    el.nombreFuente.textContent = `Fuente: ${fuenteActual().nombre}`;
  }

  function leerUrl() {
    const q = new URLSearchParams(location.search);
    if (porCodigoIndicador.has(q.get("indicador"))) estado.indicador = q.get("indicador");
    if (q.get("fuente")) estado.fuente = q.get("fuente").trim().toUpperCase();
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

  // Al cambiar de fuente o de indicador: si un extremo del rango estaba en el borde de la opción
  // anterior (el rango completo), pasa al borde de la nueva en lugar de quedar acotado al viejo.
  function seguirRangoCompleto(anterior) {
    if (!anterior || anterior.desde == null) return;
    if (estado.desde != null && estado.desde <= Math.max(anterior.desde, ANIO_INICIAL_PREFERIDO)) estado.desde = null;
    if (estado.hasta != null && estado.hasta >= anterior.hasta) estado.hasta = null;
  }

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
      li.dataset.codigo = codigo;
      li.innerHTML =
        `<span class="marca-serie" aria-hidden="true"></span>` +
        `<span class="ficha-nombre" title="${escapar(pais.nombre)}">${escapar(pais.nombre)}</span>` +
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
    const anterior = fuenteActual();
    estado.indicador = el.indicador.value;
    prepararFuentes();
    prepararPaises();
    seguirRangoCompleto(anterior);
    prepararAnios();
    pedirSeries();
  });
  el.fuente.addEventListener("change", () => {
    const anterior = fuenteActual();
    estado.fuente = el.fuente.value;
    seguirRangoCompleto(anterior);
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

  // Reemplaza el cuerpo de la tabla (las series mensuales y diarias usan un <tbody> por año).
  function ponerCuerpo(html) {
    [...el.tabla.tBodies].forEach((tb) => tb.remove());
    el.tabla.insertAdjacentHTML("beforeend", html);
  }

  function vaciarTabla(mensaje) {
    el.tabla.tHead.replaceChildren();
    ponerCuerpo(`<tbody><tr><td class="tabla-vacia">${escapar(mensaje)}</td></tr></tbody>`);
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
    if (!estado.paises.length && !esNacional()) {
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
    // Los indicadores nacionales son siempre de Uruguay: no llevan países.
    const q = new URLSearchParams({ indicador: estado.indicador });
    if (!esNacional()) q.set("paises", estado.paises.join(","));
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
  // origenGrafica[k]: índice en la respuesta de la serie k de ECharts (null en la serie auxiliar de la banda).
  let origenGrafica = [];

  // Los dos tramos de un país (real y proyectado) se resaltan juntos: sin esto, al pasar sobre uno, el
  // resaltado de ECharts atenuaría al otro como si fuera otra serie.
  function tramosHermanos(k) {
    const o = origenGrafica[k];
    return o == null ? [] : origenGrafica.flatMap((x, j) => (x === o && j !== k ? [j] : []));
  }

  function crearGrafica() {
    grafica = echarts.init(el.grafica, null, { renderer: "canvas" });
    grafica.on("mouseover", { componentType: "series" }, (e) => {
      const hermanos = tramosHermanos(e.seriesIndex);
      if (hermanos.length) grafica.dispatchAction({ type: "highlight", seriesIndex: [e.seriesIndex, ...hermanos] });
    });
    grafica.on("mouseout", { componentType: "series" }, (e) => {
      const hermanos = tramosHermanos(e.seriesIndex);
      if (hermanos.length) grafica.dispatchAction({ type: "downplay", seriesIndex: [e.seriesIndex, ...hermanos] });
    });
  }

  // "rgb(34 211 238 / 0.12)" -> "rgba(34, 211, 238, 0.12)": ECharts calcula sobre los colores y no lee la sintaxis nueva.
  function normalizarColor(c) {
    const m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*(?:[/,]\s*([\d.]+%?))?\s*\)$/.exec(c);
    if (!m) return c;
    const a = m[4] == null ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : Number(m[4]);
    return `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${a})`;
  }

  function colores() {
    const css = getComputedStyle(document.documentElement);
    const v = (n) => normalizarColor(css.getPropertyValue(n).trim());
    const series = {};
    for (let i = 1; i <= MAX_SERIES; i++) series[i] = v(`--serie-${i}`);
    return {
      series,
      tinta: v("--tinta"),
      tinta2: v("--tinta-2"),
      tinta3: v("--tinta-3"),
      superficie: v("--superficie"),
      superficie2: v("--superficie-2"),
      bordeSuave: v("--borde"),
      grilla: v("--grafica-grilla"),
      eje: v("--grafica-eje"),
      zoom: v("--grafica-zoom"),
      proyeccion: v("--grafica-proyeccion"),
      brillo: v("--grafica-brillo") === "1",
      bordeControl: v("--borde-control"),
      acento: v("--acento"),
      fuente: v("--fuente"),
      cifras: v("--fuente-cifras"),
    };
  }

  // "#2f55e4" -> "rgba(47, 85, 228, a)" (para el relleno suave de la serie única).
  function conAlfa(hex, a) {
    const n = parseInt(hex.replace("#", ""), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  function textoUnidad(indicador) {
    return [indicador.unidad, indicador.escala && indicador.escala !== "Unidades" ? indicador.escala : null]
      .filter(Boolean)
      .join(" · ");
  }

  function nombreCorto(fuente) {
    return { FMI_DM: "El FMI", BM: "El Banco Mundial", INE: "El INE", BCU: "El BCU" }[fuente] || "La fuente";
  }

  const tieneDatos = (s) => s.datos.some((d) => d.valor != null);

  // Por qué una serie vino vacía: la fuente no publica ese país, o no hay datos en los años elegidos.
  // null si tiene datos.
  function motivoVacia(s, cuerpo) {
    if (tieneDatos(s)) return null;
    const ind = porCodigoIndicador.get(cuerpo.indicador.codigo);
    const fte = ind && ind.fuentes.find((f) => f.codigo === cuerpo.fuente);
    return fte && !fte.paises.includes(s.pais) ? "fuente" : "rango";
  }

  const TEXTO_VACIA = { fuente: "sin datos en esta fuente", rango: "sin datos en este rango" };

  // ---------- Proyecciones (FMI) ----------

  // Períodos que la API marca como proyección (solo el FMI las publica). Vacío si no hay ninguno.
  const periodosProyectados = (cuerpo) =>
    new Set(cuerpo.series.flatMap((s) => s.datos.filter((d) => d.proyeccion && d.valor != null).map(clave)));

  // "Proyección del FMI" (o en minúscula, dentro de una oración), con el nombre corto de la fuente.
  function textoProyeccion(cuerpo, minuscula) {
    const fte = indicadorActual()?.fuentes.find((f) => f.codigo === cuerpo.fuente);
    return `${minuscula ? "p" : "P"}royección del ${fte?.corto || cuerpo.fuente}`;
  }

  function pintar(cuerpo) {
    const series = cuerpo.series;
    elegirFormato(series, cuerpo.base == null ? cuerpo.indicador.frecuencia : null);
    el.unidad.textContent = textoUnidad(cuerpo.indicador) + (cuerpo.base != null ? ` · ${cuerpo.base} = 100` : "");

    const conDatos = series.filter(tieneDatos);
    // La ficha de una serie vacía lleva la misma marca que la leyenda (hueca y gris).
    const vaciasCodigos = new Set(series.filter((s) => !tieneDatos(s)).map((s) => s.pais));
    el.fichas.querySelectorAll(".ficha").forEach((f) => f.classList.toggle("ficha-vacia", vaciasCodigos.has(f.dataset.codigo)));
    const vacias = (motivo) => series.filter((s) => motivoVacia(s, cuerpo) === motivo).map((s) => s.nombre);
    const sinFuente = vacias("fuente");
    const sinRango = vacias("rango");
    if (conDatos.length && (sinFuente.length || sinRango.length)) {
      el.faltantes.textContent = [
        sinFuente.length ? `${nombreCorto(cuerpo.fuente)} no publica datos de ${sinFuente.join(", ")}.` : "",
        sinRango.length ? `Sin datos en este rango: ${sinRango.join(", ")}.` : "",
      ].filter(Boolean).join(" ");
      el.faltantes.hidden = false;
    }

    // Años (series anuales) o fechas ISO (mensuales y diarias): en los dos casos el orden natural sirve.
    const anios = [...new Set(series.flatMap((s) => s.datos.map(clave)))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    if (!conDatos.length) {
      if (grafica) grafica.clear();
      const otras = (porCodigoIndicador.get(cuerpo.indicador.codigo)?.fuentes.length || 0) > 1;
      if (sinFuente.length === series.length && esNacional()) {
        mostrarEstado("vacio", "Todavía no hay datos de esta serie", `Todavía no se cargaron datos de ${cuerpo.indicador.nombre}.`);
      } else if (sinFuente.length === series.length) {
        mostrarEstado(
          "vacio",
          "Sin datos en esta fuente",
          `${nombreCorto(cuerpo.fuente)} no publica ${cuerpo.indicador.nombre} para ${series.map((s) => s.nombre).join(", ")}.` +
            (otras ? " Probá con otra fuente." : " Probá con otros países.")
        );
      } else {
        mostrarEstado(
          "vacio",
          "No hay datos en ese rango",
          `${nombreCorto(cuerpo.fuente)} no publica ${cuerpo.indicador.nombre} para ${series.map((s) => s.nombre).join(", ")} entre ${estado.desde} y ${estado.hasta}. Probá con otros años.`
        );
      }
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
    if (!grafica) crearGrafica();
    const vacia = cuerpo.series.map((s) => !tieneDatos(s));
    const pocas = vacia.filter((v) => !v).length <= 4;
    const angosto = el.grafica.clientWidth < 560;
    // Uruguay es una sola serie fija: ni etiqueta al final de la línea ni leyenda (ya la nombra el control).
    const nacional = esNacional();
    const etiquetas = pocas && !angosto && !nacional;
    const slot = (s) => ranuras.get(s.pais) || 1;
    const quieto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Series mensuales y diarias: eje de tiempo con pares [fecha, valor]; las anuales siguen con años.
    const frecuencia = cuerpo.indicador.frecuencia;
    const conFechas = Boolean(frecuencia && frecuencia !== "anual");

    // Proyecciones (solo series anuales del FMI): cada línea se parte en un tramo real y otro punteado, que
    // arranca en el último año real para que la línea siga sin cortes. Detrás, una banda cubre el mismo tramo
    // (así tampoco queda sin ancho cuando el único año proyectado es el último).
    const proyectados = conFechas ? new Set() : periodosProyectados(cuerpo);
    const primerProyectado = anios.find((a) => proyectados.has(a));
    const conProyeccion = primerProyectado !== undefined;
    const iPrimero = anios.indexOf(primerProyectado);
    const inicioBanda = String(anios[Math.max(0, iPrimero - 1)]);
    const etiquetaProyeccion = textoProyeccion(cuerpo);

    const origen = [];
    origenGrafica = origen;
    const series = cuerpo.series.flatMap((s, i) => {
      const valores = new Map(s.datos.map((d) => [clave(d), d.valor]));
      const valor = (a) => (valores.has(a) ? valores.get(a) : null);
      const tramoProyectado = conProyeccion
        ? anios.map((a, j) => (proyectados.has(a) || j === iPrimero - 1 ? valor(a) : null))
        : [];
      const conTramo = tramoProyectado.some((v, j) => v != null && j >= iPrimero);
      const tramo = (data, punteado) => ({
        type: "line",
        name: s.nombre,
        data,
        ...(conFechas ? { sampling: "lttb" } : {}),
        showSymbol: false,
        symbol: "circle",
        symbolSize: 8,
        // En el tema oscuro cada línea lleva un brillo suave de su color (más tenue con muchas series).
        lineStyle: {
          width: 2,
          ...(punteado ? { type: [5, 4] } : {}),
          ...(c.brillo && /^#[0-9a-f]{6}$/i.test(c.series[slot(s)])
            ? { shadowColor: conAlfa(c.series[slot(s)], pocas ? 0.55 : 0.35), shadowBlur: pocas ? 10 : 6 }
            : {}),
        },
        itemStyle: { color: c.series[slot(s)], borderColor: c.superficie, borderWidth: 2 },
        emphasis: { focus: "series", lineStyle: { width: 2.5, opacity: 1 } },
        blur: { lineStyle: { opacity: 0.2 } },
        // La serie única de Uruguay lleva un relleno suave que se desvanece hacia abajo.
        ...(nacional && /^#[0-9a-f]{6}$/i.test(c.series[slot(s)])
          ? {
              areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: conAlfa(c.series[slot(s)], 0.16) },
                  { offset: 1, color: conAlfa(c.series[slot(s)], 0) },
                ]),
              },
            }
          : {}),
        // Una serie sin datos no dibuja etiqueta (si no, queda encimada sobre las otras); con proyección, la
        // etiqueta va al final del tramo punteado.
        endLabel: {
          show: etiquetas && !vacia[i] && punteado === conTramo,
          formatter: "{a}",
          width: 100,
          overflow: "truncate",
          color: c.tinta2,
          fontFamily: c.fuente,
          fontSize: 12,
          distance: 6,
        },
        labelLayout: { moveOverlap: "shiftY" },
      });
      const real = tramo(
        conFechas
          ? s.datos.map((d) => [aFecha(d.fecha).getTime(), d.valor])
          : anios.map((a) => (proyectados.has(a) ? null : valor(a))),
        false
      );
      if (i === 0 && cuerpo.base != null) {
        real.markLine = {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: c.eje, type: [4, 4], width: 1 },
          data: [{ yAxis: 100 }],
        };
      }
      origen.push(i);
      if (!conTramo) return [real];
      origen.push(i);
      return [real, tramo(tramoProyectado, true)];
    });

    if (conProyeccion) {
      // Serie auxiliar invisible, la primera: la banda no depende de que una serie esté visible, y la vista previa
      // del zoom (ECharts la dibuja con la primera serie) muestra la primera serie completa, sin cortarse.
      const primera = new Map(cuerpo.series[0].datos.map((d) => [clave(d), d.valor]));
      origen.unshift(null);
      series.unshift({
        type: "line",
        name: etiquetaProyeccion,
        data: anios.map((a) => (primera.has(a) ? primera.get(a) : null)),
        silent: true,
        showSymbol: false,
        lineStyle: { opacity: 0 },
        emphasis: { disabled: true },
        tooltip: { show: false },
        markArea: {
          silent: true,
          itemStyle: { color: c.proyeccion },
          // La banda no se atenúa al resaltar una serie: marca años, no pertenece a ninguna línea.
          blur: { itemStyle: { opacity: 1 }, label: { opacity: 1 } },
          // Arriba de la banda, alineado a la derecha: no tapa las líneas y no se corta si la banda es angosta.
          label: {
            show: true,
            position: "insideTopRight",
            offset: [0, -22],
            formatter: etiquetaProyeccion,
            color: c.tinta3,
            fontFamily: c.fuente,
            fontSize: 12,
          },
          data: [[{ xAxis: inicioBanda }, { xAxis: String(anios[anios.length - 1]) }]],
        },
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: c.eje, type: [3, 3], width: 1 },
          blur: { lineStyle: { opacity: 1 } },
          data: [{ xAxis: inicioBanda }],
        },
      });
    }

    grafica.setOption(
      {
        animation: !quieto,
        animationDuration: 300,
        animationDurationUpdate: 250,
        animationEasingUpdate: "cubicOut",
        textStyle: { fontFamily: c.fuente, color: c.tinta2 },
        color: origen.map((o) => c.series[o == null ? 1 : slot(cuerpo.series[o])]),
        // Con proyección, más aire arriba para el rótulo de la banda.
        grid: { left: 4, right: etiquetas ? 112 : 12, top: conProyeccion ? 32 : 16, bottom: 64, containLabel: true },
        // La leyenda va en HTML (arriba de la gráfica) para que nunca tape el eje en pantallas angostas.
        legend: { show: false, selected: Object.fromEntries(cuerpo.series.map((s) => [s.nombre, !ocultas.has(s.pais)])) },
        tooltip: {
          trigger: "axis",
          className: "tooltip-grafica",
          backgroundColor: c.superficie,
          borderColor: c.bordeSuave,
          borderWidth: 1,
          padding: [10, 12],
          transitionDuration: 0.15,
          textStyle: { color: c.tinta, fontFamily: c.fuente },
          axisPointer: { type: "line", lineStyle: { color: c.bordeControl, width: 1, type: [3, 3] } },
          formatter: (params) => {
            // Una fila por país: en el último año real se cruzan sus dos tramos (real y proyectado).
            const valores = new Map();
            for (const p of params) {
              const o = origen[p.seriesIndex];
              if (o == null || vacia[o]) continue;
              const valor = Array.isArray(p.value) ? p.value[1] : p.value;
              if (!valores.has(o) || valores.get(o) == null) valores.set(o, valor);
            }
            const filas = [...valores]
              .map(([o, valor]) => {
                const s = cuerpo.series[o];
                return (
                  `<div class="tt-fila"><span class="marca-serie serie-${slot(s)}"></span>` +
                  `<span class="tt-nombre">${escapar(s.nombre)}</span><span class="tt-valor">${formatear(valor)}</span></div>`
                );
              })
              .join("");
            const periodo = conFechas ? textoPeriodo(params[0].axisValue, frecuencia, true) : params[0].axisValue;
            const proyeccion = proyectados.has(Number(params[0].axisValue))
              ? `<span class="tt-proyeccion">${escapar(etiquetaProyeccion)}</span>`
              : "";
            return `<div class="tt"><div class="tt-anio">${escapar(periodo)}${proyeccion}</div>${filas}</div>`;
          },
        },
        xAxis: conFechas
          ? {
              type: "time",
              axisLine: { lineStyle: { color: c.eje } },
              axisTick: { show: false },
              splitLine: { show: false },
              axisLabel: { color: c.tinta3, fontFamily: c.cifras, fontSize: 12, margin: 12, hideOverlap: true, formatter: etiquetaEjeTiempo },
            }
          : {
              type: "category",
              data: anios.map(String),
              boundaryGap: false,
              axisLine: { lineStyle: { color: c.eje } },
              axisTick: { show: false },
              // Con etiquetas de fin de línea, los años de los extremos van hacia adentro para no pisarlas.
              axisLabel: {
                color: c.tinta3,
                fontFamily: c.cifras,
                fontSize: 12,
                margin: 12,
                hideOverlap: true,
                ...(etiquetas ? { alignMinLabel: "left", alignMaxLabel: "right" } : {}),
              },
            },
        yAxis: {
          type: "value",
          // En las series de Uruguay (cotizaciones, tasas) el eje se ajusta a los datos en vez de arrancar en 0.
          scale: conFechas,
          axisLabel: { color: c.tinta3, fontFamily: c.cifras, fontSize: 12, margin: 12, formatter: formatoEje },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: c.grilla } },
        },
        dataZoom: [
          { type: "inside", xAxisIndex: 0, filterMode: "none" },
          {
            type: "slider",
            xAxisIndex: 0,
            filterMode: "none",
            height: 24,
            bottom: 8,
            borderColor: c.bordeSuave,
            borderRadius: 6,
            backgroundColor: c.superficie2,
            fillerColor: c.zoom,
            dataBackground: { lineStyle: { color: c.eje, width: 1 }, areaStyle: { color: c.superficie2, opacity: 0 } },
            selectedDataBackground: { lineStyle: { color: c.acento, width: 1 }, areaStyle: { color: c.zoom } },
            handleIcon: "path://M2,0 L6,0 Q8,0 8,2 L8,22 Q8,24 6,24 L2,24 Q0,24 0,22 L0,2 Q0,0 2,0 Z",
            handleSize: "100%",
            handleStyle: { color: c.superficie, borderColor: c.bordeControl, borderWidth: 1 },
            emphasis: { handleStyle: { borderColor: c.acento } },
            textStyle: { color: c.tinta3, fontFamily: c.cifras, fontSize: 12 },
            ...(conFechas ? { labelFormatter: (v) => textoPeriodo(v, frecuencia) } : {}),
            brushSelect: false,
          },
        ],
        series,
      },
      { notMerge: true }
    );

    if (nacional) el.leyenda.replaceChildren();
    else pintarLeyenda(cuerpo, conProyeccion ? `${etiquetaProyeccion} desde ${primerProyectado}` : null);
    const nombres = cuerpo.series.map((s) => s.nombre).join(", ");
    el.grafica.setAttribute(
      "aria-label",
      `Gráfica de líneas: ${cuerpo.indicador.nombre} de ${nombres}, ${textoPeriodo(anios[0], frecuencia, true)} a ` +
        `${textoPeriodo(anios[anios.length - 1], frecuencia, true)}.` +
        (conProyeccion ? ` Desde ${primerProyectado}, ${textoProyeccion(cuerpo, true)} (línea punteada).` : "") +
        " Los valores están en la tabla."
    );
  }

  // ---------- Leyenda ----------

  // `proyeccion`: texto de la clave del tramo punteado ("Proyección del FMI desde 2026"), o null.
  function pintarLeyenda(cuerpo, proyeccion) {
    el.leyenda.replaceChildren();
    for (const s of cuerpo.series) {
      const li = document.createElement("li");
      const motivo = motivoVacia(s, cuerpo);
      if (motivo) {
        // Sin datos: no hay línea que ocultar, así que no es un botón.
        li.innerHTML =
          `<span class="leyenda-item leyenda-vacia"><span class="leyenda-linea" aria-hidden="true"></span>` +
          `<span>${escapar(s.nombre)} <span class="leyenda-nota">${TEXTO_VACIA[motivo]}</span></span></span>`;
        el.leyenda.append(li);
        continue;
      }
      li.innerHTML =
        `<button type="button" class="leyenda-item serie-${ranuras.get(s.pais) || 1}" data-codigo="${escapar(s.pais)}" ` +
        `data-nombre="${escapar(s.nombre)}" aria-pressed="${!ocultas.has(s.pais)}">` +
        `<span class="leyenda-linea" aria-hidden="true"></span><span>${escapar(s.nombre)}</span></button>`;
      el.leyenda.append(li);
    }
    if (proyeccion) {
      // Clave de la línea punteada y la banda: no es un botón (no hay nada que ocultar).
      const li = document.createElement("li");
      li.className = "leyenda-clave";
      li.innerHTML =
        `<span class="leyenda-item leyenda-proyeccion"><span class="leyenda-linea" aria-hidden="true"></span>` +
        `<span>${escapar(proyeccion)}</span></span>`;
      el.leyenda.append(li);
    }
  }

  el.leyenda.addEventListener("click", (e) => {
    const boton = e.target.closest("button.leyenda-item");
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
    const frecuencia = cuerpo.indicador.frecuencia;
    const primera = { mensual: "Mes", diaria: "Fecha" }[frecuencia] || "Año";
    const cabeza = [`<tr><th scope="col">${primera}</th>`];
    for (const s of cuerpo.series) {
      const motivo = motivoVacia(s, cuerpo);
      cabeza.push(
        `<th scope="col"><span class="encabezado-serie serie-${ranuras.get(s.pais) || 1}${motivo ? " encabezado-vacio" : ""}">` +
          `<span class="marca-serie" aria-hidden="true"></span><span>${escapar(s.nombre)}` +
          (motivo ? `<span class="encabezado-nota">${TEXTO_VACIA[motivo]}</span>` : "") +
          `</span></span></th>`
      );
    }
    cabeza.push("</tr>");
    thead.innerHTML = cabeza.join("");

    const mapas = cuerpo.series.map((s) => new Map(s.datos.map((d) => [clave(d), d.valor])));
    // Años proyectados (FMI): fondo de la banda de la gráfica y «proy.» escrito junto al año, no solo color.
    const proyectados = periodosProyectados(cuerpo);
    const primerProyectado = anios.find((a) => proyectados.has(a));
    const fila = (a) => {
      const celdas = mapas.map((m) => {
        const v = m.get(a);
        return v == null ? '<td class="sin-dato">—</td>' : `<td>${formatear(v)}</td>`;
      });
      const periodo = escapar(textoPeriodo(a, frecuencia));
      if (!proyectados.has(a)) return `<tr><th scope="row">${periodo}</th>${celdas.join("")}</tr>`;
      const clase = a === primerProyectado ? "fila-proyeccion inicio-proyeccion" : "fila-proyeccion";
      return (
        `<tr class="${clase}"><th scope="row">${periodo}<span class="marca-proyeccion" aria-hidden="true">proy.</span>` +
        `<span class="oculto-visual"> (proyección)</span></th>${celdas.join("")}</tr>`
      );
    };
    if (frecuencia === "mensual" || frecuencia === "diaria") {
      // Series largas (miles de cotizaciones): un grupo por año con su año fijo arriba al desplazarse.
      const grupos = [];
      for (const a of anios) {
        const anio = String(a).slice(0, 4);
        if (!grupos.length || grupos[grupos.length - 1].anio !== anio) grupos.push({ anio, filas: [] });
        grupos[grupos.length - 1].filas.push(fila(a));
      }
      ponerCuerpo(
        grupos
          .map((g) =>
            `<tbody><tr class="fila-grupo"><th scope="rowgroup" colspan="${cuerpo.series.length + 1}">${g.anio}</th></tr>` +
            `${g.filas.join("")}</tbody>`)
          .join("")
      );
    } else {
      ponerCuerpo(`<tbody>${anios.map(fila).join("")}</tbody>`);
    }
    medirCabeza();
    el.notaTabla.textContent =
      textoUnidad(cuerpo.indicador) + (cuerpo.base != null ? ` (${cuerpo.base} = 100)` : "") + ". «—»: sin dato." +
      (primerProyectado !== undefined ? ` «proy.»: ${textoProyeccion(cuerpo, true)}, desde ${primerProyectado}.` : "");
  }

  // La fila del año queda fija justo debajo del encabezado, que puede ocupar una o varias líneas.
  function medirCabeza() {
    el.marcoTabla.style.setProperty("--alto-cabeza", `${el.tabla.tHead.offsetHeight}px`);
  }

  // ---------- Arranque ----------

  function alCambiarTema() {
    if (ultimaRespuesta && grafica) pintar(ultimaRespuesta);
  }

  leerUrl();
  el.indicador.value = estado.indicador;
  prepararFuentes();
  prepararPaises();
  prepararAnios();
  pintarFichas();

  document.addEventListener("cambio-tema", alCambiarTema);
  new ResizeObserver(() => grafica && grafica.resize()).observe(el.grafica);
  new ResizeObserver(medirCabeza).observe(el.tabla.tHead);
  // Esperar la fuente para que el canvas no dibuje con la de reserva.
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(cargar);
})();
