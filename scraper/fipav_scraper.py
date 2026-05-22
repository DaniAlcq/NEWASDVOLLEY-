#!/usr/bin/env python3
"""
Scraper FIPAV Sicilia per ASD Volley '96.

Scopre automaticamente i campionati in cui la società è iscritta
(senza CId hardcoded), poi estrae classifica e calendario per ognuno.

Output: file JSON in ../data/ pronti per essere consumati dal frontend.

Stagione corrente e codice società sono configurabili tramite env var o
costanti qui sotto. Lo script è robusto a piccoli cambi nell'HTML:
fallisce su un campionato senza far fallire gli altri.
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
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup, Tag

# ─── Configurazione ────────────────────────────────────────────────────

BASE = "https://sicilia.portalefipav.net"
# Codice "stagione 2025/2026" sul portale FIPAV Sicilia
STAGIONE_ID = os.environ.get("FIPAV_STAGIONE_ID", "1111")
# Codice società A.S. VOLLEY 96
SOCIETA_ID = os.environ.get("FIPAV_SOCIETA_ID", "2159")
# Comitato Regionale Sicilia
COMITATO_ID = os.environ.get("FIPAV_COMITATO_ID", "37")
# Pagina aggregatrice pubblica
PID = os.environ.get("FIPAV_PID", "7306")

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

TIMEOUT = 30
RETRY_WAIT = 5     # secondi tra retry
MAX_RETRY = 3


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
    data: str          # formato "GG/MM/AA"
    orario: str        # formato "HH:MM"
    casa: str
    casa_logo: str
    ospite: str
    ospite_logo: str
    risultato: str     # "3 - 1" oppure "" se da disputare
    parziali: str      # "25-23 25-21 25-17"
    in_casa: bool      # True se la squadra giocava in casa


@dataclass
class Campionato:
    cid: str                    # ID classifica sul portale FIPAV
    nome: str                   # es. "SERIE C FEMMINILE - Girone B"
    slug: str                   # es. "serie_c_femminile_girone_b"
    classifica: list[RigaClassifica] = field(default_factory=list)
    calendario: list[Partita] = field(default_factory=list)


# ─── HTTP utils con retry ──────────────────────────────────────────────

def fetch(url: str, params: dict | None = None) -> str:
    """GET con retry e backoff. Solleva eccezione se fallisce."""
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


# ─── Discovery: trova i campionati attivi della società ────────────────

def discover_campionati() -> list[Campionato]:
    """
    Va alla pagina pubblica filtrata per la società e ritorna la lista
    dei campionati in cui è iscritta nella stagione corrente.

    Logica: la pagina mostra blocchi di partite raggruppati per campionato.
    Il titolo di ogni blocco è in <i><a>NOME CAMPIONATO</a></i> (struttura
    ricorrente nel CMS FIPAV). Accanto al titolo c'è (se disponibile) un
    link "classifica.aspx?CId=NNN" che è proprio l'ID che ci serve.
    """
    print("→ Discovery campionati attivi della società...")
    url = f"{BASE}/risultati-classifiche.aspx"
    params = {
        "ComitatoId": COMITATO_ID,
        "StId": STAGIONE_ID,
        "PId": PID,
        "SocietaId": SOCIETA_ID,
        "btFiltro": "CERCA",
    }
    html = fetch(url, params=params)
    soup = BeautifulSoup(html, "lxml")

    campionati: list[Campionato] = []
    visti: set[str] = set()

    # Cerco tutti i link a "classifica.aspx?CId=..."
    for a in soup.find_all("a", href=re.compile(r"classifica\.aspx\?CId=\d+")):
        href = a.get("href", "")
        m = re.search(r"CId=(\d+)", href)
        if not m:
            continue
        cid = m.group(1)
        if cid in visti:
            continue
        visti.add(cid)

        # Il nome del campionato è nel testo del blocco padre, di solito
        # in un <i>...</i> immediatamente precedente la tabella.
        # Risalgo l'albero finché trovo un <i> con dentro il nome del torneo.
        nome = _trova_nome_campionato(a)
        if not nome:
            nome = f"Campionato CId={cid}"

        slug = _slugify(nome)
        campionati.append(Campionato(cid=cid, nome=nome, slug=slug))
        print(f"  ✓ trovato: {nome}  (CId={cid})")

    if not campionati:
        print("  ⚠ nessun campionato trovato per la società.", file=sys.stderr)

    return campionati


def _trova_nome_campionato(tag: Tag) -> str:
    """
    Risale dal link 'classifica' al titolo del blocco. Il portale FIPAV mette
    il nome del campionato in un <i> che precede la tabella partite.
    """
    # Cerco un <i> "fratello" o "antenato" che contenga il nome
    el: Tag | None = tag
    while el is not None:
        # Tra i fratelli precedenti
        for prev in el.find_all_previous(["i", "h2", "h3"], limit=5):
            txt = prev.get_text(strip=True)
            if re.search(r"SERIE |GIRONE|PLAY-OFF|COPPA|TROFEO|UNDER|FINAL", txt, re.I):
                return _pulisci_nome(txt)
        el = el.parent
    return ""


def _pulisci_nome(s: str) -> str:
    """Rimuove '[classifica]' e simili dalla string del titolo."""
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _slugify(nome: str) -> str:
    s = nome.lower()
    s = re.sub(r"[àáâ]", "a", s)
    s = re.sub(r"[èé]", "e", s)
    s = re.sub(r"[ìí]", "i", s)
    s = re.sub(r"[òó]", "o", s)
    s = re.sub(r"[ùú]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# ─── Parser classifica ─────────────────────────────────────────────────

def parse_classifica(cid: str) -> list[RigaClassifica]:
    """Estrae la tabella classifica da classifica.aspx?CId=NNN."""
    url = f"{BASE}/classifica.aspx"
    html = fetch(url, params={"CId": cid})
    soup = BeautifulSoup(html, "lxml")

    # La classifica è in una <table> con header che inizia con "Pos."
    table = _trova_tabella_con_header(soup, ["Pos.", "Squadra", "Punti", "PG"])
    if not table:
        print(f"  ⚠ classifica.aspx?CId={cid}: tabella non trovata", file=sys.stderr)
        return []

    righe: list[RigaClassifica] = []
    for tr in table.find_all("tr")[1:]:  # salto header
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        try:
            pos = _to_int(tds[0].get_text(strip=True))

            # Cella squadra: ha un <img> con il logo + testo
            cella_squadra = tds[1]
            img = cella_squadra.find("img")
            logo = _abs_url(img.get("src", "")) if img else ""
            nome = cella_squadra.get_text(strip=True)

            punti = _to_int(tds[2].get_text(strip=True))
            pg    = _to_int(tds[3].get_text(strip=True))
            pv    = _to_int(tds[4].get_text(strip=True)) if len(tds) > 4 else None
            pp    = _to_int(tds[5].get_text(strip=True)) if len(tds) > 5 else None
            sf    = _to_int(tds[6].get_text(strip=True)) if len(tds) > 6 else None
            ss    = _to_int(tds[7].get_text(strip=True)) if len(tds) > 7 else None
            # tds[8] = QS (quoziente set, non int)
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

def parse_calendario(cid: str, nome_societa: str) -> list[Partita]:
    """
    Estrae il calendario completo del campionato (tutte le giornate),
    filtrando solo le partite della società target.
    """
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
    # Le partite sono in <tr> dentro tabelle che hanno header "Gara | G | Data..."
    tabelle = soup.find_all("table")
    for t in tabelle:
        # Verifico che sia una tabella partite
        header = t.find("tr")
        if not header:
            continue
        ths = [th.get_text(strip=True).lower() for th in header.find_all(["th", "td"])]
        if not any("squadra casa" in h for h in ths) and not any("ospite" in h for h in ths):
            continue

        for tr in t.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            try:
                partita = _parsa_riga_partita(tds)
                if partita and _coinvolge(partita, nome_societa):
                    partite.append(partita)
            except Exception as e:
                print(f"  ⚠ riga partita saltata: {e}", file=sys.stderr)

    # Ordino per giornata numerica crescente
    partite.sort(key=lambda p: (_to_int(p.giornata) or 999, p.data))
    return partite


def _parsa_riga_partita(tds: list[Tag]) -> Optional[Partita]:
    """Parsa una riga partita. Struttura: Gara | G | Data/ora | Casa | Ospite | Risul. | ..."""
    # tds[0] = numero gara (ignorato)
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
        giornata=giornata,
        data=data,
        orario=orario,
        casa=casa,
        casa_logo=casa_logo,
        ospite=ospite,
        ospite_logo=ospite_logo,
        risultato=risultato,
        parziali=parziali,
        in_casa=False,  # impostato sotto da _coinvolge
    )


def _coinvolge(p: Partita, nome_societa: str) -> bool:
    """
    Restituisce True se la partita coinvolge la società target.
    Aggiorna anche il flag in_casa.

    Confronto fuzzy: il portale a volte abbrevia ("AS VOLLEY 96"),
    a volte usa lo sponsor ("FI.MA. FORMAZIONE MILAZZO" o
    "NDT SOLUTIONS VOLLEY '96"). Cerchiamo keyword chiave.
    """
    keywords = ["VOLLEY 96", "VOLLEY '96", "VOLLEY'96",
                "FIMA", "FI.MA", "MILAZZO",
                "NDT", "NDT SOLUTIONS"]
    casa_up = p.casa.upper()
    ospite_up = p.ospite.upper()
    in_casa = any(k in casa_up for k in keywords)
    in_trasferta = any(k in ospite_up for k in keywords)
    if in_casa:
        p.in_casa = True
        return True
    if in_trasferta:
        p.in_casa = False
        return True
    return False


# ─── Helper di parsing ────────────────────────────────────────────────

def _trova_tabella_con_header(soup: BeautifulSoup, parole_chiave: list[str]) -> Tag | None:
    """Trova la prima <table> che ha un header con tutte le parole chiave."""
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
        # Gestisco "10 " e " 10 " e numeri tipo "1,234"
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
    """
    Splitta '24/05/26 18:00' in ('24/05/26', '18:00').
    Robusto a spazi multipli e formato senza ora.
    """
    parts = s.split()
    data = parts[0] if parts else ""
    orario = parts[1] if len(parts) > 1 else ""
    return data, orario


def _pulisci_nome_squadra(s: str) -> str:
    """Rimuove spazi multipli dal nome della squadra."""
    return re.sub(r"\s+", " ", s).strip()


# ─── Output: scrittura JSON ────────────────────────────────────────────

def scrivi_json(campionato: Campionato) -> None:
    """Scrive due file: classifica_<slug>.json e calendario_<slug>.json."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Classifica
    classifica_path = OUT_DIR / f"classifica_{campionato.slug}.json"
    classifica_data = {
        "campionato": campionato.nome,
        "cid": campionato.cid,
        "aggiornato": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "items": [asdict(r) for r in campionato.classifica],
    }
    classifica_path.write_text(
        json.dumps(classifica_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"    📝 {classifica_path.name}  ({len(campionato.classifica)} righe)")

    # Calendario
    cal_path = OUT_DIR / f"calendario_{campionato.slug}.json"
    cal_data = {
        "campionato": campionato.nome,
        "cid": campionato.cid,
        "aggiornato": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "items": [asdict(p) for p in campionato.calendario],
    }
    cal_path.write_text(
        json.dumps(cal_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"    📝 {cal_path.name}  ({len(campionato.calendario)} partite)")


def scrivi_indice(campionati: list[Campionato]) -> None:
    """
    Scrive un indice campionati.json che il frontend può leggere per
    sapere quali file esistono. Così se aggiungiamo un girone nuovo,
    il frontend lo scopre da solo.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "campionati.json"
    payload = {
        "aggiornato": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "items": [
            {
                "cid": c.cid,
                "nome": c.nome,
                "slug": c.slug,
                "categoria": _detect_categoria(c.nome),
                "girone":    _detect_girone(c.nome),
            }
            for c in campionati
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n📚 Indice scritto: {path.name}")


def _detect_categoria(nome: str) -> str:
    n = nome.upper()
    if "FEMMINILE" in n: return "femminile"
    if "MASCHILE"  in n: return "maschile"
    return "altro"


def _detect_girone(nome: str) -> str:
    m = re.search(r"GIRONE\s+([A-Z])", nome.upper())
    return m.group(1) if m else ""


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    print(f"=== Scraper FIPAV Sicilia — Società {SOCIETA_ID}, Stagione {STAGIONE_ID} ===\n")

    campionati = discover_campionati()
    if not campionati:
        print("\n❌ Nessun campionato attivo trovato. Lo script termina senza scrivere file.")
        return 1

    nome_target = "VOLLEY 96"  # usato solo come display nei log

    for c in campionati:
        print(f"\n→ Campionato {c.nome}  (CId={c.cid})")
        try:
            c.classifica = parse_classifica(c.cid)
            c.calendario = parse_calendario(c.cid, nome_target)
            scrivi_json(c)
        except Exception as e:
            print(f"  ❌ errore: {e}", file=sys.stderr)
            # continuo con gli altri campionati

    scrivi_indice(campionati)
    print("\n✅ Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
