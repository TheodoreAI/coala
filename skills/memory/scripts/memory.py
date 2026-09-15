#!/usr/bin/env python3
"""Read and write a persistent agent memory store.

Standalone note store for any agent that can shell out and read a SKILL.md
(opencode, Claude Code used as a plain skill, or anything else). One fact per
file, plus a MEMORY.md index that is the only thing loaded into context by
default. If your agent tool has its own separate built-in memory feature (e.g.
Claude Code's native per-project memory), this store is independent of it —
point AGENT_MEMORY_DIR at the same directory if you want the two to overlap.

Override the location with AGENT_MEMORY_DIR (defaults to ~/.claude/memory).
"""
import argparse
import os
import re
import sys
from pathlib import Path

# The index uses an em dash, which a cp1252 Windows console cannot encode; without
# this, printing the index raises UnicodeEncodeError rather than mis-rendering.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIR = str(Path.home() / ".claude" / "memory")
TYPES = ("user", "feedback", "project", "reference")
DASH = "\u2014"  # em dash, matching the existing index style


def store() -> Path:
    d = Path(os.environ.get("AGENT_MEMORY_DIR", DEFAULT_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_path() -> Path:
    return store() / "MEMORY.md"


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    # newline="" keeps our explicit \n from being rewritten to \r\n on Windows;
    # the existing store has a mix of both and either parses fine.
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def slug_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name))


def parse_front(text: str) -> dict:
    """Pull name/description/type out of the frontmatter.

    Deliberately not a YAML parser: the frontmatter here is a fixed three-field
    shape, and depending on PyYAML would give this skill an install step.
    """
    out = {}
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return out
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*(name|description|type):\s*(.*)$", line)
        if mm:
            v = mm.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[mm.group(1)] = v
    return out


