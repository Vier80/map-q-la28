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

NOVITÀ del 17/11/2026 (scheda 33, ELO badminton sessione 3): ELO
Se nella cartella c'è badminton-elo.json (lo salva il workflow "ELO Badminton" ogni lunedì), lo
script aggiunge a badminton-performance.json l'ELO di ogni atleta o coppia. Il collegamento passa
dal campo "notion" di badminton-elo.json, che è l'id della pagina di Athletes, cioè lo stesso "id"
usato qui. Se badminton-elo.json manca o non si legge, la pagina funziona lo stesso, senza ELO.

NOVITÀ del 25/11/2026 (scheda 14): INCONTRI BWF
Se nella cartella c'è badminton.json (lo salva ogni mattina l'agente badminton, con gli incontri
del db Notion «🏸 Agente Badminton»), lo script aggiunge a badminton-performance.json la sezione
"bwf": tutti gli incontri (ognuno una volta sola) e tutti i giocatori e le coppie che li hanno
giocati, anche quelli che non sono ancora in Athletes. Così la pagina mostra nella scheda gli
incontri vinti e persi, e la ricerca trova anche chi c'è solo nei tornei BWF. Il collegamento con
la classifica WON passa dal codice BWF: «ID BWF» di Athletes oppure, se vuoto, «id_bwf» di
badminton-elo.json. Il codice di ogni incontro si ricava dai tabelloni di badminton.json
(nome → codice); per i tornei senza tabellone si usa il nome. Nessuna lettura in più da Notion.
Se badminton.json manca o non si legge, la pagina funziona lo stesso, senza elenco degli incontri.

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

# ---------------------------------------------------------------- ELO (novità del 17/11/2026)
FILE_ELO = CARTELLA / "badminton-elo.json"   # prodotto da elo_badminton.py nello stesso repository
TOP_ELO = 10                                 # quanti nella "Classifica ELO · top 10" di ogni specialità

# ---------------------------------------------------------------- INCONTRI BWF (novità del 25/11/2026)
FILE_BWF = CARTELLA / "badminton.json"       # salvato ogni mattina dall'agente badminton
# turno come scritto in Notion (colonna «Turno») -> sigla corta usata dalla pagina
SIGLA_TURNO = {"Final": "F", "Semi Final": "SF", "Quarter Final": "QF", "Round of 16": "R16",
               "Round of 32": "R32", "Round of 64": "R64", "Group Stage": "G"}
# ordine dei turni dentro lo stesso giorno: prima i gironi, ultima la finale
ORDINE_TURNO = {"G": 0, "R64": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "F": 6}


# ---------------------------------------------------------------- NOTION
def leggi_notion():
    ath = {}
    for pg in interroga(DB_ATHLETES, {"property": "Sport", "select": {"equals": "Badminton"}}):
        p = pg["properties"]
        ath[pg["id"].replace("-", "")] = {
            "nome": valore(p.get("Cognome e Nome")) or "", "noc": valore(p.get("NOC")) or "",
            "disc": valore(p.get("Disciplina")) or [], "pas": valore(p.get("🎟️Pass LA28")) or "",
            "dob": valore(p.get("DOB")) or "", "hon": valore(p.get("Honours")) or [],
            # codice BWF (scheda 32): solo lettura, serve a collegare gli incontri dell'agente
            "idbwf": valore(p.get("ID BWF")) or ""}
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


# ---------------------------------------------------------------- ELO (novità del 17/11/2026)
def dati_elo_atleta(e):
    """Dati ELO di un atleta o coppia per la pagina, nel formato compatto di badminton-performance.json.

    liv = livello ("stabile", "provvisorio", "nascosto"); n = incontri; t = tornei.
    Solo se il livello non è "nascosto": v = ELO, max = ELO massimo, vit = vittorie,
    ult = data dell'ultimo incontro, st = storico [[data, ELO dopo il torneo, codice torneo], ...].
    """
    out = {"liv": e.get("livello"), "n": e.get("incontri", 0), "t": e.get("tornei", 0)}
    if e.get("livello") in ("stabile", "provvisorio"):
        out.update(v=e.get("elo"), max=e.get("elo_max"), vit=e.get("vittorie"), ult=e.get("ultimo"),
                   st=e.get("storico") or [])
    return out


