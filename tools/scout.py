#!/usr/bin/env python3
"""
Corgi's scout: Robinhood Chain tokens + Robinhood news, as JSON on stdout.

Never invents values: anything a source does not return is null. Derived fields
(pair_age_hours, changes vs. the previous run) are computed only from returned data.

Sources (all free, no API key):
  - GeckoTerminal API v2      network id "robinhood"   (pools by 24h volume, new pools)
  - DexScreener API           chain id   "robinhood"   (market cap, pair URL, socials, profiles)
  - Blockscout                robinhoodchain.blockscout.com/api/v2 (holder counts; rate-limited)
  - Robinhood newsroom        robinhood.com/us/en/newsroom/ (embedded Next.js data)
  - Google News RSS           Robinhood / HOOD / Robinhood Chain queries
  - CoinDesk RSS              filtered for "Robinhood"

Usage:
  python3 tools/scout.py                 # print JSON, save latest + history snapshot
  python3 tools/scout.py --no-save       # print only
  python3 tools/scout.py --quick         # fewer pages, no holder lookups (~10 s)
  python3 tools/scout.py --summary       # also print a short human summary to stderr
"""
import argparse, email.utils, html, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DATA_DIR = os.environ.get("CORGI_DATA_DIR", "/workspace/corgi-data")
UA = "Mozilla/5.0 (X11; Linux x86_64) CorgiScout/0.2 (+https://github.com/0xrenny/corgi)"
GT = "https://api.geckoterminal.com/api/v2"
DS = "https://api.dexscreener.com"
BS = "https://robinhoodchain.blockscout.com/api/v2"
NETWORK = "robinhood"

# Base tokens that are not memecoins (stables, wrapped majors). Kept out of the
# memecoin lists but reported under "majors" so nothing is silently dropped.
MAJORS = {"WETH", "ETH", "USDG", "USDC", "USDT", "SUSD", "DAI", "WBTC", "CBBTC", "USDE", "PYUSD", "FRAX", "USDS", "WSTETH", "STETH"}

SOURCES = {}
_last_call = {}


def now():
    return datetime.now(TZ)


def iso(dt):
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def note(name, ok, url=None, error=None, count=None):
    s = SOURCES.setdefault(name, {"ok": True, "calls": 0, "errors": [], "url": url, "items": 0})
    s["calls"] += 1
    if not ok:
        s["ok"] = False
        s["errors"].append(str(error)[:200])
    if count:
        s["items"] += count


def fetch(url, kind="json", min_interval=0.0, host_key=None, headers=None, retries=2):
    """GET with polite pacing per host and simple retry on 429/5xx. Returns parsed body or raises."""
    key = host_key or urllib.parse.urlparse(url).netloc
    wait = _last_call.get(key, 0) + min_interval - time.time()
    if wait > 0:
        time.sleep(wait)
    h = {"User-Agent": UA, "Accept": "application/json" if kind == "json" else "*/*"}
    h.update(headers or {})
    err = None
    for attempt in range(retries + 1):
        try:
            _last_call[key] = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
                body = r.read()
            return json.loads(body) if kind == "json" else body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1) + (10 if e.code == 429 else 0))
                continue
            raise
        except Exception as e:  # network errors
            err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise err


def num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def parse_ts(v):
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------- tokens

def gt_pools(path, pages):
    out = []
    for page in range(1, pages + 1):
        url = f"{GT}/networks/{NETWORK}/{path}{'&' if '?' in path else '?'}include=base_token,quote_token,dex&page={page}"
        try:
            d = fetch(url, min_interval=2.2, host_key="gt")  # free tier ~30 calls/min
        except Exception as e:
            note("geckoterminal", False, url, e)
            break
        inc = {i["id"]: i for i in d.get("included", [])}
        rows = d.get("data", [])
        note("geckoterminal", True, url, count=len(rows))
        for p in rows:
            out.append(gt_pool_record(p, inc))
        if len(rows) < 20:
            break
    return out


