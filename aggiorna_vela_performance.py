#!/usr/bin/env python3
"""Pagina Performance Vela (scheda 39, ELO vela sessione 3) – repo map-q-la28 · versione 1.0 del 19/11/2026

Che cosa fa
-----------
1. Legge da Notion i risultati di vela dei db "Risultati A" (MASTER RESULTS: Mondiali ed Europei di
   classe) e "Risultati B" (MASTER MINOR: Sailing Grand Slam, iQFOiL Games...) e gli atleti ed equipaggi
   di vela del db Athletes (Sport = Sailing).
2. Ricalcola l'indice WON 🔺 con le STESSE formule di Notion: le prende da aggiorna_judo_performance.py
   (stessa cartella), come fa la pagina badminton. Se cambi la formula WON, la correggi lì una volta sola.
3. Aggiunge l'ELO di vela-elo.json (salvato dal workflow "ELO Vela"): il collegamento passa dal campo
   "notion" di vela-elo.json, che è l'id della pagina di Athletes, cioè lo stesso "id" usato qui.
   Se vela-elo.json manca o non si legge, la pagina funziona lo stesso, senza ELO.
4. Scrive vela-performance.json, letto dalla pagina vela-performance.html.

Le 10 classi sono le "specialità" della pagina. Negli equipaggi (49er, 49er FX, 470, Nacra 17) la barca
è una sola pagina di Athletes ("Timoniere/Prodiere"), quindi viene trattata come un unico "atleta".
Solo categoria senior: le righe U23, U21, U19 e Youth sono escluse (foglio ELO vela, punti 12-14).

Uso:
  NOTION_TOKEN=... python aggiorna_vela_performance.py
  python aggiorna_vela_performance.py --da-raw raw.json    prova con dati salvati {ath, res}

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

# nome della Disciplina in Notion -> sigla usata dalla pagina. Nei Risultati A l'ILCA 6 è scritto anche
# "ILCA6" senza spazio (scheda 34, caso 2): le due forme valgono come la stessa classe.
SPECIALITA = {"Men's Laser ILCA 7": "ILCA7", "Women's Laser Radial ILCA 6": "ILCA6",
              "Women's Laser Radial ILCA6": "ILCA6", "Men's iQFOIL": "IQM", "Women's iQFOIL": "IQW",
              "Men's 49er": "49ER", "Women's 49er FX": "49FX", "Mixed 470": "470", "Nacra 17": "N17",
              "Men's Kite": "KITEM", "Women's Kite": "KITEW"}
EQUIPAGGI = {"49ER", "49FX", "470", "N17"}
CATEGORIE_ESCLUSE = {"youth", "u23", "u21", "u19", "u17", "junior", "master"}   # la pagina è solo senior

# ---------------------------------------------------------------- ELO
FILE_ELO = CARTELLA / "vela-elo.json"   # prodotto da elo_vela.py nello stesso repository
TOP_ELO = 10                            # quanti nella "Classifica ELO · top 10" di ogni classe


# ---------------------------------------------------------------- NOTION
def leggi_notion():
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": "Sailing"}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or []}
    print(f"Athletes: {len(ath)} atleti ed equipaggi di vela")
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
        print(f"Risultati {sigla}: {len(pagine)} righe nelle classi olimpiche di vela")
    return ath, res


def bandiera_e_noc(noc_notion):
    """'🇮🇹ITA' (valore di Athletes) -> ('🇮🇹', 'ITA'). Se il formato non torna: ('', valore così com'è)."""
    m = re.match(r"^(\W*?)([A-Z]{3})$", (noc_notion or "").strip())
    return (m.group(1), m.group(2)) if m else ("", noc_notion or "—")


def nome_pulito(nome):
    """Spazi doppi tolti e ' / ' -> '/' (formato degli equipaggi in Athletes)."""
    return re.sub(r"\s+", " ", nome or "").replace(" / ", "/").strip()


# ---------------------------------------------------------------- AGGREGAZIONE (WON)
def aggrega(ath, res, oggi):
    gruppi = {}
    for r in res:
        if (r["cat"] or "").strip().lower() in CATEGORIE_ESCLUSE:   # solo senior
            continue
        if not r["ev"]:                   # righe senza regata: non sono gare
            continue
        if (r["result"] or "").strip().lower() in NON_PRESENTATI:   # non ha regatato: non conta
            continue
        for i in r["ids"]:
            if i in ath:                  # tiene solo atleti ed equipaggi di vela
                gruppi.setdefault(i, []).append(r)
    atleti, senza_rating = [], {}
    for i, righe in gruppi.items():
        info = ath[i]
        righe.sort(key=lambda r: (r["anno"] or 0, r["mese"] or 0))
        spec = SPECIALITA.get(righe[-1]["disc"])           # classe dell'ultimo risultato
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
        flag, noc = bandiera_e_noc(info["noc"])
        atleti.append({
            "id": i, "nome": nome_pulito(info["nome"]), "flag": flag, "noc": noc,
            "spec": spec, "coppia": spec in EQUIPAGGI,      # "coppia" = equipaggio (stesso nome dei campi del badminton)
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
def sigla_classe(classe_elo):
    """Classe di vela-elo.json (es. "Men's Kite") -> sigla della pagina (es. "KITEM")."""
    return SPECIALITA.get(classe_elo)


def dati_elo_atleta(e):
    """Dati ELO di una barca per la pagina, in formato compatto.

    liv = livello ("stabile", "provvisorio", "nascosto"); n = regate (eventi).
    Solo se il livello non è "nascosto": v = ELO, max = ELO massimo, vit = vittorie, podi = podi,
    mp = miglior piazzamento, ult = data dell'ultima regata,
    st = storico [[data, ELO dopo la regata, codice evento, posizione, barche in classifica], ...].
    """
    out = {"liv": e.get("livello"), "n": e.get("eventi", 0)}
    if e.get("livello") in ("stabile", "provvisorio"):
        out.update(v=e.get("elo"), max=e.get("elo_max"), vit=e.get("vittorie"), podi=e.get("podi"),
                   mp=e.get("miglior_pos"), ult=e.get("ultimo"), st=e.get("storico") or [])
    return out


def aggiungi_elo(dati, ath):
    """Aggiunge a vela-performance.json l'ELO di vela-elo.json.

    - a ogni atleta o equipaggio della classifica WON collegato all'ELO aggiunge il campo "elo";
      se la classe dell'ELO è diversa da quella della classifica WON (caso raro), la scrive nel campo
      "spec" dell'ELO, così la pagina la mostra accanto al numero;
    - in dati["elo"] mette la data dell'ELO, le regole, i nomi delle regate dello storico e la top 10
      ELO di ognuna delle 10 classi (anche chi non ha punti WON o non è in Athletes).
    """
    if not FILE_ELO.exists():
        print("AVVISO vela-elo.json non trovato: la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return
    try:
        raw = json.loads(FILE_ELO.read_text(encoding="utf-8"))
        elenco = raw["barche"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"AVVISO vela-elo.json non leggibile ({e}): la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return

    # 1. collegamento con la classifica WON: "notion" (ELO) = "id" (WON) = id della pagina di Athletes
    per_pagina = {e["notion"]: e for e in elenco if e.get("notion")}
    eventi_usati, collegati, mostrati = set(), 0, 0
    for a in dati["atleti"]:
        e = per_pagina.get(a["id"])
        if not e:
            continue                      # nessuna regata nel db Agente Vela (o pagina non abbinata)
        a["elo"] = dati_elo_atleta(e)
        if sigla_classe(e.get("classe")) != a["spec"]:
            a["elo"]["spec"] = sigla_classe(e.get("classe")) or e.get("classe")
        collegati += 1
        if "v" in a["elo"]:
            mostrati += 1
            eventi_usati.update(str(p[2]) for p in a["elo"]["st"])

    # 2. top 10 ELO di ognuna delle 10 classi: solo ELO mostrabili
    per_spec = {}
    for e in elenco:
        if e.get("livello") in ("stabile", "provvisorio"):
            per_spec.setdefault(sigla_classe(e.get("classe")), []).append(e)
    top = {}
    for spec, lista in per_spec.items():
        if not spec:
            continue
        lista.sort(key=lambda e: -e["elo"])
        righe = []
        for e in lista[:TOP_ELO]:
            info = ath.get(e.get("notion") or "")
            if info:                      # nome e bandiera come in Athletes
                flag, noc = bandiera_e_noc(info["noc"])
                nome = nome_pulito(info["nome"])
                if noc == "—":            # NOC vuoto in Athletes: uso quello delle classifiche
                    noc = e.get("noc") or "—"
            else:                         # non ancora in Athletes: nomi delle classifiche
                flag, noc = "", e.get("noc") or "—"
                nome = nome_pulito(e.get("nome", ""))
            righe.append({"id": e.get("notion"), "nome": nome, "flag": flag, "noc": noc,
                          "v": e["elo"], "liv": e["livello"], "n": e.get("eventi", 0)})
            eventi_usati.update(str(p[2]) for p in (e.get("storico") or []))
        top[spec] = righe

    nomi_eventi = {}
    for ev in raw.get("eventi") or []:
        nomi_eventi.setdefault(str(ev.get("id")), ev.get("nome", ""))
    dati["elo"] = {
        "aggiornato": raw.get("aggiornato"),
        "barche": len(elenco),
        "mostrati": sum(1 for e in elenco if e.get("livello") in ("stabile", "provvisorio")),
        "regole": raw.get("regole") or {},
        "eventi": {cid: nomi_eventi.get(cid, "") for cid in sorted(eventi_usati)},
        "top": top,
    }
    print(f"ELO (vela-elo.json del {raw.get('aggiornato')}): {collegati} atleti/equipaggi della classifica "
          f"WON collegati, {mostrati} con ELO mostrato; top {TOP_ELO} ELO in {len(top)} classi")


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
    (CARTELLA / "vela-performance.json").write_text(
        json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"vela-performance.json: {len(dati['atleti'])} atleti/equipaggi, {dati['n_risultati']} risultati, "
          f"{len(dati['eventi'])} regate")
    for sigla in dict.fromkeys(SPECIALITA.values()):
        primo = next((a for a in dati["atleti"] if a["spec"] == sigla), None)
        if primo:
            print(f"  {sigla} primo per WON: {primo['nome']} ({primo['noc']}) {primo['won']}")


if __name__ == "__main__":
    main()
