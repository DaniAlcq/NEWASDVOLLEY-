/* =====================================================================
 * menu.js — Logica del menu hamburger (mobile)
 * Nessuna duplicazione con live.js (che gestisce il bottone Live).
 * ===================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  const hamburger = document.getElementById("hamburger");
  const navbar    = document.getElementById("navbar");

  if (!hamburger || !navbar) {
    console.warn("[menu] hamburger o navbar non trovati");
    return;
  }

  const open = () => {
    navbar.classList.add("active");
    hamburger.setAttribute("aria-expanded", "true");
    document.body.classList.add("nav-open");
  };

  const close = () => {
    navbar.classList.remove("active");
    hamburger.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
  };

  const toggle = (e) => {
    e.stopPropagation();
    navbar.classList.contains("active") ? close() : open();
  };

  // Apri/chiudi col tap. Un solo listener "click" basta:
  // iOS lo emette anche per il touch, evitiamo il double-fire di touchstart+click.
  hamburger.addEventListener("click", toggle);

  // Chiudi cliccando fuori
  document.addEventListener("click", (e) => {
    if (navbar.classList.contains("active") &&
        !navbar.contains(e.target) &&
        !hamburger.contains(e.target)) {
      close();
    }
  });

  // Evita propagazione click interni al menu
  navbar.addEventListener("click", (e) => e.stopPropagation());

  // Chiudi quando selezioni una voce
  navbar.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", () => close());
  });

  // Chiudi con ESC
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });

  // Evidenzia voce di menu attiva (file corrente)
  const current = (location.pathname.split("/").pop() || "index.html");
  navbar.querySelectorAll("a").forEach((a) => {
    const target = (a.dataset.url || a.getAttribute("href") || "").split("/").pop();
    a.classList.toggle("active", target === current);
  });
});
