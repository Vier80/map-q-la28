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
    "Men's Water Polo": 11, "Women's Water Polo": 11,  # ricavato: 264 atleti / 24 squadre
    "MAG Team": 5, "WAG Team": 5, "Group All-Around": 5,
    "Dressage Team": 3, "Eventing Team": 3, "Jumping Team": 3,
    "Men's Recurve Team": 3, "Women's Recurve Team": 3,
    "Recurve Mixed team": 2, "Compound Mixed Team": 2,
    "3️⃣MixedRelay": 4, "🏓MixedTeam": 6,
    "Beach Volley Men's": 2, "Beach Volley Women's": 2,
}

# Posti atleti LA28 per sport, dai sistemi di qualificazione. Notion resta la fonte
# dei qualificati, questa tabella dà solo il totale di ogni sport.
POSTI_TOTALI_LA28 = 11198
QUOTE = {
    "Archery": 128, "Artistic Swimming": 96, "Athletics": 1810, "Badminton": 172, "Baseball": 144,
    "Basketball": 288, "Basketball 3x3": 96, "Beachvolley": 96, "Boxing": 248, "Canoe Slalom": 82,
    "Canoe Sprint": 234, "Cricket": 180, "Cycling": 324, "Cycling Track": 190, "Diving": 136,
    "Equestrian": 200, "Fencing": 212, "Flag Football": 120, "Football": 504, "Golf": 120,
    "Gym Artistic": 192, "Gym Rhythmic": 94, "Handball": 336, "Hockey Field": 384, "Judo": 372,
    "Lacrosse Sixes": 132, "Modern Pentathlon": 64, "Open Water": 44, "Rowing": 438,
    "Rowing Coastal": 64, "Rugby Sevens": 288, "Sailing": 330, "Shooting": 340, "Skateboarding": 88,
    "Softball": 90, "Sport Climbing": 76, "Squash": 32, "Surfing": 48, "Swimming": 830,
    "Table Tennis": 172, "Taekwondo": 128, "Tennis": 172, "Trampoline": 32, "Triathlon": 110,
    "Volleyball": 288, "Water Polo": 264, "Weightlifting": 120, "Wrestling": 288,
}

# Codici che sulla mappa confluiscono in un altro NOC.
ACCORPA = {"ENG": "GBR", "SCO": "GBR", "WAL": "GBR"}

# Gare senza genere: l'equitazione mette uomini e donne nella stessa gara.
GARE_OPEN = re.compile(r"dressage|eventing|jumping", re.I)
SOLO_UOMINI = {"mag team", "baseball", "decathlon", "trampoline men"}
SOLO_DONNE = {"wag team", "softball", "heptathlon", "trampoline women", "group all-around", "individual all-around"}

INDIZI_SQUADRA = re.compile(r"team|relay|4x|group|duet|mixed", re.I)
APICI = re.compile(r"[\s¹²³⁰-₟ʰ-˿ᴬ-ᶿ]+$")


def pulisci_nome(nome):
    return APICI.sub("", nome).strip()


def codice_noc(valore):
    """'🇮🇹ITA' -> 'ITA'."""
    trovato = re.search(r"[A-Z]{2,3}$", valore or "")
    return trovato.group(0) if trovato else ""


def categoria_gara(disciplina):
    """M uomini, W donne, X mista, O aperta. Gli sport a volte hanno nomi senza genere."""
    nome = re.sub(r"^[^A-Za-z]+", "", disciplina).lower()
    if "mixed" in nome or nome == "nacra 17":
        return "X"
    if nome in SOLO_UOMINI:
        return "M"
    if nome in SOLO_DONNE:
        return "W"
    if re.search(r"\bwomen", nome):
        return "W"
    if re.search(r"\bmen", nome):
        return "M"
    return "O"


def nome_card(riga):
    if any("3x3" in d for d in riga["discipline"]):
        return "Basketball 3x3"
    return riga["sport"]


def dividi_generi(riga):
    atleti = riga["atleti"]
    if "genere" in riga:
        return riga["genere"]
    categoria = categoria_gara(riga["discipline"][0]) if riga["discipline"] else "O"
    if categoria == "X":
        return {"M": atleti // 2, "W": atleti - atleti // 2, "O": 0}
    return {"M": atleti * (categoria == "M"), "W": atleti * (categoria == "W"), "O": atleti * (categoria == "O")}


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
                riga["genere"] = {"M": int(not coperti["Men"]), "W": int(not coperti["Women"]), "O": 0}
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
    for riga in pulite:
        for disciplina in riga["discipline"]:
            if categoria_gara(disciplina) == "O" and not GARE_OPEN.search(disciplina):
                avvisi.append(f"Gara senza genere riconosciuto, contata come Open: {disciplina}")

    nocs, senza_mappa = {}, []
    for riga in pulite:
        voce = nocs.setdefault(riga["noc"], {"nome": nomi.get(riga["noc"], riga["noc"]), "atleti": 0, "pass": 0, "righe": []})
        voce["atleti"] += riga["atleti"]
        voce["pass"] += 1
        voce["righe"].append({
            "nome": riga["nome"], "sport": riga["sport"], "card": nome_card(riga), "discipline": riga["discipline"],
            "genere": dividi_generi(riga), "gare": {d: categoria_gara(d) for d in riga["discipline"]},
            "atleti": riga["atleti"], "squadra": riga["squadra"], "ospitante": riga["ospitante"],
            "nota": riga.get("nota", ""),
        })
    for noc, voce in nocs.items():
        voce["righe"].sort(key=lambda r: (r["sport"], r["nome"]))
        if noc not in nomi:
            senza_mappa.append(noc)
    sport = {nome: {"quota": quota, "atleti": 0, "M": 0, "W": 0, "O": 0, "pass": 0, "noc": {}} for nome, quota in QUOTE.items()}
    for noc, voce in nocs.items():
        for riga in voce["righe"]:
            carta = sport.get(riga["card"])
            if carta is None:
                avvisi.append(f"Sport senza quota in QUOTE: {riga['card']}")
                carta = sport.setdefault(riga["card"], {"quota": 0, "atleti": 0, "M": 0, "W": 0, "O": 0, "pass": 0, "noc": {}})
            carta["atleti"] += riga["atleti"]
            carta["pass"] += 1
            for genere in "MWO":
                carta[genere] += riga["genere"][genere]
            carta["noc"][noc] = carta["noc"].get(noc, 0) + riga["atleti"]
    for nome, carta in sport.items():
        if carta["atleti"] > carta["quota"]:
            avvisi.append(f"{nome}: {carta['atleti']} qualificati superano i {carta['quota']} posti")
    return {
        "aggiornato": adesso,
        "posti_totali": POSTI_TOTALI_LA28,
        "sport": sport,
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
