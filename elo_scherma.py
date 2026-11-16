#!/usr/bin/env python3
"""ELO Scherma (scheda 26, sessione 2) – repo map-q-la28

Che cosa fa
-----------
1. Legge da Notion gli incontri INDIVIDUALI del db "🤺 Agente Scherma" (scritti dall'agente FIE).
2. Calcola un rating ELO per ogni schermidore e per ogni arma, incontro dopo incontro, con le regole
   del §4 della scheda 26 (partenza 1500, K = 32 × torneo × margine × nuovo atleta, inattività).
3. Misura quanto bene l'ELO prevede i risultati (percentuale di favoriti che vincono) e confronta
   qualche variante dei parametri: serve a confermare le scelte prima del lancio vero.
4. Abbina ogni schermidore (ID FIE) a una riga del db Athletes e divide in tre elenchi:
     - ABBINATI   : riga trovata con certezza (per ID FIE, oppure nome + NOC + arma);
     - DA CREARE  : nessuna riga somigliante. Lo script NON crea righe (decisione di Gualtiero):
                    l'elenco serve a chi vuole aggiungerle a mano, e al calcolo successivo ricevono l'ELO;
     - INCERTI    : c'è una riga somigliante ma non basta per esserne certi: decide Gualtiero.
5. In "Solo prova" (DRY_RUN=true) NON scrive nulla su Notion: stampa elenchi, classifiche di prova,
   statistiche per scegliere le soglie, e salva gli elenchi in file CSV da aprire con Excel.
6. Nel lancio vero scrive in Athletes, SOLO per gli abbinati:
     - "ELO Fen" (l'unico campo che viene riscritto): l'ELO dell'arma con più incontri;
     - "ID FIE" solo dove è vuoto;
   e salva scherma-elo.json (ELO, storico, incontri e gare per schermidore e arma) per la pagina.

REGOLA FONDAMENTALE (scheda 26 §4): nessuna operazione su Athletes elimina dati già inseriti.
La funzione `aggiorna_riga` blocca qualsiasi colonna diversa da "ELO Fen" e "ID FIE".

Uso
---
  NOTION_TOKEN=... DRY_RUN=true python elo_scherma.py       Solo prova
  NOTION_TOKEN=... DRY_RUN=false python elo_scherma.py      lancio vero
  python elo_scherma.py --da-raw dati.json                   collaudo con dati salvati (non tocca Notion)

Non servono librerie da installare (solo Python 3.10 o più recente).
"""
import argparse
import csv
import datetime as dt
import difflib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

AVVIO = time.monotonic()
CARTELLA = Path(__file__).resolve().parent

# ====================================================================== IMPOSTAZIONI
NOTION_VERSION = "2025-09-03"   # stessa versione degli altri script del repo map-q-la28
DS_SCHERMA = "09bfeb86-04dd-45cb-bebe-dfd277c75f1f"    # data source del db "🤺 Agente Scherma"
DS_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"   # data source del db Athletes
NOMI_DB = {DS_SCHERMA: "🤺 Agente Scherma", DS_ATHLETES: "Athletes"}

# Nomi ESATTI delle colonne (scheda 26 §2 e scheda 27)
COL_S = {"uid": "ID univoco", "id1": "ID FIE 1", "id2": "ID FIE 2",       # 1 = vincitore, 2 = perdente
         "p1": "Player 1", "p2": "Player 2", "noc1": "NOC 1", "noc2": "NOC 2",
         "arma": "Arma", "gender": "Gender", "score": "Score", "turno": "Turno",
         "data": "Data", "livello": "Livello", "torneo": "Torneo", "gara": "Gara"}
COL_A = {"nome": "Cognome e Nome", "sport": "Sport", "noc": "NOC", "disc": "Disciplina",
         "id_fie": "ID FIE", "elo": "ELO Fen"}
# Campi di Athletes che lo script può scrivere in una riga esistente
SCRIVIBILI_SEMPRE = {"ELO Fen"}       # valore calcolato, appartiene allo script
SCRIVIBILI_SE_VUOTI = {"ID FIE"}      # solo se la cella è vuota

# --- regole di calcolo (scheda 26 §3 e §4) ---
ELO_PARTENZA = 1500
K_BASE = 32
COEFF_TORNEO = {                      # chiave = valore di "Livello"
    "Olimpiadi": 1.5, "Campionati del Mondo": 1.25, "Grand Prix": 1.0,
    "Coppa del Mondo": 0.9, "Campionati continentali": 0.9, "Giochi continentali": 0.9,
}
SOGLIA_NUOVO = 15                     # sotto i 15 incontri nell'arma il K si moltiplica per...
MOLT_NUOVO = 1.5                      # ... 1,5 (chi parte da 1500 si avvicina prima al suo livello)
# Margine di vittoria (MoV): scarto di stoccate -> moltiplicatore, poi diviso per la media dell'arma
SCALA_MOV = [(10, 1.15), (7, 1.11), (5, 1.08), (3, 1.04), (1, 1.00)]   # (scarto minimo, valore)
MESI_SENZA_EFFETTO = 6                # inattività: nessun effetto per 6 mesi interi...
CALO_MENSILE = 0.02                   # ... poi -2% al mese della distanza da 1500
# Soglie per mostrare l'ELO nella pagina: confermate da Gualtiero il 16/11/2026 dopo la "Solo prova"
SOGLIA_MOSTRA = 10                    # da 10 incontri (e MIN_GARE gare) l'ELO è "provvisorio"
SOGLIA_STABILE = 20                   # da 20 incontri è "stabile"
MIN_GARE = 3
# Data da cui si misura la bontà delle previsioni (stagione FIE 2027 in avanti)
DATA_VERIFICA = "2026-09-01"

