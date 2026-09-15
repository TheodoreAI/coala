# coala

Memory and deliberation scaffolding for coding agents, based on the cognitive
architecture in [CoALA](https://arxiv.org/abs/2309.02427) (Sumers et al.,
"Cognitive Architectures for Language Agents"). Four self-contained skills,
each a `SKILL.md` plus a small standalone Python script — no framework, no
dependencies beyond Python 3.6+.

## What's in here

| Skill | Answers | Storage |
|---|---|---|
| `memory` | "What is true?" | One markdown file per fact + an index |
| `decision-ledger` | "What did we decide, and does this contradict it?" | One current value per `(scope, aspect)` key, with full history |
| `episodic-memory` | "Have I tried this before, and what happened?" | Append-only JSONL log, one record per attempt |
| `decision-loop` | The moment before a decision: check first, propose 2-4 real candidates, evaluate against explicit criteria, select, execute | (Reasoning discipline — no storage of its own; writes to the two above) |

These map onto CoALA's memory taxonomy (semantic / procedural / episodic) plus
its propose-evaluate-select-execute decision cycle — see each skill's
`SKILL.md` for the specific correspondence.

## Why the decision-loop skill isn't optional dressing

It's tempting to think that just handing an agent memory tools is enough —
that a capable model will reach for them when useful. `benchmark/RESULTS.md`
has the numbers from three actual runs against live vLLM-served models, but
the headline: a run that gave a strong model (`Gemma-4-31B-it`) the exact same
`check_episodes`/`check_decision` tools as the full loop, minus the explicit
"check first, then propose/evaluate/select" prompt, did **worse than a
baseline with no memory tools at all** (75% vs 50% trap rate on a seeded
decision task) — the model just never called them. The full loop cut that to
25%. The explicit deliberation instruction is the load-bearing part.

## Install

```bash
git clone <this-repo> coala
cd coala
./install.sh                          # -> ~/.claude/skills
./install.sh ~/.config/opencode/skills # or wherever your agent looks for skills
```

Then wire the four skills into your agent's instructions file — `install.sh`
prints the exact snippet at the end, and each `SKILL.md` has the full command
reference. This is a manual step on purpose: this repo won't silently edit
your `CLAUDE.md`/`AGENTS.md`/equivalent.

## Portability notes

- Every script defaults to a location under `~/.claude/` and is fully
  overridable via an environment variable (`AGENT_MEMORY_DIR`,
  `DECISION_LEDGER_GLOBAL`, `EPISODIC_MEMORY_DIR`) — set these if you want the
  stores to live somewhere else, or to point two agent tools at the same data.
- `decision-loop`'s references to its sibling skills assume the standard
  install layout (all four skills as sibling directories under one skills
  root). If you install them somewhere non-standard, adjust the relative
  paths in `skills/decision-loop/SKILL.md`.
- Nothing here requires cloud services, a database, or network access. The
  decision-ledger's *global* tier can optionally sync across machines via its
  own git repo (`decision-ledger/scripts/init_global_repo.sh`) — that's the
  only piece with a multi-machine story built in; the rest is local files.

## Benchmark harness

`benchmark/` contains the harness used to produce `RESULTS.md`: synthetic
tasks with a seeded "trap" and a seeded memory/decision entry that avoids it,
run against a real OpenAI-tool-calling-compatible endpoint (tested against
vLLM and Ollama). Useful if you want to re-run the comparison against your own
model:

```bash
cd benchmark
python3 run_benchmark.py --base-url http://localhost:11434/v1 --model <your-model> --repeats 3
```

It seeds and reads from a temporary sandboxed copy of the memory/decision
stores (via the same env-var overrides above), never your real ones.

## License

MIT — see `LICENSE`.
