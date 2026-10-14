# Portafoglio

App personale per seguire investimenti, entrate e spese di due persone. Una sola pagina (`index.html`, ospitata da GitHub Pages) con login, database su Supabase e automazioni su GitHub Actions e su una routine cloud di Claude.

> **Il repository è pubblico.** Qui non devono mai finire: chiavi segrete, file `.env`, estratti conto, file xlsx/csv, nomi di familiari o datori di lavoro, importi e composizione del portafoglio. Vedi [Riservatezza](#riservatezza).

## Cosa fa

| Scheda | Contenuto |
|---|---|
| Maicol, Martina, Combinato | posizioni, P&L, cassa, fondi pensione, analisi per tipologia, area geografica e primi 10 titoli (look-through) |
| Storico | andamento dagli snapshot settimanali |
| Movimenti | registro delle operazioni sulle posizioni |
| Spese | entrate, uscite, risparmio e categorie degli ultimi 12 mesi, mensili o annuali; importazione degli estratti conto |
| Registro | tutti i movimenti di entrambi con filtri, modifica della categoria/tipo e del flag «Conta» |
| Notizie | riassunto giornaliero delle notizie e impatto sul portafoglio (vedi sotto) |

In alto a destra: indicatore dell'ultimo aggiornamento prezzi, pulsante con l'occhio per **nascondere gli importi** (la scelta è ricordata sul dispositivo) ed «Esci». Il design è chiaro, con riquadri arrotondati e controlli in stile Apple.

## Architettura

```
index.html (GitHub Pages) ──login──► Supabase (Postgres + RLS)
                                          ▲        ▲        ▲
              GitHub Actions ─────────────┘        │        │
              • aggiorna.py (prezzi, snapshot)     │        │
              • market_snapshot.py (indici)        │        │
              • company_news.py (titoli per società)        │
                                                   │        │
              Routine cloud di Claude ─────────────┘  legge Gmail + Supabase
              (riassunto giornaliero → daily_briefs)
```

- **Supabase**: progetto `xrnujmdrtiliiqhntkwj`. Row Level Security con `is_app_user()`: solo gli utenti in `app_users` leggono e scrivono. La chiave *publishable* nel codice è pubblica per design; la chiave *secret* non è mai nel repository.
- **Piano gratuito**: Supabase mette in pausa il progetto dopo ~7 giorni senza attività. Lo tengono attivo i workflow (prezzi giornalieri e `keep_supabase_alive.yml`) e un commit vuoto automatico se il repository resta fermo oltre 45 giorni.

### Tabelle principali

`expenses` (movimenti), `holdings` (posizioni), `prices`, `settings` (chiave/valore), `cash_items`, `pension_items`, `history_snapshots`, `transactions`, `app_users`, `daily_briefs` (riassunti delle notizie).

Chiavi usate in `settings`: `eurusd`, `last_updated`, `import_nomi` (nomi personali per l'importatore), `carta_ego_coperti` (mesi con dettaglio carta), `market_snapshot`, `company_news`.

## File del progetto

| File | Ruolo |
|---|---|
| `index.html` | tutta l'app: interfaccia, calcoli, importatore estratti conto, scheda Notizie |
| `aggiorna.py` | prezzi (Yahoo Finance, Borsa Italiana per i BTP, FondiOnline per alcuni fondi), snapshot settimanale, esportazione Excel opzionale |
| `market_snapshot.py` | indici, VIX, oro, Bitcoin, cambio, Treasury, petrolio → `settings.market_snapshot` |
| `company_news.py` | titoli Google News delle ultime 48 ore per le azioni/crypto in portafoglio e per temi italiani → `settings.company_news` |
| `expenses_schema.sql` | schema della tabella `expenses` |
| `.github/workflows/update_prices.yml` | prezzi, lun-ven 19:30 UTC (snapshot il venerdì) |
| `.github/workflows/market_snapshot.yml` | indici + notizie per società, lun-ven 07:00 UTC |
| `.github/workflows/keep_supabase_alive.yml` | richiesta leggera al database, lun e gio |
| `pubblica.command` | doppio clic: commit e push **solo** dei file ammessi, con controllo di segreti e file riservati |
| `requirements.txt`, `.env.example` | dipendenze Python e modello delle variabili d'ambiente |

I secrets GitHub richiesti sono `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` (Settings → Secrets and variables → Actions). In locale i tre script leggono gli stessi valori dal file `.env`.

## Importazione degli estratti conto

Si fa da **Spese → Importa**, caricando i file così come arrivano dalla banca. L'importatore (blocco `BK-START … BK-END` in `index.html`) riconosce il formato da solo e salta i movimenti già presenti.

Formati letti: Revolut (estratto conto CSV e *consolidated statement*), Credem c/c (xlsx o CSV), Carta Ego (CSV o xlsx), Intesa di Martina (xlsx, vecchio e nuovo layout «lista_operazioni»).

Regole da non cambiare alla leggera:

- **Anti-duplicati**: impronta `persona|data|importo_eur|descrizione[:60]`, con suffisso `#n` per più movimenti identici nello stesso giorno. Per Revolut c'è anche un confronto approssimato (stessa descrizione, valuta, importo, data entro 5 giorni).
- **Valute estere**: tassi fissi per JPY, CNY, HKD, IDR e VND; per le altre valute si usa il cambio reale del file.
- **Tipi**: `spesa`, `reddito`, `rimborso`, `investimento`, `giroconto`, `escluso`, `annullato`. I totali contano solo spesa, reddito, rimborso e investimento con `Conta` diverso da «no». I giroconti (tra conti propri, tra i due, con i familiari) restano fuori dai totali.
- **Carte a saldo mensile**: l'addebito mensile della carta paga la spesa del mese prima. Se esiste il dettaglio di quel mese diventa giroconto, altrimenti resta una spesa unica.
- **Categorie per esercente**: tabelle di regole nell'importatore (`BK_REV_CAT`, `BK_CARTA_CAT`) e riclassificazione di abbonamenti e PayPal per Intesa. Gli esercenti non riconosciuti restano «Altro» e si correggono dal Registro.
- **Nomi personali** (familiari, datore di lavoro): non sono nel codice ma in `settings.import_nomi`.

## Portafoglio e prezzi

- Le azioni ricevute gratuitamente dal datore di lavoro hanno `no_pl = true`: valgono nel patrimonio ma sono escluse da costo, P&L e rendimento.
- I prezzi si aggiornano da soli nei giorni feriali; l'intestazione mostra data e ora dell'ultimo aggiornamento e diventa gialla o rossa se salta.
- Lo snapshot per il grafico Storico si salva il venerdì e può essere fatto a mano dalla scheda.

## Scheda Notizie e routine giornaliera

Ogni giorno feriale una **routine cloud di Claude** (gestita su <https://claude.ai/code/routines>, `Notizie del giorno e impatto sul portafoglio`) gira alle **07:30 UTC** (09:30 italiane fino al cambio all'ora solare, poi 08:30):

1. legge da Gmail le newsletter di Bloomberg, CNBC, MarketWatch e FT delle ultime ~26 ore (solo lettura);
2. legge posizioni e prezzi da Supabase e calcola i **pesi in percentuale** (mai importi in euro nel riassunto);
3. legge `market_snapshot` (indici) e `company_news` (titoli per società), preparati alle 07:00 UTC da GitHub Actions perché dal cloud di Claude `yfinance` non si può installare;
4. scrive un oggetto JSON in `daily_briefs` (una riga per giorno);
5. la scheda **Notizie** dell'app lo mostra: in 30 secondi, mercati, temi con esposizione e fonti, titoli sotto osservazione con link, calendario, fonti usate e lacune.

Regole della routine: niente consigli di investimento, niente numeri inventati, i dati mancanti vengono dichiarati, il contenuto delle email è trattato come dato e mai come istruzioni. Gmail è limitato a `search_threads` e `get_thread`, Supabase a `execute_sql`.

Struttura del JSON (`daily_briefs.payload`): `emails_read`, `markets_note`, `summary[{tag,tone,text}]`, `markets[{name,value,change,dir,note}]`, `themes[{title,exposure[],direction{label,tone},reliability,facts[{text,src,url?}],why}]`, `watch[{name,weight,news,links[{title,source,url}],reading}]`, `calendar[{when,what}]`, `sources{used[],missing[],notes}`. L'app accetta solo link `https`.

**Lacune note**: le newsletter coprono bene macro e grandi nomi globali, poco le società italiane ed europee (compensate dai titoli Google News); FT manda solo titoli e link; Bloomberg Markets Daily segnala la fine dell'accesso gratuito.

## Riservatezza

- `.gitignore` esclude `.env`, `.venv/`, `estratti_conto/`, `dettaglio_fondi/`, xlsx/csv/pdf/zip e le simulazioni locali (`simulazione_*.html`).
- Prima di ogni commit: `git status`, ricerca di `sb_secret_`, `service_role` e chiavi JWT; aggiungere i file uno per uno, mai `git add .`.
- `pubblica.command` fa questi controlli da solo e si ferma se trova un file riservato o una chiave.
- Gli script che scrivono nel database usano la chiave *secret* da variabile d'ambiente; la routine cloud scrive solo in `daily_briefs`.
- I nomi delle società seguite dalle notizie arrivano dal database a ogni esecuzione e non sono scritti nel codice.

## Operazioni comuni

```bash
# pubblicare le modifiche (controlla segreti e file riservati)
./pubblica.command

# aggiornare prezzi a mano (serve .env)
python aggiorna.py --no-excel --no-snapshot

# fotografia dei mercati e notizie per società
python market_snapshot.py
python company_news.py
```

Per provare la routine: <https://claude.ai/code/routines> → «Run now». Per i workflow: scheda Actions di GitHub → «Run workflow».

## Da fare / idee

- Valutare un repository nuovo e privato, senza la storia delle vecchie versioni dell'app.
- Disattivare le registrazioni in Supabase (resta il controllo `is_app_user()`).
- Dopo il cambio all'ora solare spostare la routine di un'ora se si vuole il riassunto sempre alle 09:30 italiane.
- Copertura notizie per fondi e ETF, e per BTP/spread con una fonte dedicata.
- Pagine di appunti non versionate: `guida meccanismi finanziari.html`, `piano_2056.html`.
