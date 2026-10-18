/* Tema: la identidad es oscura; el claro es una alternativa que la persona elige y queda recordada.
   Se carga en el <head> (sin defer) para que la página no parpadee al abrir con el tema claro. */
"use strict";

(function () {
  const raiz = document.documentElement;
  let guardado = null;
  try { guardado = localStorage.getItem("tema"); } catch (_) { /* almacenamiento bloqueado */ }
  raiz.dataset.tema = guardado === "claro" ? "claro" : "oscuro";

  function actualizarBotones() {
    const claro = raiz.dataset.tema === "claro";
    document.querySelectorAll("[data-cambiar-tema]").forEach((b) => b.setAttribute("aria-pressed", String(claro)));
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-cambiar-tema]")) return;
    raiz.dataset.tema = raiz.dataset.tema === "claro" ? "oscuro" : "claro";
    try { localStorage.setItem("tema", raiz.dataset.tema); } catch (_) { /* sin almacenamiento: vale para esta página */ }
    actualizarBotones();
    document.dispatchEvent(new CustomEvent("cambio-tema"));
  });
  document.addEventListener("DOMContentLoaded", actualizarBotones);
})();
