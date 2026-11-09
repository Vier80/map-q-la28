#!/usr/bin/env python3
"""Agente "Qualificati LA28".

Cosa fa, in ordine:
  1. legge dal db Notion "Athletes" le righe con Q in "🎟️Pass LA28";
  2. legge i nomi degli eventi collegati in "🎟️ Direct Q Events LA28";
  3. per ogni riga decide il tipo di quota (Athlete / NOC / Team Quota)
     con le regole del file quote_la28.py;
  4. scrive qualificati.json, che la pagina qualificati.html mostra sul web;
  5. aggiorna il db Notion "🎟️ Qualificati LA28": aggiunge le righe nuove,
     corregge quelle cambiate e manda nel cestino quelle che hanno perso la Q.

Uso:
  NOTION_TOKEN=... python aggiorna_qualificati.py           tutto
  NOTION_TOKEN=... python aggiorna_qualificati.py --prova   solo qualificati.json, Notion non viene toccato
  python aggiorna_qualificati.py --da-file prova.json       legge da un file locale (per i test)

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

import aggiorna_dati as base            # riusa rose, nomi puliti e correzione arco della mappa
import quote_la28 as quote

CARTELLA = Path(__file__).resolve().parent

# ---- Impostazioni Notion ---------------------------------------------------
ATHLETES_DS = "2c5f48c9-aad9-801b-b4b0-000b7bb9d214"      # db "Athletes"
EVENTI_DS = "321f48c9-aad9-8012-818a-000b3a1db848"        # db "🎟️ Direct Q Events 🇺🇸LA28"
QUALIFICATI_DS = "5b2e1d6c-66b6-4f2d-b0d4-070bcc9ee53b"   # db "🎟️ Qualificati LA28" (destinazione)

PROP_PASS = "🎟️Pass LA28"
PROP_NOME = "Cognome e Nome"
PROP_NOC = "NOC"
PROP_SPORT = "Sport"
PROP_DISCIPLINA = "Disciplina"
PROP_CRITERIO = "Altri Criteri"
PROP_EVENTI = "🎟️ Direct Q Events LA28"
PROP_TITOLO_EVENTO = "Evento"
NOTION_VERSION = "2025-09-03"

# ---- Come si riconosce la via di qualificazione ---------------------------
# Prima conta "Altri Criteri" del db Athletes, poi il nome dell'evento collegato.
DA_CRITERIO = {
    "host country": "Host Country", "tripartite": "Universality / Tripartite",
    "universality": "Universality / Tripartite", "world ranking": "Ranking",
}
DA_EVENTO = [
    (r"q-?series|\boqs\b", "Olympic Q-Series"),
    (r"\boqt\b|\bfiqt\b|\bftqt\b|qualification (tournament|event)|qualifier", "Qualification Tournament"),
    (r"world champ|worlds\b|world surfing games", "World Championships"),
    (r"asian|african|pan ?am|european|oceania|pacific|continental|caribbean|"
     r"\bcavb\b|\bavc\b|\bcsv\b|\bcev\b|norceca|noreca|noceca|zonal", "Continental"),
    (r"ranking|pro league", "Ranking"),
    (r"world cup", "World Cup"),
]


class ErroreNotion(Exception):
    pass


# ---- Notion ----------------------------------------------------------------
def notion(token, metodo, percorso, corpo=None):
    richiesta = urllib.request.Request(
        f"https://api.notion.com/v1/{percorso}",
        data=json.dumps(corpo).encode() if corpo is not None else None, method=metodo,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    for tentativo in range(6):
        try:
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as errore:
            testo = errore.read().decode(errors="replace")
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 5:
                time.sleep(2 ** tentativo)
                continue
            raise ErroreNotion(f"{errore.code}: {testo[:300]}")
        except urllib.error.URLError as errore:
            if tentativo < 5:
                time.sleep(2 ** tentativo)
                continue
            raise ErroreNotion(str(errore))


def interroga(token, data_source, filtro=None):
    """Legge tutte le righe di un database, 100 alla volta."""
    pagine, cursore = [], None
    while True:
        corpo = {"page_size": 100}
        if filtro:
            corpo["filter"] = filtro
        if cursore:
            corpo["start_cursor"] = cursore
        risposta = notion(token, "POST", f"data_sources/{data_source}/query", corpo)
        pagine += risposta["results"]
        if not risposta.get("has_more"):
            return pagine
        cursore = risposta["next_cursor"]


def testo_di(proprieta):
    if not proprieta:
        return ""
    tipo = proprieta["type"]
    if tipo in ("title", "rich_text"):
        return "".join(t["plain_text"] for t in proprieta[tipo])
    if tipo == "select":
        return (proprieta["select"] or {}).get("name", "")
    if tipo in ("url", "number", "checkbox"):
        return proprieta[tipo]
    if tipo == "relation":
        return [r["id"] for r in proprieta["relation"]]
    if tipo == "multi_select":
        return [v["name"] for v in proprieta["multi_select"]]
    return ""


def leggi_athletes(token):
    try:
        pagine = interroga(token, ATHLETES_DS, {"property": PROP_PASS, "select": {"equals": "Q"}})
    except ErroreNotion as errore:
        sys.exit(f'Non riesco a leggere il db "Athletes" ({errore}).\n'
                 'Controlla che la connessione Notion sia collegata al database (••• > Connessioni).')
    righe = []
    for pagina in pagine:
        p = pagina["properties"]
        righe.append({
            "id": pagina["id"], "url": pagina["url"],
            "nome": testo_di(p.get(PROP_NOME)), "noc_grezzo": testo_di(p.get(PROP_NOC)),
            "sport": testo_di(p.get(PROP_SPORT)), "discipline": testo_di(p.get(PROP_DISCIPLINA)) or [],
            "criterio": testo_di(p.get(PROP_CRITERIO)), "eventi": testo_di(p.get(PROP_EVENTI)) or [],
        })
    return righe


def leggi_eventi(token, avvisi):
    try:
        pagine = interroga(token, EVENTI_DS)
    except ErroreNotion as errore:
        avvisi.append('Non riesco a leggere il db "Direct Q Events" '
                      f"({errore}): collega la connessione anche a quel database. Proseguo senza eventi.")
        return {}
    eventi = {}
    for pagina in pagine:
        titolo = ""
        for proprieta in pagina["properties"].values():
            if proprieta["type"] == "title":
                titolo = testo_di(proprieta)
        eventi[pagina["id"]] = titolo.strip()
    return eventi


# ---- Elaborazione ------------------------------------------------------------
def senza_trattini(identificativo):
    return identificativo.replace("-", "")


def via_di_qualificazione(criterio, titoli_eventi):
    criterio = re.sub(r"^[^A-Za-z]+", "", criterio or "").lower()
    if criterio in DA_CRITERIO:
        return DA_CRITERIO[criterio]
    testo = " ".join(titoli_eventi).lower()
    if testo:
        for schema, via in DA_EVENTO:
            if re.search(schema, testo):
                return via
        return "Other event"
    return "Not specified"


def bandiera(noc_grezzo):
    """'🇮🇹ITA' -> '🇮🇹'."""
    return re.sub(r"[A-Z]{2,3}$", "", noc_grezzo or "").strip()


def pulisci_gara(gara):
    return re.sub(r"^[^A-Za-z0-9]+", "", gara).strip()


def nomi_paesi():
    mondo = json.loads((CARTELLA / "mondo.json").read_text(encoding="utf-8"))
    nomi = {}
    for geometria in mondo["objects"]["countries"]["geometries"]:
        noc, nome = geometria["properties"].get("noc"), geometria["properties"]["nome"]
        if noc and (noc not in nomi or len(nome) < len(nomi[noc])):
            nomi[noc] = nome
    return nomi


def elabora(righe, eventi, avvisi):
    paesi = nomi_paesi()
    pulite, viste = [], set()
    for riga in righe:
        if riga["id"] in viste:
            continue
        viste.add(riga["id"])
        noc = base.codice_noc(riga["noc_grezzo"])
        noc = base.ACCORPA.get(noc, noc)
        if not noc:
            avvisi.append(f"Riga senza NOC, esclusa: {riga['nome']}")
            continue
        nuova = dict(riga, nome=base.pulisci_nome(riga["nome"]), noc=noc)
        nuova["atleti"], nuova["squadra"] = base.atleti_della_riga(nuova, avvisi)
        pulite.append(nuova)
    base.correggi_arco(pulite)       # gli arcieri già compresi nella squadra non contano doppio

    uscita = []
    for riga in pulite:
        titoli = [eventi[i] for i in riga["eventi"] if eventi.get(i)]
        via = via_di_qualificazione(riga["criterio"], titoli)
        squadra = riga["squadra"] or riga["sport"] in quote.SPORT_DI_SQUADRA
        tipo, regola, url, verifica = quote.tipo_di_quota(riga["sport"], via, squadra)
        url = quote.documento_per_gara(url, riga["discipline"])
        if riga["sport"] not in quote.REGOLE and riga["sport"] not in quote.SPORT_DI_SQUADRA:
            avvisi.append(f"Sport senza regola in quote_la28.py: {riga['sport']} ({riga['nome']})")
        uscita.append({
            "chiave": senza_trattini(riga["id"]),
            "nome": riga["nome"], "noc": riga["noc"], "bandiera": bandiera(riga["noc_grezzo"]),
            "paese": paesi.get(riga["noc"], riga["noc"]),
            "sport": riga["sport"] or "—",
            "gare": [pulisci_gara(g) for g in riga["discipline"]],
            "tipo": tipo, "via": via, "evento": " · ".join(titoli),
            "posti": riga["atleti"], "nota": riga.get("nota", ""),
            "regola": regola, "documento": url, "verifica": verifica,
            "notion": riga["url"],
        })
    uscita.sort(key=lambda r: (r["sport"], " ".join(r["gare"]), r["noc"], r["nome"]))
    return uscita


def riepilogo(righe, adesso):
    posti = sum(r["posti"] for r in righe)
    conta = lambda tipo: sum(1 for r in righe if r["tipo"] == tipo)
    return {
        "aggiornato": adesso,
        "totali": {
            "posti_qualificati": posti, "noc": len({r["noc"] for r in righe}),
            "rimanenti": base.POSTI_TOTALI_LA28 - posti, "posti_totali": base.POSTI_TOTALI_LA28,
            "righe": len(righe), "athlete_quota": conta("Athlete Quota"),
            "noc_quota": conta("NOC Quota"), "team_quota": conta("Team Quota"),
        },
        "fonte_regole": quote.URL_PAGINA_CIO,
        "righe": righe,
    }


# ---- Scrittura su Notion ---------------------------------------------------------
def proprieta_notion(r):
    testo = lambda s: {"rich_text": [{"text": {"content": s[:1900]}}] if s else []}
    seleziona = lambda s: {"select": {"name": s.replace(",", " ")} if s else None}
    return {
        "Atleta / Squadra": {"title": [{"text": {"content": r["nome"][:1900]}}]},
        "NOC": seleziona(r["noc"]),
        "Paese": testo(r["paese"]),
        "Sport": seleziona(r["sport"]),
        "Gara": testo(" · ".join(r["gare"])),
        "Tipo di quota": seleziona(r["tipo"]),
        "Via di qualificazione": seleziona(r["via"]),
        "Evento": testo(r["evento"]),
        "Posti": {"number": r["posti"]},
        "Regola CIO": testo(r["regola"] + (f" ({r['nota']})" if r["nota"] else "")),
        "Sistema di qualificazione": {"url": r["documento"]},
        "Da verificare": {"checkbox": bool(r["verifica"])},
        "Athletes": {"relation": [{"id": r["chiave"]}]},
        "Chiave": testo(r["chiave"]),
    }


def impronta_da_proprieta(props):
    """Riduce le proprietà a valori semplici per capire se una riga è cambiata."""
    impronta = {}
    for nome, valore in props.items():
        if "title" in valore:
            impronta[nome] = "".join(t["text"]["content"] for t in valore["title"])
        elif "rich_text" in valore:
            impronta[nome] = "".join(t["text"]["content"] for t in valore["rich_text"])
        elif "select" in valore:
            impronta[nome] = (valore["select"] or {}).get("name", "")
        elif "relation" in valore:
            impronta[nome] = sorted(senza_trattini(x["id"]) for x in valore["relation"])
        else:
            impronta[nome] = next(iter(valore.values()))
    return impronta


def impronta_da_pagina(pagina, nomi):
    impronta = {}
    for nome in nomi:
        valore = testo_di(pagina["properties"].get(nome))
        if isinstance(valore, list):
            valore = sorted(senza_trattini(x) for x in valore)
        impronta[nome] = valore
    return impronta


def sincronizza_notion(token, righe):
    esistenti = {}
    for pagina in interroga(token, QUALIFICATI_DS):
        chiave = testo_di(pagina["properties"].get("Chiave"))
        if chiave in esistenti:                  # doppione: lo tolgo
            notion(token, "PATCH", f"pages/{pagina['id']}", {"in_trash": True})
            continue
        esistenti[chiave] = pagina
    nuove = aggiornate = tolte = 0
    for r in righe:
        props = proprieta_notion(r)
        pagina = esistenti.pop(r["chiave"], None)
        if pagina is None:
            notion(token, "POST", "pages", {
                "parent": {"type": "data_source_id", "data_source_id": QUALIFICATI_DS},
                "properties": props})
            nuove += 1
        elif impronta_da_pagina(pagina, props) != impronta_da_proprieta(props):
            notion(token, "PATCH", f"pages/{pagina['id']}", {"properties": props})
            aggiornate += 1
        else:
            continue
        time.sleep(0.35)                         # Notion accetta circa 3 richieste al secondo
    for pagina in esistenti.values():            # righe che non hanno più la Q
        notion(token, "PATCH", f"pages/{pagina['id']}", {"in_trash": True})
        tolte += 1
        time.sleep(0.35)
    return nuove, aggiornate, tolte


# ---- Avvio -----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prova", action="store_true", help="non scrive su Notion")
    parser.add_argument("--da-file", help="file JSON con 'athletes' ed 'eventi' (per i test)")
    args = parser.parse_args()
    avvisi = []
    token = None
    if args.da_file:
        dati = json.loads(Path(args.da_file).read_text(encoding="utf-8"))
        righe, eventi = dati["athletes"], dati["eventi"]
    else:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            sys.exit("Manca NOTION_TOKEN.")
        righe = leggi_athletes(token)
        eventi = leggi_eventi(token, avvisi)
    if not righe:
        sys.exit("Nessuna riga con Q: qualificati.json non è stato toccato.")

    elaborate = elabora(righe, eventi, avvisi)
    adesso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    dati = riepilogo(elaborate, adesso)
    (CARTELLA / "qualificati.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    t = dati["totali"]
    print(f"{t['righe']} qualificati, {t['posti_qualificati']} posti, {t['noc']} NOC "
          f"(Athlete {t['athlete_quota']}, NOC {t['noc_quota']}, Team {t['team_quota']})")

    if token and not args.prova:
        try:
            nuove, aggiornate, tolte = sincronizza_notion(token, elaborate)
        except ErroreNotion as errore:
            sys.exit(f'Errore scrivendo sul db "🎟️ Qualificati LA28": {errore}\n'
                     "Controlla che la connessione sia collegata alla pagina ⚙️ Agenti.")
        print(f"Notion: {nuove} nuove, {aggiornate} aggiornate, {tolte} nel cestino")
    for avviso in avvisi:
        print("AVVISO:", avviso)


if __name__ == "__main__":
    main()
