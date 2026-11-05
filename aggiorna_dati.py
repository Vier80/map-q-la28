#!/usr/bin/env python3
"""Legge dal db Notion "Athletes" le righe con Q in "🎟️Pass LA28" e scrive data.json.

Uso:
  NOTION_TOKEN=... python aggiorna_dati.py        legge da Notion
  python aggiorna_dati.py --da-tsv righe.tsv      legge da un file locale (per le prove)

Non servono librerie da installare.
"""
import argparse
import csv
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

# ---- Impostazioni del tuo database ---------------------------------------
DATA_SOURCE_ID = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"
PROP_PASS = "🎟️Pass LA28"
PROP_NOME = "Cognome e Nome"
PROP_NOC = "NOC"
PROP_SPORT = "Sport"
PROP_DISCIPLINA = "Disciplina"
PROP_CRITERIO = "Altri Criteri"
NOTION_VERSION = "2025-09-03"

# ---- Atleti per riga -----------------------------------------------------
# In Notion una squadra è una riga sola. Qui si dice quanti atleti vale.
# Fonti: sistemi di qualificazione LA28. Se aggiungi una gara a squadre nuova,
# aggiungila qui: lo script ti avvisa quando ne trova una che non conosce.
ROSE = {
    "Men's Volley": 12, "Women's Volley": 12,
    "Men's Basketball": 12, "Women's Basketball": 12,
    "Men's 3x3": 4, "Women's 3x3": 4,
    "Men's Hockey Field": 16, "Women's Hockey Field": 16,
    "Men's Handball": 14, "Women's Handball": 14,
    "Men's Football": 18, "Women's Football": 18,      # 504 atleti / 28 squadre
    "Men's Flag": 10, "Women's Flag": 10,
    "Men's Lacrosse": 11, "Women's Lacrosse": 11,
    "Men's Rugby Seevens": 12, "Women's Rugby Sevens": 12,
    "Baseball": 24, "Softball": 15,
    "Men's Cricket T20": 15, "Women's Cricket T20": 15,
    "Men's Water Polo": 12, "Women's Water Polo": 12,  # DA VERIFICARE: valore di Parigi 2024
    "MAG Team": 5, "WAG Team": 5, "Group All-Around": 5,
    "Dressage Team": 3, "Eventing Team": 3, "Jumping Team": 3,
    "Men's Recurve Team": 3, "Women's Recurve Team": 3,
    "Recurve Mixed team": 2, "Compound Mixed Team": 2,
    "3️⃣MixedRelay": 4, "🏓MixedTeam": 6,
    "Beach Volley Men's": 2, "Beach Volley Women's": 2,
}

# Codici che sulla mappa confluiscono in un altro NOC.
ACCORPA = {"ENG": "GBR", "SCO": "GBR", "WAL": "GBR"}

INDIZI_SQUADRA = re.compile(r"team|relay|4x|group|duet|mixed", re.I)
APICI = re.compile(r"[\s¹²³⁰-₟ʰ-˿ᴬ-ᶿ]+$")


def pulisci_nome(nome):
    return APICI.sub("", nome).strip()


def codice_noc(valore):
    """'🇮🇹ITA' -> 'ITA'."""
    trovato = re.search(r"[A-Z]{2,3}$", valore or "")
    return trovato.group(0) if trovato else ""


def atleti_della_riga(riga, avvisi):
    for disciplina in riga["discipline"]:
        if disciplina in ROSE:
            return ROSE[disciplina], True
    if "/" in riga["nome"]:
        return riga["nome"].count("/") + 1, True
    if any(INDIZI_SQUADRA.search(d) for d in riga["discipline"]):
        avvisi.append(f"Gara non in ROSE, contata 1 atleta: {riga['nome']} ({', '.join(riga['discipline'])})")
    return 1, False


def correggi_arco(righe):
    """Nel recurve lo stesso atleta non va contato due volte.

    Regolamento World Archery: 3 atleti per genere se l'NOC ha la squadra,
    altrimenti 1. La squadra mista recurve (1 uomo + 1 donna) pesca da quei posti.
    """
    per_noc = {}
    for riga in righe:
        if riga["sport"] == "Archery":
            per_noc.setdefault(riga["noc"], []).append(riga)
    for gruppo in per_noc.values():
        coperti = {"Men": False, "Women": False}
        for riga in gruppo:
            for genere in coperti:
                if f"{genere}'s Recurve Team" in riga["discipline"]:
                    coperti[genere] = True
        for riga in gruppo:
            for genere in coperti:
                if f"{genere}'s Recurve Individual" in riga["discipline"]:
                    if coperti[genere]:
                        riga["atleti"] = 0
                        riga["nota"] = "già compreso nella squadra"
                    coperti[genere] = True
        for riga in gruppo:
            if "Recurve Mixed team" in riga["discipline"]:
                riga["atleti"] = sum(1 for genere in coperti if not coperti[genere])
                if riga["atleti"] < 2:
                    riga["nota"] = "atleti già contati nel recurve"


