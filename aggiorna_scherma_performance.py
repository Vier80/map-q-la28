#!/usr/bin/env python3
"""Pagina Performance Scherma: legge da Notion i risultati INDIVIDUALI di scherma dei db
"Risultati A" (MASTER RESULTS) e "Risultati B" (MASTER MINOR) e gli schermidori del db
Athletes, ricalcola l'indice FEN con le formule di Notion e scrive scherma-performance.json,
usato dalla pagina scherma-performance.html.

Perché ricalcolare: l'API di Notion non restituisce il valore delle formule (FEN🔺 nel db A,
FEN 🔺 nel db B, FEN 🔸 in Athletes), quindi lo script rifà lo stesso conto partendo da
Result, Anno, Evento e 🏟️ Rating. Se cambi la formula FEN in Notion, cambia anche la
sezione FORMULA FEN qui sotto.
Nota: il FEN 🔸 di Athletes somma TUTTE le righe collegate; lo script tiene solo le gare
individuali senior, con un torneo e senza w/o (per la scherma oggi coincidono).

NOVITÀ del 16/11/2026 (scheda 26, sessione 3): ELO
Se nella cartella c'è scherma-elo.json (lo salva il workflow "ELO Scherma" ogni lunedì), lo
script aggiunge a scherma-performance.json l'ELO di ogni schermidore. Il collegamento passa dal
campo "notion" di scherma-elo.json, che è l'id della riga di Athletes, cioè lo stesso "id" usato
qui, e dall'arma (un ELO per ogni arma). Se scherma-elo.json manca o non si legge, la pagina
funziona lo stesso, senza ELO.

Le 6 gare: spada, fioretto e sciabola individuali, uomini e donne.
Le prove a squadre NON sono considerate.

La lettura da Notion (funzioni interroga e valore, codici dei database) è presa da
aggiorna_judo_performance.py, che deve stare nella stessa cartella. La formula invece è
propria della scherma ed è scritta qui.

Uso:
  NOTION_TOKEN=... python aggiorna_scherma_performance.py
  python aggiorna_scherma_performance.py --da-raw raw.json    prova con dati salvati

Non servono librerie da installare.
"""
import argparse
import datetime
import json
import re
import statistics
import sys
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARTELLA))      # trova aggiorna_judo_performance.py nella stessa cartella
from aggiorna_judo_performance import (DB_ATHLETES, DB_RISULTATI, NON_PRESENTATI,  # noqa: E402
                                       interroga, valore)

# Le armi: nome inglese usato in Notion -> nome italiano mostrato nella pagina
ARMI = {"Epee": "Spada", "Foil": "Fioretto", "Sabre": "Sciabola"}

# Le 6 discipline individuali, scritte esattamente come nel campo Disciplina dei db Risultati
# (verificato in Notion l'11/11/2026), es. "Men's Individual Epee", "Women's Individual Sabre"
DISCIPLINE_SCHERMA = [f"{g}'s Individual {a}" for g in ("Men", "Women") for a in ARMI]

# Riconosce genere e arma da un nome di disciplina. Accetta anche il refuso presente
# in Athletes "Women' Individual Epee" (manca la s dopo l'apostrofo).
RE_DISCIPLINA = re.compile(r"^(Men|Women)'?s? Individual (Epee|Foil|Sabre)$")

# ---------------------------------------------------------------- ELO (novità sessione 3)
FILE_ELO = CARTELLA / "scherma-elo.json"   # prodotto da elo_scherma.py nello stesso repository
TOP_ELO = 10                               # quanti schermidori nella "Classifica ELO · top 10" di ogni gara


# ================================================================ FORMULA FEN
# Copia in Python delle formule di Notion (testo inviato da Gualtiero l'11/11/2026):
#   - FEN🔺  nel db Risultati A (MASTER RESULTS)
#   - FEN 🔺 nel db Risultati B (MASTER MINOR)
#   - FEN 🔸 in Athletes = MASTER RESULTS.map(current.FEN🔺).sum()
#                          + MASTER MINOR.map(current.FEN 🔺).sum()
# Le due formule di riga sono identiche tranne le parole chiave del prestigio: solo il db A
# riconosce anche "PanAm" (senza trattino). Non c'è un fattore 0,55 per il db B (diverso dal WON).
# Se cambi una formula in Notion, cambia anche questa sezione.
FORMULA_PROVVISORIA = False

# 1. Traduzione delle sigle dei tabelloni. SF = semifinale persa = bronzo; QF = quarti (5°-8°).
#    R256 NON è nell'elenco della formula: come in Notion, diventa "non numero" e vale 0,005.
TRAD = {"SF": "3", "QF": "5", "R16": "9", "R32": "17", "R64": "33", "R128": "65"}

