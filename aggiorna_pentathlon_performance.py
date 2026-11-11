#!/usr/bin/env python3
"""Pagina Performance Pentathlon Moderno: legge da Notion i pentatleti del db Athletes
(Sport = "Modern Pentathlon") e i loro risultati nei db "Risultati A" (MASTER RESULTS) e
"Risultati B" (MASTER MINOR), ricava l'indice PTS di ogni risultato e scrive
pentathlon-performance.json, che userà la pagina pentathlon-performance.html.

Come si ottiene il PTS di ogni riga:
1. lo script legge il valore della formula PTS direttamente dall'API di Notion;
2. legge anche "Punti Base" (un'altra formula) e rifà il conto di PTS con le stesse formule
   di Notion (sezione FORMULA PTS qui sotto);
3. usa il valore di Notion; se manca, usa quello ricalcolato. Se i due valori non coincidono
   lo segnala nel log con un AVVISO: vuol dire che la formula qui sotto e quella di Notion
   sono diverse. Se cambi la formula PTS in Notion, cambia anche la sezione FORMULA PTS.

Differenze rispetto al judo (aggiorna_judo_performance.py):
- indice PTS invece del WON (nel pentathlon il 🏟️ Rating è vuoto);
- niente categorie di peso: solo Uomini e Donne;
- di ogni evento contano solo i primi 8 classificati, sia in Risultati A sia in Risultati B;
- la colonna Sport dei db Risultati è vuota per il pentathlon: le righe vengono trovate
  con la Disciplina e tenute solo se l'atleta collegato è un pentatleta del db Athletes.

Le funzioni comuni (lettura da Notion, conversione dei valori, piazzamento) sono prese da
aggiorna_judo_performance.py, che deve stare nella stessa cartella.

Uso:
  NOTION_TOKEN=... python aggiorna_pentathlon_performance.py
  NOTION_TOKEN=... python aggiorna_pentathlon_performance.py --salva-raw raw.json   salva anche i dati letti
  python aggiorna_pentathlon_performance.py --da-raw raw.json                       prova con dati salvati

Non servono librerie da installare.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARTELLA))      # trova aggiorna_judo_performance.py nella stessa cartella
from aggiorna_judo_performance import (DB_ATHLETES, DB_RISULTATI, NON_PRESENTATI,  # noqa: E402
                                       NOTION_VERSION, interroga, piazzamento, valore)

# ---------------------------------------------------------------- IMPOSTAZIONI
SPORT = "Modern Pentathlon"                   # valore esatto di Sport nel db Athletes
# nome della Disciplina in Notion -> genere usato dalla pagina (U = uomini, D = donne)
DISCIPLINE = {"Men's Modern Pentathlon": "U", "Women's Modern Pentathlon": "D"}
CAMPO_INDICE = "PTS"                          # nome esatto della formula nei db Risultati A e B
CAMPO_BASE = "Punti Base"                     # nome esatto della formula da cui parte PTS
MAX_POSTO = 8                                 # di ogni evento contano solo i primi 8
TOLLERANZA = 0.05                             # differenza massima accettata tra Notion e ricalcolo
FILE_JSON = "pentathlon-performance.json"


# ---------------------------------------------------------------- FORMULA PTS
# Trascrizione delle formule PTS di Notion (testo fornito da Gualtiero l'11/11/2026).
# In Notion contains(Evento, "x") vuol dire "il nome dell'evento contiene x" (maiuscole
# comprese): in Python si scrive "x" in evento.

def arrotonda_1(x):
    """Come round(x * 10) / 10 di Notion: arrotonda a 1 decimale, con il 5 verso l'alto.
    (round() di Python arrotonda il 5 al numero pari, per questo non si usa.)"""
    return math.floor(x * 10 + 0.5) / 10


def peso_anno_A(anno):
    """Risultati A: progressione degli anni."""
    if anno is None:
        return 0.2
    if anno >= 2028:
        return 1.2
    return {2027: 1.0, 2026: 0.8, 2025: 0.6, 2024: 0.4}.get(int(anno), 0.2)   # anni precedenti: 0.2


def molt_A(evento):
    """Risultati A: scala assoluta delle competizioni (l'ordine dei controlli conta)."""
    ev = evento or ""
    if "Dakar2026" in ev:
        return 0.225                          # Dakar (25%)
    if "U23" in ev and "🌐" in ev:
        return 0.675                          # Mondiale U23
    if "U23" in ev:
        return 0.45                           # U23 normale
    if "🌐" in ev:
        return 0.90                           # Mondiale assoluto
    continentali = ["Euro", "Asian", "Ame", "PanAm", "Americas", "🇪🇺", "Africa", "Afr", "Oceania", "Oce"]
    if any(k in ev for k in continentali):
        return 0.675                          # Continentali
    return 0.54                               # tutto il resto


def peso_anno_B(anno):
    """Risultati B: (Anno - 2022) * 0.2 -> 2024=0.4 | 2025=0.6 | 2026=0.8 | 2027=1.0 | 2028=1.2"""
    if anno is None:
        return None                           # [DA VERIFICARE] cosa fa Notion con Anno vuoto
    return (anno - 2022) * 0.2


def molt_B(evento):
    """Risultati B: moltiplicatori dimezzati rispetto ad A."""
    ev = evento or ""
    if "Dakar2026" in ev:
        return 0.12
    if "U23" in ev:
        return 0.25
    regionali = ["Euro", "Asian", "Ame", "Pan Am", "Americas", "🇪🇺"]
    if any(k in ev for k in regionali):
        return 0.37                           # coppe continentali o open minori
    return 0.30                               # tappe di Coppa del Mondo standard


def bonus_B(evento):
    return 1.5 if "🌐" in (evento or "") else 1


def pts_calcolato(r):
    """Rifà il PTS di una riga partendo da Punti Base. None se Punti Base manca."""
    base = r.get("base")
    if base is None:
        return None
    if r["db"] == "A":
        return arrotonda_1(base * peso_anno_A(r["anno"]) * molt_A(r["ev"]))
    peso = peso_anno_B(r["anno"])
    if peso is None:
        return None
    return arrotonda_1(base * peso * molt_B(r["ev"]) * bonus_B(r["ev"]))


# ---------------------------------------------------------------- LETTURA DELLE FORMULE
# L'API di Notion restituisce il risultato delle formule dentro la pagina, così:
#   "PTS": {"id": "WG1IPA", "type": "formula", "formula": {"type": "number", "number": 37.5}}
# Se la formula dipende da troppe pagine collegate, il risultato può arrivare vuoto
# ("unsupported" o null): in quel caso si chiede la singola proprietà con un'altra chiamata
# (GET /pages/{pagina}/properties/{proprietà}), che restituisce il valore completo.

def numero_da_formula(f):
    """Dal blocco "formula" di Notion ricava un numero (o None se non c'è)."""
    if not f:
        return None
    tipo = f.get("type")
    v = f.get(tipo) if tipo else None
    if isinstance(v, bool):                   # un sì/no non è un punteggio
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):                    # formula che restituisce testo, es. "37,5"
        try:
            return float(v.replace(",", ".").strip())
        except ValueError:
            return None
    return None


