/* =====================================================================
 * calendario.js — Carica e mostra il calendario dai JSON locali
 * I JSON in data/ sono generati automaticamente da GitHub Actions
 * (scraper/fipav_scraper.py).
 * ===================================================================== */

(function () {
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const tbody  = $("#calendar-body");
  const btnFem = $("#btn-femminile");
  const btnMas = $("#btn-maschile");

  // Icone luogo: HOME quando giochiamo in casa, AWAY quando in trasferta.
  // Sostituibili nel layout HTML (CSS) o cambiando il path qui.
  const ICONA_CASA = "img/home.png";
  const ICONA_TRASFERTA = "img/away.png";

  if (!tbody) return;

  let loading = false;
  let indice = null;

  async function caricaIndice() {
    if (indice) return indice;
    try {
      const res = await fetch("data/campionati.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      indice = await res.json();
    } catch (e) {
      console.warn("[calendario] indice non disponibile:", e);
      indice = { items: [] };
    }
    return indice;
  }

  function slugPerCategoria(cat) {
    const it = (indice?.items || []).find(i => i.categoria === cat);
    return it ? it.slug : null;
  }

  function rigaHTML(p) {
    const giornata = p.giornata || "-";
    const data     = p.data || "-";
    const orario   = p.orario || "";

    // Avversario = la squadra che NON è la nostra
    const avversario      = p.in_casa ? p.ospite      : p.casa;
    const avversario_logo = p.in_casa ? p.ospite_logo : p.casa_logo;

    const icona = p.in_casa ? ICONA_CASA : ICONA_TRASFERTA;
    const alt   = p.in_casa ? "Casa" : "Trasferta";

    const risultato = p.risultato || "-";

    return `
      <tr>
        <td>${giornata}</td>
        <td class="data-cell">${data}${orario ? `\nore ${orario}` : ""}</td>
        <td class="avversario-cell">
          <div class="avv-wrap">
            ${avversario_logo ? `<img src="${avversario_logo}" alt="${avversario}" class="logo-squadra" loading="lazy">` : ""}
            <span>${avversario}</span>
          </div>
        </td>
        <td class="luogo-cell">
          <img src="${icona}" alt="${alt}" class="icon-luogo">
        </td>
        <td>${risultato}</td>
      </tr>
    `;
  }

  async function caricaCalendario(categoria, bottoneAttivo) {
    if (loading) return;
    loading = true;
    tbody.classList.add("table-loading");

    try {
      await caricaIndice();
      const slug = slugPerCategoria(categoria);

      if (!slug) {
        tbody.innerHTML = `<tr><td colspan="5">Nessun calendario ${categoria} disponibile.</td></tr>`;
        return;
      }

      const res  = await fetch(`data/calendario_${slug}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = data.items || [];

      tbody.innerHTML = rows.length
        ? rows.map(rigaHTML).join("")
        : `<tr><td colspan="5">Nessuna partita registrata.</td></tr>`;

      [btnFem, btnMas].forEach(b => b && b.classList.remove("active"));
      if (bottoneAttivo) bottoneAttivo.classList.add("active");

    } catch (err) {
      console.error("[calendario] errore:", err);
      tbody.innerHTML = `<tr><td colspan="5">Impossibile caricare il calendario.</td></tr>`;
    } finally {
      tbody.classList.remove("table-loading");
      if (bottoneAttivo) bottoneAttivo.blur();
      setTimeout(() => { loading = false; }, 150);
    }
  }

  if (btnFem) btnFem.addEventListener("click", () => caricaCalendario("femminile", btnFem));
  if (btnMas) btnMas.addEventListener("click", () => caricaCalendario("maschile",  btnMas));

  document.addEventListener("DOMContentLoaded", async () => {
    await caricaIndice();
    const cat = (new URLSearchParams(location.search).get("cat") || "femminile").toLowerCase();

    const hasMas = slugPerCategoria("maschile");
    if (btnMas && !hasMas) btnMas.style.display = "none";

    if (cat === "maschile" && hasMas && btnMas) {
      caricaCalendario("maschile", btnMas);
    } else if (btnFem) {
      caricaCalendario("femminile", btnFem);
    }
  });
})();
