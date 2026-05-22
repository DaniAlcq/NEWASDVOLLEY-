#!/usr/bin/env python3
"""
Scraper FIPAV Sicilia per ASD Volley '96 — v2.

Strategia (più robusta della v1):
1. Recupera l'elenco di TUTTI i campionati attivi della stagione corrente
   leggendo il dropdown della pagina principale risultati-classifiche.aspx
2. Per ogni campionato, scarica la classifica
3. Filtra: tiene solo i campionati dove appare una squadra che matcha
   le keyword della società (VOLLEY 96, FIMA, MILAZZO, NDT, ...)
4. Per quei campionati estrae anche il calendario

Output: file JSON in ../data/ pronti per essere consumati dal frontend.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# ─── Configurazione ────────────────────────────────────────────────────

BASE = "https://sicilia.portalefipav.net"
STAGIONE_ID = os.environ.get("FIPAV_STAGIONE_ID", "1111")
COMITATO_ID = os.environ.get("FIPAV_COMITATO_ID", "37")
PID         = os.environ.get("FIPAV_PID", "7306")

# Keyword per riconoscere la squadra. Case-insensitive.
SOCIETA_KEYWORDS = [
    "VOLLEY 96", "VOLLEY '96", "VOLLEY'96",
    "FIMA", "FI.MA",
    "MILAZZO",
    "NDT",
]

OUT_DIR = Path(__file__).resolve().parent.parent / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

TIMEOUT     = 30
RETRY_WAIT  = 5
MAX_RETRY   = 3


# ─── Modelli dati ──────────────────────────────────────────────────────

@dataclass
class RigaClassifica:
    posizione: int | None
    nome: str
    logo: str
    punti: int | None
    partite_giocate: int | None
    vittorie: int | None
    sconfitte: int | None
    set_fatti: int | None = None
    set_subiti: int | None = None
    punti_fatti: int | None = None
    punti_subiti: int | None = None
    penalita: int | None = None


@dataclass
class Partita:
    giornata: str
    data: str
    orario: str
    casa: str
    casa_logo: str
    ospite: str
    ospite_logo: str
    risultato: str
    parziali: str
    in_casa: bool


@dataclass
class Campionato:
    cid: str
    nome: str
    slug: str
    classifica: list[RigaClassifica] = field(default_factory=list)
    calendario: list[Partita] = field(default_factory=list)


# ─── HTTP utils con retry ──────────────────────────────────────────────

def fetch(url: str, params: dict | None = None) -> str:
    """GET con retry e backoff."""
    last_err: Exception | None = None
    for tentativo in range(1, MAX_RETRY + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            print(f"  [retry {tentativo}/{MAX_RETRY}] {e}", file=sys.stderr)
            if tentativo < MAX_RETRY:
                time.sleep(RETRY_WAIT * tentativo)
    raise RuntimeError(f"Fetch fallito dopo {MAX_RETRY} tentativi: {last_err}")


# ─── Discovery: lista di TUTTI i campionati della stagione ─────────────

def discover_tutti_campionati() -> list[tuple[str, str]]:
    """
    Estrae l'elenco completo dei campionati della stagione corrente
    dal dropdown HTML della pagina principale.
    Ritorna [(CId, nome_campionato), ...].

    Strategia: il dropdown 'Campionato' è un <select> con <option value="NNN">NOME</option>.
    """
    print("→ Discovery completa dei campionati della stagione...")
    url = f"{BASE}/risultati-classifiche.aspx"
    params = {
        "ComitatoId": COMITATO_ID,
        "StId": STAGIONE_ID,
        "PId": PID,
    }
    html = fetch(url, params=params)
    soup = BeautifulSoup(html, "lxml")

    campionati: list[tuple[str, str]] = []

    # Cerco TUTTI i <select> e prendo quello che contiene i nomi dei campionati
    # (riconoscibile perché contiene option con "SERIE" o "GIRONE" nel testo)
    for select in soup.find_all("select"):
        options = select.find_all("option")
        # Verifico se è il dropdown dei campionati
        sembra_campionati = any(
            re.search(r"SERIE\s+[A-Z]|GIRONE|PLAY-OFF|COPPA|TROFEO|UNDER|FINAL\s+SIX",
                      o.get_text(), re.I)
            for o in options
        )
        if not sembra_campionati:
            continue

        for opt in options:
            cid = (opt.get("value") or "").strip()
            nome = opt.get_text(strip=True)
            if not cid or not cid.isdigit():
                continue
            if not nome or "Tutti i campionati" in nome:
                continue
            campionati.append((cid, nome))
        break  # solo il primo select valido

    # Fallback se il dropdown non si trova: scansiona link <a href="classifica.aspx?CId=NNN">
    if not campionati:
        print("  (dropdown non trovato, uso fallback dai link)", file=sys.stderr)
        visti: set[str] = set()
        for a in soup.find_all("a", href=re.compile(r"classifica\.aspx\?CId=\d+")):
            m = re.search(r"CId=(\d+)", a.get("href", ""))
            if not m or m.group(1) in visti:
                continue
            visti.add(m.group(1))
            campionati.append((m.group(1), f"Campionato CId={m.group(1)}"))

    print(f"  → trovati {len(campionati)} campionati totali nella stagione")
    return campionati


# ─── Parser classifica ─────────────────────────────────────────────────

def parse_classifica(cid: str) -> list[RigaClassifica]:
    """Estrae la tabella classifica da classifica.aspx?CId=NNN."""
    url = f"{BASE}/classifica.aspx"
    html = fetch(url, params={"CId": cid})
    soup = BeautifulSoup(html, "lxml")

    table = _trova_tabella_con_header(soup, ["Pos.", "Squadra", "Punti", "PG"])
    if not table:
        return []

    righe: list[RigaClassifica] = []
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        try:
            pos = _to_int(tds[0].get_text(strip=True))
            cella_squadra = tds[1]
            img = cella_squadra.find("img")
            logo = _abs_url(img.get("src", "")) if img else ""
            nome = cella_squadra.get_text(strip=True)

            punti = _to_int(tds[2].get_text(strip=True))
            pg    = _to_int(tds[3].get_text(strip=True))
            pv    = _to_int(tds[4].get_text(strip=True))  if len(tds) > 4  else None
            pp    = _to_int(tds[5].get_text(strip=True))  if len(tds) > 5  else None
            sf    = _to_int(tds[6].get_text(strip=True))  if len(tds) > 6  else None
            ss    = _to_int(tds[7].get_text(strip=True))  if len(tds) > 7  else None
            pf    = _to_int(tds[9].get_text(strip=True))  if len(tds) > 9  else None
            ps    = _to_int(tds[10].get_text(strip=True)) if len(tds) > 10 else None
            penal = _to_int(tds[12].get_text(strip=True)) if len(tds) > 12 else None

            righe.append(RigaClassifica(
                posizione=pos, nome=nome, logo=logo,
                punti=punti, partite_giocate=pg,
                vittorie=pv, sconfitte=pp,
                set_fatti=sf, set_subiti=ss,
                punti_fatti=pf, punti_subiti=ps,
                penalita=penal,
            ))
        except Exception as e:
            print(f"  ⚠ riga classifica saltata: {e}", file=sys.stderr)

    return righe


# ─── Parser calendario ─────────────────────────────────────────────────

def parse_calendario(cid: str) -> list[Partita]:
    """Estrae il calendario completo del campionato CId."""
    url = f"{BASE}/risultati-classifiche.aspx"
    params = {
        "ComitatoId": COMITATO_ID,
        "StId": STAGIONE_ID,
        "PId": PID,
        "CId": cid,
        "btFiltro": "CERCA",
    }
    html = fetch(url, params=params)
    soup = BeautifulSoup(html, "lxml")

    partite: list[Partita] = []
    for t in soup.find_all("table"):
        header = t.find("tr")
        if not header:
            continue
        testo_header = header.get_text(" ", strip=True).lower()
        if "squadra casa" not in testo_header and "squadra ospite" not in testo_header:
            continue

        for tr in t.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            try:
                p = _parsa_riga_partita(tds)
                if p and _coinvolge_societa(p):
                    partite.append(p)
            except Exception as e:
                print(f"  ⚠ riga partita saltata: {e}", file=sys.stderr)

    partite.sort(key=lambda p: (_to_int(p.giornata) or 999, p.data))
    return partite


def _parsa_riga_partita(tds: list[Tag]) -> Optional[Partita]:
    giornata = tds[1].get_text(strip=True)
    data_ora = tds[2].get_text(" ", strip=True)
    data, orario = _split_data_ora(data_ora)

    casa_cell   = tds[3]
    ospite_cell = tds[4]
    risul_cell  = tds[5]

    casa_img    = casa_cell.find("img")
    ospite_img  = ospite_cell.find("img")
    casa_logo   = _abs_url(casa_img.get("src", "")) if casa_img else ""
    ospite_logo = _abs_url(ospite_img.get("src", "")) if ospite_img else ""
    casa        = _pulisci_nome_squadra(casa_cell.get_text(" ", strip=True))
    ospite      = _pulisci_nome_squadra(ospite_cell.get_text(" ", strip=True))

    risultato_raw = risul_cell.get_text(strip=True)
    risultato = "" if risultato_raw in ("-", "", "—") else risultato_raw

    parziali = ""
    if len(tds) > 6:
        parziali = tds[6].get_text(" ", strip=True)
        if parziali in ("-", "—"):
            parziali = ""

    return Partita(
        giornata=giornata, data=data, orario=orario,
        casa=casa, casa_logo=casa_logo,
        ospite=ospite, ospite_logo=ospite_logo,
        risultato=risultato, parziali=parziali,
        in_casa=False,
    )


def _matcha_societa(nome: str) -> bool:
    """True se il nome contiene una keyword della nostra società."""
    upper = nome.upper()
    return any(kw in upper for kw in SOCIETA_KEYWORDS)


def _coinvolge_societa(p: Partita) -> bool:
    """True se la partita coinvolge la nostra società (e setta in_casa)."""
    if _matcha_societa(p.casa):
        p.in_casa = True
        return True
    if _matcha_societa(p.ospite):
        p.in_casa = False
        return True
    return False


# ─── Categoria/girone dal nome del campionato ──────────────────────────

def detect_categoria(nome: str) -> str:
    n = nome.upper()
    if "FEMMINILE" in n: return "femminile"
    if "MASCHILE"  in n: return "maschile"
    return "altro"


def detect_girone(nome: str) -> str:
    m = re.search(r"GIRONE\s+([A-Z])", nome.upper())
    return m.group(1) if m else ""


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[àáâ]", "a", s)
    s = re.sub(r"[èé]", "e", s)
    s = re.sub(r"[ìí]", "i", s)
    s = re.sub(r"[òó]", "o", s)
    s = re.sub(r"[ùú]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# ─── Helper di parsing ────────────────────────────────────────────────

def _trova_tabella_con_header(soup, parole_chiave: list[str]) -> Tag | None:
    for t in soup.find_all("table"):
        header = t.find("tr")
        if not header:
            continue
        testo = header.get_text(" ", strip=True)
        if all(k in testo for k in parole_chiave):
            return t
    return None


def _to_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s or s in ("-", "—"):
        return None
    try:
        s = s.replace(".", "").replace(" ", "")
        return int(s)
    except ValueError:
        return None


def _abs_url(src: str) -> str:
    if not src:
        return ""
    if src.startswith(("http://", "https://")):
        return src
    return urljoin(BASE + "/", src)


def _split_data_ora(s: str) -> tuple[str, str]:
    parts = s.split()
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def _pulisci_nome_squadra(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ─── Output ────────────────────────────────────────────────────────────

def scrivi_json(c: Campionato) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    (OUT_DIR / f"classifica_{c.slug}.json").write_text(
        json.dumps({
            "campionato": c.nome, "cid": c.cid, "aggiornato": now,
            "items": [asdict(r) for r in c.classifica],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"    📝 classifica_{c.slug}.json  ({len(c.classifica)} righe)")

    (OUT_DIR / f"calendario_{c.slug}.json").write_text(
        json.dumps({
            "campionato": c.nome, "cid": c.cid, "aggiornato": now,
            "items": [asdict(p) for p in c.calendario],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"    📝 calendario_{c.slug}.json  ({len(c.calendario)} partite)")


def scrivi_indice(campionati: list[Campionato]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    payload = {
        "aggiornato": now,
        "items": [
            {
                "cid": c.cid,
                "nome": c.nome,
                "slug": c.slug,
                "categoria": detect_categoria(c.nome),
                "girone":    detect_girone(c.nome),
            }
            for c in campionati
        ],
    }
    (OUT_DIR / "campionati.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n📚 Indice scritto: campionati.json  ({len(campionati)} campionati)")


def pulisci_file_vecchi(campionati_attivi: list[Campionato]) -> None:
    """Rimuove i JSON di campionati che non sono più attivi (es. residuati del primo run)."""
    if not OUT_DIR.exists():
        return
    slug_attivi = {c.slug for c in campionati_attivi}
    for f in OUT_DIR.glob("classifica_*.json"):
        slug = f.stem.removeprefix("classifica_")
        if slug not in slug_attivi:
            f.unlink()
            print(f"  🗑  rimosso file obsoleto: {f.name}")
    for f in OUT_DIR.glob("calendario_*.json"):
        slug = f.stem.removeprefix("calendario_")
        if slug not in slug_attivi:
            f.unlink()
            print(f"  🗑  rimosso file obsoleto: {f.name}")


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    print(f"=== Scraper FIPAV Sicilia v2 — Stagione {STAGIONE_ID} ===")
    print(f"    Keyword società: {SOCIETA_KEYWORDS}\n")

    tutti = discover_tutti_campionati()
    if not tutti:
        print("\n❌ Nessun campionato trovato nella stagione.")
        return 1

    nostri: list[Campionato] = []
    print(f"\n→ Cerco la società tra i {len(tutti)} campionati...\n")

    for i, (cid, nome) in enumerate(tutti, 1):
        try:
            classifica = parse_classifica(cid)
            if not classifica:
                continue
            # Match: una qualsiasi riga della classifica contiene una keyword
            ha_societa = any(_matcha_societa(r.nome) for r in classifica)
            if not ha_societa:
                continue

            print(f"  ✓ MATCH [{i}/{len(tutti)}]: {nome}  (CId={cid})")
            c = Campionato(cid=cid, nome=nome, slug=slugify(nome), classifica=classifica)
            c.calendario = parse_calendario(cid)
            nostri.append(c)

            # piccola cortesia: non bombardiamo il server
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠ errore su CId={cid}: {e}", file=sys.stderr)

    if not nostri:
        print("\n❌ Nessun campionato trovato che contenga la società.")
        print("   Verifica le keyword in SOCIETA_KEYWORDS.")
        return 1

    print(f"\n→ Scrivo i JSON per {len(nostri)} campionati...\n")
    for c in nostri:
        scrivi_json(c)

    scrivi_indice(nostri)
    pulisci_file_vecchi(nostri)

    print("\n✅ Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
