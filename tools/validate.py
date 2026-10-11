#!/usr/bin/env python3
"""Validate data/state.json and data/log.json before deploying. Exit code 1 on error."""
import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"post", "reply", "draft", "thought", "walk", "build", "note", "system"}
STATUS = {"awake", "napping", "walking", "offline"}
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

if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"ok: state + {len(log.get('entries', []))} log entries")
