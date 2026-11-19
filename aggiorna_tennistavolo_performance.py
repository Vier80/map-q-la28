#!/usr/bin/env python3
"""Pagina Performance Tennistavolo (versione 1.0 del 19/11/2026, scheda 43): legge da Notion i risultati
di tennistavolo dei db "Risultati A" (MASTER RESULTS) e "Risultati B" (MASTER MINOR) e gli atleti/coppie
di tennistavolo del db Athletes (Sport = Table Tennis), ricalcola l'indice WON 🔺 con le stesse formule
di Notion e scrive tennistavolo-performance.json, usato dalla pagina tennistavolo-performance.html.

È la copia di aggiorna_badminton_performance.py (schede 14 e 33) con queste differenze:
  - Sport = "Table Tennis" e specialità con l'emoji 🏓 ("🏓Men's Singles" ...);
  - "🏓Mixed doubles" con la d minuscola (vecchia opzione di Risultati A) vale come "🏓Mixed Doubles";
  - la sesta specialità olimpica, "🏓MixedTeam" (squadre miste), è esclusa dalla pagina
    (decisione del 19/11/2026, foglio «Tennistavolo LA28 – punti da decidere e verificare»);
  - ELO da tennistavolo-elo.json (workflow "ELO Tennis Tavolo", ogni lunedì).

La formula WON e la lettura da Notion sono prese da aggiorna_judo_performance.py (stessa
cartella): se cambi la formula WON in Notion, basta correggerla lì e vale per entrambe le pagine.

Le 5 specialità: singolare maschile e femminile, doppio maschile, femminile e misto.
Nei doppi la coppia è una sola pagina del db Athletes (es. "Felix LEBRUN/Alexis LEBRUN"),
quindi viene trattata come un unico "atleta".

ELO: se nella cartella c'è tennistavolo-elo.json, lo script aggiunge a tennistavolo-performance.json
l'ELO di ogni atleta o coppia. Il collegamento passa dal campo "notion" di tennistavolo-elo.json, che è
l'id della pagina di Athletes, cioè lo stesso "id" usato qui. Se tennistavolo-elo.json manca o non si
legge, la pagina funziona lo stesso, senza ELO.

Uso:
  NOTION_TOKEN=... python aggiorna_tennistavolo_performance.py
  python aggiorna_tennistavolo_performance.py --da-raw raw.json    prova con dati salvati

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
                                       interroga, piazzamento, valore, won)

# nome della Disciplina in Notion -> sigla usata dalla pagina
# ("🏓Mixed doubles" con la d minuscola: vecchia opzione di Risultati A, scheda 40 §4 punto 15)
SPECIALITA = {"🏓Men's Singles": "MS", "🏓Women's Singles": "WS", "🏓Men's Doubles": "MD",
              "🏓Women's Doubles": "WD", "🏓Mixed Doubles": "XD", "🏓Mixed doubles": "XD"}
SPORT = "Table Tennis"                       # valore di "Sport" in Athletes
FILE_JSON = "tennistavolo-performance.json"  # letto dalla pagina tennistavolo-performance.html

# ---------------------------------------------------------------- ELO
FILE_ELO = CARTELLA / "tennistavolo-elo.json"   # prodotto da elo_tennistavolo.py nello stesso repository
TOP_ELO = 10                                 # quanti nella "Classifica ELO · top 10" di ogni specialità


# ---------------------------------------------------------------- NOTION
def leggi_notion():
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": SPORT}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} atleti e coppie di tennistavolo")
    # nel filtro solo i nomi che esistono oggi in Notion (la vecchia "🏓Mixed doubles" è stata corretta)
    filtro = {"or": [{"property": "Disciplina", "select": {"equals": d}} for d in SPECIALITA if d != "🏓Mixed doubles"]}
    res = []
    for sigla, db in DB_RISULTATI.items():
        pagine = interroga(db, filtro)
        for pg in pagine:
            p = pg["properties"]
            res.append({"db": sigla, "ids": valore(p.get("Athlete")) or [], "ev": valore(p.get("Evento")) or "",
                        "anno": valore(p.get("Anno")), "mese": valore(p.get("Mese")),
                        "result": valore(p.get("Result")) or "", "rating": valore(p.get("🏟️ Rating")),
                        "disc": valore(p.get("Disciplina")) or "", "cat": valore(p.get("CAT")) or ""})
        print(f"Risultati {sigla}: {len(pagine)} righe nelle specialità di tennistavolo")
    return ath, res


# ---------------------------------------------------------------- AGGREGAZIONE
def aggrega(ath, res, oggi):
    gruppi = {}
    for r in res:
        if r["cat"] == "Youth":           # la pagina è solo senior
            continue
        if not r["ev"]:                   # righe senza torneo (es. "Scheda Ranking"): non sono gare
            continue
        if (r["result"] or "").strip().lower() in NON_PRESENTATI:   # non ha giocato: non conta
            continue
        for i in r["ids"]:
            if i in ath:                  # tiene solo atleti e coppie di tennistavolo
                gruppi.setdefault(i, []).append(r)
    atleti, senza_rating = [], {}
    for i, righe in gruppi.items():
        info = ath[i]
        righe.sort(key=lambda r: (r["anno"] or 0, r["mese"] or 0))
        spec = SPECIALITA.get(righe[-1]["disc"])           # specialità dell'ultimo risultato
        if not spec:
            spec = next((SPECIALITA[d] for d in info["disc"] if d in SPECIALITA), None)
        if not spec:
            continue
        for r in righe:
            if not r["rating"]:
                senza_rating[r["ev"]] = senza_rating.get(r["ev"], 0) + 1
        ws = [won(r) for r in righe]
        pl = [piazzamento(r["result"]) for r in righe]
        rat = [r["rating"] for r in righe if r["rating"]]
        eta = None
        if info["dob"]:
            d = datetime.date.fromisoformat(info["dob"][:10])
            eta = oggi.year - d.year - ((oggi.month, oggi.day) < (d.month, d.day))
        m = re.match(r"^(\W*?)([A-Z]{3})$", (info["noc"] or "").strip())
        atleti.append({
            "id": i, "nome": re.sub(r"\s+", " ", info["nome"]).replace(" / ", "/").strip(),
            "flag": m.group(1) if m else "", "noc": m.group(2) if m else (info["noc"] or "—"),
            "spec": spec, "coppia": spec in ("MD", "WD", "XD"),
            "won": round(sum(ws), 2), "gare": len(righe),
            "ori": pl.count(1), "arg": pl.count(2), "bro": pl.count(3),
            "field": round(statistics.mean(rat)) if rat else None,
            "piazz": round(statistics.mean([p for p in pl if p]), 1) if any(pl) else None,
            "q": info["pas"] == "Q", "hon": info["hon"], "eta": eta,
            "storia": [[r["ev"], int(r["anno"] or 0), (r["result"] or "").strip(),
                        int(r["rating"]) if r["rating"] else None, w] for r, w in zip(righe, ws)]})
    atleti.sort(key=lambda a: -a["won"])
    for ev, n in sorted(senza_rating.items()):
        print(f"AVVISO {n} risultati di «{ev}» senza 🏟️ Rating: valgono 0 punti WON")
    eventi = sorted({r["ev"] for a in atleti for r in gruppi[a["id"]] if r["ev"]})
    return {"aggiornato": oggi.isoformat(), "atleti": atleti, "eventi": eventi,
            "n_risultati": sum(a["gare"] for a in atleti)}


# ---------------------------------------------------------------- ELO
def dati_elo_atleta(e):
    """Dati ELO di un atleta o coppia per la pagina, nel formato compatto di tennistavolo-performance.json.

    liv = livello ("stabile", "provvisorio", "nascosto"); n = incontri; t = tornei.
    Solo se il livello non è "nascosto": v = ELO, max = ELO massimo, vit = vittorie,
    ult = data dell'ultimo incontro, st = storico [[data, ELO dopo il torneo, codice torneo], ...].
    """
    out = {"liv": e.get("livello"), "n": e.get("incontri", 0), "t": e.get("tornei", 0)}
    if e.get("livello") in ("stabile", "provvisorio"):
        out.update(v=e.get("elo"), max=e.get("elo_max"), vit=e.get("vittorie"), ult=e.get("ultimo"),
                   st=e.get("storico") or [])
    return out


def bandiera_e_noc(noc_notion):
    """'🇮🇹ITA' (valore di Athletes) -> ('🇮🇹', 'ITA'). Se il formato non torna: ('', valore così com'è)."""
    m = re.match(r"^(\W*?)([A-Z]{3})$", (noc_notion or "").strip())
    return (m.group(1), m.group(2)) if m else ("", noc_notion or "—")


def aggiungi_elo(dati, ath):
    """Aggiunge a tennistavolo-performance.json l'ELO di tennistavolo-elo.json (come badminton, scheda 33).

    - a ogni atleta o coppia della classifica WON collegato all'ELO aggiunge il campo "elo";
      se la specialità dell'ELO è diversa da quella della classifica WON (caso raro), la scrive
      nel campo "spec" dell'ELO, così la pagina la mostra accanto al numero;
    - in dati["elo"] mette la data dell'ELO, le regole, i nomi dei tornei dello storico e la top 10
      ELO di ognuna delle 5 specialità (anche chi non ha punti WON o non è in Athletes).
    """
    if not FILE_ELO.exists():
        print("AVVISO tennistavolo-elo.json non trovato: la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return
    try:
        raw = json.loads(FILE_ELO.read_text(encoding="utf-8"))
        elenco = raw["atleti"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"AVVISO tennistavolo-elo.json non leggibile ({e}): la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return

    # 1. collegamento con la classifica WON: "notion" (ELO) = "id" (WON) = id della pagina di Athletes
    per_pagina = {e["notion"]: e for e in elenco if e.get("notion")}
    tornei_usati, collegati, mostrati = set(), 0, 0
    for a in dati["atleti"]:
        e = per_pagina.get(a["id"])
        if not e:
            continue                      # nessun incontro nei tornei WTT letti (o pagina non abbinata)
        a["elo"] = dati_elo_atleta(e)
        if e.get("spec") != a["spec"]:
            a["elo"]["spec"] = e.get("spec")   # caso raro: la pagina scrive la specialità accanto all'ELO
        collegati += 1
        if "v" in a["elo"]:
            mostrati += 1
            tornei_usati.update(str(c) for _, _, c in a["elo"]["st"])

    # 2. top 10 ELO di ognuna delle 5 specialità: solo ELO mostrabili
    per_spec = {}
    for e in elenco:
        if e.get("livello") in ("stabile", "provvisorio"):
            per_spec.setdefault(e.get("spec"), []).append(e)
    top = {}
    for spec, lista in per_spec.items():
        lista.sort(key=lambda e: -e["elo"])
        righe = []
        for e in lista[:TOP_ELO]:
            info = ath.get(e.get("notion") or "")
            if info:                      # nome e bandiera come in Athletes
                flag, noc = bandiera_e_noc(info["noc"])
                nome = re.sub(r"\s+", " ", info["nome"]).replace(" / ", "/").strip()
                if noc == "—":            # NOC vuoto in Athletes: uso quello del sito WTT
                    noc = e.get("noc") or "—"
            else:                         # non ancora in Athletes: dati del sito WTT
                flag, noc = "", e.get("noc") or "—"
                nome = re.sub(r"\s*/\s*", "/", e.get("nome", "")).strip()
            righe.append({"id": e.get("notion"), "nome": nome, "flag": flag, "noc": noc,
                          "v": e["elo"], "liv": e["livello"], "n": e.get("incontri", 0)})
        top[spec] = righe

    nomi_tornei = {str(cid): (t or {}).get("nome", "") for cid, t in (raw.get("tornei") or {}).items()}
    dati["elo"] = {
        "aggiornato": raw.get("aggiornato"),
        "giocatori": len(elenco),
        "mostrati": sum(1 for e in elenco if e.get("livello") in ("stabile", "provvisorio")),
        "regole": raw.get("regole") or {},
        "tornei": {cid: nomi_tornei.get(cid, "") for cid in sorted(tornei_usati)},
        "top": top,
    }
    print(f"ELO (tennistavolo-elo.json del {raw.get('aggiornato')}): {collegati} atleti/coppie della classifica "
          f"WON collegati, {mostrati} con ELO mostrato; top {TOP_ELO} ELO in {len(top)} specialità")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file con {ath, res} salvati, per le prove")
    args = ap.parse_args()
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        ath, res = raw["ath"], raw["res"]
    else:
        ath, res = leggi_notion()
    oggi = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date()
    dati = aggrega(ath, res, oggi)
    aggiungi_elo(dati, ath)
    (CARTELLA / FILE_JSON).write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{FILE_JSON}: {len(dati['atleti'])} atleti/coppie, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} tornei")
    for sigla in dict.fromkeys(SPECIALITA.values()):     # MS, WS, MD, WD, XD (XD una volta sola)
        primo = next((a for a in dati["atleti"] if a["spec"] == sigla), None)
        if primo:
            print(f"  {sigla} primo per WON: {primo['nome']} ({primo['noc']}) {primo['won']}")


if __name__ == "__main__":
    main()
