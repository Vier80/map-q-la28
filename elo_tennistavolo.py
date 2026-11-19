#!/usr/bin/env python3
"""ELO Tennis Tavolo (scheda 42, sessione 2) – repo map-q-la28 · versione 1.0 del 19/11/2026

Stessa struttura dell'ELO badminton (elo_badminton.py 1.1, schede 32-33), con le regole decise da
Gualtiero nel foglio «Tennistavolo LA28 – punti da decidere e verificare» (19/11/2026).

Che cosa fa
-----------
1. Legge da Notion gli incontri del db «🏓 Agente Tennis Tavolo» (scritti dall'agente tennistavolo 1.3),
   tabellone principale E qualificazioni.
2. Calcola un rating ELO incontro dopo incontro:
     - un ELO per ogni giocatore nei singolari (MS, WS) e per ogni COPPIA nei doppi (MD, WD, XD);
     - K = 32 × coefficiente del torneo × peso del turno × 1,5 per i primi 15 incontri;
     - coefficiente del torneo: Mondiali 1,25 · WTT Finals 1,15 · Smash 1,10 · World Cup 1,10 ·
       Champions 1,05 · Star Contender 1,0 · Contender 0,9;
     - peso del turno: finale 100% · semifinale 98% · quarti 96% · turni 3-5 del tabellone 94% ·
       turni 1-2 e gironi del tabellone principale 92% · qualificazioni 90%;
     - walkover (anche «walkover (infortunio)», cioè ritirato prima di giocare): il vincitore non cambia;
       il perdente perde il 7,5% del normale; niente per entrambi al primo turno del tabellone
       principale e nelle qualificazioni;
     - ritiro a partita iniziata: 20%, 40% o 60% della variazione normale secondo il momento
       (partite complete prima del ritiro: 0-1 → 20%, 2-3 → 40%, 4 o più → 60%);
     - squalifica = vittoria normale;
     - nessun margine di vittoria (la versione «lieve» è tra le varianti del rapporto, per decidere);
     - inattività: dopo 70 giorni senza incontri, −2% della distanza da 1500 ogni 30 giorni.
3. Misura quanto bene l'ELO prevede i risultati e confronta alcune varianti dei parametri.
4. Abbina ogni giocatore o coppia a una pagina del db Athletes (Sport = Table Tennis):
     ABBINATI (per ID ITTF, oppure nome + NOC + specialità) · DA CREARE (lo script NON crea pagine) ·
     INCERTI (decide Gualtiero).
5. In «Solo prova» (DRY_RUN=true) NON scrive nulla su Notion: stampa elenchi, classifiche, statistiche
   per le soglie, salva i CSV e tennistavolo_raw.json (copia dei dati letti, per i controlli di Claude).
6. Nel lancio vero scrive in Athletes, SOLO per gli abbinati (pagine già esistenti):
     - «ELO TT» (l'unico campo che viene riscritto);
     - «ID ITTF» solo dove è vuoto;
   e salva tennistavolo-elo.json (ELO, storico, tornei) per la pagina performance (sessione 3).

REGOLA FONDAMENTALE: nessuna operazione su Athletes elimina o sovrascrive dati già inseriti.
La funzione `aggiorna_riga` blocca qualsiasi colonna diversa da «ELO TT» e «ID ITTF».

Uso
---
  NOTION_TOKEN=... DRY_RUN=true python elo_tennistavolo.py       Solo prova
  NOTION_TOKEN=... DRY_RUN=false python elo_tennistavolo.py      lancio vero
  python elo_tennistavolo.py --da-raw tennistavolo_raw.json       collaudo con dati salvati (non tocca Notion)

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
DS_TT = "41df48c9-aad9-817f-98ea-000bc2c69bc1"         # data source del db «🏓 Agente Tennis Tavolo»
DS_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"   # data source del db Athletes
NOMI_DB = {DS_TT: "🏓 Agente Tennis Tavolo", DS_ATHLETES: "Athletes"}

# Nomi ESATTI delle colonne del db Agente Tennis Tavolo (creato da Claude il 19/11/2026, scheda 41)
COL_T = {"uid": "ID Univoco", "id1": "ID ITTF 1", "id2": "ID ITTF 2",          # 1 = vincitore, 2 = sconfitto
         "p1": "Player 1", "p2": "Player 2", "noc1": "NOC 1", "noc2": "NOC 2",
         "disc": "Disciplina", "score": "Score", "turno": "Turno", "tab": "Tabellone", "data": "Data",
         "cat": "Categoria", "torneo": "Torneo"}
# Nomi ESATTI delle proprietà di Athletes (ID ITTF ed ELO TT: decisi il 19/11/2026, da creare in Notion)
COL_A = {"nome": "Cognome e Nome", "sport": "Sport", "noc": "NOC", "disc": "Disciplina",
         "id_ittf": "ID ITTF", "elo": "ELO TT"}
COLONNE_NUOVE_A = {"ID ITTF", "ELO TT"}     # se mancano: in prova solo avviso, nel lancio vero stop
SPORT_ATHLETES = "Table Tennis"
# Campi di Athletes che lo script può scrivere in una pagina esistente
SCRIVIBILI_SEMPRE = {"ELO TT"}        # valore calcolato, appartiene allo script
SCRIVIBILI_SE_VUOTI = {"ID ITTF"}     # solo se la cella è vuota

# Le 5 specialità: sigla nel db Agente Tennis Tavolo -> Disciplina in Athletes (verificato il 19/11/2026)
SPECIALITA = {"MS": "🏓Men's Singles", "WS": "🏓Women's Singles", "MD": "🏓Men's Doubles",
              "WD": "🏓Women's Doubles", "XD": "🏓Mixed Doubles"}
DOPPI = {"MD", "WD", "XD"}
# Riconosce la specialità di Athletes anche senza emoji, con spazi o maiuscole diverse
# («🏓MixedTeam» non corrisponde a nessuna e viene ignorata: la gara a squadre non ha ELO)
RE_SPECIALITA = re.compile(r"(Men's|Women's|Mixed)\s+(Singles|Doubles)", re.I)
SIGLA_DA_TESTO = {("men's", "singles"): "MS", ("women's", "singles"): "WS", ("men's", "doubles"): "MD",
                  ("women's", "doubles"): "WD", ("mixed", "doubles"): "XD"}

# --- regole di calcolo (foglio delle decisioni, 19/11/2026) ---
ELO_PARTENZA = 1500
K_BASE = 32
COEFF_TORNEO = {                      # chiave = valore della colonna «Categoria»
    "Mondiali": 1.25, "WTT Finals": 1.15, "Smash": 1.10, "World Cup": 1.10,
    "Champions": 1.05, "Star Contender": 1.0, "Contender": 0.9,
}
PESO_FINALE, PESO_SEMI, PESO_QUARTI = 1.00, 0.98, 0.96
PESO_TURNI_1_2 = 0.92                 # turni 1 e 2 del tabellone principale, e i suoi gironi
PESO_TURNI_3_5 = 0.94                 # turni 3, 4 e 5 del tabellone principale
PESO_QUALIFICAZIONI = 0.90            # tutte le partite di qualificazione
PESO_ALTRI = 0.95                     # qualsiasi altro turno (oggi non ce ne sono)
# Turni «numerati»: si contano dal primo presente nel tabellone di quella specialità in quel torneo
TURNI_NUMERATI = ["Round of 128", "Round of 64", "Round of 32", "Round of 16"]
GIRONE = "Group Stage"
QUALIFICAZIONE = "Qualificazione"     # valore della colonna «Tabellone»
# Walkover e ritiri
QUOTA_WALKOVER_PERDENTE = 0.075       # il perdente perde il 7,5% del normale; il vincitore non cambia
QUOTA_RITIRO = {1: 0.20, 2: 0.40, 3: 0.60}   # momento del ritiro (1 = presto, 3 = tardi) -> quota
SOGLIA_NUOVO = 15                     # sotto i 15 incontri il K si moltiplica per...
MOLT_NUOVO = 1.5                      # ... 1,5 (chi parte da 1500 si avvicina prima al suo livello)
GIORNI_SENZA_EFFETTO = 70             # inattività: nessun effetto per 70 giorni...
GIORNI_PER_CALO = 30                  # ... poi ogni 30 giorni interi...
CALO = 0.02                           # ... -2% della distanza da 1500
# Soglie per mostrare l'ELO nella pagina: di partenza come il badminton, da confermare dopo la Solo prova
SOGLIA_MOSTRA = 10                    # da 10 incontri (e MIN_TORNEI tornei) l'ELO è «provvisorio»
SOGLIA_STABILE = 20                   # da 20 incontri è «stabile»
MIN_TORNEI = 3
# Data da cui si misura la bontà delle previsioni (circa l'ultimo terzo dei dati)
DATA_VERIFICA = "2026-05-01"

# Ordine dei turni nella stessa data: prima le qualificazioni, poi il tabellone
ORDINE_TURNI = {"Qualifying Group": 0, "Qualifying Round 1": 1, "Qualifying Round 2": 2,
                "Qualifying Round 3": 3, "Qualifying Round 4": 4, "Qualification Elimination Round": 5,
                GIRONE: 6, "Round of 128": 7, "Round of 64": 8, "Round of 32": 9, "Round of 16": 10,
                "Quarter Final": 11, "Semi Final": 12, "Final": 13}

# Sigle dei titoli che in Athletes possono stare nel nome (es. «... WC»): non fanno parte del nome
TITOLI = {"WC", "OLY", "OC", "EC"}
# Lettere che la scomposizione degli accenti non trasforma: le trascrivo a mano
TRASCRIZIONI = {"Ø": "O", "Æ": "AE", "Œ": "OE", "ẞ": "SS", "Ð": "D", "Đ": "D", "Ł": "L", "Þ": "TH"}
# Gran Bretagna: il sito WTT usa le quattro nazioni (ENG, WAL...), Athletes a volte GBR
NAZIONI_GB = {"ENG", "SCO", "WAL", "NIR"}
# Atleti neutrali: il sito WTT scrive AIN; in Athletes possono essere RUS o BLR (e dal 2026 il sito usa RUS)
NEUTRALI = {"AIN": {"RUS", "BLR"}}

PAUSA_NOTION = 0.35
LIMITE_NOTION = 10000   # una ricerca dell'API Notion restituisce al massimo 10.000 righe
TEMPO_MAX_MINUTI = float(os.getenv("TEMPO_MAX_MINUTI", "").strip() or 165)

FILE_JSON = CARTELLA / "tennistavolo-elo.json"
FILE_RAPPORTO = CARTELLA / "rapporto_elo_tennistavolo.txt"
FILE_RAW = CARTELLA / "tennistavolo_raw.json"
CSV_ABBINATI = CARTELLA / "tennistavolo_elo_abbinati.csv"
CSV_DA_CREARE = CARTELLA / "tennistavolo_elo_da_creare.csv"
CSV_INCERTI = CARTELLA / "tennistavolo_elo_incerti.csv"


# ====================================================================== LOG
_righe_log = []


def log(testo=""):
    """Stampa a video e conserva la riga per il file rapporto_elo_tennistavolo.txt."""
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
    if t == "url":
        return p.get("url")
    return None


def interroga(ds, filtro=None, etichetta=""):
    """Tutte le righe di un data source (100 alla volta) che rispettano il filtro.

    Se la ricerca arriva a 10.000 righe (limite dell'API Notion) lo script si ferma: le righe
    oltre la 10.000ª non verrebbero lette e l'ELO sarebbe calcolato su dati incompleti.
    """
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
            break
        cursore = r["next_cursor"]
    if len(pagine) >= LIMITE_NOTION:
        sys.exit(f'ERRORE: la ricerca "{etichetta or NOMI_DB.get(ds, ds)}" ha restituito {len(pagine)} righe, '
                 f"cioè il limite dell'API Notion: alcune righe non sono state lette. Bisogna dividere "
                 f"ancora la lettura (per esempio per specialità e tabellone).")
    return pagine


def controlla_colonne(ds, attese, facoltative=()):
    """Legge lo schema del db; si ferma se manca una colonna obbligatoria.
    Restituisce (proprietà, elenco delle colonne facoltative mancanti)."""
    props = chiama("GET", f"data_sources/{ds}")["properties"]
    mancanti = [c for c in attese if c not in props and c not in facoltative]
    if mancanti:
        sys.exit(f'ERRORE: nel db "{NOMI_DB[ds]}" non trovo le colonne: {", ".join(mancanti)}')
    return props, [c for c in facoltative if c not in props]


def fette_incontri():
    """Le ricerche in cui è divisa la lettura del db Agente Tennis Tavolo: [(etichetta, filtro), ...].

    - 5 ricerche, una per specialità (la più grande, MS, aveva 3.924 righe il 19/11/2026);
    - 1 ricerca «di controllo» per le righe con Disciplina vuota o scritta in modo diverso.
    Insieme coprono tutto il db; una pagina trovata due volte viene contata una volta sola.
    """
    c = COL_T["disc"]
    fette = [(s, {"property": c, "select": {"equals": s}}) for s in SPECIALITA]
    altre = {"or": [{"property": c, "select": {"is_empty": True}},
                    {"and": [{"property": c, "select": {"does_not_equal": s}} for s in SPECIALITA]}]}
    fette.append(("altre (Disciplina vuota o diversa)", altre))
    return fette


def leggi_incontri():
    """Righe del db Agente Tennis Tavolo nel formato interno dello script (lettura divisa per specialità)."""
    controlla_colonne(DS_TT, COL_T.values())
    incontri, visti, conteggi = [], set(), []
    for etichetta, filtro in fette_incontri():
        pagine = interroga(DS_TT, filtro, f"Agente Tennis Tavolo, {etichetta}")
        conteggi.append((etichetta, len(pagine)))
        for pg in pagine:
            if pg["id"] in visti:
                continue
            visti.add(pg["id"])
            p = pg["properties"]
            incontri.append({k: (valore(p.get(c)) or "") for k, c in COL_T.items()})
    log(f"Lettura del db Agente Tennis Tavolo in {len(conteggi)} ricerche (la più grande: "
        f"{max(n for _, n in conteggi)} righe; limite di Notion {LIMITE_NOTION}):")
    log("  " + " · ".join(f"{e} {n}" for e, n in conteggi))
    return incontri


def leggi_athletes():
    """Pagine di tennistavolo del db Athletes (Sport = Table Tennis), opzioni di Disciplina e
    colonne nuove ancora mancanti (ID ITTF, ELO TT)."""
    props, mancanti = controlla_colonne(DS_ATHLETES, COL_A.values(), COLONNE_NUOVE_A)
    opzioni = {"disc": [o["name"] for o in props[COL_A["disc"]]["multi_select"]["options"]]}
    atleti = []
    for pg in interroga(DS_ATHLETES, {"property": COL_A["sport"], "select": {"equals": SPORT_ATHLETES}},
                        f"Athletes, Sport = {SPORT_ATHLETES}"):
        p = pg["properties"]
        atleti.append({"page": pg["id"].replace("-", ""), "nome": valore(p.get(COL_A["nome"])) or "",
                       "noc": valore(p.get(COL_A["noc"])) or "", "disc": valore(p.get(COL_A["disc"])) or [],
                       "id_ittf": (valore(p.get(COL_A["id_ittf"])) or "").strip(),
                       "elo": valore(p.get(COL_A["elo"]))})
    return atleti, opzioni, mancanti


def aggiorna_riga(atleta, nuovi):
    """Scrive in una pagina ESISTENTE di Athletes rispettando la regola fondamentale.

    nuovi = {nome colonna: valore}. Rifiuta qualsiasi colonna non ammessa e salta «ID ITTF»
    quando la cella contiene già qualcosa.
    """
    props = {}
    for col, val in nuovi.items():
        if col in SCRIVIBILI_SEMPRE:
            props[col] = {"number": val}
        elif col in SCRIVIBILI_SE_VUOTI:
            if atleta["id_ittf"]:
                continue                     # la cella è già compilata: non la tocco
            props[col] = {"rich_text": [{"text": {"content": str(val)}}]}
        else:
            raise RuntimeError(f"tentativo di scrivere la colonna non ammessa '{col}': bloccato")
    if props:
        chiama("PATCH", f"pages/{atleta['page']}", {"properties": props})
    return bool(props)


# ====================================================================== LETTURA DELLO SCORE
RE_PARTITA = re.compile(r"(\d+)\s*-\s*(\d+)")


def partita_conclusa(a, b):
    """True se una partita (game) di tennistavolo è finita: almeno 11 punti con 2 di scarto."""
    return max(a, b) >= 11 and abs(a - b) >= 2


def momento_ritiro(partite):
    """Momento del ritiro dalle partite giocate prima: 0-1 complete -> 1, 2-3 -> 2, 4 o più -> 3."""
    complete = sum(1 for a, b in partite if partita_conclusa(a, b))
    return 1 if complete <= 1 else (2 if complete <= 3 else 3)


def esito(score):
    """Legge lo Score scritto dall'agente e restituisce (tipo, momento del ritiro, partite vinte, perse).

    tipo = "normale" | "walkover" | "ritiro" | "illeggibile".
    Formati dell'agente 1.3: "4-1 (11-5, 11-8, ...)", "walkover", "walkover (infortunio)",
    "ritiro (11-3)", "squalifica (11-6, 11-3, 11-9)".
    """
    s = (score or "").strip().lower()
    if s.startswith("walkover"):
        return "walkover", None, 0, 0
    dentro = s[s.find("(") + 1:] if "(" in s else ""
    partite = [(int(a), int(b)) for a, b in RE_PARTITA.findall(dentro)]
    if s.startswith("squalifica"):
        return "normale", None, 0, 0       # decisione di Gualtiero: come una vittoria normale
    if s.startswith("ritiro"):
        return "ritiro", momento_ritiro(partite), 0, 0
    m = re.match(r"^(\d+)\s*-\s*(\d+)\s*\(", s)
    if m:
        return "normale", None, int(m.group(1)), int(m.group(2))
    return "illeggibile", None, 0, 0


# ====================================================================== CALCOLO ELO
def torneo_di(uid):
    """'WTT|3246|TTEMSINGLES-----------FNL-000100' -> '3246' (codice WTT del torneo)."""
    parti = (uid or "").split("|")
    return parti[1] if len(parti) > 2 else ""


def primi_turni(incontri):
    """Per ogni (torneo, specialità) il primo turno «numerato» presente nel tabellone principale.

    Es. Champions con tabellone da 32 -> «Round of 32»; Smash -> «Round of 64»; Mondiali -> «Round of 128»;
    WTT Finals e World Cup (gironi + eliminazione) -> «Round of 16».
    """
    primo = {}
    for m in incontri:
        if m["turno"] in TURNI_NUMERATI and m["tab"] != QUALIFICAZIONE:
            chiave = (torneo_di(m["uid"]), m["disc"])
            i = TURNI_NUMERATI.index(m["turno"])
            primo[chiave] = min(primo.get(chiave, 99), i)
    return primo


def numero_turno(m, primo):
    """Numero del turno nel tabellone principale (1 = primo turno); None per gironi, quarti, semi, finale."""
    if m["turno"] not in TURNI_NUMERATI:
        return None
    i0 = primo.get((torneo_di(m["uid"]), m["disc"]))
    if i0 is None:
        return None
    return TURNI_NUMERATI.index(m["turno"]) - i0 + 1


def peso_turno(m, primo):
    """Peso del turno (foglio delle decisioni, punto 19)."""
    if m["tab"] == QUALIFICAZIONE:
        return PESO_QUALIFICAZIONI
    t = m["turno"]
    if t == "Final":
        return PESO_FINALE
    if t == "Semi Final":
        return PESO_SEMI
    if t == "Quarter Final":
        return PESO_QUARTI
    if t == GIRONE:
        return PESO_TURNI_1_2
    if t in TURNI_NUMERATI:
        n = numero_turno(m, primo)
        if n is not None and n <= 2:
            return PESO_TURNI_1_2
        if n is not None and n <= 5:
            return PESO_TURNI_3_5
    return PESO_ALTRI


def filtra(incontri):
    """Tiene gli incontri utilizzabili; restituisce (validi ordinati, scarti per motivo, primi turni)."""
    scarti, validi = Counter(), []
    primo = primi_turni([m for m in incontri if m.get("turno")])
    for m in incontri:
        tipo, momento, vinte, perse = esito(m["score"])
        if tipo == "illeggibile":
            scarti[f"punteggio non riconosciuto: '{m['score']}'"] += 1
        elif not m["id1"] or not m["id2"]:
            scarti["manca un ID ITTF"] += 1
        elif m["id1"] == m["id2"]:
            scarti["stesso ID ITTF nei due lati"] += 1
        elif m["cat"] not in COEFF_TORNEO:
            scarti[f"Categoria sconosciuta: '{m['cat']}'"] += 1
        elif m["disc"] not in SPECIALITA:
            scarti[f"Disciplina sconosciuta: '{m['disc']}'"] += 1
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["data"] or ""):
            scarti["data mancante"] += 1
        else:
            if m["turno"] not in ORDINE_TURNI:
                scarti[f"turno non previsto (peso {PESO_ALTRI:.0%}, tenuto): '{m['turno']}'"] += 1
            n = numero_turno(m, primo)
            validi.append(dict(m, tipo=tipo, momento=momento, vinte=vinte, perse=perse,
                               peso=peso_turno(m, primo),
                               # walkover senza penalità: primo turno del principale o qualificazioni
                               primo_turno=(n == 1 or m["tab"] == QUALIFICAZIONE),
                               torneo_id=torneo_di(m["uid"])))
    validi.sort(key=lambda m: (m["data"], ORDINE_TURNI.get(m["turno"], 6.5), m["uid"]))
    return validi, scarti, primo


def con_inattivita(rating, ultima, giorno):
    """Calo per inattività tra la data `ultima` e la data `giorno`.

    Nessun effetto per 70 giorni; poi, per ogni 30 giorni interi in più, la distanza da 1500
    si riduce del 2%. Esempio: 1700 fermo da 130 giorni -> 2 periodi -> 1500 + 200 × 0,98² = 1692.
    """
    if not ultima:
        return rating
    giorni = (dt.date.fromisoformat(giorno) - dt.date.fromisoformat(ultima)).days
    periodi = (giorni - GIORNI_SENZA_EFFETTO) // GIORNI_PER_CALO if giorni > GIORNI_SENZA_EFFETTO else 0
    if periodi <= 0:
        return rating
    return ELO_PARTENZA + (rating - ELO_PARTENZA) * (1 - CALO) ** periodi


def quota(m, lato):
    """Quota della variazione normale per il vincitore (lato 'w') o il perdente (lato 'l')."""
    if m["tipo"] == "walkover":
        if lato == "w":
            return 0.0                     # il vincitore non cambia
        return 0.0 if m["primo_turno"] else QUOTA_WALKOVER_PERDENTE
    if m["tipo"] == "ritiro":
        return QUOTA_RITIRO[m["momento"]]
    return 1.0


def mov_lieve(m):
    """Variante «MoV lieve» (solo per il confronto nel rapporto): conta lo scarto di partite.

    d = partite vinte − perse, diviso per le partite che servivano per vincere (3 o 4):
    3-2 o 4-3 vale circa 1,0; 3-0 o 4-0 vale 1,10. Il valore viene poi diviso per la media di tutti
    gli incontri, così il K medio non cambia (come nella scherma).
    """
    if m["tipo"] != "normale" or not m["vinte"]:
        return 1.0
    return 0.95 + 0.15 * (m["vinte"] - m["perse"]) / m["vinte"]


def calcola_elo(validi, oggi, k_base=K_BASE, usa_turno=True, usa_torneo=True, usa_mov=False,
                verifica_da=None):
    """Calcola l'ELO di tutti i giocatori (singolari) e di tutte le coppie (doppi).

    Restituisce (dizionario (ID ITTF, specialità) -> scheda, statistiche delle previsioni).
    Le previsioni si misurano solo sugli incontri giocati per intero dal `verifica_da`, quando
    entrambi avevano già almeno SOGLIA_MOSTRA incontri.
    I walkover cambiano solo l'ELO del perdente e NON contano come incontri giocati.
    """
    A = {}
    prev = {"n": 0, "giuste": 0, "brier": 0.0, "logloss": 0.0}
    media_mov = 1.0
    if usa_mov:
        valori = [mov_lieve(m) for m in validi if m["tipo"] == "normale"]
        media_mov = sum(valori) / len(valori) if valori else 1.0

    def scheda(pid, disc, nome, noc):
        chiave = (pid, disc)
        a = A.get(chiave)
        if a is None:
            a = A[chiave] = {"id": pid, "disc": disc, "nome": nome, "noc": noc,
                             "rating": float(ELO_PARTENZA), "n": 0, "v": 0, "wo": 0, "ritiri": 0,
                             "ultima": None, "tornei": [], "storico": [], "max": float(ELO_PARTENZA),
                             "nocs": set()}
        a["nome"], a["noc"] = nome or a["nome"], noc or a["noc"]     # tengo i dati più recenti
        a["nocs"].update(x for x in (noc or "").split("/") if x)    # tutti i NOC visti (AIN -> RUS...)
        return a

    for m in validi:
        w = scheda(m["id1"], m["disc"], m["p1"], m["noc1"])    # vincitore
        l = scheda(m["id2"], m["disc"], m["p2"], m["noc2"])    # perdente
        for x in (w, l):
            x["rating"] = con_inattivita(x["rating"], x["ultima"], m["data"])
        rw, rl = w["rating"], l["rating"]                      # rating PRIMA dell'incontro
        atteso_w = 1 / (1 + 10 ** ((rl - rw) / 400))          # probabilità che vinca chi ha vinto
        giocato = m["tipo"] != "walkover"
        if (verifica_da and m["tipo"] == "normale" and m["data"] >= verifica_da
                and w["n"] >= SOGLIA_MOSTRA and l["n"] >= SOGLIA_MOSTRA):
            prev["n"] += 1
            prev["giuste"] += 1 if atteso_w > 0.5 else (0.5 if atteso_w == 0.5 else 0)
            prev["brier"] += (1 - atteso_w) ** 2
            prev["logloss"] += -math.log(max(atteso_w, 1e-9))
        peso = m["peso"] if usa_turno else 1.0
        torneo = COEFF_TORNEO[m["cat"]] if usa_torneo else 1.0
        mov = mov_lieve(m) / media_mov if usa_mov else 1.0
        for x, r_io, r_avv, s, lato in ((w, rw, rl, 1, "w"), (l, rl, rw, 0, "l")):
            atteso = 1 / (1 + 10 ** ((r_avv - r_io) / 400))
            k = k_base * torneo * peso * mov * (MOLT_NUOVO if x["n"] < SOGLIA_NUOVO else 1)
            x["rating"] = r_io + k * (s - atteso) * quota(m, lato)
            x["max"] = max(x["max"], x["rating"])
            if not giocato:
                x["wo"] += 1
                continue                   # walkover: non è un incontro giocato
            x["n"] += 1
            x["v"] += s
            x["ritiri"] += 1 if m["tipo"] == "ritiro" else 0
            x["ultima"] = m["data"]
            if m["torneo_id"] not in x["tornei"]:
                x["tornei"].append(m["torneo_id"])
            # storico: un punto per torneo (il valore dopo l'ultimo incontro di quel torneo)
            if x["storico"] and x["storico"][-1][2] == m["torneo_id"]:
                x["storico"][-1] = [m["data"], round(x["rating"]), m["torneo_id"]]
            else:
                x["storico"].append([m["data"], round(x["rating"]), m["torneo_id"]])

    for a in A.values():
        a["elo"] = con_inattivita(a["rating"], a["ultima"], oggi.isoformat())
        a["n_tornei"] = len(a["tornei"])
        a["livello"] = livello_elo(a["n"], a["n_tornei"])
    return A, prev


def livello_elo(n, tornei, mostra=None, stabile=None, min_tornei=None):
    """'nascosto' / 'provvisorio' / 'stabile' secondo le soglie."""
    mostra = SOGLIA_MOSTRA if mostra is None else mostra
    stabile = SOGLIA_STABILE if stabile is None else stabile
    min_tornei = MIN_TORNEI if min_tornei is None else min_tornei
    if n < mostra or tornei < min_tornei:
        return "nascosto"
    return "provvisorio" if n < stabile else "stabile"


def testo_previsioni(prev):
    if not prev["n"]:
        return "nessun incontro da valutare"
    return (f"{prev['n']} incontri · favorito vincente {100 * prev['giuste'] / prev['n']:.1f}% · "
            f"Brier {prev['brier'] / prev['n']:.4f} · log-loss {prev['logloss'] / prev['n']:.4f}")


# ====================================================================== NOMI E ABBINAMENTO
def lettere(testo):
    """Tiene solo lettere vere e spazi; toglie apici (²ˣᵒᶜ), emoji, punteggiatura e titoli (WC, OLY...)."""
    out = []
    for ch in testo or "":
        cat = unicodedata.category(ch)
        if cat in ("Lu", "Ll", "Lt", "Lo"):     # NON "Lm": ˣ ᵒ ᶜ ʷ sono lettere-apice decorative
            out.append(ch)
        else:
            out.append(" ")                     # spazi, trattini, punti, apostrofi, emoji, cifre
    return " ".join(p for p in "".join(out).split() if p not in TITOLI)


def senza_accenti(testo):
    """Maiuscolo, senza accenti e con le lettere speciali trascritte, per confrontare i nomi.
    «BØJE», «BOEJE» e «BOJE» danno tutti «BOJE»; le coppie AE, OE, UE diventano A, O, U su
    ENTRAMBI i nomi confrontati, quindi due nomi uguali restano uguali."""
    t = unicodedata.normalize("NFKD", (testo or "").upper())
    t = "".join(TRASCRIZIONI.get(c, c) for c in t if not unicodedata.combining(c))
    t = t.replace("SS", "S")
    for doppia, semplice in (("AE", "A"), ("OE", "O"), ("UE", "U")):
        t = t.replace(doppia, semplice)
    return t


def parti_nome(nome):
    """Divide il nome di UN giocatore in (COGNOME, Nome, parole in ordine alfabetico, insieme delle parole).

    Il cognome si riconosce dalle MAIUSCOLE, quindi vale sia per «LIN Yun-Ju» sia per «Felix LEBRUN».
    Spazi, trattini e accenti non contano: «Yun-Ju» e «Yun Ju» coincidono.
    """
    parole = lettere(nome).split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    if not cognome or not altri:
        cognome, altri = parole, []
    c = senza_accenti("".join(cognome))
    n = senza_accenti("".join(altri))
    insieme = "".join(sorted(senza_accenti(p) for p in parole))
    return c, n, insieme, frozenset(senza_accenti(p) for p in parole)


def giocatori(nome):
    """'LIN Shidong / KUAI Man' oppure 'LIN Shidong/KUAI Man' -> lista di parti_nome."""
    return [parti_nome(x) for x in (nome or "").split("/") if lettere(x).strip()]


def simile(x, y):
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def confronta_giocatore(g1, g2):
    """'esatto', 'simile' o None tra due giocatori (ciascuno = parti_nome)."""
    c, n, ins, parole = g1
    rc, rn, rins, rparole = g2
    if (c == rc and n == rn) or (ins and ins == rins) or (c + n and c + n in (rc + rn, rn + rc)):
        return "esatto"
    corto, lungo = sorted((parole, rparole), key=len)
    if len(corto) >= 2 and corto < lungo:
        return "simile"
    if c == rc and (not n or not rn or n.startswith(rn) or rn.startswith(n) or simile(n, rn) >= 0.75):
        return "simile"
    if n and n == rn and (simile(c, rc) >= 0.8 or c in rc or rc in c or sorted(c) == sorted(rc)):
        return "simile"     # stesso nome, cognome simile o con le lettere scambiate («QIU» / «QUI»)
    if simile(c + n, rc + rn) >= 0.88 or simile(ins, rins) >= 0.9:
        return "simile"
    return None


def confronta(gs1, gs2):
    """Confronta due liste di giocatori (singolo o coppia), in qualunque ordine.
    'esatto' se tutti coincidono esattamente; 'simile' se ognuno è almeno simile; altrimenti None."""
    if len(gs1) != len(gs2) or not gs1:
        return None
    ordini = [gs2] if len(gs2) == 1 else [gs2, list(reversed(gs2))]
    migliore = None
    for altro in ordini:
        esiti_g = [confronta_giocatore(a, b) for a, b in zip(gs1, altro)]
        if all(e == "esatto" for e in esiti_g):
            return "esatto"
        if all(esiti_g):
            migliore = "simile"
    return migliore


def codice_noc(valore_noc):
    """'🇮🇹ITA' -> 'ITA' (ultime tre lettere maiuscole)."""
    m = re.search(r"([A-Z]{2,3})$", valore_noc or "")
    return m.group(1) if m else ""


def noc_compatibile(codice_athletes, nocs_sito):
    """True se il NOC di Athletes va bene per i NOC del sito WTT (per le coppie miste ne basta uno).

    NOC vuoto in Athletes: va bene. GBR vale per ENG, SCO, WAL, NIR (e viceversa).
    Neutrali: AIN sul sito vale per RUS o BLR in Athletes.
    """
    if not codice_athletes or codice_athletes in nocs_sito:
        return True
    if codice_athletes == "GBR" and nocs_sito & NAZIONI_GB:
        return True
    if codice_athletes in NAZIONI_GB and "GBR" in nocs_sito:
        return True
    return any(codice_athletes in NEUTRALI.get(n, set()) for n in nocs_sito)


def specialita_athletes(disc):
    """Disciplina (multi-select) di una pagina di Athletes -> insieme di sigle (MS, WS, MD, WD, XD)."""
    out = set()
    for d in disc:
        m = RE_SPECIALITA.search(d or "")
        if m:
            out.add(SIGLA_DA_TESTO[(m.group(1).lower(), m.group(2).lower())])
    return out


def abbina(A, athletes):
    """Divide giocatori e coppie in abbinati / da creare / incerti (stesso metodo del badminton).

    Restituisce un dizionario  (ID ITTF, specialità) -> {"esito", "page", "motivo", "candidati"}.
      1. pagina di Athletes con lo stesso ID ITTF -> abbinato;
      2. una sola pagina con lo stesso nome (nei doppi: gli stessi due giocatori, in qualunque ordine),
         la stessa specialità e un NOC compatibile (o vuoto in Athletes) -> abbinato;
      3. pagine con nome simile, o stesso nome ma specialità o NOC diversi -> incerto;
      4. nessuna pagina somigliante -> da creare (lo script non la crea).
    """
    per_id = defaultdict(list)
    for r in athletes:
        if r["id_ittf"]:
            per_id[r["id_ittf"]].append(r)
    liberi = []
    for r in athletes:
        if r["id_ittf"]:
            continue                         # pagina già collegata a un ID ITTF: non è candidata per il nome
        r["_spec"] = specialita_athletes(r["disc"])
        r["_gioc"] = giocatori(r["nome"])
        r["_codice"] = codice_noc(r["noc"])
        if r["_gioc"]:
            liberi.append(r)

    esiti, certi_per_riga = {}, defaultdict(list)
    for chiave, a in A.items():
        pid, spec = chiave
        if pid in per_id:
            righe = per_id[pid]
            esiti[chiave] = ({"esito": "abbinato", "page": righe[0]["page"], "motivo": "ID ITTF", "candidati": righe}
                             if len(righe) == 1 else
                             {"esito": "incerto", "page": None, "candidati": righe,
                              "motivo": f"ID ITTF presente in {len(righe)} pagine di Athletes"})
            continue
        gs = giocatori(a["nome"])
        nocs = set(a["nocs"]) or {x for x in (a["noc"] or "").split("/") if x}
        esatti, simili = [], []
        for r in liberi:
            e = confronta(gs, r["_gioc"])
            if e == "esatto":
                esatti.append(r)
            elif e == "simile":
                simili.append(r)
        buoni = [r for r in esatti if noc_compatibile(r["_codice"], nocs) and spec in r["_spec"]]
        if len(buoni) == 1 and len(esatti) == 1:
            come = "nome + NOC + specialità" if buoni[0]["_codice"] else "nome + specialità (NOC vuoto in Athletes)"
            esiti[chiave] = {"esito": "abbinato", "page": buoni[0]["page"], "motivo": come, "candidati": buoni}
            certi_per_riga[buoni[0]["page"]].append(chiave)
        elif esatti or simili:
            motivi = []
            for r in esatti:
                diff = []
                if not noc_compatibile(r["_codice"], nocs):
                    diff.append(f"NOC {r['_codice']}")
                if spec not in r["_spec"]:
                    diff.append("specialità diversa")
                motivi.append("stesso nome" + (", ma " + " e ".join(diff) if diff else ""))
            if len(esatti) > 1:
                motivi.insert(0, f"{len(esatti)} pagine con lo stesso nome")
            if simili:
                motivi.append("nome simile: " + ", ".join(r["nome"] for r in simili[:3]))
            esiti[chiave] = {"esito": "incerto", "page": None, "motivo": "; ".join(motivi),
                             "candidati": esatti + simili}
        else:
            esiti[chiave] = {"esito": "da creare", "page": None, "motivo": "nessuna pagina somigliante",
                             "candidati": []}
    # due giocatori/coppie diversi abbinati con certezza alla STESSA pagina: nessuno dei due è certo
    for page, chiavi in certi_per_riga.items():
        if len(chiavi) > 1:
            for k in chiavi:
                esiti[k].update(esito="incerto", page=None,
                                motivo=f"{len(chiavi)} giocatori o coppie WTT con lo stesso nome e la stessa specialità")
    # una pagina già presa con certezza non è più candidata per gli altri
    prese = {e["page"] for e in esiti.values() if e["esito"] == "abbinato"}
    for e in esiti.values():
        if e["esito"] != "incerto" or e["motivo"].startswith("ID ITTF"):
            continue
        rimasti = [r for r in e["candidati"] if r["page"] not in prese]
        if not rimasti:
            e.update(esito="da creare", motivo="l'unica pagina somigliante è già abbinata a un altro",
                     candidati=[])
        else:
            e["candidati"] = rimasti
    return esiti


# ====================================================================== USCITE
def nome_athletes(nome_sito):
    """'LIN Shidong / KUAI Man' -> 'LIN Shidong/KUAI Man' (coppia = una pagina, nomi con '/')."""
    return "/".join(x.strip() for x in nome_sito.split("/"))


def tag(a):
    return {"stabile": "", "provvisorio": " (provvisorio)", "nascosto": " [non mostrato]"}[a["livello"]]


def stampa_classifiche(A, quanti=10):
    log("\n" + "=" * 78)
    log(f"CLASSIFICA ELO DI PROVA (primi {quanti} per specialità, solo ELO mostrati; italiani sempre)")
    log("=" * 78)
    for spec in SPECIALITA:
        lista = sorted((a for a in A.values() if a["disc"] == spec and a["livello"] != "nascosto"),
                       key=lambda a: -a["elo"])
        log(f"\n{spec}  ({len(lista)} con ELO mostrato)")
        for i, a in enumerate(lista, 1):
            ita = "ITA" in (a["noc"] or "").split("/")
            if i <= quanti or ita:
                segno = "  ← Italia" if ita and i > quanti else ""
                log(f"  {i:>3}. {a['nome'][:42]:<42} {a['noc']:<7} {a['elo']:7.0f}  "
                    f"{a['n']:>3} inc. {a['n_tornei']:>2} tornei{tag(a)}{segno}")
    italiani = [a for a in A.values() if "ITA" in (a["noc"] or "").split("/") and a["livello"] == "nascosto"]
    if italiani:
        log("\nItaliani con ELO non ancora mostrato: " + "; ".join(
            f"{a['nome']} ({a['disc']}, {a['n']} inc., {a['n_tornei']} tornei, ELO {a['elo']:.0f})"
            for a in sorted(italiani, key=lambda a: -a["n"])))


def stampa_soglie(A):
    """Quanti ELO si vedrebbero con soglie diverse: serve a sceglierle dopo la Solo prova."""
    log("\n" + "=" * 78)
    log("SCELTA DELLE SOGLIE: giocatori/coppie con ELO mostrato (provvisorio + stabile) e stabili")
    log("=" * 78)
    combinazioni = [(6, 12, 2), (8, 15, 2), (10, 20, 3), (12, 25, 3), (15, 30, 4)]
    log("  soglie (mostra / stabile / tornei minimi)   " + "   ".join(f"{s:>5}" for s in SPECIALITA))
    for mostra, stabile, min_t in combinazioni:
        celle = []
        for spec in SPECIALITA:
            lv = [livello_elo(a["n"], a["n_tornei"], mostra, stabile, min_t) for a in A.values() if a["disc"] == spec]
            celle.append(f"{lv.count('provvisorio') + lv.count('stabile')}/{lv.count('stabile')}")
        segno = "  ← attuali" if (mostra, stabile, min_t) == (SOGLIA_MOSTRA, SOGLIA_STABILE, MIN_TORNEI) else ""
        log(f"  {mostra:>2} / {stabile:>2} / {min_t}                             "
            + "  ".join(f"{c:>7}" for c in celle) + segno)
    log("  (valori = mostrati/stabili)")


def scrivi_csv(percorso, intestazione, righe):
    """CSV con il punto e virgola: si apre bene con Excel in italiano."""
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(intestazione)
        w.writerows(righe)


def link(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}" if page_id else ""


def salva_elenchi(A, esiti, per_page, opzioni):
    def base(k):
        a = A[k]
        return [a["id"], a["nome"], a["noc"], a["disc"], round(a["elo"]), a["n"], a["n_tornei"], a["livello"]]
    intest = ["ID ITTF", "Nome WTT", "NOC WTT", "Specialità", "ELO", "Incontri", "Tornei", "Livello"]
    ordina = lambda k: (-A[k]["n"], A[k]["nome"])
    ab = sorted((k for k, e in esiti.items() if e["esito"] == "abbinato"), key=ordina)
    dc = sorted((k for k, e in esiti.items() if e["esito"] == "da creare"), key=ordina)
    inc = sorted((k for k, e in esiti.items() if e["esito"] == "incerto"), key=ordina)
    opz = opzioni.get("disc") or []
    disciplina = lambda s: next((o for o in opz if specialita_athletes([o]) == {s}), SPECIALITA[s])
    scrivi_csv(CSV_ABBINATI, intest + ["Pagina Athletes", "NOC Athletes", "Come", "Link"],
               [base(k) + [per_page[esiti[k]["page"]]["nome"], per_page[esiti[k]["page"]]["noc"],
                           esiti[k]["motivo"], link(esiti[k]["page"])] for k in ab])
    scrivi_csv(CSV_DA_CREARE, intest + ["Nome da scrivere in Athletes", "Disciplina da scegliere"],
               [base(k) + [nome_athletes(A[k]["nome"]), disciplina(A[k]["disc"])] for k in dc])
    scrivi_csv(CSV_INCERTI, intest + ["Motivo", "Candidati in Athletes (nome | NOC | disciplina | link)"],
               [base(k) + [esiti[k]["motivo"],
                           " || ".join(f"{r['nome']} | {r['noc'] or '-'} | {'/'.join(r['disc']) or '-'} | "
                                       f"{link(r['page'])}" for r in esiti[k]["candidati"][:4])]
                for k in inc])
    return ab, dc, inc


def salva_json(A, esiti, tornei, oggi):
    """tennistavolo-elo.json: tutto ciò che serve alla pagina (sessione 3). Una voce per giocatore o coppia."""
    atleti = []
    for k, a in sorted(A.items(), key=lambda x: -x[1]["elo"]):
        e = esiti.get(k, {})
        atleti.append({
            "id_ittf": a["id"], "nome": a["nome"], "noc": a["noc"],
            "notion": (e.get("page") or "").replace("-", "") or None,
            "spec": a["disc"], "coppia": a["disc"] in DOPPI,
            "elo": round(a["elo"]), "elo_max": round(a["max"]), "livello": a["livello"],
            "incontri": a["n"], "vittorie": a["v"], "walkover": a["wo"], "ritiri": a["ritiri"],
            "tornei": a["n_tornei"], "ultimo": a["ultima"], "storico": a["storico"]})
    dati = {"aggiornato": oggi.isoformat(),
            "regole": {"partenza": ELO_PARTENZA, "k": K_BASE, "coeff_torneo": COEFF_TORNEO,
                       "peso_turno": {"Final": PESO_FINALE, "Semi Final": PESO_SEMI, "Quarter Final": PESO_QUARTI,
                                      "turni 1-2 e gironi": PESO_TURNI_1_2, "turni 3-5": PESO_TURNI_3_5,
                                      "qualificazioni": PESO_QUALIFICAZIONI, "altri": PESO_ALTRI},
                       "walkover_perdente": QUOTA_WALKOVER_PERDENTE, "ritiro": QUOTA_RITIRO,
                       "inattivita": {"giorni_senza_effetto": GIORNI_SENZA_EFFETTO,
                                      "ogni_giorni": GIORNI_PER_CALO, "calo": CALO},
                       "soglia_provvisorio": SOGLIA_MOSTRA, "soglia_stabile": SOGLIA_STABILE,
                       "min_tornei": MIN_TORNEI},
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

    log(f"ELO Tennis Tavolo 1.0 · {'SOLO PROVA: non scrivo nulla su Notion' if solo_prova else 'SCRITTURA su Notion'} "
        f"· data del calcolo {oggi.isoformat()}")

    # 1. lettura
    mancanti = []
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        incontri, athletes, opzioni = raw["incontri"], raw["athletes"], raw.get("opzioni", {})
    else:
        incontri = leggi_incontri()
        athletes, opzioni, mancanti = leggi_athletes()
        FILE_RAW.write_text(json.dumps({"incontri": incontri, "athletes": athletes, "opzioni": opzioni},
                                       ensure_ascii=False), encoding="utf-8")
    if mancanti:
        msg = (f"in Athletes mancano le proprietà {', '.join(sorted(mancanti))} "
               "(da creare: «ID ITTF» di tipo Testo, «ELO TT» di tipo Numero)")
        if not solo_prova:
            sys.exit("ERRORE: " + msg + ". Senza di esse non posso scrivere.")
        log("AVVISO: " + msg + ". Per la Solo prova non servono; servono per il lancio vero.")
    log(f"Incontri letti dal db Agente Tennis Tavolo: {len(incontri)} "
        f"(tabellone principale {sum(1 for m in incontri if m.get('tab') != QUALIFICAZIONE)}, "
        f"qualificazione {sum(1 for m in incontri if m.get('tab') == QUALIFICAZIONE)})")
    log(f"Pagine di Athletes con Sport = {SPORT_ATHLETES}: {len(athletes)}, con ID ITTF già compilato: "
        f"{sum(1 for r in athletes if r['id_ittf'])}")

    # 2. calcolo
    validi, scarti, _ = filtra(incontri)
    tipi = Counter(m["tipo"] for m in validi)
    log(f"Incontri usati nell'ELO: {len(validi)} (giocati {tipi['normale']}, con ritiro {tipi['ritiro']}, "
        f"walkover {tipi['walkover']})")
    for motivo, n in scarti.most_common():
        log(f"  esclusi {n}: {motivo}" if not motivo.startswith("turno non previsto") else f"  nota {n}: {motivo}")
    pesi = Counter(f"{m['peso']:.0%}" for m in validi)
    log("Incontri per peso del turno: " + ", ".join(f"{p} {n}" for p, n in sorted(pesi.items(), reverse=True)))
    ritiri = Counter(m["momento"] for m in validi if m["tipo"] == "ritiro")
    if ritiri:
        log("Ritiri per momento: " + ", ".join(f"{QUOTA_RITIRO[k]:.0%} {v}" for k, v in sorted(ritiri.items())))
    A, prev = calcola_elo(validi, oggi, verifica_da=DATA_VERIFICA)
    livelli = Counter(a["livello"] for a in A.values())
    log(f"Schede ELO (giocatori nei singolari + coppie nei doppi): {len(A)} · stabili {livelli['stabile']} · "
        f"provvisori {livelli['provvisorio']} · non mostrati {livelli['nascosto']}")
    log("  per specialità: " + ", ".join(f"{s} {sum(1 for a in A.values() if a['disc'] == s)}" for s in SPECIALITA))

    # 3. bontà delle previsioni e confronto tra varianti
    log("\n" + "=" * 78)
    log(f"BONTÀ DELLE PREVISIONI (incontri giocati dal {DATA_VERIFICA}, entrambi con almeno {SOGLIA_MOSTRA} incontri prima)")
    log("=" * 78)
    log(f"  Regole decise (K 32, senza MoV):    {testo_previsioni(prev)}")
    varianti = (("K 24", dict(k_base=24)), ("K 40", dict(k_base=40)),
                ("MoV lieve (scarto di partite)", dict(usa_mov=True)),
                ("senza peso del turno", dict(usa_turno=False)),
                ("senza peso del torneo", dict(usa_torneo=False)))
    for nome, opz in varianti:
        _, p = calcola_elo(validi, oggi, verifica_da=DATA_VERIFICA, **opz)
        log(f"  Variante {nome:<27} {testo_previsioni(p)}")
    # variante senza qualificazioni: stesso calcolo, ma le qualificazioni non entrano
    senza_q = [m for m in validi if m["tab"] != QUALIFICAZIONE]
    _, p = calcola_elo(senza_q, oggi, verifica_da=DATA_VERIFICA)
    log(f"  Variante {'senza qualificazioni':<27} {testo_previsioni(p)}")
    log("  (favorito vincente: più alto è meglio; Brier e log-loss: più bassi è meglio;"
        " un modello a caso darebbe 50%, Brier 0,25, log-loss 0,693)")
    log("  Nota: la variante senza qualificazioni è valutata su meno incontri, quindi i numeri non sono"
        " del tutto confrontabili.")

    tornei = {}
    for m in validi:
        t = tornei.setdefault(m["torneo_id"], {"nome": m["torneo"], "categoria": m["cat"], "data": m["data"]})
        t["data"] = min(t["data"], m["data"])

    # 4. abbinamento con Athletes
    esiti = abbina(A, athletes)
    per_page = {r["page"]: r for r in athletes}
    ab, dc, inc = salva_elenchi(A, esiti, per_page, opzioni)
    mostrato = lambda k: A[k]["livello"] != "nascosto"
    log("\n" + "=" * 78)
    log("ABBINAMENTO CON IL DB ATHLETES (solo pagine esistenti)")
    log("=" * 78)
    log(f"Abbinati: {len(ab)} ({dict(Counter(esiti[k]['motivo'] for k in ab))}); con ELO mostrato: "
        f"{sum(1 for k in ab if mostrato(k))}")
    log(f"Da creare (lo script non li crea): {len(dc)}; con ELO mostrato: {sum(1 for k in dc if mostrato(k))}")
    log(f"Incerti: {len(inc)}; con ELO mostrato: {sum(1 for k in inc if mostrato(k))}")
    usate = {esiti[k]["page"] for k in ab}
    log(f"Pagine di tennistavolo in Athletes: {len(athletes)}, abbinate: {len(usate)}, "
        f"senza incontri riconosciuti: {len(athletes) - len(usate)}")
    log("\nIncerti (tutti, prima quelli con più incontri):")
    for k in inc[:80]:
        a = A[k]
        log(f"  · {a['nome']} ({a['noc']}, {a['disc']}, {a['n']} inc., ELO {a['elo']:.0f}) → {esiti[k]['motivo']}")
    log("\nDa creare con ELO mostrato e NOC ITA: " + (", ".join(
        A[k]["nome"] for k in dc if mostrato(k) and "ITA" in (A[k]["noc"] or "").split("/")) or "nessuno"))
    righe_no = [r for r in athletes if r["page"] not in usate]
    log(f"\nPagine di Athletes NON abbinate ({len(righe_no)}): "
        + "; ".join(f"{r['nome']} ({codice_noc(r['noc']) or '-'})" for r in righe_no[:80]))
    log(f"Elenchi completi nei file {CSV_ABBINATI.name}, {CSV_DA_CREARE.name}, {CSV_INCERTI.name} "
        f"(Artifacts del lancio).")

    stampa_soglie(A)
    stampa_classifiche(A)
    salva_json(A, esiti, tornei, oggi)
    log(f"\n{FILE_JSON.name}: {len(A)} schede (giocatori + coppie), {len(tornei)} tornei")

    if solo_prova:
        log("\nProva terminata: non è stato scritto nulla su Notion.")
        return 0

    # 5. scrittura su Notion (solo db Athletes; solo ELO TT e ID ITTF vuoti; solo abbinati)
    log("\n" + "=" * 78)
    log("SCRITTURA IN ATHLETES")
    log("=" * 78)
    aggiornate = invariate = errori = 0
    for k in ab:
        if minuti() > TEMPO_MAX_MINUTI:
            log(f"ATTENZIONE: mi sono fermato dopo {TEMPO_MAX_MINUTI:.0f} minuti. Rilancia: "
                "le pagine già scritte risultano abbinate per ID ITTF.")
            return 1
        riga = per_page[esiti[k]["page"]]
        elo = round(A[k]["elo"])
        nuovi = {}
        if riga["elo"] is None or round(riga["elo"]) != elo:
            nuovi["ELO TT"] = elo
        if not riga["id_ittf"]:
            nuovi["ID ITTF"] = A[k]["id"]
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
    log(f"Pagine aggiornate: {aggiornate} · invariate: {invariate} · errori: {errori} · "
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