def gt_pool_record(p, inc):
    a, rel = p.get("attributes", {}), p.get("relationships", {})
    def tok(k):
        tid = ((rel.get(k) or {}).get("data") or {}).get("id")
        t = (inc.get(tid) or {}).get("attributes", {})
        addr = t.get("address") or (tid.split("_", 1)[1] if tid and "_" in tid else None)
        return {"address": addr, "name": t.get("name"), "symbol": t.get("symbol")}
    base, quote = tok("base_token"), tok("quote_token")
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id")
    pc = a.get("price_change_percentage") or {}
    tx = (a.get("transactions") or {}).get("h24") or {}
    vol = a.get("volume_usd") or {}
    created = parse_ts(a.get("pool_created_at"))
    pool = a.get("address")
    return {
        "symbol": base["symbol"], "name": base["name"], "contract": base["address"],
        "quote_symbol": quote["symbol"], "pool_name": a.get("name"), "pool_address": pool, "dex": dex,
        "price_usd": num(a.get("base_token_price_usd")),
        "volume_24h_usd": num(vol.get("h24")), "volume_1h_usd": num(vol.get("h1")),
        "liquidity_usd": num(a.get("reserve_in_usd")),
        "market_cap_usd": num(a.get("market_cap_usd")), "fdv_usd": num(a.get("fdv_usd")),
        "change_1h_pct": num(pc.get("h1")), "change_24h_pct": num(pc.get("h24")),
        "buys_24h": tx.get("buys"), "sells_24h": tx.get("sells"),
        "pair_created_at": iso(created),
        "pair_age_hours": round((now() - created).total_seconds() / 3600, 1) if created else None,
        "urls": {
            "geckoterminal": f"https://www.geckoterminal.com/{NETWORK}/pools/{pool}" if pool else None,
            "dexscreener": f"https://dexscreener.com/{NETWORK}/{pool}" if pool else None,
        },
        "market_cap_source": "geckoterminal" if num(a.get("market_cap_usd")) is not None else None,
    }


def best_per_token(pools):
    """One row per base token: the pool with the highest 24h volume, plus how many pools we saw."""
    by = {}
    for p in pools:
        k = (p["contract"] or p["pool_address"] or "").lower()
        if not k:
            continue
        g = by.setdefault(k, {"pools": [], "best": None})
        if any(x["pool_address"] == p["pool_address"] for x in g["pools"]):
            continue
        g["pools"].append(p)
        if g["best"] is None or (p["volume_24h_usd"] or 0) > (g["best"]["volume_24h_usd"] or 0):
            g["best"] = p
    rows = []
    for g in by.values():
        r = dict(g["best"])
        vols = [x["volume_24h_usd"] for x in g["pools"] if x["volume_24h_usd"] is not None]
        r["pools_seen"] = len(g["pools"])
        r["volume_24h_usd_all_seen_pools"] = round(sum(vols), 2) if vols else None
        rows.append(r)
    return rows


def flags(r):
    f = []
    if r["liquidity_usd"] == 0:
        f.append("liquidity_reported_zero")  # often v4 hooks / bonding curves the indexer can't price
    if r["liquidity_usd"] and r["volume_24h_usd"] and r["volume_24h_usd"] > 50 * r["liquidity_usd"]:
        f.append("volume_over_50x_liquidity")  # possible wash trading / bot churn
    if r["buys_24h"] and r["sells_24h"] and r["sells_24h"] > 2 * r["buys_24h"]:
        f.append("sells_over_2x_buys")
    if r["change_24h_pct"] is not None and r["change_24h_pct"] <= -90:
        f.append("price_down_over_90pct_24h")  # likely rug / dump
    if r.get("holders") is not None and r["holders"] < 200 and (r["volume_24h_usd"] or 0) > 1e6:
        f.append("few_holders_for_volume")  # big volume, tiny holder base
    if r["pair_age_hours"] is not None and r["pair_age_hours"] < 24:
        f.append("under_24h_old")
    return f