def aggrega(righe, adesso):
    mondo = json.loads((CARTELLA / "mondo.json").read_text(encoding="utf-8"))
    nomi = {}
    for geometria in mondo["objects"]["countries"]["geometries"]:
        noc = geometria["properties"].get("noc")
        nome = geometria["properties"]["nome"]
        if noc and (noc not in nomi or len(nome) < len(nomi[noc])):
            nomi[noc] = nome

    avvisi = []
    viste = set()
    pulite = []
    for riga in righe:
        chiave = riga.get("id") or (riga["noc"], riga["nome"], tuple(riga["discipline"]))
        if chiave in viste:
            avvisi.append(f"Riga doppia ignorata: {riga['nome']}")
            continue
        viste.add(chiave)
        riga = dict(riga, nome=pulisci_nome(riga["nome"]), noc=codice_noc(riga["noc"]))
        riga["noc"] = ACCORPA.get(riga["noc"], riga["noc"])
        if not riga["noc"]:
            avvisi.append(f"Riga senza NOC, esclusa: {riga['nome']}")
            continue
        riga["atleti"], riga["squadra"] = atleti_della_riga(riga, avvisi)
        pulite.append(riga)
    correggi_arco(pulite)

    nocs, senza_mappa = {}, []
    for riga in pulite:
        voce = nocs.setdefault(riga["noc"], {"nome": nomi.get(riga["noc"], riga["noc"]), "atleti": 0, "pass": 0, "righe": []})
        voce["atleti"] += riga["atleti"]
        voce["pass"] += 1
        voce["righe"].append({
            "nome": riga["nome"], "sport": riga["sport"], "discipline": riga["discipline"],
            "atleti": riga["atleti"], "squadra": riga["squadra"], "ospitante": riga["ospitante"],
            "nota": riga.get("nota", ""),
        })
    for noc, voce in nocs.items():
        voce["righe"].sort(key=lambda r: (r["sport"], r["nome"]))
        if noc not in nomi:
            senza_mappa.append(noc)
    return {
        "aggiornato": adesso,
        "totali": {"atleti": sum(v["atleti"] for v in nocs.values()), "pass": len(pulite), "noc": len(nocs)},
        "noc": dict(sorted(nocs.items(), key=lambda kv: (-kv[1]["atleti"], kv[0]))),
        "senza_mappa": sorted(senza_mappa),
    }, avvisi


def leggi_tsv(percorso):
    righe = []
    with open(percorso, encoding="utf-8", newline="") as file:
        for campi in csv.reader(file, delimiter="\t", quoting=csv.QUOTE_NONE):
            noc, sport, discipline, criterio, *nome = campi
            righe.append({"noc": noc, "sport": sport, "discipline": discipline.split("|"),
                          "ospitante": criterio == "H", "nome": " ".join(nome)})
    return righe


def pagina_in_riga(pagina):
    p = pagina["properties"]
    selezione = lambda nome: ((p.get(nome) or {}).get("select") or {}).get("name", "")
    return {
        "id": pagina["id"],
        "nome": "".join(t["plain_text"] for t in p[PROP_NOME]["title"]),
        "noc": selezione(PROP_NOC),
        "sport": selezione(PROP_SPORT),
        "discipline": [v["name"] for v in p[PROP_DISCIPLINA]["multi_select"]],
        "ospitante": "Host Country" in selezione(PROP_CRITERIO),
    }


def chiama_notion(token, corpo):
    richiesta = urllib.request.Request(
        f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query",
        data=json.dumps(corpo).encode(), method="POST",
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
                sys.exit('Notion non trova il database: collega la connessione al db "Athletes" (••• > Connessioni).')
            sys.exit(f"Errore Notion {errore.code}: {testo}")


def leggi_notion(token):
    righe, cursore = [], None
    while True:
        corpo = {"page_size": 100, "filter": {"property": PROP_PASS, "select": {"equals": "Q"}}}
        if cursore:
            corpo["start_cursor"] = cursore
        risposta = chiama_notion(token, corpo)
        righe += [pagina_in_riga(p) for p in risposta["results"]]
        if not risposta.get("has_more"):
            return righe
        cursore = risposta["next_cursor"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--da-tsv")
    args = parser.parse_args()
    if args.da_tsv:
        righe = leggi_tsv(args.da_tsv)
    else:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            sys.exit("Manca NOTION_TOKEN.")
        righe = leggi_notion(token)
    if not righe:
        sys.exit("Nessuna riga con Q: data.json non è stato toccato.")
    oggi = datetime.datetime.now().strftime("%Y-%m-%d")
    dati, avvisi = aggrega(righe, oggi)
    (CARTELLA / "data.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{dati['totali']['atleti']} atleti, {dati['totali']['pass']} pass, {dati['totali']['noc']} NOC")
    for avviso in avvisi:
        print("AVVISO:", avviso)


if __name__ == "__main__":
    main()
