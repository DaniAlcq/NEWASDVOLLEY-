# ASD Volley '96 — Sito Ufficiale

Sito statico ospitato su **GitHub Pages**, con dati di calendario e classifiche aggiornati **in automatico** dal portale FIPAV Sicilia ogni 2 ore tramite **GitHub Actions**.

---

## 🔧 Architettura

```
┌──────────────────────────────────────────────────────────────────┐
│                      GITHUB REPOSITORY                            │
│                                                                   │
│  ┌─────────────────────┐         ┌────────────────────────────┐  │
│  │  Sito statico        │         │  GitHub Actions            │  │
│  │  HTML / CSS / JS     │◄────────┤  (ogni 2 ore + manuale)   │  │
│  │                      │         │                            │  │
│  │  Legge JSON locali   │         │  fipav_scraper.py          │  │
│  │  da /data            │         │  ↓                         │  │
│  │                      │         │  scrape sicilia.fipav.it   │  │
│  └──────────┬───────────┘         │  ↓                         │  │
│             │                     │  commit data/*.json        │  │
│             ▼                     └────────────────────────────┘  │
│      GitHub Pages                                                 │
│      asdvolley96.it                                               │
└───────────────────────────────────────────────────────────────────┘
```

**Cosa NON è cambiato:**

- Google Sheets continua a gestire la **diretta YouTube** (tab `Diretta`) e qualunque carosello/news editoriali che già usavi.
- Il dominio personalizzato `asdvolley96.it` resta con il CNAME esistente.

**Cosa è cambiato:**

- Calendario e classifiche **non sono più gestiti su Sheets**: vengono presi direttamente da `sicilia.portalefipav.net` dallo scraper.
- I file `js/calendario.js` e `js/classifiche.js` leggono dai JSON locali in `/data` invece che da Opensheet.
- Rimossi: `fade.js` (rompeva il pulsante back del browser), `script.js` (era vuoto), duplicato del bottone Live in `menu.js`.

---

## 📁 Struttura del repository

```
.
├── index.html              # Home (riusa il tuo esistente)
├── calendario.html         # ⟵ refactor: legge da data/calendario_*.json
├── classifiche.html        # ⟵ refactor: legge da data/classifica_*.json
├── squadre.html            # Pagine statiche (riusa esistente)
├── contatti.html           # Cleanup minore
│
├── css/
│   ├── style.css
│   └── style-apple.css
│
├── js/
│   ├── menu.js             # Hamburger menu (no più duplicato live)
│   ├── live.js             # Bottone diretta YouTube da Sheets
│   ├── classifiche.js      # ⟵ NUOVO: carica dai JSON locali
│   └── calendario.js       # ⟵ NUOVO: carica dai JSON locali
│
├── data/                   # ⟵ NUOVA: alimentata dalle Actions
│   ├── campionati.json
│   ├── classifica_<slug>.json
│   └── calendario_<slug>.json
│
├── img/
│   ├── home.png            # ⟵ ICONA CASA (da aggiungere — vedi sotto)
│   ├── away.png            # ⟵ ICONA TRASFERTA (da aggiungere)
│   └── ...
│
├── scraper/
│   ├── fipav_scraper.py    # Lo scraper Python
│   └── requirements.txt
│
└── .github/workflows/
    └── fipav-scrape.yml    # Cron job ogni 2 ore + run manuale
```

---

## 🚀 Setup iniziale (una sola volta)

### 1. Pusha il codice nel tuo repo GitHub

```bash
git add .
git commit -m "Refactor: GitHub Actions per dati FIPAV automatici"
git push origin main
```

### 2. Verifica i permessi delle Actions

Vai su **Settings → Actions → General → Workflow permissions** del repo e assicurati che sia selezionato:

- ✅ **Read and write permissions**
- ✅ **Allow GitHub Actions to create and approve pull requests** (opzionale)

Senza questo, il workflow non può fare commit dei JSON aggiornati.

### 3. Avvia il primo scraping manualmente

1. Vai sulla tab **Actions** del repo
2. Apri "Aggiorna dati FIPAV"
3. Clicca **Run workflow** → **Run workflow**

Dopo ~1 minuto vedrai:
- I JSON popolati in `/data`
- Un commit automatico fatto da `github-actions[bot]`
- GitHub Pages si rideploya da solo entro pochi secondi

### 4. Aggiungi le icone Casa/Trasferta

Nel file `js/calendario.js` sono referenziate due icone:

```js
const ICONA_CASA = "img/home.png";
const ICONA_TRASFERTA = "img/away.png";
```

Crea o scarica due piccole icone PNG (es. una casa per casa, una valigia per trasferta) e mettile in `img/`. Se preferisci tenere le icone che già usavi (era una cella `<img class="icon-luogo">` con URL da Sheets), basta cambiare quelle due righe.

---

## ⚙️ Configurazione avanzata

### Cambiare stagione o società