def ds_enrich(rows):
    addrs = [r["contract"] for r in rows if r.get("contract")]
    info = {}
    for i in range(0, len(addrs), 30):
        url = f"{DS}/tokens/v1/{NETWORK}/" + ",".join(addrs[i:i + 30])
        try:
            d = fetch(url, min_interval=0.3)
            note("dexscreener", True, url, count=len(d))
        except Exception as e:
            note("dexscreener", False, url, e)
            continue
        for p in d:
            a = ((p.get("baseToken") or {}).get("address") or "").lower()
            cur = info.get(a)
            if cur is None or (num((p.get("volume") or {}).get("h24")) or 0) > (num((cur.get("volume") or {}).get("h24")) or 0):
                info[a] = p
    for r in rows:
        p = info.get((r.get("contract") or "").lower())
        r["dexscreener"] = None
        if not p:
            continue
        links = [{"type": s.get("type"), "url": s.get("url")} for s in ((p.get("info") or {}).get("socials") or [])]
        links += [{"type": "website", "url": w.get("url")} for w in ((p.get("info") or {}).get("websites") or [])]
        r["dexscreener"] = {
            "pair_url": p.get("url"), "market_cap_usd": num(p.get("marketCap")), "fdv_usd": num(p.get("fdv")),
            "volume_24h_usd": num((p.get("volume") or {}).get("h24")), "liquidity_usd": num((p.get("liquidity") or {}).get("usd")),
            "pair_created_at": iso(parse_ts(p.get("pairCreatedAt"))), "links": links or None,
        }
        if r["market_cap_usd"] is None and num(p.get("marketCap")) is not None:
            r["market_cap_usd"] = num(p.get("marketCap"))
            r["market_cap_source"] = "dexscreener"


def ds_profiles():
    out = []
    for path, label in (("token-profiles/latest/v1", "profile"), ("token-boosts/latest/v1", "boost")):
        url = f"{DS}/{path}"
        try:
            d = fetch(url, min_interval=0.3)
            rows = [x for x in d if x.get("chainId") == NETWORK]
            note("dexscreener", True, url, count=len(rows))
            for x in rows:
                out.append({"kind": label, "contract": x.get("tokenAddress"), "url": x.get("url"),
                            "description": x.get("description"), "boost_amount": x.get("amount"),
                            "links": [{"type": l.get("type") or l.get("label"), "url": l.get("url")} for l in (x.get("links") or [])] or None})
        except Exception as e:
            note("dexscreener", False, url, e)
    return out


def bs_holders(rows, limit):
    for r in rows[:limit]:
        r.setdefault("holders", None)
        if not r.get("contract"):
            continue
        url = f"{BS}/tokens/{r['contract']}"
        try:
            d = fetch(url, min_interval=1.2, retries=1)
            r["holders"] = int(d["holders_count"]) if d.get("holders_count") not in (None, "") else None
            note("blockscout", True, url, count=1)
        except Exception as e:
            note("blockscout", False, url, e)
    for r in rows[limit:]:
        r.setdefault("holders", None)


def chain_stats():
    url = f"{BS}/stats"
    try:
        d = fetch(url)
        note("blockscout", True, url, count=1)
        return {"total_transactions": num(d.get("total_transactions")), "transactions_today": num(d.get("transactions_today")),
                "total_addresses": num(d.get("total_addresses")), "average_block_time_ms": num(d.get("average_block_time")),
                "eth_price_usd": num(d.get("coin_price")), "source": url}
    except Exception as e:
        note("blockscout", False, url, e)
        return None


# ---------------------------------------------------------------- news

def news_newsroom():
    url = "https://robinhood.com/us/en/newsroom/"
    try:
        h = fetch(url, kind="text")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        items = json.loads(m.group(1))["props"]["pageProps"]["articlesCollection"]["items"]
        out = []
        for it in items:
            f = it.get("fields", it)
            if not f.get("slug") or not f.get("title"):
                continue
            out.append({"title": f["title"].strip(), "url": f"https://robinhood.com/us/en/newsroom/{f['slug']}/",
                        "published_at": iso(parse_ts(f.get("publishDate"))), "source": "Robinhood Newsroom", "official": True})
        note("robinhood_newsroom", True, url, count=len(out))
        return out
    except Exception as e:
        note("robinhood_newsroom", False, url, e)
        return []


def rss(url, name, must_match=None, official=False):
    try:
        root = ET.fromstring(fetch(url, kind="text", min_interval=1.0))
    except Exception as e:
        note(name, False, url, e)
        return []
    out = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        desc = it.findtext("description") or ""
        if must_match and not re.search(must_match, title + " " + desc, re.I):
            continue
        src = it.find("source")
        pub = it.findtext("pubDate")
        try:
            pub_dt = email.utils.parsedate_to_datetime(pub) if pub else None
        except Exception:
            pub_dt = None
        out.append({"title": title, "url": (it.findtext("link") or "").strip() or None, "published_at": iso(pub_dt),
                    "source": (src.text.strip() if src is not None and src.text else name), "official": official})
    note(name, True, url, count=len(out))
    return out


