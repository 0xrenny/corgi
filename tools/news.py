#!/usr/bin/env python3
"""
Corgi's crypto/web3 news sniff: top headlines from free RSS/Atom feeds, deduped and ranked.

Never invents anything: titles, links, sources and times come straight from the feeds.
The only computed fields are the cluster (same story in several outlets), the score and
the reasons behind it.

Sources (free, no key; checked 2026-10-11):
  CoinDesk       https://www.coindesk.com/arc/outboundfeeds/rss/
  The Block      https://www.theblock.co/rss.xml
  Decrypt        https://decrypt.co/feed
  Cointelegraph  https://cointelegraph.com/rss
Checked but not used: Blockworks https://blockworks.co/feed (Atom, answers but stale: newest item Jan 2026).
Not usable without a paid key: CoinGecko /news (PRO only, 401), CryptoPanic API (paid plans only, 404 on free paths).

Usage:
  python3 tools/news.py                    # JSON on stdout + $CORGI_DATA_DIR/news-latest.json
  python3 tools/news.py --summary          # also a short list on stderr
  python3 tools/news.py --entry > /tmp/news.json   # ready-to-edit "news" diary entry (fill the takes!)
Options: --hours 24 --top 3 --no-save --include-published
"""
import argparse, email.utils, html, json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CORGI_DATA_DIR", "/workspace/corgi-data"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 CorgiNews/0.1"
FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]
# Words that tend to mark market-moving / ecosystem-wide stories (weights are a heuristic, documented in README).
WEIGHTS = {
    "sec": 3, "etf": 3, "hack": 3, "hacked": 3, "exploit": 3, "exploited": 3, "drained": 3, "stolen": 3, "fed": 2, "rate": 1,
    "stablecoin": 2, "stablecoins": 2, "regulation": 2, "regulator": 2, "lawsuit": 2, "court": 2, "bill": 2, "congress": 2,
    "bitcoin": 2, "btc": 2, "ethereum": 2, "eth": 1, "solana": 1, "binance": 2, "coinbase": 2, "robinhood": 3, "blackrock": 2,
    "billion": 2, "record": 1, "all-time": 2, "liquidations": 2, "liquidated": 2, "outage": 2, "bankruptcy": 3, "arrested": 2,
    "losses": 2, "breach": 3, "attack": 2, "vulnerability": 2, "crash": 1, "cftc": 2, "launch": 1, "launches": 1, "approval": 2, "approves": 2, "ban": 2, "tariff": 2, "treasury": 1, "airdrop": 1,
}
DOWNRANK = re.compile(r"\b(sponsored|press release|price prediction|price analysis|how to|what is|explained|podcast|newsletter|weekly recap|daily recap|quiz)\b", re.I)
STOP = set("the a an and or of to in on for with by as at is are was be from its it this that new says after amid over into up out vs how why what will could would can than more most about".split())
SOURCES = {}


def now():
    return datetime.now(TZ)


def iso(d):
    return d.astimezone(TZ).isoformat(timespec="seconds")


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fetch_feed(name, url):
    src = SOURCES.setdefault(name, {"url": url, "ok": False, "items": 0, "error": None})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
        root = ET.fromstring(body)
    except Exception as e:
        src["error"] = str(e)[:200]
        return []
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(f".//{atom}entry")
    for it in nodes:
        if it.tag.startswith(atom):
            title = clean(it.findtext(f"{atom}title"))
            link = next((l.get("href") for l in it.findall(f"{atom}link") if l.get("rel") in (None, "alternate")), None)
            pub = parse_date(it.findtext(f"{atom}published") or it.findtext(f"{atom}updated"))
            summary = clean(it.findtext(f"{atom}summary") or "")
            cats = [c.get("term") or "" for c in it.findall(f"{atom}category")]
        else:
            title = clean(it.findtext("title"))
            link = (it.findtext("link") or "").strip() or None
            pub = parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
            summary = clean(it.findtext("description") or "")
            cats = [clean(c.text) for c in it.findall("category")]
        if not title or not link or not link.startswith("https://") or not pub:
            continue
        out.append({"title": title, "url": link.split("?utm")[0], "source": name, "published_at": pub,
                    "summary": summary[:300], "categories": [c for c in cats if c][:8]})
    src["ok"] = bool(out)
    src["items"] = len(out)
    if not out and not src["error"]:
        src["error"] = "feed parsed but had no usable items"
    return out


def words(t):
    t = re.sub(r"['’]s\b", "", t.lower())
    return {w for w in re.findall(r"[a-z0-9$][a-z0-9$\-]+", t) if w not in STOP and len(w) > 2}


