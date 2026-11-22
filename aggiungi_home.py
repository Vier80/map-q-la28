#!/usr/bin/env python3
"""Aggiunge il tasto «🏠 Home» (verso home.html) nella testata di tutte le pagine del sito LA28.

Versione 1.0 del 22/11/2026 (scheda 50). Repo map-q-la28, cartella principale.

QUANDO PARTE
  Dentro il workflow «Aggiorna mappa LA28», subito PRIMA della pubblicazione su GitHub Pages
  e DOPO il salvataggio dei json. Modifica le pagine solo nella copia che viene pubblicata:
  i file del repository restano come sono (non viene fatto nessun commit).

PERCHÉ COSÌ E NON A MANO NEI FILE
  - alcune pagine vengono ricopiate dagli agenti (stima.html arriva ogni giorno dall'agente
    della Stima): un tasto scritto a mano sparirebbe al primo lancio;
  - le pagine nuove ricevono il tasto da sole, senza fare niente.

COME SCEGLIE DOVE METTERLO (una pagina alla volta)
  1. testata con i pulsanti <a class="vai"> (quasi tutte le pagine) → un pulsante «vai» in più,
     come PRIMO pulsante: prende i colori della pagina, perché usa il suo stesso stile;
  2. testata con <nav class="collegamenti"> (qualificati.html) → una carta «collegamento» in più;
  3. pagina con i bottoncini <a class="chip link"> (scheda.html) → un bottoncino in più;
  4. tutte le altre (es. redazione.html) → un piccolo bottone «🏠 Home» in una riga in cima alla pagina.
  Il tasto non compare nella stampa / PDF.

USO
  python aggiungi_home.py              lavora nella cartella dello script
  python aggiungi_home.py CARTELLA     lavora in un'altra cartella (per le prove)
Non servono librerie da installare.
"""
import re
import sys
from pathlib import Path

DESTINAZIONE = "home.html"                 # la homepage
SALTA = {"home.html"}                      # pagine che non devono avere il tasto
SEGNO = "data-la28-home"                   # segno di riconoscimento: se c'è già, la pagina non si tocca

# --- i quattro modi di disegnare il tasto -------------------------------------------------------
# 1) pulsante «vai» completo (titolo in grassetto, riga sotto, freccia), come «Mappa» o «Per sport»
TASTO_VAI = (f'<a class="vai" href="{DESTINAZIONE}" {SEGNO} title="Homepage del progetto LA28">'
             '<b>🏠 Home</b><span>Tutte le pagine LA28</span><i>›</i></a>\n    ')
# 1-bis) pulsante «vai» semplice, solo testo (index.html: «Qualificati per sport →»)
TASTO_VAI_SEMPLICE = f' <a class="vai" href="{DESTINAZIONE}" {SEGNO} style="margin-left:0">🏠 Home</a>'
# 2) carta «collegamento» di qualificati.html (pagina in inglese, quindi testo in inglese)
TASTO_COLLEGAMENTO = (
    f'\n      <a class="collegamento" href="{DESTINAZIONE}" {SEGNO}>\n'
    '        <span class="ico"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">'
    '<path d="M12 3 2 11.5h3V21h5.5v-6h3v6H19v-9.5h3L12 3Z"/></svg></span>\n'
    '        <span><b>Home</b><small>All LA28 project pages</small></span><span class="freccia">›</span>\n'
    '      </a>')
# 3) bottoncino «chip» di scheda.html
TASTO_CHIP = f'<a class="chip link" href="{DESTINAZIONE}" {SEGNO}>🏠 Home</a>\n      '
# 4) bottone autonomo con uno stile tutto suo
#    in una riga tutta sua in cima alla pagina: così non copre avvisi o pulsanti della pagina
TASTO_LIBERO = (f'\n<div class="la28-home-riga" {SEGNO}>'
                f'<a class="la28-home" href="{DESTINAZIONE}" title="Homepage del progetto LA28">🏠 Home</a></div>')
STILE = (f'<style {SEGNO}>\n'
         '.la28-home-riga { padding: 10px 12px 2px }\n'
         '.la28-home { display: inline-flex; align-items: center;\n'
         '  padding: 6px 13px; border-radius: 999px; background: rgba(255,255,255,.94); border: 1px solid rgba(0,0,0,.14);\n'
         '  box-shadow: 0 1px 4px rgba(0,0,0,.12); color: #16294d; font: 600 14px/1.2 Quicksand, "Avenir Next", system-ui, sans-serif;\n'
         '  text-decoration: none }\n'
         '.la28-home:hover { background: #fff; box-shadow: 0 3px 10px rgba(0,0,0,.16) }\n'
         f'@media print {{ [{SEGNO}] {{ display: none !important }} }}\n'
         '</style>\n')


def aggiungi(testo):
    """Restituisce (testo nuovo, dove è stato messo il tasto) oppure (None, motivo)."""
    if SEGNO in testo:
        return None, "tasto già presente"
    testata = re.search(r"<header\b[^>]*>.*?</header>", testo, re.S)

    # 1) testata con pulsanti «vai»
    if testata:
        primo = re.search(r'<(a|button)\s+class="vai"[^>]*>.*?</\1>', testata.group(0), re.S)
        if primo:
            inizio = testata.start() + primo.start()
            fine = testata.start() + primo.end()
            if "<b>" in primo.group(0):                       # pulsante completo: Home diventa il primo
                return testo[:inizio] + TASTO_VAI + testo[inizio:], "pulsante nella testata"
            return testo[:fine] + TASTO_VAI_SEMPLICE + testo[fine:], "link nella testata"
        # 2) testata con le carte «collegamento»
        nav = re.search(r'<nav class="collegamenti"[^>]*>', testata.group(0))
        if nav:
            punto = testata.start() + nav.end()
            return testo[:punto] + TASTO_COLLEGAMENTO + testo[punto:], "carta nella testata"

    # 3) pagina con i bottoncini «chip link»
    chip = re.search(r'<a class="chip link"', testo)
    if chip:
        return testo[:chip.start()] + TASTO_CHIP + testo[chip.start():], "bottoncino nella testata"

    # 4) nessuna testata riconosciuta: bottone in cima alla pagina
    corpo = re.search(r"<body\b[^>]*>", testo)
    if not corpo:
        return None, "manca <body>: pagina saltata"
    return testo[:corpo.end()] + TASTO_LIBERO + testo[corpo.end():], "bottone in cima alla pagina"


def main(cartella):
    cartella = Path(cartella)
    pagine = sorted(p for p in cartella.glob("*.html") if p.name not in SALTA)
    if not (cartella / DESTINAZIONE).exists():
        print(f"AVVISO: {DESTINAZIONE} non è nella cartella: il tasto porterebbe a una pagina che non c'è. Non faccio nulla.")
        return 0
    modificate = 0
    for pagina in pagine:
        testo = pagina.read_text(encoding="utf-8")
        nuovo, dove = aggiungi(testo)
        if nuovo is None:
            print(f"  {pagina.name}: {dove}")
            continue
        # lo stile (bottone libero + niente tasto nella stampa) va prima di </head>
        if "</head>" in nuovo:
            nuovo = nuovo.replace("</head>", STILE + "</head>", 1)
        pagina.write_text(nuovo, encoding="utf-8")
        modificate += 1
        print(f"  {pagina.name}: {dove}")
    print(f"Tasto Home aggiunto in {modificate} pagine su {len(pagine)} (i file del repository non cambiano).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent))