# Ordine dei turni nella stessa data (scheda 26 §4)
ORDINE_TURNI = {"Preliminare da 256": 0, "Preliminare da 128": 1, "Preliminare da 64": 2,
                "Tabellone da 128": 3, "Tabellone da 64": 4, "Tabellone da 32": 5,
                "Tabellone da 16": 6, "Quarti di finale": 7, "Semifinale": 8,
                "Finale 3° posto": 9, "Finale": 10}

ARMI_EN = {"Fioretto": "Foil", "Spada": "Epee", "Sciabola": "Sabre"}
EN_ARMI = {v: k for k, v in ARMI_EN.items()}
# Disciplina in Athletes: "Men's Individual Foil"; accetta anche il refuso "Women' Individual Epee"
RE_DISCIPLINA = re.compile(r"^(Men|Women)'?s? Individual (Epee|Foil|Sabre)$")
# Sigle dei titoli che in Athletes stanno nel nome (es. "Romain CANNONE OLY [R]"): non fanno parte del nome
TITOLI = {"WC", "OLY", "OC", "EC"}

PAUSA_NOTION = 0.35
TEMPO_MAX_MINUTI = float(os.getenv("TEMPO_MAX_MINUTI", "").strip() or 165)

FILE_JSON = CARTELLA / "scherma-elo.json"
FILE_RAPPORTO = CARTELLA / "rapporto_elo_scherma.txt"
CSV_ABBINATI = CARTELLA / "scherma_elo_abbinati.csv"
CSV_DA_CREARE = CARTELLA / "scherma_elo_da_creare.csv"
CSV_INCERTI = CARTELLA / "scherma_elo_incerti.csv"


# ====================================================================== LOG
_righe_log = []


def log(testo=""):
    """Stampa a video e conserva la riga per il file rapporto_elo_scherma.txt."""
    print(testo, flush=True)
    _righe_log.append(str(testo))


def minuti():
    return (time.monotonic() - AVVIO) / 60