# 4. Parole chiave del prestigio continentale (1,25), diverse tra db A e db B
KEYWORDS = {"A": ["EUR", "🇪🇺", "Asian", "AFR", "African", "AME", "Pan-Am", "PanAm", "Oce"],
            "B": ["EUR", "🇪🇺", "Asian", "AFR", "African", "AME", "Pan-Am", "Oce"]}
# parole che danno il prestigio mondiale (1,5)
MONDIALE = ["🌐", "Mondiale", "World"]


def piazzamento(result):
    """2. Trasforma il testo di Result (1, 2, SF, QF, R16…) in un numero; None se non è un numero
    (come toNumber() vuoto in Notion, es. R256 o w/o)."""
    t = (result or "").strip()
    t = TRAD.get(t, t)
    try:
        return float(t)
    except ValueError:
        return None


def peso_risultato(p):
    """3. Curva della scherma ("più dolce per attutire la varianza")."""
    if p is None:
        return 0.005          # [DA VERIFICARE] in Notion un numero vuoto non soddisfa i confronti
    if p == 1:
        return 0.18           # 1° posto
    if p == 2:
        return 0.14           # 2° posto
    if p == 3:
        return 0.11           # 3° posto / SF
    if p <= 8:
        return 0.08           # quarti di finale (dal 4° all'8°)
    if p <= 16:
        return 0.045          # ottavi (R16)
    if p <= 32:
        return 0.02           # sedicesimi (R32)
    if p <= 64:
        return 0.01           # trentaduesimi (R64)
    return 0.005              # oltre il 64° (es. R128): partecipazione minima


def peso_prestigio(evento, db):
    """4. Prestigio: 1,5 mondiale, 1,25 continentale, 1,0 il resto (vale per A e B)."""
    ev = evento or ""
    if any(k in ev for k in MONDIALE):
        return 1.5
    if any(k in ev for k in KEYWORDS[db]):
        return 1.25
    return 1.0


def peso_anno(anno):
    """5. Decadimento temporale."""
    return {2025: 0.4, 2026: 0.6, 2027: 0.8, 2028: 1.0}.get(int(anno) if anno else 0, 0.2)


def fen(r):
    """6. Punti FEN di un singolo risultato, arrotondati a 2 decimali come in Notion."""
    rating = r["rating"] or 0                       # Rating vuoto = 0 punti
    p = piazzamento(r["result"])
    c = rating * peso_risultato(p) * peso_prestigio(r["ev"], r["db"]) * 1.0 * peso_anno(r["anno"])
    return round(c * 100) / 100


# ================================================================ NOTION
def solo_squadre(discipline):
    """True se tutte le discipline della pagina Athletes sono a squadre (es. 'Men's Team Foil')."""
    return bool(discipline) and all("Team" in d for d in discipline)


def leggi_notion():
    # 1) gli schermidori del db Athletes (Sport = Fencing); le pagine delle squadre
    #    (es. "ITA Men's Team Foil") vengono scartate più avanti, in aggrega()
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": "Fencing"}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} pagine di scherma (individuali e squadre)")

    # 2) i risultati delle 6 discipline individuali nei db A e B
    filtro = {"or": [{"property": "Disciplina", "select": {"equals": d}} for d in DISCIPLINE_SCHERMA]}
    res = []
    for sigla, db in DB_RISULTATI.items():
        pagine = interroga(db, filtro)
        for pg in pagine:
            p = pg["properties"]
            res.append({"db": sigla, "ids": valore(p.get("Athlete")) or [], "ev": valore(p.get("Evento")) or "",
                        "anno": valore(p.get("Anno")), "mese": valore(p.get("Mese")),
                        "result": valore(p.get("Result")) or "", "rating": valore(p.get("🏟️ Rating")),
                        "disc": valore(p.get("Disciplina")) or "", "cat": valore(p.get("CAT")) or ""})
        print(f"Risultati {sigla}: {len(pagine)} righe nelle gare individuali di scherma")
    return ath, res


# ================================================================ AGGREGAZIONE
def genere_arma(disc):
    """Da 'Women's Individual Sabre' a ('D', 'Sciabola'); (None, None) se non è scherma individuale."""
    m = RE_DISCIPLINA.match((disc or "").strip())
    if not m:
        return None, None
    return ("U" if m.group(1) == "Men" else "D"), ARMI[m.group(2)]


