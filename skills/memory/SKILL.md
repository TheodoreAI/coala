---
name: memory
description: "Persistent cross-session memory about the user, their machines, and their ongoing projects. Read it to recall facts established in earlier sessions (how to reach a host, where a runtime lives, what a project is for, how the user wants you to work); write to it when something durable and non-obvious is learned that would be costly to rediscover. Use when the user says remember this, when you learn a fact that will still matter next week, or when a task touches infrastructure or a project you may have notes on already. Not for decisions -- those go in the context-ledger skill."
---

# Memory

Long-term memory shared with Claude Code. One fact per file, plus a `MEMORY.md`
index of one-line hooks. The index is what gets loaded by default; individual
memories are read on demand. That split is the whole design — it keeps recall
cheap, so the store can grow without every session paying for all of it.

All operations go through the bundled script. Do not hand-edit the files: the
index and the frontmatter have to stay in sync, and `add` maintains both.

    python3 <skill_path>/scripts/memory.py <command>

## Recall — before you assume you don't know something

    python3 <skill_path>/scripts/memory.py index
    python3 <skill_path>/scripts/memory.py search <term> [<term>...]
    python3 <skill_path>/scripts/memory.py read <name>

Read `index` at the start of a session that touches the user's machines,
clusters, or named projects. It is small. When a hook looks relevant, `read`
that one file — don't read them all.

`search` is lexical, not semantic: it ranks by keyword overlap, weighting the
name and description above body text. It will miss a memory that uses different
vocabulary for the same thing, so a `NO MATCH` means "no keyword hit", not "no
such memory". Check `index` before concluding nothing is recorded.

**Memories describe what was true when written.** If one names a file, host,
flag, or command, verify it still exists before acting on it.

## Writing — after you learn something durable

    python3 <skill_path>/scripts/memory.py add <name> \
      --title "<human-readable title>" \
      --description "<one line that decides relevance during recall>" \
      --type <user|feedback|project|reference> \
      --body "<the fact>"

`<name>` is a kebab-case slug and becomes `<name>.md`. Long bodies are easier to
pass with `--body-file <path>`, or on stdin if `--body` is omitted.

Writing to a name that already exists fails unless you pass `--force`. That is
deliberate: silently overwriting a memory is how a store quietly loses facts.
If you mean to revise one, `read` it first, then re-`add` with `--force`.

### The four types

- `user` — who the user is: role, expertise, standing preferences.
- `feedback` — guidance on how you should work, both corrections and confirmed
  approaches. Include the reasoning, then how to apply it.
- `project` — ongoing work, goals, or constraints not derivable from the code or
  git history. Convert relative dates to absolute ones ("last Tuesday" is
  useless in three months).
- `reference` — pointers to external resources: URLs, dashboards, tickets.

### What earns a memory

Something durable and non-obvious that would be **costly to rediscover** — a
constraint found by probing, a silent-failure mode, a decided architecture, a
preference the user stated once. Link related memories inline with
`[[other-name]]`; a link to a memory that doesn't exist yet is fine, it marks
something worth writing later.

Do **not** write down:

- anything the repository already records — code structure, git history, a fix
  you just made, contents of a `CLAUDE.md` or `AGENTS.md`;
- things that only matter inside the current conversation;
- technical decisions. Those belong in the `context-ledger` skill, which keys
  them by `(scope, aspect)` so a later session can detect that it is about to
  contradict one. Memory has no such conflict detection — it is for facts, not
  choices.

If the user asks you to remember something in one of those categories, ask what
was non-obvious about it and record *that* instead.

Before adding, `search` for what you're about to write. Update the existing
memory rather than creating a near-duplicate — two files saying almost the same
thing is how the index stops being trustworthy. Delete memories that turn out to
be wrong:

    python3 <skill_path>/scripts/memory.py remove <name> --yes

## Health check

    python3 <skill_path>/scripts/memory.py check

Reports drift: files with no index line, index lines pointing at missing files,
frontmatter whose `name` disagrees with the filename, invalid types. Exits
nonzero if anything is off. Worth running after any manual edit to the store.

## Where it lives

`~/.claude/memory/` by default, overridable with the `AGENT_MEMORY_DIR`
environment variable. This is a standalone store independent of any
agent-tool-specific built-in memory feature — if your tool has one of those
too (e.g. Claude Code's native per-project memory) and you want the two to
overlap, point `AGENT_MEMORY_DIR` at that same directory; otherwise this skill
works the same way in any agent that can shell out and read a `SKILL.md`.
