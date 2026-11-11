# Mappa dei qualificati LA28: come metterla online gratis

Serve solo un account GitHub, lo stesso dei tuoi agenti. Una volta configurata, la aggiorni con un clic.

## Cosa c'è nella cartella

- `index.html`: la pagina con la mappa
- `data.json`: i qualificati, viene riscritto a ogni aggiornamento
- `mondo.json`: i confini dei paesi
- `aggiorna_dati.py`: legge Notion e scrive `data.json`
- `.github/workflows/aggiorna.yml`: il comando di aggiornamento

## Prima configurazione (una volta sola)

1. **Notion.** Apri il database Athletes, clicca `•••` in alto a destra, poi Connessioni, e aggiungi la tua connessione (va bene "Agente Squash").
2. **Repository.** Su GitHub crea un repository nuovo, per esempio `mappa-la28`, impostato su **Public**. Con l'account gratuito GitHub Pages funziona solo con i repository pubblici: la pagina e i dati saranno visibili a tutti, il token no.
3. **Carica i file.** Add file > Upload files, trascina tutto il contenuto della cartella e conferma con Commit changes. Controlla che ci sia anche la cartella `.github`: i Mac la nascondono, quindi la vedi con Cmd+Maiusc+Punto. Se non riesci a caricarla, in GitHub fai Add file > Create new file, come nome scrivi `.github/workflows/aggiorna.yml` e incolla il contenuto del file.
4. **Token.** Settings > Secrets and variables > Actions > New repository secret. Nome `NOTION_TOKEN`, valore il token della connessione Notion.
5. **Pagina web.** Settings > Pages > Source: scegli **GitHub Actions**.

6. **Primo lancio.** Actions > Aggiorna mappa LA28 > Run workflow. Se GitHub chiede di abilitare i workflow, conferma. Dopo circa un minuto la pagina è online all'indirizzo `https://TUONOME.github.io/mappa-la28/`.
7. **Dentro Notion.** Nella pagina che preferisci scrivi `/embed`, incolla l'indirizzo e scegli Incorpora. Trascina i bordi del riquadro per ingrandirlo. Conviene una pagina a tutta larghezza.

## Come si aggiorna

Da quel momento non devi fare nulla. Ogni 15 minuti circa GitHub controlla Notion: se hai messo o tolto una Q, ripubblica la mappa. Dopo qualche minuto basta ricaricare la pagina di Notion. GitHub può ritardare i controlli automatici, soprattutto nelle ore di punta. Se hai fretta, lancia Run workflow a mano.

Se lo script non riconosce una gara a squadre, nel registro dell'esecuzione trovi una riga che inizia con `AVVISO`. Aggiungi quella gara nell'elenco `ROSE` di `aggiorna_dati.py`, con il numero di atleti.

## Come si conta

- Atleti: ogni persona vale 1, anche se gareggia in più prove. Le coppie valgono 2.
- Squadre: una riga di Notion vale il numero di posti previsto dal sistema di qualificazione LA28 (elenco `ROSE`).
- Recurve: 3 atleti per genere se c'è la squadra, altrimenti 1. La squadra mista non aggiunge posti.
- Pallanuoto: 12 è il valore di Parigi 2024, da confermare.
- ENG, SCO e WAL confluiscono in GBR. I codici senza territorio vengono tenuti nei totali ma non hanno un paese sulla mappa.

## Pagina Previsioni Wrestling

- `wrestling.html`: favoriti per l'oro LA28 in ognuna delle 18 categorie di lotta, stessa grafica di `sport.html`
- `wrestling.json`: le previsioni, riscritto a ogni aggiornamento
- `aggiorna_wrestling.py`: legge il db Notion "Previsioni Wrestling LA28" e scrive `wrestling.json`

Una volta sola: in Notion apri il database **Previsioni Wrestling LA28**, `•••` > Connessioni, aggiungi la stessa connessione della mappa.
Da lì in poi si aggiorna da sola: l'agente previsioni ricalcola quando cambiano i dati wrestling, e questa pagina lo legge al controllo successivo (ogni 15 minuti circa).
Indirizzo: `https://vier80.github.io/map-q-la28/wrestling.html` (si raggiunge anche da Qualificati per sport > Wrestling).

## Pagina Tennis

