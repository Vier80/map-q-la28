#!/usr/bin/env python3
"""ELO Judo (scheda 19, sessione 2) – repo map-q-la28

Che cosa fa
-----------
1. Legge da Notion tutti gli incontri del db "🥋 Agente Judo" (scritti dall'agente risultati IJF).
2. Calcola un rating ELO per ogni judoka, incontro dopo incontro, con le regole del §5 della scheda 19.
3. Abbina ogni judoka (codice IJF) a una riga del db Athletes (§5.9) e divide i judoka in tre elenchi:
     - ABBINATI   : riga di Athletes trovata con certezza (per ID IJF, oppure nome + NOC + categoria);
     - DA CREARE  : nessuna riga somigliante in Athletes;
     - INCERTI    : c'è una riga somigliante, ma non basta per esserne certi: decide Gualtiero.
4. In "Solo prova" (DRY_RUN=true) NON scrive nulla su Notion: stampa gli elenchi e una classifica ELO di
   prova, e salva gli elenchi in file CSV da aprire con Excel.
5. Nel lancio vero scrive in Athletes:
     - `ELO` per tutti gli abbinati (è l'unico campo che viene riscritto);
     - `ID IJF` solo dove è vuoto;
     - le righe nuove per i judoka DA CREARE;
   e salva judo-elo.json (storico, incontri e tornei per atleta) per la pagina judo-performance.html.

REGOLA FONDAMENTALE (scheda 19 §5.9): nessuna operazione su Athletes elimina dati già inseriti.
Lo script non archivia righe, non svuota campi e nelle righe esistenti scrive solo `ELO` e,
se vuoto, `ID IJF`. La funzione `aggiorna_riga` controlla questo vincolo prima di ogni scrittura.

Uso
---
  NOTION_TOKEN=... DRY_RUN=true python elo_judo.py      Solo prova
  NOTION_TOKEN=... DRY_RUN=false python elo_judo.py     lancio vero
  python elo_judo.py --da-raw dati.json                  collaudo con dati salvati (non tocca Notion)

Non servono librerie da installare (solo Python 3.10 o più recente).
"""
import argparse
import csv
import datetime as dt
import difflib
import json
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
DS_AGENTE_JUDO = "410f48c9-aad9-807c-a3ec-000b4d5ea2ab"   # data source del db "🥋 Agente Judo"
DS_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"      # data source del db Athletes
NOMI_DB = {DS_AGENTE_JUDO: "🥋 Agente Judo", DS_ATHLETES: "Athletes"}

# Nomi ESATTI delle colonne (scheda 19 §4 e 01_schema_notion §1.1 e §5)
COL_J = {"p1": "Player 1", "noc1": "NOC 1", "id1": "ID IJF 1",
         "p2": "Player 2", "noc2": "NOC 2", "id2": "ID IJF 2",
         "winner": "Winner", "gender": "Gender", "cat": "Categoria", "score": "Score",
         "turno": "Turno", "torneo": "Torneo", "tipo": "Tipo Torneo", "data": "Data", "uid": "ID Univoco"}
COL_A = {"nome": "Cognome e Nome", "sport": "Sport", "noc": "NOC", "disc": "Disciplina",
         "id_ijf": "ID IJF", "elo": "ELO"}
# Campi di Athletes che lo script può scrivere in una riga GIÀ ESISTENTE (§5.9)
SCRIVIBILI_SEMPRE = {"ELO"}            # valore calcolato, appartiene allo script
SCRIVIBILI_SE_VUOTI = {"ID IJF", "NOC"}  # solo se la cella è vuota

# --- regole di calcolo (scheda 19 §5) ---
ELO_PARTENZA = 1500
K_BASE = 32
COEFF_TORNEO = {                        # §5.1, chiave = valore di "Tipo Torneo"
    "Olimpiadi": 1.5, "Mondiali": 1.25, "Grand Slam": 1.0,
    "Campionati continentali": 0.9, "Giochi continentali": 0.9, "Grand Prix": 0.85,
}
SOGLIA_NUOVO = 15            # sotto i 15 incontri il K si moltiplica per...
MOLT_NUOVO = 1.5             # ... 1,5 (chi parte da 1500 si avvicina prima al suo livello)
COEFF_SQUALIFICA = 0.85      # §5.4: lo sconfitto ha HM o 3 shido
COEFF_GOLDEN = 0.9           #       golden score
COEFF_IPPON = 1.15           #       ippon nel tempo regolamentare
COEFF_WAZA = 1.0             #       waza-ari o yuko (e Score "n.d.")
MESI_SENZA_EFFETTO = 6       # §5.6: inattività tollerata
CALO_MENSILE = 0.02          #       poi -2% al mese della distanza da 1500
SOGLIA_MOSTRA = 10           # §5.7: da 10 incontri (e 2 tornei) ELO "provvisorio"
SOGLIA_STABILE = 20          #       da 20 incontri ELO "stabile"
MIN_TORNEI = 2

