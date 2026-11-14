#!/usr/bin/env python3
"""Pagina Performance Wrestling: legge da Notion gli incontri del database "Agente Wrestling"
(popolato dall'agente wrestling con i risultati UWW) e scrive wrestling-performance.json,
che userà la pagina wrestling-performance.html.

Versione 2 del 14/11/2026 (scheda 24, sessione 3 dell'ELO wrestling):
  - unisce l'ELO calcolato da elo_wrestling.py (file wrestling-elo.json nella cartella del repo);
  - riconosce i turni nuovi arrivati con gli Asian Games: "Final 3-4" (finale per il bronzo)
    e i gironi a due gruppi "A | Round n" / "B | Round n";
  - legge anche "ID UWW 1" e "ID UWW 2", che servono a collegare i lottatori all'ELO.

Non crea né modifica nulla in Notion: legge soltanto.

Cosa calcola (per stile, categoria e torneo, più il totale di tutti i tornei):
  1. per ogni lottatore: incontri, vittorie, sconfitte, punti segnati, punti subiti,
     differenza punti, media punti per incontro;
  2. vittorie per schienata (VFA) e per superiorità tecnica (VSU, VSU1);
  3. vittorie senza combattere (VFO forfait, VIN infortunio, DSQ squalifica): contano come
     vittorie ma i loro punti NON entrano nelle statistiche dei punti;
  4. il campione di ogni categoria in ogni torneo (vincitore del turno "Final 1-2"),
     con argento e bronzi (vincitori di "Final 3-5" e "Final 3-4"); per le categorie a girone
     all'italiana ("Round 1, 2, 3...") il campione è chi vince più incontri del girone;
  5. gli H2H: le coppie di lottatori che si sono incontrate almeno 2 volte, con bilancio
     e punteggi di ogni incontro;
  6. l'ELO di ogni lottatore (da wrestling-elo.json): valore, livello, storico e la top 10 ELO
     di ogni categoria olimpica. Se il file manca, la pagina funziona come prima, senza ELO.

Regole importanti sui dati:
  - "Score" ha il formato "6-2 (VPO1)": il primo numero sono i punti del Player 1, il secondo
    quelli del Player 2, tra parentesi il tipo di vittoria. Può essere anche solo "(VFO)".
  - Il Player 1 NON è sempre il vincitore: il vincitore si prende SEMPRE dalla colonna "Vincitore".

Uso:
  NOTION_TOKEN=... python aggiorna_wrestling_performance.py
  NOTION_TOKEN=... python aggiorna_wrestling_performance.py --salva-raw raw_wrestling.json
        (come sopra, e in più salva le righe lette da Notion per fare prove senza Internet)
  python aggiorna_wrestling_performance.py --da-raw raw_wrestling.json
        (prova con righe salvate: non serve NOTION_TOKEN)

Non servono librerie da installare.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
FILE_JSON = "wrestling-performance.json"
FILE_ELO = "wrestling-elo.json"          # prodotto da elo_wrestling.py (workflow "ELO Wrestling")
NOTION_VERSION = "2025-09-03"
DB_WRESTLING = "40ef48c9-aad9-809e-995f-000b5420780c"   # data source "Agente Wrestling"

# Colonne del db "Agente Wrestling" lette dallo script (nomi ESATTI, verificati il 12/11/2026;
# "ID UWW 1" e "ID UWW 2" aggiunte il 13/11/2026, scheda 22 §4.1)
COLONNE = ["Incontro", "Player 1", "NOC 1", "Player 2", "NOC 2", "Gender", "Stile", "Categoria",
           "Score", "Vincitore", "Turno", "Torneo", "Data", "Fonte", "ID Univoco", "ID UWW 1", "ID UWW 2"]

STILI = ["Freestyle", "Greco-Roman", "Women's Wrestling"]   # ordine di presentazione
TOTALE = "Tutti i tornei"                                  # nome della riga "totale"

# ---------------------------------------------------------------- TIPI DI VITTORIA (UWW)
# VPO/VPO1 = ai punti · VSU/VSU1 = superiorità tecnica · VFA = schienata (fall)
# VFO = forfait · VIN = infortunio · DSQ = squalifica · VCA = 3 ammonizioni dell'avversario
SCHIENATA = {"VFA"}
SUPERIORITA = {"VSU", "VSU1"}
SENZA_COMBATTERE = {"VFO", "VIN", "DSQ"}   # vittorie "a tavolino": contano come vittorie
# Tipi i cui punti NON entrano nelle statistiche dei punti.
# [DA DECIDERE] VCA: qui i punti CONTANO (l'incontro è stato lottato). Per escluderli
# basta scrivere:  SENZA_PUNTI = SENZA_COMBATTERE | {"VCA"}
SENZA_PUNTI = set(SENZA_COMBATTERE)
TIPI_NOTI = {"VPO", "VPO1", "VSU", "VSU1", "VFA", "VFO", "VIN", "DSQ", "VCA"}

# Ordine dei turni dentro un torneo (serve solo per mettere in fila gli incontri).
# I gironi ("Round n", "A | Round n", "B | Round n") sono gestiti da ordine_turno().
ORDINE_TURNO = {"Qualif.": 0, "1/16 Final": 1, "1/8 Final": 2, "1/4 Final": 3, "1/2 Final": 4,
                "Repechage": 5, "Final 3-5": 6, "Final 3-4": 6, "Final 1-2": 7}
FINALE = "Final 1-2"
BRONZO = {"Final 3-5", "Final 3-4"}       # "Final 3-4": finale per il bronzo dei tornei a due gironi
# turni di girone: "Round 2" (girone unico all'italiana) oppure "A | Round 2" / "B | Round 2" (due gironi)
RE_GIRONE = re.compile(r"^(?:([AB]) \| )?Round (\d+)$")

# ELO (scheda 22 §5.8): stili e "pool" dell'ELO; FS = libera maschile e femminile, GR = greco-romana
POOL_DI_STILE = {"Freestyle": "FS", "Women's Wrestling": "FS", "Greco-Roman": "GR"}


# ---------------------------------------------------------------- NOTION
def chiama(percorso, corpo):
    """Manda una richiesta all'API di Notion e restituisce la risposta (dizionario)."""
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("Manca NOTION_TOKEN.")
    richiesta = urllib.request.Request(
        f"https://api.notion.com/v1/{percorso}", data=json.dumps(corpo).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    for tentativo in range(5):
        try:
            with urllib.request.urlopen(richiesta, timeout=90) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as errore:
            testo_err = errore.read().decode(errors="replace")
            # troppe richieste o errore temporaneo di Notion: aspetta e riprova
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 4:
                time.sleep(2 ** tentativo)
                continue
            if errore.code == 404:
                sys.exit('Notion non trova il database "Agente Wrestling": aprilo in Notion, '
                         '••• > Connessioni, aggiungi la stessa connessione della mappa.')
            sys.exit(f"Errore Notion {errore.code}: {testo_err}")
        except urllib.error.URLError as errore:
            if tentativo < 4:
                time.sleep(2 ** tentativo)
                continue
            sys.exit(f"Notion non raggiungibile: {errore}")


def valore(p):
    """Trasforma una proprietà Notion in un valore semplice (testo, numero, data...)."""
    if not p:
        return None
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in p[t])
    if t == "select":
        return (p["select"] or {}).get("name")
    if t == "date":
        return (p["date"] or {}).get("start")
    if t == "url":
        return p["url"]
    if t == "number":
        return p["number"]
    return None