- `tennis.html`: simulazione dei qualificati LA28 del tennis (singolare e doppio), stessa grafica della pagina wrestling in azzurro chiaro
- `tennis.json`: i dati, riscritto a ogni aggiornamento
- `aggiorna_tennis.py`: legge il db Notion "LA28 Tennis" (scritto dall'agente tennis) e scrive `tennis.json`

Una volta sola: in Notion apri il database **LA28 Tennis**, `•••` > Connessioni, aggiungi la stessa connessione della mappa.
Indirizzo: `https://vier80.github.io/map-q-la28/tennis.html` (si raggiunge anche da Qualificati per sport > Tennis).

## Pagina Calendario delle qualificazioni

- `calendario.html`: calendario degli eventi che assegnano posti diretti per LA28 (2026, 2027, 2028), con filtri per anno, stato, sport e ricerca, e pulsante Scarica PDF; stessa grafica di `stima.html`, in lilla
- `calendario.json`: gli eventi, riscritto a ogni aggiornamento
- `aggiorna_calendario.py`: legge il db Notion **Calendario Qualificazioni LA28** e scrive `calendario.json`

Una volta sola: in Notion apri il database **Calendario Qualificazioni LA28**, `•••` > Connessioni, aggiungi la stessa connessione della mappa.
Il database è riempito dall'agente del repository privato `agente-calendario-la28`, che legge le pagine di Totallympics salvate a mano (il sito blocca i server di GitHub): istruzioni nella guida di quel repository.
Indirizzo: `https://vier80.github.io/map-q-la28/calendario.html`

## Pagina Qualificati LA28 (tipo di quota)

- `qualificati.html`: atleti e squadre con la Q in `🎟️Pass LA28`, con il tipo di quota (Athlete Quota, NOC Quota, Team Quota) secondo i sistemi di qualificazione CIO e pulsante Download PDF
- `qualificati.json`: i dati, riscritto a ogni aggiornamento
- `aggiorna_qualificati.py`: legge i qualificati del db Athletes e gli eventi collegati del db **🎟️ Direct Q Events 🇺🇸LA28**, decide il tipo di quota, scrive `qualificati.json` e aggiorna il db Notion **🎟️ Qualificati LA28** (aggiunge, corregge e manda nel cestino le righe che hanno perso la Q)
- `quote_la28.py`: le regole CIO sport per sport, usate da `aggiorna_qualificati.py`; lo script usa anche funzioni di `aggiorna_dati.py`, che deve restare nella stessa cartella

Una volta sola: in Notion apri i database **🎟️ Direct Q Events 🇺🇸LA28** e **🎟️ Qualificati LA28**, `•••` > Connessioni, aggiungi la stessa connessione della mappa.
Se nel registro dell'esecuzione compare `AVVISO: Sport senza regola`, aggiungi lo sport in `quote_la28.py`. Se compare `AVVISO: Non riesco a leggere il db "Direct Q Events"`, controlla la connessione di quel database.
Indirizzo: `https://vier80.github.io/map-q-la28/qualificati.html`

## Pagina Performance Judo

- `judo-performance.html`: classifica WON per categoria di peso, distacco in vetta, quadrante della performance, qualità del field, forza delle nazioni e focus Italia, nella grafica rosso pastello di `judo.html`
- `judo-performance.json`: i dati, riscritto a ogni aggiornamento
- `aggiorna_judo_performance.py`: legge i judoka del db Athletes e i loro risultati nei db **Risultati A** (MASTER RESULTS) e **Risultati B** (MASTER MINOR), ricalcola il WON 🔺 con le stesse formule di Notion e scrive `judo-performance.json`

Una volta sola: in Notion apri i database **Risultati A** e **Risultati B**, `•••` > Connessioni, aggiungi la stessa connessione della mappa.
Lo script ricalcola il WON con le stesse formule di Notion: se modifichi la formula WON in Notion, va modificata anche la sezione FORMULA dello script.
Le righe senza 🏟️ Rating valgono 0 punti: nel registro dell'esecuzione compaiono come `AVVISO`.
Indirizzo: `https://vier80.github.io/map-q-la28/judo-performance.html`

## Pagina Performance Badminton

- `badminton-performance.html`: classifica WON per specialità (singolari e doppi), distacco in vetta, quadrante della performance, qualità del field, forza delle nazioni e focus Italia, nel verde menta di `badminton.html`
- `badminton-performance.json`: i dati, riscritto a ogni aggiornamento
- `aggiorna_badminton_performance.py`: legge atleti e coppie di badminton del db Athletes e i loro risultati nei db **Risultati A** e **Risultati B**, ricalcola il WON 🔺 con le funzioni di `aggiorna_judo_performance.py` (che deve restare nella stessa cartella) e scrive `badminton-performance.json`

Indirizzo: `https://vier80.github.io/map-q-la28/badminton-performance.html`

## Pagina Performance Pentathlon Moderno

- `pentathlon-performance.html`: classifica PTS per genere, distacco in vetta, quadrante della performance, grandi eventi contro Coppa del Mondo, forza delle nazioni e focus Italia, in grigio pastello
- `pentathlon-performance.json`: i dati, riscritto a ogni aggiornamento
- `aggiorna_pentathlon_performance.py`: legge i pentatleti del db Athletes e i loro risultati nei db **Risultati A** e **Risultati B** (solo i primi 8 di ogni evento), prende la formula **PTS** da Notion e la ricontrolla con le stesse formule; scrive `pentathlon-performance.json`. Usa le funzioni di `aggiorna_judo_performance.py`, che deve restare nella stessa cartella

Se modifichi la formula PTS o Punti Base in Notion, la pagina resta giusta (il PTS viene letto da Notion), ma nel registro dell'esecuzione compare un `AVVISO … diverso dal ricalcolo`: in quel caso aggiorna la sezione FORMULA PTS dello script.
Indirizzo: `https://vier80.github.io/map-q-la28/pentathlon-performance.html`