# ====================================================================== NOTION
def chiama(metodo, percorso, corpo=None):
    """Chiamata all'API di Notion; riprova se Notion è occupato (429) o in errore (5xx)."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        sys.exit("ERRORE: manca NOTION_TOKEN (secret del repository).")
    dati = json.dumps(corpo).encode() if corpo is not None else None
    for tentativo in range(6):
        richiesta = urllib.request.Request(
            f"https://api.notion.com/v1/{percorso}", data=dati, method=metodo,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(richiesta, timeout=90) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as errore:
            testo = errore.read().decode(errors="replace")
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 5:
                time.sleep(float(errore.headers.get("Retry-After") or 2 ** tentativo))
                continue
            if errore.code == 404:
                db = next((n for i, n in NOMI_DB.items() if i in percorso), "?")
                raise RuntimeError(f'Notion non trova "{db}": aprilo, ••• > Connessioni, '
                                   f'aggiungi la connessione usata da questo repository.')
            raise RuntimeError(f"Notion ha risposto {errore.code}: {testo[:400]}")
        except (urllib.error.URLError, TimeoutError) as errore:
            if tentativo < 5:
                time.sleep(2 ** tentativo)
                continue
            raise RuntimeError(f"Notion non raggiungibile: {errore}")


def valore(p):
    """Valore semplice di una proprietà Notion (testo, select, numero, data, multi-select)."""
    if not p:
        return None
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in p[t]).strip()
    if t == "select":
        return (p["select"] or {}).get("name")
    if t == "number":
        return p["number"]
    if t == "multi_select":
        return [x["name"] for x in p["multi_select"]]
    if t == "date":
        return ((p["date"] or {}).get("start") or "")[:10]
    return None


def interroga(ds, filtro=None):
    """Tutte le righe di un data source (100 alla volta)."""
    pagine, cursore = [], None
    while True:
        corpo = {"page_size": 100}
        if filtro:
            corpo["filter"] = filtro
        if cursore:
            corpo["start_cursor"] = cursore
        r = chiama("POST", f"data_sources/{ds}/query", corpo)
        pagine += r["results"]
        if not r.get("has_more"):
            return pagine
        cursore = r["next_cursor"]


def controlla_colonne(ds, attese):
    """Legge lo schema del db; si ferma se manca una colonna. Restituisce le proprietà."""
    props = chiama("GET", f"data_sources/{ds}")["properties"]
    mancanti = [c for c in attese if c not in props]
    if mancanti:
        sys.exit(f'ERRORE: nel db "{NOMI_DB[ds]}" non trovo le colonne: {", ".join(mancanti)}')
    return props


LIMITE_NOTION = 10000   # una ricerca dell'API Notion restituisce al massimo 10.000 righe (verificato il 16/11/2026)


def leggi_incontri():
    """Incontri individuali del db Agente Scherma, nel formato interno dello script.

    L'API di Notion non restituisce più di 10.000 righe per ricerca: con una ricerca sola si
    perdevano 1.773 incontri (prima «Solo prova» del 16/11/2026). Per questo la lettura è divisa
    in 6 ricerche, una per arma e genere (circa 2.000 righe ciascuna). Se una di esse arrivasse
    al limite, lo script si ferma invece di calcolare un ELO incompleto.
    """
    controlla_colonne(DS_SCHERMA, COL_S.values())
    incontri, visti = [], set()
    for arma in ARMI_EN:
        for genere in ("Men", "Women"):
            filtro = {"and": [{"property": COL_S["gara"], "select": {"equals": "Individuale"}},
                              {"property": COL_S["arma"], "select": {"equals": arma}},
                              {"property": COL_S["gender"], "select": {"equals": genere}}]}
            pagine = interroga(DS_SCHERMA, filtro)
            if len(pagine) >= LIMITE_NOTION:
                sys.exit(f"ERRORE: {arma} {genere}: {len(pagine)} righe, è il limite di Notion. "
                         "Bisogna dividere ancora la lettura (per esempio per stagione).")
            for pg in pagine:
                if pg["id"] in visti:
                    continue
                visti.add(pg["id"])
                p = pg["properties"]
                incontri.append({k: (valore(p.get(c)) or "") for k, c in COL_S.items() if k != "gara"})
            log(f"  letti {arma} {genere}: {len(pagine)} incontri")
    return incontri


def leggi_athletes():
    """Schermidori del db Athletes (Sport = Fencing) e opzioni di Disciplina."""
    props = controlla_colonne(DS_ATHLETES, COL_A.values())
    opzioni = {"disc": [o["name"] for o in props[COL_A["disc"]]["multi_select"]["options"]]}
    atleti = []
    for pg in interroga(DS_ATHLETES, {"property": COL_A["sport"], "select": {"equals": "Fencing"}}):
        p = pg["properties"]
        atleti.append({"page": pg["id"].replace("-", ""), "nome": valore(p.get(COL_A["nome"])) or "",
                       "noc": valore(p.get(COL_A["noc"])) or "", "disc": valore(p.get(COL_A["disc"])) or [],
                       "id_fie": (valore(p.get(COL_A["id_fie"])) or "").strip(),
                       "elo": valore(p.get(COL_A["elo"]))})
    return atleti, opzioni


def aggiorna_riga(atleta, nuovi):
    """Scrive in una riga ESISTENTE di Athletes rispettando la regola fondamentale.

    nuovi = {nome colonna: valore}. Rifiuta qualsiasi colonna non ammessa e salta "ID FIE"
    quando la cella contiene già qualcosa.
    """
    props = {}
    for col, val in nuovi.items():
        if col in SCRIVIBILI_SEMPRE:
            props[col] = {"number": val}
        elif col in SCRIVIBILI_SE_VUOTI:
            if atleta["id_fie"]:
                continue                     # la cella è già compilata: non la tocco
            props[col] = {"rich_text": [{"text": {"content": str(val)}}]}
        else:
            raise RuntimeError(f"tentativo di scrivere la colonna non ammessa '{col}': bloccato")
    if props:
        chiama("PATCH", f"pages/{atleta['page']}", {"properties": props})
    return bool(props)


# ====================================================================== CALCOLO ELO
def scarto(score):
    """Scarto di stoccate dallo Score "15-11" (vincitore per primo). None se illeggibile."""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", score or "")
    if not m:
        return None
    return int(m.group(1)) - int(m.group(2))


def mov_grezzo(d):
    """Moltiplicatore del margine di vittoria (scheda 26 §3), prima della normalizzazione."""
    for minimo, v in SCALA_MOV:
        if d >= minimo:
            return v
    return 1.0                               # scarto 0 o negativo (non dovrebbe capitare)


def con_inattivita(rating, ultima, giorno):
    """Calo per inattività (come il judo) tra la data `ultima` e la data `giorno`."""
    if not ultima:
        return rating
    d1, d2 = dt.date.fromisoformat(ultima), dt.date.fromisoformat(giorno)
    mesi_fermo = (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)
    mesi_calo = mesi_fermo - MESI_SENZA_EFFETTO
    if mesi_calo <= 0:
        return rating
    return ELO_PARTENZA + (rating - ELO_PARTENZA) * (1 - CALO_MENSILE) ** mesi_calo


def gara_di(uid):
    """'2027|451|A128|...' -> '2027|451' (stagione e codice FIE della gara)."""
    return "|".join(uid.split("|")[:2])


def filtra(incontri):
    """Tiene gli incontri utilizzabili; restituisce (validi ordinati, scarti per motivo)."""
    scarti, validi = Counter(), []
    for m in incontri:
        d = scarto(m["score"])
        if "(" in m["score"]:
            scarti["esito anomalo (MED, DNS, DNF...)"] += 1
        elif not m["id1"] or not m["id2"]:
            scarti["manca un ID FIE"] += 1
        elif m["id1"] == m["id2"]:
            scarti["stesso ID FIE nei due lati"] += 1
        elif m["livello"] not in COEFF_TORNEO:
            scarti[f"Livello sconosciuto: '{m['livello']}'"] += 1
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["data"] or ""):
            scarti["data mancante"] += 1
        elif m["arma"] not in ARMI_EN:
            scarti[f"Arma sconosciuta: '{m['arma']}'"] += 1
        elif d is None or d < 0:
            scarti[f"punteggio illeggibile: '{m['score']}'"] += 1
        else:
            if m["turno"] not in ORDINE_TURNI:
                scarti[f"turno non previsto (messo tra i Tabelloni da 16 e i Quarti): '{m['turno']}'"] += 1
            m = dict(m, scarto=d, gara=gara_di(m["uid"]))
            validi.append(m)
    validi.sort(key=lambda m: (m["data"], ORDINE_TURNI.get(m["turno"], 6.5), m["uid"]))
    return validi, scarti


def medie_mov(validi):
    """Media del MoV grezzo per arma: serve a normalizzarlo (il K medio resta 32 × torneo)."""
    somme, conti = defaultdict(float), Counter()
    for m in validi:
        somme[m["arma"]] += mov_grezzo(m["scarto"])
        conti[m["arma"]] += 1
    return {a: somme[a] / conti[a] for a in conti}


def calcola_elo(validi, oggi, k_base=K_BASE, usa_mov=True, verifica_da=None):
    """Calcola l'ELO di tutti gli schermidori, separatamente per arma.

    Restituisce (dizionario (ID FIE, arma) -> scheda, statistiche delle previsioni).
    Le previsioni si misurano solo dagli incontri a partire da `verifica_da`, e solo quando
    entrambi gli schermidori avevano già almeno SOGLIA_MOSTRA incontri nell'arma.
    """
    medie = medie_mov(validi)
    A = {}
    prev = {"n": 0, "giuste": 0, "brier": 0.0, "logloss": 0.0}

    def scheda(pid, arma, nome, noc, gender):
        chiave = (pid, arma)
        a = A.get(chiave)
        if a is None:
            a = A[chiave] = {"id": pid, "arma": arma, "nome": nome, "noc": noc, "gender": gender,
                             "rating": float(ELO_PARTENZA), "n": 0, "v": 0, "ultima": None,
                             "gare": [], "storico": [], "max": float(ELO_PARTENZA)}
        a["nome"], a["noc"] = nome or a["nome"], noc or a["noc"]     # tengo i dati più recenti
        return a

    for m in validi:
        w = scheda(m["id1"], m["arma"], m["p1"], m["noc1"], m["gender"])    # vincitore
        l = scheda(m["id2"], m["arma"], m["p2"], m["noc2"], m["gender"])    # perdente
        for x in (w, l):
            x["rating"] = con_inattivita(x["rating"], x["ultima"], m["data"])
        rw, rl = w["rating"], l["rating"]                  # rating PRIMA dell'incontro
        atteso_w = 1 / (1 + 10 ** ((rl - rw) / 400))      # probabilità che vinca chi ha vinto
        if verifica_da and m["data"] >= verifica_da and w["n"] >= SOGLIA_MOSTRA and l["n"] >= SOGLIA_MOSTRA:
            prev["n"] += 1
            prev["giuste"] += 1 if atteso_w > 0.5 else (0.5 if atteso_w == 0.5 else 0)
            prev["brier"] += (1 - atteso_w) ** 2
            prev["logloss"] += -math.log(max(atteso_w, 1e-9))
        mov = mov_grezzo(m["scarto"]) / medie[m["arma"]] if usa_mov else 1.0
        for x, r_io, r_avv, s in ((w, rw, rl, 1), (l, rl, rw, 0)):
            atteso = 1 / (1 + 10 ** ((r_avv - r_io) / 400))
            k = k_base * COEFF_TORNEO[m["livello"]] * mov * (MOLT_NUOVO if x["n"] < SOGLIA_NUOVO else 1)
            x["rating"] = r_io + k * (s - atteso)
            x["n"] += 1
            x["v"] += s
            x["ultima"] = m["data"]
            x["max"] = max(x["max"], x["rating"])
            if m["gara"] not in x["gare"]:
                x["gare"].append(m["gara"])
            # storico: un punto per gara (il valore dopo l'ultimo incontro di quella gara)
            if x["storico"] and x["storico"][-1][2] == m["gara"]:
                x["storico"][-1] = [m["data"], round(x["rating"]), m["gara"]]
            else:
                x["storico"].append([m["data"], round(x["rating"]), m["gara"]])

    for a in A.values():
        a["elo"] = con_inattivita(a["rating"], a["ultima"], oggi.isoformat())
        a["n_gare"] = len(a["gare"])
        a["livello"] = livello_elo(a["n"], a["n_gare"])
    return A, prev


def livello_elo(n, gare, mostra=None, stabile=None, min_gare=None):
    """'nascosto' / 'provvisorio' / 'stabile' secondo le soglie."""
    mostra = SOGLIA_MOSTRA if mostra is None else mostra
    stabile = SOGLIA_STABILE if stabile is None else stabile
    min_gare = MIN_GARE if min_gare is None else min_gare
    if n < mostra or gare < min_gare:
        return "nascosto"
    return "provvisorio" if n < stabile else "stabile"


def testo_previsioni(prev):
    if not prev["n"]:
        return "nessun incontro da valutare"
    return (f"{prev['n']} incontri · favorito vincente {100 * prev['giuste'] / prev['n']:.1f}% · "
            f"Brier {prev['brier'] / prev['n']:.4f} · log-loss {prev['logloss'] / prev['n']:.4f}")


# ====================================================================== NOMI E ABBINAMENTO
def lettere(testo):
    """Tiene solo lettere vere, spazi e trattini; toglie mano [R]/[L], apici (²ˣᵒᶜ), emoji e titoli."""
    testo = re.sub(r"\[[RLrl]\]", " ", testo or "")
    out = []
    for ch in testo:
        cat = unicodedata.category(ch)
        if cat in ("Lu", "Ll", "Lt", "Lo"):     # NON "Lm": ˣ ᵒ ᶜ ʷ sono lettere-apice decorative
            out.append(ch)
        elif ch in " -'’‘.":
            out.append(" ")
        else:
            out.append(" ")
    return " ".join(p for p in "".join(out).split() if p not in TITOLI)


def senza_accenti(testo):
    t = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def parti_nome(nome):
    """Divide un nome in (COGNOME, Nome, tutte le parole in ordine alfabetico), già normalizzati.

    Il cognome si riconosce dalle MAIUSCOLE, quindi vale sia per "COGNOME Nome" (FIE) sia per
    "Nome COGNOME [R]" (Athletes). Spazi, trattini e accenti non contano.
    """
    parole = lettere(nome).split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    if not cognome or not altri:
        cognome, altri = parole, []
    c = senza_accenti("".join(cognome))
    n = senza_accenti("".join(altri))
    insieme = "".join(sorted(senza_accenti(p) for p in parole))
    return c, n, insieme


def codice_noc(valore_noc):
    """'🇮🇹ITA' -> 'ITA' (ultime tre lettere maiuscole)."""
    m = re.search(r"([A-Z]{2,3})$", valore_noc or "")
    return m.group(1) if m else ""


def gare_athletes(disc):
    """Discipline individuali di una riga di Athletes -> insieme di (genere, arma)."""
    out = set()
    for d in disc:
        m = RE_DISCIPLINA.match((d or "").strip())
        if m:
            out.add(("Men" if m.group(1) == "Men" else "Women", EN_ARMI[m.group(2)]))
    return out


def simile(x, y):
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def persone_da(A):
    """Raggruppa le schede (ID FIE, arma) per persona e sceglie l'arma principale."""
    P = {}
    for (pid, arma), a in A.items():
        p = P.setdefault(pid, {"id": pid, "nome": a["nome"], "noc": a["noc"], "gender": a["gender"],
                               "armi": {}})
        p["armi"][arma] = a
    for p in P.values():
        # arma principale = quella con più incontri; a parità, quella dell'incontro più recente
        p["principale"] = max(p["armi"].values(), key=lambda a: (a["n"], a["ultima"]))["arma"]
        ultima = max(p["armi"].values(), key=lambda a: a["ultima"])
        p["nome"], p["noc"] = ultima["nome"], ultima["noc"]
    return P


