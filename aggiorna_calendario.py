#!/usr/bin/env python3
"""Legge dal db Notion "Calendario Qualificazioni LA28" gli eventi e scrive calendario.json
per la pagina calendario.html.

Uso:
  NOTION_TOKEN=... python aggiorna_calendario.py              legge da Notion
  python aggiorna_calendario.py --da-json eventi.json          legge il file salvato dall'agente (prove)

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
DATA_SOURCE_ID = "0fc5d220-8897-4352-bb67-9c91bb1f6bd1"   # db "Calendario Qualificazioni LA28"
NOTION_VERSION = "2025-09-03"
FONTE = "https://totallympics.com/qualification-tracker/los-angeles-2028/qualification-calendar/"


def notion(percorso, corpo, token):
    dati = json.dumps(corpo).encode()
    for tentativo in range(6):
        req = urllib.request.Request("https://api.notion.com/v1/" + percorso, data=dati, method="POST", headers={
            "Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and tentativo < 5:
                time.sleep(float(e.headers.get("Retry-After") or 2 ** tentativo))
                continue
            raise SystemExit(f"Notion {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def testo(p):
    if not p:
        return ""
    return "".join(t.get("plain_text", "") for t in p.get(p.get("type"), []) or [])


def da_notion(token):
    eventi, cursore = [], None
    while True:
        corpo = {"page_size": 100}
        if cursore:
            corpo["start_cursor"] = cursore
        r = notion(f"data_sources/{DATA_SOURCE_ID}/query", corpo, token)
        for p in r["results"]:
            pr = p["properties"]
            g = lambda n: pr.get(n) or {}
            sel = lambda n: (g(n).get("select") or {}).get("name", "")
            if sel("Stato") == "Non più nel calendario":
                continue
            per = g("Periodo").get("date") or {}
            eventi.append({
                "anno": sel("Anno"), "evento": testo(g("Evento")), "sport": sel("Sport") or "Altro",
                "date": testo(g("Date")), "inizio": per.get("start"), "fine": per.get("end") or per.get("start"),
                "paese": sel("Paese"), "sede": testo(g("Sede")), "quota": g("Posti quota").get("number"),
                "uomini": g("Uomini").get("number"), "donne": g("Donne").get("number"),
                "misti": g("Misti").get("number"), "open": g("Open").get("number"),
                "note": testo(g("Note")), "discussione": g("Discussione").get("url") or "",
                "tracker": g("Tracker").get("url") or "", "chiave": testo(g("Chiave")),
            })
        if not r.get("has_more"):
            return eventi
        cursore = r["next_cursor"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-json", help="file con gli eventi salvati dall'agente (--json)")
    a = ap.parse_args()
    if a.da_json:
        eventi = json.loads(Path(a.da_json).read_text(encoding="utf-8"))
    else:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            sys.exit("Manca NOTION_TOKEN")
        eventi = da_notion(token)
    campi = ["anno", "evento", "sport", "date", "inizio", "fine", "paese", "sede", "quota",
             "uomini", "donne", "misti", "open", "note", "discussione", "tracker"]
    righe = []
    for e in eventi:
        r = {k: e.get(k) for k in campi}
        for k in ("quota", "uomini", "donne", "misti", "open"):
            if isinstance(r[k], float) and r[k].is_integer():
                r[k] = int(r[k])
        if r["inizio"] and not r["fine"]:
            r["fine"] = r["inizio"]
        righe.append({k: v for k, v in r.items() if v not in (None, "")})
    # Ordine: anno, poi data (le date da definire in fondo all'anno), poi nome
    righe.sort(key=lambda r: (r.get("anno", ""), r.get("inizio") or "9999", r.get("fine") or "", r.get("evento", "")))
    out = {
        "aggiornato": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fonte": FONTE,
        "eventi": righe,
    }
    (CARTELLA / "calendario.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"calendario.json: {len(righe)} eventi")


if __name__ == "__main__":
    main()
