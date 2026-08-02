#!/usr/bin/env python3
"""
Aggiorna prezzi_live.json — Maicol + Martina in un colpo solo.
Usato da portafoglio_app.html tramite il bottone "📥 Importa prezzi".

Esegui con doppio click su aggiorna_prezzi.bat oppure:
    python aggiorna_prezzi.py
"""

import json, os, re, sys
from datetime import datetime

try:
    import yfinance as yf
    import requests
except ImportError:
    print("📦 Installazione dipendenze...")
    os.system(f'{sys.executable} -m pip install yfinance requests beautifulsoup4 --break-system-packages -q')
    import yfinance as yf
    import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

OUTPUT = 'prezzi_live.json'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ═══════════════════════════════════════════════════════════
# MAPPA ISIN → (TICKER, VALUTA)
# None come ticker = scraper custom o valore statico
# ═══════════════════════════════════════════════════════════

ISIN_MAP = {
    # ── MAICOL ──
    'NL0010273215': ('ASML.AS',           'EUR'),  # ASML
    'IT0001031084': ('BGN.MI',            'EUR'),  # Banca Generali
    'US0846707026': ('BRK-B',            'USD'),  # Berkshire
    'US67066G1040': ('NVDA',             'USD'),  # NVIDIA
    'US70450Y1038': ('PYPL',             'USD'),  # PayPal
    'IT0004176001': ('PRY.MI',           'EUR'),  # Prysmian (Borsa Italiana)
    'IT0005631590': (None,               'EUR'),  # BTP 3.65% 2035  → scraper BI
    'LU1437017350': ('AEME.PA',          'EUR'),  # ETF EM Amundi (Euronext Paris — AEME.MI errato su Yahoo)
    'LU1841731745': ('LCCN.MI',          'EUR'),  # ETF China Amundi (LCCN su Borsa Italiana)
    'LU1681043599': ('CW8.MI',           'EUR'),  # ETF World CW8
    'IE00B579F325': ('SGLD.MI',          'EUR'),  # Gold Invesco (Borsa Italiana)
    'IE00BYZK4552': ('RBOT.MI',          'EUR'),  # ETF Automation
    'JE00B1VS3333': ('PHAG.MI',          'EUR'),  # Silver WisdomTree (Borsa Italiana)
    'IE00BM67HK77': ('XDWH.MI',          'EUR'),  # ETF Health
    'IE00BM67HV82': ('XDWI.MI',          'EUR'),  # ETF Industrial (Borsa Italiana)
    'BTC':          ('BTC-USD',           'USD'),  # Bitcoin
    'IT0000380664': ('0P00000U75.F',     'EUR'),  # Euromobiliare Flessibile
    'FR0000121667': ('EL.PA',            'EUR'),  # EssilorLuxottica
    'RUBINO AZIONARIO': (None,           'EUR'),  # Rubino → nessun ticker live

    # ── MARTINA ──
    'IE00B4L5Y983': ('SWDA.MI',          'EUR'),  # ETF World iShares
    'IE00BJ5JPG56': ('ICGA.DE',          'EUR'),  # ETF China iShares (Xetra EUR — non quotato su BI)
    'IE00B4L5YC18': ('SEMA.MI',           'EUR'),  # ETF EM iShares (SEMA su Borsa Italiana, non EIMI)
    'LU0256013359': (None,               'EUR'),  # Eurizon MS 40  → FondiOnline
    'IT0005367757': (None,               'EUR'),  # Eurizon Tesoreria → FondiOnline
    'LU1529957257': (None,               'EUR'),  # Eurizon Sustainable → FondiOnline
    'IT0005599078': (None,               'EUR'),  # Epsilon Difesa → FondiOnline
    'LU0552385295': (None,               'USD'),  # MS Global Opportunity → FondiOnline (valuta USD)
    'IT0005635583': (None,               'EUR'),  # BTP 3.85% 2040 → scraper BI
    # Fondi pensione: nessun prezzo live, aggiornamento manuale in app
}

# ISINs per cui usiamo FondiOnline.it (server-rendered, nessun JS richiesto)
FONDIONLINE_URLS = {
    'LU0256013359': 'https://www.fondionline.it/elenco-fondi/bilanciati-moderati-eur-globali/eurizon-manager-selection-ms-40-LU0256013359.html',
    'IT0005367757': 'https://www.fondionline.it/elenco-fondi/obbligazionari-eur/eurizon-tesoreria-IT0005367757.html',
    'LU1529957257': 'https://www.fondionline.it/elenco-fondi/azionari-internazionali/eurizon-sustainable-global-equities-LU1529957257.html',
    'IT0005599078': 'https://www.fondionline.it/elenco-fondi/bilanciati-moderati/epsilon-difesa-IT0005599078.html',
    'LU0552385295': 'https://www.fondionline.it/elenco-fondi/azionari-internazionali/morgan-stanley-global-opportunity-LU0552385295.html',
}
FONDIONLINE_ISINS = set(FONDIONLINE_URLS.keys())

# ISINs per cui usiamo lo scraper di Borsa Italiana
BORSA_ITALIANA_ISINS = {
    'IT0005631590',   # BTP 3.65% 2035
    'IT0005635583',   # BTP 3.85% 2040
}


# ═══════════════════════════════════════════════════════════
# FETCH EUR/USD
# ═══════════════════════════════════════════════════════════

