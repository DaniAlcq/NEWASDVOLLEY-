/* =====================================================================
 * live.js — Bottone "Guarda la diretta"
 * Legge da Google Sheets (tab 'Diretta') se la diretta è ON e l'URL.
 * Si nasconde se off; apre il link in nuova tab se on.
 * ===================================================================== */

(function () {
  const SHEET_ID = "1ucM1JY5MXHF7-9mpjp2mfB41TvoA1ziMUGGz86woQXA";
  const GS = (tab) => `https://opensheet.elk.sh/${SHEET_ID}/${encodeURIComponent(tab)}`;
  const FALLBACK = "https://www.youtube.com/@ASD_VOLLEY96/live";
  const URL_KEYS = ["youtube_url", "url", "link", "youtube", "live_url", "YouTube", "YouTube_URL"];

  const btn = document.getElementById("live-button");
  if (!btn) return;

  let liveURL = FALLBACK;

  const pickUrl = (row) => {
    for (const k of URL_KEYS) {
      const v = row?.[k];
      if (v && String(v).trim()) return String(v).trim();
    }
    return FALLBACK;
  };

  const isHttpUrl = (s) => /^https?:\/\//i.test(s);

  async function refresh() {
    try {
      const res = await fetch(GS("Diretta"), { cache: "no-store" });
      const rows = res.ok ? await res.json() : [];
      const r = rows[0] || {};
      const flag = String((r.live || "").trim().toLowerCase());
      const on = /^(si|1|true|on|live)$/i.test(flag);

      liveURL = pickUrl(r);
      if (!isHttpUrl(liveURL)) liveURL = FALLBACK;

      btn.href = liveURL;
      btn.classList.toggle("live-hidden", !on);
    } catch {
      btn.classList.add("live-hidden");
      liveURL = FALLBACK;
      btn.href = liveURL;
    }
  }

  // Apri in nuova tab anche se l'href fosse stato resettato
  btn.addEventListener("click", (e) => {
    if (btn.classList.contains("live-hidden")) { e.preventDefault(); return; }
    if (!isHttpUrl(liveURL)) liveURL = FALLBACK;
    window.open(liveURL, "_blank", "noopener");
    e.preventDefault();
  });

  document.addEventListener("DOMContentLoaded", refresh);
  setInterval(refresh, 60_000);  // ricarica ogni minuto
})();
