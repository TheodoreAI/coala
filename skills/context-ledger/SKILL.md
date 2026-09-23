---
name: context-ledger
description: "Track technical decisions made while coding in a keyed ledger so Claude never silently re-decides or contradicts something it already decided earlier, including in past sessions and across different projects. Covers two tiers: LOCAL decisions specific to one codebase (architecture choices, library picks, data formats, retry/auth/config strategies for this project) and GLOBAL decisions that should hold across all the user's projects (default tooling, commit conventions, personal coding preferences), kept in sync across machines via its own git repo. Use this proactively, without being asked, whenever making or revisiting a notable design decision during coding work — check the ledger before deciding, log the decision after deciding. Also use when the user asks what did we decide about X, why did we do it this way, or wants a log or history of project or personal decisions."
---

# Context Ledger

> **Naming note: "context" here means McCarthy's contexts, not an LLM's context window.**
> The name comes from John McCarthy's formalization of context ("Notes on Formalizing
> Context", 1993), where `ist(c, p)` asserts that proposition `p` is true in context `c`.
> It has nothing to do with context length or the token window of a language model.
> Each entry is one such assertion: the tier plus `scope` identify the context `c`, and
> `aspect = value` is the proposition `p`. Local and global are nested contexts. A local
> entry overrides a global one at the same key, and a global entry lifts into any
> project that hasn't decided otherwise. The script (`decisions.py`), the global repo
> (`global-decisions/`), and the `DECISION_LEDGER_GLOBAL` env var keep their old names so
> existing ledgers keep working.

A ledger that lets Claude check "have I already decided this?" and "did I just contradict myself?" without ever needing to judge whether two decisions are semantically "the same" — that question (proposition identity) is open in general, going back to Frege. This works by never trying to solve it: a decision is identified by an exact `(scope, aspect)` key that whoever logs it chooses. Two decisions only ever get compared if they share a key.

For *generating and scoring the candidates* before you get here — i.e. the step that produces the value this ledger then stores — see the `decision-loop` skill. This skill only handles checking/logging the outcome, not the deliberation itself.

## Two tiers — pick the right one

**LOCAL** — decisions specific to *this codebase*: this project's retry policy, this project's token format, this project's schema shape. Stored at `.claude/decisions/` inside the project. Rides along with the project's own git history automatically — no extra sync needed, it's just part of the repo.

**GLOBAL** — decisions that should hold across *all* the user's projects: a default package manager, a commit-message convention, a personal formatting preference. Stored in its own separate git repo (default `~/.claude/global-decisions/`, overridable via the `DECISION_LEDGER_GLOBAL` env var), so the user can push/pull it across machines independently of any one project.

**How to choose:** ask "would this decision make sense in a totally different project?" If yes — it's about the user's general preferences or tooling, not this codebase — it's global. If it only makes sense in the context of this specific system's architecture, it's local. When genuinely unsure, default to local; it's the lower-consequence guess (a local decision won't leak into unrelated projects, whereas a wrongly-global one might get "found" and applied somewhere it doesn't belong).

## When to use this

Use it automatically, without being asked, whenever coding work involves a **notable technical decision** — one that:
- could plausibly be revisited later (by you, in a future session, or by the user),
- affects more than the current line (a pattern, a contract, a strategy), or
- would cause a real problem if silently contradicted elsewhere.

Don't log routine implementation details that don't meet that bar — variable names, which loop construct to use. If everything gets logged, the ledger stops being useful signal.

## Workflow

All operations go through the bundled script — never hand-edit ledger files unless fixing a mistake, and never touch the internal format.

### 1. Before deciding — check first

```bash
python3 <skill_path>/scripts/decisions.py check <scope> <aspect>
```

With no flag, this checks **local first, then falls back to global** — so a project-specific decision correctly overrides a general personal preference if both exist for the same key, while a general preference still surfaces when the project hasn't decided anything of its own. Add `--global` or `--local` to restrict to one tier (useful when you already know which kind of decision you're dealing with).

- `scope` — for local: the file, module, or feature area (`auth.py`, `checkout-flow`). For global: a topic (`python-tooling`, `commit-style`, `date-format`).
- `aspect` — the specific question, short and kebab-case, reused exactly every time this question comes up (`retry-policy`, `package-manager`). Stability of naming is what makes the key system work — don't rename an aspect between sessions.

If `FOUND`: follow it. Don't silently re-derive a different answer. If you have a real reason to change it, say so to the user before overriding, then log the new decision (step 2).

If `NOT FOUND`: this only means no *same-key* decision exists. Before deciding fresh, also run:

```bash
python3 <skill_path>/scripts/decisions.py related <scope> <aspect> "<the value you're about to decide>"
```

This surfaces decisions at *different* keys that share vocabulary or a scope segment with what you're about to log — pure lexical overlap, not a semantic matcher. It's deliberately recall-oriented: it will surface some candidates that turn out unrelated (e.g. a UI decision that happens to also mention "retry"), and that's expected — its job is to put plausible neighbors in front of you, not to decide anything. **You make the actual call**, the same way you'd judge any two facts for consistency:
- Nothing returned, or everything returned is obviously unrelated → decide fresh and log it.
- Something returned genuinely bears on the decision you're about to make (e.g. it assumes something your new decision would contradict) → don't silently proceed. Treat it like the same-key conflict case: flag it to the user before or as part of logging (see step 3 below for how), then log your decision either way — the goal is visibility, not blocking.