def leggi_notion():
    """Legge TUTTE le righe del db "Agente Wrestling" (100 alla volta)."""
    righe, cursore = [], None
    while True:
        corpo = {"page_size": 100}
        if cursore:
            corpo["start_cursor"] = cursore
        r = chiama(f"data_sources/{DB_WRESTLING}/query", corpo)
        for pg in r["results"]:
            p = pg["properties"]
            righe.append({c: valore(p.get(c)) for c in COLONNE})
        if not r.get("has_more"):
            break
        cursore = r["next_cursor"]
    print(f"Agente Wrestling: {len(righe)} incontri letti da Notion")
    return righe


# ---------------------------------------------------------------- LETTURA DEGLI INCONTRI
def pulisci(testo):
    """Toglie gli spazi doppi e quelli all'inizio e alla fine."""
    return re.sub(r"\s+", " ", testo or "").strip()


RE_SCORE = re.compile(r"^(?:(\d+)\s*-\s*(\d+))?\s*(?:\(\s*([^)]*?)\s*\))?$")


def leggi_score(score):
    """'6-2 (VPO1)' -> (6, 2, 'VPO1', True); '(VFO)' -> (None, None, 'VFO', True).
    L'ultimo valore è False se il testo non ha il formato atteso."""
    m = RE_SCORE.match(pulisci(score))
    if not m or not (m.group(1) or m.group(3)):
        return None, None, "", False
    p1 = int(m.group(1)) if m.group(1) else None
    p2 = int(m.group(2)) if m.group(2) else None
    return p1, p2, (m.group(3) or "").upper(), True


