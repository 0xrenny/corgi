#!/usr/bin/env python3
"""Validate data/state.json and data/log.json before deploying. Exit code 1 on error."""
import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve() if "--root" in sys.argv else Path(__file__).resolve().parent.parent
KINDS = {"post", "reply", "draft", "thought", "walk", "build", "note", "system", "scout", "news"}
STATUS = {"awake", "napping", "walking", "offline"}
TOKEN_NUM = ("price_usd", "volume_24h_usd", "liquidity_usd", "market_cap_usd", "fdv_usd", "change_24h_pct", "pair_age_hours")
errors = []

def ts_ok(v, where):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None: errors.append(f"{where}: timestamp needs a timezone offset: {v}")
    except Exception:
        errors.append(f"{where}: invalid ISO 8601 timestamp: {v!r}")

state = json.loads((ROOT / "data/state.json").read_text("utf-8"))
log = json.loads((ROOT / "data/log.json").read_text("utf-8"))

if state.get("status") not in STATUS: errors.append(f"state.status must be one of {sorted(STATUS)}")
for k in ("born_at", "last_move_at"):
    if state.get(k): ts_ok(state[k], f"state.{k}")
plan = state.get("plan") or {}
for k in ("updated_at", "next_check_at"):
    if plan.get(k): ts_ok(plan[k], f"state.plan.{k}")
if not isinstance(state.get("bio", []), list): errors.append("state.bio must be a list of paragraphs")

ids = set()
for i, e in enumerate(log.get("entries", [])):
    w = f"log.entries[{i}]"
    if not e.get("ts"): errors.append(f"{w}: missing ts")
    else: ts_ok(e["ts"], w)
    if e.get("kind") not in KINDS: errors.append(f"{w}: kind must be one of {sorted(KINDS)}")
    if not str(e.get("text", "")).strip(): errors.append(f"{w}: empty text")
    if e.get("kind") in ("post", "reply") and len(e.get("text", "")) > 280:
        errors.append(f"{w}: {len(e['text'])} chars, X allows 280")
    if e.get("id"):
        if e["id"] in ids: errors.append(f"{w}: duplicate id {e['id']}")
        ids.add(e["id"])
    if e.get("url") and not str(e["url"]).startswith(("https://", "http://")):
        errors.append(f"{w}: url must be http(s)")
    if not isinstance(e.get("tools", []), list): errors.append(f"{w}: tools must be a list")
    if "tokens" in e:
        toks = e["tokens"]
        if not isinstance(toks, list) or len(toks) > 12:
            errors.append(f"{w}: tokens must be a list of at most 12 items")
        else:
            for j, t in enumerate(toks):
                if not isinstance(t, dict) or not t.get("symbol"):
                    errors.append(f"{w}.tokens[{j}]: needs a symbol"); continue
                for k in TOKEN_NUM:
                    if t.get(k) is not None and not isinstance(t[k], (int, float)):
                        errors.append(f"{w}.tokens[{j}].{k}: must be a number or null")
                if t.get("url") and not str(t["url"]).startswith("https://"):
                    errors.append(f"{w}.tokens[{j}].url must be https")
    if e.get("kind") == "news" or "items" in e:
        its = e.get("items")
        if e.get("kind") == "news" and (not isinstance(its, list) or not 2 <= len(its) <= 3):
            errors.append(f"{w}: news entries need 2-3 items")
        elif not isinstance(its, list):
            errors.append(f"{w}: items must be a list")
        if "TODO" in str(e.get("text", "")): errors.append(f"{w}: text still has a TODO")
        for j, it in enumerate(its if isinstance(its, list) else []):
            ww = f"{w}.items[{j}]"
            if not isinstance(it, dict): errors.append(f"{ww}: must be an object"); continue
            for k in ("title", "source", "take"):
                if not str(it.get(k) or "").strip(): errors.append(f"{ww}: {k} is required")
            if "TODO" in str(it.get("take", "")): errors.append(f"{ww}: take still has a TODO")
            if len(str(it.get("take", ""))) > 220: errors.append(f"{ww}: take is over 220 characters (keep it to one line)")
            if not str(it.get("url", "")).startswith("https://"): errors.append(f"{ww}: url must be https")
            if not it.get("published_at"): errors.append(f"{ww}: published_at is required")
            else: ts_ok(it["published_at"], f"{ww}.published_at")
            for k, a in enumerate(it.get("also") or []):
                if not isinstance(a, dict) or not a.get("source") or not str(a.get("url", "")).startswith("https://"):
                    errors.append(f"{ww}.also[{k}]: needs source + https url")
    if "headlines" in e:
        hl = e["headlines"]
        if not isinstance(hl, list) or len(hl) > 10:
            errors.append(f"{w}: headlines must be a list of at most 10 items")
        else:
            for j, h in enumerate(hl):
                if not isinstance(h, dict) or not h.get("title"):
                    errors.append(f"{w}.headlines[{j}]: needs a title"); continue
                if h.get("url") and not str(h["url"]).startswith(("https://", "http://")):
                    errors.append(f"{w}.headlines[{j}].url must be http(s)")
                if h.get("published_at"): ts_ok(h["published_at"], f"{w}.headlines[{j}].published_at")