### 2. After deciding — log it

```bash
# local (default)
python3 <skill_path>/scripts/decisions.py add <scope> <aspect> "<value>" --reason "<one-line why>"

# global
python3 <skill_path>/scripts/decisions.py add <scope> <aspect> "<value>" --reason "<one-line why>" --global
```

Logging to a key that already has a value **overwrites the file** — the script prints `CONFLICT` with old vs. new side by side. The old value is preserved two ways, and the distinction matters:

- **Always**, in an append-only `<aspect>.history` file written next to the decision *before* the overwrite. This does not depend on anyone committing, so logging the same key twice in one session can never silently lose the first value.
- **Additionally**, in git once the change is committed — `git log -p <file>` shows every past value alongside the reason it changed.

Run `decisions.py history <scope> <aspect>` to see every value ever written at a key, oldest first. History files are excluded from `list`, `related`, and `export`, which only ever report current values.

**When you see a `CONFLICT`, always surface it to the user in your reply** — a sentence is enough. Don't let it happen silently in a tool call.

**Cross-key conflicts (from `related`) are surfaced differently from `CONFLICT`, because they're less certain.** A same-key `CONFLICT` is exact — same path, no ambiguity. A cross-key finding from `related` came from lexical overlap plus your own judgment, so it can be wrong. Never call it a "conflict" outright; say something like "worth noting — this may be in tension with the earlier decision that..." and let the user weigh it. Like same-key conflicts, this never blocks the write: log the decision either way, just make sure the possible tension is visible in your reply rather than buried in a tool call the user didn't see.

**After logging, commit the change** — the append-only history file protects the value locally, but committing is still what shares it and what puts the change in the project's real history. in the relevant tier's git repo (`git add -A && git commit -m "..."` in the project repo for local, or in the global ledger's own repo for global). For a global write, if a remote is configured, push it too — that's what actually gets the decision onto the user's other machine. If the global ledger isn't a git repo yet, the script will print setup instructions; walk the user through them once, then it's a normal git remote from then on.

At the start of a session, if you're about to rely on the global tier for a decision that matters, it's worth a quick `git pull` in the global repo first, so you're not reading a stale copy from before changes made on another machine.

### 3. Reviewing decisions

```bash
python3 <skill_path>/scripts/decisions.py list                     # both tiers
python3 <skill_path>/scripts/decisions.py list --local              # local only
python3 <skill_path>/scripts/decisions.py list --global             # global only
python3 <skill_path>/scripts/decisions.py list --scope auth.py      # filter

python3 <skill_path>/scripts/decisions.py export                    # local -> .claude/decisions.md
python3 <skill_path>/scripts/decisions.py export --global           # global -> <global-root>/../decisions.md
```

Export after a batch of decisions, or when the user asks to see decision history. The local export is good to commit to the project repo so humans and future sessions can browse it without running the script. The global export is good to commit to the global ledger repo for the same reason.

## What this does and doesn't catch

**Catches:** the same question decided two different ways at two different times — locally, globally, or one overriding the other.

**Doesn't catch:** two *different* keys that conflict in substance (e.g. a local `auth.py / token-expiry-strategy` says stateless, but a different local scope quietly assumes stateful tokens). That requires actually solving semantic identity in general, which nothing does reliably. Mitigate normally: keep related decisions in clearly related scopes, and use judgment.

## If `check` errors out with a merge conflict

This means the same key was decided differently on two machines before the global ledger was synced — git left `<<<<<<<` conflict markers in the file instead of silently picking one. Don't try to route around it; resolve it explicitly: open the file, pick the value that should win (or log a fresh decision that supersedes both — that's often the more honest move), remove the conflict markers, commit. Tell the user this happened; it's exactly the kind of contradiction this tool exists to surface, not hide.

## Notes

- **First-time global setup**: run `scripts/init_global_repo.sh` once — it `git init`s the global root (default `~/.claude/global-decisions`, or wherever `DECISION_LEDGER_GLOBAL` points), copies in the `.gitattributes` template, and makes the first commit. It's safe to re-run (skips whatever's already done) and checks for a configured git identity first, printing clear instructions instead of failing on a raw git error if one isn't set up yet. It prints the remaining steps (create a remote, push, clone on the other machine) since those require the user's own git hosting account.
- `scope`/`aspect` naming is the whole mechanism — pick deliberately and reuse exactly. Case doesn't distinguish keys: `Auth.py` and `auth.py` are normalized to the same file, so identity stays consistent whether a decision was logged on a case-sensitive filesystem (Linux) or a case-insensitive one (macOS/Windows).
- **Cross-machine/cross-OS setup**: copy `assets/gitattributes-template` to `.gitattributes` at the root of each git repo the ledger lives in (the project repo for local, the global ledger's own repo for global). This pins line endings to LF on checkout, so cloning the same repo on Windows vs. macOS/Linux doesn't rewrite every file and bury real changes in cosmetic diff noise. Do this once per repo, right after `git init`.
- If `python3` isn't on PATH (some Windows setups only have `python`), use whichever command actually resolves to Python 3 on that machine — the script itself doesn't care which one invokes it.
- The `DECISION_LEDGER_GLOBAL` env var (if you use it to point at a non-default global location) needs to be set separately on each machine — it's a local environment setting, not something git syncs for you.
- If the user only has one laptop or doesn't want cross-machine sync, the global tier still works locally — it's just not synced. Nothing about it requires git; git is only needed for the multi-machine case.
