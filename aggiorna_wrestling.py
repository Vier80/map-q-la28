#!/usr/bin/env python3
"""Legge dal db Notion "Previsioni Wrestling LA28" le previsioni calcolate dall'agente
previsioni e scrive wrestling.json, usato dalla pagina wrestling.html.

Uso:
  NOTION_TOKEN=... python aggiorna_wrestling.py      legge da Notion
  python aggiorna_wrestling.py --da-json file.json   legge un file locale (per le prove)

Non servono librerie da installare.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
DATA_SOURCE_ID = "875b452d-a3a6-4a61-84f7-363e1e1766a9"   # Previsioni Wrestling LA28
NOTION_VERSION = "2025-09-03"

STILI = {"FS": "Libera", "GR": "Greco-romana", "WW": "Femminile"}
ORDINE_KG = {"FS": [57, 65, 74, 86, 97, 125], "GR": [60, 67, 77, 87, 97, 130], "WW": [50, 53, 57, 62, 68, 76]}


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
                sys.exit('Notion non trova il database: collega la connessione al db "Previsioni Wrestling LA28" (••• > Connessioni).')
            sys.exit(f"Errore Notion {errore.code}: {testo}")


def testo(p):
    if not p:
        return ""
    t = p.get("type")
    if t in ("title", "rich_text"):
        return "".join(x["plain_text"] for x in p[t])
    if t == "select":
        return (p["select"] or {}).get("name", "")
    if t == "number":
        return p["number"]
    if t == "multi_select":
        return [x["name"] for x in p["multi_select"]]
    if t == "date":
        return (p["date"] or {}).get("start", "")
    if t == "relation":
        return [x["id"] for x in p["relation"]]
    return ""


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
                "atleta": testo(p.get("Atleta")), "noc": testo(p.get("NOC")), "stile": testo(p.get("Stile")),
                "categoria": testo(p.get("Categoria")), "rank": testo(p.get("Rank")), "rating": testo(p.get("Rating")),
                "p_oro": testo(p.get("P Oro")), "p_medaglia": testo(p.get("P Medaglia")),
                "p_qualifica": testo(p.get("P Qualifica")), "via": testo(p.get("Via probabile")),
                "bilancio": testo(p.get("Bilancio")), "eta": testo(p.get("Età LA28")),
                "titoli": testo(p.get("Titoli")) or [], "aggiornato": testo(p.get("Aggiornato")),
            })
        if not r.get("has_more"):
            break
        cursore = r["next_cursor"]
    info = chiama("GET", f"data_sources/{DATA_SOURCE_ID}")
    descrizione = "".join(x.get("plain_text", "") for x in info.get("description", []))
    return righe, descrizione


def aggrega(righe, descrizione):
    categorie = {}
    for r in righe:
        if not r["categoria"] or not r["atleta"]:
            continue
        stile, kg = r["categoria"].split()[0], int(r["categoria"].split()[1].replace("kg", ""))
        c = categorie.setdefault(r["categoria"], {"stile": stile, "nome_stile": STILI.get(stile, stile),
                                                  "kg": kg, "atleti": []})
        c["atleti"].append({
            "nome": r["atleta"], "noc": r["noc"], "rank": int(r["rank"] or 99),
            "oro": r["p_oro"] or 0, "medaglia": r["p_medaglia"] or 0, "qualifica": r["p_qualifica"] or 0,
            "via": r["via"], "rating": r["rating"], "bilancio": r["bilancio"],
            "eta": r.get("eta"), "titoli": r.get("titoli") or [],
        })
    for c in categorie.values():
        c["atleti"].sort(key=lambda a: a["rank"])
    ordine = {f"{s} {kg}kg": (i, j) for i, s in enumerate(ORDINE_KG) for j, kg in enumerate(ORDINE_KG[s])}
    date = sorted(r.get("aggiornato") or "" for r in righe)
    simulazioni = None
    if "simulazioni" in descrizione:
        try:
            simulazioni = int(descrizione.split(" simulazioni")[0].split()[-1])
        except ValueError:
            pass
    incontri = None
    if " incontri" in descrizione:
        try:
            incontri = int(descrizione.split(" incontri")[0].split()[-1])
        except ValueError:
            pass
    return {
        "aggiornato": (date[-1] if date and date[-1] else datetime.date.today().isoformat())[:10],
        "simulazioni": simulazioni, "incontri": incontri,
        "categorie": dict(sorted(categorie.items(), key=lambda kv: ordine.get(kv[0], (9, 9)))),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--da-json")
    args = parser.parse_args()
    if args.da_json:
        righe, descrizione = json.load(open(args.da_json, encoding="utf-8")), ""
        for r in righe:
            r["aggiornato"] = datetime.date.today().isoformat()
    else:
        righe, descrizione = leggi_notion()
    if not righe:
        sys.exit("Nessuna previsione in Notion: wrestling.json non è stato toccato.")
    dati = aggrega(righe, descrizione)
    (CARTELLA / "wrestling.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(dati['categorie'])} categorie, {sum(len(c['atleti']) for c in dati['categorie'].values())} atleti")


if __name__ == "__main__":
    main()