# §5.5: ordine dei turni nello stesso giorno ("Round 1" prima di tutti, §6 punto 4)
ORDINE_TURNI = {"Round 1": 0, "Round of 128": 1, "Round of 64": 2, "Round of 32": 3,
                "Round of 16": 4, "Quarter-Final": 5, "Repechage": 6, "Semi-Final": 7,
                "Bronze": 8, "Final": 9}

PESI = {"Men": ["-60", "-66", "-73", "-81", "-90", "-100", "+100"],
        "Women": ["-48", "-52", "-57", "-63", "-70", "-78", "+78"]}
CODICI_NEUTRALI = {"IJF", "AIN", "IRT", "EOR", "NEU", "ROT"}

PAUSA_NOTION = 0.35          # secondi tra una scrittura e l'altra (Notion accetta ~3 richieste/s)
TEMPO_MAX_MINUTI = float(os.getenv("TEMPO_MAX_MINUTI", "").strip() or 165)

FILE_JSON = CARTELLA / "judo-elo.json"
FILE_RAPPORTO = CARTELLA / "rapporto_elo.txt"
CSV_ABBINATI = CARTELLA / "elo_abbinati.csv"
CSV_DA_CREARE = CARTELLA / "elo_da_creare.csv"
CSV_INCERTI = CARTELLA / "elo_incerti.csv"


# ====================================================================== LOG
_righe_log = []


def log(testo=""):
    """Stampa a video e conserva la riga per il file rapporto_elo.txt."""
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
                attesa = float(errore.headers.get("Retry-After") or 2 ** tentativo)
                time.sleep(attesa)
                continue
            if errore.code == 404:
                db = next((n for i, n in NOMI_DB.items() if i in percorso), "?")
                raise RuntimeError(f'Notion non trova "{db}": aprilo, ••• > Connessioni, '
                                   f'aggiungi la connessione "Agente Squash".')
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


def leggi_incontri():
    """Righe del db Agente Judo nel formato interno dello script."""
    controlla_colonne(DS_AGENTE_JUDO, COL_J.values())
    incontri = []
    for pg in interroga(DS_AGENTE_JUDO):
        p = pg["properties"]
        v = {k: valore(p.get(c)) or "" for k, c in COL_J.items()}
        # chi ha vinto: il nome in Winner è uguale a Player 1 (bianco) o a Player 2 (blu)
        vince = 1 if v["winner"] == v["p1"] else 2 if v["winner"] == v["p2"] else 0
        incontri.append({
            "uid": v["uid"], "cid": v["uid"].split("|")[0], "data": v["data"], "turno": v["turno"],
            "tipo": v["tipo"], "gender": v["gender"], "cat": v["cat"], "score": v["score"],
            "torneo": v["torneo"], "vince": vince,
            "id1": v["id1"], "nome1": v["p1"], "noc1": v["noc1"],
            "id2": v["id2"], "nome2": v["p2"], "noc2": v["noc2"]})
    return incontri


def leggi_athletes():
    """Judoka del db Athletes (Sport = Judo) e opzioni esistenti di NOC e Disciplina."""
    props = controlla_colonne(DS_ATHLETES, COL_A.values())
    opzioni = {"noc": [o["name"] for o in props[COL_A["noc"]]["select"]["options"]],
               "disc": [o["name"] for o in props[COL_A["disc"]]["multi_select"]["options"]],
               "sport": [o["name"] for o in props[COL_A["sport"]]["select"]["options"]]}
    atleti = []
    for pg in interroga(DS_ATHLETES, {"property": COL_A["sport"], "select": {"equals": "Judo"}}):
        p = pg["properties"]
        atleti.append({"page": pg["id"], "nome": valore(p.get(COL_A["nome"])) or "",
                       "noc": valore(p.get(COL_A["noc"])) or "",
                       "disc": valore(p.get(COL_A["disc"])) or [],
                       "id_ijf": (valore(p.get(COL_A["id_ijf"])) or "").strip(),
                       "elo": valore(p.get(COL_A["elo"]))})
    return atleti, opzioni


