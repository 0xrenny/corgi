#!/usr/bin/env python3
"""
Corgi's paper copy-trading experiment: follow 8 Robinhood Chain wallets, mirror their
swaps on paper from a $100 bankroll, publish everything to data/copy.json.

PAPER ONLY. No wallet, no keys, no real orders. Every copied trade points at the real
on-chain transaction it copied. Nothing is invented: a value no source returned is
null, a swap that can't be priced is recorded as skipped, a failed source is logged.

Commands:
  python3 tools/copybot.py select [--force]   # one-time: pick the 8 wallets, start the experiment
  python3 tools/copybot.py run                # each wake: copy new swaps, mark to market, commit + push
  python3 tools/copybot.py run --no-push      # commit locally only
  python3 tools/copybot.py run --no-git       # write data/copy.json only
  python3 tools/copybot.py run --dry-run      # compute and print the summary, write nothing

Sources (free, no key):
  GeckoTerminal v2 (network "robinhood"): top pools, pool trades (signer address per swap),
      OHLCV candles for fill prices, simple token prices for marks. ~30 calls/min.
  Blockscout robinhoodchain.blockscout.com/api/v2: per-wallet ERC-20 transfers (what the
      wallet actually swapped, with tx hashes), address info (contract? tags?).
  DexScreener: token -> most liquid pool lookup (batch of 30).

Raw selection reports and caches live outside the repo in $CORGI_DATA_DIR/copy.
"""
import argparse, json, math, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
ROOT = Path(__file__).resolve().parent.parent
COPY = ROOT / "data/copy.json"
DATA_DIR = Path(os.environ.get("CORGI_DATA_DIR", "/workspace/corgi-data")) / "copy"
UA = "Mozilla/5.0 (X11; Linux x86_64) CorgiScout/0.2 (+https://github.com/0xrenny/corgi)"
GT = "https://api.geckoterminal.com/api/v2"
DS = "https://api.dexscreener.com"
BS = "https://robinhoodchain.blockscout.com/api/v2"
EXPLORER = "https://robinhoodchain.blockscout.com"
NET = "robinhood"

# Quote / non-meme tokens: these are the "money" side of a swap, never copied as positions.
QUOTE_SYMBOLS = {"WETH", "ETH", "USDG", "USDC", "USDT", "SUSD", "DAI", "WBTC", "CBBTC", "USDE", "PYUSD", "FRAX", "USDS", "WSTETH", "STETH"}
QUOTE_ADDRS = {"0x0bd7d308f8e1639fab988df18a8011f41eacad73", "0x5fc5360d0400a0fd4f2af552add042d716f1d168"}  # WETH, USDG

# ---- the rules of the experiment (also written into copy.json) ----
BANKROLL = 100.0
SIZE_PCT = 10.0            # each copied buy = 10% of current equity
MAX_TOKEN_PCT = 25.0       # never more than 25% of equity in one token (cost basis)
MIN_ORDER = 1.0            # skip buys smaller than $1
DELAY_S = 60               # we "react" 60 s after the wallet's transaction
SLIPPAGE_PCT = 1.0         # adverse price move on every fill
FEE_PCT = 1.0              # swap fee per side (memecoin pools are often 1%)
GAS_USD = 0.01             # per swap (Robinhood Chain is an L2; gas is cents)
N_WALLETS = 8
NICKNAMES = ["Beagle", "Husky", "Shiba", "Collie", "Poodle", "Dachshund", "Whippet", "Basenji"]

SOURCES = {}
_last = {}


def now():
    return datetime.now(TZ)


def iso(dt):
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def pts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def note(src, ok, err=None):
    s = SOURCES.setdefault(src, {"ok": True, "calls": 0, "failed_calls": 0, "errors": []})
    s["calls"] += 1
    if not ok:
        s["failed_calls"] += 1
        s["ok"] = False
        if len(s["errors"]) < 5:
            s["errors"].append(str(err)[:160])


def fetch(url, src, interval):
    wait = _last.get(src, 0) + interval - time.time()
    if wait > 0:
        time.sleep(wait)
    err = None
    for attempt in range(3):
        try:
            _last[src] = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read())
            note(src, True)
            return d
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(4 * (attempt + 1) + (12 if e.code == 429 else 0))
                continue
            break
        except Exception as e:
            err = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
    note(src, False, f"{err} @ {url.split('?')[0][-90:]}")
    return None


gt = lambda path: fetch(GT + path, "geckoterminal", 2.2)
bs = lambda path: fetch(BS + path, "blockscout", 0.6)


def short(a):
    return a[:6] + "…" + a[-4:]