Lo scraper usa di default:
- `FIPAV_STAGIONE_ID = 1111` (stagione 2025/2026)
- `FIPAV_SOCIETA_ID  = 2159` (ASD Volley '96)

Per **cambiarli senza toccare il codice**, vai su **Settings → Secrets and variables → Actions → Variables** e crea:

| Nome | Valore |
|---|---|
| `FIPAV_STAGIONE_ID` | nuovo codice stagione (lo trovi nel dropdown del portale) |
| `FIPAV_SOCIETA_ID`  | nuovo codice società |

Le Variables hanno priorità sulle costanti hardcoded.

### Cambiare la frequenza di aggiornamento

In `.github/workflows/fipav-scrape.yml`:

```yaml
schedule:
  - cron: "0 */2 * * *"   # ogni 2 ore  (DEFAULT)
  # - cron: "0 */6 * * *" # ogni 6 ore
  # - cron: "0 8,20 * * *" # solo alle 8:00 e alle 20:00 UTC
```

Più rado = meno consumo di minuti GitHub Actions (comunque siamo ben dentro il free tier: 2000 min/mese gratis).

---

## 🧪 Test locale dello scraper

Prima di pushare modifiche, puoi provare lo scraper sul tuo PC:

```bash
cd scraper
python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python fipav_scraper.py
```

Output atteso:
```
=== Scraper FIPAV Sicilia — Società 2159, Stagione 1111 ===

→ Discovery campionati attivi della società...
  ✓ trovato: SERIE C FEMMINILE - Girone B  (CId=XXXXX)
  ✓ trovato: SERIE C MASCHILE - Girone A   (CId=XXXXX)

→ Campionato SERIE C FEMMINILE - Girone B
    📝 classifica_serie_c_femminile_girone_b.json  (11 righe)
    📝 calendario_serie_c_femminile_girone_b.json  (22 partite)

...

📚 Indice scritto: campionati.json

✅ Done.
```

Per testare il sito in locale dopo aver generato i JSON:

```bash
# nella root del repo
python3 -m http.server 8000
# apri http://localhost:8000
```

---

## 🛠 Manutenzione

### Cosa fare se FIPAV cambia struttura HTML

Lo scraper logga su stderr quando non riesce a parsare qualcosa. Vai su **Actions → Aggiorna dati FIPAV → Run più recente** e leggi i log.

Se vedi messaggi tipo `⚠ tabella non trovata` o `⚠ riga partita saltata`, il portale FIPAV ha cambiato qualcosa. Le modifiche tipiche da fare in `scraper/fipav_scraper.py`:

- `_trova_tabella_con_header()` — aggiorna le parole chiave se gli header cambiano
- `parse_classifica()` — aggiorna gli indici delle colonne (`tds[0]`, `tds[1]`...)
- `_parsa_riga_partita()` — idem per le tabelle partite

Il design è **resiliente**: anche se uno dei due parser si rompe, l'altro continua a funzionare. Niente blackout totale.

### Cosa fare se cambia il nome della società

Nel portale FIPAV la società è registrata come "A.S. VOLLEY 96" (codice 2159). Sul campo gioca con denominazioni sponsorizzate (es. "FI.MA. FORMAZIONE MILAZZO" femminile, "ADG NDT SOLUTIONS VOLLEY '96" maschile).

Lo scraper riconosce la squadra con un **match fuzzy** su queste keyword (in `_coinvolge()`):

```python
keywords = ["VOLLEY 96", "VOLLEY '96", "FIMA", "FI.MA",
            "MILAZZO", "NDT", "NDT SOLUTIONS"]
```

Se cambia sponsor, aggiungi la nuova keyword e fai un push.

---

## 📝 Note sui contenuti editoriali

Il **carosello foto** e le **news** continuano a essere gestiti come prima — Google Sheets + link Drive — senza modifiche da questo refactor. Se in futuro volessi cambiarli, è una discussione separata.

---

## ❓ FAQ

**Q: Se FIPAV è offline, cosa succede al sito?**
A: Niente. I JSON in `/data` restano quelli dell'ultima esecuzione riuscita. Lo scraping ritenta automaticamente all'esecuzione successiva.

**Q: I JSON sono pubblici?**
A: Sì, sono in GitHub Pages. Non c'è nulla di sensibile (sono gli stessi dati pubblici del portale FIPAV).

**Q: Posso vedere quando sono stati aggiornati?**
A: Sì, ogni JSON contiene un campo `"aggiornato"` con timestamp ISO 8601 UTC. Esempio:
```json
{ "aggiornato": "2026-05-22T14:00:11+00:00", "items": [...] }
```

**Q: Posso modificare manualmente i JSON?**
A: Tecnicamente sì, ma alla prossima esecuzione (entro 2 ore) lo scraper li sovrascriverà. Se vuoi un override permanente, devi cambiare la logica nello script.

---

🏐 Buon volley!