def ordine_turno(turno):
    """Posizione del turno nel torneo: i gironi prima di tutto il resto (Round 1 = 0,01 ... Round 5 = 0,05)."""
    if turno in ORDINE_TURNO:
        return ORDINE_TURNO[turno]
    m = RE_GIRONE.match(turno or "")
    return int(m.group(2)) / 100 if m else 9


def kg(categoria):
    """'125 kg' -> 125 (per ordinare le categorie)."""
    m = re.match(r"\d+", categoria or "")
    return int(m.group()) if m else 999


def prepara(righe, avvisi):
    """Controlla ogni riga e la trasforma in un "incontro" con il vincitore già individuato."""
    incontri = []
    tipi_parziali = {}            # VIN/DSQ con un punteggio: punti parziali esclusi
    for r in righe:
        p1, p2, vinc = pulisci(r.get("Player 1")), pulisci(r.get("Player 2")), pulisci(r.get("Vincitore"))
        etichetta = f"{p1} vs {p2} ({pulisci(r.get('Torneo'))}, {r.get('Stile')} {r.get('Categoria')})"
        if not p1 or not p2:
            avvisi.append(f"Riga senza uno dei due lottatori, ignorata: {r.get('Incontro')}")
            continue
        # il vincitore si prende SEMPRE dalla colonna Vincitore (il Player 1 non è sempre chi vince)
        if vinc == p1:
            chi_vince = 1
        elif vinc == p2:
            chi_vince = 2
        else:
            avvisi.append(f"Vincitore «{vinc}» diverso da entrambi i lottatori, riga ignorata: {etichetta}")
            continue
        s1, s2, tipo, ok = leggi_score(r.get("Score"))
        if not ok:
            avvisi.append(f"Score non riconosciuto «{r.get('Score')}»: vittoria contata, punti no: {etichetta}")
        elif tipo and tipo not in TIPI_NOTI:
            avvisi.append(f"Tipo di vittoria sconosciuto «{tipo}»: trattato come vittoria ai punti: {etichetta}")
        con_punti = s1 is not None and tipo not in SENZA_PUNTI
        if s1 is not None and tipo in SENZA_PUNTI:
            tipi_parziali[tipo] = tipi_parziali.get(tipo, 0) + 1
        # controllo di coerenza: ai punti o per superiorità il vincitore deve avere almeno i punti dell'altro
        if con_punti and tipo in {"VPO", "VPO1", "VSU", "VSU1"}:
            pv, pp = (s1, s2) if chi_vince == 1 else (s2, s1)
            if pv < pp:
                avvisi.append(f"Il vincitore ha meno punti ({r.get('Score')}) in una vittoria {tipo}: {etichetta}")
        incontri.append({
            "torneo": pulisci(r.get("Torneo")) or "?", "stile": r.get("Stile") or "?",
            "cat": pulisci(r.get("Categoria")) or "?", "turno": pulisci(r.get("Turno")),
            "data": (r.get("Data") or "")[:10],
            "p": [p1, p2], "noc": [pulisci(r.get("NOC 1")), pulisci(r.get("NOC 2"))],
            "id": [pulisci(r.get("ID UWW 1")), pulisci(r.get("ID UWW 2"))],     # per collegare l'ELO
            "punti": [s1, s2], "tipo": tipo, "w": chi_vince, "con_punti": con_punti})
    for tipo, n in sorted(tipi_parziali.items()):
        print(f"NOTA {n} incontri {tipo} hanno un punteggio parziale: i punti sono esclusi dalle statistiche")
    # ordine cronologico: data, poi turno
    incontri.sort(key=lambda b: (b["data"], b["torneo"], b["stile"], kg(b["cat"]),
                                 ordine_turno(b["turno"])))
    return incontri