def aggrega(ath, res, oggi):
    # raggruppa i risultati validi per atleta
    gruppi = {}
    for r in res:
        if r["cat"] == "Youth":           # la pagina è solo senior
            continue
        if not r["ev"]:                   # righe senza torneo: non sono gare
            continue
        if (r["result"] or "").strip().lower() in NON_PRESENTATI:   # non ha tirato: non conta
            continue
        for i in r["ids"]:
            # tiene solo gli schermidori del db Athletes, escluse le pagine delle squadre
            if i in ath and not solo_squadre(ath[i]["disc"]):
                gruppi.setdefault(i, []).append(r)

    atleti, senza_rating = [], {}
    for i, righe in gruppi.items():
        info = ath[i]
        righe.sort(key=lambda r: (r["anno"] or 0, r["mese"] or 0))      # ordine cronologico
        g, arma = genere_arma(righe[-1]["disc"])                         # gara dell'ultimo risultato
        if not arma:
            g, arma = next((genere_arma(d) for d in info["disc"] if genere_arma(d)[1]), (None, None))
        if not arma:
            continue
        for r in righe:
            if not r["rating"]:
                senza_rating[r["ev"]] = senza_rating.get(r["ev"], 0) + 1
        punti = [fen(r) for r in righe]
        pl = [piazzamento(r["result"]) for r in righe]
        rat = [r["rating"] for r in righe if r["rating"]]
        eta = None
        if info["dob"]:
            d = datetime.date.fromisoformat(info["dob"][:10])
            eta = oggi.year - d.year - ((oggi.month, oggi.day) < (d.month, d.day))
        m = re.match(r"^(\W*?)([A-Z]{3})$", (info["noc"] or "").strip())   # "🇮🇹ITA" -> "🇮🇹", "ITA"
        atleti.append({
            "id": i, "nome": re.sub(r"\s+", " ", info["nome"]).strip(),
            "flag": m.group(1) if m else "", "noc": m.group(2) if m else (info["noc"] or "—"),
            "genere": g, "arma": arma,
            "fen": round(sum(punti), 2), "gare": len(righe),
            "ori": pl.count(1), "arg": pl.count(2), "bro": pl.count(3),   # bronzo = semifinale persa
            "field": round(statistics.mean(rat)) if rat else None,
            "piazz": round(statistics.mean([p for p in pl if p]), 1) if any(pl) else None,
            "q": info["pas"] == "Q", "hon": info["hon"], "eta": eta,
            "storia": [[r["ev"], int(r["anno"] or 0), (r["result"] or "").strip(),
                        int(r["rating"]) if r["rating"] else None, w] for r, w in zip(righe, punti)]})
    atleti.sort(key=lambda a: -a["fen"])
    for ev, n in sorted(senza_rating.items()):
        print(f"AVVISO {n} risultati di «{ev}» senza 🏟️ Rating: valgono 0 punti FEN")
    eventi = sorted({r["ev"] for a in atleti for r in gruppi[a["id"]] if r["ev"]})
    return {"aggiornato": oggi.isoformat(), "formula_provvisoria": FORMULA_PROVVISORIA,
            "atleti": atleti, "eventi": eventi, "n_risultati": sum(a["gare"] for a in atleti)}


# ================================================================ ELO (novità sessione 3)
def dati_elo_atleta(e):
    """Dati ELO di uno schermidore per la pagina, nel formato compatto di scherma-performance.json.

    liv = livello ("stabile", "provvisorio", "nascosto"); n = incontri; t = gare.
    Solo se il livello non è "nascosto": v = ELO, max = ELO massimo, vit = vittorie,
    ult = data dell'ultimo incontro, st = storico [[data, ELO dopo la gara, id gara], ...].
    """
    out = {"liv": e.get("livello"), "n": e.get("incontri", 0), "t": e.get("gare", 0)}
    if e.get("livello") in ("stabile", "provvisorio"):
        out.update(v=e.get("elo"), max=e.get("elo_max"), vit=e.get("vittorie"), ult=e.get("ultimo"),
                   st=e.get("storico") or [])
    return out


def bandiera_e_noc(noc_notion):
    """'🇮🇹ITA' (valore di Athletes) -> ('🇮🇹', 'ITA'). Se il formato non torna: ('', valore così com'è)."""
    m = re.match(r"^(\W*?)([A-Z]{3})$", (noc_notion or "").strip())
    return (m.group(1), m.group(2)) if m else ("", noc_notion or "—")