# ---- data/copy.json (paper copy-trading experiment), optional
copy_note = ""
cp = ROOT / "data/copy.json"
if cp.exists():
    import re
    HEX40, HEX64 = re.compile(r"^0x[0-9a-f]{40}$"), re.compile(r"^0x[0-9a-f]{64}$")
    def isnum(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v
    try:
        c = json.loads(cp.read_text("utf-8"))
    except Exception as ex:
        c = None; errors.append(f"copy.json: not valid JSON: {ex}")
    if c is not None:
        if c.get("paper") is not True: errors.append("copy.json: paper must be true (this is a paper experiment)")
        ex_ = c.get("experiment") or {}
        if ex_.get("started_at"): ts_ok(ex_["started_at"], "copy.experiment.started_at")
        else: errors.append("copy.json: experiment.started_at missing")
        if not isnum(ex_.get("bankroll_usd")) or ex_["bankroll_usd"] <= 0: errors.append("copy.json: experiment.bankroll_usd must be > 0")
        for k in ("size_pct_of_equity", "delay_seconds", "slippage_pct", "fee_pct_per_side", "gas_usd_per_swap"):
            if not isnum((ex_.get("rules") or {}).get(k)): errors.append(f"copy.experiment.rules.{k} must be a number")
        if c.get("updated_at"): ts_ok(c["updated_at"], "copy.updated_at")
        ws = c.get("wallets") or []
        if not 1 <= len(ws) <= 8: errors.append("copy.json: 1-8 wallets expected")
        waddr = set()
        for i, w in enumerate(ws):
            if not HEX40.match(str(w.get("address", ""))): errors.append(f"copy.wallets[{i}].address must be a lowercase 0x address")
            if not w.get("label"): errors.append(f"copy.wallets[{i}]: label missing")
            waddr.add(w.get("address"))
        tids = set()
        for i, t in enumerate(c.get("trades") or []):
            w = f"copy.trades[{i}]"
            ts_ok(t.get("ts"), w + ".ts"); ts_ok(t.get("source_ts"), w + ".source_ts")
            if t.get("side") not in ("buy", "sell"): errors.append(f"{w}.side must be buy/sell")
            if t.get("wallet") not in waddr: errors.append(f"{w}: wallet is not one of the followed wallets")
            if not HEX64.match(str(t.get("tx_hash", ""))): errors.append(f"{w}: tx_hash must be a real 0x… hash")
            if not str(t.get("tx_url", "")).startswith("https://robinhoodchain.blockscout.com/tx/"): errors.append(f"{w}: tx_url must point to the explorer")
            for k in ("size_usd", "qty", "fill_price_usd", "market_price_usd", "cash_after_usd", "equity_after_usd"):
                if not isnum(t.get(k)) or t[k] < 0: errors.append(f"{w}.{k} must be a number >= 0")
            if t.get("side") == "sell" and not isnum(t.get("realized_pnl_usd")): errors.append(f"{w}: sell needs realized_pnl_usd")
            if not (t.get("token") or {}).get("address"): errors.append(f"{w}: token.address missing")
            if t.get("id") in tids: errors.append(f"{w}: duplicate id {t.get('id')}")
            tids.add(t.get("id"))
        hist = c.get("balance_history") or []
        if not hist: errors.append("copy.json: balance_history is empty")
        prev = None
        for i, h in enumerate(hist):
            ts_ok(h.get("ts"), f"copy.balance_history[{i}]")
            if not isnum(h.get("equity")): errors.append(f"copy.balance_history[{i}].equity must be a number")
            if prev and h.get("ts", "") and datetime.fromisoformat(h["ts"]) < datetime.fromisoformat(prev): errors.append(f"copy.balance_history[{i}]: not in time order")
            prev = h.get("ts")
        for i, p in enumerate(c.get("positions") or []):
            for k in ("qty", "cost_usd", "value_usd"):
                if not isnum(p.get(k)): errors.append(f"copy.positions[{i}].{k} must be a number")
        s = c.get("summary") or {}
        for k in ("equity_usd", "pnl_usd", "max_drawdown_pct"):
            if not isnum(s.get(k)): errors.append(f"copy.summary.{k} must be a number")
        if s.get("win_rate") is not None and not (isnum(s["win_rate"]) and 0 <= s["win_rate"] <= 1): errors.append("copy.summary.win_rate must be 0-1 or null")
        copy_note = f" + copy.json ({len(ws)} wallets, {len(c.get('trades') or [])} paper trades)"

if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"ok: state + {len(log.get('entries', []))} log entries{copy_note}")