def abbina(P, athletes):
    """Divide gli schermidori in abbinati / da creare / incerti.

    Restituisce un dizionario  ID FIE -> {"esito", "page", "motivo", "candidati"}.
    """
    per_id = defaultdict(list)
    for r in athletes:
        if r["id_fie"]:
            per_id[r["id_fie"]].append(r)
    liberi = []
    for r in athletes:
        if r["id_fie"]:
            continue
        r["_gare"] = gare_athletes(r["disc"])
        if not r["_gare"]:                   # pagine delle squadre (solo discipline "Team"): escluse
            continue
        r["_c"], r["_n"], r["_ins"] = parti_nome(r["nome"])
        r["_codice"] = codice_noc(r["noc"])
        liberi.append(r)

    esiti, certi_per_riga = {}, defaultdict(list)
    for pid, p in P.items():
        if pid in per_id:
            righe = per_id[pid]
            esiti[pid] = ({"esito": "abbinato", "page": righe[0]["page"], "motivo": "ID FIE", "candidati": righe}
                          if len(righe) == 1 else
                          {"esito": "incerto", "page": None, "candidati": righe,
                           "motivo": f"ID FIE presente in {len(righe)} righe di Athletes"})
            continue
        c, n, ins = parti_nome(p["nome"])
        gare = {(p["gender"], arma) for arma in p["armi"]}
        esatti, simili = [], []
        for r in liberi:
            if (c == r["_c"] and n == r["_n"]) or (ins and ins == r["_ins"]):
                esatti.append(r)
            elif c == r["_c"] and (not n or not r["_n"] or n.startswith(r["_n"]) or r["_n"].startswith(n)
                                    or simile(n, r["_n"]) >= 0.75):
                simili.append(r)
            elif n and n == r["_n"] and (simile(c, r["_c"]) >= 0.8 or c in r["_c"] or r["_c"] in c):
                simili.append(r)
            elif simile(c + n, r["_c"] + r["_n"]) >= 0.88 or simile(ins, r["_ins"]) >= 0.9:
                simili.append(r)
        # certo: stesso nome + stessa arma + stesso NOC (oppure NOC vuoto in Athletes, come nel judo)
        buoni = [r for r in esatti if (r["_codice"] == p["noc"] or not r["_codice"]) and r["_gare"] & gare]
        if len(buoni) == 1 and len(esatti) == 1:
            come = "nome + NOC + arma" if buoni[0]["_codice"] else "nome + arma (NOC vuoto in Athletes)"
            esiti[pid] = {"esito": "abbinato", "page": buoni[0]["page"], "motivo": come, "candidati": buoni}
            certi_per_riga[buoni[0]["page"]].append(pid)
        elif esatti or simili:
            motivi = []
            for r in esatti:
                diff = []
                if r["_codice"] and r["_codice"] != p["noc"]:
                    diff.append(f"NOC {r['_codice']}")
                if not r["_gare"] & gare:
                    diff.append("arma o genere diversi")
                motivi.append("stesso nome" + (", ma " + " e ".join(diff) if diff else ""))
            if len(esatti) > 1:
                motivi.insert(0, f"{len(esatti)} righe con lo stesso nome")
            if simili:
                motivi.append("nome simile: " + ", ".join(r["nome"] for r in simili[:3]))
            esiti[pid] = {"esito": "incerto", "page": None, "motivo": "; ".join(motivi),
                          "candidati": esatti + simili}
        else:
            esiti[pid] = {"esito": "da creare", "page": None, "motivo": "nessuna riga somigliante",
                          "candidati": []}
    # due schermidori diversi abbinati con certezza alla STESSA riga: nessuno dei due è certo
    for page, pids in certi_per_riga.items():
        if len(pids) > 1:
            for pid in pids:
                esiti[pid].update(esito="incerto", page=None,
                                  motivo=f"{len(pids)} schermidori FIE con lo stesso nome e la stessa arma")
    # una riga già presa con certezza non è più candidata per gli altri (come nel judo)
    prese = {e["page"] for e in esiti.values() if e["esito"] == "abbinato"}
    for e in esiti.values():
        if e["esito"] != "incerto" or e["motivo"].startswith("ID FIE"):
            continue
        rimasti = [r for r in e["candidati"] if r["page"] not in prese]
        if not rimasti:
            e.update(esito="da creare", motivo="l'unica riga somigliante è già abbinata a un altro schermidore",
                     candidati=[])
        else:
            e["candidati"] = rimasti
    return esiti


