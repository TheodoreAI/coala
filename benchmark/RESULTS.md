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

## Run 4 — five local Ollama models, baseline vs. coala vs. coala-noloop

Same 3-condition harness as Run 3, swept across every tool-calling-capable
model pulled locally (2026-09-15). `nomic-embed-text` excluded (embedding-only).
`qwen2.5-coder:7b` excluded from the comparison below — see note.

| model | condition | success | hit_trap | avg_attempts | avg_turns |
|---|---|---|---|---|---|
| qwen3.5:0.8b | baseline | 83% | 50% | 1.8 | 3.1 |
| qwen3.5:0.8b | coala | 50% | 50% | 2.0 | 4.1 |
| qwen3.5:0.8b | coala-noloop | 50% | 50% | 2.3 | 3.1 |
| qwen3.5:9b | baseline | 100% | 75% | 2.2 | 2.9 |
| qwen3.5:9b | coala | 100% | 50% | 1.8 | 4.2 |
| qwen3.5:9b | coala-noloop | 100% | 67% | 2.2 | 2.8 |
| gpt-oss:20b | baseline | 50% | 75% | 2.0 | 3.0 |
| gpt-oss:20b | coala | 75% | 50% | 1.5 | 4.5 |
| gpt-oss:20b | coala-noloop | 67% | 67% | 1.9 | 2.9 |
| gemma4:e4b | baseline | 100% | 75% | 2.0 | 3.0 |
| gemma4:e4b | coala | 100% | 58% | 1.8 | 4.0 |
| gemma4:e4b | coala-noloop | 100% | 75% | 2.0 | 3.0 |

**`qwen2.5-coder:7b` produced 0% across all three conditions** (`avg_attempts=0,
avg_turns=1` everywhere) — not a CoALA result. A raw request confirmed this
Ollama build never emits an OpenAI-style `tool_calls` field for this model; it
describes the JSON shape in prose instead ("you should mention the name...").
The harness correctly reads that as "no tool call, end of episode." This is a
tool-calling-support gap in the model/quant, not something the scaffolding can
fix — excluded from conclusions below.

Takeaways from this sweep:

- **Full `coala` reduced `hit_trap` on every model that could use tools at
  all** (qwen3.5:9b 75%→50%, gpt-oss:20b 75%→50%, gemma4:e4b 75%→58%), except
  the smallest model, where it isn't a scaffolding win at all — see next point.
- **`qwen3.5:0.8b` is too small for the tools to help.** `coala` and
  `coala-noloop` both *dropped* success rate from 83% to 50% versus baseline,
  with `hit_trap` unchanged — the extra tool surface seems to cost this model
  more (fumbled/ignored calls, wasted attempts) than it gains from the one time
  it does check. Adding tools isn't free at this size.
- **`coala-noloop` is inconsistent on local models**, unlike the sharp
  "actively worse than baseline" result on the 31B cluster run (Run 3). Here it
  lands between baseline and full `coala` for qwen3.5:9b and gpt-oss:20b, and
  ties baseline exactly for gemma4:e4b and qwen3.5:0.8b. It never *beats* full
  `coala`, but it doesn't reliably backfire either — the "worse than no tools"
  effect may be specific to strong-but-undirected models that are otherwise
  disposed to explore, rather than universal.
- Net: across every model that can actually place tool calls, full `coala`
  (tools + explicit check-first/propose/evaluate prompt) was the best or tied-
  best condition on `hit_trap`. It was never the worst. That holds from
  0.8B-ish local models up through a 31B cluster-served model, which is some
  evidence against "better models make this scaffolding obsolete" — the
  ordering held at every scale tested except the one too small to use tools at
  all.

Raw JSON for all four runs is not checked in (regenerate with
`run_benchmark.py` against your own endpoint) — this file is the durable
record of what was measured and why it matters.
