#!/usr/bin/env python3
"""
decisions.py — a two-tier, git-native context ledger for coding agents.

Identity is never inferred from meaning. A decision is identified by an
exact (scope, aspect) key chosen by whoever logs it. Two decisions only
get compared if they share a key — this sidesteps the open "proposition
identity" problem instead of trying to solve it.

Two tiers, same mechanism, different scope of truth:

  LOCAL  — decisions specific to one codebase (this project's retry
           policy, this project's auth token format). Lives inside the
           project at .claude/decisions/. Rides along with the project's
           own git history automatically — no separate sync needed.

  GLOBAL — decisions that should hold across all your projects (your
           default tooling, your commit-message convention, your date
           format). Lives in its own small git repo, independent of any
           one project, so you can `git pull`/`git push` it and have it
           follow you across machines.

Each decision is ONE PLAIN FILE at <root>/<scope>/<aspect>.yaml. There is
deliberately no database and no "superseded" bookkeeping in the file
itself — when a decision changes, the file is simply overwritten, and
git's own history of that file *is* the supersession history
(`git log -p` on the file shows every past value and why it changed).
Because that guarantee depends on someone remembering to commit between two
writes, each key ALSO gets an append-only <aspect>.history file recording
every value ever written, so a superseded value is never lost silently even
if nothing is committed. See append_history().
This also means the storage format is git-diff- and git-merge-friendly,
unlike a binary database file.

Usage:
  decisions.py check <scope> <aspect>               # local, falls back to global
  decisions.py check <scope> <aspect> --global       # global only
  decisions.py check <scope> <aspect> --local        # local only

  decisions.py add <scope> <aspect> "<value>" --reason "..."       # local
  decisions.py add <scope> <aspect> "<value>" --reason "..." --global

  decisions.py history <scope> <aspect>              # every past value at this key
  decisions.py list [--scope SCOPE] [--global] [--local] [--both]
  decisions.py export [--global] [--local]
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LOCAL_DIRNAME = ".claude/decisions"
GLOBAL_DEFAULT = Path.home() / ".claude" / "global-decisions" / "decisions"
GLOBAL_ENV_VAR = "DECISION_LEDGER_GLOBAL"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_project_root(start: Path) -> Path:
    """Walk up from start looking for a .git directory; fall back to start."""
    cur = start.resolve()
    for _ in range(50):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def local_root() -> Path:
    return find_project_root(Path.cwd()) / LOCAL_DIRNAME


def global_root() -> Path:
    import os
    env = os.environ.get(GLOBAL_ENV_VAR)
    return Path(env).expanduser() if env else GLOBAL_DEFAULT


WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def sanitize_segment(s: str) -> str:
    """Make a single path segment filesystem-safe AND identical across
    machines/OSes. Two things matter beyond basic character-safety:

    - Case is normalized to lowercase. Linux filesystems are case-sensitive,
      macOS/Windows are not by default -- without normalizing, "Auth.py" and
      "auth.py" would silently collide on one OS and silently diverge into
      two different keys on another. Normalizing makes identity consistent
      regardless of which machine logged the decision.
    - Windows reserves certain names outright (con, aux, nul, com1-9,
      lpt1-9), with or without an extension -- a decision keyed to one of
      these would fail to write at all on a Windows machine while working
      fine on Linux/macOS. Guard against that explicitly.
    """
    s = s.strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)
    s = s.strip("-") or "unnamed"
    if s in (".", ".."):
        s = "unnamed"
    s = s.lower()
    if s.split(".")[0] in WINDOWS_RESERVED:
        s = f"{s}-key"
    return s


def key_path(root: Path, scope: str, aspect: str) -> Path:
    scope_parts = [sanitize_segment(p) for p in scope.split("/") if p.strip()]
    aspect_part = sanitize_segment(aspect)
    return root.joinpath(*scope_parts, f"{aspect_part}.yaml")


def read_decision(path: Path):
    if not path.exists():
        return None
    text = path.read_text()
    if text.startswith("<<<<<<<") or "\n<<<<<<<" in text:
        print(f"ERROR: {path} has unresolved git merge conflict markers.", file=sys.stderr)
        print("  Someone decided this differently on two machines before syncing.", file=sys.stderr)
        print("  Resolve the conflict by hand (pick one value, or log a fresh decision "
              "that supersedes both) before trusting this key.", file=sys.stderr)
        sys.exit(1)
    data = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def history_path(path: Path) -> Path:
    """Append-only companion to a decision file: foo.yaml -> foo.history.

    Deliberately NOT a .yaml extension: iter_decisions() globs "*.yaml", so a
    history file must not be picked up and mistaken for a decision of its own.
    """
    return path.with_suffix(".history")


def _flat(s: str) -> str:
    """Collapse whitespace/newlines so one record can never span extra lines
    and corrupt the append-only parse."""
    return " ".join((s or "").split())


def append_history(path: Path, value: str, reason: str, decided_at: str, event: str):
    """Append one immutable record of a decision to the key's history file.

    Why this exists: the current-value file is OVERWRITTEN on every add, so
    without this the only record of a superseded value is git history -- which
    depends on someone remembering to `git commit` between two writes. Log the
    same key twice before committing and the first value is gone silently.
    That reintroduces exactly the "reliable only if the agent cooperates"
    failure this ledger exists to eliminate, at the one point where the loss
    is invisible.

    This file is append-only and is written BEFORE the overwrite, so the
    superseded value survives even if nothing is ever committed. Opened in
    "a" mode: O_APPEND writes go to the end of the file, so a concurrent
    writer cannot clobber an existing record.
    """
    import os

    hp = history_path(path)
    hp.parent.mkdir(parents=True, exist_ok=True)
    record = (
        f"- decided_at: {decided_at}\n"
        f"  event: {event}\n"
        f"  value: {_flat(value)}\n"
        f"  reason: {_flat(reason) or '(none given)'}\n"
    )
    with open(hp, "a", encoding="utf-8") as f:
        f.write(record)
        f.flush()
        os.fsync(f.fileno())


def read_history(path: Path):
    """Parse the append-only history file into a list of records, oldest first.

    Tolerant by design: a record left partial by a crash mid-append is skipped
    rather than raising, since a truncated tail must never make the surviving
    history unreadable.
    """
    hp = history_path(path)
    if not hp.exists():
        return []
    entries, cur = [], None
    for line in hp.read_text(encoding="utf-8").splitlines():
        if line.startswith("- "):
            if cur:
                entries.append(cur)
            cur, line = {}, line[2:]
        elif line.startswith("  ") and cur is not None:
            line = line.strip()
        else:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur:
        entries.append(cur)
    return [e for e in entries if "value" in e]


def write_decision(path: Path, value: str, reason: str, decided_at: str = None):
    """Write atomically: write to a temp file in the same directory, then
    rename over the target. os.replace is atomic on POSIX and Windows, so a
    crash or power loss mid-write can never leave a truncated/corrupt file —
    the target either has the old content or the new content, never a mix."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"value: {value}\n"
        f"reason: {reason}\n"
        f"decided_at: {decided_at or now()}\n"
    )
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # missing_ok= is Python 3.8+; the OSU cluster login nodes ship 3.6.
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


