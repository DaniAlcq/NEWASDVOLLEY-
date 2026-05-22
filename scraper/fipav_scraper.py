#!/usr/bin/env python3
"""
Scraper FIPAV Sicilia per ASD Volley '96 — v3.

Strategia (più robusta delle v1/v2):
- Match della squadra primario tramite il SocietaId nel path del logo
  (es. /mngArea/Societa/img/2159/Loghi/LogoS2159.jpg → società 2159)
- Fallback su keyword fuzzy nel nome (normalizzato: rimossi punti e spazi)
- Discovery: scansiona tutti i campionati della stagione e tiene quelli
  dove la classifica contiene la nostra società

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

# Codice univoco società su FIPAV Sicilia (immutabile)
SOCIETA_ID = os.environ.get("FIPAV_SOCIETA_ID", "2159")

# Keyword di fallback nel nome (case-insensitive, normalizzate)
# La normalizzazione rimuove punti e spazi multipli, quindi "FI.MA." → "FIMA"
SOCIETA_KEYWORDS_FALLBACK = [
    "VOLLEY96", "FIMA", "MILAZZO", "NDTSOLUTIONS", "NDT",
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


# ─── Riconoscimento società (il cuore del fix) ────────────────────────

def _normalize(s: str) -> str:
    """Normalizza un nome: maiuscolo, senza punteggiatura, senza spazi multipli."""
    if not s:
        return ""
    s = s.upper()
    # Rimuovo punteggiatura comune nei nomi società
    s = re.sub(r"[.,\-_'`´’]", "", s)
    # Spazi multipli → uno
    s = re.sub(r"\s+", " ", s).strip()
    # Versione senza spazi per match come "FIMA" in "FI MA"
    return s


def _matcha_societa(nome: str, logo_url: str = "") -> bool:
    """
    True se questa squadra è ASD Volley '96.
    Strategie in cascata:
      1. Il path del logo contiene /img/{SOCIETA_ID}/ — match esatto e affidabile
      2. Keyword nel nome normalizzato (rimuove punti/spazi)
    """
    # Strategia 1: match per ID nel path del logo
    if logo_url and f"/img/{SOCIETA_ID}/" in logo_url:
        return True

    # Strategia 2: keyword nel nome
    nome_norm = _normalize(nome)
    # Versione senza spazi per beccare "VOLLEY 96" anche se diventa "VOLLEY96"
    nome_compatto = nome_norm.replace(" ", "")
    for kw in SOCIETA_KEYWORDS_FALLBACK:
        if kw in nome_compatto:
            return True
    return False


# ─── Discovery campionati della stagione ──────────────────────────────

def discover_tutti_campionati() -> list[tuple[str, str]]:
    """Ritorna [(CId, nome), ...] di tutti i campionati della stagione."""
    print("→ Discovery dei campionati della stagione...")
    url = f"{BASE}/risultati-classifiche.aspx"
    params = {"ComitatoId": COMITATO_ID, "StId": STAGIONE_ID, "PId": PID}
    html = fetch(url, params=params)
    soup = BeautifulSoup(html, "lxml")

    campionati: list[tuple[str, str]] = []

    # Cerco il <select> dei campionati
    for select in soup.find_all("select"):
        options = select.find_all("option")
        sembra_campionati = any(
            re.search(r"SERIE\s+[A-Z]|GIRONE|PLAY-?OFF|COPPA|TROFEO|UNDER|FINAL",
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
        break

    print(f"  → trovati {len(campionati)} campionati")
    return campionati


# ─── Parser classifica ─────────────────────────────────────────────────

def parse_classifica(cid: str) -> list[RigaClassifica]:
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
    url = f"{BASE}/risultati-classifiche.aspx"
    params = {
        "ComitatoId": COMITATO_ID, "StId": STAGIONE_ID, "PId": PID,
        "CId": cid, "btFiltro": "CERCA",
    }
    html = fetch(url, params=params)
    soup = BeautifulSoup(html, "lxml")

    partite: list[Partita] = []
    debug_seen = 0   # contatore partite incontrate (per log diagnostico)

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
                if not p:
                    continue
                debug_seen += 1
                if _coinvolge_societa(p):
                    partite.append(p)
            except Exception as e:
                print(f"  ⚠ riga partita saltata: {e}", file=sys.stderr)

    print(f"    [debug] partite totali nel campionato: {debug_seen}, nostre: {len(partite)}")
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


def _coinvolge_societa(p: Partita) -> bool:
    """True se la partita coinvolge la nostra società (setta in_casa)."""
    if _matcha_societa(p.casa, p.casa_logo):
        p.in_casa = True
        return True
    if _matcha_societa(p.ospite, p.ospite_logo):
        p.in_casa = False
        return True
    return False


# ─── Categoria/girone ──────────────────────────────────────────────────

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
                "cid": c.cid, "nome": c.nome, "slug": c.slug,
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
    print(f"\n📚 Indice: campionati.json  ({len(campionati)} campionati)")


def pulisci_file_vecchi(campionati_attivi: list[Campionato]) -> None:
    """Rimuove i JSON di campionati non più attivi."""
    if not OUT_DIR.exists():
        return
    slug_attivi = {c.slug for c in campionati_attivi}
    for prefix in ("classifica_", "calendario_"):
        for f in OUT_DIR.glob(f"{prefix}*.json"):
            slug = f.stem.removeprefix(prefix)
            if slug not in slug_attivi:
                f.unlink()
                print(f"  🗑  rimosso: {f.name}")


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    print(f"=== Scraper FIPAV Sicilia v3 ===")
    print(f"    Stagione:    {STAGIONE_ID}")
    print(f"    Società ID:  {SOCIETA_ID}")
    print(f"    Fallback kw: {SOCIETA_KEYWORDS_FALLBACK}\n")

    tutti = discover_tutti_campionati()
    if not tutti:
        print("\n❌ Nessun campionato trovato nella stagione.")
        return 1

    nostri: list[Campionato] = []
    print(f"\n→ Scansione di {len(tutti)} campionati...\n")

    for i, (cid, nome) in enumerate(tutti, 1):
        try:
            classifica = parse_classifica(cid)
            if not classifica:
                continue
            ha_societa = any(_matcha_societa(r.nome, r.logo) for r in classifica)
            if not ha_societa:
                continue

            print(f"  ✓ MATCH [{i}/{len(tutti)}]: {nome}  (CId={cid})")
            c = Campionato(cid=cid, nome=nome, slug=slugify(nome), classifica=classifica)
            c.calendario = parse_calendario(cid)
            nostri.append(c)
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠ errore su CId={cid}: {e}", file=sys.stderr)

    if not nostri:
        print("\n❌ Nessun campionato trovato che contenga la società.")
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