def aggiorna_riga(atleta, nuovi):
    """Scrive in una riga ESISTENTE di Athletes, rispettando la regola fondamentale (§5.9).

    nuovi = {nome colonna: valore}. Rifiuta qualsiasi colonna non ammessa e salta i campi
    "solo se vuoti" quando la cella contiene già qualcosa.
    """
    props = {}
    for col, val in nuovi.items():
        if col in SCRIVIBILI_SEMPRE:
            props[col] = {"number": val}
        elif col in SCRIVIBILI_SE_VUOTI:
            attuale = atleta["id_ijf"] if col == "ID IJF" else atleta["noc"]
            if attuale:
                continue                     # la cella è già compilata: non la tocco
            props[col] = ({"rich_text": [{"text": {"content": str(val)}}]} if col == "ID IJF"
                          else {"select": {"name": val}})
        else:
            raise RuntimeError(f"tentativo di scrivere la colonna non ammessa '{col}': bloccato")
    if props:
        chiama("PATCH", f"pages/{atleta['page']}", {"properties": props})
    return bool(props)


def crea_riga(dati):
    """Crea una riga nuova in Athletes per un judoka che non c'è ancora (§5.9)."""
    props = {COL_A["nome"]: {"title": [{"text": {"content": dati["nome"]}}]},
             COL_A["sport"]: {"select": {"name": "Judo"}},
             COL_A["id_ijf"]: {"rich_text": [{"text": {"content": dati["id"]}}]},
             COL_A["elo"]: {"number": dati["elo_notion"]}}
    if dati["noc_notion"]:
        props[COL_A["noc"]] = {"select": {"name": dati["noc_notion"]}}
    if dati["disc"]:
        props[COL_A["disc"]] = {"multi_select": [{"name": d} for d in dati["disc"]]}
    r = chiama("POST", "pages", {"parent": {"type": "data_source_id", "data_source_id": DS_ATHLETES},
                                 "properties": props})
    return r["id"]


# ====================================================================== CALCOLO ELO
def coeff_vittoria(score, vince):
    """Coefficiente del modo di vittoria (§5.4) letto dallo Score "bianco - blu".

    vince = 1 se ha vinto il bianco (lato sinistro), 2 se ha vinto il blu (lato destro).
    Restituisce (coefficiente, etichetta).
    """
    s = (score or "").strip()
    if not s or s.lower() == "n.d.":
        return COEFF_WAZA, "n.d."           # torneo senza punteggi: vale come waza-ari (§6 punto 5)
    golden = "(GS)" in s
    s = s.replace("(GS)", "").strip()
    if " - " not in s:
        return COEFF_WAZA, "score illeggibile"
    sinistra, destra = [x.split() for x in s.split(" - ", 1)]
    vincitore, sconfitto = (sinistra, destra) if vince == 1 else (destra, sinistra)
    shido = max([int(t[:-1]) for t in sconfitto if re.fullmatch(r"\d+S", t)] or [0])
    if "HM" in sconfitto or shido >= 3:
        return COEFF_SQUALIFICA, "squalifica"   # vale anche se il vincitore ha "I"
    if golden:
        return COEFF_GOLDEN, "golden score"
    if "I" in vincitore:
        return COEFF_IPPON, "ippon"
    return COEFF_WAZA, "waza-ari"


def con_inattivita(rating, ultima, giorno):
    """Applica il calo per inattività (§5.6) tra la data `ultima` e la data `giorno`."""
    if not ultima:
        return rating
    d1, d2 = dt.date.fromisoformat(ultima), dt.date.fromisoformat(giorno)
    # mesi di calendario interi senza incontri (dal 13/11/2025 al 13/11/2026 = 12 mesi)
    mesi_fermo = (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)
    mesi_calo = mesi_fermo - MESI_SENZA_EFFETTO
    if mesi_calo <= 0:
        return rating
    return ELO_PARTENZA + (rating - ELO_PARTENZA) * (1 - CALO_MENSILE) ** mesi_calo