# ------------------------------------------------------------------ prices

_pool_cache = {}


def pools_for(tokens):
    """token address -> {pool, symbol, name} via DexScreener (most liquid pair where it is the base)."""
    need = [t for t in tokens if t not in _pool_cache]
    for i in range(0, len(need), 30):
        chunk = need[i:i + 30]
        d = fetch(f"{DS}/tokens/v1/{NET}/{','.join(chunk)}", "dexscreener", 1.0)
        best = {}
        for p in d or []:
            b = (p.get("baseToken") or {})
            a = (b.get("address") or "").lower()
            liq = num((p.get("liquidity") or {}).get("usd")) or 0
            vol = num((p.get("volume") or {}).get("h24")) or 0
            score = (liq > 0, vol, liq)
            if a in chunk and (a not in best or score > best[a][0]):
                best[a] = (score, {"pool": p.get("pairAddress", "").lower(), "symbol": b.get("symbol"), "name": b.get("name")})
        for a in chunk:
            _pool_cache[a] = best[a][1] if a in best else None
    return {t: _pool_cache.get(t) for t in tokens}


_candles = {}


def candles(pool, token, tf, agg, since):
    """OHLCV (ts, close) ascending for `token` in `pool`, back to `since` (datetime)."""
    key = (pool, token, tf, agg)
    rows = _candles.get(key)
    if rows is None:
        rows, before = [], None
        for _ in range(4):
            q = f"/networks/{NET}/pools/{pool}/ohlcv/{tf}?aggregate={agg}&limit=1000&currency=usd&token={token}"
            if before:
                q += f"&before_timestamp={before}"
            d = gt(q)
            lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            if not lst:
                break
            rows.extend((int(r[0]), num(r[4])) for r in lst if num(r[4]))
            oldest = min(int(r[0]) for r in lst)
            if oldest <= since.timestamp() or len(lst) < 1000:
                break
            before = oldest
        rows = sorted(set(rows))
        _candles[key] = rows
    return rows


def price_at(rows, t, width):
    """Close of the candle containing t; else the last close before t. Returns (price, source)."""
    ts = t.timestamp()
    best = None
    for start, close in rows:
        if start <= ts:
            best = (start, close)
        else:
            break
    if not best:
        return None, None
    return best[1], ("candle" if ts - best[0] < width else "last_close_before")


def spot_prices(tokens):
    out = {}
    for i in range(0, len(tokens), 30):
        d = gt(f"/simple/networks/{NET}/token_price/{','.join(tokens[i:i+30])}")
        for k, v in ((((d or {}).get("data") or {}).get("attributes") or {}).get("token_prices") or {}).items():
            if num(v):
                out[k.lower()] = num(v)
    return out


# ------------------------------------------------------------------ swaps from Blockscout

def wallet_transfers(addr, stop_ts=None, stop_block=None, max_pages=6):
    """ERC-20 transfers of a wallet, newest first, until stop_ts / stop_block. Returns (items, complete)."""
    items, path, pages = [], f"/addresses/{addr}/token-transfers?type=ERC-20", 0
    while path and pages < max_pages:
        d = bs(path)
        pages += 1
        if d is None:
            return items, False
        for it in d.get("items", []):
            t = pts(it.get("timestamp"))
            if (stop_ts and t and t < stop_ts) or (stop_block and it.get("block_number", 0) <= stop_block):
                return items, True
            items.append(it)
        p = d.get("next_page_params")
        path = f"/addresses/{addr}/token-transfers?type=ERC-20&" + urllib.parse.urlencode(p) if p else None
    return items, path is None