def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def collect_news(max_age_days, limit):
    items = news_newsroom()
    for q in ('Robinhood when:2d', '"Robinhood Chain" when:7d', 'HOOD stock Robinhood when:2d', 'Robinhood crypto when:3d'):
        items += rss(gnews(q), "google_news")
    items += rss("https://www.coindesk.com/arc/outboundfeeds/rss/", "coindesk", must_match=r"robinhood|\bHOOD\b")
    cutoff = now() - timedelta(days=max_age_days)
    seen, out = set(), []
    for n in items:
        t = n["title"]
        # Google News titles end with " - Publisher"; drop it for matching.
        if n["source"] and t.endswith(" - " + n["source"]):
            t = t[: -len(n["source"]) - 3]
        n["title"] = t
        # Robinhood's own prediction-market listing pages show up as "news"; skip them.
        if n["source"] == "Robinhood" and re.search(r"prediction market", t, re.I):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:90]
        if not key or key in seen:
            continue
        seen.add(key)
        pub = parse_ts(n["published_at"])
        if not n["official"] and pub and pub < cutoff:
            continue
        n["robinhood_chain"] = bool(re.search(r"robinhood chain", t, re.I))
        out.append(n)
    out.sort(key=lambda n: n["published_at"] or "", reverse=True)
    official = [n for n in out if n["official"]][:5]
    rest = [n for n in out if not n["official"]][: max(0, limit - len(official))]
    return sorted(official + rest, key=lambda n: n["published_at"] or "", reverse=True)


# ---------------------------------------------------------------- compare