def bandiera_e_noc(noc_notion):
    """'🇮🇹ITA' (valore di Athletes) -> ('🇮🇹', 'ITA'). Se il formato non torna: ('', valore così com'è)."""
    m = re.match(r"^(\W*?)([A-Z]{3})$", (noc_notion or "").strip())
    return (m.group(1), m.group(2)) if m else ("", noc_notion or "—")


def aggiungi_elo(dati, ath):
    """Aggiunge a badminton-performance.json l'ELO di badminton-elo.json (scheda 33).

    - a ogni atleta o coppia della classifica WON collegato all'ELO aggiunge il campo "elo";
      se la specialità dell'ELO è diversa da quella della classifica WON (caso raro), la scrive
      nel campo "spec" dell'ELO, così la pagina la mostra accanto al numero;
    - in dati["elo"] mette la data dell'ELO, le regole, i nomi dei tornei dello storico e la top 10
      ELO di ognuna delle 5 specialità (anche chi non ha punti WON o non è in Athletes).
    """
    if not FILE_ELO.exists():
        print("AVVISO badminton-elo.json non trovato: la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return
    try:
        raw = json.loads(FILE_ELO.read_text(encoding="utf-8"))
        elenco = raw["atleti"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"AVVISO badminton-elo.json non leggibile ({e}): la pagina mostrerà «—» nella colonna ELO.")
        dati["elo"] = None
        return

    # 1. collegamento con la classifica WON: "notion" (ELO) = "id" (WON) = id della pagina di Athletes
    per_pagina = {e["notion"]: e for e in elenco if e.get("notion")}
    tornei_usati, collegati, mostrati = set(), 0, 0
    for a in dati["atleti"]:
        e = per_pagina.get(a["id"])
        if not e:
            continue                      # nessun incontro nei tornei BWF letti (o pagina non abbinata)
        a["elo"] = dati_elo_atleta(e)
        if e.get("spec") != a["spec"]:
            a["elo"]["spec"] = e.get("spec")   # caso raro: la pagina scrive la specialità accanto all'ELO
        collegati += 1
        if "v" in a["elo"]:
            mostrati += 1
            tornei_usati.update(str(c) for _, _, c in a["elo"]["st"])

    # 2. top 10 ELO di ognuna delle 5 specialità: solo ELO mostrabili
    per_spec = {}
    for e in elenco:
        if e.get("livello") in ("stabile", "provvisorio"):
            per_spec.setdefault(e.get("spec"), []).append(e)
    top = {}
    for spec, lista in per_spec.items():
        lista.sort(key=lambda e: -e["elo"])
        righe = []
        for e in lista[:TOP_ELO]:
            info = ath.get(e.get("notion") or "")
            if info:                      # nome e bandiera come in Athletes
                flag, noc = bandiera_e_noc(info["noc"])
                nome = re.sub(r"\s+", " ", info["nome"]).replace(" / ", "/").strip()
                if noc == "—":            # NOC vuoto in Athletes: uso quello del sito BWF
                    noc = e.get("noc") or "—"
            else:                         # non ancora in Athletes: dati del sito BWF
                flag, noc = "", e.get("noc") or "—"
                nome = re.sub(r"\s*/\s*", "/", e.get("nome", "")).strip()
            righe.append({"id": e.get("notion"), "nome": nome, "flag": flag, "noc": noc,
                          "v": e["elo"], "liv": e["livello"], "n": e.get("incontri", 0)})
        top[spec] = righe

    nomi_tornei = {str(cid): (t or {}).get("nome", "") for cid, t in (raw.get("tornei") or {}).items()}
    dati["elo"] = {
        "aggiornato": raw.get("aggiornato"),
        "giocatori": len(elenco),
        "mostrati": sum(1 for e in elenco if e.get("livello") in ("stabile", "provvisorio")),
        "regole": raw.get("regole") or {},
        "tornei": {cid: nomi_tornei.get(cid, "") for cid in sorted(tornei_usati)},
        "top": top,
    }
    print(f"ELO (badminton-elo.json del {raw.get('aggiornato')}): {collegati} atleti/coppie della classifica "
          f"WON collegati, {mostrati} con ELO mostrato; top {TOP_ELO} ELO in {len(top)} specialità")


# ---------------------------------------------------------------- INCONTRI BWF (novità del 25/11/2026)
def norma_nome(nome):
    """Nome per i confronti: spazi doppi ridotti a uno, ' / ' uniforme, maiuscolo.
    Serve perché il sito BWF a volte scrive 'CHEN Zhi  Ray' con due spazi."""
    nome = re.sub(r"\s*/\s*", " / ", nome or "")
    return re.sub(r"\s+", " ", nome).strip().upper()


def norma_codice(codice):
    """Codice BWF uniforme: per le coppie i due codici in ordine crescente, es. '89426/65267' -> '65267/89426'."""
    parti = [c.strip() for c in str(codice or "").split("/") if c.strip()]
    return "/".join(sorted(parti, key=lambda c: (len(c), c)))


def aggiungi_incontri(dati, ath):
    """Aggiunge a badminton-performance.json gli incontri dei tornei BWF letti dall'agente badminton,
    per TUTTI i giocatori e le coppie che compaiono in badminton.json, anche se non sono in Athletes.

    Ogni incontro è scritto una sola volta (non una volta per il vincitore e una per lo sconfitto):
      dati["bwf"] = {
        "aggiornato": data di badminton.json,
        "tornei":   [[nome, categoria, inizio, fine, stato], ...],
        "squadre":  [[nome, NOC, codice BWF, specialità, athletes, elo], ...]
                    un giocatore (singolari) o una coppia (doppi), con il nome come sul sito BWF;
                    athletes: 2 = nella classifica WON, 1 = in Athletes ma senza risultati WON, 0 = non in Athletes;
                    elo: [valore, livello] se l'ELO è mostrabile, altrimenti null,
        "incontri": [[indice torneo, data, turno, indice vincitore, indice sconfitto, punteggio], ...]
                    turno = F, SF, QF, R16, R32, R64, G (gironi delle Finals);
                    punteggio dal lato del vincitore, come in Notion (la pagina lo gira per le sconfitte)
      }
      a["sq"] = indice della sua squadra in dati["bwf"]["squadre"] (solo atleti e coppie collegati).
    Esclusi gli incontri «non disputato» (come nell'ELO).
    """
    dati["bwf"] = None
    if not FILE_BWF.exists():
        print("AVVISO badminton.json non trovato: la scheda non mostrerà gli incontri BWF.")
        return
    try:
        bwf = json.loads(FILE_BWF.read_text(encoding="utf-8"))
        incontri, tornei = bwf["incontri"], bwf["tornei"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"AVVISO badminton.json non leggibile ({e}): la scheda non mostrerà gli incontri BWF.")
        return
    tabelloni = bwf.get("tabelloni") or {}

    # 1. ELO (facoltativo): codice BWF delle pagine di Athletes e valore ELO di ogni scheda
    elo = []
    if FILE_ELO.exists():
        try:
            elo = json.loads(FILE_ELO.read_text(encoding="utf-8")).get("atleti", []) or []
        except (OSError, ValueError, TypeError, AttributeError):
            elo = []                          # senza ELO si usa solo «ID BWF» di Athletes
    elo_per_chiave = {(norma_codice(e.get("id_bwf")), e.get("spec")): e for e in elo if e.get("id_bwf")}

    # 2. codice BWF delle pagine di Athletes: prima «ID BWF», poi «id_bwf» dell'ELO (collegato con "notion")
    codice_pagina = {i: norma_codice(info.get("idbwf")) for i, info in ath.items() if info.get("idbwf")}
    for e in elo:
        if e.get("notion") in ath and e.get("notion") not in codice_pagina and e.get("id_bwf"):
            codice_pagina[e["notion"]] = norma_codice(e["id_bwf"])
    codici_athletes = set(codice_pagina.values())

    # 3. dal nome al codice: torneo per torneo dai tabelloni ufficiali (più sicuro, perché il sito
    #    BWF a volte cambia la grafia di un nome), poi un elenco generale per i tornei senza tabellone
    per_torneo = {nome: {norma_nome(s[0]): norma_codice(s[2]) for s in (t.get("squadre") or [])
                         if len(s) > 2 and s[2]} for nome, t in tabelloni.items()}
    generale, doppi = {}, set()
    coppie_nomi = [(n, c) for m in per_torneo.values() for n, c in m.items()]
    coppie_nomi += [(norma_nome(e.get("nome")), norma_codice(e.get("id_bwf"))) for e in elo]
    for n, c in coppie_nomi:
        if not n or not c:
            continue
        if generale.get(n, c) != c:
            doppi.add(n)                      # stesso nome con due codici diversi: non lo uso
        generale.setdefault(n, c)
    for n in doppi:
        generale.pop(n, None)

    def codice_di(torneo, nome):
        n = norma_nome(nome)
        return (per_torneo.get(torneo) or {}).get(n) or generale.get(n)

    # 4. squadre (giocatore o coppia, per specialità) e incontri, ognuno scritto una volta
    indice_torneo = {t["nome"]: i for i, t in enumerate(tornei)}
    elenco_tornei = [[t["nome"], t.get("categoria", ""), t.get("inizio", ""), t.get("fine", ""), t.get("stato", "")]
                     for t in tornei]
    squadre, indice_sq, ultima_vista = [], {}, {}

    def squadra(torneo, disc, nome, noc, data):
        """Indice della squadra: chiave = (codice, specialità); senza codice si usa il nome."""
        codice = codice_di(torneo, nome)
        chiave = (codice, disc) if codice else ("nome:" + norma_nome(nome), disc)
        nome = re.sub(r"\s+", " ", nome or "").strip()
        if chiave not in indice_sq:
            indice_sq[chiave] = len(squadre)
            squadre.append([nome, noc or "", codice or "", disc, 0, None])
        k = indice_sq[chiave]
        if data >= ultima_vista.get(k, ""):   # nome e NOC dell'incontro più recente
            ultima_vista[k] = data
            squadre[k][0], squadre[k][1] = nome, noc or squadre[k][1]
        return k

    righe = []
    for m in incontri:
        torneo, disc, turno, p1, n1, p2, n2, score, data = (list(m) + [""] * 9)[:9]
        if (score or "").startswith("non disputato"):
            continue                          # incontro non giocato: escluso, come nell'ELO
        if torneo not in indice_torneo:       # torneo non più nel calendario: lo aggiungo in fondo
            indice_torneo[torneo] = len(elenco_tornei)
            elenco_tornei.append([torneo, "", data, data, "concluso"])
        v, s = squadra(torneo, disc, p1, n1, data), squadra(torneo, disc, p2, n2, data)
        righe.append([indice_torneo[torneo], data, SIGLA_TURNO.get(turno, turno), v, s, score])
    righe.sort(key=lambda r: (r[1], ORDINE_TURNO.get(r[2], 9)))      # ordine cronologico

    # 5. collegamento con la classifica WON e stato in Athletes
    per_codice = {}
    for k, sq in enumerate(squadre):
        if sq[2]:
            per_codice.setdefault(sq[2], []).append(k)
    collegati = 0
    for a in dati["atleti"]:
        codice = codice_pagina.get(a["id"])
        if not codice or codice not in per_codice:
            continue
        ks = per_codice[codice]
        k = next((k for k in ks if squadre[k][3] == a["spec"]), ks[0])   # di norma la stessa specialità
        a["sq"] = k
        squadre[k][4] = 2
        collegati += 1
    for sq in squadre:
        if sq[4] == 0 and sq[2] in codici_athletes:
            sq[4] = 1                         # in Athletes, ma senza risultati nei db Risultati A e B
        e = elo_per_chiave.get((sq[2], sq[3])) if sq[2] else None
        if e and e.get("livello") in ("stabile", "provvisorio"):
            sq[5] = [e.get("elo"), e.get("livello")]

    dati["bwf"] = {"aggiornato": bwf.get("aggiornato"), "tornei": elenco_tornei,
                   "squadre": squadre, "incontri": righe}
    senza = [a["nome"] for a in dati["atleti"] if "sq" not in a]
    altri = sum(1 for sq in squadre if sq[4] < 2)
    print(f"Incontri BWF (badminton.json del {bwf.get('aggiornato')}): {len(righe)} incontri, {len(squadre)} giocatori "
          f"e coppie; {collegati} collegati alla classifica WON, {altri} solo BWF "
          f"({sum(1 for sq in squadre if sq[4] == 0)} non in Athletes); "
          f"{sum(1 for r in righe if r[2] == 'F')} finali")
    senza_codice = sum(1 for sq in squadre if not sq[2])
    if senza_codice:
        print(f"  {senza_codice} giocatori o coppie senza codice BWF: riconosciuti solo dal nome")
    if senza:
        print(f"  {len(senza)} atleti/coppie della classifica WON senza codice BWF o senza incontri: "
              + ", ".join(senza[:12]) + (" …" if len(senza) > 12 else ""))


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
    aggiungi_elo(dati, ath)               # novità del 17/11/2026
    aggiungi_incontri(dati, ath)          # novità del 25/11/2026
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
