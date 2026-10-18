/* Portada: los números de la muestra cuentan hasta su valor una vez, al abrir.
   El valor final ya está en el HTML: sin JavaScript, o con movimiento reducido, se ve quieto. */
"use strict";

(function () {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const fmt = new Intl.NumberFormat("es-UY", { maximumFractionDigits: 0, useGrouping: "always" });
  const DURACION = 1100;
  const salida = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

  document.querySelectorAll(".muestra-leyenda strong, [data-contar]").forEach((el, i) => {
    const final = Number(el.textContent.replace(/\./g, "").trim());
    if (!Number.isFinite(final) || final <= 0) return;
    const espera = 450 + i * 40;
    let inicio = null;
    el.textContent = "0";
    function paso(ahora) {
      if (inicio === null) inicio = ahora + espera;
      const t = Math.max(0, (ahora - inicio) / DURACION);
      el.textContent = fmt.format(Math.round(final * salida(t)));
      if (t < 1) requestAnimationFrame(paso);
      else el.textContent = fmt.format(final);
    }
    requestAnimationFrame(paso);
  });
})();