def warn_if_not_git_repo(root: Path, tier_name: str):
    check = root
    for _ in range(50):
        if (check / ".git").exists():
            return
        if check.parent == check:
            break
        check = check.parent
    print(f"NOTE: {tier_name} ledger at {root} is not inside a git repo yet.",
          file=sys.stderr)
    if tier_name == "global":
        print(f"  Run: git init {root.parent} && cd {root.parent} && "
              f"git add -A && git commit -m 'init global context ledger'",
              file=sys.stderr)
        print("  Then add a remote (e.g. a private GitHub repo) and clone it "
              "on your other machine so both stay in sync.", file=sys.stderr)


def cmd_check(args):
    tiers = []
    if args.global_:
        tiers = [("global", global_root())]
    elif args.local:
        tiers = [("local", local_root())]
    else:
        tiers = [("local", local_root()), ("global", global_root())]

    for tier_name, root in tiers:
        path = key_path(root, args.scope, args.aspect)
        data = read_decision(path)
        if data:
            print(f"FOUND ({tier_name}): {args.scope} / {args.aspect} = {data.get('value')!r}")
            print(f"  reason: {data.get('reason') or '(none given)'}")
            print(f"  decided: {data.get('decided_at')}")
            print("Follow this unless there's a good reason to revisit it — "
                  "if you do change it, log the new decision so it overwrites this one.")
            return

    where = "global scope" if args.global_ else ("local scope" if args.local else "local or global")
    print(f"NOT FOUND: no decision for {args.scope} / {args.aspect} in {where}")
    print("Safe to decide fresh and log it.")