# ====================================================================== USCITE
def nome_athletes(nome_fie):
    """'FAVARETTO Martina' (FIE) -> 'Martina FAVARETTO' (formato di Athletes)."""
    parole = nome_fie.split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    return " ".join(altri + cognome) if cognome and altri else nome_fie


def disciplina(gender, arma, opzioni=None):
    """('Women', 'Spada') -> la Disciplina di Athletes, scelta tra le opzioni esistenti se note."""
    voluta = f"{gender}'s Individual {ARMI_EN[arma]}"
    for o in opzioni or []:
        m = RE_DISCIPLINA.match(o)
        if m and m.group(1) == gender and m.group(2) == ARMI_EN[arma]:
            return o                         # es. il refuso "Women' Individual Epee", se è quella in uso
    return voluta


def tag(a):
    return {"stabile": "", "provvisorio": " (provvisorio)", "nascosto": " [non mostrato]"}[a["livello"]]


def stampa_classifiche(A, quanti=10):
    log("\n" + "=" * 78)
    log(f"CLASSIFICA ELO DI PROVA (primi {quanti} per gara, solo ELO mostrati nella pagina)")
    log("=" * 78)
    for g, nome_g in (("Men", "Uomini"), ("Women", "Donne")):
        for arma in ("Fioretto", "Spada", "Sciabola"):
            lista = sorted((a for a in A.values() if a["gender"] == g and a["arma"] == arma
                            and a["livello"] != "nascosto"), key=lambda a: -a["elo"])
            log(f"\n{nome_g} {arma.lower()}  ({len(lista)} con ELO mostrato)")
            for i, a in enumerate(lista, 1):
                if i <= quanti or a["noc"] == "ITA":
                    segno = "  ← Italia" if a["noc"] == "ITA" and i > quanti else ""
                    log(f"  {i:>3}. {a['nome'][:30]:<30} {a['noc']:<4} {a['elo']:7.0f}  "
                        f"{a['n']:>2} inc. {a['n_gare']:>2} gare{tag(a)}{segno}")


