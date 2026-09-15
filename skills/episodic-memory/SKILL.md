---
name: episodic-memory
description: "Append-only log of attempts and their outcomes — 'on this date I tried X, here's what happened, here's the lesson.' Distinct from the memory skill (durable facts) and decision-ledger (keyed choices): this is a searchable trajectory history for nontrivial or multi-attempt tasks, especially ones that failed, partially worked, or took several tries. Use it to log a finished attempt at something nonobvious, and to check whether a similar attempt was already made before starting a recurring or tricky task. Not for facts (use memory) or for choices with one current value (use decision-ledger)."
---

# Episodic Memory

A log of *experiences*, not facts or choices. The `decision-loop` skill is a common
source of episodes worth logging here — after proposing/evaluating candidates and
executing one, its outcome (including what else was considered and why it lost)
belongs in this store.

Three stores exist and they answer different questions:

- **memory** (semantic) — "what is true?" One file per fact, current-truth only.
- **decision-ledger** (procedural/keyed) — "what did we decide, and does this
  contradict it?" One active value per `(scope, aspect)` key, with history.
- **episodic-memory** (this) — "have I tried this before, and what happened?"
  Many entries expected, purely additive, no "current value" — every attempt
  is its own record, kept forever.

The same underlying event can produce entries in more than one store: e.g.
after a failed cluster job, you might log an episode here (*what was tried
and why it failed*) **and** a memory (*the durable fact about the constraint
you discovered*). They're not redundant — the episode is the trajectory, the
memory is the distilled fact extracted from it.

All operations go through the bundled script — it's append-only JSONL, so
don't hand-edit the log file (a manual edit risks corrupting a line that other
tooling then can't parse).

    python3 <skill_path>/scripts/episodes.py <command>

## When to log an episode

After finishing a nontrivial task that involved real trial and error —
especially if it failed, partially worked, took multiple attempts, or you'd
want to know "did I already try this" before repeating it later. Prime
candidates:

- A debugging session where the first N approaches didn't work.
- Any task that ended in failure or was abandoned — these are the ones most
  worth recording, since they're otherwise the easiest to silently repeat.
- A multi-step operational task (deploying something, submitting a cluster
  job, migrating a config) where the sequence of actions itself is useful to
  recall, not just the end state.

Don't log routine work that succeeded on the first try with nothing surprising
— that's not costly to redo and doesn't need a trajectory record. (A durable
fact discovered along the way might still be worth a `memory` entry even if no
episode is logged.)

```bash
python3 <skill_path>/scripts/episodes.py log <scope> "<one-line task>" \
  --outcome success|failure|partial|abandoned \
  --detail "<what was actually tried / actions taken>" \
  --lesson "<the key takeaway for next time>"
```

- `scope` — a short freeform tag for what area this belongs to (`cluster`,
  `clipboard-sync`, `opencode`, `photo-to-3d`). Reuse existing scopes where
  they fit — run `scopes` to see what's already in use — but unlike the
  decision ledger's keys, there's no strict identity requirement here.
- `task` — one line, specific enough to recognize on a later `recent`/`search`
  scan.
- `--detail` — what happened: the actions taken, the error seen, the sequence
  of attempts. Use `--detail-file` for anything long.
- `--lesson` — optional but worth including whenever there is one: the one
  sentence you'd want to read *before* trying this again.

## When to check before starting

Before a nontrivial or recurring task — especially one that smells like
something you (or a past session) may have already attempted — search first:

```bash
python3 <skill_path>/scripts/episodes.py recent --scope <scope>   # recent activity in an area
python3 <skill_path>/scripts/episodes.py search <term> [<term>...]  # keyword search across everything
python3 <skill_path>/scripts/episodes.py show <id>                  # full detail on one episode
```

`search` is lexical, not semantic, same caveat as the memory skill's search:
a `NO MATCH` means no keyword hit, not "this was never tried." A `recent`
scan of the relevant scope is often more useful than a keyword guess for
open-ended "has this come up before" questions.

If a past episode shows `failure` or `abandoned` for something close to what
you're about to do, say so before repeating the approach — that's the entire
point of this store.

## Health check

```bash
python3 <skill_path>/scripts/episodes.py check
```

Validates every line parses, has a valid `outcome`, and has no duplicate
`id`. Corrupted or partial lines from an interrupted write are skipped by
every other command automatically, but `check` is what surfaces that it
happened.

## Where it lives

`~/.claude/episodes/episodes.jsonl` by default, overridable with the
`EPISODIC_MEMORY_DIR` environment variable. Single append-only file, one JSON
object per line, never rewritten in place.