def latest_previous():
    hist = os.path.join(DATA_DIR, "history")
    if not os.path.isdir(hist):
        return None
    files = sorted(f for f in os.listdir(hist) if f.endswith(".json"))
    if not files:
        return None
    try:
        with open(os.path.join(hist, files[-1]), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def pct(a, b):
    return round((a - b) / b * 100, 1) if a is not None and b not in (None, 0) else None


def compare(cur, prev):
    if not prev:
        return None
    pt = {(t.get("contract") or "").lower(): t for t in prev.get("top_tokens", []) + prev.get("new_tokens", [])}
    ct = {(t.get("contract") or "").lower(): t for t in cur["top_tokens"] + cur["new_tokens"]}
    moves = []
    for k, t in ct.items():
        p = pt.get(k)
        if p:
            moves.append({"symbol": t["symbol"], "contract": t["contract"],
                          "price_change_since_last_pct": pct(t["price_usd"], p.get("price_usd")),
                          "volume_24h_change_since_last_pct": pct(t["volume_24h_usd"], p.get("volume_24h_usd"))})
    prev_rank = [(t.get("contract") or "").lower() for t in prev.get("top_tokens", [])]
    cur_rank = [(t.get("contract") or "").lower() for t in cur["top_tokens"]]
    prev_news = {n.get("url") for n in prev.get("news", [])}
    return {
        "previous_generated_at": prev.get("generated_at"),
        "entered_top": [t["symbol"] for t in cur["top_tokens"] if (t["contract"] or "").lower() not in prev_rank],
        "left_top": [t.get("symbol") for t in prev.get("top_tokens", []) if (t.get("contract") or "").lower() not in cur_rank],
        "token_moves": moves,
        "new_headlines": [n["title"] for n in cur["news"] if n["url"] not in prev_news],
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=15, help="memecoins to keep in top_tokens")
    ap.add_argument("--volume-pages", type=int, default=3, help="GeckoTerminal pages (20 pools each) sorted by 24h volume")
    ap.add_argument("--new-pages", type=int, default=3, help="GeckoTerminal new_pools pages")
    ap.add_argument("--new-hours", type=float, default=48, help="max pair age for new_tokens")
    ap.add_argument("--min-new-volume", type=float, default=10000, help="min 24h USD volume for new_tokens")
    ap.add_argument("--holders", type=int, default=10, help="look up holder counts on Blockscout for the first N tokens (0 = off)")
    ap.add_argument("--news", type=int, default=20)
    ap.add_argument("--news-days", type=float, default=3)
    ap.add_argument("--quick", action="store_true", help="1 page each, no holder lookups")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--summary", action="store_true", help="print a short human summary to stderr")
    ap.add_argument("--keep-history", type=int, default=1000, help="max snapshots kept in history/")
    a = ap.parse_args()
    if a.quick:
        a.volume_pages, a.new_pages, a.holders = 1, 1, 0

    started = now()
    pools = gt_pools("pools?sort=h24_volume_usd_desc", a.volume_pages)
    pools += gt_pools("new_pools", a.new_pages)
    tokens = best_per_token(pools)
    majors = sorted([t for t in tokens if (t["symbol"] or "").upper() in MAJORS], key=lambda t: t["volume_24h_usd"] or 0, reverse=True)
    memes = [t for t in tokens if (t["symbol"] or "").upper() not in MAJORS]
    memes.sort(key=lambda t: t["volume_24h_usd"] or 0, reverse=True)
    top = memes[: a.top]
    new = [t for t in memes if t["pair_age_hours"] is not None and t["pair_age_hours"] <= a.new_hours
           and (t["volume_24h_usd"] or 0) >= a.min_new_volume]
    new.sort(key=lambda t: t["volume_24h_usd"] or 0, reverse=True)
    new = new[:15]

    uniq = {id(t): t for t in top + new}
    sel = list(uniq.values())
    ds_enrich(sel)
    if a.holders:
        bs_holders(sorted(sel, key=lambda t: t["volume_24h_usd"] or 0, reverse=True), a.holders)
    for t in sel:
        t.setdefault("holders", None)
        t["flags"] = flags(t)

    out = {
        "schema_version": 1,
        "generated_at": iso(started),
        "duration_s": None,
        "network": {"name": "Robinhood Chain", "geckoterminal_id": NETWORK, "dexscreener_id": NETWORK,
                    "explorer": "https://robinhoodchain.blockscout.com"},
        "chain_stats": chain_stats(),
        "params": {k: v for k, v in vars(a).items() if k not in ("no_save", "summary")},
        "top_tokens": top,
        "new_tokens": new,
        "majors": [{k: t[k] for k in ("symbol", "contract", "pool_name", "price_usd", "volume_24h_usd", "liquidity_usd", "urls")} for t in majors[:5]],
        "dexscreener_profiles": ds_profiles(),
        "news": collect_news(a.news_days, a.news),
        "sources": SOURCES,
        "notes": [
            "volume_24h_usd, liquidity_usd, price, fdv and change come from the single highest-volume pool GeckoTerminal returned for that token.",
            "market_cap_usd is null unless GeckoTerminal or DexScreener reports it; it is never computed here.",
            "liquidity_reported_zero usually means the indexer cannot price that pool (e.g. Uniswap v4 hooks / bonding curves), not that it is empty.",
        ],
    }
    prev = latest_previous()
    out["changes_vs_previous"] = compare(out, prev)
    out["duration_s"] = round((now() - started).total_seconds(), 1)

    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if not a.no_save:
        hist = os.path.join(DATA_DIR, "history")
        os.makedirs(hist, exist_ok=True)
        with open(os.path.join(DATA_DIR, "scout-latest.json"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        with open(os.path.join(hist, "scout-" + started.strftime("%Y%m%dT%H%M%S%z") + ".json"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        files = sorted(f for f in os.listdir(hist) if f.endswith(".json"))
        for f in files[: max(0, len(files) - a.keep_history)]:
            os.remove(os.path.join(hist, f))
    if a.summary:
        def m(v):
            return "n/a" if v is None else (f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.1f}k" if v >= 1e3 else f"${v:.0f}")
        print(f"[scout] {out['generated_at']}  {out['duration_s']}s", file=sys.stderr)
        for t in top[:10]:
            print(f"  {t['symbol']:<10} vol {m(t['volume_24h_usd']):>9}  liq {m(t['liquidity_usd']):>9}  mcap {m(t['market_cap_usd']):>9}  24h {t['change_24h_pct']}%  age {t['pair_age_hours']}h  {','.join(t['flags'])}", file=sys.stderr)
        print(f"  new (<= {a.new_hours:g}h, >= {m(a.min_new_volume)}): " + ", ".join(t["symbol"] or "?" for t in new), file=sys.stderr)
        for n in out["news"][:6]:
            print(f"  [{n['published_at']}] {n['title']} ({n['source']})", file=sys.stderr)
        bad = {k: v["errors"][:1] for k, v in SOURCES.items() if not v["ok"]}
        if bad:
            print(f"  source errors: {bad}", file=sys.stderr)


if __name__ == "__main__":
    main()