def chiama_get(percorso):
    """Chiamata GET all'API di Notion, con gli stessi tentativi di chiama() del judo."""
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("Manca NOTION_TOKEN.")
    richiesta = urllib.request.Request(
        f"https://api.notion.com/v1/{percorso}", method="GET",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION})
    for tentativo in range(5):
        try:
            with urllib.request.urlopen(richiesta, timeout=90) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as errore:
            if errore.code in (429, 500, 502, 503, 504) and tentativo < 4:
                time.sleep(2 ** tentativo)    # attende 1, 2, 4, 8 secondi e riprova
                continue
            print(f"AVVISO lettura di {percorso} non riuscita: errore {errore.code}")
            return None
    return None


def formula_riga(pg, nome):
    """Restituisce il valore numerico della formula `nome` di una riga, oppure None."""
    p = pg["properties"].get(nome)
    if p is None:
        sys.exit(f'Nel db dei risultati non esiste la proprietà "{nome}": '
                 f'controlla il nome esatto in Notion.')
    v = numero_da_formula(p.get("formula"))
    if v is not None:
        return v
    # secondo tentativo: la proprietà da sola (serve per le formule con molti collegamenti)
    item = chiama_get(f"pages/{pg['id']}/properties/{p['id']}")
    if item and item.get("type") == "formula":
        return numero_da_formula(item.get("formula"))
    return None


