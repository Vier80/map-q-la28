#!/usr/bin/env python3
"""Pagina Performance Judo: legge da Notion i risultati di judo dei db "Risultati A"
(MASTER RESULTS) e "Risultati B" (MASTER MINOR) e i judoka del db Athletes, ricalcola
l'indice WON 🔺 con le stesse formule di Notion e scrive judo-performance.json,
usato dalla pagina judo-performance.html.

Perché ricalcolare: l'API di Notion non restituisce il valore delle formule, quindi lo
script rifà lo stesso conto partendo da Result, Anno, Evento e 🏟️ Rating.
Se cambi la formula WON in Notion, cambia anche le funzioni qui sotto (sezione FORMULA).

Uso:
  NOTION_TOKEN=... python aggiorna_judo_performance.py
  python aggiorna_judo_performance.py --da-raw raw.json    prova con dati salvati

Non servono librerie da installare.
"""
import argparse
import datetime
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
NOTION_VERSION = "2025-09-03"
DB_ATHLETES = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"
DB_RISULTATI = {"A": "2caf48c9-aad9-80f2-ac49-000b94979383",   # MASTER RESULTS
                "B": "2cbf48c9-aad9-8095-bd49-000bf60d6cdf"}   # MASTER MINOR
NOMI_DB = {DB_ATHLETES: "Athletes", DB_RISULTATI["A"]: "Risultati A (MASTER RESULTS)",
           DB_RISULTATI["B"]: "Risultati B (MASTER MINOR)"}

PESI_KG = {"Men": ["-60", "-66", "-73", "-81", "-90", "-100", "+100"],
           "Women": ["-48", "-52", "-57", "-63", "-70", "-78", "+78"]}
DISCIPLINE_JUDO = [f"{g}'s {kg}kg" for g, kgs in PESI_KG.items() for kg in kgs]

# ---------------------------------------------------------------- FORMULA WON 🔺
TRAD = {"SF": "3", "QF": "5", "R16": "9", "R32": "17", "R64": "33", "R128": "65"}
NON_PRESENTATI = {"w/o", "dns", "dnp", "wd"}   # ritiri / non presentati
KEYWORDS = ["EUR", "🇪🇺", "Asian", "AFR", "African", "AME", "Pan-Am", "Oce"]


def piazzamento(result):
    t = (result or "").strip()
    t = TRAD.get(t, t)
    try:
        return float(t)
    except ValueError:
        return None                     # come toNumber() vuoto in Notion


def peso_risultato(p):
    if p is None:
        return 0.01
    for posto, peso in ((1, 0.18), (2, 0.13), (3, 0.09), (4, 0.07), (5, 0.05), (6, 0.03), (7, 0.02)):
        if p == posto:
            return peso
    if 8 <= p <= 16:
        return 0.015
    return 0.01                         # partecipazione oltre il 16° posto


def peso_anno(anno):
    return {2025: 0.4, 2026: 0.6, 2027: 0.8, 2028: 1.0}.get(int(anno) if anno else 0, 0.2)


def peso_prestigio(evento):         # solo Risultati A
    ev = evento or ""
    if "🌐" in ev:
        return 1.5
    if any(k in ev for k in KEYWORDS):
        return 1.25
    return 1.0


def won(r):
    rating = r["rating"] or 0
    p = piazzamento(r["result"])
    if r["db"] == "A":
        c = rating * peso_risultato(p) * peso_prestigio(r["ev"]) * 1.0 * peso_anno(r["anno"])
    else:
        c = rating * peso_risultato(p) * 0.55 * peso_anno(r["anno"])
    return round(c * 100) / 100


# ---------------------------------------------------------------- NOTION
def chiama(percorso, corpo):
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
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 4:
                time.sleep(2 ** tentativo)
                continue
            if errore.code == 404:
                db = next((n for i, n in NOMI_DB.items() if i in percorso), "?")
                sys.exit(f'Notion non trova il database "{db}": aprilo, ••• > Connessioni, '
                         f'aggiungi la stessa connessione della mappa.')
            sys.exit(f"Errore Notion {errore.code}: {testo_err}")


def valore(p):
    if not p:
        return None
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in p[t])
    if t == "select":
        return (p["select"] or {}).get("name")
    if t == "number":
        return p["number"]
    if t == "multi_select":
        return [x["name"] for x in p["multi_select"]]
    if t == "date":
        return (p["date"] or {}).get("start")
    if t == "relation":
        return [x["id"].replace("-", "") for x in p["relation"]]
    return None


def interroga(db, filtro):
    pagine, cursore = [], None
    while True:
        corpo = {"page_size": 100, "filter": filtro}
        if cursore:
            corpo["start_cursor"] = cursore
        r = chiama(f"data_sources/{db}/query", corpo)
        pagine += r["results"]
        if not r.get("has_more"):
            return pagine
        cursore = r["next_cursor"]


def leggi_notion():
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": "Judo"}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} judoka")
    filtro = {"or": [{"property": "Disciplina", "select": {"equals": d}} for d in DISCIPLINE_JUDO]}
    res = []
    for sigla, db in DB_RISULTATI.items():
        pagine = interroga(db, filtro)
        for pg in pagine:
            p = pg["properties"]
            res.append({"db": sigla, "ids": valore(p.get("Athlete")) or [], "ev": valore(p.get("Evento")) or "",
                        "anno": valore(p.get("Anno")), "mese": valore(p.get("Mese")),
                        "result": valore(p.get("Result")) or "", "rating": valore(p.get("🏟️ Rating")),
                        "disc": valore(p.get("Disciplina")) or "", "cat": valore(p.get("CAT")) or ""})
        print(f"Risultati {sigla}: {len(pagine)} righe nelle categorie di judo")
    return ath, res


# ---------------------------------------------------------------- AGGREGAZIONE
def categoria(disc):
    m = re.match(r"(Men|Women)'s ([-+]\d+)kg", disc or "")
    return (m.group(1), m.group(2) + " kg") if m else (None, None)


def aggrega(ath, res, oggi):
    gruppi = {}
    for r in res:
        if r["cat"] == "Youth":           # la pagina è solo senior
            continue
        if (r["result"] or "").strip().lower() in NON_PRESENTATI:   # non ha partecipato: non conta
            continue
        for i in r["ids"]:
            if i in ath:                  # tiene solo i judoka (esclude es. il taekwondo -57 kg)
                gruppi.setdefault(i, []).append(r)
    atleti, senza_rating = [], {}
    for i, righe in gruppi.items():
        info = ath[i]
        righe.sort(key=lambda r: (r["anno"] or 0, r["mese"] or 0))
        g, cat = categoria(righe[-1]["disc"])          # categoria dell'ultimo risultato
        if not cat and info["disc"]:
            g, cat = categoria(info["disc"][0])
        if not cat:
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
        m = re.match(r"^(\W*?)([A-Z]{3})$", info["noc"] or "")
        atleti.append({
            "id": i, "nome": re.sub(r"\s+", " ", info["nome"]).strip(),
            "flag": m.group(1) if m else "", "noc": m.group(2) if m else (info["noc"] or "—"),
            "genere": "U" if g == "Men" else "D", "cat": cat,
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
    (CARTELLA / "judo-performance.json").write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"judo-performance.json: {len(dati['atleti'])} atleti, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} tornei")
    if dati["atleti"]:
        a = dati["atleti"][0]
        print(f"Primo per WON: {a['nome']} ({a['noc']}) {a['won']}")


if __name__ == "__main__":
    main()