def stampa_soglie(A):
    """Quanti ELO si vedrebbero con soglie diverse: serve a sceglierle (scheda 26 §3)."""
    log("\n" + "=" * 78)
    log("SCELTA DELLE SOGLIE: schermidori con ELO mostrato (provvisorio + stabile) e stabili")
    log("=" * 78)
    combinazioni = [(8, 15, 2), (10, 20, 3), (10, 25, 3), (12, 25, 3), (15, 30, 4)]
    log("  soglie (mostra / stabile / gare minime)   " + "   ".join(
        f"{g[:1]}{a[:3]}" for g in ("Men", "Women") for a in ("Fioretto", "Spada", "Sciabola")))
    for mostra, stabile, min_gare in combinazioni:
        celle = []
        for g in ("Men", "Women"):
            for arma in ("Fioretto", "Spada", "Sciabola"):
                lv = [livello_elo(a["n"], a["n_gare"], mostra, stabile, min_gare)
                      for a in A.values() if a["gender"] == g and a["arma"] == arma]
                celle.append(f"{lv.count('provvisorio') + lv.count('stabile')}/{lv.count('stabile')}")
        segno = "  ← attuali" if (mostra, stabile, min_gare) == (SOGLIA_MOSTRA, SOGLIA_STABILE, MIN_GARE) else ""
        log(f"  {mostra:>2} / {stabile:>2} / {min_gare}                          " +
            "  ".join(f"{c:>7}" for c in celle) + segno)
    log("  (colonne: M = uomini, W = donne; Fio, Spa, Sci; valori = mostrati/stabili)")


def scrivi_csv(percorso, intestazione, righe):
    """CSV con il punto e virgola: si apre bene con Excel in italiano."""
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(intestazione)
        w.writerows(righe)


def link(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}" if page_id else ""