def swaps_from_transfers(addr, items):
    """Group a wallet's transfers per transaction and turn them into buy/sell legs of non-quote tokens."""
    addr = addr.lower()
    by_tx = defaultdict(list)
    for it in items:
        by_tx[it["transaction_hash"].lower()].append(it)
    swaps, meta = [], {}
    for tx, its in by_tx.items():
        meme, quote = defaultdict(float), 0.0
        info = {}
        for it in its:
            tok = it.get("token") or {}
            ta = (tok.get("address_hash") or tok.get("address") or "").lower()
            sym = (tok.get("symbol") or "").upper()
            dec = int((it.get("total") or {}).get("decimals") or tok.get("decimals") or 18)
            val = num((it.get("total") or {}).get("value"))
            if val is None:
                continue
            amt = val / 10 ** dec
            f, t = (it.get("from") or {}), (it.get("to") or {})
            fa, tA = (f.get("hash") or "").lower(), (t.get("hash") or "").lower()
            sign = 1 if tA == addr else -1 if fa == addr else 0
            if sign == 0 or (fa == addr and tA == addr):
                continue
            other = f if sign == 1 else t
            if ta in QUOTE_ADDRS or sym in QUOTE_SYMBOLS:
                quote += sign * amt
                continue
            if not other.get("is_contract"):
                continue  # wallet-to-wallet transfer, not a swap
            meme[ta] += sign * amt
            info[ta] = {"symbol": tok.get("symbol"), "name": tok.get("name")}
            meta[tx] = (pts(it.get("timestamp")), it.get("block_number"))
        legs = [(k, v) for k, v in meme.items() if abs(v) > 0]
        if not legs:
            continue
        pos = [l for l in legs if l[1] > 0]
        neg = [l for l in legs if l[1] < 0]
        if len(legs) == 1:
            k, v = legs[0]
            if (v > 0 and quote > 1e-12) or (v < 0 and quote < -1e-12):
                continue  # token and quote moved the same way: liquidity add/remove, not a swap
        elif not (len(pos) == 1 and len(neg) == 1 and abs(quote) < 1e-12):
            continue  # multi-token / liquidity transaction: not a clean swap
        ts, blk = meta[tx]
        for k, v in legs:
            swaps.append({"tx": tx, "ts": ts, "block": blk, "token": k, "side": "buy" if v > 0 else "sell",
                          "qty": abs(v), "symbol": info[k]["symbol"], "name": info[k]["name"]})
    swaps.sort(key=lambda s: (s["ts"], s["block"]))
    return swaps


# ------------------------------------------------------------------ selection