def cmd_add(args):
    tier_name = "global" if args.global_ else "local"
    root = global_root() if args.global_ else local_root()
    path = key_path(root, args.scope, args.aspect)

    existing = read_decision(path)
    stamp = now()

    # Seed history for keys written before history files existed, so the value
    # being superseded right now isn't the one value that never gets recorded.
    if existing and not history_path(path).exists():
        append_history(path, existing.get("value", ""), existing.get("reason", ""),
                       existing.get("decided_at", "(unknown)"), "seeded-from-existing")

    # Append BEFORE overwriting: if we crash between the two, history holds a
    # superset of the truth, which is the recoverable direction to fail in.
    append_history(path, args.value, args.reason or "", stamp,
                   "superseded-previous" if existing else "initial")
    write_decision(path, args.value, args.reason or "", stamp)

    if existing:
        print(f"CONFLICT ({tier_name}): this key already had a decision.")
        print(f"  key:       {args.scope} / {args.aspect}")
        print(f"  old value: {existing.get('value')!r}  (decided {existing.get('decided_at')})")
        print(f"  old reason: {existing.get('reason') or '(none given)'}")
        print(f"  new value: {args.value!r}")
        print(f"  new reason: {args.reason or '(none given)'}")
        print(f"  file: {path}")
        print(f"  history: {history_path(path)}  ({len(read_history(path))} records, append-only)")
        print("The old value is preserved in the history file above regardless of git, "
              "and in git history once you commit.")
        print("Flag this to the user — it may be an intentional change, or a mistake.")
    else:
        print(f"Logged ({tier_name}): {args.scope} / {args.aspect} = {args.value!r}")
        print(f"  file: {path}")

    warn_if_not_git_repo(root, tier_name)
    print(f"Remember to commit this change in the {tier_name} ledger's git repo"
          + (" and push it so your other machine picks it up." if tier_name == "global" else "."))


def cmd_history(args):
    tiers = []
    if args.global_:
        tiers = [("global", global_root())]
    elif args.local:
        tiers = [("local", local_root())]
    else:
        tiers = [("local", local_root()), ("global", global_root())]

    for tier_name, root in tiers:
        path = key_path(root, args.scope, args.aspect)
        records = read_history(path)
        if not records:
            continue
        print(f"HISTORY ({tier_name}): {args.scope} / {args.aspect} "
              f"— {len(records)} record(s), oldest first")
        for i, r in enumerate(records, 1):
            marker = "  (current)" if i == len(records) else ""
            print(f"  {i}. {r.get('decided_at')}  [{r.get('event', '?')}]{marker}")
            print(f"       value:  {r.get('value')!r}")
            if "reason" in r:
                print(f"       reason: {r.get('reason')}")
            else:
                # A record missing fields was almost certainly cut short by a
                # crash mid-append. Say so rather than printing "None".
                print("       reason: (incomplete record — likely truncated "
                      "by an interrupted write)")
        return

    print(f"NO HISTORY: nothing recorded for {args.scope} / {args.aspect}")
    print("Either the key was never logged, or it was last written before "
          "history files existed and has not been re-logged since.")


def iter_decisions(root: Path, scope_filter: str = None):
    if not root.exists():
        return
    for path in sorted(root.rglob("*.yaml")):
        rel = path.relative_to(root)
        aspect = path.stem
        scope = "/".join(rel.parts[:-1])
        if scope_filter and scope != scope_filter and sanitize_segment(scope_filter) not in rel.parts[:-1]:
            continue
        data = read_decision(path)
        if data:
            yield scope, aspect, data


STOPWORDS = {
    "the", "a", "an", "is", "in", "of", "for", "to", "and", "with", "on",
    "at", "this", "that", "no", "none", "given", "value", "reason", "test",
}


def tokenize(*parts: str):
    tokens = set()
    for part in parts:
        if not part:
            continue
        for word in re.split(r"[^a-z0-9]+", part.lower()):
            if word and word not in STOPWORDS and len(word) > 1:
                tokens.add(word)
    return tokens


def cmd_related(args):
    """Cheap, deterministic lexical retrieval -- NOT a semantic matcher.
    This surfaces candidates for a human (or the calling Claude session) to
    judge; it never decides a conflict itself. No embeddings, no similarity
    threshold to tune -- just token overlap plus a bonus for sharing a scope
    path segment, which is a strong "probably related" signal (e.g. two
    decisions both touching auth.py)."""
    query_tokens = tokenize(args.scope, args.aspect, args.value)
    query_scope_parts = {sanitize_segment(p) for p in args.scope.split("/") if p.strip()}
    query_key = (sanitize_segment(args.aspect),)

    tiers = []
    if args.global_ and not args.both:
        tiers = [("global", global_root())]
    elif args.local and not args.both:
        tiers = [("local", local_root())]
    else:
        tiers = [("local", local_root()), ("global", global_root())]

    scored = []
    for tier_name, root in tiers:
        for scope, aspect, data in iter_decisions(root):
            scope_parts = set(scope.split("/"))
            same_key = (
                scope_parts == query_scope_parts
                and sanitize_segment(aspect) == query_key[0]
                and tier_name == ("global" if args.global_ else "local")
            )
            if same_key:
                continue  # exact-key matches are handled by add/check's own conflict logic

            cand_tokens = tokenize(scope, aspect, data.get("value", ""), data.get("reason", ""))
            overlap = query_tokens & cand_tokens
            score = len(overlap)
            if scope_parts & query_scope_parts:
                score += 2  # shared scope segment is a stronger signal than a shared word
            if score > 0:
                scored.append((score, tier_name, scope, aspect, data, sorted(overlap)))

    scored.sort(key=lambda row: row[0], reverse=True)
    top = scored[:5]

    if not top:
        print("No related decisions found (cheap lexical check only -- this is not a semantic search).")
        return

    print(f"Possibly related decisions for {args.scope} / {args.aspect} "
          f"(lexical overlap only -- use judgment, not this score, to decide if it's a real conflict):")
    for score, tier_name, scope, aspect, data, overlap in top:
        print(f"  [{tier_name}] {scope} / {aspect} = {data.get('value')!r}  "
              f"(shared: {', '.join(overlap) if overlap else 'scope'}, decided {data.get('decided_at')})")