def salva_elenchi(P, esiti, per_page, opzioni):
    def base(p):
        a = p["armi"][p["principale"]]
        return [p["id"], p["nome"], p["noc"], f"{p['gender']} {p['principale']}", round(a["elo"]),
                a["n"], a["n_gare"], a["livello"]]
    intest = ["ID FIE", "Nome FIE", "NOC FIE", "Arma principale", "ELO", "Incontri", "Gare", "Livello"]
    ordina = lambda pid: (-P[pid]["armi"][P[pid]["principale"]]["n"], P[pid]["nome"])
    ab = sorted((p for p, e in esiti.items() if e["esito"] == "abbinato"), key=ordina)
    dc = sorted((p for p, e in esiti.items() if e["esito"] == "da creare"), key=ordina)
    inc = sorted((p for p, e in esiti.items() if e["esito"] == "incerto"), key=ordina)
    scrivi_csv(CSV_ABBINATI, intest + ["Riga Athletes", "NOC Athletes", "Come", "Link"],
               [base(P[p]) + [per_page[esiti[p]["page"]]["nome"], per_page[esiti[p]["page"]]["noc"],
                              esiti[p]["motivo"], link(esiti[p]["page"])] for p in ab])
    scrivi_csv(CSV_DA_CREARE, intest + ["Nome da scrivere in Athletes", "Disciplina da scegliere"],
               [base(P[p]) + [nome_athletes(P[p]["nome"]),
                              disciplina(P[p]["gender"], P[p]["principale"], opzioni.get("disc"))] for p in dc])
    scrivi_csv(CSV_INCERTI, intest + ["Motivo", "Candidati in Athletes (nome | NOC | disciplina | link)"],
               [base(P[p]) + [esiti[p]["motivo"],
                              " || ".join(f"{r['nome']} | {r['noc'] or '-'} | {'/'.join(r['disc']) or '-'} | "
                                          f"{link(r['page'])}" for r in esiti[p]["candidati"][:4])]
                for p in inc])
    return ab, dc, inc


