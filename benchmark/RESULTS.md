# Benchmark results

Three runs of `run_benchmark.py`'s synthetic tasks (`tasks.py`): 4 tasks x 3
reps per condition, against real vLLM-served models. Each task has a seeded
"trap" (a plausible wrong first choice) and, for the CoALA-style conditions, a
seeded episodic-memory or decision-ledger entry that — if actually consulted —
avoids the trap on the first try. Full task definitions in `tasks.py`.

## Run 1 — Gemma-4-31B-it, cluster, baseline vs. coala (2 conditions)

| condition | success | hit_trap | avg_attempts | avg_turns |
|---|---|---|---|---|
| baseline | 100% | 50% | 1.8 | 2.8 |
| coala | 100% | 17% | 0.9 | 3.8 |

`coala` = memory tools (`check_episodes`/`check_decision`) **plus** an explicit
system-prompt instruction to check first, then propose/evaluate/select before
acting. Clean win on the decision-ledger task (`service_port_pick`: 100%
avoidance), partial on the episodic-memory task (`gpu_partition_pick`: 2/3),
no differentiation on the two tasks that were trivial for both conditions.

## Run 2 — gemma4:e4b (much smaller, local Ollama), same 2 conditions

| condition | success | hit_trap | avg_attempts | avg_turns |
|---|---|---|---|---|
| baseline | 100% | 75% | 2.0 | 3.0 |
| coala | 100% | 58% | 1.8 | 3.9 |

Same model family, far fewer active params. The `coala` benefit shrank sharply.
Tracing a `service_port_pick` run showed why: the model called `check_episodes`
instead of the more specific `check_decision` and never noticed the seeded
ledger entry — it picked the wrong tool for the task category even though both
were offered and it had been told to check first. A capability gap, not a
scaffolding failure.

## Run 3 — Gemma-4-31B-it, cluster, baseline vs. coala vs. coala-noloop (3 conditions)

Added `coala-noloop`: identical `check_episodes`/`check_decision` tools, but
the system prompt only mentions they exist — no instruction to check first or
to propose/evaluate/select. Isolates "having the tools" from "being told to
use them deliberately."

| condition | success | hit_trap | avg_attempts | avg_turns |
|---|---|---|---|---|
| baseline | 100% | 50% | 1.8 | 2.8 |
| coala | 100% | 25% | 1.0 | 3.8 |
| coala-noloop | 100% | **75%** | 2.0 | 3.0 |

**Key finding: `coala-noloop` was worse than baseline, not just non-better.**
With the tools available but no instruction to use them, this run of the model
never called them on the seeded tasks and fell into the trap more often than a
baseline with no memory tools at all. The explicit "check first, then
propose/evaluate/select" instruction — not tool availability — is what
produces the benefit.

## Takeaways

1. The `decision-loop` skill's explicit deliberation prompt is load-bearing.
   Handing an agent memory tools without instructing it to check them first is
   not a lesser version of the benefit — on this evidence, it can be actively
   worse than not having the tools, likely because the extra tool definitions
   add noise/latency without being used.
2. This doesn't obviously get fixed by scaling down further, but the opposite
   direction (Run 2) suggests it doesn't just disappear at scale either — a
   smaller model can have the discipline (told to check first) but still fail
   because it picks the wrong tool for the situation. Two distinct failure
   modes: **not checking at all** (coala-noloop) vs. **checking the wrong
   thing** (small model, coala).
3. Neither failure mode is solved by better prompting alone at a fixed model
   size — Run 2's model was already told to check first and still misfired.
   Worth testing whether more capable models fix the wrong-tool-selection
   failure mode specifically, independent of whether they need the explicit
   loop instruction at all (Run 3 suggests even capable models still need it).

Raw JSON for all three runs is not checked in (regenerate with
`run_benchmark.py` against your own endpoint) — this file is the durable
record of what was measured and why it matters.