def published_urls():
    try:
        log = json.loads((ROOT / "data/log.json").read_text("utf-8"))
    except Exception:
        return set()
    return {i.get("url") for e in log.get("entries", []) if e.get("kind") == "news" for i in e.get("items") or []}


def rank(items, hours, top, skip_urls):
    t0 = now()
    fresh = [i for i in items if t0 - i["published_at"] <= timedelta(hours=hours) and i["published_at"] <= t0 + timedelta(minutes=10)]
    fresh.sort(key=lambda i: i["published_at"], reverse=True)
    clusters = []
    for it in fresh:
        w = words(it["title"])
        it["_w"] = w
        for c in clusters:
            inter = len(w & c["w"])
            if inter >= 4 or (inter >= 3 and inter / max(1, min(len(w), len(c["w"]))) >= 0.5):
                c["items"].append(it); c["w"] |= w; break
        else:
            clusters.append({"items": [it], "w": set(w)})
    scored = []
    for c in clusters:
        its = c["items"]
        if any(i["url"] in skip_urls for i in its):
            continue
        srcs = sorted({i["source"] for i in its})
        lead = min(its, key=lambda i: i["published_at"])  # credit whoever had it first
        kw = sum(WEIGHTS.get(x, 0) for x in words(lead["title"]) | {y.lower() for y in lead["categories"]})
        age_h = (t0 - max(i["published_at"] for i in its)).total_seconds() / 3600
        score = 4 * (len(srcs) - 1) + min(kw, 8) + max(0, 6 - age_h / 4)
        reasons = []
        if len(srcs) > 1: reasons.append(f"covered by {len(srcs)} outlets")
        if kw: reasons.append("market-moving keywords")
        if DOWNRANK.search(lead["title"]) or any(DOWNRANK.search(x) for x in lead["categories"]):
            score -= 8; reasons.append("downranked: explainer/opinion/sponsored")
        scored.append({
            "title": lead["title"], "source": lead["source"], "url": lead["url"], "published_at": iso(lead["published_at"]),
            "summary": lead["summary"], "score": round(score, 2), "reasons": reasons,
            "also_covered_by": [{"source": i["source"], "title": i["title"], "url": i["url"], "published_at": iso(i["published_at"])} for i in its if i is not lead][:5],
        })
    scored.sort(key=lambda s: s["score"], reverse=True)
    # at most one story per outlet in the top picks, so the list isn't one feed's homepage
    top_list, used = [], {}
    for s in scored:
        if used.get(s["source"], 0) >= 1 and len(scored) > top * 2:
            continue
        top_list.append(s); used[s["source"]] = used.get(s["source"], 0) + 1
        if len(top_list) == top:
            break
    return top_list, scored, len(fresh)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--entry", action="store_true", help="print a ready-to-edit 'news' diary entry instead")
    ap.add_argument("--include-published", action="store_true", help="don't skip stories already in data/log.json")
    a = ap.parse_args()
    items = []
    for name, url in FEEDS:
        items += fetch_feed(name, url)
        time.sleep(0.3)
    skip = set() if a.include_published else published_urls()
    top, allc, n_fresh = rank(items, a.hours, a.top, skip)
    if len(top) < a.top and a.hours < 48:  # quiet day (weekends): widen once
        a.hours = 48
        top, allc, n_fresh = rank(items, a.hours, a.top, skip)
    doc = {"generated_at": iso(now()), "window_hours": a.hours, "items_fetched": len(items), "items_in_window": n_fresh,
           "stories": len(allc), "top": top, "next": allc[len(top):len(top) + 7], "sources": SOURCES}
    if not a.no_save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "news-latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), "utf-8")
    if a.summary:
        for k, v in SOURCES.items():
            print(f"{'ok ' if v['ok'] else 'ERR'} {k}: {v['items']} items {v['error'] or ''}", file=sys.stderr)
        for s in top:
            print(f"- [{s['score']}] {s['source']} {s['published_at'][11:16]}: {s['title']} ({', '.join(s['reasons'])})", file=sys.stderr)
    if a.entry:
        entry = {"kind": "news", "text": "TODO: my short take on today's news, in my own words",
                 "items": [{"title": s["title"], "source": s["source"], "url": s["url"], "published_at": s["published_at"], "take": "TODO: one line"} for s in top],
                 "tools": [{"name": "news.rss", "input": ", ".join(k for k, v in SOURCES.items() if v["ok"])}]}
        print(json.dumps({"entries": [entry]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    if not any(v["ok"] for v in SOURCES.values()):
        sys.exit(2)


if __name__ == "__main__":
    main()
