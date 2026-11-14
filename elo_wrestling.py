#!/usr/bin/env python3
"""ELO Wrestling (scheda 22 regole §5, scheda 24 sessione 2) – repo map-q-la28

Che cosa fa
-----------
1. Legge da Notion tutti gli incontri del db "🤼 Agente Wrestling" (scritti dall'agente UWW).
2. Calcola un rating ELO per ogni lottatore, incontro dopo incontro, con le regole del §5 della
   scheda 22. Ci sono DUE ELO separati ("pool"):
     - FS = libera maschile (Freestyle) + libera femminile (Women's Wrestling);
     - GR = greco-romana (Greco-Roman).
   Chi lotta in entrambi gli stili ha due ELO.
3. Abbina ogni lottatore (codice ID UWW) a una riga del db Athletes e divide i lottatori in tre elenchi:
     - ABBINATI  : riga di Athletes trovata con certezza;
     - DA CREARE : nessuna riga somigliante in Athletes;
     - INCERTI   : c'è una riga somigliante, ma non basta per esserne certi: decide Gualtiero.
4. In "Solo prova" (DRY_RUN=true) NON scrive nulla su Notion: stampa gli elenchi e una classifica ELO
   di prova e salva gli elenchi in file CSV da aprire con Excel.
5. Nel lancio vero scrive in Athletes:
     - `ELO FS` e `ELO GR` per tutti gli abbinati (sono gli unici campi che vengono riscritti);
     - `ID UWW` e `NOC` solo dove sono vuoti;
     - le righe nuove per i lottatori DA CREARE;
   e salva wrestling-elo.json (storico, incontri e tornei per atleta) per la pagina
   wrestling-performance.html (sessione 3).

REGOLA FONDAMENTALE (scheda 22 §4.2): nessuna operazione su Athletes elimina dati già inseriti.
Lo script non archivia righe, non svuota campi e nelle righe esistenti scrive solo `ELO FS`,
`ELO GR` e, se vuoti, `ID UWW` e `NOC`. La funzione `aggiorna_riga` controlla questo vincolo
prima di ogni scrittura.

Uso
---
  NOTION_TOKEN=... DRY_RUN=true python elo_wrestling.py      Solo prova
  NOTION_TOKEN=... DRY_RUN=false python elo_wrestling.py     lancio vero
  python elo_wrestling.py --da-raw dati.json                  collaudo con dati salvati (non tocca Notion)

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
DS_AGENTE_WRESTLING = "40ef48c9-aad9-809e-995f-000b5420780c"  # data source del db "🤼 Agente Wrestling"
DS_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"          # data source del db Athletes
NOMI_DB = {DS_AGENTE_WRESTLING: "🤼 Agente Wrestling", DS_ATHLETES: "Athletes"}

# Nomi ESATTI delle colonne (scheda 22 §2.1, §2.5 e §4)
COL_W = {"p1": "Player 1", "noc1": "NOC 1", "id1": "ID UWW 1",
         "p2": "Player 2", "noc2": "NOC 2", "id2": "ID UWW 2",
         "vincitore": "Vincitore", "gender": "Gender", "stile": "Stile", "cat": "Categoria",
         "score": "Score", "turno": "Turno", "torneo": "Torneo", "tipo": "Tipo Torneo",
         "data": "Data", "uid": "ID Univoco"}
COL_A = {"nome": "Cognome e Nome", "sport": "Sport", "noc": "NOC", "disc": "Disciplina",
         "id_uww": "ID UWW", "elo_fs": "ELO FS", "elo_gr": "ELO GR"}
SPORT = "Wrestling"                    # valore esatto di `Sport` per i lottatori (scheda 22 §2.5)
# Campi di Athletes che lo script può scrivere in una riga GIÀ ESISTENTE (§4.2)
SCRIVIBILI_SEMPRE = {"ELO FS", "ELO GR"}   # valori calcolati, appartengono allo script
SCRIVIBILI_SE_VUOTI = {"ID UWW", "NOC"}     # solo se la cella è vuota

# --- regole di calcolo (scheda 22 §5) ---
ELO_PARTENZA = 1500
K_BASE = 32
COEFF_TORNEO = {                        # §5.2, chiave = valore di "Tipo Torneo"
    "Olimpiadi": 1.5, "Mondiali": 1.25, "Campionati continentali": 1.0,
    "Giochi continentali": 1.0, "Ranking Series": 0.9, "Altri tornei": 0.8,
}
# Rete di sicurezza (§4.1): se "Tipo Torneo" è vuoto, il tipo si ricava dal nome del torneo.
# Il nome del Polyák ha DUE spazi tra "Imre" e "Varga": per questo i nomi si confrontano
# dopo aver tolto gli spazi doppi.
TIPO_DA_NOME = {
    "Islamic Solidarity Games": "Giochi continentali",
    "Zagreb Open": "Ranking Series",
    "Muhamet Malo": "Ranking Series",
    "Senior Asian Championships": "Campionati continentali",
    "Senior European Championships": "Campionati continentali",
    "Ulaanbaatar Open": "Ranking Series",
    "Polyák Imre Varga János & Kozma István Memorial": "Ranking Series",
    "Asian Games": "Giochi continentali",
    "Senior World Championships": "Mondiali",
}
ESCLUSI = {"VFO", "VIN"}       # §5.1: forfait e ritiro per infortunio, fuori dall'ELO
MOV_SCHIENATA = 1.5            # §5.4: VFA
MOV_SUPERIORITA = 1.3          #       VSU e VSU1
MOV_SQUALIFICA = 0.85          #       DSQ e VCA
MOV_CRITERIO = 0.9             #       VPO/VPO1 con scarto 0 (vittoria per criterio)
MOV_EXTRA_MAX = 0.15           #       ai punti: 1,0 + 0,15 × (d − 1) / (S − 2)
SOGLIA_SUPERIORITA = {"Freestyle": 10, "Women's Wrestling": 10, "Greco-Roman": 8}
POOL_DI_STILE = {"Freestyle": "FS", "Women's Wrestling": "FS", "Greco-Roman": "GR"}
COLONNA_POOL = {"FS": "ELO FS", "GR": "ELO GR"}
FASE_FINALI = {"1/2 Final", "Final 3-5", "Final 3-4", "Final 1-2"}   # §5.5
TORNEI_FASE = {"Olimpiadi", "Mondiali"}
MOLT_FASE = 1.10
SOGLIA_NUOVO = 8             # §5.3: sotto gli 8 incontri dello stile il K si moltiplica per...
MOLT_NUOVO = 1.5             # ... 1,5
SALITA = 0.90                # §5.6: salita di peso, distanza da 1500 × 0,90
DISCESA = 0.95               #       discesa di peso, distanza da 1500 × 0,95
GIORNI_STESSA_CAT = 365      #       nessuna riduzione se ha lottato in quella categoria negli ultimi 12 mesi
MESI_SENZA_EFFETTO = 9       # §5.7: inattività tollerata
CALO_MENSILE = 0.03          #       poi -3% al mese della distanza da 1500
SOGLIA_MOSTRA = 6            # §5.8: da 6 incontri (e 2 tornei) ELO "provvisorio"
SOGLIA_STABILE = 12          #       da 12 incontri ELO "stabile"
MIN_TORNEI = 2

# Categorie olimpiche per stile (senza 🔴 in Disciplina, scheda 22 §2.5), in kg
OLIMPICHE = {"Freestyle": [57, 65, 74, 86, 97, 125],
             "Greco-Roman": [60, 67, 77, 87, 97, 130],
             "Women's Wrestling": [50, 53, 57, 62, 68, 76]}
# §5.10, caso "a metà strada" (es. 61 kg tra 57 e 65): True = la categoria più pesante.
# [DA DECIDERE] da Gualtiero: proposta accettata in attesa di conferma.
META_STRADA_PIU_PESANTE = True
SIGLA_STILE = {"Freestyle": "FS", "Greco-Roman": "GR", "Women's Wrestling": "WW"}

# §4.3, nomi con più nomi propri (UWW "Spencer Richard LEE", Athletes "Spencer LEE"):
# True = abbinati se coincidono cognome, NOC, categoria e almeno uno dei nomi propri.
# [DA DECIDERE] da Gualtiero dopo la "Solo prova": se False finiscono tra gli incerti.
ABBINA_PIU_NOMI = True

# Righe di Athletes con Disciplina VUOTA (oggi circa 200 lottatori): True = basta nome + NOC
# (NOC uguale e non vuoto), come la regola del "NOC vuoto" del judo. Disciplina NON viene scritta.
# [DA DECIDERE] da Gualtiero: se False finiscono tra gli incerti.
ABBINA_DISCIPLINA_VUOTA = True

# Codici di atleti neutrali o rifugiati: non hanno un'opzione NOC in Athletes
CODICI_NEUTRALI = {"UWW", "EOR", "AIN", "NEU"}

PAUSA_NOTION = 0.35          # secondi tra una scrittura e l'altra (Notion accetta ~3 richieste/s)
TEMPO_MAX_MINUTI = float(os.getenv("TEMPO_MAX_MINUTI", "").strip() or 165)

FILE_JSON = CARTELLA / "wrestling-elo.json"
FILE_RAPPORTO = CARTELLA / "rapporto_elo_wrestling.txt"
CSV_ABBINATI = CARTELLA / "elo_wrestling_abbinati.csv"
CSV_DA_CREARE = CARTELLA / "elo_wrestling_da_creare.csv"
CSV_INCERTI = CARTELLA / "elo_wrestling_incerti.csv"


# ====================================================================== LOG
_righe_log = []


def log(testo=""):
    """Stampa a video e conserva la riga per il file del rapporto."""
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
    """Righe del db Agente Wrestling nel formato interno dello script."""
    controlla_colonne(DS_AGENTE_WRESTLING, COL_W.values())
    incontri = []
    for pg in interroga(DS_AGENTE_WRESTLING):
        p = pg["properties"]
        incontri.append({k: (valore(p.get(c)) or "") for k, c in COL_W.items()})
    return incontri


def leggi_athletes():
    """Lottatori del db Athletes (Sport = Wrestling) e opzioni esistenti di NOC e Disciplina."""
    props = controlla_colonne(DS_ATHLETES, COL_A.values())
    opzioni = {"noc": [o["name"] for o in props[COL_A["noc"]]["select"]["options"]],
               "disc": [o["name"] for o in props[COL_A["disc"]]["multi_select"]["options"]],
               "sport": [o["name"] for o in props[COL_A["sport"]]["select"]["options"]]}
    if SPORT not in opzioni["sport"]:
        sys.exit(f"ERRORE: in Athletes la colonna Sport non ha l'opzione '{SPORT}'.")
    atleti = []
    for pg in interroga(DS_ATHLETES, {"property": COL_A["sport"], "select": {"equals": SPORT}}):
        p = pg["properties"]
        atleti.append({"page": pg["id"], "nome": valore(p.get(COL_A["nome"])) or "",
                       "noc": valore(p.get(COL_A["noc"])) or "",
                       "disc": valore(p.get(COL_A["disc"])) or [],
                       "id_uww": (valore(p.get(COL_A["id_uww"])) or "").strip(),
                       "elo_fs": valore(p.get(COL_A["elo_fs"])),
                       "elo_gr": valore(p.get(COL_A["elo_gr"]))})
    return atleti, opzioni


def aggiorna_riga(atleta, nuovi):
    """Scrive in una riga ESISTENTE di Athletes, rispettando la regola fondamentale (§4.2).

    nuovi = {nome colonna: valore}. Rifiuta qualsiasi colonna non ammessa e salta i campi
    "solo se vuoti" quando la cella contiene già qualcosa.
    """
    props = {}
    for col, val in nuovi.items():
        if col in SCRIVIBILI_SEMPRE:
            props[col] = {"number": val}
        elif col in SCRIVIBILI_SE_VUOTI:
            attuale = atleta["id_uww"] if col == "ID UWW" else atleta["noc"]
            if attuale:
                continue                     # la cella è già compilata: non la tocco
            props[col] = ({"rich_text": [{"text": {"content": str(val)}}]} if col == "ID UWW"
                          else {"select": {"name": val}})
        else:
            raise RuntimeError(f"tentativo di scrivere la colonna non ammessa '{col}': bloccato")
    if props:
        chiama("PATCH", f"pages/{atleta['page']}", {"properties": props})
    return bool(props)


def crea_riga(dati):
    """Crea una riga nuova in Athletes per un lottatore che non c'è ancora (§4.3)."""
    props = {COL_A["nome"]: {"title": [{"text": {"content": dati["nome"]}}]},
             COL_A["sport"]: {"select": {"name": SPORT}},
             COL_A["id_uww"]: {"rich_text": [{"text": {"content": dati["id"]}}]}}
    for col, val in dati["elo"].items():          # {"ELO FS": 1612, "ELO GR": 1490}
        props[col] = {"number": val}
    if dati["noc_notion"]:
        props[COL_A["noc"]] = {"select": {"name": dati["noc_notion"]}}
    if dati["disc"]:
        props[COL_A["disc"]] = {"multi_select": [{"name": d} for d in dati["disc"]]}
    r = chiama("POST", "pages", {"parent": {"type": "data_source_id", "data_source_id": DS_ATHLETES},
                                 "properties": props})
    return r["id"]