def aggiungi_elo(dati, ath):
    """Aggiunge a scherma-performance.json l'ELO di scherma-elo.json (scheda 26).

    - a ogni schermidore della classifica FEN collegato all'ELO aggiunge il campo "elo",
      scegliendo l'ELO della STESSA arma della classifica FEN; se in quell'arma non ha incontri,
      usa l'ELO dell'arma principale (quella con più incontri);
    - in dati["elo"] mette la data dell'ELO, i nomi delle gare dello storico e la top 10 ELO
      di ognuna delle 6 gare (anche schermidori senza punti FEN), per il pannello "Classifica ELO".
      Nella top 10 entra solo l'arma principale di ogni schermidore (regola della scheda 26:
      uno schermidore compare nell'arma in cui ha più incontri).
    """
    if not FILE_ELO.exists():
        print("AVVISO scherma-elo.json non trovato: la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return
    try:
        raw = json.loads(FILE_ELO.read_text(encoding="utf-8"))
        elenco = raw["atleti"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"AVVISO scherma-elo.json non leggibile ({e}): la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return

    # 1. collegamento con la classifica FEN: "notion" (ELO) = "id" (FEN) = id della riga di Athletes.
    #    Uno schermidore può avere più ELO (uno per arma): li raccolgo per (id Athletes, arma).
    per_arma, principale = {}, {}
    for e in elenco:
        if not e.get("notion"):
            continue
        per_arma[(e["notion"], e.get("arma"))] = e
        if e.get("principale"):
            principale[e["notion"]] = e
    gare_usate, collegati, mostrati = set(), 0, 0
    for a in dati["atleti"]:
        e = per_arma.get((a["id"], a["arma"])) or principale.get(a["id"])
        if not e:
            continue                      # nessun incontro nelle stagioni FIE lette (o non abbinato)
        a["elo"] = dati_elo_atleta(e)
        if e.get("arma") != a["arma"]:
            a["elo"]["arma"] = e.get("arma")   # caso raro: la pagina scrive l'arma accanto all'ELO
        collegati += 1
        if "v" in a["elo"]:
            mostrati += 1
            gare_usate.update(str(c) for _, _, c in a["elo"]["st"])

    # 2. top 10 ELO di ognuna delle 6 gare: solo ELO mostrabili e solo l'arma principale
    per_gara = {}
    for e in elenco:
        if e.get("livello") not in ("stabile", "provvisorio") or not e.get("principale"):
            continue
        per_gara.setdefault(f"{e.get('genere')}|{e.get('arma')}", []).append(e)
    top = {}
    for chiave, lista in per_gara.items():
        lista.sort(key=lambda e: -e["elo"])
        righe = []
        for e in lista[:TOP_ELO]:
            info = ath.get(e.get("notion") or "")
            if info:                      # nome e bandiera come in Athletes
                flag, noc = bandiera_e_noc(info["noc"])
                nome = re.sub(r"\s+", " ", info["nome"]).strip()
                if noc == "—":            # NOC vuoto in Athletes: uso quello della FIE
                    noc = e.get("noc") or "—"
            else:                         # schermidore non ancora in Athletes: dati della FIE
                flag, noc, nome = "", e.get("noc") or "—", e.get("nome", "")
            righe.append({"id": e.get("notion"), "nome": nome, "flag": flag, "noc": noc,
                          "v": e["elo"], "liv": e["livello"], "n": e.get("incontri", 0)})
        top[chiave] = righe

    nomi_gare = {str(cid): (t or {}).get("nome", "") for cid, t in (raw.get("tornei") or {}).items()}
    dati["elo"] = {
        "aggiornato": raw.get("aggiornato"),
        "schermidori": len({e.get("id_fie") for e in elenco}),
        "mostrati": sum(1 for e in elenco if e.get("livello") in ("stabile", "provvisorio")),
        "regole": raw.get("regole") or {},
        "tornei": {cid: nomi_gare.get(cid, "") for cid in sorted(gare_usate)},
        "top": top,
    }
    print(f"ELO (scherma-elo.json del {raw.get('aggiornato')}): {collegati} schermidori della classifica "
          f"FEN collegati, {mostrati} con ELO mostrato; top {TOP_ELO} ELO in {len(top)} gare")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file con {ath, res} salvati, per le prove")
    args = ap.parse_args()
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        ath, res = raw["ath"], raw["res"]
    else:
        ath, res = leggi_notion()
    if FORMULA_PROVVISORIA:
        print("AVVISO formula FEN PROVVISORIA (struttura del WON): i punti non sono ancora quelli di Notion")
    oggi = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date()
    dati = aggrega(ath, res, oggi)
    aggiungi_elo(dati, ath)               # novità sessione 3
    (CARTELLA / "scherma-performance.json").write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"scherma-performance.json: {len(dati['atleti'])} schermidori, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} tornei")
    for g, nome_g in (("U", "Uomini"), ("D", "Donne")):
        for arma in ARMI.values():
            primo = next((a for a in dati["atleti"] if a["genere"] == g and a["arma"] == arma), None)
            if primo:
                print(f"  {nome_g} {arma}: primo per FEN {primo['nome']} ({primo['noc']}) {primo['fen']}")


if __name__ == "__main__":
    main()
