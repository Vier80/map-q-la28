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