# ====================================================================== LETTURA DELLO SCORE
# Esempi di Score: "6-2 (VPO1)", "10-0 (VSU)", "5-16 (VSU1)", "2-2 (VFA)", "(VFO)".
# Il primo numero è di Player 1, il secondo di Player 2.
RE_SCORE = re.compile(r"^(?:(\d+)\s*-\s*(\d+))?\s*(?:\(\s*([^)]*?)\s*\))?$")


def leggi_score(score):
    """'6-2 (VPO1)' -> (6, 2, 'VPO1'); punti None se mancano; tipo '' se manca."""
    m = RE_SCORE.match((score or "").strip())
    if not m:
        return None, None, ""
    a, b, tipo = m.groups()
    return (int(a) if a else None), (int(b) if b else None), (tipo or "").upper()


def mov(tipo, punti_v, punti_p, stile):
    """Qualità della vittoria (§5.4), in ordine di precedenza. Restituisce (MoV, etichetta)."""
    if tipo == "VFA":
        return MOV_SCHIENATA, "schienata"
    if tipo in ("VSU", "VSU1"):
        return MOV_SUPERIORITA, "superiorità"
    if tipo in ("DSQ", "VCA"):
        return MOV_SQUALIFICA, "squalifica"
    if tipo in ("VPO", "VPO1"):
        if punti_v is None or punti_p is None:
            return 1.0, "punti (scarto sconosciuto)"
        d = max(0, punti_v - punti_p)
        if d == 0:
            return MOV_CRITERIO, "criterio"
        s = SOGLIA_SUPERIORITA[stile]
        return min(1.0 + MOV_EXTRA_MAX, 1.0 + MOV_EXTRA_MAX * (d - 1) / (s - 2)), "punti"
    return 1.0, f"tipo sconosciuto '{tipo}'"


