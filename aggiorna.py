#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggiorna.py — motore del portafoglio online.

Fa tre cose, in ordine:
  1) PREZZI   → scarica i prezzi live (Yahoo Finance) e li scrive nel database
  2) SNAPSHOT → salva lo snapshot dell'andamento (uno per giorno, di fatto settimanale se schedulato)
  3) EXCEL    → rigenera un file .xlsx con Posizioni, vista Geografica e Storico

Uso:
    python aggiorna.py              # fa tutto
    python aggiorna.py --no-excel   # solo prezzi + snapshot (utile in cloud)
    python aggiorna.py --no-excel --no-snapshot   # solo prezzi (uso quotidiano in cloud)
    python aggiorna.py --only-excel # solo l'Excel, senza toccare i prezzi

Richiede le variabili d'ambiente (vedi .env.example):
    SUPABASE_URL          il Project URL
    SUPABASE_SERVICE_KEY  la chiave *secret* / service_role  (NON la publishable!)
    OUTPUT_DIR            cartella dove salvare l'Excel (default: cartella corrente)
"""

import os, sys, datetime
from supabase import create_client

# ---------------------------------------------------------------------------
# Carica il file .env (stessa cartella dello script), senza dipendenze esterne
# ---------------------------------------------------------------------------
def load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")

if not URL or not KEY:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.exit(f"Manca SUPABASE_URL o SUPABASE_SERVICE_KEY.\n"
             f"Controlla che esista il file '.env' in: {here}\n"
             f"e che dentro ci siano le due righe compilate.")

sb = create_client(URL, KEY)

# ═══════════════════════════════════════════════════════════
#  MAPPA ISIN → (ticker Yahoo, valuta) — ripresa dal tuo aggiorna_prezzi.py
#  ticker None = prezzo via scraper (FondiOnline / Borsa Italiana) o manuale
# ═══════════════════════════════════════════════════════════
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

ISIN_MAP = {
    # ── Maicol ──
    'NL0010273215': ('ASML.AS', 'EUR'),        # ASML
    'IT0001031084': ('BGN.MI', 'EUR'),         # Banca Generali
    'US0846707026': ('BRYN.DE', 'EUR'),        # Berkshire B — listino in EUR (come su Credem)
    'US67066G1040': ('NVD.DE', 'EUR'),         # NVIDIA — listino in EUR (come su Credem)
    'US70450Y1038': ('PYPL', 'USD'),           # PayPal
    'IT0004176001': ('PRY.MI', 'EUR'),         # Prysmian
    'IT0005631590': (None, 'EUR'),             # BTP 3.65% 2035  → Borsa Italiana
    'LU1437017350': ('AEME.PA', 'EUR'),        # Amundi EM
    'LU1841731745': ('LCCN.MI', 'EUR'),        # Amundi China
    'LU1681043599': ('CW8.MI', 'EUR'),         # Amundi World CW8
    'IE00B579F325': ('SGLD.MI', 'EUR'),        # Gold Invesco
    'IE00BYZK4552': ('RBOT.MI', 'EUR'),        # iShares Automation
    'JE00B1VS3333': ('PHAG.MI', 'EUR'),        # WisdomTree Silver
    'IE00BM67HK77': ('XDWH.MI', 'EUR'),        # iShares Health
    'IE00BM67HV82': ('XDWI.MI', 'EUR'),        # iShares Industrial
    'BTC':          ('BTC-USD', 'USD'),        # Bitcoin
    'IT0000380664': ('0P00000U75.F', 'EUR'),   # Euromobiliare Flessibile
    'FR0000121667': ('EL.PA', 'EUR'),          # EssilorLuxottica
    'RUBINO AZIONARIO': (None, 'EUR'),         # Rubino → manuale (nessun ticker live)
    # ── Martina ──
    'IE00B4L5Y983': ('SWDA.MI', 'EUR'),        # iShares World
    'IE00BJ5JPG56': ('ICGA.DE', 'EUR'),        # iShares China (Xetra)
    'IE00B4L5YC18': ('SEMA.MI', 'EUR'),        # iShares EM
    'LU0256013359': (None, 'EUR'),             # Eurizon MS 40          → FondiOnline
    'IT0005367757': (None, 'EUR'),             # Eurizon Tesoreria      → FondiOnline
    'LU1529957257': (None, 'EUR'),             # Eurizon Sustainable    → FondiOnline
    'IT0005599078': (None, 'EUR'),             # Epsilon Difesa         → FondiOnline
    'LU0552385295': (None, 'USD'),             # MS Global Opportunity  → FondiOnline
    'IT0005635583': (None, 'EUR'),             # BTP 3.85% 2040         → Borsa Italiana
}

# Fondi non quotati → NAV da FondiOnline.it (pagine server-rendered)
FONDIONLINE_URLS = {
    'LU0256013359': 'https://www.fondionline.it/elenco-fondi/bilanciati-moderati-eur-globali/eurizon-manager-selection-ms-40-LU0256013359.html',
    'IT0005367757': 'https://www.fondionline.it/elenco-fondi/obbligazionari-eur/eurizon-tesoreria-IT0005367757.html',
    'LU1529957257': 'https://www.fondionline.it/elenco-fondi/azionari-internazionali/eurizon-sustainable-global-equities-LU1529957257.html',
    'IT0005599078': 'https://www.fondionline.it/elenco-fondi/bilanciati-moderati/epsilon-difesa-IT0005599078.html',
    'LU0552385295': 'https://www.fondionline.it/elenco-fondi/azionari-internazionali/morgan-stanley-global-opportunity-LU0552385295.html',
}
FONDIONLINE_ISINS = set(FONDIONLINE_URLS.keys())

# BTP → scraper Borsa Italiana
BORSA_ITALIANA_ISINS = {'IT0005631590', 'IT0005635583'}

# ---------------------------------------------------------------------------
# Lettura dati
# ---------------------------------------------------------------------------
def load():
    d = {}
    d["holdings"] = sb.table("holdings").select("*").execute().data
    d["prices"]   = {p["isin"]: p["market_price"] for p in sb.table("prices").select("*").execute().data}
    d["settings"] = {s["key"]: s["value"] for s in sb.table("settings").select("*").execute().data}
    d["cash"]     = sb.table("cash_items").select("*").execute().data
    d["pension"]  = sb.table("pension_items").select("*").execute().data
    d["eurusd"]   = float(d["settings"].get("eurusd", 1.14))
    return d

# ---------------------------------------------------------------------------
# 1) PREZZI  (tre fonti: Yahoo Finance, FondiOnline.it, Borsa Italiana)
# ---------------------------------------------------------------------------
import re
try:
    import requests
except ImportError:
    requests = None

def fetch_eurusd(default):
    try:
        import yfinance as yf
        h = yf.Ticker('EURUSD=X').history(period='1d')
        if not h.empty:
            return float(h['Close'].iloc[-1])
    except Exception:
        pass
    return default

def fetch_yahoo(ticker):
    # 1) yfinance
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='1d')
        if not h.empty:
            return float(h['Close'].iloc[-1])
    except Exception:
        pass
    # 2) API v8 come fallback
    if requests:
        try:
            url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}'
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                meta = r.json()['chart']['result'][0]['meta']
                return float(meta['regularMarketPrice'])
        except Exception:
            pass
    return None

def fetch_fondionline(isin):
    if not requests:
        return None
    url = FONDIONLINE_URLS.get(isin)
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        m = re.search(r'Prezzo/Nav al \d{2}/\d{2}/\d{4}[^0-9]+([\d]+[,\.]\d{2,4})\s*(EUR|USD)', r.text)
        if m:
            return float(m.group(1).replace('.', '').replace(',', '.'))
    except Exception as e:
        print("   FondiOnline", isin, e)
    return None

def fetch_borsa_italiana(isin):
    if not requests:
        return None
    url = f'https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/{isin}-MOTX.html?lang=it'
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        span = soup.find('span', class_='t-text -black-warm-60 -formatPrice')
        if span:
            tag = span.find('strong')
            if tag:
                return float(tag.text.strip().replace(',', '.'))
    except Exception as e:
        print("   Borsa Italiana", isin, e)
    return None

def yahoo_symbol_from_isin(isin):
    """Chiede a Yahoo il simbolo corrispondente a un ISIN (utile per i fondi)."""
    if not requests:
        return None
    try:
        r = requests.get('https://query1.finance.yahoo.com/v1/finance/search',
                         params={'q': isin, 'quotesCount': 5, 'newsCount': 0},
                         headers=HEADERS, timeout=10)
        quotes = r.json().get('quotes', [])
        if quotes:
            return quotes[0].get('symbol')
    except Exception:
        pass
    return None

def update_prices(data):
    old = data["prices"]  # ultimi prezzi nel DB → fallback se il fetch fallisce
    eurusd = fetch_eurusd(data["eurusd"])
    print(f"  EUR/USD = {eurusd:.4f}")
    sb.table("settings").upsert({"key": "eurusd", "value": str(round(eurusd, 4))},
                                on_conflict="key").execute()

    ok = stale = skip = fail = 0
    for isin, (ticker, currency) in ISIN_MAP.items():
        if ticker is None and isin not in FONDIONLINE_ISINS and isin not in BORSA_ITALIANA_ISINS:
            skip += 1
            continue
        if isin in BORSA_ITALIANA_ISINS:
            price, fonte = fetch_borsa_italiana(isin), "Borsa Italiana"
        elif ticker:
            price, fonte = fetch_yahoo(ticker), "Yahoo"
        else:
            # fondi: risolvi l'ISIN in un simbolo Yahoo, poi prendi il prezzo;
            # se Yahoo non lo trova, ripiega sullo scraper FondiOnline
            sym = yahoo_symbol_from_isin(isin)
            price = fetch_yahoo(sym) if sym else None
            fonte = f"Yahoo/{sym}" if price else None
            if not price:
                price, fonte = fetch_fondionline(isin), "FondiOnline"

        if price and price > 0:
            sb.table("prices").upsert(
                {"isin": isin, "market_price": round(price, 4),
                 "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                on_conflict="isin").execute()
            print(f"  OK  {isin:18} {price:>11.4f} {currency}  [{fonte}]")
            ok += 1
        elif old.get(isin):
            print(f"  ~   {isin:18} non trovato, mantengo {old[isin]}")
            stale += 1
        else:
            print(f"  XX  {isin:18} nessun prezzo")
            fail += 1

    sb.table("settings").upsert({"key": "last_updated", "value": datetime.date.today().isoformat()},
                                on_conflict="key").execute()
    print(f"Prezzi: {ok} aggiornati | {stale} invariati | {skip} manuali | {fail} falliti")

# ---------------------------------------------------------------------------
# 2) SNAPSHOT
# ---------------------------------------------------------------------------
def val_eur(h, prices, eurusd):
    mp = prices.get(h["isin"], 0) or 0
    rate = eurusd if h["currency"] == "USD" else 1
    return h["qty"] * mp / rate

def cost_eur(h, eurusd):
    rate = eurusd if h["currency"] == "USD" else 1
    return h["qty"] * h["avg_price"] / rate

def write_snapshot(data):
    today = datetime.date.today().isoformat()
    for pf in ("maicol", "martina"):
        hs = [h for h in data["holdings"] if h["portfolio"] == pf]
        invested = sum(val_eur(h, data["prices"], data["eurusd"]) for h in hs)
        cost     = sum(cost_eur(h, data["eurusd"]) for h in hs)
        cassa    = sum(float(c["value"]) for c in data["cash"] if c["portfolio"] == pf)
        pens     = sum(float(p["value"]) for p in data["pension"] if p["portfolio"] == pf)
        pl = invested - cost
        rec = {"portfolio": pf, "snap_date": today,
               "invested": round(invested), "cash": round(cassa), "pension": round(pens),
               "total": round(invested + cassa + pens), "pl_eur": round(pl),
               "pl_pct": round(pl / cost * 100, 2) if cost else 0, "cost": round(cost)}
        sb.table("history_snapshots").upsert(rec, on_conflict="portfolio,snap_date").execute()
        print(f"  Snapshot {pf}: totale €{rec['total']:,}")
    print("Snapshot salvato per", today)

# ---------------------------------------------------------------------------
# 3) EXCEL
# ---------------------------------------------------------------------------
def build_excel(data):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    head_fill = PatternFill("solid", fgColor="1D212C")
    head_font = Font(color="E3B23C", bold=True)
    thin = Side(style="thin", color="D9DDE6")
    border = Border(bottom=thin)

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill; cell.font = head_font
            cell.alignment = Alignment(horizontal="center")

    eurusd = data["eurusd"]
    prices = data["prices"]

    # --- Posizioni ---
    ws = wb.active; ws.title = "Posizioni"
    cols = ["Portafoglio","Titolo","ISIN","Strumento","Categoria","Valuta",
            "Qtà","PMC","Prezzo","Valore €","Costo €","P&L €","P&L %"]
    ws.append(cols); style_header(ws, len(cols))
    for h in sorted(data["holdings"], key=lambda x:(x["portfolio"], -val_eur(x, prices, eurusd))):
        v = val_eur(h, prices, eurusd); c = cost_eur(h, eurusd); pl = v - c
        ws.append([h["portfolio"], h["name"], h["isin"], h.get("detail"), h.get("type"),
                   h["currency"], h["qty"], h["avg_price"], prices.get(h["isin"], 0),
                   round(v,2), round(c,2), round(pl,2), round(pl/c*100,2) if c else 0])
    for col in "GHIJKL":
        for cell in ws[col]:
            cell.number_format = "#,##0.00"

    # --- Geografia ---
    ws2 = wb.create_sheet("Geografia")
    ws2.append(["Regione","Maicol €","Martina €","Totale €","% Totale"]); style_header(ws2, 5)
    def geo_for(pf):
        g = {}
        for h in data["holdings"]:
            if h["portfolio"] != pf: continue
            v = val_eur(h, prices, eurusd)
            gb = h.get("geo_breakdown")
            if isinstance(gb, dict) and gb:
                for k, pct in gb.items(): g[k] = g.get(k, 0) + v * (pct/100)
            else:
                k = h.get("geo") or "Altro"; g[k] = g.get(k, 0) + v
        return g
    gm, gt = geo_for("maicol"), geo_for("martina")
    regions = sorted(set(gm) | set(gt))
    grand = sum(gm.values()) + sum(gt.values())
    for r in regions:
        tot = gm.get(r,0) + gt.get(r,0)
        ws2.append([r, round(gm.get(r,0),2), round(gt.get(r,0),2), round(tot,2),
                    round(tot/grand*100,1) if grand else 0])
    for col in "BCD":
        for cell in ws2[col]: cell.number_format = "#,##0.00"

    # --- Storico ---
    ws3 = wb.create_sheet("Storico")
    ws3.append(["Portafoglio","Data","Investito","Cassa","Pensione","Totale","P&L €","P&L %"]); style_header(ws3, 8)
    snaps = sb.table("history_snapshots").select("*").order("snap_date").execute().data
    for s in snaps:
        ws3.append([s["portfolio"], s["snap_date"], s["invested"], s["cash"], s.get("pension",0),
                    s["total"], s["pl_eur"], s["pl_pct"]])
    for col in "CDEFG":
        for cell in ws3[col]: cell.number_format = "#,##0"

    for w in (ws, ws2, ws3):
        for column_cells in w.columns:
            length = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells)
            w.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 34)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "portafoglio.xlsx")
    wb.save(path)
    print("Excel salvato in", path)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    data = load()
    if "--only-excel" in args:
        build_excel(data); return
    print("→ Prezzi"); update_prices(data)
    data = load()  # ricarica con i prezzi nuovi
    if "--no-snapshot" not in args:
        print("→ Snapshot"); write_snapshot(data)
    if "--no-excel" not in args:
        print("→ Excel"); build_excel(data)
    print("Fatto.")

if __name__ == "__main__":
    main()
