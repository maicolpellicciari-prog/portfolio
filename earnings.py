#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
earnings.py — trimestrali delle societa' piu' importanti del portafoglio, anche dentro ETF e fondi (look-through).

1) legge dal database le posizioni e i prezzi, e dal file index.html la tabella LOOK (primi titoli di ogni ETF/fondo);
2) calcola il peso di ogni societa' sul totale investito (esclusi i fondi pensione) e tiene le TOP_N piu' pesanti;
3) per ciascuna chiede a Yahoo Finance (yfinance) l'ultima trimestrale (utile per azione atteso/reale/sorpresa)
   e la prossima (data e utile atteso);
4) salva tutto in settings (chiave 'earnings'). La routine delle notizie lo legge da li'.

Richiede SUPABASE_URL e SUPABASE_SERVICE_KEY (come aggiorna.py; in locale basta il file .env).
"""
import os, sys, re, json, math, datetime, warnings
import yfinance as yf
from supabase import create_client

warnings.filterwarnings("ignore")
TOP_N = 22

# nome usato in index.html (LOOK / CANON) -> ticker Yahoo Finance
TICKERS = {
    "NVIDIA": "NVDA", "Apple": "AAPL", "Microsoft": "MSFT", "Amazon": "AMZN", "Alphabet (A+C)": "GOOGL",
    "Broadcom": "AVGO", "Meta Platforms": "META", "Micron Technology": "MU", "Tesla": "TSLA", "TSMC": "TSM",
    "Samsung Electronics": "005930.KS", "SK hynix": "000660.KS", "Tencent": "0700.HK", "Alibaba": "BABA",
    "MediaTek": "2454.TW", "Delta Electronics": "2308.TW", "China Construction Bank": "0939.HK",
    "Hon Hai Precision": "2317.TW", "ASML": "ASML.AS", "Uber": "UBER", "Spotify": "SPOT", "Hermès": "RMS.PA",
    "DoorDash": "DASH", "MercadoLibre": "MELI", "Xiaomi": "1810.HK", "Meituan": "3690.HK", "ICBC": "1398.HK",
    "Bank of China": "3988.HK", "Ping An Insurance": "2318.HK", "PDD Holdings": "PDD", "NetEase": "NTES",
    "BYD": "1211.HK", "Caterpillar": "CAT", "GE Aerospace": "GE", "RTX": "RTX", "Siemens": "SIE.DE",
    "GE Vernova": "GEV", "Schneider Electric": "SU.PA", "Union Pacific": "UNP", "Rolls-Royce": "RR.L",
    "Boeing": "BA", "Eaton": "ETN", "Eli Lilly": "LLY", "Johnson & Johnson": "JNJ", "AbbVie": "ABBV",
    "Merck & Co.": "MRK", "UnitedHealth": "UNH", "Roche": "ROG.SW", "Novartis": "NOVN.SW", "AstraZeneca": "AZN.L",
    "Amgen": "AMGN", "Thermo Fisher": "TMO", "ServiceNow": "NOW", "Snowflake": "SNOW", "Advantest": "6857.T",
    "SAP": "SAP.DE", "Keyence": "6861.T", "Emerson Electric": "EMR", "Autodesk": "ADSK", "AMD": "AMD",
    "Berkshire Hathaway": "BRK-B", "EssilorLuxottica": "EL.PA", "PayPal": "PYPL", "Prysmian": "PRY.MI",
    "Banca Generali": "BGN.MI",
}


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


def parse_index_html():
    """Estrae LOOK e CANON da index.html (stessa fonte dell'analisi 'Primi 10 titoli')."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), encoding="utf-8").read()
    look = {}
    block = src[src.index("const LOOK = {"):src.index("const CANON")]
    for isin, body in re.findall(r"'([A-Z0-9]{12})':\[(.*?)\],?\n", block):
        look[isin] = [(n, float(p)) for n, p in re.findall(r"\['([^']+)',\s*([0-9.]+)\]", body)]
    canon = dict(re.findall(r"'([A-Z0-9]{12})':'([^']+)'", src[src.index("const CANON"):][:600]))
    return look, canon


def f(x):
    try:
        x = float(x)
        return None if math.isnan(x) else round(x, 4)
    except Exception:
        return None


def company_data(tk):
    t = yf.Ticker(tk)
    ed = t.earnings_dates
    today = datetime.datetime.now(datetime.timezone.utc).date()
    last = nxt = None
    if ed is not None and len(ed):
        ed = ed.sort_index()
        for d, r in ed.iterrows():
            day = d.date()
            rep = f(r.get("Reported EPS"))
            if rep is not None and day <= today:
                last = {"date": day.isoformat(), "eps_est": f(r.get("EPS Estimate")), "eps_act": rep,
                        "surprise_pct": f(r.get("Surprise(%)"))}
        for d, r in ed.iterrows():
            day = d.date()
            if f(r.get("Reported EPS")) is None and day >= today - datetime.timedelta(days=2):
                nxt = {"date": day.isoformat(), "eps_est": f(r.get("EPS Estimate"))}
                break
    return last, nxt


def main():
    load_env()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Manca SUPABASE_URL o SUPABASE_SERVICE_KEY.")
    sb = create_client(url, key)
    look, canon = parse_index_html()
    hold = sb.table("holdings").select("name,isin,asset,qty,currency").execute().data or []
    prices = {p["isin"]: p["market_price"] for p in (sb.table("prices").select("isin,market_price").execute().data or [])}
    eurusd = 1.15
    for s in sb.table("settings").select("key,value").eq("key", "eurusd").execute().data or []:
        try: eurusd = float(s["value"])
        except Exception: pass
    value, total = {}, 0.0
    for h in hold:
        nm = h["name"] or ""
        if re.search(r"previmoda|pension", nm, re.I):          # fondi pensione: fuori dal totale
            continue
        v = float(h["qty"] or 0) * float(prices.get(h["isin"]) or 0) / (eurusd if h.get("currency") == "USD" else 1)
        total += v
        if h["isin"] in look:
            for n, p in look[h["isin"]]:
                value[n] = value.get(n, 0) + v * p / 100
        else:
            n = canon.get(h["isin"]) or re.sub(r"\s*\(.*?\)", "", nm).strip()
            value[n] = value.get(n, 0) + v
    ranked = sorted(((n, v) for n, v in value.items() if n in TICKERS and total), key=lambda x: -x[1])[:TOP_N]
    items, errors = [], []
    for n, v in ranked:
        try:
            last, nxt = company_data(TICKERS[n])
            items.append({"name": n, "ticker": TICKERS[n], "weight_pct": round(v / total * 100, 2), "last": last, "next": nxt})
        except Exception as e:
            errors.append(f"{n}: {str(e)[:70]}")
            items.append({"name": n, "ticker": TICKERS[n], "weight_pct": round(v / total * 100, 2), "last": None, "next": None})
    payload = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "items": items, "errors": errors}
    sb.table("settings").upsert([{"key": "earnings", "value": json.dumps(payload, ensure_ascii=False)}], on_conflict="key").execute()
    print(f"Trimestrali salvate per {len(items)} societa'" + (f" · errori: {errors}" if errors else ""))
    for i in items:
        print(f"  {i['name']:20s} {i['weight_pct']:5.2f}%  ultima {i['last']['date'] if i['last'] else '-':10s} "
              f"{'sorpresa '+str(i['last']['surprise_pct'])+'%' if i['last'] else '':18s} prossima {i['next']['date'] if i['next'] else '-'}")


if __name__ == "__main__":
    main()