def calcola_elo(incontri, oggi):
    """Calcola l'ELO di tutti i judoka. Restituisce (dizionario per ID IJF, scarti per motivo)."""
    scarti = Counter()
    validi = []
    for m in incontri:
        if not m["id1"] or not m["id2"]:
            scarti["manca un ID IJF"] += 1
        elif m["vince"] not in (1, 2):
            scarti["Winner diverso da Player 1 e Player 2"] += 1
        elif m["tipo"] not in COEFF_TORNEO:
            scarti[f"Tipo Torneo sconosciuto: '{m['tipo']}'"] += 1
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["data"] or ""):
            scarti["data mancante"] += 1
        else:
            if m["turno"] not in ORDINE_TURNI:
                scarti[f"turno non previsto (messo tra QF e Repechage): '{m['turno']}'"] += 1
            validi.append(m)

    # §5.5: prima la data, poi il turno; a parità l'ID Univoco (solo per avere sempre lo stesso ordine)
    validi.sort(key=lambda m: (m["data"], ORDINE_TURNI.get(m["turno"], 5.5), m["uid"]))

    A = {}

    def scheda(pid, nome, noc):
        a = A.get(pid)
        if a is None:
            a = A[pid] = {"id": pid, "nome": nome, "noc": noc, "rating": float(ELO_PARTENZA),
                          "n": 0, "v": 0, "ultima": None, "tornei": [], "cat": set(),
                          "ultimo_gender": "", "ultima_cat": "", "storico": [], "max": float(ELO_PARTENZA)}
        a["nome"], a["noc"] = nome or a["nome"], noc or a["noc"]    # tengo i dati più recenti
        return a

    modi = Counter()
    for m in validi:
        a = scheda(m["id1"], m["nome1"], m["noc1"])
        b = scheda(m["id2"], m["nome2"], m["noc2"])
        for x in (a, b):
            x["rating"] = con_inattivita(x["rating"], x["ultima"], m["data"])
        coeff, modo = coeff_vittoria(m["score"], m["vince"])
        modi[modo] += 1
        ra, rb = a["rating"], b["rating"]            # rating PRIMA dell'incontro
        for x, r_io, r_avv, s in ((a, ra, rb, 1 if m["vince"] == 1 else 0),
                                  (b, rb, ra, 1 if m["vince"] == 2 else 0)):
            atteso = 1 / (1 + 10 ** ((r_avv - r_io) / 400))
            k = K_BASE * COEFF_TORNEO[m["tipo"]] * coeff * (MOLT_NUOVO if x["n"] < SOGLIA_NUOVO else 1)
            x["rating"] = r_io + k * (s - atteso)
            x["n"] += 1
            x["v"] += s
            x["ultima"] = m["data"]
            x["max"] = max(x["max"], x["rating"])
            x["cat"].add((m["gender"], m["cat"]))
            x["ultimo_gender"], x["ultima_cat"] = m["gender"], m["cat"]
            if m["cid"] not in x["tornei"]:          # tornei diversi disputati
                x["tornei"].append(m["cid"])
            # storico: un punto per torneo (il valore dopo l'ultimo incontro di quel torneo)
            if x["storico"] and x["storico"][-1][2] == m["cid"]:
                x["storico"][-1] = [m["data"], round(x["rating"]), m["cid"]]
            else:
                x["storico"].append([m["data"], round(x["rating"]), m["cid"]])

    # ELO alla data del calcolo (con l'eventuale calo per inattività) e soglia di visualizzazione
    for a in A.values():
        a["elo"] = con_inattivita(a["rating"], a["ultima"], oggi.isoformat())
        a["n_tornei"] = len(a["tornei"])
        if a["n"] < SOGLIA_MOSTRA or a["n_tornei"] < MIN_TORNEI:
            a["livello"] = "nascosto"
        elif a["n"] < SOGLIA_STABILE:
            a["livello"] = "provvisorio"
        else:
            a["livello"] = "stabile"
    return A, scarti, modi, len(validi)


# ====================================================================== NOMI E ABBINAMENTO
def lettere(testo):
    """Tiene solo lettere vere, spazi e trattini; toglie apici (²ˣᵒᶜ), emoji e simboli."""
    out = []
    for ch in testo or "":
        cat = unicodedata.category(ch)
        if cat in ("Lu", "Ll", "Lt", "Lo"):     # NON "Lm": ˣ ᵒ ᶜ ʷ sono lettere-apice decorative
            out.append(ch)
        elif ch in " -'’‘. ":
            out.append(" ")
    return " ".join("".join(out).split())


def senza_accenti(testo):
    t = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def parti_nome(nome):
    """Divide un nome in (COGNOME, Nome), riconoscendo il cognome dalle MAIUSCOLE.

    Vale sia per "COGNOME Nome" (IJF) sia per "Nome COGNOME" (Athletes) e per "KIM Won-jin".
    Restituisce i due pezzi "compattati" (senza spazi, trattini e accenti, in maiuscolo).
    """
    parole = lettere(nome).split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    if not cognome or not altri:            # formato non riconosciuto: tutto nel "cognome"
        cognome, altri = parole, []
    c = senza_accenti("".join(cognome))
    n = senza_accenti("".join(altri))
    insieme = "".join(sorted(senza_accenti(p) for p in parole))
    return c, n, insieme