# ---------------------------------------------------------------- NOTION
def leggi_notion():
    # 1) i pentatleti del db Athletes: da qui parte tutto
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": SPORT}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} pentatleti")

    # 2) le righe di pentathlon nei db Risultati A e B. Non si filtra su Sport (è vuoto):
    #    si filtra sulle due Discipline, poi in aggrega() si tengono solo gli atleti del punto 1
    filtro = {"or": [{"property": "Disciplina", "select": {"equals": d}} for d in DISCIPLINE]}
    res = []
    for sigla, db in DB_RISULTATI.items():
        pagine = interroga(db, filtro)
        for pg in pagine:
            p = pg["properties"]
            res.append({"db": sigla, "ids": valore(p.get("Athlete")) or [], "ev": valore(p.get("Evento")) or "",
                        "anno": valore(p.get("Anno")), "mese": valore(p.get("Mese")),
                        "result": valore(p.get("Result")) or "",
                        "pts_notion": formula_riga(pg, CAMPO_INDICE),   # PTS calcolato da Notion
                        "base": formula_riga(pg, CAMPO_BASE),           # Punti Base, per il ricalcolo
                        "disc": valore(p.get("Disciplina")) or "", "cat": valore(p.get("CAT")) or ""})
        print(f"Risultati {sigla}: {len(pagine)} righe di pentathlon")
    return ath, res


# ---------------------------------------------------------------- SCELTA DEL PTS
def scegli_pts(res):
    """Per ogni riga decide il PTS da usare (r["pts"]) e confronta Notion con il ricalcolo."""
    da_notion = calcolati = mancanti = 0
    diversi = []
    for r in res:
        notion = r.get("pts_notion", r.get("pts"))     # "pts": vecchi file di prova
        calc = pts_calcolato(r)
        if notion is not None:
            r["pts"] = notion
            da_notion += 1
            if calc is not None and abs(notion - calc) > TOLLERANZA:
                diversi.append(r)
        elif calc is not None:
            r["pts"] = calc
            calcolati += 1
        else:
            r["pts"] = None
            mancanti += 1
    print(f"PTS letti da Notion: {da_notion} · ricalcolati dallo script: {calcolati} · "
          f"senza valore: {mancanti} (su {len(res)} righe)")
    if diversi:
        print(f"AVVISO {len(diversi)} righe con PTS di Notion diverso dal ricalcolo: "
              f"la sezione FORMULA PTS va controllata. Primi esempi:")
        for r in diversi[:5]:
            print(f"  {r['db']} · {r['ev']} · {r['disc']} · posto {r['result']}: "
                  f"Notion {r['pts']} · ricalcolo {pts_calcolato(r)} · Punti Base {r['base']}")
    if res and da_notion + calcolati == 0:
        print("AVVISO nessun PTS disponibile né da Notion né dal ricalcolo: "
              "serve il testo della formula Punti Base.")