# ---------------------------------------------------------------- STATISTICHE
def nuova_scheda(stile, cat, torneo, nome):
    return {"stile": stile, "cat": cat, "torneo": torneo, "nome": nome, "noc": "",
            "inc": 0, "v": 0, "s": 0,                 # incontri, vittorie, sconfitte
            "inc_punti": 0, "ps": 0, "pp": 0,         # incontri con punti validi, punti segnati e subiti
            "vfa": 0, "vsu": 0,                       # vittorie per schienata e per superiorità tecnica
            "v_sc": 0, "s_sc": 0,                     # vittorie e sconfitte senza combattere (VFO/VIN/DSQ)
            "tipi": {}}                               # vittorie per tipo, es. {"VPO1": 3, "VSU": 2}


def aggiungi(schede, chiave, inc, lato):
    """Aggiunge l'incontro alla scheda del lottatore 'lato' (0 = Player 1, 1 = Player 2)."""
    nome = inc["p"][lato]
    sc = schede.setdefault(chiave + (nome,), nuova_scheda(*chiave, nome))
    sc["noc"] = inc["noc"][lato] or sc["noc"]          # gli incontri sono in ordine: resta il NOC più recente
    sc["inc"] += 1
    vince = inc["w"] == lato + 1
    tipo = inc["tipo"]
    if vince:
        sc["v"] += 1
        sc["tipi"][tipo or "?"] = sc["tipi"].get(tipo or "?", 0) + 1
        sc["vfa"] += tipo in SCHIENATA
        sc["vsu"] += tipo in SUPERIORITA
        sc["v_sc"] += tipo in SENZA_COMBATTERE
    else:
        sc["s"] += 1
        sc["s_sc"] += tipo in SENZA_COMBATTERE
    if inc["con_punti"]:
        sc["inc_punti"] += 1
        sc["ps"] += inc["punti"][lato]
        sc["pp"] += inc["punti"][1 - lato]


def calcola_statistiche(incontri):
    schede = {}
    for inc in incontri:
        for torneo in (inc["torneo"], TOTALE):          # ogni incontro vale per il torneo e per il totale
            for lato in (0, 1):
                aggiungi(schede, (inc["stile"], inc["cat"], torneo), inc, lato)
    for sc in schede.values():
        sc["dp"] = sc["ps"] - sc["pp"]
        sc["media"] = round(sc["ps"] / sc["inc_punti"], 2) if sc["inc_punti"] else None
    return schede


# ---------------------------------------------------------------- CAMPIONI E MEDAGLIE
def classifica_girone(bouts):
    """Girone all'italiana (turni "Round 1, 2, 3..." o "A | Round 1..."): ordina per vittorie;
    a parità tra DUE lottatori decide lo scontro diretto, altrimenti la differenza punti.
    [DA VERIFICARE] è una semplificazione dei criteri UWW (che usano anche i punti di classifica)."""
    vitt, dp, nomi, noc = {}, {}, [], {}
    for b in bouts:
        for lato in (0, 1):
            n = b["p"][lato]
            if n not in nomi:
                nomi.append(n)
            noc[n] = b["noc"][lato]
            vitt[n] = vitt.get(n, 0) + (b["w"] == lato + 1)
            if b["con_punti"]:
                dp[n] = dp.get(n, 0) + b["punti"][lato] - b["punti"][1 - lato]
    ordine = sorted(nomi, key=lambda n: (-vitt[n], -dp.get(n, 0), n))
    for i in range(len(ordine) - 1):
        a, b = ordine[i], ordine[i + 1]
        pari = [n for n in ordine if vitt[n] == vitt[a]]
        if len(pari) == 2 and vitt[b] == vitt[a]:
            diretto = next((x for x in bouts if set(x["p"]) == {a, b}), None)
            if diretto and diretto["p"][diretto["w"] - 1] == b:
                ordine[i], ordine[i + 1] = b, a
    return ordine, noc


def punteggio_per(inc, nome):
    """Punteggio visto da 'nome': '7-4 (VPO1)' con i suoi punti per primi; '(VIN)' se senza punti."""
    lato = inc["p"].index(nome)
    tipo = f" ({inc['tipo']})" if inc["tipo"] else ""
    if inc["punti"][0] is None:
        return tipo.strip()
    return f"{inc['punti'][lato]}-{inc['punti'][1 - lato]}{tipo}"