def nome_athletes(nome_ijf):
    """'COGNOME Nome' (IJF) -> 'Nome COGNOME' (formato di Athletes)."""
    parole = nome_ijf.split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    return " ".join(altri + cognome) if cognome and altri else nome_ijf


def disciplina(gender, cat):
    """('Men', '-90 kg') -> "Men's -90kg" (formato di Athletes)."""
    return f"{gender}'s {cat.replace(' ', '')}" if gender and cat else ""


def codice_noc(valore_noc):
    """'🇮🇹ITA' -> 'ITA' (ultime tre lettere maiuscole)."""
    m = re.search(r"([A-Z]{2,3})$", valore_noc or "")
    return m.group(1) if m else ""


def simile(x, y):
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def abbina(A, athletes):
    """Divide i judoka in abbinati / da creare / incerti (scheda 19 §5.9).

    Restituisce un dizionario  id IJF -> {"esito", "page", "motivo", "candidati"}.
    """
    # 1) righe di Athletes con ID IJF già compilato
    per_id = defaultdict(list)
    for r in athletes:
        if r["id_ijf"]:
            per_id[r["id_ijf"]].append(r)
    liberi = [r for r in athletes if not r["id_ijf"]]
    for r in liberi:
        r["_c"], r["_n"], r["_ins"] = parti_nome(r["nome"])
        r["_codice"] = codice_noc(r["noc"])
        r["_disc"] = set(r["disc"])
        r["_squadra"] = any("Team" in d for d in r["disc"]) or "Team" in r["nome"]
    liberi = [r for r in liberi if not r["_squadra"]]      # "ITA Judo Mixed Team" ecc.

    esiti = {}
    certi_per_riga = defaultdict(list)
    for pid, a in A.items():
        if pid in per_id:
            righe = per_id[pid]
            if len(righe) == 1:
                esiti[pid] = {"esito": "abbinato", "page": righe[0]["page"], "motivo": "ID IJF",
                              "candidati": righe}
            else:
                esiti[pid] = {"esito": "incerto", "page": None,
                              "motivo": f"ID IJF presente in {len(righe)} righe di Athletes", "candidati": righe}
            continue
        c, n, ins = parti_nome(a["nome"])
        discipline = {disciplina(g, k) for g, k in a["cat"]}
        esatti, simili = [], []
        for r in liberi:
            if (c == r["_c"] and n == r["_n"]) or (ins and ins == r["_ins"]):
                esatti.append(r)
            elif c == r["_c"] and (not n or not r["_n"] or n.startswith(r["_n"]) or r["_n"].startswith(n)
                                    or simile(n, r["_n"]) >= 0.75):
                simili.append(r)
            elif n and n == r["_n"] and (simile(c, r["_c"]) >= 0.8 or c in r["_c"] or r["_c"] in c):
                simili.append(r)
            elif c == r["_c"] and r["_codice"] == a["noc"] and r["_disc"] & discipline:
                simili.append(r)       # stesso cognome, NOC e categoria: nome scritto diversamente
                                       # (es. "Babalay" / "Balabay", "Shar" / "Shannon")
            elif simile(c + n, r["_c"] + r["_n"]) >= 0.88:
                simili.append(r)
        # Regola del 13/11/2026 (decisione di Gualtiero): se in Athletes il NOC è VUOTO basta che
        # coincidano nome e categoria; il NOC mancante verrà compilato nel lancio vero.
        buoni = [r for r in esatti
                 if (r["_codice"] == a["noc"] or not r["_codice"]) and r["_disc"] & discipline]
        if len(buoni) == 1 and len(esatti) == 1:
            come = "nome + NOC + categoria" if buoni[0]["_codice"] else "nome + categoria (NOC vuoto in Athletes)"
            esiti[pid] = {"esito": "abbinato", "page": buoni[0]["page"], "motivo": come,
                          "candidati": buoni}
            certi_per_riga[buoni[0]["page"]].append(pid)
        elif esatti or simili:
            motivi = []
            for r in esatti:
                diff = []
                if r["_codice"] != a["noc"]:
                    diff.append(f"NOC {r['_codice'] or 'vuoto'}")
                if not r["_disc"] & discipline:
                    diff.append(f"categoria {'/'.join(sorted(r['_disc'])) or 'vuota'}")
                motivi.append("stesso nome" + (", ma " + " e ".join(diff) if diff else ""))
            if len(esatti) > 1:
                motivi.insert(0, f"{len(esatti)} righe con lo stesso nome")
            if simili:
                motivi.append(f"nome simile: {', '.join(r['nome'] for r in simili[:3])}")
            esiti[pid] = {"esito": "incerto", "page": None, "motivo": "; ".join(motivi),
                          "candidati": esatti + simili}
        else:
            esiti[pid] = {"esito": "da creare", "page": None, "motivo": "nessuna riga somigliante",
                          "candidati": []}
    # due judoka IJF diversi abbinati con certezza alla STESSA riga: nessuno dei due è certo
    for page, pids in certi_per_riga.items():
        if len(pids) > 1:
            for pid in pids:
                esiti[pid].update(esito="incerto", page=None,
                                  motivo=f"{len(pids)} judoka IJF con lo stesso nome, NOC e categoria")
    # Una riga già presa con certezza da un judoka non è più candidata per gli altri: dalla
    # settimana dopo avrà l'ID IJF e sparirà dai candidati. Lo applico subito, così il primo lancio
    # e quelli successivi danno lo stesso risultato (es. due "KIM" coreani con nomi simili).
    prese = {e["page"] for e in esiti.values() if e["esito"] == "abbinato"}
    for pid, e in esiti.items():
        if e["esito"] != "incerto" or not e["candidati"] or e["motivo"].startswith("ID IJF"):
            continue
        rimasti = [r for r in e["candidati"] if r["page"] not in prese]
        if not rimasti:
            e.update(esito="da creare", motivo="l'unica riga somigliante è già abbinata a un altro judoka",
                     candidati=[])
        else:
            e["candidati"] = rimasti
    return esiti


