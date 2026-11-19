#!/usr/bin/env python3
"""ELO Vela (scheda 38, sessione 2) – repo map-q-la28 · versione 1.1 del 19/11/2026

Novità della versione 1.1 (decisioni di Gualtiero del 19/11/2026, dopo la prima Solo prova):
  - K base 64 invece di 32: con 32 i valori restavano troppo vicini a 1500 (ILCA 7 da 1437 a 1615);
  - soglie confermate: provvisorio da 3 eventi, stabile da 6; sconto equipaggio nuovo confermato al 20%;
  - abbinamento con Athletes: se c'è UNA SOLA pagina candidata con lo stesso NOC (o NOC vuoto) si
    abbina anche quando
      · il nome è quasi uguale (Matt/Matthew WEARN, Gian/Gian Andrea STRAGIOTTI), oppure
      · in Athletes la Disciplina è vuota;
    se mancano sia il nome identico sia la Disciplina, serve lo stesso NOC (non vuoto);
  - nel rapporto e nel JSON ogni atleta compare con il nome scritto più spesso (preferendo la forma
    "Nome COGNOME"), non con quello dell'ultima regata.

Che cosa fa
-----------
1. Legge da Notion le classifiche finali del db "⛵ Agente Vela" (una riga per barca per evento,
   scritte dall'agente vela).
2. Riconosce gli atleti anche quando il loro nome è scritto in modi diversi da una regata all'altra
   ("GAUTREY George", "George GAUTREY", "Matt Wearn" / "Matthew WEARN", "Kampman" / "Kampmann"):
     - stesso ID World Sailing                         -> stessa persona;
     - stessa classe + stesso NOC + stesse parole del nome (in qualunque ordine, senza accenti
       e maiuscole)                                      -> stessa persona;
     - stessa classe + stesso NOC + nome quasi uguale (una sola parola diversa per una lettera o
       abbreviata, es. MATT/MATTHEW)                     -> stessa persona, ma l'unione finisce
       nell'elenco vela_elo_uniti.csv da controllare.
3. Calcola un ELO per ogni barca (scheda 34 §8, decisioni del 17/11/2026):
     - un ELO separato per ciascuna delle 10 classi, partenza 1500;
     - classi a due (49er, 49er FX, 470, Nacra 17): un ELO per EQUIPAGGIO (timoniere + prodiere);
     - ogni regata = confronti a coppie tra tutte le barche della classifica finale:
       chi è arrivato davanti "ha battuto" chi è arrivato dietro (pari merito = mezzo punto);
     - variazione = K / (N − 1) × somma di (risultato − atteso) contro le altre N − 1 barche,
       con K = 64 × coefficiente dell'evento (Olimpiadi 1,5 · Mondiali 1,25 · Sailing Grand Slam 1,0 ·
       Europei 0,9 · Giochi continentali 0,9 · Altre regate 0,8);
     - tutti i rating di una regata si aggiornano INSIEME, partendo dai valori prima della regata;
     - barche "mai partite" (DNC/DNS in tutte le prove) escluse;
     - equipaggio nuovo: parte dalla media degli ultimi ELO dei suoi due atleti in quella classe
       (1500 per chi non ne ha), avvicinata a 1500 dello SCONTO_CAMBIO (20%, deciso il 19/11);
     - inattività come il judo: 6 mesi interi senza effetto, poi −2% al mese della distanza da 1500.
4. Misura quanto bene l'ELO prevede l'ordine d'arrivo e confronta qualche variante dei parametri.
5. Abbina ogni barca (atleta o equipaggio) a una pagina del db Athletes (Sport = Sailing) e divide in
   ABBINATI / DA CREARE / INCERTI, come badminton e scherma. Lo script NON crea pagine.
6. In "Solo prova" (DRY_RUN=true) non scrive nulla su Notion: stampa il rapporto, salva gli elenchi
   CSV e vela_raw.json (copia dei dati letti, serve a Claude per i collaudi).
7. Nel lancio vero scrive in Athletes, SOLO per gli abbinati:
     - "ELO Vela" (l'unico campo che viene riscritto);
     - "ID WS" solo dove è vuoto ("id1/id2" per gli equipaggi, come "ID BWF");
   e salva vela-elo.json (ELO, storico ed eventi) per la pagina performance (sessione 3).

REGOLA FONDAMENTALE: nessuna operazione su Athletes elimina o sovrascrive dati già inseriti.
La funzione `aggiorna_riga` blocca qualsiasi colonna diversa da "ELO Vela" e "ID WS".

Uso
---
  NOTION_TOKEN=... DRY_RUN=true python elo_vela.py        Solo prova
  NOTION_TOKEN=... DRY_RUN=false python elo_vela.py       lancio vero
  python elo_vela.py --da-raw vela_raw.json                collaudo con dati salvati (non tocca Notion)

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
DS_VELA = "41bf48c9-aad9-814c-a19a-000b29ce3118"       # data source del db "⛵ Agente Vela"
DS_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"   # data source del db Athletes
NOMI_DB = {DS_VELA: "⛵ Agente Vela", DS_ATHLETES: "Athletes"}

# Nomi ESATTI delle colonne del db Agente Vela (scheda 35 §3)
COL_V = {"uid": "ID Univoco", "tim": "Timoniere", "pro": "Prodiere", "noc": "NOC",
         "id1": "ID WS 1", "id2": "ID WS 2", "velico": "Numero velico", "classe": "Classe",
         "pos": "Posizione", "punti": "Punti netti", "evento": "Evento", "tipo": "Tipo Evento",
         "inizio": "Data inizio", "fine": "Data fine", "note": "Note"}
# Nomi ESATTI delle proprietà di Athletes ("ID WS" ed "ELO Vela" decise nel foglio, punto 17:
# vanno create da Gualtiero prima del lancio vero)
COL_A = {"nome": "Cognome e Nome", "sport": "Sport", "noc": "NOC", "disc": "Disciplina",
         "id_ws": "ID WS", "elo": "ELO Vela"}
COL_A_NUOVE = {"ID WS", "ELO Vela"}
SCRIVIBILI_SEMPRE = {"ELO Vela"}      # valore calcolato, appartiene allo script
SCRIVIBILI_SE_VUOTI = {"ID WS"}       # solo se la cella è vuota

# Le 10 classi, scritte come le opzioni di "Disciplina" in Athletes (verificate il 18/11/2026)
CLASSI = ["Men's Laser ILCA 7", "Women's Laser Radial ILCA 6", "Men's iQFOIL", "Women's iQFOIL",
          "Men's 49er", "Women's 49er FX", "Mixed 470", "Nacra 17", "Men's Kite", "Women's Kite"]
DOPPI = {"Men's 49er", "Women's 49er FX", "Mixed 470", "Nacra 17"}
SIGLA = {"Men's Laser ILCA 7": "ILCA 7", "Women's Laser Radial ILCA 6": "ILCA 6", "Men's iQFOIL": "iQ M",
         "Women's iQFOIL": "iQ W", "Men's 49er": "49er", "Women's 49er FX": "49er FX", "Mixed 470": "470",
         "Nacra 17": "Nacra", "Men's Kite": "Kite M", "Women's Kite": "Kite W"}

# --- regole di calcolo (scheda 34 §8, decise da Gualtiero il 17/11/2026) ---
ELO_PARTENZA = 1500
K_BASE = 64                   # 32 deciso il 17/11, portato a 64 il 19/11 dopo la Solo prova
COEFF_EVENTO = {"Olimpiadi": 1.5, "Mondiali": 1.25, "Sailing Grand Slam": 1.0,
                "Europei": 0.9, "Giochi continentali": 0.9, "Altre regate": 0.8}
SCONTO_CAMBIO = 0.20          # (deciso il 19/11) equipaggio nuovo: quota della distanza da 1500 che si perde
MESI_SENZA_EFFETTO = 6        # inattività come il judo: 6 mesi interi senza effetto...
CALO = 0.02                   # ... poi -2% al mese della distanza da 1500
# Soglie per mostrare l'ELO nella pagina, in NUMERO DI EVENTI (foglio, punto 15; confermate il 19/11)
SOGLIA_MOSTRA = 3             # da 3 eventi l'ELO è "provvisorio"
SOGLIA_STABILE = 6            # da 6 eventi è "stabile"
DATA_VERIFICA = "2026-07-01"  # da qui si misura la bontà delle previsioni

TITOLI = {"WC", "OLY", "OC", "EC"}
TRASCRIZIONI = {"Ø": "O", "Æ": "AE", "Œ": "OE", "ẞ": "SS", "Ð": "D", "Đ": "D", "Ł": "L", "Þ": "TH"}

PAUSA_NOTION = 0.35
LIMITE_NOTION = 10000
TEMPO_MAX_MINUTI = float(os.getenv("TEMPO_MAX_MINUTI", "").strip() or 165)

FILE_JSON = CARTELLA / "vela-elo.json"
FILE_RAW = CARTELLA / "vela_raw.json"
FILE_RAPPORTO = CARTELLA / "rapporto_elo_vela.txt"
CSV_ABBINATI = CARTELLA / "vela_elo_abbinati.csv"
CSV_DA_CREARE = CARTELLA / "vela_elo_da_creare.csv"
CSV_INCERTI = CARTELLA / "vela_elo_incerti.csv"
CSV_UNITI = CARTELLA / "vela_elo_uniti.csv"


# ====================================================================== LOG
_righe_log = []


def log(testo=""):
    """Stampa a video e conserva la riga per il file rapporto_elo_vela.txt."""
    print(testo, flush=True)
    _righe_log.append(str(testo))


def minuti():
    return (time.monotonic() - AVVIO) / 60


# ====================================================================== NOTION
def chiama(metodo, percorso, corpo=None):
    """Chiamata all'API di Notion; riprova se Notion è occupato (429), in errore (5xx) o la rete cade."""
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
        except (urllib.error.URLError, TimeoutError, ConnectionError) as errore:
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
    Se una ricerca arriva a 10.000 righe (limite dell'API) lo script si ferma: dati incompleti."""
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
        sys.exit(f'ERRORE: la ricerca "{etichetta}" ha restituito {len(pagine)} righe, il limite '
                 f"dell'API Notion: alcune righe non sono state lette.")
    return pagine


def schema(ds):
    return chiama("GET", f"data_sources/{ds}")["properties"]


def leggi_righe():
    """Righe del db Agente Vela, lette una classe alla volta (+ una ricerca di controllo)."""
    props = schema(DS_VELA)
    mancanti = [c for c in COL_V.values() if c not in props]
    if mancanti:
        sys.exit(f'ERRORE: nel db "⛵ Agente Vela" non trovo le colonne: {", ".join(mancanti)}')
    c = COL_V["classe"]
    fette = [(cl, {"property": c, "select": {"equals": cl}}) for cl in CLASSI]
    fette.append(("altre (Classe vuota o diversa)",
                  {"or": [{"property": c, "select": {"is_empty": True}},
                          {"and": [{"property": c, "select": {"does_not_equal": cl}} for cl in CLASSI]}]}))
    righe, visti, conteggi = [], set(), []
    for etichetta, filtro in fette:
        pagine = interroga(DS_VELA, filtro, f"Agente Vela, {etichetta}")
        conteggi.append((etichetta, len(pagine)))
        for pg in pagine:
            if pg["id"] in visti:
                continue
            visti.add(pg["id"])
            p = pg["properties"]
            righe.append({k: valore(p.get(col)) for k, col in COL_V.items()})
    log("Lettura del db Agente Vela: " + " · ".join(f"{SIGLA.get(e, e)} {n}" for e, n in conteggi))
    return righe


def leggi_athletes():
    """Pagine di vela del db Athletes (Sport = Sailing). Restituisce (pagine, colonne nuove mancanti)."""
    props = schema(DS_ATHLETES)
    base = [COL_A[k] for k in ("nome", "sport", "noc", "disc")]
    mancanti = [c for c in base if c not in props]
    if mancanti:
        sys.exit(f'ERRORE: nel db Athletes non trovo le colonne: {", ".join(mancanti)}')
    nuove_mancanti = [c for c in COL_A_NUOVE if c not in props]
    atleti = []
    for pg in interroga(DS_ATHLETES, {"property": COL_A["sport"], "select": {"equals": "Sailing"}},
                        "Athletes, Sport = Sailing"):
        p = pg["properties"]
        atleti.append({"page": pg["id"].replace("-", ""), "nome": valore(p.get(COL_A["nome"])) or "",
                       "noc": valore(p.get(COL_A["noc"])) or "", "disc": valore(p.get(COL_A["disc"])) or [],
                       "id_ws": (valore(p.get(COL_A["id_ws"])) or "").strip() if COL_A["id_ws"] in props else "",
                       "elo": valore(p.get(COL_A["elo"])) if COL_A["elo"] in props else None})
    return atleti, nuove_mancanti


def aggiorna_riga(atleta, nuovi):
    """Scrive in una pagina ESISTENTE di Athletes rispettando la regola fondamentale.
    Rifiuta qualsiasi colonna non ammessa e salta "ID WS" quando la cella contiene già qualcosa."""
    props = {}
    for col, val in nuovi.items():
        if col in SCRIVIBILI_SEMPRE:
            props[col] = {"number": val}
        elif col in SCRIVIBILI_SE_VUOTI:
            if atleta["id_ws"]:
                continue                     # la cella è già compilata: non la tocco
            props[col] = {"rich_text": [{"text": {"content": str(val)}}]}
        else:
            raise RuntimeError(f"tentativo di scrivere la colonna non ammessa '{col}': bloccato")
    if props:
        chiama("PATCH", f"pages/{atleta['page']}", {"properties": props})
    return bool(props)


# ====================================================================== NOMI
def lettere(testo):
    """Tiene solo lettere vere e spazi; toglie apici (²ˣᵒᶜ), emoji, punteggiatura e titoli (WC, OLY...)."""
    out = []
    for ch in testo or "":
        cat = unicodedata.category(ch)
        out.append(ch if cat in ("Lu", "Ll", "Lt", "Lo") else " ")   # NON "Lm": ˣ ᵒ ᶜ sono decorazioni
    return " ".join(p for p in "".join(out).split() if p not in TITOLI)


def senza_accenti(testo):
    """Maiuscolo, senza accenti e con le lettere speciali trascritte: 'Søe' -> 'SOE', 'Löffler' -> 'LOFLER'."""
    t = unicodedata.normalize("NFKD", (testo or "").upper())
    t = "".join(TRASCRIZIONI.get(c, c) for c in t if not unicodedata.combining(c))
    t = t.replace("SS", "S")
    for doppia, semplice in (("AE", "A"), ("OE", "O"), ("UE", "U")):
        t = t.replace(doppia, semplice)
    return t


def parole_nome(nome):
    """'GAUTREY George' e 'George Gautrey' -> ('GAUTREY', 'GEORGE'): parole normalizzate in ordine alfabetico."""
    return tuple(sorted(senza_accenti(p) for p in lettere(nome).split()))


def parola_simile(a, b):
    """Due parole di un nome sono 'quasi uguali': abbreviazione (MATT/MATTHEW) o una lettera di differenza
    (KAMPMAN/KAMPMANN)."""
    if a == b:
        return True
    corta, lunga = sorted((a, b), key=len)
    if len(corta) >= 3 and lunga.startswith(corta):
        return True
    return len(corta) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def nomi_simili(n1, n2):
    """Vero se due nomi (tuple di parole) indicano probabilmente la stessa persona:
    - stesso numero di parole e al massimo UNA parola quasi uguale, le altre identiche; oppure
    - tutte le parole del nome più corto (almeno 2) compaiono identiche nell'altro
      ('Federico PILLONI' dentro 'Federico Alan PILLONI')."""
    if n1 == n2:
        return True
    corto, lungo = sorted((list(n1), list(n2)), key=len)
    if len(corto) < 2:
        return False
    rimaste, diverse = list(lungo), 0
    for p in corto:
        if p in rimaste:
            rimaste.remove(p)
            continue
        uguale = next((q for q in rimaste if parola_simile(p, q)), None)
        if uguale is None:
            return False
        rimaste.remove(uguale)
        diverse += 1
    if len(corto) == len(lungo):
        return diverse <= 1
    return diverse == 0


# ====================================================================== PERSONE E BARCHE
class Unione:
    """Insiemi che si uniscono (union-find): ogni nome o ID è un nodo; i nodi della stessa persona
    finiscono nello stesso insieme, rappresentato dalla sua 'radice'."""

    def __init__(self):
        self.padre = {}

    def radice(self, x):
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unisci(self, a, b):
        ra, rb = self.radice(a), self.radice(b)
        if ra != rb:
            self.padre[max(ra, rb)] = min(ra, rb)


# Un ID World Sailing è il codice della nazione + le iniziali + un numero (es. AUSGM33, ITARP80).
# Alcune pagine (Mondiali iQFOiL 2025) collegano invece il numero velico ("AUS81"): non è un ID.
RE_ID_WS = re.compile(r"^[A-Z]{3}[A-Z]{1,5}\d{1,4}$")


ID_SCARTATI = []      # ID non validi trovati nelle righe (solo per il rapporto)


def id_valido(ident, scarti):
    """L'ID se ha la forma giusta, altrimenti "" (la riga resta nel calcolo, l'ID no)."""
    ident = (ident or "").strip().upper()
    if ident and not RE_ID_WS.match(ident):
        scarti["nota: ID World Sailing non valido ignorato (la riga resta nel calcolo)"] += 1
        ID_SCARTATI.append(ident)
        return ""
    return ident


def prepara_righe(grezze):
    """Controlla le righe lette e le porta al formato interno. Restituisce (righe, scarti per motivo)."""
    righe, scarti = [], Counter()
    for r in grezze:
        uid = r.get("uid") or ""
        pos = r.get("pos")
        data = r.get("fine") or r.get("inizio") or ""
        if r.get("classe") not in CLASSI:
            scarti[f"classe sconosciuta: '{r.get('classe')}'"] += 1
        elif r.get("tipo") not in COEFF_EVENTO:
            scarti[f"Tipo Evento sconosciuto: '{r.get('tipo')}'"] += 1
        elif not isinstance(pos, (int, float)):
            scarti["Posizione vuota"] += 1
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
            scarti["data mancante"] += 1
        elif not lettere(r.get("tim") or ""):
            scarti["nome mancante"] += 1
        elif "mai partita" in (r.get("note") or ""):
            scarti["barca mai partita (DNC/DNS in tutte le prove)"] += 1
        else:
            righe.append({**r, "pos": int(pos), "data": data, "id_evento": uid.split("|")[0] or r.get("evento"),
                          "id1": id_valido(r.get("id1"), scarti), "id2": id_valido(r.get("id2"), scarti),
                          "noc": (r.get("noc") or "").strip().upper(), "pro": r.get("pro") or ""})
    return righe, scarti


def riconosci_persone(righe):
    """Assegna a ogni atleta di ogni riga una 'persona' (radice dell'Unione).

    Nodi: 'ID:<ID World Sailing>' e 'N:<classe>|<NOC>|<parole del nome>'. Unioni:
      1) il nome e l'ID della stessa cella (stessa persona per definizione);
      2) nomi quasi uguali nella stessa classe e con lo stesso NOC (nomi_simili), se le due persone
         non hanno ID World Sailing diversi: queste unioni vanno controllate (vela_elo_uniti.csv).
    Restituisce (persone: radice -> scheda, uniti: elenco delle unioni per nome simile)."""
    u = Unione()
    nodi_nome = defaultdict(set)              # (classe, NOC) -> nodi nome
    for r in righe:
        r["_atleti"] = []
        for nome, ident in ((r["tim"], r["id1"]), (r["pro"], r["id2"])):
            if not lettere(nome):
                continue
            nodo = f"N:{r['classe']}|{r['noc']}|{' '.join(parole_nome(nome))}"
            u.radice(nodo)
            nodi_nome[(r["classe"], r["noc"])].add(nodo)
            if ident:
                u.unisci(nodo, f"ID:{ident}")
            r["_atleti"].append((nodo, nome, ident))
    # ID di ogni insieme dopo le unioni sicure
    def id_di():
        out = defaultdict(set)
        for r in righe:
            for nodo, _, ident in r["_atleti"]:
                if ident:
                    out[u.radice(nodo)].add(ident)
        return out
    ids = id_di()
    uniti = []
    for (classe, noc), nodi in nodi_nome.items():
        nodi = sorted(nodi)
        for i, a in enumerate(nodi):
            for b in nodi[i + 1:]:
                ra, rb = u.radice(a), u.radice(b)
                if ra == rb:
                    continue
                if ids[ra] and ids[rb] and not (ids[ra] & ids[rb]):
                    continue                  # due ID World Sailing diversi: persone diverse
                na, nb = tuple(a.split("|", 2)[2].split()), tuple(b.split("|", 2)[2].split())
                if nomi_simili(na, nb):
                    u.unisci(a, b)
                    ids[u.radice(a)] = ids[ra] | ids[rb]
                    uniti.append((classe, noc, " ".join(na), " ".join(nb)))
    persone = {}
    for r in righe:
        r["_persone"] = []
        for nodo, nome, ident in r["_atleti"]:
            p = u.radice(nodo)
            s = persone.setdefault(p, {"nomi": Counter(), "ids": set(), "noc": r["noc"]})
            s["nomi"][nome] += 1
            if ident:
                s["ids"].add(ident)
            r["_persone"].append(p)
    return persone, uniti


def chiave_barca(r):
    """Identità della barca nell'ELO: (classe, persona) nelle classi singole,
    (classe, coppia di persone in qualunque ordine) negli equipaggi."""
    if r["classe"] in DOPPI:
        coppia = r["_persone"] if len(r["_persone"]) == 2 else r["_persone"] + ["?" + r["uid"]]
        return (r["classe"], tuple(sorted(coppia)))
    return (r["classe"], (r["_persone"][0],))


def costruisci_eventi(righe):
    """Raggruppa le righe in eventi (stesso id_evento e stessa classe), in ordine di data di fine.
    Se la stessa barca compare due volte nello stesso evento tengo il piazzamento migliore."""
    gruppi = defaultdict(list)
    for r in righe:
        gruppi[(r["id_evento"], r["classe"])].append(r)
    eventi, doppie, piccoli = [], 0, 0
    for (ide, classe), rr in gruppi.items():
        migliori = {}
        for r in sorted(rr, key=lambda r: r["pos"]):
            k = chiave_barca(r)
            if k in migliori:
                doppie += 1
                continue
            migliori[k] = r
        if len(migliori) < 2:
            piccoli += 1
            continue
        primo = rr[0]
        eventi.append({"id": ide, "classe": classe, "nome": primo.get("evento") or ide, "tipo": primo["tipo"],
                       "data": max(r["data"] for r in rr), "inizio": min((r.get("inizio") or r["data"]) for r in rr),
                       "barche": [(k, r["pos"], r) for k, r in migliori.items()]})
    eventi.sort(key=lambda e: (e["data"], e["id"], e["classe"]))
    return eventi, doppie, piccoli


# ====================================================================== CALCOLO ELO
def mesi_interi(da, a):
    """Mesi di calendario interi tra due date AAAA-MM-GG (es. 15/01 -> 14/07 = 5 mesi, 15/07 = 6)."""
    d1, d2 = dt.date.fromisoformat(da), dt.date.fromisoformat(a)
    m = (d2.year - d1.year) * 12 + d2.month - d1.month
    return m - 1 if d2.day < d1.day else m


def con_inattivita(rating, ultima, giorno):
    """Calo per inattività (come il judo): nessun effetto per 6 mesi interi, poi la distanza da 1500
    si riduce del 2% per ogni mese intero in più. Es. 1700 fermo da 12 mesi -> 1500 + 200 × 0,98⁶ = 1677."""
    if not ultima or giorno <= ultima:
        return rating
    periodi = mesi_interi(ultima, giorno) - MESI_SENZA_EFFETTO
    if periodi <= 0:
        return rating
    return ELO_PARTENZA + (rating - ELO_PARTENZA) * (1 - CALO) ** periodi


def livello_elo(n, mostra=None, stabile=None):
    mostra = SOGLIA_MOSTRA if mostra is None else mostra
    stabile = SOGLIA_STABILE if stabile is None else stabile
    if n < mostra:
        return "nascosto"
    return "provvisorio" if n < stabile else "stabile"


def calcola_elo(eventi, oggi, k_base=K_BASE, sconto=SCONTO_CAMBIO, usa_coeff=True,
                molt_nuovo=1.0, prime=0, verifica_da=None):
    """Calcola l'ELO di tutte le barche, evento dopo evento.

    Restituisce (B: chiave barca -> scheda, statistiche delle previsioni).
    Previsioni: per ogni coppia di barche di un evento dal `verifica_da`, con entrambe almeno
    SOGLIA_MOSTRA eventi alle spalle, si guarda se l'ELO più alto è arrivato davanti."""
    B = {}
    ultimo_atleta = {}                 # (classe, persona) -> (rating dell'ultima sua barca, data)
    prev = {"n": 0, "giuste": 0.0, "brier": 0.0, "logloss": 0.0}

    for ev in eventi:
        coeff = COEFF_EVENTO[ev["tipo"]] if usa_coeff else 1.0
        schede = []
        for k, pos, r in ev["barche"]:
            b = B.get(k)
            if b is None:
                partenza, da_equipaggi = float(ELO_PARTENZA), False
                if ev["classe"] in DOPPI:
                    # equipaggio nuovo: media degli ultimi ELO dei suoi atleti (1500 per chi non ne ha),
                    # avvicinata a 1500 dello sconto (variante semplificata decisa il 17/11/2026)
                    valori = []
                    for p in k[1]:
                        prima = ultimo_atleta.get((ev["classe"], p))
                        if prima:
                            valori.append(con_inattivita(prima[0], prima[1], ev["data"]))
                            da_equipaggi = True
                        else:
                            valori.append(float(ELO_PARTENZA))
                    if da_equipaggi:
                        media = sum(valori) / len(valori)
                        partenza = ELO_PARTENZA + (1 - sconto) * (media - ELO_PARTENZA)
                b = B[k] = {"chiave": k, "classe": ev["classe"], "rating": partenza, "partenza": round(partenza),
                            "da_equipaggi": da_equipaggi, "n": 0, "ultima": None, "storico": [],
                            "max": partenza, "miglior_pos": None, "vittorie": 0, "podi": 0, "nomi": None, "noc": ""}
            b["rating"] = con_inattivita(b["rating"], b["ultima"], ev["data"])
            schede.append((b, pos, r))
        N = len(schede)
        R = [b["rating"] for b, _, _ in schede]      # rating PRIMA della regata
        P = [pos for _, pos, _ in schede]
        # previsioni (solo coppie con risultato diverso)
        if verifica_da and ev["data"] >= verifica_da:
            for i in range(N):
                if schede[i][0]["n"] < SOGLIA_MOSTRA:
                    continue
                for j in range(i + 1, N):
                    if schede[j][0]["n"] < SOGLIA_MOSTRA or P[i] == P[j]:
                        continue
                    a, c = (i, j) if P[i] < P[j] else (j, i)          # a = arrivato davanti
                    atteso = 1 / (1 + 10 ** ((R[c] - R[a]) / 400))
                    prev["n"] += 1
                    prev["giuste"] += 1 if atteso > 0.5 else (0.5 if atteso == 0.5 else 0)
                    prev["brier"] += (1 - atteso) ** 2
                    prev["logloss"] += -math.log(max(atteso, 1e-9))
        # aggiornamento simultaneo
        nuovi = []
        for i in range(N):
            somma = 0.0
            for j in range(N):
                if i == j:
                    continue
                s = 1.0 if P[i] < P[j] else (0.5 if P[i] == P[j] else 0.0)
                somma += s - 1 / (1 + 10 ** ((R[j] - R[i]) / 400))
            k = k_base * coeff * (molt_nuovo if schede[i][0]["n"] < prime else 1.0)
            nuovi.append(R[i] + k / (N - 1) * somma)
        for (b, pos, r), nuovo in zip(schede, nuovi):
            b["rating"] = nuovo
            b["max"] = max(b["max"], nuovo)
            b["n"] += 1
            b["ultima"] = ev["data"]
            b["miglior_pos"] = pos if b["miglior_pos"] is None else min(b["miglior_pos"], pos)
            b["vittorie"] += 1 if pos == 1 else 0
            b["podi"] += 1 if pos <= 3 else 0
            b["nomi"] = (r["tim"], r["pro"])                  # i nomi più recenti
            b["noc"] = r["noc"] or b["noc"]
            b["storico"].append([ev["data"], round(nuovo), ev["id"], pos, N])
            for p in b["chiave"][1]:
                ultimo_atleta[(ev["classe"], p)] = (nuovo, ev["data"])
    for b in B.values():
        b["elo"] = con_inattivita(b["rating"], b["ultima"], oggi.isoformat())
        b["livello"] = livello_elo(b["n"])
    return B, prev


def testo_previsioni(prev):
    if not prev["n"]:
        return "nessun confronto da valutare"
    return (f"{prev['n']} confronti · davanti il favorito {100 * prev['giuste'] / prev['n']:.1f}% · "
            f"Brier {prev['brier'] / prev['n']:.4f} · log-loss {prev['logloss'] / prev['n']:.4f}")


# ====================================================================== ABBINAMENTO CON ATHLETES
def parti_nome(nome):
    """Nome di UN atleta -> (COGNOME, Nome, parole in ordine alfabetico). Il cognome si riconosce dalle
    MAIUSCOLE ("Lara VADLAU"); se il nome non ha maiuscole ("Lara Vadlau") vale l'ordine alfabetico."""
    parole = lettere(nome).split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    if not cognome or not altri:
        cognome, altri = parole, []
    return (senza_accenti("".join(cognome)), senza_accenti("".join(altri)),
            "".join(sorted(senza_accenti(p) for p in parole)))


def confronta_nomi(n1, n2):
    """'esatto', 'simile' o None tra due nomi di UN atleta."""
    if parole_nome(n1) == parole_nome(n2):
        return "esatto"
    if nomi_simili(parole_nome(n1), parole_nome(n2)):
        return "simile"
    c, n, ins = parti_nome(n1)
    rc, rn, rins = parti_nome(n2)
    if c == rc and n and rn and (n.startswith(rn) or rn.startswith(n)):
        return "simile"
    if difflib.SequenceMatcher(None, ins, rins).ratio() >= 0.9:
        return "simile"
    return None


def esito_persona(nomi, nome_pagina):
    """Il migliore esito tra tutti i modi in cui la persona è scritta nelle classifiche."""
    esiti = [confronta_nomi(x, nome_pagina) for x in nomi]
    return "esatto" if "esatto" in esiti else ("simile" if "simile" in esiti else None)


def confronta_barca(nomi_persone, nomi_pagina):
    """Confronta una barca (lista di persone, ognuna con i suoi nomi) con una pagina di Athletes
    (lista di nomi separati da '/'), in qualunque ordine: 'esatto', 'simile' o None."""
    if len(nomi_persone) != len(nomi_pagina) or not nomi_persone:
        return None
    ordini = [nomi_pagina] if len(nomi_pagina) == 1 else [nomi_pagina, list(reversed(nomi_pagina))]
    migliore = None
    for altro in ordini:
        es = [esito_persona(p, q) for p, q in zip(nomi_persone, altro)]
        if all(e == "esatto" for e in es):
            return "esatto"
        if all(es):
            migliore = "simile"
    return migliore


def codice_noc(valore_noc):
    """'🇮🇹ITA' -> 'ITA'."""
    m = re.search(r"([A-Z]{2,3})$", valore_noc or "")
    return m.group(1) if m else ""


def classi_athletes(disc):
    """Disciplina di una pagina di Athletes -> classi (tollera 'ILCA6' / 'ILCA 6', foglio punto 20)."""
    out = set()
    for d in disc or []:
        dn = re.sub(r"ILCA\s*(\d)", r"ILCA \1", d)
        if dn in CLASSI:
            out.add(dn)
    return out


def abbina(B, persone, athletes):
    """Divide le barche in abbinati / da creare / incerti (stesse regole di badminton e scherma):
      1. pagina di Athletes con lo stesso ID WS (tutti gli atleti della barca) -> abbinato;
      2. una sola pagina con lo stesso nome (negli equipaggi gli stessi due atleti, in qualunque ordine),
         la stessa classe in Disciplina e lo stesso NOC (oppure NOC vuoto in Athletes) -> abbinato;
      3. pagine con nome simile, o stesso nome ma classe o NOC diversi -> incerto;
      4. nessuna pagina somigliante -> da creare (lo script non la crea)."""
    for r in athletes:
        r["_nomi"] = [x.strip() for x in r["nome"].split("/") if lettere(x)]
        r["_classi"] = classi_athletes(r["disc"])
        r["_codice"] = codice_noc(r["noc"])
        r["_ids"] = {x.strip().upper() for x in r["id_ws"].split("/") if x.strip()}
        r["_parole"] = {w for n in r["_nomi"] for w in parole_nome(n)}
        r["_inizi"] = {w[:4] for w in r["_parole"]}          # prime 4 lettere di ogni parola
    esiti, certi_per_pagina = {}, defaultdict(list)
    for k, b in B.items():
        classe, pers = k
        pers = [p for p in pers if not p.startswith("?")]
        nomi_persone = [list(persone[p]["nomi"]) for p in pers]
        ids_persone = [persone[p]["ids"] for p in pers]
        # 1. per ID WS: ogni atleta della barca ha un suo ID nella pagina
        per_id = [r for r in athletes if r["_ids"] and len(r["_ids"]) == len(pers)
                  and all(ids & r["_ids"] for ids in ids_persone)]
        if len(per_id) == 1:
            esiti[k] = {"esito": "abbinato", "page": per_id[0]["page"], "motivo": "ID WS", "candidati": per_id}
            continue
        if len(per_id) > 1:
            esiti[k] = {"esito": "incerto", "page": None, "candidati": per_id,
                        "motivo": f"ID WS presente in {len(per_id)} pagine di Athletes"}
            continue
        # parole di tutti i modi in cui sono scritti gli atleti della barca: una pagina che non ha nemmeno
        # una parola che comincia con le stesse 4 lettere non può somigliare (serve solo alla velocità)
        parole_barca = {w for nomi in nomi_persone for n in nomi for w in parole_nome(n)}
        esatti, simili = [], []
        for r in athletes:
            if r["_ids"]:
                continue                     # pagina già collegata a un ID WS: non è candidata per il nome
            if not ({w[:4] for w in parole_barca} & r["_inizi"]):
                continue
            e = confronta_barca(nomi_persone, r["_nomi"])
            if e == "esatto":
                esatti.append(r)
            elif e == "simile":
                simili.append(r)
        noc = b["noc"]
        buoni = [r for r in esatti if (not r["_codice"] or r["_codice"] == noc) and classe in r["_classi"]]
        # versione 1.1: una sola pagina candidata, accettata anche se il nome è quasi uguale oppure
        # la Disciplina è vuota (decisione del 19/11/2026); se mancano entrambe le cose serve lo stesso NOC
        unica = (esatti + simili)[0] if len(esatti) + len(simili) == 1 else None
        if unica is not None:
            stesso_noc = unica["_codice"] == noc
            noc_ok = stesso_noc or not unica["_codice"]
            classe_ok = classe in unica["_classi"]
            disc_vuota = not unica["_classi"]
            nome_ok = bool(esatti)
            accetta = noc_ok and (classe_ok or disc_vuota) and (nome_ok or classe_ok or stesso_noc)
        else:
            accetta = False
        if len(buoni) == 1 and len(esatti) == 1 and not simili:
            come = "nome + NOC + classe" if buoni[0]["_codice"] else "nome + classe (NOC vuoto in Athletes)"
            esiti[k] = {"esito": "abbinato", "page": buoni[0]["page"], "motivo": come, "candidati": buoni}
            certi_per_pagina[buoni[0]["page"]].append(k)
        elif accetta:
            parti = ["nome" if nome_ok else "nome quasi uguale",
                     "NOC" if stesso_noc else "NOC vuoto in Athletes",
                     "classe" if classe_ok else "Disciplina vuota in Athletes"]
            esiti[k] = {"esito": "abbinato", "page": unica["page"], "motivo": " + ".join(parti), "candidati": [unica]}
            certi_per_pagina[unica["page"]].append(k)
        elif esatti or simili:
            motivi = []
            for r in esatti:
                diff = []
                if r["_codice"] and r["_codice"] != noc:
                    diff.append(f"NOC {r['_codice']}")
                if classe not in r["_classi"]:
                    diff.append("classe diversa" if r["_classi"] else "Disciplina vuota")
                motivi.append("stesso nome" + (", ma " + " e ".join(diff) if diff else ""))
            if len(esatti) > 1:
                motivi.insert(0, f"{len(esatti)} pagine con lo stesso nome")
            if simili:
                motivi.append("nome simile: " + ", ".join(r["nome"] for r in simili[:3]))
            esiti[k] = {"esito": "incerto", "page": None, "motivo": "; ".join(motivi), "candidati": esatti + simili}
        else:
            esiti[k] = {"esito": "da creare", "page": None, "motivo": "nessuna pagina somigliante", "candidati": []}
    # più barche abbinate alla STESSA pagina (es. "Bruno FESTO" e, in una sola regata, "Bruno FEDTO"):
    # versione 1.1: la pagina resta alla barca abbinata per nome identico e, a parità, a quella con più
    # eventi; le altre diventano incerte. Se nessuna prevale, sono tutte incerte (come prima).
    for page, chiavi in certi_per_pagina.items():
        if len(chiavi) < 2:
            continue
        ordine = sorted(chiavi, key=lambda k: (not esiti[k]["motivo"].startswith("nome +"), -B[k]["n"]))
        primo, secondo = ordine[0], ordine[1]
        prevale = ((esiti[primo]["motivo"].startswith("nome +") and not esiti[secondo]["motivo"].startswith("nome +"))
                   or B[primo]["n"] > B[secondo]["n"])
        for k in (ordine[1:] if prevale else ordine):
            esiti[k].update(esito="incerto", page=None,
                            motivo=(f"pagina già abbinata a {nome_barca(B[primo])} ({B[primo]['n']} eventi): "
                                    "forse la stessa barca scritta in modo diverso") if prevale
                            else f"{len(chiavi)} barche con lo stesso nome e la stessa classe")
    prese = {e["page"] for e in esiti.values() if e["esito"] == "abbinato"}
    for e in esiti.values():
        if e["esito"] != "incerto" or e["motivo"].startswith("ID WS"):
            continue
        rimasti = [r for r in e["candidati"] if r["page"] not in prese]
        if not rimasti:
            e.update(esito="da creare", motivo="l'unica pagina somigliante è già abbinata a un'altra barca",
                     candidati=[])
        else:
            e["candidati"] = rimasti
    return esiti


def id_ws_barca(b, persone):
    """Testo per "ID WS": 'ID' (singolo) o 'id1/id2' (timoniere/prodiere). None se manca un ID o è dubbio."""
    pers = [p for p in b["chiave"][1] if not p.startswith("?")]
    ids = []
    for p in pers:
        if len(persone[p]["ids"]) != 1:
            return None
        ids.append(next(iter(persone[p]["ids"])))
    if len(pers) == 2 and b["nomi"]:
        # ordine timoniere/prodiere come nelle classifiche più recenti
        tim = parole_nome(b["nomi"][0])
        primo = next((i for i, p in enumerate(pers)
                      if any(parole_nome(n) == tim for n in persone[p]["nomi"])), 0)
        ids = [ids[primo], ids[1 - primo]]
    return "/".join(ids) if ids else None


# ====================================================================== USCITE
NOMI_SCELTI = {}      # nome della barca "come lo scrive di solito" (preparato da scegli_nomi)


def nome_migliore(scheda_persona):
    """Il nome scritto più spesso nelle classifiche; a parità preferisce la forma con il COGNOME in
    maiuscolo ('Lorenzo Brando CHIAVARINI' invece di 'Lorenzo Brando Chiavarini')."""
    def punteggio(item):
        nome, volte = item
        maiuscolo = any(len(w) > 1 and w == w.upper() and w != w.lower() for w in nome.split())
        tutto_maiuscolo = nome == nome.upper()
        return (volte + (2 if maiuscolo and not tutto_maiuscolo else 0), not tutto_maiuscolo)
    return max(scheda_persona["nomi"].items(), key=punteggio)[0]


def scegli_nomi(B, persone):
    """Per ogni barca: timoniere e prodiere (ordine dell'ultima regata) con il loro nome più usato."""
    for k, b in B.items():
        pers = [p for p in k[1] if not p.startswith("?")]
        t_ultimo = parole_nome((b["nomi"] or ("", ""))[0])
        ordinati = sorted(pers, key=lambda p: 0 if any(parole_nome(n) == t_ultimo for n in persone[p]["nomi"]) else 1)
        nomi = [nome_migliore(persone[p]) for p in ordinati]
        NOMI_SCELTI[k] = (nomi[0] if nomi else "?", nomi[1] if len(nomi) > 1 else "")


def nome_barca(b):
    t, p = NOMI_SCELTI.get(b["chiave"]) or b["nomi"] or ("?", "")
    return f"{t} / {p}" if p else t


def nome_athletes(b):
    """Nome nel formato di Athletes: 'Nome COGNOME' o 'Nome COGNOME/Nome COGNOME'."""
    def formato(n):
        parole = lettere(n).split()
        if any(p == p.upper() and len(p) > 1 for p in parole):
            return " ".join(parole)
        return " ".join(parole[:-1] + [parole[-1].upper()]) if len(parole) > 1 else n
    t, p = NOMI_SCELTI.get(b["chiave"]) or b["nomi"] or ("", "")
    return formato(t) + (f"/{formato(p)}" if p else "")


def tag(b):
    return {"stabile": "", "provvisorio": " (provvisorio)", "nascosto": " [non mostrato]"}[b["livello"]]


def stampa_classifiche(B, quanti=10):
    log("\n" + "=" * 78)
    log(f"CLASSIFICA ELO DI PROVA (primi {quanti} per classe, solo ELO mostrati; più gli italiani)")
    log("=" * 78)
    for classe in CLASSI:
        lista = sorted((b for b in B.values() if b["classe"] == classe and b["livello"] != "nascosto"),
                       key=lambda b: -b["elo"])
        log(f"\n{classe}  ({len(lista)} con ELO mostrato su {sum(1 for b in B.values() if b['classe'] == classe)})")
        for i, b in enumerate(lista, 1):
            ita = b["noc"] == "ITA"
            if i <= quanti or ita:
                segno = "  ← Italia" if ita and i > quanti else ""
                log(f"  {i:>3}. {nome_barca(b)[:44]:<44} {b['noc']:<4} {b['elo']:7.0f}  "
                    f"{b['n']:>2} eventi, migliore {b['miglior_pos']}°{tag(b)}{segno}")


def stampa_soglie(B):
    log("\n" + "=" * 78)
    log("SCELTA DELLE SOGLIE (in numero di eventi): barche con ELO mostrato / stabili, per classe")
    log("=" * 78)
    combinazioni = [(2, 4), (3, 5), (3, 6), (4, 7), (5, 8)]
    log("  mostra/stabile " + " ".join(f"{SIGLA[c]:>8}" for c in CLASSI))
    for mostra, stabile in combinazioni:
        celle = []
        for c in CLASSI:
            lv = [livello_elo(b["n"], mostra, stabile) for b in B.values() if b["classe"] == c]
            celle.append(f"{lv.count('provvisorio') + lv.count('stabile')}/{lv.count('stabile')}")
        segno = "  ← attuali" if (mostra, stabile) == (SOGLIA_MOSTRA, SOGLIA_STABILE) else ""
        log(f"  {mostra:>2} / {stabile:<2}        " + " ".join(f"{x:>8}" for x in celle) + segno)


def scrivi_csv(percorso, intestazione, righe):
    """CSV con il punto e virgola: si apre bene con Excel in italiano."""
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(intestazione)
        w.writerows(righe)


def link(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}" if page_id else ""


def salva_elenchi(B, esiti, per_page, persone):
    def base(k):
        b = B[k]
        return [nome_barca(b), b["noc"], b["classe"], round(b["elo"]), b["n"], b["miglior_pos"], b["livello"],
                id_ws_barca(b, persone) or ""]
    intest = ["Barca", "NOC", "Classe", "ELO", "Eventi", "Miglior posizione", "Livello", "ID WS"]
    ordina = lambda k: (-B[k]["n"], nome_barca(B[k]))
    ab = sorted((k for k, e in esiti.items() if e["esito"] == "abbinato"), key=ordina)
    dc = sorted((k for k, e in esiti.items() if e["esito"] == "da creare"), key=ordina)
    inc = sorted((k for k, e in esiti.items() if e["esito"] == "incerto"), key=ordina)
    scrivi_csv(CSV_ABBINATI, intest + ["Pagina Athletes", "NOC Athletes", "Come", "Link"],
               [base(k) + [per_page[esiti[k]["page"]]["nome"], per_page[esiti[k]["page"]]["noc"],
                           esiti[k]["motivo"], link(esiti[k]["page"])] for k in ab])
    scrivi_csv(CSV_DA_CREARE, intest + ["Nome da scrivere in Athletes", "Disciplina da scegliere",
                                        "Altri modi in cui è scritto"],
               [base(k) + [nome_athletes(B[k]), B[k]["classe"],
                           " | ".join(n for p in B[k]["chiave"][1] if not p.startswith("?")
                                      for n in persone[p]["nomi"])] for k in dc])
    scrivi_csv(CSV_INCERTI, intest + ["Motivo", "Candidati in Athletes (nome | NOC | disciplina | link)"],
               [base(k) + [esiti[k]["motivo"],
                           " || ".join(f"{r['nome']} | {r['noc'] or '-'} | {'/'.join(r['disc']) or '-'} | "
                                       f"{link(r['page'])}" for r in esiti[k]["candidati"][:4])] for k in inc])
    return ab, dc, inc


def salva_json(B, esiti, eventi, persone, oggi):
    """vela-elo.json: ciò che serve alla pagina (sessione 3). Una voce per barca (atleta o equipaggio)."""
    barche = []
    for k, b in sorted(B.items(), key=lambda x: -x[1]["elo"]):
        e = esiti.get(k, {})
        t, p = NOMI_SCELTI.get(k) or b["nomi"] or ("", "")
        barche.append({"nome": nome_barca(b), "timoniere": t, "prodiere": p or None, "noc": b["noc"],
                       "classe": b["classe"], "equipaggio": b["classe"] in DOPPI,
                       "notion": (e.get("page") or "").replace("-", "") or None, "id_ws": id_ws_barca(b, persone),
                       "elo": round(b["elo"]), "elo_max": round(b["max"]), "partenza": b["partenza"],
                       "livello": b["livello"], "eventi": b["n"], "miglior_pos": b["miglior_pos"],
                       "vittorie": b["vittorie"], "podi": b["podi"], "ultimo": b["ultima"], "storico": b["storico"]})
    dati = {"aggiornato": oggi.isoformat(),
            "regole": {"partenza": ELO_PARTENZA, "k": K_BASE, "coeff_evento": COEFF_EVENTO,
                       "sconto_cambio_equipaggio": SCONTO_CAMBIO,
                       "inattivita": {"mesi_senza_effetto": MESI_SENZA_EFFETTO, "calo_mensile": CALO},
                       "soglia_provvisorio": SOGLIA_MOSTRA, "soglia_stabile": SOGLIA_STABILE},
            "eventi": [{"id": e["id"], "classe": e["classe"], "nome": e["nome"], "tipo": e["tipo"],
                        "inizio": e["inizio"], "fine": e["data"], "barche": len(e["barche"])} for e in eventi],
            "barche": barche}
    FILE_JSON.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ====================================================================== MAIN
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file JSON con {righe, athletes} salvati: collaudo senza Notion")
    ap.add_argument("--oggi", help="data del calcolo AAAA-MM-GG (di norma oggi)")
    args = ap.parse_args()
    solo_prova = os.getenv("DRY_RUN", "true").strip().lower() != "false" or bool(args.da_raw)
    oggi = dt.date.fromisoformat(args.oggi) if args.oggi else dt.date.today()
    log(f"ELO Vela 1.1 · {'SOLO PROVA: non scrivo nulla su Notion' if solo_prova else 'SCRITTURA su Notion'} "
        f"· data del calcolo {oggi.isoformat()}")

    # 1. lettura
    nuove_mancanti = []
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        grezze, athletes = raw["righe"], raw["athletes"]
    else:
        grezze = leggi_righe()
        athletes, nuove_mancanti = leggi_athletes()
        FILE_RAW.write_text(json.dumps({"righe": grezze, "athletes": athletes}, ensure_ascii=False),
                            encoding="utf-8")
    log(f"Righe lette dal db Agente Vela: {len(grezze)}")
    log(f"Pagine di Athletes con Sport = Sailing: {len(athletes)}, con ID WS già compilato: "
        f"{sum(1 for r in athletes if r['id_ws'])}")
    if nuove_mancanti:
        log(f"ATTENZIONE: in Athletes mancano le proprietà {', '.join(sorted(nuove_mancanti))} "
            "(da creare prima del lancio vero: 'ELO Vela' di tipo Numero, 'ID WS' di tipo Testo).")
        if not solo_prova:
            log("Lancio vero interrotto: crea le proprietà e rilancia.")
            return 1

    # 2. persone, barche ed eventi
    righe, scarti = prepara_righe(grezze)
    log(f"Righe usate: {len(righe)}")
    for motivo, n in scarti.most_common():
        if motivo.startswith("nota: "):
            log(f"  nota {n}: {motivo[6:]}: {', '.join(ID_SCARTATI[:15])}")
        else:
            log(f"  escluse {n}: {motivo}")
    persone, uniti = riconosci_persone(righe)
    piu_id = [p for p in persone.values() if len(p["ids"]) > 1]
    log(f"Atleti riconosciuti: {len(persone)} · con ID World Sailing: "
        f"{sum(1 for p in persone.values() if p['ids'])} · con più ID diversi (cambio di nazione?): {len(piu_id)}")
    log(f"Nomi quasi uguali uniti (da controllare in {CSV_UNITI.name}): {len(uniti)}")
    for classe, noc, a, b in uniti[:40]:
        log(f"  · {SIGLA[classe]:<7} {noc:<4} {a}  =  {b}")
    scrivi_csv(CSV_UNITI, ["Classe", "NOC", "Nome 1", "Nome 2"], uniti)
    for p in piu_id[:10]:
        log(f"  più ID: {', '.join(sorted(p['ids']))} → {', '.join(list(p['nomi'])[:3])}")
    eventi, doppie, piccoli = costruisci_eventi(righe)
    senza_prodiere = sum(1 for r in righe if r["classe"] in DOPPI and len(r["_persone"]) < 2)
    log(f"Eventi (evento + classe): {len(eventi)} · barche ripetute nello stesso evento (tenuta la migliore): "
        f"{doppie} · eventi con meno di 2 barche (saltati): {piccoli} · equipaggi senza prodiere: {senza_prodiere}")
    log("\nEventi in ordine di calcolo (data di fine · classe · tipo e coefficiente · barche):")
    for e in eventi:
        log(f"  {e['data']} · {SIGLA[e['classe']]:<7} · {e['tipo']} ({COEFF_EVENTO[e['tipo']]}) · "
            f"{len(e['barche']):>3} · {e['nome']}")

    # 3. calcolo
    B, prev = calcola_elo(eventi, oggi, verifica_da=DATA_VERIFICA)
    scegli_nomi(B, persone)
    livelli = Counter(b["livello"] for b in B.values())
    log(f"\nBarche con un ELO: {len(B)} · stabili {livelli['stabile']} · provvisorie {livelli['provvisorio']} "
        f"· non mostrate {livelli['nascosto']}")
    log("  per classe: " + ", ".join(f"{SIGLA[c]} {sum(1 for b in B.values() if b['classe'] == c)}" for c in CLASSI))
    nuovi_eq = [b for b in B.values() if b["da_equipaggi"]]
    log(f"Equipaggi partiti dall'ELO degli equipaggi precedenti dei loro atleti: {len(nuovi_eq)}")
    for b in sorted(nuovi_eq, key=lambda b: -b["n"])[:8]:
        log(f"  · {nome_barca(b)} ({SIGLA[b['classe']]}): partenza {b['partenza']}")

    log("\n" + "=" * 78)
    log(f"BONTÀ DELLE PREVISIONI (eventi dal {DATA_VERIFICA}, coppie di barche con almeno "
        f"{SOGLIA_MOSTRA} eventi alle spalle)")
    log("=" * 78)
    log(f"  Regole decise (K {K_BASE}, sconto {SCONTO_CAMBIO:.0%}):      {testo_previsioni(prev)}")
    varianti = [("K 32", dict(k_base=32)), ("K 96", dict(k_base=96)),
                ("K ×1,5 nei primi 3 eventi", dict(molt_nuovo=1.5, prime=3)),
                ("senza coefficienti evento", dict(usa_coeff=False)),
                ("sconto equipaggio 0%", dict(sconto=0.0)), ("sconto equipaggio 50%", dict(sconto=0.5))]
    for nome, opz in varianti:
        _, p = calcola_elo(eventi, oggi, verifica_da=DATA_VERIFICA, **opz)
        log(f"  Variante {nome:<31} {testo_previsioni(p)}")
    log("  (davanti il favorito: più alto è meglio; Brier e log-loss: più bassi è meglio;"
        " a caso: 50%, Brier 0,25, log-loss 0,693)")

    # 4. abbinamento con Athletes
    esiti = abbina(B, persone, athletes)
    per_page = {r["page"]: r for r in athletes}
    ab, dc, inc = salva_elenchi(B, esiti, per_page, persone)
    mostrato = lambda k: B[k]["livello"] != "nascosto"
    log("\n" + "=" * 78)
    log("ABBINAMENTO CON IL DB ATHLETES (solo pagine esistenti, Sport = Sailing)")
    log("=" * 78)
    log(f"Abbinati: {len(ab)} ({dict(Counter(esiti[k]['motivo'] for k in ab))}); con ELO mostrato: "
        f"{sum(1 for k in ab if mostrato(k))}")
    log(f"Da creare (lo script non li crea): {len(dc)}; con ELO mostrato: {sum(1 for k in dc if mostrato(k))}")
    log(f"Incerti: {len(inc)}; con ELO mostrato: {sum(1 for k in inc if mostrato(k))}")
    usate = {esiti[k]["page"] for k in ab}
    log(f"Pagine di vela in Athletes: {len(athletes)}, abbinate: {len(usate)}, senza barca riconosciuta: "
        f"{len(athletes) - len(usate)}")
    log("\nIncerti (tutti; prima quelli con più eventi):")
    for k in inc[:80]:
        b = B[k]
        log(f"  · {nome_barca(b)} ({b['noc']}, {SIGLA[b['classe']]}, {b['n']} eventi, ELO {b['elo']:.0f}) "
            f"→ {esiti[k]['motivo']}")
    log("\nDa creare con ELO mostrato e NOC ITA: " + (", ".join(
        nome_barca(B[k]) + f" ({SIGLA[B[k]['classe']]})" for k in dc if mostrato(k) and B[k]["noc"] == "ITA")
        or "nessuno"))
    righe_no = [r for r in athletes if r["page"] not in usate]
    log(f"\nPagine di Athletes NON abbinate (prime 60 su {len(righe_no)}): "
        + "; ".join(f"{r['nome']} ({codice_noc(r['noc']) or '-'})" for r in righe_no[:60]))
    log(f"Elenchi completi nei file {CSV_ABBINATI.name}, {CSV_DA_CREARE.name}, {CSV_INCERTI.name}, "
        f"{CSV_UNITI.name} (Artifacts del lancio).")

    stampa_soglie(B)
    stampa_classifiche(B)
    salva_json(B, esiti, eventi, persone, oggi)
    log(f"\n{FILE_JSON.name}: {len(B)} barche, {len(eventi)} eventi")

    if solo_prova:
        log("\nProva terminata: non è stato scritto nulla su Notion.")
        return 0

    # 5. scrittura su Notion (solo Athletes; solo ELO Vela e ID WS vuoti; solo abbinati)
    log("\n" + "=" * 78)
    log("SCRITTURA IN ATHLETES")
    log("=" * 78)
    aggiornate = invariate = errori = 0
    for k in ab:
        if minuti() > TEMPO_MAX_MINUTI:
            log(f"ATTENZIONE: mi sono fermato dopo {TEMPO_MAX_MINUTI:.0f} minuti. Rilancia.")
            return 1
        riga = per_page[esiti[k]["page"]]
        elo = round(B[k]["elo"])
        nuovi = {}
        if riga["elo"] is None or round(riga["elo"]) != elo:
            nuovi["ELO Vela"] = elo
        ident = id_ws_barca(B[k], persone)
        if not riga["id_ws"] and ident:
            nuovi["ID WS"] = ident
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