# ---------------------------------------------------------------- AGGREGAZIONE
def aggrega(ath, res, oggi):
    scarti = {"Youth": 0, "senza evento": 0, "non presentati": 0, f"oltre l'{MAX_POSTO}° posto": 0,
              "piazzamento non numerico": 0, "atleta non pentatleta": 0}
    gruppi = {}
    for r in res:
        if r["cat"] == "Youth":                       # la pagina è solo senior
            scarti["Youth"] += 1
            continue
        if not r["ev"]:                               # riga senza torneo: non è una gara
            scarti["senza evento"] += 1
            continue
        if (r["result"] or "").strip().lower() in NON_PRESENTATI:   # non ha gareggiato
            scarti["non presentati"] += 1
            continue
        posto = piazzamento(r["result"])              # "1" -> 1.0, testo non numerico -> None
        if posto is None:
            scarti["piazzamento non numerico"] += 1
            continue
        if posto > MAX_POSTO:                         # regola: solo i primi 8 di ogni evento
            scarti[f"oltre l'{MAX_POSTO}° posto"] += 1
            continue
        tenuta = False
        for i in r["ids"]:
            if i in ath:                              # l'atleta collegato è un pentatleta di Athletes
                gruppi.setdefault(i, []).append(r)
                tenuta = True
        if not tenuta:
            scarti["atleta non pentatleta"] += 1

    atleti, senza_pts = [], {}
    for i, righe in gruppi.items():
        info = ath[i]
        righe.sort(key=lambda r: (r["anno"] or 0, r["mese"] or 0))          # dalla più vecchia
        genere = DISCIPLINE.get(righe[-1]["disc"])                         # genere dell'ultimo risultato
        if not genere:
            genere = next((DISCIPLINE[d] for d in info["disc"] if d in DISCIPLINE), None)
        if not genere:
            continue
        for r in righe:
            if r["pts"] is None:
                senza_pts[r["ev"]] = senza_pts.get(r["ev"], 0) + 1
        punti = [r["pts"] or 0 for r in righe]       # PTS mancante = 0 punti
        posti = [piazzamento(r["result"]) for r in righe]
        eta = None
        if info["dob"]:
            d = datetime.date.fromisoformat(info["dob"][:10])
            eta = oggi.year - d.year - ((oggi.month, oggi.day) < (d.month, d.day))
        m = re.match(r"^(\W*?)([A-Z]{3})$", (info["noc"] or "").strip())   # "🇮🇹ITA" -> "🇮🇹" + "ITA"
        totale = round(sum(punti), 2)
        atleti.append({
            "id": i, "nome": re.sub(r"\s+", " ", info["nome"]).strip(),
            "flag": m.group(1) if m else "", "noc": m.group(2) if m else (info["noc"] or "—"),
            "genere": genere,
            "pts": totale, "gare": len(righe),
            "pts_medio": round(totale / len(righe), 2),
            "ori": posti.count(1), "arg": posti.count(2), "bro": posti.count(3),
            "piazz": round(statistics.mean(posti), 1),
            "q": info["pas"] == "Q", "hon": info["hon"], "eta": eta,
            # storia: [evento, anno, mese, piazzamento, PTS, db]
            "storia": [[r["ev"], int(r["anno"] or 0), int(r["mese"] or 0), (r["result"] or "").strip(),
                        round(p, 2), r["db"]] for r, p in zip(righe, punti)]})
    atleti.sort(key=lambda a: -a["pts"])

    for motivo, n in scarti.items():
        if n:
            print(f"Escluse {n} righe: {motivo}")
    for ev, n in sorted(senza_pts.items()):
        print(f"AVVISO {n} risultati di «{ev}» senza valore PTS: valgono 0 punti")
    eventi = sorted({r[0] for a in atleti for r in a["storia"]})
    return {"aggiornato": oggi.isoformat(), "indice": CAMPO_INDICE, "max_posto": MAX_POSTO,
            "atleti": atleti, "eventi": eventi, "n_risultati": sum(a["gare"] for a in atleti)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-raw", help="file con {ath, res} salvati, per le prove senza Notion")
    ap.add_argument("--salva-raw", help="salva in questo file i dati letti da Notion")
    args = ap.parse_args()
    if args.da_raw:
        raw = json.load(open(args.da_raw, encoding="utf-8"))
        ath, res = raw["ath"], raw["res"]
    else:
        ath, res = leggi_notion()
        if args.salva_raw:
            Path(args.salva_raw).write_text(json.dumps({"ath": ath, "res": res}, ensure_ascii=False),
                                            encoding="utf-8")
    scegli_pts(res)
    oggi = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date()
    dati = aggrega(ath, res, oggi)
    (CARTELLA / FILE_JSON).write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{FILE_JSON}: {len(dati['atleti'])} atleti, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} eventi")
    for g, etichetta in (("U", "Uomini"), ("D", "Donne")):
        primo = next((a for a in dati["atleti"] if a["genere"] == g), None)
        if primo:
            print(f"  {etichetta}, primo per PTS: {primo['nome']} ({primo['noc']}) {primo['pts']}")


if __name__ == "__main__":
    main()
