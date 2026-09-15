#!/usr/bin/env python3
"""
episodes.py — an append-only episodic memory log for coding agents.

Distinct from the other two stores:

  memory (semantic)   — durable FACTS: "GLM-5.3-Flash needs vLLM 0.29+".
                         One file per fact, current-truth only.
  decisions (procedural/keyed) — CHOICES: "we use uv, not pip", keyed by
                         (scope, aspect), one active value + history.
  episodes (this, episodic)    — EXPERIENCES: "on 2026-09-07 I tried serving
                         GLM-5.3-Flash on dgxh, it OOM'd, here's why". Many
                         entries expected, no "current value" concept, purely
                         additive. The point is answering "have I tried this
                         before, and what happened" without re-deriving it.

Storage is a single append-only JSONL file — one JSON object per line, never
rewritten in place. That makes corruption recovery trivial (skip a bad line)
and keeps the format git-diff-friendly if the store ever ends up under
version control.

Usage:
  episodes.py log <scope> "<task>" --outcome success|failure|partial|abandoned
              [--detail "..."] [--detail-file PATH] [--lesson "..."]

  episodes.py recent [--n N] [--scope SCOPE]
  episodes.py search <term> [<term>...] [--scope SCOPE]
  episodes.py show <id>
  episodes.py scopes
  episodes.py check
"""
import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIR = str(Path.home() / ".claude" / "episodes")
LOG_NAME = "episodes.jsonl"
OUTCOMES = ("success", "failure", "partial", "abandoned")


def store_dir() -> Path:
    d = Path(os.environ.get("EPISODIC_MEMORY_DIR", DEFAULT_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path() -> Path:
    return store_dir() / LOG_NAME


def new_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, secrets.token_hex(2))


def append_record(rec: dict) -> None:
    """Append one JSON line. O_APPEND write, flushed+fsynced, so a concurrent
    writer or a crash mid-session can't corrupt or lose a prior record — each
    line stands alone and is never edited after being written."""
    p = log_path()
    line = json.dumps(rec, ensure_ascii=False)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_records():
    """Yield every valid record, oldest first. A line that fails to parse
    (e.g. truncated by a crash mid-write) is skipped, not fatal — the rest of
    an append-only log must stay readable even if its last line didn't land
    cleanly."""
    p = log_path()
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                print("WARNING: skipping unparseable line %d in %s" % (i, p),
                      file=sys.stderr)
                continue
            yield rec


def fmt_short(rec: dict) -> str:
    return "[%s] (%s/%s) %s" % (
        rec.get("id", "?"), rec.get("scope", "?"), rec.get("outcome", "?"),
        rec.get("task", "")
    )


def fmt_full(rec: dict) -> str:
    lines = [
        "id:      %s" % rec.get("id", "?"),
        "ts:      %s" % rec.get("ts", "?"),
        "scope:   %s" % rec.get("scope", "?"),
        "outcome: %s" % rec.get("outcome", "?"),
        "task:    %s" % rec.get("task", ""),
    ]
    if rec.get("detail"):
        lines.append("detail:  %s" % rec["detail"])
    if rec.get("lesson"):
        lines.append("lesson:  %s" % rec["lesson"])
    return "\n".join(lines)


# ------------------------------------------------------------------- commands

def cmd_log(a):
    if a.outcome not in OUTCOMES:
        sys.exit("--outcome must be one of: %s" % ", ".join(OUTCOMES))
    detail = a.detail
    if a.detail_file:
        detail = Path(a.detail_file).read_text(encoding="utf-8").strip()
    rec = {
        "id": new_id(),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": a.scope,
        "task": a.task.strip(),
        "outcome": a.outcome,
        "detail": (detail or "").strip(),
        "lesson": (a.lesson or "").strip(),
    }
    append_record(rec)
    print("LOGGED %s" % rec["id"])
    print(fmt_short(rec))


def cmd_recent(a):
    recs = list(read_records())
    if a.scope:
        recs = [r for r in recs if r.get("scope") == a.scope]
    recs = recs[-a.n:]
    if not recs:
        print("(no episodes logged yet%s)" % (" for scope %r" % a.scope if a.scope else ""))
        return
    for r in reversed(recs):
        print(fmt_short(r))


def cmd_search(a):
    terms = [t.lower() for t in a.terms if len(t) > 2]
    if not terms:
        sys.exit("give at least one search term of 3+ characters")
    hits = []
    for r in read_records():
        if a.scope and r.get("scope") != a.scope:
            continue
        blob = " ".join([
            r.get("task", ""), r.get("detail", ""), r.get("lesson", ""),
            r.get("scope", ""),
        ]).lower()
        score = sum(blob.count(t) for t in terms)
        if score:
            hits.append((score, r))
    if not hits:
        print("NO MATCH")
        return
    hits.sort(key=lambda x: x[0], reverse=True)
    for score, r in hits:
        print("[%3d] %s" % (score, fmt_short(r)))


def cmd_show(a):
    for r in read_records():
        if r.get("id") == a.id:
            print(fmt_full(r))
            return
    sys.exit("NOT FOUND: %s" % a.id)


def cmd_scopes(a):
    counts = {}
    for r in read_records():
        s = r.get("scope", "?")
        counts[s] = counts.get(s, 0) + 1
    if not counts:
        print("(no episodes logged yet)")
        return
    for s, n in sorted(counts.items(), key=lambda x: -x[1]):
        print("%4d  %s" % (n, s))


def cmd_check(a):
    p = log_path()
    if not p.exists():
        print("OK - no log file yet at %s" % p)
        return
    total, bad = 0, 0
    ids = set()
    dupes = set()
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                print("BAD LINE %d: unparseable" % i)
                continue
            rid = rec.get("id")
            if not rid:
                print("BAD LINE %d: missing id" % i)
                bad += 1
                continue
            if rid in ids:
                dupes.add(rid)
            ids.add(rid)
            if rec.get("outcome") not in OUTCOMES:
                print("BAD LINE %d: invalid outcome %r" % (i, rec.get("outcome")))
                bad += 1
    for d in sorted(dupes):
        print("DUPLICATE id: %s" % d)
    ok = bad == 0 and not dupes
    if ok:
        print("OK - %d episodes, log is well-formed" % total)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(
        prog="episodes.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="record a finished attempt at something")
    p.add_argument("scope", help="short tag for what area this belongs to, "
                                 "e.g. 'cluster', 'clipboard-sync', 'opencode'")
    p.add_argument("task", help="one-line description of what was attempted")
    p.add_argument("--outcome", "-o", required=True, choices=OUTCOMES)
    p.add_argument("--detail", "-d", help="what actually happened / actions taken")
    p.add_argument("--detail-file", help="read --detail text from a file instead")
    p.add_argument("--lesson", "-l", help="the key takeaway for next time")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("recent", help="show the most recent episodes")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_recent)

    p = sub.add_parser("search", help="rank episodes by keyword overlap")
    p.add_argument("terms", nargs="+")
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("show", help="print one episode in full")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)

    sub.add_parser("scopes", help="list scopes with episode counts"
                   ).set_defaults(fn=cmd_scopes)

    sub.add_parser("check", help="validate the log file is well-formed"
                   ).set_defaults(fn=cmd_check)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