def salva_json(A, P, esiti, tornei, oggi):
    """scherma-elo.json: tutto ciò che serve alla pagina (sessione 3). Una voce per schermidore e arma."""
    atleti = []
    for a in sorted(A.values(), key=lambda a: -a["elo"]):
        p, e = P[a["id"]], esiti.get(a["id"], {})
        atleti.append({
            "id_fie": a["id"], "nome": a["nome"], "noc": a["noc"],
            "notion": (e.get("page") or "").replace("-", "") or None,   # stesso formato di scherma-performance.json
            "genere": "U" if a["gender"] == "Men" else "D", "arma": a["arma"],
            "principale": a["arma"] == p["principale"],
            "elo": round(a["elo"]), "elo_max": round(a["max"]), "livello": a["livello"],
            "incontri": a["n"], "vittorie": a["v"], "gare": a["n_gare"], "ultimo": a["ultima"],
            "storico": a["storico"]})
    dati = {"aggiornato": oggi.isoformat(),
            "regole": {"partenza": ELO_PARTENZA, "k": K_BASE, "soglia_provvisorio": SOGLIA_MOSTRA,
                       "soglia_stabile": SOGLIA_STABILE, "min_gare": MIN_GARE},
            "tornei": tornei, "atleti": atleti}
    FILE_JSON.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ====================================================================== MAIN
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file JSON con {incontri, athletes, opzioni} salvati: collaudo senza Notion")
    ap.add_argument("--oggi", help="data del calcolo AAAA-MM-GG (di norma oggi)")
    args = ap.parse_args()
    solo_prova = os.getenv("DRY_RUN", "true").strip().lower() != "false" or bool(args.da_raw)
    oggi = dt.date.fromisoformat(args.oggi) if args.oggi else dt.date.today()

    log(f"ELO Scherma · {'SOLO PROVA: non scrivo nulla su Notion' if solo_prova else 'SCRITTURA su Notion'} "
        f"· data del calcolo {oggi.isoformat()}")

    # 1. lettura
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        incontri, athletes, opzioni = raw["incontri"], raw["athletes"], raw.get("opzioni", {})
    else:
        incontri = leggi_incontri()
        athletes, opzioni = leggi_athletes()
    log(f"Incontri individuali letti dal db Agente Scherma: {len(incontri)}")
    log(f"Righe di Athletes con Sport = Fencing: {len(athletes)}, con ID FIE già compilato: "
        f"{sum(1 for r in athletes if r['id_fie'])}")

    # 2. calcolo
    validi, scarti = filtra(incontri)
    log(f"Incontri usati nell'ELO: {len(validi)}")
    for motivo, n in scarti.most_common():
        log(f"  esclusi {n}: {motivo}")
    medie = medie_mov(validi)
    log("Margine di vittoria medio per arma (serve a normalizzarlo): "
        + ", ".join(f"{a} {v:.3f}" for a, v in sorted(medie.items())))
    A, prev = calcola_elo(validi, oggi, verifica_da=DATA_VERIFICA)
    livelli = Counter(a["livello"] for a in A.values())
    log(f"Schede ELO (schermidore × arma): {len(A)} · stabili {livelli['stabile']} · "
        f"provvisori {livelli['provvisorio']} · non mostrati {livelli['nascosto']}")

    # 3. bontà delle previsioni e confronto tra varianti (scheda 26 §8)
    log("\n" + "=" * 78)
    log(f"BONTÀ DELLE PREVISIONI (incontri dal {DATA_VERIFICA}, entrambi con almeno {SOGLIA_MOSTRA} incontri prima)")
    log("=" * 78)
    log(f"  Regole decise (K 32, con margine):  {testo_previsioni(prev)}")
    for k_base, usa_mov, nome in ((24, True, "K 24, con margine"), (40, True, "K 40, con margine"),
                                  (32, False, "K 32, senza margine")):
        _, p = calcola_elo(validi, oggi, k_base=k_base, usa_mov=usa_mov, verifica_da=DATA_VERIFICA)
        log(f"  Variante {nome:<22} {testo_previsioni(p)}")
    log("  (favorito vincente: più alto è meglio; Brier e log-loss: più bassi è meglio;"
        " un modello a caso darebbe 50%, Brier 0,25, log-loss 0,693)")

    tornei = {}
    for m in validi:
        t = tornei.setdefault(m["gara"], {"nome": m["torneo"], "livello": m["livello"], "data": m["data"],
                                          "arma": m["arma"], "genere": "U" if m["gender"] == "Men" else "D"})
        t["data"] = min(t["data"], m["data"])

    # 4. abbinamento con Athletes
    P = persone_da(A)
    esiti = abbina(P, athletes)
    per_page = {r["page"]: r for r in athletes}
    ab, dc, inc = salva_elenchi(P, esiti, per_page, opzioni)
    mostrato = lambda pid: P[pid]["armi"][P[pid]["principale"]]["livello"] != "nascosto"
    log("\n" + "=" * 78)
    log("ABBINAMENTO CON IL DB ATHLETES")
    log("=" * 78)
    log(f"Schermidori (persone): {len(P)}, di cui in due armi: {sum(1 for p in P.values() if len(p['armi']) > 1)}")
    log(f"Abbinati: {len(ab)} ({dict(Counter(esiti[p]['motivo'] for p in ab))}); con ELO mostrato: "
        f"{sum(1 for p in ab if mostrato(p))}")
    log(f"Da creare (lo script non li crea): {len(dc)}; con ELO mostrato: {sum(1 for p in dc if mostrato(p))}")
    log(f"Incerti: {len(inc)}; con ELO mostrato: {sum(1 for p in inc if mostrato(p))}")
    individuali = [r for r in athletes if gare_athletes(r["disc"])]
    usate = {esiti[p]["page"] for p in ab}
    log(f"Righe individuali di Athletes: {len(individuali)}, abbinate: {len(usate)}, "
        f"senza incontri FIE riconosciuti: {len(individuali) - len(usate)}")
    log("\nIncerti con ELO mostrato (i più importanti da controllare):")
    for p in [p for p in inc if mostrato(p)][:60]:
        a = P[p]["armi"][P[p]["principale"]]
        log(f"  · {P[p]['nome']} ({P[p]['noc']}, {P[p]['gender']} {P[p]['principale']}, {a['n']} inc., "
            f"ELO {a['elo']:.0f}) → {esiti[p]['motivo']}")
    log("\nDa creare con ELO mostrato e NOC ITA: " + (", ".join(
        P[p]["nome"] for p in dc if mostrato(p) and P[p]["noc"] == "ITA") or "nessuno"))
    righe_no = [r for r in individuali if r["page"] not in usate]
    log(f"\nRighe individuali di Athletes NON abbinate (prime 40 su {len(righe_no)}): "
        + "; ".join(f"{r['nome']} ({codice_noc(r['noc']) or '-'})" for r in righe_no[:40]))
    log(f"Elenchi completi nei file {CSV_ABBINATI.name}, {CSV_DA_CREARE.name}, {CSV_INCERTI.name} "
        f"(Artifacts del lancio).")

    stampa_soglie(A)
    stampa_classifiche(A)
    salva_json(A, P, esiti, tornei, oggi)
    log(f"\n{FILE_JSON.name}: {len(A)} schede (schermidore × arma), {len(tornei)} gare")

    if solo_prova:
        log("\nProva terminata: non è stato scritto nulla su Notion.")
        return 0

    # 5. scrittura su Notion (solo db Athletes; solo ELO Fen e ID FIE vuoti; solo abbinati)
    log("\n" + "=" * 78)
    log("SCRITTURA IN ATHLETES")
    log("=" * 78)
    aggiornate = invariate = errori = 0
    for p in ab:
        if minuti() > TEMPO_MAX_MINUTI:
            log(f"ATTENZIONE: mi sono fermato dopo {TEMPO_MAX_MINUTI:.0f} minuti. Rilancia: "
                "le righe già scritte risultano abbinate per ID FIE.")
            return 1
        riga = per_page[esiti[p]["page"]]
        elo = round(P[p]["armi"][P[p]["principale"]]["elo"])        # ELO dell'arma principale
        nuovi = {}
        if riga["elo"] is None or round(riga["elo"]) != elo:
            nuovi["ELO Fen"] = elo
        if not riga["id_fie"]:
            nuovi["ID FIE"] = p
        if not nuovi:
            invariate += 1
            continue
        try:
            aggiorna_riga(riga, nuovi)
            aggiornate += 1
            time.sleep(PAUSA_NOTION)
        except RuntimeError as e:
            log(f"  Errore su {riga['nome']}: {e}")
            errori += 1
    log(f"Righe aggiornate: {aggiornate} · invariate: {invariate} · errori: {errori} · "
        f"incerti non scritti: {len(inc)} · da creare non scritti: {len(dc)} · minuti: {minuti():.0f}")
    return 1 if errori else 0


if __name__ == "__main__":
    codice = 1
    try:
        codice = main()
    except SystemExit as e:
        codice = e.code if isinstance(e.code, int) else 1
        if not isinstance(e.code, int):
            log(str(e.code))
    except Exception:                    # qualsiasi errore: lo scrivo nel rapporto
        import traceback
        log(traceback.format_exc())
    finally:
        FILE_RAPPORTO.write_text("\n".join(_righe_log) + "\n", encoding="utf-8")
    sys.exit(codice)
