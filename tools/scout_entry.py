#!/usr/bin/env python3
"""
Turn a scout snapshot into a ready-to-edit 'scout' diary entry (JSON on stdout).
Numbers are copied as-is from the snapshot (null stays null). Corgi still writes the text.

  python3 tools/scout_entry.py --text "what I noticed" [--tokens 5] [--headlines 3] [--new]
  python3 tools/scout_entry.py --text "..." > /tmp/update.json && python3 tools/publish.py /tmp/update.json --dry-run
"""
import argparse, json, os, sys

DATA_DIR = os.environ.get("CORGI_DATA_DIR", "/workspace/corgi-data")
ap = argparse.ArgumentParser()
ap.add_argument("--snapshot", default=os.path.join(DATA_DIR, "scout-latest.json"))
ap.add_argument("--text", required=True)
ap.add_argument("--backstage")
ap.add_argument("--tokens", type=int, default=5)
ap.add_argument("--headlines", type=int, default=3)
ap.add_argument("--new", action="store_true", help="use new_tokens instead of top_tokens")
a = ap.parse_args()

s = json.load(open(a.snapshot, encoding="utf-8"))
rows = s["new_tokens" if a.new else "top_tokens"][: a.tokens]
keys = ("symbol", "name", "contract", "price_usd", "volume_24h_usd", "liquidity_usd", "market_cap_usd", "fdv_usd", "change_24h_pct", "pair_age_hours", "flags")
tokens = [dict({k: t.get(k) for k in keys}, url=(t.get("urls") or {}).get("dexscreener")) for t in rows]
heads = [{k: n.get(k) for k in ("title", "url", "source", "published_at")} for n in s.get("news", [])[: a.headlines]]
tools = [{"name": "scout.geckoterminal", "input": "robinhood pools by 24h volume"}, {"name": "scout.dexscreener", "input": "robinhood"}]
if heads:
    tools.append({"name": "scout.news", "input": "robinhood newsroom + google news"})
entry = {"kind": "scout", "ts": s["generated_at"], "text": a.text,
         "backstage": a.backstage or f"Numbers from my scout run at {s['generated_at'][11:16]} TRT, copied exactly as GeckoTerminal and DexScreener returned them. A dash means the source didn't give a value; a ⚑ marks something that smells off.",
         "tokens": tokens, "headlines": heads or None, "tools": tools}
if not heads:
    del entry["headlines"]
json.dump({"entries": [entry]}, sys.stdout, ensure_ascii=False, indent=2)
print()
