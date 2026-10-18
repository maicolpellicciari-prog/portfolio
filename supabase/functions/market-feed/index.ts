// market-feed: fotografia dei mercati (Yahoo Finance) e titoli di notizie (Google News) per la scheda "Notizie".
// Chiamata ogni sera da pg_cron (22:30 UTC, lun-ven). Autenticazione: intestazione x-feed-token, confrontata con il segreto
// custodito nel database (private.secrets, letto via get_feed_token()); verify_jwt e' disattivato perche' lo chiama il database.
// Scrive in settings le chiavi 'market_snapshot' e 'company_news', lette dalla routine del riassunto.
// Copia di riferimento: la versione in uso e' quella pubblicata su Supabase (Edge Functions > market-feed).
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36";

// [nome, ticker, decimali, suffisso, tipo]  tipo: pct = variazione %, yield = rendimento con variazione in punti base
const ITEMS: [string, string, number, string, string][] = [
  ["S&P 500", "^GSPC", 2, "", "pct"],
  ["Nasdaq Composite", "^IXIC", 2, "", "pct"],
  ["FTSE MIB", "FTSEMIB.MI", 2, "", "pct"],
  ["Euro Stoxx 50", "^STOXX50E", 2, "", "pct"],
  ["DAX", "^GDAXI", 2, "", "pct"],
  ["Nikkei 225", "^N225", 2, "", "pct"],
  ["Hang Seng", "^HSI", 2, "", "pct"],
  ["Shanghai Comp.", "000001.SS", 2, "", "pct"],
  ["VIX (volatilita')", "^VIX", 2, "", "pct"],
  ["Treasury USA 10 anni", "^TNX", 2, "%", "yield"],
  ["EUR/USD", "EURUSD=X", 4, "", "pct"],
  ["Oro (future)", "GC=F", 2, "", "pct"],
  ["Bitcoin", "BTC-USD", 0, " $", "pct"],
  ["Petrolio Brent", "BZ=F", 2, " $", "pct"],
  ["Petrolio WTI", "CL=F", 2, " $", "pct"],
];
const TOPICS: [string, string, string][] = [
  ["BTP e spread", "BTP spread rendimento", "it"],
  ["BCE e tassi", "BCE tassi Lagarde", "it"],
  ["Borsa italiana", "Piazza Affari Ftse Mib", "it"],
  ["CPI e inflazione USA", "US CPI inflation report", "en"],
  ["Fed e tassi USA", "Federal Reserve interest rates", "en"],
];

function it(x: number, dec: number): string {
  const [i, d] = Math.abs(x).toFixed(dec).split(".");
  const g = i.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (x < 0 ? "−" : "") + g + (d ? "," + d : "");
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function inBatches<T, R>(arr: T[], size: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(...(await Promise.all(arr.slice(i, i + size).map(fn))));
    await sleep(300);
  }
  return out;
}