def calcola_medaglie(incontri, avvisi):
    """Per ogni torneo, stile e categoria: oro, argento e bronzi."""
    gruppi = {}
    for inc in incontri:
        gruppi.setdefault((inc["torneo"], inc["stile"], inc["cat"]), []).append(inc)
    medaglie, campioni = {}, []
    for (torneo, stile, cat), bouts in gruppi.items():
        finali = [b for b in bouts if b["turno"] == FINALE]
        girone = [b for b in bouts if RE_GIRONE.match(b["turno"])]
        if finali:
            if len(finali) > 1:
                avvisi.append(f"{len(finali)} finali 1-2 in {torneo} {stile} {cat}: uso l'ultima")
            f = finali[-1]
            oro, argento = f["p"][f["w"] - 1], f["p"][2 - f["w"]]
            # bronzi: vincitori di "Final 3-5" (due bronzi) o di "Final 3-4" (tornei a due gironi: un bronzo)
            bronzi = [b["p"][b["w"] - 1] for b in bouts if b["turno"] in BRONZO]
            finale, nel_girone = f, False
        elif girone:
            gruppi_girone = {RE_GIRONE.match(b["turno"]).group(1) for b in girone}
            if len(gruppi_girone) > 1:
                avvisi.append(f"Due gironi senza finale in {torneo} {stile} {cat}: classifica unica dei due gironi "
                              f"[DA VERIFICARE]")
            ordine, _ = classifica_girone(girone)
            oro, argento, bronzi = ordine[0], ordine[1] if len(ordine) > 1 else None, ordine[2:3]
            # l'incontro "decisivo" mostrato per il campione: quello tra oro e argento
            finale = next((b for b in girone if set(b["p"]) == {oro, argento}), None)
            nel_girone = True
            avvisi.append(f"Girone all'italiana in {torneo} {stile} {cat}: campione {oro} "
                          f"(calcolato dalle vittorie nel girone) [DA VERIFICARE]")
        else:
            avvisi.append(f"Nessuna finale in {torneo} {stile} {cat}: campione non determinato "
                          f"(torneo non ancora concluso o dati incompleti)")
            continue
        medaglie[(torneo, stile, cat, oro)] = "oro"
        if argento:
            medaglie[(torneo, stile, cat, argento)] = "argento"
        for n in bronzi:
            medaglie[(torneo, stile, cat, n)] = "bronzo"
        voce = {"torneo": torneo, "stile": stile, "cat": cat, "nome": oro, "girone": nel_girone,
                "argento": argento, "bronzi": bronzi}
        if finale:
            lato = finale["p"].index(oro)
            voce.update({"noc": finale["noc"][lato], "avversario": finale["p"][1 - lato],
                         "noc_avv": finale["noc"][1 - lato], "score": punteggio_per(finale, oro),
                         "tipo": finale["tipo"], "data": finale["data"]})
        campioni.append(voce)
    return medaglie, campioni


# ---------------------------------------------------------------- H2H
def calcola_h2h(incontri):
    """Coppie di lottatori che si sono incontrate almeno 2 volte (in qualsiasi torneo)."""
    coppie = {}
    for inc in incontri:
        coppie.setdefault(tuple(sorted(inc["p"])), []).append(inc)
    risultato = []
    for (x, y), bouts in coppie.items():
        if len(bouts) < 2:
            continue
        vitt = {x: 0, y: 0}
        noc = {}
        for b in bouts:
            vitt[b["p"][b["w"] - 1]] += 1
            noc.update(zip(b["p"], b["noc"]))          # resta il NOC più recente
        # "a" è chi è avanti nel bilancio (a parità, ordine alfabetico)
        a, b_ = sorted((x, y), key=lambda n: (-vitt[n], n))
        risultato.append({
            "a": a, "noc_a": noc[a], "b": b_, "noc_b": noc[b_], "v_a": vitt[a], "v_b": vitt[b_],
            "incontri": [{"torneo": i["torneo"], "data": i["data"], "turno": i["turno"],
                          "stile": i["stile"], "cat": i["cat"], "vincitore": i["p"][i["w"] - 1],
                          "score": punteggio_per(i, a)}           # punteggio visto da "a"
                         for i in bouts]})
    risultato.sort(key=lambda h: (-len(h["incontri"]), h["a"]))
    return risultato