def select(a):
    if COPY.exists() and not a.force:
        sys.exit("copybot: data/copy.json exists; the experiment already started (use --force to restart)")
    t0 = now()
    window_h = a.window_hours
    since = t0 - timedelta(hours=window_h)
    # 1. universe: top non-quote pools by 24h volume
    universe = []
    for page in (1, 2, 3):
        d = gt(f"/networks/{NET}/pools?sort=h24_volume_usd_desc&include=base_token&page={page}")
        inc = {i["id"]: i.get("attributes", {}) for i in (d or {}).get("included", [])}
        for p in (d or {}).get("data", []):
            at = p["attributes"]
            bid = p["relationships"]["base_token"]["data"]["id"]
            b = inc.get(bid, {})
            baddr = bid.split("_", 1)[1].lower()
            if (b.get("symbol") or "").upper() in QUOTE_SYMBOLS or baddr in QUOTE_ADDRS:
                continue
            universe.append({"pool": at["address"].lower(), "token": baddr, "symbol": b.get("symbol"),
                             "volume_24h_usd": num((at.get("volume_usd") or {}).get("h24"))})
    universe = universe[: a.pools]
    print(f"universe: {len(universe)} pools", file=sys.stderr)
    # 2. candidates: signers of recent >= $50 swaps in those pools
    seen = defaultdict(lambda: {"n": 0, "vol": 0.0, "pools": set(), "buys": 0, "sells": 0})
    for u in universe:
        _pool_cache[u["token"]] = {"pool": u["pool"], "symbol": u["symbol"], "name": None}
        d = gt(f"/networks/{NET}/pools/{u['pool']}/trades?trade_volume_in_usd_greater_than={a.min_trade_usd}")
        trades = [x["attributes"] for x in (d or {}).get("data", [])]
        u["trades_sampled"] = len(trades)
        for t in trades:
            w = (t.get("tx_from_address") or "").lower()
            s = seen[w]
            s["n"] += 1; s["vol"] += num(t.get("volume_in_usd")) or 0; s["pools"].add(u["pool"])
            s["buys" if t.get("kind") == "buy" else "sells"] += 1
    excluded = defaultdict(int)
    cands = []
    for w, s in seen.items():
        if s["n"] > a.max_sample_trades:
            excluded["bot_like_sample_frequency"] += 1; continue
        if s["n"] < 2:
            excluded["single_swap_in_sample"] += 1; continue
        # active, repeat traders first: breadth across pools, then activity, then size
        cands.append((len(s["pools"]), min(s["n"], 20), s["buys"] > 0 and s["sells"] > 0, s["vol"], w))
    cands.sort(reverse=True)
    cands = [c[-1] for c in cands[: a.candidates]]
    print(f"candidates: {len(cands)} (of {len(seen)} signers)", file=sys.stderr)
    # 3. per candidate: real history from Blockscout
    scored, reports = [], []
    for i, w in enumerate(cands):
        info = bs(f"/addresses/{w}")
        if info is None:
            excluded["blockscout_unavailable"] += 1; continue
        if info.get("is_contract"):
            excluded["is_contract"] += 1; continue
        if info.get("public_tags") or info.get("is_scam"):
            excluded["tagged_address"] += 1; continue
        items, complete = wallet_transfers(w, stop_ts=since, max_pages=a.pages)
        sw = swaps_from_transfers(w, items)
        rep = {"wallet": w, "swaps": len(sw), "complete_window": complete}
        if len(sw) < 4:
            excluded["too_few_swaps"] += 1; rep["excluded"] = "too_few_swaps"; reports.append(rep); continue
        span_h = max((sw[-1]["ts"] - sw[0]["ts"]).total_seconds() / 3600, 1.0)
        if len(sw) / span_h > a.max_swaps_per_hour:
            excluded["bot_like_swap_rate"] += 1; rep["excluded"] = "bot_like_swap_rate"; reports.append(rep); continue
        blk = defaultdict(set)
        for s in sw:
            blk[(s["block"], s["token"])].add(s["side"])
        if any(len(v) == 2 for v in blk.values()):
            excluded["same_block_round_trip"] += 1; rep["excluded"] = "same_block_round_trip"; reports.append(rep); continue
        reports.append(rep)
        scored.append((w, sw, span_h))
        print(f"  [{i+1}/{len(cands)}] {short(w)} {len(sw)} swaps over {span_h:.1f}h", file=sys.stderr)
    # 4. value every swap at the 5-minute candle close and compute realized PnL (average cost)
    toks = sorted({s["token"] for _, sw, _ in scored for s in sw})
    pools_for(toks)
    results = []
    for w, sw, span_h in scored:
        held = defaultdict(lambda: [0.0, 0.0])  # qty, cost
        pnl, wins, sells, vol, unpriced, curve = 0.0, 0, 0, 0.0, 0, []
        tokens = set()
        for s in sw:
            pinfo = _pool_cache.get(s["token"])
            if not pinfo or not pinfo.get("pool"):
                unpriced += 1; continue
            rows = candles(pinfo["pool"], s["token"], "minute", 5, since)
            px, _ = price_at(rows, s["ts"], 300)
            if not px:
                unpriced += 1; continue
            usd = px * s["qty"]
            vol += usd
            tokens.add(s["token"])
            h = held[s["token"]]
            if s["side"] == "buy":
                h[0] += s["qty"]; h[1] += usd
            elif h[0] > 0:
                q = min(s["qty"], h[0])
                cost = h[1] * q / h[0]
                r = px * q - cost
                h[0] -= q; h[1] -= cost
                pnl += r; sells += 1; wins += r > 0
                curve.append(round(pnl, 2))
        st = {"wallet": w, "realized_pnl_usd": round(pnl, 2), "matched_sells": sells, "wins": wins,
              "win_rate": round(wins / sells, 3) if sells else None, "swaps": len(sw), "unpriced_swaps": unpriced,
              "tokens": len(tokens), "volume_usd": round(vol, 2), "history_hours": round(span_h, 1),
              "first_swap_at": iso(sw[0]["ts"]), "last_swap_at": iso(sw[-1]["ts"]), "pnl_curve": curve[-24:]}
        rep = next(r for r in reports if r["wallet"] == w)
        rep.update(st)
        if sells < a.min_sells:
            excluded["fewer_than_min_closed_trades"] += 1; rep["excluded"] = "fewer_than_min_closed_trades"; continue
        if len(tokens) < 2:
            excluded["single_token"] += 1; rep["excluded"] = "single_token"; continue
        if pnl <= 0:
            excluded["not_profitable"] += 1; rep["excluded"] = "not_profitable"; continue
        results.append(st)
    results.sort(key=lambda r: r["realized_pnl_usd"], reverse=True)
    pick = results[:N_WALLETS]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / f"selection-{t0.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(
        {"at": iso(t0), "universe": universe, "reports": reports, "excluded": excluded, "sources": SOURCES}, indent=1, default=str))
    if len(pick) < N_WALLETS:
        print(f"copybot: only {len(pick)} wallets passed the rules", file=sys.stderr)
    if not pick:
        sys.exit("copybot: no wallet passed; nothing started")
    start = now()
    wallets = []
    for i, r in enumerate(pick):
        wallets.append({"address": r["wallet"], "label": NICKNAMES[i], "rank": i + 1,
                        "explorer_url": f"{EXPLORER}/address/{r['wallet']}",
                        "selection": {k: v for k, v in r.items() if k != "wallet"},
                        "copy": {"copied_trades": 0, "realized_pnl_usd": 0.0, "wins": 0, "losses": 0, "last_trade_at": None, "open_value_usd": 0.0, "pnl_curve": [0.0]},
                        "cursor": {"last_block": None, "last_ts": None}})
    doc = {
        "schema_version": 1,
        "paper": True,
        "experiment": {
            "name": "Corgi's paper copy-trade",
            "started_at": iso(start),
            "day1": start.date().isoformat(),
            "bankroll_usd": BANKROLL,
            "rules": {
                "size_pct_of_equity": SIZE_PCT, "max_token_pct_of_equity": MAX_TOKEN_PCT, "min_order_usd": MIN_ORDER,
                "delay_seconds": DELAY_S, "slippage_pct": SLIPPAGE_PCT, "fee_pct_per_side": FEE_PCT, "gas_usd_per_swap": GAS_USD,
            },
            "method": [
                f"Wallets: signers of swaps >= ${a.min_trade_usd:g} in the top " + str(len(universe)) + " Robinhood Chain non-stablecoin pools by 24h volume (GeckoTerminal), repeat signers (2+ swaps) ranked by how many of those pools they traded, then activity, then size; top " + str(a.candidates) + " checked on Blockscout.",
                f"Excluded: contracts, tagged addresses, > {a.max_sample_trades} swaps in the pool samples, > {a.max_swaps_per_hour} swaps/hour, any buy+sell of the same token in one block (MEV/arb), fewer than {a.min_sells} closed trades, a single token, or realized PnL <= 0.",
                f"Score: realized PnL over the wallet's last {window_h}h of swaps (at most {a.pages * 50} transfers), each swap valued at the token's 5-minute candle close, average-cost basis. Top {N_WALLETS} kept. The list is frozen for the whole experiment.",
                f"Copying: only swaps after the start. A buy is copied at {SIZE_PCT:g}% of current equity (capped at cash and at {MAX_TOKEN_PCT:g}% of equity per token, skipped under ${MIN_ORDER:g}). A sell closes the same fraction of our position as the wallet sold of what it bought since we started following.",
                f"Fills: the real price {DELAY_S}s after the wallet's transaction (1-minute candle close, or the last trade before it), {SLIPPAGE_PCT:g}% worse for slippage, {FEE_PCT:g}% fee per side, ${GAS_USD:g} gas. Corgi checks 4 times a day, so fills are reconstructed afterwards as if a bot had reacted live.",
                "Marks: open positions are valued at GeckoTerminal's current token price on every run. If a price is missing, the last one is kept and marked stale.",
            ],
            "selection": {"at": iso(t0), "window_hours": window_h, "universe_pools": len(universe),
                          "signers_seen": len(seen), "candidates_checked": len(cands), "passed": len(results),
                          "excluded": dict(excluded), "sources_tried": {
                              "fomo_leaderboard": "not used: fomo.family's public boards mix chains and its API (fomoapi.io) needs a key; robinscan.io/leaderboard was unreachable from Corgi's box",
                          }},
        },
        "updated_at": iso(start),
        "wallets": wallets,
        "trades": [], "skipped": [], "positions": [], "tracked": {},
        "balance_history": [{"ts": iso(start), "equity": BANKROLL, "cash": BANKROLL, "positions_value": 0.0, "event": "start"}],
        "summary": {}, "runs": [],
        "runs_log": [{"at": iso(start), "kind": "select", "sources": SOURCES}],
    }
    doc["summary"] = summarize(doc)
    write(doc, a)
    print(json.dumps([{k: w[k] for k in ("label", "address")} | {"pnl": w["selection"]["realized_pnl_usd"], "sells": w["selection"]["matched_sells"], "wr": w["selection"]["win_rate"]} for w in wallets], indent=1))