def kg(cat):
    """'86 kg' -> 86 (0 se non leggibile)."""
    m = re.match(r"\s*(\d+)", cat or "")
    return int(m.group(1)) if m else 0


def ordine_turno(turno):
    """§5.9: gironi, Qualif., 1/16, 1/8, 1/4, 1/2, Repechage, finali per il bronzo, finale."""
    fissi = {"Qualif.": 1, "1/16 Final": 2, "1/8 Final": 3, "1/4 Final": 4, "1/2 Final": 5,
             "Repechage": 6, "Final 3-5": 7, "Final 3-4": 7, "Final 1-2": 8}
    if turno in fissi:
        return fissi[turno]
    m = re.fullmatch(r"(?:[AB] \| )?Round (\d+)", turno or "")
    if m:                               # gironi: Round 1 (0,01) ... Round 5 (0,05)
        return int(m.group(1)) / 100
    return None


def mesi_interi(d1, d2):
    """Mesi di calendario interi tra due date (dal 13/11/2025 al 13/11/2026 = 12)."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)


def con_inattivita(rating, ultima, giorno):
    """Calo per inattività (§5.7) tra la data `ultima` e la data `giorno`."""
    if not ultima:
        return rating
    mesi_calo = mesi_interi(dt.date.fromisoformat(ultima), dt.date.fromisoformat(giorno)) - MESI_SENZA_EFFETTO
    if mesi_calo <= 0:
        return rating
    return ELO_PARTENZA + (rating - ELO_PARTENZA) * (1 - CALO_MENSILE) ** mesi_calo


def spazi(testo):
    return " ".join((testo or "").split())


# ====================================================================== CALCOLO ELO
def prepara(incontri):
    """Controlla le righe e le trasforma; restituisce (incontri validi, scarti, avvisi)."""
    scarti, avvisi = Counter(), Counter()
    tipo_da_nome = {spazi(k): v for k, v in TIPO_DA_NOME.items()}
    visti, validi = set(), []
    for m in incontri:
        uid = (m.get("uid") or "").strip()
        if uid and uid in visti:
            scarti["ID Univoco doppio (contato una volta sola)"] += 1
            continue
        visti.add(uid)
        a, b, tipo_v = leggi_score(m.get("score"))
        stile = m.get("stile") or ""
        tipo_t = m.get("tipo") or ""
        if not tipo_t and spazi(m.get("torneo")) in tipo_da_nome:
            tipo_t = tipo_da_nome[spazi(m.get("torneo"))]
            avvisi[f"Tipo Torneo vuoto, ricavato dal nome: {m.get('torneo')} -> {tipo_t}"] += 1
        id1, id2 = (m.get("id1") or "").strip(), (m.get("id2") or "").strip()
        vince = 1 if m.get("vincitore") == m.get("p1") else 2 if m.get("vincitore") == m.get("p2") else 0
        if m.get("p1") == m.get("p2"):
            vince = 0
        if tipo_v in ESCLUSI:
            scarti[f"{tipo_v} (escluso per regola)"] += 1
        elif not id1 or not id2:
            scarti["manca un ID UWW (riga da completare con l'agente in modalità completa)"] += 1
        elif id1 == id2:
            scarti["stesso ID UWW per i due lottatori"] += 1
        elif stile not in POOL_DI_STILE:
            scarti[f"Stile sconosciuto: '{stile}'"] += 1
        elif vince not in (1, 2):
            scarti["Vincitore diverso da Player 1 e Player 2"] += 1
        elif tipo_t not in COEFF_TORNEO:
            scarti[f"Tipo Torneo sconosciuto: '{tipo_t}' ({m.get('torneo')})"] += 1
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.get("data") or ""):
            scarti["data mancante"] += 1
        else:
            if ordine_turno(m.get("turno")) is None:
                avvisi[f"turno non previsto (messo tra 1/4 e 1/2): '{m.get('turno')}'"] += 1
            pv, pp = (a, b) if vince == 1 else (b, a)
            coeff, modo = mov(tipo_v, pv, pp, stile)
            if modo.startswith("tipo sconosciuto"):
                avvisi[f"Score con tipo di vittoria sconosciuto (MoV 1,0): '{m.get('score')}'"] += 1
            validi.append({**m, "uid": uid, "slug": uid.split("|")[0], "tipo": tipo_t,
                           "pool": POOL_DI_STILE[stile], "id1": id1, "id2": id2, "vince": vince,
                           "mov": coeff, "modo": modo, "kg": kg(m.get("cat"))})
    return validi, scarti, avvisi


def calcola_elo(incontri, oggi):
    """Calcola l'ELO di tutti i lottatori, separato per pool (FS e GR).

    Restituisce (A, scarti, avvisi, statistiche). A è un dizionario
    (pool, ID UWW) -> scheda del lottatore in quel pool.
    """
    validi, scarti, avvisi = prepara(incontri)

    # §5.3: MoV normalizzato per stile = MoV / media del MoV dello stile
    somme = defaultdict(lambda: [0.0, 0])
    for m in validi:
        somme[m["stile"]][0] += m["mov"]
        somme[m["stile"]][1] += 1
    media_mov = {s: (t / n if n else 1.0) for s, (t, n) in somme.items()}

    # §5.9: data, turno, ID Univoco
    validi.sort(key=lambda m: (m["data"], ordine_turno(m["turno"]) if ordine_turno(m["turno"]) is not None
                               else 4.5, m["uid"]))

    A = {}

    def scheda(pool, pid, nome, noc, m):
        a = A.get((pool, pid))
        if a is None:
            a = A[(pool, pid)] = {
                "id": pid, "pool": pool, "nome": nome, "noc": noc, "rating": float(ELO_PARTENZA),
                "n": 0, "v": 0, "ultima": None, "tornei": [], "max": float(ELO_PARTENZA),
                "storico": [], "cat_n": Counter(), "cat_ultima_data": {}, "ultima_cat": "",
                "ultimo_kg": 0, "stile": m["stile"], "gender": m["gender"], "noc_tutti": [],
                "cambi": []}
        # tengo i dati più recenti (gli incontri arrivano in ordine di data)
        a["nome"], a["stile"], a["gender"] = nome or a["nome"], m["stile"], m["gender"] or a["gender"]
        if noc:
            a["noc"] = noc
            if noc not in a["noc_tutti"]:
                a["noc_tutti"].append(noc)
        return a

    modi = defaultdict(Counter)
    for m in validi:
        a = scheda(m["pool"], m["id1"], m["p1"], m["noc1"], m)
        b = scheda(m["pool"], m["id2"], m["p2"], m["noc2"], m)
        for x in (a, b):
            # 1) inattività fino al giorno dell'incontro (§5.7)
            x["rating"] = con_inattivita(x["rating"], x["ultima"], m["data"])
            # 2) cambio di categoria di peso (§5.6)
            if x["ultimo_kg"] and m["kg"] and m["kg"] != x["ultimo_kg"] and x["rating"] > ELO_PARTENZA:
                ultima_qui = x["cat_ultima_data"].get(m["cat"])
                recente = ultima_qui and (dt.date.fromisoformat(m["data"]) -
                                          dt.date.fromisoformat(ultima_qui)).days <= GIORNI_STESSA_CAT
                if not recente:
                    f = SALITA if m["kg"] > x["ultimo_kg"] else DISCESA
                    prima = x["rating"]
                    x["rating"] = ELO_PARTENZA + f * (x["rating"] - ELO_PARTENZA)
                    x["cambi"].append([m["data"], x["ultima_cat"], m["cat"], round(prima), round(x["rating"])])
        modi[m["stile"]][m["modo"]] += 1
        fase = MOLT_FASE if (m["turno"] in FASE_FINALI and m["tipo"] in TORNEI_FASE) else 1.0
        k_comune = K_BASE * COEFF_TORNEO[m["tipo"]] * (m["mov"] / media_mov[m["stile"]]) * fase
        ra, rb = a["rating"], b["rating"]            # rating PRIMA dell'incontro
        for x, r_io, r_avv, s in ((a, ra, rb, 1 if m["vince"] == 1 else 0),
                                  (b, rb, ra, 1 if m["vince"] == 2 else 0)):
            atteso = 1 / (1 + 10 ** ((r_avv - r_io) / 400))
            k = k_comune * (MOLT_NUOVO if x["n"] < SOGLIA_NUOVO else 1)
            x["rating"] = r_io + k * (s - atteso)
            x["n"] += 1
            x["v"] += s
            x["ultima"] = m["data"]
            x["max"] = max(x["max"], x["rating"])
            x["cat_n"][m["cat"]] += 1
            x["cat_ultima_data"][m["cat"]] = m["data"]
            x["ultima_cat"], x["ultimo_kg"] = m["cat"], m["kg"]
            if m["slug"] not in x["tornei"]:          # tornei diversi disputati
                x["tornei"].append(m["slug"])
            # storico: un punto per torneo (il valore dopo l'ultimo incontro di quel torneo)
            if x["storico"] and x["storico"][-1][2] == m["slug"]:
                x["storico"][-1] = [m["data"], round(x["rating"]), m["slug"]]
            else:
                x["storico"].append([m["data"], round(x["rating"]), m["slug"]])

    # ELO alla data del calcolo (con l'eventuale calo per inattività), livello e categoria di riferimento
    for a in A.values():
        a["elo"] = con_inattivita(a["rating"], a["ultima"], oggi.isoformat())
        a["n_tornei"] = len(a["tornei"])
        if a["n"] < SOGLIA_MOSTRA or a["n_tornei"] < MIN_TORNEI:
            a["livello"] = "nascosto"
        elif a["n"] < SOGLIA_STABILE:
            a["livello"] = "provvisorio"
        else:
            a["livello"] = "stabile"
        a["cat_rif"], a["come_rif"] = categoria_riferimento(a)
    stat = {"validi": len(validi), "modi": modi, "media_mov": media_mov,
            "per_stile": Counter(m["stile"] for m in validi)}
    return A, scarti, avvisi, stat, validi


def categoria_riferimento(a):
    """Categoria olimpica in cui mostrare il lottatore nella pagina (§5.10).

    Restituisce (categoria, come è stata scelta).
    """
    olimpiche = OLIMPICHE.get(a["stile"], [])
    # per ogni categoria: (incontri, data dell'ultimo incontro) -> la più frequente, poi la più recente
    def migliore(categorie):
        return max(categorie, key=lambda c: (a["cat_n"][c], a["cat_ultima_data"].get(c, "")))
    # categorie disputate nel pool (un lottatore è o uomo o donna, quindi lo stile è uno solo)
    proprie = list(a["cat_n"])
    olimp = [c for c in proprie if kg(c) in olimpiche]
    if olimp:
        return migliore(olimp), "olimpica più frequente"
    if not proprie or not olimpiche:
        return a["ultima_cat"], "ultima categoria"
    base = kg(migliore(proprie))
    distanza = lambda o: abs(o - base)
    vicine = sorted(olimpiche, key=lambda o: (distanza(o), -o if META_STRADA_PIU_PESANTE else o))
    scelta = vicine[0]
    a_meta = len(vicine) > 1 and distanza(vicine[0]) == distanza(vicine[1])
    return f"{scelta} kg", ("olimpica più vicina" + (" (a metà strada: la più pesante)" if a_meta else ""))


# ====================================================================== NOMI E ABBINAMENTO
def lettere(testo):
    """Tiene solo lettere vere, spazi e trattini; toglie apici (²ˣᵒᶜ), emoji e simboli."""
    out = []
    for ch in testo or "":
        cat = unicodedata.category(ch)
        if cat in ("Lu", "Ll", "Lt", "Lo"):     # NON "Lm": ˣ ᵒ ᶜ ʷ sono lettere-apice decorative
            out.append(ch)
        elif ch in " -'’‘. ":
            out.append(" ")
    return " ".join("".join(out).split())


def senza_accenti(testo):
    t = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def parti_nome(nome):
    """Divide un nome in (COGNOME, Nome, tutto insieme, nomi propri singoli).

    Il cognome si riconosce dalle MAIUSCOLE: vale per "Nome COGNOME" (UWW e Athletes),
    per "Spencer Richard LEE" e per "Bekzat ALMAZ UULU". Se tutto è in maiuscolo
    (es. "JALGASBAY BERDIMURATOV") il nome intero finisce nel "cognome".
    I pezzi sono "compattati": senza spazi, trattini e accenti, in maiuscolo.
    """
    parole = lettere(nome).split()
    cognome = [p for p in parole if len(p) > 1 and p == p.upper() and p != p.lower()]
    altri = [p for p in parole if p not in cognome]
    if not cognome or not altri:            # formato non riconosciuto: tutto nel "cognome"
        cognome, altri = parole, []
    c = senza_accenti("".join(cognome))
    n = senza_accenti("".join(altri))
    insieme = "".join(sorted(senza_accenti(p) for p in parole))
    singoli = {senza_accenti(p) for p in altri if len(p) > 1}
    return c, n, insieme, singoli


RE_DISC = re.compile(r"(Men|Women)'s\s*(\d+)\s*kg\s*(FS|GR|WW)", re.I)


def chiave_disc(testo):
    """"🔴Men's 61kg FS" -> ('Men', 61, 'FS'); il 🔴 iniziale si ignora (§4.3). None se non è lotta."""
    m = RE_DISC.search(testo or "")
    return (m.group(1).capitalize(), int(m.group(2)), m.group(3).upper()) if m else None


def chiave_incontro(stile, gender, cat):
    """('Freestyle', 'Men', '74 kg') -> ('Men', 74, 'FS')."""
    return (gender, kg(cat), SIGLA_STILE.get(stile, ""))


def codice_noc(valore_noc):
    """'🇪🇸ESP' -> 'ESP' (ultime tre lettere maiuscole)."""
    m = re.search(r"([A-Z]{2,3})$", valore_noc or "")
    return m.group(1) if m else ""


def simile(x, y):
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def persone(A):
    """Raccoglie i due pool per persona: un lottatore = un ID UWW = una riga di Athletes."""
    P = {}
    for (pool, pid), a in sorted(A.items(), key=lambda kv: kv[1]["ultima"] or ""):
        p = P.setdefault(pid, {"id": pid, "pool": {}, "nome": "", "noc": "", "noc_set": set(),
                               "chiavi": set(), "ultima": ""})
        p["pool"][pool] = a
        if (a["ultima"] or "") >= p["ultima"]:      # nome e NOC più recenti
            p["ultima"], p["nome"] = a["ultima"] or "", a["nome"]
        for c in a["cat_n"]:
            p["chiavi"].add(chiave_incontro(a["stile"], a["gender"], c))
    # NOC: il più recente tra quelli "veri" (non neutrali); i neutrali solo se non c'è altro
    for p in P.values():
        tutti = [n for a in sorted(p["pool"].values(), key=lambda a: a["ultima"] or "") for n in a["noc_tutti"]]
        veri = [n for n in tutti if n not in CODICI_NEUTRALI]
        p["noc_set"] = set(veri)
        p["noc"] = veri[-1] if veri else (tutti[-1] if tutti else "")
    return P


def abbina(P, athletes):
    """Divide i lottatori in abbinati / da creare / incerti (scheda 22 §4.2 e §4.3, come judo §5.9).

    Restituisce un dizionario  ID UWW -> {"esito", "page", "motivo", "candidati"}.
    """
    per_id = defaultdict(list)
    for r in athletes:
        if r["id_uww"]:
            per_id[r["id_uww"]].append(r)
    liberi = [r for r in athletes if not r["id_uww"]]
    for r in liberi:
        r["_c"], r["_n"], r["_ins"], r["_singoli"] = parti_nome(r["nome"])
        r["_codice"] = codice_noc(r["noc"])
        r["_disc"] = {k for k in (chiave_disc(d) for d in r["disc"]) if k}

    def noc_ok(r, p):
        # NOC uguale a uno dei NOC "veri" del lottatore; oppure NOC vuoto in Athletes (come il judo);
        # oppure lottatore che ha gareggiato solo come neutrale (UWW, EOR): il NOC non dice nulla
        return r["_codice"] in p["noc_set"] or not r["_codice"] or not p["noc_set"]

    def cat_ok(r, p):
        # categoria in comune con Disciplina; oppure (se ABBINA_DISCIPLINA_VUOTA) Disciplina vuota
        # in Athletes ma NOC uguale e non vuoto
        if r["_disc"] & p["chiavi"]:
            return True
        return ABBINA_DISCIPLINA_VUOTA and not r["_disc"] and r["_codice"] in p["noc_set"]

    def valuta(p, liberi):
        """Cerca la riga di Athletes di un lottatore tra le righe `liberi` (senza ID UWW)."""
        c, n, ins, singoli = parti_nome(p["nome"])
        esatti, piu_nomi, simili = [], [], []
        for r in liberi:
            if (c == r["_c"] and n == r["_n"]) or (ins and ins == r["_ins"]):
                esatti.append(r)
            elif c == r["_c"] and singoli & r["_singoli"]:
                piu_nomi.append(r)     # stesso cognome e almeno un nome proprio in comune
            elif c == r["_c"] and (not n or not r["_n"] or n.startswith(r["_n"]) or r["_n"].startswith(n)
                                    or simile(n, r["_n"]) >= 0.75):
                simili.append(r)
            elif n and n == r["_n"] and (simile(c, r["_c"]) >= 0.8 or c in r["_c"] or r["_c"] in c):
                simili.append(r)
            elif c == r["_c"] and r["_codice"] in p["noc_set"] and r["_disc"] & p["chiavi"]:
                simili.append(r)       # stesso cognome, NOC e categoria: nome scritto diversamente
            elif simile(c + n, r["_c"] + r["_n"]) >= 0.88:
                simili.append(r)
        buoni = [r for r in esatti if noc_ok(r, p) and cat_ok(r, p)]
        # regola dei più nomi propri (§4.3): NOC deve coincidere davvero (non vuoto)
        buoni_piu = [r for r in piu_nomi if r["_codice"] in p["noc_set"] and cat_ok(r, p)]
        # omonimi: le altre righe con lo stesso nome sono di un'ALTRA categoria (non vuota), quindi
        # di un'altra persona (es. i due "Aman AMAN" indiani, uno in libera 57 kg e uno in greco 77 kg)
        omonimi_altrove = all(r["_disc"] and not r["_disc"] & p["chiavi"] for r in esatti if r not in buoni)
        if len(buoni) == 1 and (len(esatti) == 1 or omonimi_altrove):
            r = buoni[0]
            if len(esatti) > 1:
                come = "nome + NOC + categoria (omonimo in un'altra categoria)"
            elif not r["_disc"]:
                come = "nome + NOC (Disciplina vuota in Athletes)"
            elif r["_codice"] in p["noc_set"]:
                come = "nome + NOC + categoria"
            elif not r["_codice"]:
                come = "nome + categoria (NOC vuoto in Athletes)"
            else:
                come = "nome + categoria (lottatore solo neutrale)"
            return {"esito": "abbinato", "page": r["page"], "motivo": come, "candidati": buoni}
        elif ABBINA_PIU_NOMI and not esatti and len(buoni_piu) == 1 and len(piu_nomi) == 1:
            r = buoni_piu[0]
            return {"esito": "abbinato", "page": r["page"],
                    "motivo": "più nomi propri: cognome + un nome + NOC + categoria"
                              + (" (Disciplina vuota in Athletes)" if not r["_disc"] else ""),
                    "candidati": buoni_piu}
        elif esatti or piu_nomi or simili:
            motivi = []
            for r in esatti + piu_nomi:
                diff = []
                if not noc_ok(r, p):
                    diff.append(f"NOC {r['_codice']}")
                if not cat_ok(r, p):
                    diff.append(f"categoria {'/'.join(r['disc']) or 'vuota'}")
                tipo = "stesso nome" if r in esatti else f"nome diverso ({r['nome']})"
                motivi.append(tipo + (", ma " + " e ".join(diff) if diff else ""))
            if len(esatti) > 1:
                motivi.insert(0, f"{len(esatti)} righe con lo stesso nome")
            if simili:
                motivi.append(f"nome simile: {', '.join(r['nome'] for r in simili[:3])}")
            return {"esito": "incerto", "page": None, "motivo": "; ".join(motivi),
                    "candidati": esatti + piu_nomi + simili}
        else:
            return {"esito": "da creare", "page": None, "motivo": "nessuna riga somigliante",
                    "candidati": []}

    esiti = {}
    for pid, p in P.items():
        if pid in per_id:
            righe = per_id[pid]
            if len(righe) == 1:
                esiti[pid] = {"esito": "abbinato", "page": righe[0]["page"], "motivo": "ID UWW",
                              "candidati": righe}
            else:
                esiti[pid] = {"esito": "incerto", "page": None,
                              "motivo": f"ID UWW presente in {len(righe)} righe di Athletes", "candidati": righe}
        else:
            esiti[pid] = valuta(p, liberi)

    def togli_doppi():
        """Due lottatori UWW diversi abbinati con certezza alla STESSA riga: nessuno dei due è certo
        (es. due omonimi con stesso NOC e stessa categoria)."""
        per_riga = defaultdict(list)
        for pid, e in esiti.items():
            if e["esito"] == "abbinato" and e["motivo"] != "ID UWW":
                per_riga[e["page"]].append(pid)
        for page, pids in per_riga.items():
            if len(pids) > 1:
                for pid in pids:
                    esiti[pid].update(esito="incerto", page=None,
                                      motivo=f"{len(pids)} lottatori UWW (ID diversi) sulla stessa riga di Athletes")

    togli_doppi()
    # Secondo giro: una riga già presa con certezza da un lottatore non è più candidata per gli altri
    # (dal lancio successivo avrà l'ID UWW e sparirà comunque dai candidati). Rivaluto gli incerti
    # senza quelle righe, così il primo lancio e quelli successivi danno lo stesso risultato.
    prese = {e["page"] for e in esiti.values() if e["esito"] == "abbinato"}
    rimaste = [r for r in liberi if r["page"] not in prese]
    for pid, e in list(esiti.items()):
        if e["esito"] != "incerto" or e["motivo"].startswith("ID UWW") or "stessa riga" in e["motivo"]:
            continue
        nuovo = valuta(P[pid], rimaste)
        if nuovo["esito"] == "da creare":
            nuovo["motivo"] = "le righe somiglianti sono già abbinate ad altri lottatori"
        esiti[pid] = nuovo
    togli_doppi()
    return esiti


# ====================================================================== USCITE
def tag(a):
    return {"stabile": "", "provvisorio": " (provvisorio)", "nascosto": " [non mostrato]"}[a["livello"]]


def livello_persona(p):
    """Il livello "migliore" tra i due pool (serve solo per ordinare gli elenchi)."""
    ordine = {"stabile": 2, "provvisorio": 1, "nascosto": 0}
    return max((a["livello"] for a in p["pool"].values()), key=lambda l: ordine[l])


def stampa_classifiche(A, quanti=10):
    log("\n" + "=" * 78)
    log(f"CLASSIFICA ELO DI PROVA (primi {quanti} per categoria olimpica di riferimento, solo ELO mostrati)")
    log("=" * 78)
    for stile, pesi in OLIMPICHE.items():
        for k in pesi:
            cat = f"{k} kg"
            lista = [a for a in A.values() if a["stile"] == stile and a["cat_rif"] == cat
                     and a["livello"] != "nascosto"]
            lista.sort(key=lambda a: -a["elo"])
            log(f"\n{stile} {cat}  ({len(lista)} con ELO mostrato)")
            for i, a in enumerate(lista, 1):
                if i <= quanti or a["noc"] == "ITA":
                    log(f"  {i:>2}. {a['nome'][:32]:<32} {a['noc']:<4} {a['elo']:7.0f}  "
                        f"{a['n']:>2} inc. {a['n_tornei']:>2} tor.{tag(a)}"
                        + ("  ← Italia" if a["noc"] == "ITA" and i > quanti else ""))


def scrivi_csv(percorso, intestazione, righe):
    """CSV con il punto e virgola: si apre bene con Excel in italiano."""
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(intestazione)
        w.writerows(righe)


def link(page_id):
    return f"https://app.notion.com/p/{(page_id or '').replace('-', '')}" if page_id else ""


def discipline_persona(p, disc_ok=None):
    """Valori di Disciplina (formato Athletes) di tutte le categorie disputate.

    Con disc_ok (opzioni esistenti) restituisce i valori ESATTI delle opzioni, 🔴 compreso.
    """
    out = []
    for g, k, s in sorted(p["chiavi"], key=lambda x: (x[2], x[1])):
        if disc_ok is not None:
            opz = disc_ok.get((g, k, s))
            if opz:
                out.append(opz)
        else:
            out.append(f"{g}'s {k}kg {s}")
    return out


def salva_elenchi(P, esiti, per_page):
    def base(p):
        fs, gr = p["pool"].get("FS"), p["pool"].get("GR")
        return [p["id"], p["nome"], p["noc"], " / ".join(discipline_persona(p)),
                round(fs["elo"]) if fs else "", fs["n"] if fs else "", fs["livello"] if fs else "",
                round(gr["elo"]) if gr else "", gr["n"] if gr else "", gr["livello"] if gr else ""]
    intest = ["ID UWW", "Nome UWW", "NOC UWW", "Categorie disputate", "ELO FS", "Incontri FS", "Livello FS",
              "ELO GR", "Incontri GR", "Livello GR"]
    ordina = lambda pid: (-sum(a["n"] for a in P[pid]["pool"].values()), P[pid]["nome"])
    ab = sorted((p for p, e in esiti.items() if e["esito"] == "abbinato"), key=ordina)
    dc = sorted((p for p, e in esiti.items() if e["esito"] == "da creare"), key=ordina)
    inc = sorted((p for p, e in esiti.items() if e["esito"] == "incerto"), key=ordina)
    scrivi_csv(CSV_ABBINATI, intest + ["Riga Athletes", "NOC Athletes", "Come", "Link"],
               [base(P[p]) + [per_page[esiti[p]["page"]]["nome"], per_page[esiti[p]["page"]]["noc"],
                              esiti[p]["motivo"], link(esiti[p]["page"])] for p in ab])
    scrivi_csv(CSV_DA_CREARE, intest, [base(P[p]) for p in dc])
    scrivi_csv(CSV_INCERTI, intest + ["Motivo", "Candidati in Athletes (nome | NOC | Disciplina | link)"],
               [base(P[p]) + [esiti[p]["motivo"],
                              " || ".join(f"{r['nome']} | {r['noc'] or '-'} | {'/'.join(r['disc']) or '-'} | "
                                          f"{link(r['page'])}" for r in esiti[p]["candidati"][:4])]
                for p in inc])
    return ab, dc, inc


def salva_json(A, esiti, tornei, oggi, stat):
    """wrestling-elo.json: tutto ciò che serve alla pagina (sessione 3). Un record per lottatore e pool."""
    atleti = []
    for a in sorted(A.values(), key=lambda a: (a["pool"], -a["elo"])):
        e = esiti.get(a["id"], {})
        atleti.append({
            "id_uww": a["id"], "pool": a["pool"], "stile": a["stile"],
            "genere": "U" if a["gender"] == "Men" else "D",
            "nome": a["nome"], "noc": a["noc"],
            "notion": (e.get("page") or "").replace("-", "") or None,
            "cat": a["cat_rif"], "cat_ultima": a["ultima_cat"],
            "categorie": dict(a["cat_n"].most_common()),
            "elo": round(a["elo"]), "elo_max": round(a["max"]), "livello": a["livello"],
            "incontri": a["n"], "vittorie": a["v"], "tornei": a["n_tornei"], "ultimo": a["ultima"],
            "storico": [[d, v, c] for d, v, c in a["storico"]]})
    dati = {"aggiornato": oggi.isoformat(),
            "regole": {"partenza": ELO_PARTENZA, "k": K_BASE, "soglia_provvisorio": SOGLIA_MOSTRA,
                       "soglia_stabile": SOGLIA_STABILE, "min_tornei": MIN_TORNEI,
                       "media_mov": {k: round(v, 4) for k, v in stat["media_mov"].items()}},
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

    log(f"ELO Wrestling · {'SOLO PROVA: non scrivo nulla su Notion' if solo_prova else 'SCRITTURA su Notion'} "
        f"· data del calcolo {oggi.isoformat()}")

    # 1. lettura
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        incontri, athletes, opzioni = raw["incontri"], raw["athletes"], raw["opzioni"]
    else:
        incontri = leggi_incontri()
        athletes, opzioni = leggi_athletes()
    log(f"Incontri letti dal db Agente Wrestling: {len(incontri)}")
    log(f"Lottatori nel db Athletes (Sport = {SPORT}): {len(athletes)}, "
        f"con ID UWW già compilato: {sum(1 for r in athletes if r['id_uww'])}")

    # 2. calcolo
    A, scarti, avvisi, stat, validi = calcola_elo(incontri, oggi)
    log(f"Incontri usati nell'ELO: {stat['validi']}  ("
        + ", ".join(f"{s} {n}" for s, n in stat["per_stile"].most_common()) + ")")
    for motivo, n in scarti.most_common():
        log(f"  esclusi {n:>4}: {motivo}")
    for motivo, n in avvisi.most_common():
        log(f"  ATTENZIONE {n} incontri: {motivo}")
    log("Modo di vittoria e media del MoV per stile (§5.3: il MoV di ogni incontro viene diviso per la media):")
    for stile, c in stat["modi"].items():
        log(f"  {stile:<18} media MoV {stat['media_mov'][stile]:.3f} · "
            + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    for pool in ("FS", "GR"):
        liv = Counter(a["livello"] for a in A.values() if a["pool"] == pool)
        log(f"Pool {pool}: {sum(liv.values())} lottatori · stabili {liv['stabile']} · "
            f"provvisori {liv['provvisorio']} · non mostrati {liv['nascosto']}")
    cambi = [(a, c) for a in A.values() for c in a["cambi"]]
    log(f"Riduzioni per cambio di categoria (§5.6): {len(cambi)}")
    for a, (d, da, a_cat, prima, dopo) in sorted(cambi, key=lambda x: -x[1][3])[:10]:
        log(f"  · {a['nome']} ({a['noc']}, {a['pool']}) {d}: {da} → {a_cat}, {prima} → {dopo}")
    rif = Counter(a["come_rif"] for a in A.values())
    log("Categoria di riferimento (§5.10): " + ", ".join(f"{k} {v}" for k, v in rif.most_common()))
    meta = [a for a in A.values() if "metà strada" in a["come_rif"] and a["livello"] != "nascosto"]
    if meta:
        log("  con ELO mostrato e categoria 'a metà strada': "
            + ", ".join(f"{a['nome']} ({a['ultima_cat']} → {a['cat_rif']})" for a in meta[:15]))

    tornei = {}
    for m in validi:
        t = tornei.setdefault(m["slug"], {"nome": spazi(m.get("torneo")), "tipo": m["tipo"], "data": m["data"]})
        t["data"] = min(t["data"], m["data"])

    # 3. abbinamento con Athletes
    P = persone(A)
    esiti = abbina(P, athletes)
    per_page = {r["page"]: r for r in athletes}
    ab, dc, inc = salva_elenchi(P, esiti, per_page)
    log("\n" + "=" * 78)
    log("ABBINAMENTO CON IL DB ATHLETES (scheda 22 §4.2 e §4.3)")
    log("=" * 78)
    log(f"Lottatori (persone, per ID UWW): {len(P)}; in entrambi gli stili: "
        f"{sum(1 for p in P.values() if len(p['pool']) == 2)}")
    log(f"Abbinati: {len(ab)}")
    for come, n in Counter(esiti[p]["motivo"] for p in ab).most_common():
        log(f"  {n:>5}  {come}")
    piu = [p for p in ab if esiti[p]["motivo"].startswith("più nomi")]
    if piu:
        log(f"  Abbinati con la regola dei più nomi propri ({len(piu)}; ABBINA_PIU_NOMI = {ABBINA_PIU_NOMI}):")
        for p in piu[:40]:
            log(f"    · {P[p]['nome']} ({P[p]['noc']}) → {per_page[esiti[p]['page']]['nome']}")
    dv = [p for p in ab if "Disciplina vuota" in esiti[p]["motivo"]]
    if dv:
        log(f"  Abbinati con Disciplina vuota in Athletes ({len(dv)}; ABBINA_DISCIPLINA_VUOTA = "
            f"{ABBINA_DISCIPLINA_VUOTA}): " + ", ".join(f"{P[p]['nome']} ({P[p]['noc']})" for p in dv[:50]))
    noc_da_compilare = [p for p in ab if not per_page[esiti[p]["page"]]["noc"]]
    if noc_da_compilare:
        log(f"  di cui con NOC vuoto in Athletes, che il lancio vero compilerà: {len(noc_da_compilare)} → "
            + ", ".join(f"{P[p]['nome']} ({P[p]['noc']})" for p in noc_da_compilare[:20]))
    mostrato = lambda p: livello_persona(P[p]) != "nascosto"
    log(f"Da creare: {len(dc)}  (di cui con ELO mostrato nella pagina: {sum(1 for p in dc if mostrato(p))})")
    log(f"Incerti: {len(inc)}  (di cui con ELO mostrato: {sum(1 for p in inc if mostrato(p))})")
    usate = {esiti[p]["page"] for p in ab}
    log(f"Righe wrestling di Athletes senza nessun incontro nel db: {len(athletes) - len(usate)} "
        f"(restano senza ELO; tra queste ci sono anche quelle candidate degli incerti)")

    noc_ok = {codice_noc(o): o for o in opzioni["noc"] if codice_noc(o)}
    disc_ok = {}
    for o in opzioni["disc"]:
        k = chiave_disc(o)
        if k:
            disc_ok.setdefault(k, o)
    senza_noc = Counter(P[p]["noc"] for p in dc if P[p]["noc"] not in noc_ok)
    if senza_noc:
        log("Da creare con NOC vuoto (codice senza opzione in Athletes o atleta neutrale): "
            + ", ".join(f"{k} {v}" for k, v in senza_noc.most_common()))
    senza_disc = sorted({d for p in dc for d in discipline_persona(P[p])
                         if chiave_disc(d) not in disc_ok})
    if senza_disc:
        log(f"ATTENZIONE: categorie senza opzione in Disciplina (non verranno scritte): {', '.join(senza_disc)}")
    log("Da creare per NOC (primi 15): "
        + ", ".join(f"{k} {v}" for k, v in Counter(P[p]["noc"] for p in dc).most_common(15)))
    log(f"Italiani da creare: {', '.join(P[p]['nome'] for p in dc if P[p]['noc'] == 'ITA') or 'nessuno'}")
    log("\nIncerti con ELO mostrato nella pagina (i più importanti da controllare):")
    for p in [p for p in inc if mostrato(p)][:80]:
        log(f"  · {P[p]['nome']} ({P[p]['noc']}, {' / '.join(discipline_persona(P[p]))}) → {esiti[p]['motivo']}")
    log(f"Elenchi completi nei file {CSV_ABBINATI.name}, {CSV_DA_CREARE.name}, {CSV_INCERTI.name} "
        f"(Artifacts del lancio).")

    stampa_classifiche(A)
    salva_json(A, esiti, tornei, oggi, stat)
    log(f"\n{FILE_JSON.name}: {len(A)} record (lottatore × stile), {len(tornei)} tornei")

    if solo_prova:
        log("\nProva terminata: non è stato scritto nulla su Notion.")
        return 0

    # 4. scrittura su Notion (solo db Athletes; solo ELO FS/GR, ID UWW e NOC vuoti, righe nuove)
    log("\n" + "=" * 78)
    log("SCRITTURA IN ATHLETES")
    log("=" * 78)
    aggiornate = invariate = create = errori = 0
    interrotto = False
    for p in ab:
        if minuti() > TEMPO_MAX_MINUTI:
            interrotto = True
            break
        persona, riga = P[p], per_page[esiti[p]["page"]]
        nuovi = {}
        for pool, a in persona["pool"].items():
            col = COLONNA_POOL[pool]
            attuale = riga["elo_fs"] if pool == "FS" else riga["elo_gr"]
            if attuale is None or round(attuale) != round(a["elo"]):
                nuovi[col] = round(a["elo"])
        if not riga["id_uww"]:
            nuovi["ID UWW"] = persona["id"]
        if not riga["noc"] and persona["noc"] in noc_ok:      # NOC solo se vuoto
            nuovi["NOC"] = noc_ok[persona["noc"]]
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
        persona = P[p]
        try:
            page = crea_riga({"nome": persona["nome"], "id": persona["id"],
                              "elo": {COLONNA_POOL[pool]: round(a["elo"]) for pool, a in persona["pool"].items()},
                              "noc_notion": noc_ok.get(persona["noc"], ""),
                              "disc": discipline_persona(persona, disc_ok)})
            esiti[p]["page"] = page
            create += 1
            if create % 100 == 0:
                log(f"  ... create {create} righe ({minuti():.0f} minuti)")
            time.sleep(PAUSA_NOTION)
        except RuntimeError as e:
            log(f"  Errore nel creare {persona['nome']}: {e}")
            errori += 1
    salva_json(A, esiti, tornei, oggi, stat)       # di nuovo, con gli id delle righe appena create
    log(f"Righe aggiornate: {aggiornate} · invariate: {invariate} · create: {create} · errori: {errori} · "
        f"incerti non scritti: {len(inc)} · minuti: {minuti():.0f}")
    if interrotto:
        log(f"ATTENZIONE: mi sono fermato dopo {TEMPO_MAX_MINUTI:.0f} minuti. Rilancia: le righe già "
            f"scritte risultano abbinate per ID UWW e non vengono duplicate.")
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
    except Exception:              # qualsiasi errore: lo scrivo nel rapporto
        import traceback
        log(traceback.format_exc())
    finally:
        FILE_RAPPORTO.write_text("\n".join(_righe_log) + "\n", encoding="utf-8")
    sys.exit(codice)