# ====================================================================== USCITE
def tag(a):
    return {"stabile": "", "provvisorio": " (provvisorio)", "nascosto": " [non mostrato]"}[a["livello"]]


def stampa_classifiche(A, esiti, quanti=10):
    log("\n" + "=" * 78)
    log(f"CLASSIFICA ELO DI PROVA (primi {quanti} per categoria, solo ELO mostrati nella pagina)")
    log("=" * 78)
    for g, pesi in PESI.items():
        for kg in pesi:
            cat = f"{kg} kg"
            lista = [a for a in A.values() if a["ultimo_gender"] == g and a["ultima_cat"] == cat
                     and a["livello"] != "nascosto"]
            lista.sort(key=lambda a: -a["elo"])
            log(f"\n{'Uomini' if g == 'Men' else 'Donne'} {cat}  ({len(lista)} con ELO mostrato)")
            for i, a in enumerate(lista[:quanti], 1):
                log(f"  {i:>2}. {a['nome'][:30]:<30} {a['noc']:<4} {a['elo']:7.0f}  "
                    f"{a['n']:>2} inc. {a['n_tornei']:>2} tor.{tag(a)}")
            ita = [(i, a) for i, a in enumerate(lista, 1) if a["noc"] == "ITA" and i > quanti]
            for i, a in ita:
                log(f"  {i:>2}. {a['nome'][:30]:<30} {a['noc']:<4} {a['elo']:7.0f}  "
                    f"{a['n']:>2} inc. {a['n_tornei']:>2} tor.{tag(a)}  ← Italia")


def scrivi_csv(percorso, intestazione, righe):
    """CSV con il punto e virgola: si apre bene con Excel in italiano."""
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(intestazione)
        w.writerows(righe)


def salva_elenchi(A, esiti, per_page):
    def base(a):
        return [a["id"], a["nome"], a["noc"], disciplina(a["ultimo_gender"], a["ultima_cat"]),
                round(a["elo"]), a["n"], a["n_tornei"], a["livello"]]
    intest = ["ID IJF", "Nome IJF", "NOC IJF", "Ultima categoria", "ELO", "Incontri", "Tornei", "Livello"]
    ordina = lambda pid: (-A[pid]["n"], A[pid]["nome"])
    ab = sorted((p for p, e in esiti.items() if e["esito"] == "abbinato"), key=ordina)
    dc = sorted((p for p, e in esiti.items() if e["esito"] == "da creare"), key=ordina)
    inc = sorted((p for p, e in esiti.items() if e["esito"] == "incerto"), key=ordina)
    scrivi_csv(CSV_ABBINATI, intest + ["Riga Athletes", "NOC Athletes", "Come", "Link"],
               [base(A[p]) + [per_page[esiti[p]["page"]]["nome"], per_page[esiti[p]["page"]]["noc"],
                              esiti[p]["motivo"], link(esiti[p]["page"])] for p in ab])
    scrivi_csv(CSV_DA_CREARE, intest + ["Nome da scrivere in Athletes"],
               [base(A[p]) + [nome_athletes(A[p]["nome"])] for p in dc])
    scrivi_csv(CSV_INCERTI, intest + ["Motivo", "Candidati in Athletes (nome | NOC | categoria | link)"],
               [base(A[p]) + [esiti[p]["motivo"],
                              " || ".join(f"{r['nome']} | {r['noc'] or '-'} | {'/'.join(r['disc']) or '-'} | "
                                          f"{link(r['page'])}" for r in esiti[p]["candidati"][:4])]
                for p in inc])
    return ab, dc, inc