def cmd_list(args):
    tiers = []
    if args.global_ and not args.both:
        tiers = [("global", global_root())]
    elif args.local and not args.both:
        tiers = [("local", local_root())]
    else:
        tiers = [("local", local_root()), ("global", global_root())]

    found_any = False
    for tier_name, root in tiers:
        rows = list(iter_decisions(root, args.scope))
        if not rows:
            continue
        found_any = True
        print(f"-- {tier_name} ({root}) --")
        for scope, aspect, data in rows:
            print(f"{scope} / {aspect} = {data.get('value')!r}  ({data.get('decided_at')})")
    if not found_any:
        print("(no decisions logged yet)")


def cmd_export(args):
    tier_name = "global" if args.global_ else "local"
    root = global_root() if args.global_ else local_root()
    rows = list(iter_decisions(root))

    lines = [f"# Context Ledger ({tier_name})", "", "Auto-generated — do not edit by hand.", ""]
    by_scope = {}
    for scope, aspect, data in rows:
        by_scope.setdefault(scope, []).append((aspect, data))

    for scope in sorted(by_scope):
        lines.append(f"## {scope}")
        lines.append("")
        for aspect, data in sorted(by_scope[scope]):
            lines.append(f"### {aspect}")
            lines.append(f"- `{data.get('value')}` — {data.get('reason') or 'no reason given'} "
                         f"({data.get('decided_at')})")
            lines.append("")

    out_path = root.parent / "decisions.md" if tier_name == "global" else Path(".claude/decisions.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Exported {len(rows)} {tier_name} decisions to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Two-tier keyed context ledger for coding agents.")
    # add_subparsers(required=) is Python 3.7+; set the attribute instead so
    # this runs on 3.6 as well.
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_check = sub.add_parser("check", help="Look up a decision (local first, then global, unless flagged)")
    p_check.add_argument("scope")
    p_check.add_argument("aspect")
    p_check.add_argument("--global", dest="global_", action="store_true", help="check global tier only")
    p_check.add_argument("--local", action="store_true", help="check local tier only")
    p_check.set_defaults(func=cmd_check)

    p_add = sub.add_parser("add", help="Log a decision (overwrites any existing one at the same key)")
    p_add.add_argument("scope")
    p_add.add_argument("aspect")
    p_add.add_argument("value")
    p_add.add_argument("--reason", "-r", default="")
    p_add.add_argument("--global", dest="global_", action="store_true",
                        help="write to the global (cross-project) ledger instead of local")
    p_add.set_defaults(func=cmd_add)

    p_related = sub.add_parser(
        "related",
        help="Cheap lexical candidates across DIFFERENT keys that might overlap with a new decision (not a semantic matcher)",
    )
    p_related.add_argument("scope")
    p_related.add_argument("aspect")
    p_related.add_argument("value")
    p_related.add_argument("--global", dest="global_", action="store_true")
    p_related.add_argument("--local", action="store_true")
    p_related.add_argument("--both", action="store_true")
    p_related.set_defaults(func=cmd_related)

    p_list = sub.add_parser("list", help="List decisions")
    p_list.add_argument("--scope", default=None)
    p_list.add_argument("--global", dest="global_", action="store_true")
    p_list.add_argument("--local", action="store_true")
    p_list.add_argument("--both", action="store_true", help="show both tiers even if --local/--global given")
    p_list.set_defaults(func=cmd_list)

    p_hist = sub.add_parser("history", help="Show every recorded value for one key, oldest first")
    p_hist.add_argument("scope")
    p_hist.add_argument("aspect")
    p_hist.add_argument("--global", dest="global_", action="store_true")
    p_hist.add_argument("--local", action="store_true")
    p_hist.set_defaults(func=cmd_history)

    p_export = sub.add_parser("export", help="Write a human-readable markdown view of one tier")
    p_export.add_argument("--global", dest="global_", action="store_true", help="export the global tier")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
