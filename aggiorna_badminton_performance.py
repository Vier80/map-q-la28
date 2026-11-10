#!/usr/bin/env python3
"""Pagina Performance Badminton: legge da Notion i risultati di badminton dei db "Risultati A"
(MASTER RESULTS) e "Risultati B" (MASTER MINOR) e gli atleti/coppie di badminton del db Athletes,
ricalcola l'indice WON 🔺 con le stesse formule di Notion e scrive badminton-performance.json,
usato dalla pagina badminton-performance.html.

La formula WON e la lettura da Notion sono prese da aggiorna_judo_performance.py (stessa
cartella): se cambi la formula WON in Notion, basta correggerla lì e vale per entrambe le pagine.

Le 5 specialità: singolare maschile e femminile, doppio maschile, femminile e misto.
Nei doppi la coppia è una sola pagina del db Athletes (es. "SEO Seung-jae/CHAE Yu-jung"),
quindi viene trattata come un unico "atleta".

Uso:
  NOTION_TOKEN=... python aggiorna_badminton_performance.py
  python aggiorna_badminton_performance.py --da-raw raw.json    prova con dati salvati

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
SPECIALITA = {"🏸Men's Singles": "MS", "🏸Women's Singles": "WS", "🏸Men's Doubles": "MD",
              "🏸Women's Doubles": "WD", "🏸Mixed Doubles": "XD"}


# ---------------------------------------------------------------- NOTION
def leggi_notion():
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": "Badminton"}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} atleti e coppie di badminton")
    filtro = {"or": [{"property": "Disciplina", "select": {"equals": d}} for d in SPECIALITA]}
    res = []
    for sigla, db in DB_RISULTATI.items():
        pagine = interroga(db, filtro)
        for pg in pagine:
            p = pg["properties"]
            res.append({"db": sigla, "ids": valore(p.get("Athlete")) or [], "ev": valore(p.get("Evento")) or "",
                        "anno": valore(p.get("Anno")), "mese": valore(p.get("Mese")),
                        "result": valore(p.get("Result")) or "", "rating": valore(p.get("🏟️ Rating")),
                        "disc": valore(p.get("Disciplina")) or "", "cat": valore(p.get("CAT")) or ""})
        print(f"Risultati {sigla}: {len(pagine)} righe nelle specialità di badminton")
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
            if i in ath:                  # tiene solo atleti e coppie di badminton
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
    (CARTELLA / "badminton-performance.json").write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"badminton-performance.json: {len(dati['atleti'])} atleti/coppie, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} tornei")
    for sigla in SPECIALITA.values():
        primo = next((a for a in dati["atleti"] if a["spec"] == sigla), None)
        if primo:
            print(f"  {sigla} primo per WON: {primo['nome']} ({primo['noc']}) {primo['won']}")


if __name__ == "__main__":
    main()