def memories():
    for p in sorted(store().glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        yield p, parse_front(read_text(p))


def quote(v: str) -> str:
    """Quote only when a bare YAML scalar would be ambiguous, matching existing style."""
    if re.search(r":\s", v) or re.search(r"^[\s>|&*!%@\[\]{}#-]", v) or '"' in v or "'" in v:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


# ----------------------------------------------------------------- index sync

def set_index_line(name: str, title: str, hook: str) -> None:
    ip = index_path()
    lines = read_text(ip).splitlines() if ip.exists() else []
    new = "- [%s](%s.md) %s %s" % (title, name, DASH, hook)
    pat = re.compile(r"^- \[[^\]]*\]\(" + re.escape(name) + r"\.md\)")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            lines[i] = new
            break
    else:
        lines.append(new)
    write_text(ip, "\n".join(x for x in lines if x.strip()) + "\n")


def drop_index_line(name: str) -> None:
    ip = index_path()
    if not ip.exists():
        return
    pat = re.compile(r"^- \[[^\]]*\]\(" + re.escape(name) + r"\.md\)")
    kept = [ln for ln in read_text(ip).splitlines() if not pat.match(ln)]
    write_text(ip, "\n".join(x for x in kept if x.strip()) + "\n")


# ------------------------------------------------------------------- commands

def cmd_index(a):
    ip = index_path()
    print(read_text(ip).rstrip() if ip.exists() else "(index is empty)")


def cmd_read(a):
    p = store() / ("%s.md" % a.name)
    if not p.exists():
        sys.exit("NOT FOUND: %s" % a.name)
    print(read_text(p).rstrip())


def cmd_search(a):
    terms = [t.lower() for t in a.terms if len(t) > 2]
    if not terms:
        sys.exit("give at least one search term of 3+ characters")
    hits = []
    for p, fm in memories():
        body = read_text(p).lower()
        head = (fm.get("name", "") + " " + fm.get("description", "")).lower()
        # Name and description are what the index shows, so weight them above
        # body text: a term there means the memory is *about* that thing.
        score = sum(body.count(t) + 4 * head.count(t) for t in terms)
        if score:
            hits.append((score, p.stem, fm.get("description", "")))
    if not hits:
        print("NO MATCH")
        return
    for score, name, desc in sorted(hits, reverse=True):
        print("[%3d] %s\n      %s" % (score, name, desc))


def cmd_add(a):
    if not slug_ok(a.name):
        sys.exit("name must be kebab-case (got %r)" % a.name)
    if a.body_file:
        body = read_text(Path(a.body_file))
    elif a.body is not None:
        body = a.body
    else:
        body = sys.stdin.read()
    body = body.strip()
    if not body:
        sys.exit("refusing to write an empty memory")
    p = store() / ("%s.md" % a.name)
    existed = p.exists()
    if existed and not a.force:
        sys.exit("%s already exists. Re-run with --force to replace it, "
                 "or pick a different name." % a.name)
    front = ("---\nname: %s\ndescription: %s\nmetadata:\n  type: %s\n---\n\n"
             % (a.name, quote(a.description), a.type))
    write_text(p, front + body + "\n")
    title = a.title or a.name
    hook = a.hook or a.description
    set_index_line(a.name, title, hook)
    print("%s %s" % ("UPDATED" if existed else "WROTE", p))
    print("index line: - [%s](%s.md) %s %s" % (title, a.name, DASH, hook))


def cmd_append(a):
    """Add text to an existing memory without rewriting the rest of it.

    Rewriting a whole body to add one line is how bodies silently lose content,
    so this splices instead: the existing text is never re-emitted.
    """
    p = store() / ("%s.md" % a.name)
    if not p.exists():
        sys.exit("NOT FOUND: %s (use 'add' to create it)" % a.name)
    text = a.text
    if a.text_file:
        text = read_text(Path(a.text_file))
    if text is None:
        text = sys.stdin.read()
    text = text.strip()
    if not text:
        sys.exit("refusing to append empty text")
    s = read_text(p)
    m = re.match(r"(---\r?\n.*?\r?\n---\r?\n)(.*)$", s, re.S)
    if not m:
        sys.exit("%s has no frontmatter; fix it with 'add --force' first" % p.name)
    front, body = m.group(1), m.group(2).rstrip()
    write_text(p, front + body + "\n\n" + text + "\n")
    print("APPENDED to %s (+%d chars)" % (p, len(text)))

def cmd_remove(a):
    p = store() / ("%s.md" % a.name)
    if not p.exists():
        sys.exit("NOT FOUND: %s" % a.name)
    if not a.yes:
        sys.exit("would delete %s\nRe-run with --yes to confirm." % p)
    p.unlink()
    drop_index_line(a.name)
    print("DELETED %s" % p)


def cmd_check(a):
    """Report drift between the files on disk and the index."""
    names = {p.stem for p, _ in memories()}
    ip = index_path()
    linked = set(re.findall(r"\]\(([^)]+)\.md\)", read_text(ip))) if ip.exists() else set()
    ok = True
    for n in sorted(names - linked):
        print("UNINDEXED: %s.md exists but has no MEMORY.md line" % n)
        ok = False
    for n in sorted(linked - names):
        print("DANGLING : MEMORY.md links %s.md, which does not exist" % n)
        ok = False
    for p, fm in memories():
        if fm.get("name") != p.stem:
            print("MISMATCH : %s has frontmatter name %r" % (p.name, fm.get("name")))
            ok = False
        if fm.get("type") not in TYPES:
            print("BAD TYPE : %s has type %r" % (p.name, fm.get("type")))
            ok = False
    if ok:
        print("OK - %d memories, index in sync" % len(names))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(
        prog="memory.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("index", help="print MEMORY.md, the index of every memory"
                   ).set_defaults(fn=cmd_index)

    p = sub.add_parser("read", help="print one memory in full")
    p.add_argument("name")
    p.set_defaults(fn=cmd_read)

    p = sub.add_parser("search", help="rank memories by keyword overlap")
    p.add_argument("terms", nargs="+")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("add", help="write a new memory (or replace one with --force)")
    p.add_argument("name", help="kebab-case slug; becomes <name>.md")
    p.add_argument("--title", "-T", help="human-readable title for the index line")
    p.add_argument("--description", "-d", required=True,
                   help="one line; this is what decides relevance during recall")
    p.add_argument("--type", "-t", required=True, choices=TYPES)
    p.add_argument("--hook", help="index-line hook (defaults to --description)")
    p.add_argument("--body", "-b", help="memory text; omit to read stdin")
    p.add_argument("--body-file", help="read the body from a file instead")
    p.add_argument("--force", action="store_true", help="overwrite an existing memory")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("append", help="add text to an existing memory, keeping the rest")
    p.add_argument("name")
    p.add_argument("--text", "-x", help="text to append; omit to read stdin")
    p.add_argument("--text-file", help="read the text to append from a file")
    p.set_defaults(fn=cmd_append)

    p = sub.add_parser("remove", help="delete a memory and its index line")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_remove)

    sub.add_parser("check", help="report drift between files and the index"
                   ).set_defaults(fn=cmd_check)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
