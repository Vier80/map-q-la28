#!/usr/bin/env python3
"""Legge dal db Notion "LA28 Tennis" la simulazione dei qualificati (scritta dall'agente tennis)
e scrive tennis.json, usato dalla pagina tennis.html.

Uso:
  NOTION_TOKEN=... python aggiorna_tennis.py      legge da Notion
  python aggiorna_tennis.py --da-json file.json   legge un file locale (per le prove)

Non servono librerie da installare.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
DATA_SOURCE_ID = "40ff48c9-aad9-8066-8872-000b077d062c"   # LA28 Tennis
NOTION_VERSION = "2025-09-03"

EVENTI = {   # nome nel db -> (nome in pagina, posti, atleti per voce)
    "Men's Singles": ("Singolare maschile", 64, 1),
    "Women's Singles": ("Singolare femminile", 64, 1),
    "Men's Doubles": ("Doppio maschile", 32, 2),
    "Women's Doubles": ("Doppio femminile", 32, 2),
}


def chiama(metodo, percorso, corpo=None):
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("Manca NOTION_TOKEN.")
    richiesta = urllib.request.Request(
        f"https://api.notion.com/v1/{percorso}",
        data=json.dumps(corpo).encode() if corpo is not None else None, method=metodo,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    for tentativo in range(5):
        try:
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as errore:
            testo = errore.read().decode(errors="replace")
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 4:
                time.sleep(2 ** tentativo)
                continue
            if errore.code == 404:
                sys.exit('Notion non trova il database: collega la connessione al db "LA28 Tennis" (••• > Connessioni).')
            sys.exit(f"Errore Notion {errore.code}: {testo}")


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
    if t == "date":
        return (p["date"] or {}).get("start")
    return None


def leggi_notion():
    righe, cursore = [], None
    while True:
        corpo = {"page_size": 100}
        if cursore:
            corpo["start_cursor"] = cursore
        r = chiama("POST", f"data_sources/{DATA_SOURCE_ID}/query", corpo)
        for pagina in r["results"]:
            p = pagina["properties"]
            righe.append({
                "pos": valore(p.get("Pos")), "ranking": valore(p.get("Ranking")),
                "nome": valore(p.get("Name")) or "", "noc": valore(p.get("NOC")) or "",
                "evento": valore(p.get("Evento")), "stato": valore(p.get("Stato")),
                "via": valore(p.get("Via di qualificazione")), "dettagli": valore(p.get("Dettagli")) or "",
                "simulazione": valore(p.get("Simulazione")) or "", "data_classifica": valore(p.get("Data Classifica")),
            })
        if not r.get("has_more"):
            break
        cursore = r["next_cursor"]
    return righe


def aggrega(righe):
    eventi = {}
    for chiave, (nome, posti, per_voce) in EVENTI.items():
        eventi[chiave] = {"nome": nome, "posti": posti, "per_voce": per_voce,
                          "genere": "W" if chiave.startswith("Women") else "M",
                          "tipo": "doppio" if "Doubles" in chiave else "singolare",
                          "classifica": None, "voci": []}
    for r in righe:
        e = eventi.get(r["evento"])
        if not e:
            continue
        dettagli = r["dettagli"].split(" | ")[0].strip()       # toglie le note tecniche sulla fonte
        dettagli = dettagli.split("; somma dei migliori ranking")[0]   # la somma è già mostrata a destra
        e["voci"].append({
            "pos": int(r["pos"]) if r["pos"] is not None else 999,
            "ranking": int(r["ranking"]) if r["ranking"] is not None else None,
            "nome": r["nome"], "noc": r["noc"], "stato": r["stato"] or "", "via": r["via"] or "",
            "dettagli": dettagli,
        })
        if r.get("data_classifica"):
            e["classifica"] = max(e["classifica"] or "", r["data_classifica"][:10])
    for e in eventi.values():
        e["voci"].sort(key=lambda v: v["pos"])
    simulazioni = sorted(r["simulazione"] for r in righe if r.get("simulazione"))
    return {"simulazione": simulazioni[-1] if simulazioni else "", "eventi": eventi}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--da-json")
    args = parser.parse_args()
    righe = json.load(open(args.da_json, encoding="utf-8")) if args.da_json else leggi_notion()
    if not righe:
        sys.exit("Nessuna riga nel db LA28 Tennis: tennis.json non è stato toccato.")
    dati = aggrega(righe)
    (CARTELLA / "tennis.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    print({e["nome"]: len(e["voci"]) for e in dati["eventi"].values()})


if __name__ == "__main__":
    main()
