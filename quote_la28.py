"""Regole del tipo di quota LA28, ricavate dai sistemi di qualificazione CIO.

Fonte: https://www.olympics.com/ioc/documents/olympic-games/los-angeles-2028-olympic-games
(letti il 9 novembre 2026).

I tre tipi, come su Totallympics:
  ATLETA  -> "Athlete Quota": il posto è dell'atleta (nominativo), l'NOC non può cambiarlo.
  NOC     -> "NOC Quota":     il posto è dell'NOC, che sceglie chi mandare (un atleta).
  Se il posto è dell'NOC e copre una squadra, un equipaggio o una coppia, diventa "Team Quota".

Come si legge una regola:
  "base"        tipo di quota della via di qualificazione normale (Mondiali, ranking, ecc.)
  "squadra"     tipo per le gare a squadre/coppie, se diverso dalla base
  e poi, se serve, un tipo diverso per singola via di qualificazione:
  "Host Country", "Universality / Tripartite", "Continental", "Ranking",
  "Olympic Q-Series", "World Championships", "Qualification Tournament"
  "doc"         sigla del PDF CIO (serve per il link)
  "regola"      la regola in breve, finisce nella pagina e in Notion

Se il CIO cambia un regolamento, basta correggere la riga dello sport qui sotto.
"""

ATLETA, NOC = "ATLETA", "NOC"
URL_DOC = "https://stillmed.olympics.com/media/Documents/Olympic-Games/LA28/{}-LA28-Qualification-System.pdf"
URL_PAGINA_CIO = "https://www.olympics.com/ioc/documents/olympic-games/los-angeles-2028-olympic-games"

# Sport di squadra: ogni riga è una squadra e il posto è sempre dell'NOC.
SPORT_DI_SQUADRA = {
    "Baseball": "BSB", "Softball": "BSB", "Basketball": "BKB", "Cricket": "CRT",
    "Flag Football": "FFB", "Football": None, "Handball": "HBL", "Hockey Field": "HOC",
    "Lacrosse Sixes": "LAC", "Rugby Sevens": "RU7", "Volleyball": "VVO", "Water Polo": "WPO",
}