# ------------------------------------------------------------------ the copy run

def summarize(doc):
    tr = doc["trades"]
    cash = doc.get("cash", BANKROLL) if "cash" in doc else BANKROLL
    pos_val = sum(p.get("value_usd") or 0 for p in doc["positions"])
    equity = cash + pos_val
    sells = [t for t in tr if t["side"] == "sell"]
    wins = sum(1 for t in sells if (t.get("realized_pnl_usd") or 0) > 0)
    eq = [h["equity"] for h in doc["balance_history"]] + [equity]
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    streak = 0
    for t in reversed(sells):
        if (t.get("realized_pnl_usd") or 0) > 0:
            streak += 1
        else:
            break
    realized = sum(t.get("realized_pnl_usd") or 0 for t in sells)
    return {
        "equity_usd": round(equity, 4), "cash_usd": round(cash, 4), "positions_value_usd": round(pos_val, 4),
        "pnl_usd": round(equity - BANKROLL, 4), "pnl_pct": round((equity - BANKROLL) / BANKROLL * 100, 3),
        "realized_pnl_usd": round(realized, 4), "unrealized_pnl_usd": round(sum(p.get("unrealized_pnl_usd") or 0 for p in doc["positions"]), 4),
        "trades": len(tr), "buys": len(tr) - len(sells), "sells": len(sells), "wins": wins, "losses": len(sells) - wins,
        "win_rate": round(wins / len(sells), 4) if sells else None,
        "max_drawdown_pct": round(mdd * 100, 3), "peak_equity_usd": round(max(eq), 4),
        "fees_paid_usd": round(sum(t.get("fee_usd") or 0 for t in tr), 4),
        "open_positions": len(doc["positions"]), "win_streak": streak, "skipped": len(doc["skipped"]),
        "best_trade_usd": round(max((t["realized_pnl_usd"] for t in sells), default=0), 4) if sells else None,
        "worst_trade_usd": round(min((t["realized_pnl_usd"] for t in sells), default=0), 4) if sells else None,
    }


