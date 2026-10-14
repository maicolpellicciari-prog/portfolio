#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
company_news.py — titoli di notizie recenti sulle societa' in portafoglio, per la scheda "Notizie".

Legge dal database le posizioni (azioni e crypto) e cerca su Google News RSS le ultime 48 ore, piu' alcuni temi
generali italiani. Salva solo titolo, fonte, data e link nella tabella settings (chiave 'company_news').
Le societa' NON sono scritte nel codice (il repository e' pubblico): arrivano dal database a ogni esecuzione.
La routine che prepara il riassunto giornaliero legge da li'.

Richiede SUPABASE_URL e SUPABASE_SERVICE_KEY (come aggiorna.py; in locale basta il file .env).
"""
import os, sys, re, json, datetime, time, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
from supabase import create_client

PER_QUERY = 5          # titoli massimi per ricerca
MAX_AGE_H = 48         # solo notizie piu' recenti di cosi'
TOPICS = [             # temi generali (non sono posizioni): (etichetta, ricerca, edizione)
    ("BTP e spread", "BTP spread rendimento", "it"),
    ("BCE e tassi", "BCE tassi Lagarde", "it"),
    ("Borsa italiana", "Piazza Affari Ftse Mib", "it"),
    ("CPI e inflazione USA", "US CPI inflation report", "en"),
    ("Fed e tassi USA", "Federal Reserve interest rates", "en"),
]


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


def clean_name(n):
    n = re.sub(r"\(.*?\)", "", n)                       # "(EL.PA)", "(Invesco)"
    n = re.sub(r"\s+(Class\s+)?[AB]$", "", n.strip())   # "Berkshire Hathaway B"
    return n.strip()


def search(query, edition):
    hl, gl, ceid = ("it", "IT", "IT:it") if edition == "it" else ("en-US", "US", "US:en")
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{query} when:2d")
           + f"&hl={hl}&gl={gl}&ceid={ceid}")
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    now = datetime.datetime.now(datetime.timezone.utc)
    out, seen = [], set()
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        key = re.sub(r"\W+", " ", title.lower())[:80]
        if not title or key in seen:
            continue
        try:
            d = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if (now - d).total_seconds() > MAX_AGE_H * 3600:
            continue
        seen.add(key)
        out.append({"title": title, "source": src, "date": d.astimezone(datetime.timezone.utc).isoformat(timespec="minutes"),
                    "link": (it.findtext("link") or "").strip()})
        if len(out) >= PER_QUERY:
            break
    return out


def main():
    load_env()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Manca SUPABASE_URL o SUPABASE_SERVICE_KEY.")
    sb = create_client(url, key)
    hold = sb.table("holdings").select("name,asset,geo").execute().data or []
    targets, seen = [], set()
    for h in hold:
        if h.get("asset") not in ("Azione", "Crypto"):
            continue
        label = clean_name(h["name"])
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        edition = "en" if h.get("geo") in ("USA", "Crypto") else "it"
        targets.append((label, label + (" crypto" if h.get("asset") == "Crypto" else ""), edition))
    targets += TOPICS
    items, errors = [], []
    for label, query, edition in targets:
        try:
            items.append({"label": label, "news": search(query, edition)})
        except Exception as e:
            errors.append(f"{label}: {str(e)[:80]}")
        time.sleep(1)
    if not any(i["news"] for i in items):
        sys.exit("Nessuna notizia scaricata: " + "; ".join(errors))
    payload = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "items": items, "errors": errors}
    sb.table("settings").upsert([{"key": "company_news", "value": json.dumps(payload, ensure_ascii=False)}],
                                on_conflict="key").execute()
    print("Salvate notizie per: " + ", ".join(f"{i['label']} ({len(i['news'])})" for i in items)
          + (f" · errori: {errors}" if errors else ""))


if __name__ == "__main__":
    main()