REGOLE = {
    "Archery": {"doc": "ARC", "base": NOC,
                "regola": "Tutti i posti (individuali, squadre e misto) vanno all'NOC."},
    "Artistic Swimming": {"doc": "SWA", "base": NOC,
                          "regola": "Posti all'NOC, sia per la squadra sia per il duo."},
    "Athletics": {"doc": None, "base": NOC, "provvisoria": True,
                  "regola": "Regolamento LA28 non ancora pubblicato sul sito CIO: considerato posto NOC (da verificare)."},
    "Badminton": {"doc": "BDM", "base": ATLETA, "squadra": ATLETA,
                  "Host Country": NOC, "Universality / Tripartite": NOC,
                  "regola": "Posti nominativi dal ranking olimpico; paese ospitante e universalità vanno all'NOC."},
    "Beachvolley": {"doc": "VBV", "base": NOC,
                    "regola": "Tutti i posti vanno all'NOC, anche quelli vinti dalla coppia."},
    "Boxing": {"doc": "BOX", "base": ATLETA,
               "regola": "Tutti i posti sono assegnati agli atleti per nome."},
    "Canoe Slalom": {"doc": "PSL", "base": NOC,
                     "regola": "Posti all'NOC per gara, non legati all'atleta che li ha vinti."},
    "Canoe Sprint": {"doc": "PSP", "base": NOC,
                     "regola": "Posti all'NOC per gara, non legati all'atleta che li ha vinti."},
    "Cycling": {"doc": "CRD", "base": NOC, "Olympic Q-Series": ATLETA,
                "regola": "Strada, BMX Racing e MTB: posti all'NOC. BMX Freestyle: posti nominativi solo dalle Q-Series."},
    "Cycling Track": {"doc": "CTR", "base": NOC,
                      "regola": "Posti all'NOC; nessun posto per paese ospitante o universalità."},
    "Diving": {"doc": "DIV", "base": NOC,
               "regola": "Posti individuali e sincro all'NOC, non a un atleta specifico."},
    "Equestrian": {"doc": "EQU-JPG", "base": NOC,
                   "regola": "Posti di squadra e individuali all'NOC (salto, dressage, completo)."},
    "Fencing": {"doc": "FEN", "base": ATLETA, "squadra": NOC,
                "Host Country": NOC, "Universality / Tripartite": NOC,
                "regola": "Individuale: posti nominativi. Squadre: posti all'NOC. Paese ospitante all'NOC."},
    "Golf": {"doc": "GLF", "base": ATLETA, "squadra": NOC,
             "regola": "Stroke play individuale: posti nominativi dal ranking. Gara mista a squadre: all'NOC."},
    "Gym Artistic": {"doc": "GAR", "base": ATLETA, "squadra": NOC,
                     "regola": "Squadre: posto all'NOC. Individuali e attrezzi: posti nominativi."},
    "Gym Rhythmic": {"doc": "GRY", "base": NOC, "squadra": NOC,
                     "Continental": ATLETA, "Host Country": ATLETA, "Universality / Tripartite": ATLETA,
                     "regola": "Individuale dai Mondiali e squadre: posti all'NOC. Continentali, ospitante e universalità: nominativi."},
    "Trampoline": {"doc": "GTR", "base": NOC, "Universality / Tripartite": ATLETA,
                   "regola": "Posti all'NOC, tranne il posto di universalità che è nominativo."},
    "Judo": {"doc": "JUD", "base": ATLETA, "squadra": NOC,
             "Host Country": NOC, "Universality / Tripartite": NOC,
             "regola": "Posti nominativi dal ranking olimpico IJF; squadra mista, ospitante e universalità all'NOC."},
    "Modern Pentathlon": {"doc": "MPN", "base": ATLETA,
                          "Host Country": NOC, "Universality / Tripartite": NOC,
                          "regola": "Posti nominativi; ospitante e universalità all'NOC."},
    "Open Water": {"doc": "OWS", "base": ATLETA,
                   "regola": "Posti assegnati agli atleti per nome."},
    "Rowing": {"doc": "ROW", "base": NOC, "Universality / Tripartite": ATLETA,
               "regola": "Posti all'NOC per barca; i posti di universalità sono nominativi."},
    "Rowing Coastal": {"doc": "RCB", "base": NOC, "Universality / Tripartite": ATLETA,
                       "regola": "Posti all'NOC; gli inviti della Commissione Tripartita sono nominativi."},
    "Sailing": {"doc": "SAL", "base": NOC, "Universality / Tripartite": ATLETA,
                "regola": "Posti all'NOC per barca (Mondiali, continentali, ospitante); universalità nominativa."},
    "Shooting": {"doc": "SHO", "base": NOC, "Ranking": ATLETA, "Universality / Tripartite": ATLETA,
                 "regola": "Posti all'NOC, tranne quelli dal ranking olimpico e di universalità che sono nominativi."},
    "Skateboarding": {"doc": "SKB", "base": ATLETA, "Universality / Tripartite": NOC,
                      "regola": "Posti nominativi dal ranking WSR; universalità all'NOC."},
    "Sport Climbing": {"doc": "CLB-Boulder", "base": ATLETA,
                       "Host Country": NOC, "Universality / Tripartite": NOC,
                       "regola": "Posti nominativi; ospitante e universalità all'NOC."},
    "Squash": {"doc": "SQU", "base": ATLETA,
               "Host Country": NOC, "Universality / Tripartite": NOC,
               "regola": "Posti nominativi (ranking PSA e tornei continentali); ospitante e universalità all'NOC."},
    "Surfing": {"doc": "SRF", "base": ATLETA,
                "Host Country": NOC, "Universality / Tripartite": NOC,
                "regola": "Posti nominativi (WSL, ISA Games, continentali); ospitante, universalità e squadra ISA all'NOC."},
    "Swimming": {"doc": "SWM", "base": ATLETA, "squadra": NOC, "Universality / Tripartite": NOC,
                 "regola": "Gare individuali: posti nominativi. Staffette: posti all'NOC."},
    "Table Tennis": {"doc": "TTE", "base": ATLETA, "squadra": NOC,
                     "Host Country": NOC, "Universality / Tripartite": NOC,
                     "regola": "Singolari: posti nominativi. Squadra mista e doppio misto: all'NOC."},
    "Taekwondo": {"doc": "TKW", "base": NOC,
                  "regola": "Tutti i posti vanno all'NOC, che sceglie l'atleta."},
    "Tennis": {"doc": "TEN", "base": ATLETA, "squadra": ATLETA, "Universality / Tripartite": NOC,
               "regola": "Posti nominativi (anche doppi e misto); solo l'universalità va all'NOC."},
    "Triathlon": {"doc": "TRI", "base": NOC,
                  "regola": "Posti all'NOC, individuali e staffetta mista."},
    "Weightlifting": {"doc": "WLF", "base": ATLETA, "Host Country": NOC,
                      "regola": "Posti nominativi dal ranking olimpico; i posti dell'ospitante vanno all'NOC."},
    "Wrestling": {"doc": "WRE", "base": NOC,
                  "regola": "Tutti i posti vanno all'NOC; nessun posto per il paese ospitante."},
}

# Discipline equestri e di arrampicata hanno un PDF ciascuna.
DOC_PER_GARA = [
    ("dressage", "EQU-DRS"), ("eventing", "EQU-EVE"), ("jumping", "EQU-JPG"),
    ("lead", "CLB-Lead"), ("speed", "CLB-Speed"), ("boulder", "CLB-Boulder"),
    ("bmx race", "BMX"), ("freestyle park", "BMF"), ("mtb", "MTB"), ("3x3", "BK3"),
]


def nome_tipo(chi, squadra):
    if chi == ATLETA:
        return "Athlete Quota"
    return "Team Quota" if squadra else "NOC Quota"


def tipo_di_quota(sport, via, squadra):
    """Restituisce (tipo, regola, url_documento, da_verificare)."""
    if sport in SPORT_DI_SQUADRA:
        doc = SPORT_DI_SQUADRA[sport]
        return ("Team Quota", "Sport di squadra: il posto è dell'NOC per la sua squadra.",
                URL_DOC.format(doc) if doc else URL_PAGINA_CIO, False)
    regola = REGOLE.get(sport)
    if regola is None:
        return ("NOC Quota", "Sport non presente nelle regole: considerato posto NOC (da verificare).",
                URL_PAGINA_CIO, True)
    if squadra and "squadra" in regola:
        chi = regola["squadra"]          # le gare a squadre hanno una regola sola
    else:
        chi = regola.get(via) or regola["base"]
    url = URL_DOC.format(regola["doc"]) if regola.get("doc") else URL_PAGINA_CIO
    return nome_tipo(chi, squadra), regola["regola"], url, bool(regola.get("provvisoria"))


def documento_per_gara(url, gare):
    """Per equitazione, arrampicata, ciclismo e 3x3 punta al PDF della disciplina giusta."""
    testo = " ".join(gare).lower()
    for parola, doc in DOC_PER_GARA:
        if parola in testo:
            return URL_DOC.format(doc)
    return url