def fetch_eurusd():
    try:
        h = yf.Ticker('EURUSD=X').history(period='1d')
        if not h.empty:
            return float(h['Close'].iloc[-1])
    except Exception:
        pass
    return 1.09


# ═══════════════════════════════════════════════════════════
# SCRAPER FONDIONLINE.IT (fondi non quotati)
# Pagine server-rendered → nessun JS richiesto
# Pattern: "Prezzo/Nav al DD/MM/YYYY: 199,56 EUR"
# ═══════════════════════════════════════════════════════════

def fetch_fondionline(isin):
    url = FONDIONLINE_URLS.get(isin)
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"    FondiOnline HTTP {r.status_code} ({isin})")
            return None
        # Cerca "Prezzo/Nav al GG/MM/AAAA: X,XX EUR/USD" (raw HTML con tag)
        m = re.search(
            r'Prezzo/Nav al \d{2}/\d{2}/\d{4}[^0-9]+([\d]+[,\.]\d{2,4})\s*(EUR|USD)',
            r.text
        )
        if m:
            raw = m.group(1).replace('.', '').replace(',', '.')
            return float(raw)
        print(f"    FondiOnline: pattern NAV non trovato ({isin})")
    except Exception as e:
        print(f"    FondiOnline ({isin}): {e}")
    return None


# ═══════════════════════════════════════════════════════════
# SCRAPER BORSA ITALIANA (BTP)
# ═══════════════════════════════════════════════════════════

def fetch_borsa_italiana(isin):
    url = f'https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/{isin}-MOTX.html?lang=it'
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if BeautifulSoup:
            soup = BeautifulSoup(r.text, 'html.parser')
            span = soup.find('span', class_='t-text -black-warm-60 -formatPrice')
            if span:
                tag = span.find('strong')
                if tag:
                    return float(tag.text.strip().replace(',', '.'))
    except Exception as e:
        print(f"    Borsa Italiana ({isin}): {e}")
    return None


# ═══════════════════════════════════════════════════════════
# FETCH YAHOO (singolo ticker, con fallback API v8)
# ═══════════════════════════════════════════════════════════

def fetch_yahoo(ticker):
    # Tentativo 1: yfinance
    try:
        h = yf.Ticker(ticker).history(period='1d')
        if not h.empty:
            return float(h['Close'].iloc[-1])
    except Exception:
        pass
    # Tentativo 2: Yahoo API v8
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            meta = r.json()['chart']['result'][0]['meta']
            return float(meta['regularMarketPrice'])
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("🔄 Aggiornamento prezzi — Maicol + Martina")
    print("=" * 50)

    # Carica prezzi precedenti come fallback
    old_prices = {}
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, 'r', encoding='utf-8') as f:
                old_prices = json.load(f)
        except Exception:
            pass

    print("💱 Fetch EUR/USD...")
    eurusd = fetch_eurusd()
    print(f"   EUR/USD = {eurusd:.4f}")

    results = {
        '_eurusd':  round(eurusd, 4),
        '_updated': datetime.now().isoformat(timespec='seconds'),
    }

    ok = 0
    skip = 0
    stale = 0
    fail = 0

    for isin, (ticker, currency) in ISIN_MAP.items():
        # Nessun ticker live → skip (aggiornamento manuale in app)
        if ticker is None and isin not in FONDIONLINE_ISINS and isin not in BORSA_ITALIANA_ISINS:
            print(f"  ⏭  {isin:20} → aggiornamento manuale")
            skip += 1
            continue

        price = None

        # Borsa Italiana (BTP)
        if isin in BORSA_ITALIANA_ISINS:
            price = fetch_borsa_italiana(isin)
            fonte = 'Borsa Italiana'

        # FondiOnline.it (fondi non quotati)
        elif isin in FONDIONLINE_ISINS:
            price = fetch_fondionline(isin)
            fonte = 'FondiOnline.it'

        # Yahoo Finance
        else:
            price = fetch_yahoo(ticker)
            fonte = 'Yahoo Finance'

        if price and price > 0:
            results[isin] = {'raw': round(price, 4), 'currency': currency}
            tag = f'[{fonte}]'
            if currency == 'USD':
                eur_equiv = price / eurusd
                print(f"  ✅ {isin:20} {price:>10.3f} USD  = €{eur_equiv:.2f}  {tag}")
            else:
                print(f"  ✅ {isin:20} {price:>10.4f} EUR  {tag}")
            ok += 1
        elif isin in old_prices and old_prices[isin].get('raw'):
            # Fallback: tieni il prezzo precedente
            results[isin] = old_prices[isin]
            old_val = old_prices[isin]['raw']
            print(f"  ⚠️  {isin:20} → prezzo non trovato, mantengo vecchio: {old_val}")
            stale += 1
        else:
            print(f"  ❌ {isin:20} → nessun prezzo disponibile")
            fail += 1

    # Salva
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("=" * 50)
    print(f"✅ {ok} aggiornati  |  ⚠️  {stale} invariati (vecchio prezzo)  |  ⏭  {skip} manuali  |  ❌ {fail} senza prezzo")
    print(f"💾 Salvato: {OUTPUT}")
    print()
    print("👉 Apri portafoglio_app.html → clicca 📥 Importa prezzi → seleziona prezzi_live.json")
    if sys.stdin.isatty():
        input("\nPremi INVIO per chiudere...")