def link(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}" if page_id else ""


def salva_json(A, esiti, tornei, oggi):
    """judo-elo.json: tutto ciò che serve alla pagina (sessione 3)."""
    atleti = []
    for a in sorted(A.values(), key=lambda a: -a["elo"]):
        e = esiti.get(a["id"], {})
        atleti.append({
            "id_ijf": a["id"], "nome": a["nome"], "noc": a["noc"],
            "notion": (e.get("page") or "").replace("-", "") or None,   # stesso formato di judo-performance.json
            "genere": "U" if a["ultimo_gender"] == "Men" else "D", "cat": a["ultima_cat"],
            "elo": round(a["elo"]), "elo_max": round(a["max"]), "livello": a["livello"],
            "incontri": a["n"], "vittorie": a["v"], "tornei": a["n_tornei"], "ultimo": a["ultima"],
            "storico": [[d, v, c] for d, v, c in a["storico"]]})
    dati = {"aggiornato": oggi.isoformat(),
            "regole": {"partenza": ELO_PARTENZA, "k": K_BASE, "soglia_provvisorio": SOGLIA_MOSTRA,
                       "soglia_stabile": SOGLIA_STABILE, "min_tornei": MIN_TORNEI},
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

    log(f"ELO Judo · {'SOLO PROVA: non scrivo nulla su Notion' if solo_prova else 'SCRITTURA su Notion'} "
        f"· data del calcolo {oggi.isoformat()}")

    # 1. lettura
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        incontri, athletes, opzioni = raw["incontri"], raw["athletes"], raw["opzioni"]
    else:
        incontri = leggi_incontri()
        athletes, opzioni = leggi_athletes()
    log(f"Incontri letti dal db Agente Judo: {len(incontri)}")
    log(f"Judoka nel db Athletes (Sport = Judo): {len(athletes)}, "
        f"con ID IJF già compilato: {sum(1 for r in athletes if r['id_ijf'])}")

    # 2. calcolo
    A, scarti, modi, n_validi = calcola_elo(incontri, oggi)
    log(f"Incontri usati nell'ELO: {n_validi}")
    for motivo, n in scarti.most_common():
        log(f"  ATTENZIONE {n} incontri: {motivo}")
    log("Modo di vittoria: " + ", ".join(f"{k} {v}" for k, v in modi.most_common()))
    livelli = Counter(a["livello"] for a in A.values())
    log(f"Judoka: {len(A)} · stabili {livelli['stabile']} · provvisori {livelli['provvisorio']} · "
        f"non mostrati {livelli['nascosto']}")
    tornei = {}
    for m in incontri:
        tornei.setdefault(m["cid"], {"nome": m.get("torneo", ""), "tipo": m["tipo"], "data": m["data"]})
        tornei[m["cid"]]["data"] = min(tornei[m["cid"]]["data"] or m["data"], m["data"] or "9999")

    # 3. abbinamento con Athletes
    esiti = abbina(A, athletes)
    per_page = {r["page"]: r for r in athletes}
    ab, dc, inc = salva_elenchi(A, esiti, per_page)
    log("\n" + "=" * 78)
    log("ABBINAMENTO CON IL DB ATHLETES (§5.9)")
    log("=" * 78)
    log(f"Abbinati: {len(ab)}  ({Counter(esiti[p]['motivo'] for p in ab)})")
    noc_da_compilare = [p for p in ab if not per_page[esiti[p]["page"]]["noc"]]
    if noc_da_compilare:
        log(f"  di cui con NOC vuoto in Athletes, che il lancio vero compilerà: {len(noc_da_compilare)} → "
            + ", ".join(f"{A[p]['nome']} ({A[p]['noc']})" for p in noc_da_compilare[:20]))
    log(f"Da creare: {len(dc)}  (di cui con ELO mostrato nella pagina: "
        f"{sum(1 for p in dc if A[p]['livello'] != 'nascosto')})")
    log(f"Incerti: {len(inc)}  (di cui con ELO mostrato: {sum(1 for p in inc if A[p]['livello'] != 'nascosto')})")
    usate = {esiti[p]["page"] for p in ab}
    log(f"Righe judo di Athletes senza nessun incontro dal 1/1/2026: {len(athletes) - len(usate)} "
        f"(restano senza ELO; tra queste ci sono anche quelle candidate degli incerti)")

    noc_ok = {codice_noc(o): o for o in opzioni["noc"] if codice_noc(o)}
    disc_ok = set(opzioni["disc"])
    senza_noc = Counter(A[p]["noc"] for p in dc if A[p]["noc"] not in noc_ok)
    if senza_noc:
        log("Da creare con NOC vuoto (codice senza opzione in Athletes o atleta neutrale): "
            + ", ".join(f"{k} {v}" for k, v in senza_noc.most_common()))
    log("Da creare per NOC (primi 15): "
        + ", ".join(f"{k} {v}" for k, v in Counter(A[p]["noc"] for p in dc).most_common(15)))
    log(f"Italiani da creare: {', '.join(A[p]['nome'] for p in dc if A[p]['noc'] == 'ITA') or 'nessuno'}")
    log("\nIncerti con ELO mostrato nella pagina (i più importanti da controllare):")
    for p in [p for p in inc if A[p]["livello"] != "nascosto"][:60]:
        a, e = A[p], esiti[p]
        log(f"  · {a['nome']} ({a['noc']}, {disciplina(a['ultimo_gender'], a['ultima_cat'])}, "
            f"{a['n']} inc.) → {e['motivo']}")
    log(f"Elenchi completi nei file {CSV_ABBINATI.name}, {CSV_DA_CREARE.name}, {CSV_INCERTI.name} "
        f"(Artifacts del lancio).")

    stampa_classifiche(A, esiti)
    salva_json(A, esiti, tornei, oggi)
    log(f"\n{FILE_JSON.name}: {len(A)} judoka")

    if solo_prova:
        log("\nProva terminata: non è stato scritto nulla su Notion.")
        return 0

    # 4. scrittura su Notion (solo db Athletes; solo ELO, ID IJF vuoti e righe nuove)
    log("\n" + "=" * 78)
    log("SCRITTURA IN ATHLETES")
    log("=" * 78)
    aggiornate = invariate = create = errori = 0
    interrotto = False
    for p in ab:
        if minuti() > TEMPO_MAX_MINUTI:
            interrotto = True
            break
        a, riga = A[p], per_page[esiti[p]["page"]]
        nuovi = {}
        if riga["elo"] is None or round(riga["elo"]) != round(a["elo"]):
            nuovi["ELO"] = round(a["elo"])
        if not riga["id_ijf"]:
            nuovi["ID IJF"] = a["id"]
        if not riga["noc"] and a["noc"] in noc_ok:      # NOC solo se vuoto (§5.9)
            nuovi["NOC"] = noc_ok[a["noc"]]
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
    for p in dc:
        if interrotto or minuti() > TEMPO_MAX_MINUTI:
            interrotto = True
            break
        a = A[p]
        disc = [d for d in sorted({disciplina(g, k) for g, k in a["cat"]}) if d in disc_ok]
        try:
            page = crea_riga({"nome": nome_athletes(a["nome"]), "id": a["id"], "elo_notion": round(a["elo"]),
                              "noc_notion": noc_ok.get(a["noc"], ""), "disc": disc})
            esiti[p]["page"] = page
            create += 1
            if create % 100 == 0:
                log(f"  ... create {create} righe ({minuti():.0f} minuti)")
            time.sleep(PAUSA_NOTION)
        except RuntimeError as e:
            log(f"  Errore nel creare {a['nome']}: {e}")
            errori += 1
    salva_json(A, esiti, tornei, oggi)           # di nuovo, con gli id delle righe appena create
    log(f"Righe aggiornate: {aggiornate} · invariate: {invariate} · create: {create} · errori: {errori} · "
        f"incerti non scritti: {len(inc)} · minuti: {minuti():.0f}")
    if interrotto:
        log(f"ATTENZIONE: mi sono fermato dopo {TEMPO_MAX_MINUTI:.0f} minuti. Rilancia: le righe già "
            f"scritte risultano abbinate per ID IJF e non vengono duplicate.")
        return 1
    return 1 if errori else 0


if __name__ == "__main__":
    codice = 1
    try:
        codice = main()
    except SystemExit as e:
        codice = e.code if isinstance(e.code, int) else 1
        if not isinstance(e.code, int):
            log(str(e.code))
    except Exception as e:          # qualsiasi errore: lo scrivo nel rapporto
        import traceback
        log(traceback.format_exc())
    finally:
        FILE_RAPPORTO.write_text("\n".join(_righe_log) + "\n", encoding="utf-8")
    sys.exit(codice)
