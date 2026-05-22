/* =====================================================================
 * classifiche.js — Carica e mostra le classifiche dai JSON locali
 * I JSON in data/ sono generati automaticamente da GitHub Actions
 * (scraper/fipav_scraper.py).
 * ===================================================================== */

(function () {
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const tbody  = $("#tabella-classifica");
  const btnFem = $("#btn-femminile");
  const btnMas = $("#btn-maschile");

  if (!tbody) return;

  let loading = false;

  // ─── Carica indice campionati e mappa i bottoni ai file giusti ─────
  let indice = null;
  async function caricaIndice() {
    if (indice) return indice;
    try {
      const res = await fetch("data/campionati.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      indice = await res.json();
    } catch (e) {
      console.warn("[classifiche] indice non disponibile, uso fallback:", e);
      indice = { items: [] };
    }
    return indice;
  }

  // Restituisce lo slug del campionato che matcha una categoria.
  // Se ce ne sono più (es. più gironi futuri) prende il primo.
  function slugPerCategoria(cat) {
    const it = (indice?.items || []).find(i => i.categoria === cat);
    return it ? it.slug : null;
  }

  async function caricaClassifica(categoria, bottoneAttivo) {
    if (loading) return;
    loading = true;
    tbody.classList.add("table-loading");

    try {
      await caricaIndice();
      const slug = slugPerCategoria(categoria);

      if (!slug) {
        tbody.innerHTML = `<tr><td colspan="6">Nessuna classifica ${categoria} disponibile in questo momento.</td></tr>`;
        return;
      }

      const res  = await fetch(`data/classifica_${slug}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = data.items || [];

      const frag = document.createDocumentFragment();
      rows.forEach(r => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${r.posizione ?? "-"}</td>
          <td class="squadra-cell team-cell">
            ${r.logo ? `<img src="${r.logo}" alt="Logo ${r.nome || ""}" class="logo-squadra" loading="lazy">` : ""}
            <span class="team-name">${r.nome || ""}</span>
          </td>
          <td>${r.punti ?? "-"}</td>
          <td>${r.partite_giocate ?? "-"}</td>
          <td>${r.vittorie ?? "-"}</td>
          <td>${r.sconfitte ?? "-"}</td>
        `;
        frag.appendChild(tr);
      });
      tbody.replaceChildren(frag);

      // Aggiorno stato bottoni
      [btnFem, btnMas].forEach(b => b && b.classList.remove("active"));
      if (bottoneAttivo) bottoneAttivo.classList.add("active");

    } catch (err) {
      console.error("[classifiche] errore:", err);
      tbody.innerHTML = `<tr><td colspan="6">Impossibile caricare la classifica.</td></tr>`;
    } finally {
      tbody.classList.remove("table-loading");
      if (bottoneAttivo) bottoneAttivo.blur();   // rilascia stato :active su iOS
      setTimeout(() => { loading = false; }, 150);
    }
  }

  // ─── Wire-up bottoni ───────────────────────────────────────────────
  if (btnFem) btnFem.addEventListener("click", () => caricaClassifica("femminile", btnFem));
  if (btnMas) btnMas.addEventListener("click", () => caricaClassifica("maschile",  btnMas));

  // ─── Init: ?cat=Femminile|Maschile, default femminile ──────────────
  document.addEventListener("DOMContentLoaded", async () => {
    await caricaIndice();
    const cat = (new URLSearchParams(location.search).get("cat") || "femminile").toLowerCase();

    // Nasconde il bottone Maschile se non c'è un campionato maschile attivo
    const hasMas = slugPerCategoria("maschile");
    if (btnMas && !hasMas) btnMas.style.display = "none";

    if (cat === "maschile" && hasMas && btnMas) {
      caricaClassifica("maschile", btnMas);
    } else if (btnFem) {
      caricaClassifica("femminile", btnFem);
    }
  });
})();
