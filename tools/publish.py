#!/usr/bin/env python3
"""
Merge new diary entries / state updates into data/log.json + data/state.json,
validate, commit and push to main (GitHub Pages redeploys on push).

Input file (JSON), any of:
  {"entries": [ {...}, ... ], "state": { ...partial state... }}
  [ {...entry...}, ... ]
  {...single entry...}

Rules:
  - timestamps are normalised to Europe/Istanbul ISO 8601 (seconds); missing ts -> now
  - missing id -> generated "YYYYMMDD-HHMMSS-<kind>-<hash>"; duplicate ids are refused (use --replace)
  - entries are sorted newest first
  - the first time a real (non-example) entry is published, every seed entry with
    "example": true is removed and state.example_data is set to false (banner off).
    Use --keep-examples to prevent that.
  - state is deep-merged; last_move_at defaults to the newest entry's ts
  - tools/validate.py runs on the merged result before anything is written

Usage:
  python3 tools/publish.py update.json --dry-run     # show what would change, write nothing
  python3 tools/publish.py update.json               # write, validate, commit, push
  python3 tools/publish.py update.json --no-push     # write + commit locally only
  echo '{"state":{"status":"napping"}}' | python3 tools/publish.py -
"""
import argparse, copy, hashlib, json, os, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
ROOT = Path(__file__).resolve().parent.parent
STATE_TS = [("born_at",), ("last_move_at",), ("plan", "updated_at"), ("plan", "next_check_at")]


def die(msg, code=1):
    print("publish: " + msg, file=sys.stderr)
    sys.exit(code)


def norm_ts(v, where):
    if v in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        die(f"{where}: not an ISO 8601 timestamp: {v!r}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)  # naive times are taken as Istanbul time
    return d.astimezone(TZ).isoformat(timespec="seconds")


def deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed:\n{r.stdout}{r.stderr}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="JSON file with entries/state, or - for stdin")
    ap.add_argument("--dry-run", action="store_true", help="validate and show the result, write nothing, no git")
    ap.add_argument("--no-push", action="store_true", help="commit locally but don't push")
    ap.add_argument("--no-git", action="store_true", help="write files only, no commit/push")
    ap.add_argument("--keep-examples", action="store_true", help="don't remove seed example entries")
    ap.add_argument("--replace", action="store_true", help="allow replacing entries with an existing id")
    ap.add_argument("--max-entries", type=int, default=1000, help="keep at most this many entries (oldest dropped)")
    ap.add_argument("-m", "--message", help="commit message")
    ap.add_argument("--print", dest="print_result", action="store_true", help="print the merged JSON files")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.input == "-" else Path(a.input).read_text("utf-8")
    try:
        upd = json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"input is not valid JSON: {e}")
    if isinstance(upd, list):
        upd = {"entries": upd}
    elif isinstance(upd, dict) and "ts" in upd and "kind" in upd:
        upd = {"entries": [upd]}
    new_entries = upd.get("entries") or []
    state_upd = upd.get("state") or {}
    if not isinstance(new_entries, list) or not isinstance(state_upd, dict):
        die("entries must be a list and state an object")

    if not a.dry_run and not a.no_git:
        dirty = git("status", "--porcelain", "data").stdout.strip()
        if dirty:
            die("data/ has uncommitted changes; commit or discard them first:\n" + dirty)
        git("pull", "--rebase", "--quiet", "origin", "main")

    state = json.loads((ROOT / "data/state.json").read_text("utf-8"))
    log = json.loads((ROOT / "data/log.json").read_text("utf-8"))
    before_state, entries = copy.deepcopy(state), list(log.get("entries", []))
    ids = {e.get("id") for e in entries}

    now = datetime.now(TZ).isoformat(timespec="seconds")
    added, replaced = [], []
    for i, e in enumerate(new_entries):
        if not isinstance(e, dict):
            die(f"entries[{i}] is not an object")
        e = dict(e)
        e["ts"] = norm_ts(e.get("ts"), f"entries[{i}].ts") or now
        for h in e.get("headlines") or []:
            if isinstance(h, dict) and h.get("published_at"):
                h["published_at"] = norm_ts(h["published_at"], f"entries[{i}].headlines.published_at")
        if not e.get("id"):
            hsh = hashlib.sha1((e["ts"] + str(e.get("kind")) + str(e.get("text"))).encode()).hexdigest()[:6]
            e["id"] = datetime.fromisoformat(e["ts"]).strftime("%Y%m%d-%H%M%S") + f"-{e.get('kind', 'note')}-{hsh}"
        if e.get("example") is False:
            del e["example"]
        if e["id"] in ids:
            if not a.replace:
                die(f"entries[{i}]: id {e['id']!r} already exists (use --replace)")
            entries = [x for x in entries if x.get("id") != e["id"]]
            replaced.append(e["id"])
        ids.add(e["id"])
        entries.append(e)
        added.append(e)

    removed_examples = 0
    real_new = [e for e in added if not e.get("example")]
    if real_new and not a.keep_examples:
        n = len(entries)
        entries = [e for e in entries if not e.get("example")]
        removed_examples = n - len(entries)
        state["example_data"] = False

    deep_merge(state, state_upd)
    for path in STATE_TS:
        obj = state
        for k in path[:-1]:
            obj = obj.get(k) if isinstance(obj, dict) else None
        if isinstance(obj, dict) and obj.get(path[-1]):
            obj[path[-1]] = norm_ts(obj[path[-1]], "state." + ".".join(path))
    entries.sort(key=lambda e: datetime.fromisoformat(e["ts"]), reverse=True)
    entries = entries[: a.max_entries]
    if real_new and "last_move_at" not in state_upd:
        state["last_move_at"] = max(e["ts"] for e in real_new)
    log["entries"] = entries

    state_txt = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    log_txt = json.dumps(log, ensure_ascii=False, indent=2) + "\n"

    # validate the merged result in a scratch copy before touching the real files
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data").mkdir()
        (Path(tmp) / "data/state.json").write_text(state_txt, "utf-8")
        (Path(tmp) / "data/log.json").write_text(log_txt, "utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), "--root", tmp], capture_output=True, text=True)
        if r.returncode != 0:
            die("validation failed, nothing written:\n" + r.stdout + r.stderr)

    changed_state = sorted(k for k in set(state) | set(before_state) if state.get(k) != before_state.get(k))
    summary = {
        "dry_run": a.dry_run,
        "added": [f"{e['id']} ({e.get('kind')}) {e['ts']}" for e in added],
        "replaced": replaced,
        "removed_example_entries": removed_examples,
        "example_banner": bool(state.get("example_data")),
        "state_fields_changed": changed_state,
        "total_entries": len(entries),
        "validation": r.stdout.strip(),
    }
    if a.print_result:
        print(state_txt + log_txt)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.dry_run:
        return

    (ROOT / "data/state.json").write_text(state_txt, "utf-8")
    (ROOT / "data/log.json").write_text(log_txt, "utf-8")
    if a.no_git:
        return
    git("add", "data/state.json", "data/log.json")
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        print("publish: nothing changed, no commit")
        return
    msg = a.message or (f"diary: {len(added)} new entr{'y' if len(added) == 1 else 'ies'}" if added else "diary: state update")
    git("commit", "--quiet", "-m", msg)
    if a.no_push:
        print("publish: committed locally (not pushed)")
        return
    git("push", "--quiet", "origin", "HEAD:main")
    print("publish: pushed to main: " + git("rev-parse", "--short", "HEAD").stdout.strip())


if __name__ == "__main__":
    main()