def run(a):
    if not COPY.exists():
        sys.exit("copybot: no data/copy.json yet; run `copybot.py select` first")
    if not a.dry_run and not a.no_git:
        dirty = git("status", "--porcelain", "data").stdout.strip()
        if dirty:
            sys.exit("copybot: data/ has uncommitted changes; commit or discard them first:\n" + dirty)
        git("pull", "--rebase", "--quiet", "origin", "main")
    doc = json.loads(COPY.read_text("utf-8"))
    t_run = now()
    start = pts(doc["experiment"]["started_at"])
    R = doc["experiment"]["rules"]
    cash = doc.get("cash", BANKROLL)
    positions = {(p["wallet"], p["token"]["address"]): p for p in doc["positions"]}
    tracked = doc.setdefault("tracked", {})
    last_px = {p["token"]["address"]: p.get("last_price_usd") for p in doc["positions"]}
    done = {(t["tx_hash"], t["wallet"], t["token"]["address"], t["side"]) for t in doc["trades"]}
    done |= {(t["tx_hash"], t["wallet"], (t.get("token") or {}).get("address"), t["side"]) for t in doc["skipped"]}
    run_info = {"at": iso(t_run), "kind": "run", "new_swaps": 0, "copied": 0, "skipped": 0, "wallets_failed": [], "notes": []}

    # 1. new swaps of every followed wallet
    events = []
    for w in doc["wallets"]:
        cur = w["cursor"]
        stop_ts = start
        items, complete = wallet_transfers(w["address"], stop_ts=stop_ts, stop_block=cur.get("last_block"), max_pages=a.pages)
        if not complete:
            run_info["wallets_failed" if not items else "notes"].append(
                f"{w['label']}: Blockscout history incomplete this run ({len(items)} transfers read)")
        sw = swaps_from_transfers(w["address"], items)
        for s in sw:
            if s["ts"] < start:
                continue
            events.append((s, w))
        if items and complete:
            cur["last_block"] = max(it.get("block_number", 0) for it in items)
            cur["last_ts"] = iso(max(pts(it["timestamp"]) for it in items))
        elif items and not complete:
            pass  # keep old cursor so the gap is re-read next time
    events.sort(key=lambda e: (e[0]["ts"], e[0]["block"]))
    run_info["new_swaps"] = len(events)
    pools_for(sorted({s["token"] for s, _ in events}))

    def equity():
        return cash + sum(p["qty"] * (last_px.get(p["token"]["address"]) or p["avg_price_usd"]) for p in positions.values())

    def skip(s, w, reason):
        if (s["tx"], w["address"], s["token"], s["side"]) in done:
            return
        done.add((s["tx"], w["address"], s["token"], s["side"]))
        doc["skipped"].append({"ts": iso(s["ts"]), "wallet": w["address"], "label": w["label"], "side": s["side"],
                               "token": {"address": s["token"], "symbol": s["symbol"]}, "reason": reason,
                               "tx_hash": s["tx"], "tx_url": f"{EXPLORER}/tx/{s['tx']}"})
        run_info["skipped"] += 1

    for s, w in events:
        key = (s["tx"], w["address"], s["token"], s["side"])
        if key in done:
            continue
        fill_t = s["ts"] + timedelta(seconds=R["delay_seconds"])
        if fill_t > t_run - timedelta(seconds=60):
            run_info["notes"].append(f"{s['tx'][:10]}: too fresh, left for the next run")
            cur = w["cursor"]  # rewind the cursor so the next run reads this swap again
            if cur.get("last_block") is not None and s["block"] <= cur["last_block"]:
                cur["last_block"] = s["block"] - 1
            continue
        tw = tracked.setdefault(w["address"], {})
        pinfo = _pool_cache.get(s["token"])
        if not pinfo or not pinfo.get("pool"):
            if s["side"] == "buy":
                tw[s["token"]] = tw.get(s["token"], 0) + s["qty"]
            skip(s, w, "no pool found to price this token"); continue
        rows = candles(pinfo["pool"], s["token"], "minute", 1, s["ts"] - timedelta(minutes=30))
        px, src = price_at(rows, fill_t, 60)
        if not px:
            if s["side"] == "buy":
                tw[s["token"]] = tw.get(s["token"], 0) + s["qty"]
            skip(s, w, "no price candle at fill time"); continue
        tok = {"address": s["token"], "symbol": s["symbol"] or pinfo.get("symbol"), "name": s["name"] or pinfo.get("name"), "pool": pinfo["pool"],
               "chart_url": f"https://www.geckoterminal.com/{NET}/pools/{pinfo['pool']}"}
        last_px[s["token"]] = px
        pk = (w["address"], s["token"])
        rec = {"id": f"{s['tx'][:12]}-{w['label'].lower()}-{s['side']}", "ts": iso(fill_t), "source_ts": iso(s["ts"]),
               "wallet": w["address"], "label": w["label"], "side": s["side"], "token": tok,
               "their_qty": s["qty"], "market_price_usd": px, "price_source": f"geckoterminal_1m_{src}",
               "tx_hash": s["tx"], "tx_url": f"{EXPLORER}/tx/{s['tx']}"}
        if s["side"] == "buy":
            tw[s["token"]] = tw.get(s["token"], 0) + s["qty"]
            eq = equity()
            in_token = sum(p["cost_usd"] for (ww, tt), p in positions.items() if tt == s["token"])
            size = min(eq * R["size_pct_of_equity"] / 100, cash - R["gas_usd_per_swap"], eq * R["max_token_pct_of_equity"] / 100 - in_token)
            if size < R["min_order_usd"]:
                skip(s, w, "position cap reached" if in_token > 0 else "not enough paper cash"); continue
            fee = size * R["fee_pct_per_side"] / 100
            fill = px * (1 + R["slippage_pct"] / 100)
            qty = (size - fee) / fill
            cash -= size + R["gas_usd_per_swap"]
            p = positions.get(pk)
            if p:
                p["qty"] += qty; p["cost_usd"] += size + R["gas_usd_per_swap"]
            else:
                p = positions[pk] = {"wallet": w["address"], "label": w["label"], "token": tok, "qty": 0.0 + qty,
                                     "cost_usd": size + R["gas_usd_per_swap"], "opened_at": iso(fill_t), "open_tx_url": rec["tx_url"]}
            p["avg_price_usd"] = p["cost_usd"] / p["qty"]
            rec.update({"size_usd": round(size, 4), "qty": qty, "fill_price_usd": fill, "fee_usd": round(fee + R["gas_usd_per_swap"], 4), "realized_pnl_usd": None})
        else:
            p = positions.get(pk)
            theirs = tw.get(s["token"], 0)
            if not p or theirs <= 0:
                skip(s, w, "sell of a position we never copied (bought before the start or skipped)"); continue
            frac = min(1.0, s["qty"] / theirs)
            tw[s["token"]] = max(0.0, theirs - s["qty"])
            q = p["qty"] * frac if frac < 0.999 else p["qty"]
            fill = px * (1 - R["slippage_pct"] / 100)
            gross = q * fill
            fee = gross * R["fee_pct_per_side"] / 100
            proceeds = gross - fee - R["gas_usd_per_swap"]
            cost = p["cost_usd"] * (q / p["qty"])
            pnl = proceeds - cost
            cash += proceeds
            p["qty"] -= q; p["cost_usd"] -= cost
            if p["qty"] <= 1e-12 or frac >= 0.999:
                del positions[pk]
            rec.update({"size_usd": round(gross, 4), "qty": q, "fill_price_usd": fill, "fraction_closed": round(frac, 4),
                        "fee_usd": round(fee + R["gas_usd_per_swap"], 4), "realized_pnl_usd": round(pnl, 4)})
            wc = w["copy"]; wc["realized_pnl_usd"] = round(wc["realized_pnl_usd"] + pnl, 4)
            wc["wins" if pnl > 0 else "losses"] += 1
            wc["pnl_curve"] = (wc.get("pnl_curve") or [0.0])[-40:] + [wc["realized_pnl_usd"]]
        rec["cash_after_usd"] = round(cash, 4)
        rec["equity_after_usd"] = round(equity(), 4)
        doc["trades"].append(rec)
        done.add(key)
        w["copy"]["copied_trades"] += 1
        w["copy"]["last_trade_at"] = rec["ts"]
        doc["balance_history"].append({"ts": rec["ts"], "equity": rec["equity_after_usd"], "cash": rec["cash_after_usd"],
                                       "positions_value": round(rec["equity_after_usd"] - rec["cash_after_usd"], 4), "event": "trade", "trade_id": rec["id"]})
        run_info["copied"] += 1

    # 2. mark open positions to market
    marks = spot_prices(sorted({k[1] for k in positions})) if positions else {}
    for (wa, ta), p in positions.items():
        if ta in marks:
            p["last_price_usd"], p["last_price_at"], p["price_stale"] = marks[ta], iso(t_run), False
        else:
            p["last_price_usd"] = last_px.get(ta) or p["avg_price_usd"]; p["price_stale"] = True
            p.setdefault("last_price_at", None)
        p["value_usd"] = round(p["qty"] * p["last_price_usd"], 4)
        p["unrealized_pnl_usd"] = round(p["value_usd"] - p["cost_usd"], 4)
    for w in doc["wallets"]:
        w["copy"]["open_value_usd"] = round(sum(p["value_usd"] for p in positions.values() if p["wallet"] == w["address"]), 4)
    doc["positions"] = sorted(positions.values(), key=lambda p: -p["value_usd"])
    doc["cash"] = round(cash, 6)
    pos_val = sum(p["value_usd"] for p in doc["positions"])
    doc["balance_history"].append({"ts": iso(t_run), "equity": round(cash + pos_val, 4), "cash": round(cash, 4),
                                   "positions_value": round(pos_val, 4), "event": "mark"})
    doc["trades"].sort(key=lambda t: t["ts"])
    doc["balance_history"].sort(key=lambda h: h["ts"])
    doc["skipped"] = doc["skipped"][-400:]
    run_info["sources"] = SOURCES
    doc["runs_log"] = (doc.get("runs_log") or [])[-200:] + [run_info]
    doc["updated_at"] = iso(t_run)
    doc["summary"] = summarize(doc)
    print(json.dumps({"run": {k: v for k, v in run_info.items() if k != "sources"}, "sources": {k: {"ok": v["ok"], "calls": v["calls"], "failed": v["failed_calls"]} for k, v in SOURCES.items()}, "summary": doc["summary"]}, indent=1))
    if a.dry_run:
        return
    write(doc, a)


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"copybot: git {' '.join(args)} failed:\n{r.stdout}{r.stderr}")
    return r


