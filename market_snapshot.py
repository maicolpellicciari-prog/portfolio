#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_snapshot.py — fotografia dei mercati per la scheda "Notizie".

Scarica da Yahoo Finance gli indici principali (azionari, volatilita', oro, Bitcoin, cambio, tassi, petrolio)
e li salva gia' formattati in italiano nella tabella settings (chiave 'market_snapshot').
Il riassunto giornaliero (routine nel cloud) li legge da li', perche' dal cloud yfinance non si installa.

Richiede SUPABASE_URL e SUPABASE_SERVICE_KEY (come aggiorna.py; in locale basta il file .env).
"""
import os, sys, json, datetime
import yfinance as yf
from supabase import create_client


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# (nome, ticker, decimali, suffisso, tipo)  tipo: 'pct' = variazione %, 'yield' = rendimento in % con variazione in punti base
ITEMS = [
    ("S&P 500",              "^GSPC",     2, "",   "pct"),
    ("Nasdaq Composite",     "^IXIC",     2, "",   "pct"),
    ("FTSE MIB",             "FTSEMIB.MI", 2, "",  "pct"),
    ("Euro Stoxx 50",        "^STOXX50E", 2, "",   "pct"),
    ("DAX",                  "^GDAXI",    2, "",   "pct"),
    ("Nikkei 225",           "^N225",     2, "",   "pct"),
    ("Hang Seng",            "^HSI",      2, "",   "pct"),
    ("Shanghai Comp.",       "000001.SS", 2, "",   "pct"),
    ("VIX (volatilita')",    "^VIX",      2, "",   "pct"),
    ("Treasury USA 10 anni", "^TNX",      2, "%",  "yield"),
    ("EUR/USD",              "EURUSD=X",  4, "",   "pct"),
    ("Oro (future)",         "GC=F",      2, "",   "pct"),
    ("Bitcoin",              "BTC-USD",   0, " $", "pct"),
    ("Petrolio Brent",       "BZ=F",      2, " $", "pct"),
    ("Petrolio WTI",         "CL=F",      2, " $", "pct"),
]


def it(x, dec):
    s = f"{abs(x):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if x < 0 else "") + s


def main():
    load_env()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Manca SUPABASE_URL o SUPABASE_SERVICE_KEY.")
    out, errors = [], []
    for name, tk, dec, suf, kind in ITEMS:
        try:
            h = yf.Ticker(tk).history(period="7d")["Close"].dropna()
            if len(h) < 2:
                raise ValueError("dati insufficienti")
            last, prev = float(h.iloc[-1]), float(h.iloc[-2])
            d = h.index[-1]
            if kind == "yield":
                bp = (last - prev) * 100
                change = ("+" if bp >= 0 else "−") + f"{abs(bp):.0f} pb"
                direction = "up" if bp > 0 else ("down" if bp < 0 else "flat")
            else:
                pct = (last / prev - 1) * 100
                change = ("+" if pct >= 0 else "−") + it(abs(pct), 2) + "%"
                direction = "up" if pct > 0.005 else ("down" if pct < -0.005 else "flat")
            out.append({"name": name, "value": it(last, dec) + suf, "change": change, "dir": direction,
                        "note": "dati di mercato · ultimo dato " + d.strftime("%d/%m")})
        except Exception as e:
            errors.append(f"{name}: {str(e)[:80]}")
    if not out:
        sys.exit("Nessun dato scaricato: " + "; ".join(errors))
    payload = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "items": out, "errors": errors}
    create_client(url, key).table("settings").upsert(
        [{"key": "market_snapshot", "value": json.dumps(payload, ensure_ascii=False)}], on_conflict="key").execute()
    print(f"Salvati {len(out)} dati di mercato" + (f" · errori: {errors}" if errors else ""))


if __name__ == "__main__":
    main()