type Bar = { d: string; c: number };
async function chart(sym: string, range: string, interval: string): Promise<Bar[]> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=${interval}`;
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const j = await r.json();
  const res = j?.chart?.result?.[0];
  if (!res) throw new Error("nessun dato");
  const ts: number[] = res.timestamp || [];
  const cl: (number | null)[] = res.indicators?.quote?.[0]?.close || [];
  const off: number = res.meta?.gmtoffset || 0;
  const out: Bar[] = [];
  ts.forEach((t, i) => {
    const c = cl[i];
    if (c != null) out.push({ d: new Date((t + off) * 1000).toISOString().slice(0, 10), c });
  });
  return out;
}
// Ultimo prezzo e chiusura precedente. Le barre giornaliere di Yahoo per le borse non USA a fine seduta a volte mancano:
// in quel caso si usa l'ultima barra oraria.
async function lastAndPrev(sym: string) {
  const daily = await chart(sym, "7d", "1d");
  let hourly: Bar[] = [];
  try { hourly = await chart(sym, "5d", "1h"); } catch (_) { /* ripiego sulle giornaliere */ }
  if (hourly.length && daily.length) {
    const d = hourly[hourly.length - 1].d;
    const last = daily[daily.length - 1].d === d ? daily[daily.length - 1].c : hourly[hourly.length - 1].c;
    const before = daily.filter((x) => x.d < d);
    if (before.length) return { last, prev: before[before.length - 1].c, d };
  }
  if (daily.length < 2) throw new Error("dati insufficienti");
  return { last: daily[daily.length - 1].c, prev: daily[daily.length - 2].c, d: daily[daily.length - 1].d };
}

async function markets() {
  const errors: string[] = [];
  const res = await inBatches(ITEMS, 5, async ([name, tk, dec, suf, kind]) => {
    try {
      const { last, prev, d } = await lastAndPrev(tk);
      let change: string, dir: string;
      if (kind === "yield") {
        const bp = (last - prev) * 100;
        change = (bp >= 0 ? "+" : "−") + Math.abs(bp).toFixed(0) + " pb";
        dir = bp > 0 ? "up" : bp < 0 ? "down" : "flat";
      } else {
        const pct = (last / prev - 1) * 100;
        change = (pct >= 0 ? "+" : "−") + it(Math.abs(pct), 2) + "%";
        dir = pct > 0.005 ? "up" : pct < -0.005 ? "down" : "flat";
      }
      return { name, value: it(last, dec) + suf, change, dir, note: "dati di mercato · ultimo dato " + d.slice(8, 10) + "/" + d.slice(5, 7) };
    } catch (e) {
      errors.push(`${name}: ${String((e as Error).message).slice(0, 70)}`);
      return null;
    }
  });
  const items = res.filter((x) => x);
  if (!items.length) throw new Error("nessun dato di mercato: " + errors.join("; "));
  const payload = { generated_at: new Date().toISOString().slice(0, 19) + "+00:00", items, errors };
  const { error } = await sb.from("settings").upsert([{ key: "market_snapshot", value: JSON.stringify(payload) }], { onConflict: "key" });
  if (error) throw new Error(error.message);
  return { ok: items.length, errors };
}

const dec = (s: string) =>
  s.replace(/<!\[CDATA\[|\]\]>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").trim();
async function search(query: string, edition: string) {
  const [hl, gl, ceid] = edition === "it" ? ["it", "IT", "IT:it"] : ["en-US", "US", "US:en"];
  const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query + " when:2d")}&hl=${hl}&gl=${gl}&ceid=${ceid}`;
  const r = await fetch(url, { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const xml = await r.text();
  const out: { title: string; source: string; date: string; link: string }[] = [];
  const seen = new Set<string>();
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const b = m[1];
    let title = dec(/<title>([\s\S]*?)<\/title>/.exec(b)?.[1] || "");
    const src = dec(/<source[^>]*>([\s\S]*?)<\/source>/.exec(b)?.[1] || "");
    if (src && title.endsWith(" - " + src)) title = title.slice(0, -(src.length + 3)).trim();
    const key = title.toLowerCase().replace(/\W+/g, " ").slice(0, 80);
    const t = Date.parse(/<pubDate>([\s\S]*?)<\/pubDate>/.exec(b)?.[1] || "");
    if (!title || seen.has(key) || isNaN(t) || Date.now() - t > 48 * 3600e3) continue;
    seen.add(key);
    out.push({ title, source: src, date: new Date(t).toISOString().slice(0, 16) + "+00:00", link: dec(/<link>([\s\S]*?)<\/link>/.exec(b)?.[1] || "") });
    if (out.length >= 5) break;
  }
  return out;
}
function cleanName(n: string) {
  return n.replace(/\(.*?\)/g, "").replace(/\s+(Class\s+)?[AB]$/, "").trim();
}
async function news() {
  const { data: hold, error: he } = await sb.from("holdings").select("name,asset,geo");
  if (he) throw new Error(he.message);
  const targets: [string, string, string][] = [];
  const seen = new Set<string>();
  for (const h of hold || []) {
    if (h.asset !== "Azione" && h.asset !== "Crypto") continue;
    const label = cleanName(h.name || "");
    if (!label || seen.has(label.toLowerCase())) continue;
    seen.add(label.toLowerCase());
    targets.push([label, label + (h.asset === "Crypto" ? " crypto" : ""), h.geo === "USA" || h.geo === "Crypto" ? "en" : "it"]);
  }
  targets.push(...TOPICS);
  const errors: string[] = [];
  const items = await inBatches(targets, 4, async ([label, q, ed]) => {
    try { return { label, news: await search(q, ed) }; }
    catch (e) { errors.push(`${label}: ${String((e as Error).message).slice(0, 60)}`); return { label, news: [] }; }
  });
  if (!items.some((i) => i.news.length)) throw new Error("nessuna notizia scaricata: " + errors.join("; "));
  const payload = { generated_at: new Date().toISOString().slice(0, 19) + "+00:00", items, errors };
  const { error } = await sb.from("settings").upsert([{ key: "company_news", value: JSON.stringify(payload) }], { onConflict: "key" });
  if (error) throw new Error(error.message);
  return { ok: items.length, errors };
}

Deno.serve(async (req: Request) => {
  const { data: expected } = await sb.rpc("get_feed_token");
  const given = req.headers.get("x-feed-token") || "";
  if (!expected || given.length !== expected.length || given !== expected) return new Response("non autorizzato", { status: 401 });
  const only = new URL(req.url).searchParams.get("only");
  const out: Record<string, unknown> = {};
  for (const [k, fn] of [["markets", markets], ["news", news]] as [string, () => Promise<unknown>][]) {
    if (only && only !== k) continue;
    try { out[k] = await fn(); } catch (e) { out[k] = { error: String((e as Error).message) }; }
  }
  return new Response(JSON.stringify(out), { headers: { "Content-Type": "application/json" } });
});