# ---------------------------------------------------------------- ELO (da wrestling-elo.json)
def unisci_elo(incontri, avvisi):
    """Legge wrestling-elo.json e prepara i dati ELO per la pagina.

    Collega ogni lottatore della pagina (stile + nome, come nelle statistiche) al suo record ELO
    attraverso l'ID UWW: per ogni nome si usa l'ID dell'incontro più recente.
    Restituisce None se il file manca o non si legge (la pagina funziona come prima, senza ELO).
    """
    percorso = CARTELLA / FILE_ELO
    try:
        elo = json.loads(percorso.read_text(encoding="utf-8"))
        record = elo["atleti"]
    except FileNotFoundError:
        avvisi.append(f"{FILE_ELO} non trovato: la pagina resta senza ELO (lancia il workflow \"ELO Wrestling\")")
        return None
    except (ValueError, KeyError) as errore:
        avvisi.append(f"{FILE_ELO} non leggibile ({errore}): la pagina resta senza ELO")
        return None
    per_id = {(r["pool"], str(r["id_uww"])): r for r in record}

    # nome usato nella pagina -> ID UWW (gli incontri sono in ordine di data: resta il più recente)
    id_di = {}
    for inc in incontri:
        for lato in (0, 1):
            if inc["id"][lato]:
                id_di[(inc["stile"], inc["p"][lato])] = inc["id"][lato]

    def compatto(r):
        """Dati ELO di un lottatore come li usa la pagina. Valore e storico solo se l'ELO è mostrato."""
        e = {"liv": r["livello"], "n": r["incontri"], "t": r["tornei"], "cat": r["cat"]}
        if r["livello"] != "nascosto":
            e.update({"v": r["elo"], "max": r["elo_max"], "vit": r["vittorie"], "ult": r["ultimo"],
                      "st": r["storico"]})
        return e

    atleti, senza = {}, 0
    for (stile, nome), pid in id_di.items():
        r = per_id.get((POOL_DI_STILE.get(stile), pid))
        if r:
            atleti[f"{stile}|{nome}"] = compatto(r)
        else:
            senza += 1
    # top 10 ELO di ogni categoria (categoria di riferimento del lottatore, scheda 22 §5.10)
    top = {}
    for r in sorted(record, key=lambda r: -r["elo"]):
        if r["livello"] == "nascosto":
            continue
        lista = top.setdefault(f"{r['stile']}|{r['cat']}", [])
        if len(lista) < 10:
            lista.append({"nome": r["nome"], "noc": r["noc"], "v": r["elo"], "max": r["elo_max"],
                          "liv": r["livello"], "n": r["incontri"], "t": r["tornei"]})
    if senza:
        avvisi.append(f"{senza} lottatori della pagina senza record ELO (manca l'ID UWW o non sono nel calcolo)")
    mostrati = sum(1 for r in record if r["livello"] != "nascosto")
    print(f"ELO: {len(record)} record in {FILE_ELO} (aggiornato al {elo.get('aggiornato')}), {mostrati} mostrati; "
          f"collegati alla pagina {len(atleti)} lottatori")
    tornei = {slug: t.get("nome", slug) for slug, t in (elo.get("tornei") or {}).items()}
    return {"aggiornato": elo.get("aggiornato"), "n": len(record), "mostrati": mostrati,
            "regole": elo.get("regole", {}), "tornei": tornei, "atleti": atleti, "top": top}