def write(doc, a):
    txt = json.dumps(doc, ensure_ascii=False, indent=1, default=str) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data").mkdir()
        for f in ("state.json", "log.json"):
            (Path(tmp) / "data" / f).write_text((ROOT / "data" / f).read_text("utf-8"), "utf-8")
        (Path(tmp) / "data/copy.json").write_text(txt, "utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), "--root", tmp], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("copybot: validation failed, nothing written:\n" + r.stdout + r.stderr)
    COPY.write_text(txt, "utf-8")
    print("copybot: " + r.stdout.strip(), file=sys.stderr)
    if getattr(a, "no_git", False):
        return
    git("add", "data/copy.json")
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        return
    s = doc["summary"]
    git("commit", "--quiet", "-m", f"copy: {s['trades']} paper trades, equity ${s['equity_usd']:.2f}")
    if getattr(a, "no_push", False):
        return
    git("push", "--quiet", "origin", "HEAD:main")
    print("copybot: pushed " + git("rev-parse", "--short", "HEAD").stdout.strip(), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("select")
    s.add_argument("--force", action="store_true")
    s.add_argument("--pools", type=int, default=30)
    s.add_argument("--min-trade-usd", type=float, default=25)
    s.add_argument("--candidates", type=int, default=70)
    s.add_argument("--pages", type=int, default=3, help="Blockscout pages (50 transfers each) per candidate")
    s.add_argument("--window-hours", type=int, default=48)
    s.add_argument("--max-sample-trades", type=int, default=40)
    s.add_argument("--max-swaps-per-hour", type=float, default=20)
    s.add_argument("--min-sells", type=int, default=3)
    r = sub.add_parser("run")
    r.add_argument("--pages", type=int, default=8)
    for p in (s, r):
        p.add_argument("--no-git", action="store_true")
        p.add_argument("--no-push", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "select":
        select(a)
    else:
        if a.cmd is None:
            a = ap.parse_args(["run"] + sys.argv[1:])
        run(a)


if __name__ == "__main__":
    main()
