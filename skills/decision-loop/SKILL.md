---
name: decision-loop
description: "Structured propose -> evaluate -> select -> execute deliberation for a notable, risky, or ambiguous decision -- one that could plausibly be revisited later, affects more than the current line/step, or has genuinely competing approaches worth comparing. Generates 2-4 real candidates, scores them against explicit criteria, picks one with a stated reason, then executes -- rather than committing to the first approach that comes to mind. Composes with decision-ledger (check for a prior answer first; log the pick if it's a reusable technical decision) and episodic-memory (log the outcome so a future search surfaces the comparison, not just the end fact). Not for routine work with one obvious approach -- that should skip this entirely."
---

# Decision Loop

A reasoning discipline for the moment just before a notable decision gets made,
borrowed from CoALA's (arXiv 2309.02427) propose/evaluate/select/execute framing
of agent decision-making. It exists because the default failure mode is committing
to the first plausible approach without seriously naming or comparing alternatives
— which is fine for routine work, but costly for a decision that's hard to reverse
or likely to get revisited.

**This isn't decorative — it's the load-bearing part, not the memory tools alone.**
A benchmark (`google/gemma-4-31b-it`, 3 conditions x 4 synthetic tasks x 3 reps,
2026-09-15) tested whether just *having* `check_episodes`/`check_decision` tools
available is enough, without an explicit instruction to check first and deliberate.
It wasn't: with the tools present but no "check first, then propose/evaluate/select"
prompt, the model skipped them entirely and fell into the seeded trap *more* often
than a baseline with no memory tools at all (75% vs 50% trap rate) — the explicit
loop version cut it to 25%. Tool availability alone does not reproduce the benefit;
the explicit check-first-then-deliberate instruction does. Full write-up and raw
numbers: `../../benchmark/RESULTS.md` in this repo.

## When to use this

Same bar as the `decision-ledger` skill uses for logging a decision — reuse it
exactly, so the two stay aligned:

- could plausibly be revisited later (by you, in a future session, or by the user),
- affects more than the current line/step (a pattern, a contract, a strategy), or
- would cause a real problem if silently contradicted or redone worse elsewhere,
- **and** there are genuinely competing approaches worth comparing — not just one
  obvious path with no real alternative.

Skip it for routine implementation details, single-obvious-approach tasks, or
anything where naming alternatives would be theater rather than real comparison.

## The loop

1. **Check first.** Before proposing anything, check whether this was already
   decided: `python3 ../decision-ledger/scripts/decisions.py check <scope> <aspect>`
   (paths here assume the standard install layout — sibling skill directories
   under one skills root; adjust if yours differs). If found, follow it — this
   loop is for open questions, not re-litigating settled ones.
2. **Propose** — name 2-4 real candidate approaches. Not one approach plus straw
   men; each candidate should be something you'd actually be willing to execute.
3. **Evaluate** — score the candidates against criteria that actually matter for
   *this* decision (typically some mix of: correctness/risk, effort, reversibility,
   fit with existing patterns or prior decisions). State the criteria, don't just
   assert a winner.
4. **Select** — pick one, state the one-line reason it won.
5. **Execute** — proceed with implementation as normal.

Keep steps 2-4 terse and internal. This is a reasoning discipline, not a report to
generate for its own sake — per standing tone guidance, don't narrate internal
deliberation to the user. Surface only the final choice and its one-line rationale
in user-facing text, unless the user actually asked to see the options compared.

## Close the loop — log the outcome

Once execution finishes:

- **If the choice amounts to a reusable technical decision** (something a future
  session could contradict or need to know about), log it:

  ```bash
  python3 ../decision-ledger/scripts/decisions.py add <scope> <aspect> "<value>" --reason "<why, including what lost and to what>"
  ```

- **Always log the episode**, regardless of outcome, so a future "have I tried this
  before" search surfaces the comparison itself, not just the end fact:

  ```bash
  python3 ../episodic-memory/scripts/episodes.py log <scope> "<task>" \
    --outcome success|failure|partial|abandoned \
    --detail "<candidates considered + why one won>" \
    --lesson "<what to remember for next time>"
  ```

The episode's `--detail` is what makes this loop worth more than a decision alone:
it preserves *what else was considered and why it lost*, which a decision-ledger
entry (current value + reason) doesn't capture on its own.

## Relationship to the other two stores

- `decision-ledger` — checked at the start of this loop (don't re-decide a settled
  key) and written to at the end (if the pick is a durable choice).
- `episodic-memory` — written to at the end always, capturing the trajectory
  (candidates, comparison, outcome), which the decision-ledger's single current
  value doesn't hold.
- `memory` (facts) — untouched by this loop unless the process surfaces a durable,
  non-decision fact worth recording separately.