# ---------------------------------------------------------------- MESSA INSIEME
def aggrega(righe, oggi):
    avvisi = []
    incontri = prepara(righe, avvisi)
    schede = calcola_statistiche(incontri)
    medaglie, campioni = calcola_medaglie(incontri, avvisi)

    # tornei in ordine di data, con il primo e l'ultimo giorno di gara
    tornei = {}
    for inc in incontri:
        t = tornei.setdefault(inc["torneo"], {"nome": inc["torneo"], "dal": inc["data"], "al": inc["data"], "incontri": 0})
        t["incontri"] += 1
        if inc["data"]:
            t["dal"] = min(t["dal"] or inc["data"], inc["data"])
            t["al"] = max(t["al"] or inc["data"], inc["data"])
    lista_tornei = sorted(tornei.values(), key=lambda t: (t["dal"] or "", t["nome"]))
    pos_torneo = {t["nome"]: i for i, t in enumerate(lista_tornei)}
    pos_torneo[TOTALE] = len(lista_tornei)

    # stesso lottatore in due categorie dello stesso torneo e stile: probabile errore nei dati
    visti = {}
    for (stile, cat, torneo, nome) in schede:
        if torneo != TOTALE:
            visti.setdefault((stile, torneo, nome), []).append(cat)
    for (stile, torneo, nome), cats in visti.items():
        if len(cats) > 1:
            avvisi.append(f"{nome} compare in più categorie ({', '.join(cats)}) di {torneo} {stile} [DA VERIFICARE]")

    statistiche = []
    for (stile, cat, torneo, nome), sc in schede.items():
        if torneo == TOTALE:
            # nel totale: quanti tornei, titoli e medaglie
            mie = [medaglie.get((t, stile, cat, nome)) for t in tornei]
            sc["tornei"] = sum(1 for t in tornei if (stile, cat, t, nome) in schede)
            sc["titoli"] = mie.count("oro")
            sc["medaglie"] = [mie.count("oro"), mie.count("argento"), mie.count("bronzo")]
        else:
            sc["medaglia"] = medaglie.get((torneo, stile, cat, nome))
            sc["campione"] = sc["medaglia"] == "oro"
        statistiche.append(sc)
    ordine_stile = {s: i for i, s in enumerate(STILI)}
    statistiche.sort(key=lambda s: (ordine_stile.get(s["stile"], 9), kg(s["cat"]), pos_torneo[s["torneo"]],
                                    -s["v"], -s["dp"], s["nome"]))
    campioni.sort(key=lambda c: (pos_torneo[c["torneo"]], ordine_stile.get(c["stile"], 9), kg(c["cat"])))

    categorie = {}
    for inc in incontri:
        categorie.setdefault(inc["stile"], set()).add(inc["cat"])
    h2h = calcola_h2h(incontri)
    elo = unisci_elo(incontri, avvisi)

    # elenco compatto di tutti gli incontri, utile alla pagina per le schede dei lottatori:
    # [n° torneo, stile, categoria, turno, data, Player 1, NOC 1, Player 2, NOC 2, punti 1, punti 2, tipo, vincitore (1 o 2)]
    elenco = [[pos_torneo[i["torneo"]], i["stile"], i["cat"], i["turno"], i["data"], i["p"][0], i["noc"][0],
               i["p"][1], i["noc"][1], i["punti"][0], i["punti"][1], i["tipo"], i["w"]] for i in incontri]

    for a in avvisi:
        print("AVVISO", a)
    return {"aggiornato": oggi.isoformat(), "totale": TOTALE,
            "tornei": lista_tornei,
            "stili": [s for s in STILI if s in categorie] + sorted(s for s in categorie if s not in STILI),
            "categorie": {s: sorted(c, key=kg) for s, c in categorie.items()},
            "n_incontri": len(incontri),
            "n_lottatori": len({n for i in incontri for n in i["p"]}),
            "statistiche": statistiche, "campioni": campioni, "h2h": h2h,
            "incontri": elenco, "elo": elo, "avvisi": avvisi}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file JSON con le righe già salvate (prova senza Notion)")
    ap.add_argument("--salva-raw", help="salva in questo file le righe lette da Notion")
    args = ap.parse_args()
    if args.da_raw:
        righe = json.load(open(args.da_raw, encoding="utf-8"))
        print(f"Righe lette da {args.da_raw}: {len(righe)}")
    else:
        righe = leggi_notion()
        if args.salva_raw:
            Path(args.salva_raw).write_text(json.dumps(righe, ensure_ascii=False), encoding="utf-8")
    if not righe:
        sys.exit("Nessun incontro nel database: niente da calcolare.")
    oggi = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date()
    dati = aggrega(righe, oggi)
    (CARTELLA / FILE_JSON).write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{FILE_JSON}: {dati['n_incontri']} incontri, {dati['n_lottatori']} lottatori, "
          f"{len(dati['tornei'])} tornei, {len(dati['campioni'])} campioni, {len(dati['h2h'])} coppie H2H")
    for c in dati["campioni"][:3]:
        print(f"  es. campione {c['torneo']} · {c['stile']} {c['cat']}: {c['nome']} ({c.get('noc', '')}) "
              f"{c.get('score', '')} su {c.get('avversario', '')}")


if __name__ == "__main__":
    main()