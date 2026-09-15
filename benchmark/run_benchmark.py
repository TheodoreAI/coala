#!/usr/bin/env python3
"""
Run the full CoALA benchmark: every task x both conditions, against a
Gemma-4 vLLM endpoint (OpenAI-compatible).

    python run_benchmark.py --base-url http://127.0.0.1:8003/v1 \
        --model gemma-4-31b-it --api-key "$(cat ~/.osu-llm/vllm-api-key)"

Writes results.json and prints a summary table.
"""
import argparse
import json
import sys
from pathlib import Path

from tasks import TASKS
from harness import run_task


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--repeats", type=int, default=1,
                     help="repeat each task x condition N times to smooth noise")
    a = ap.parse_args()

    CONDITIONS = ("baseline", "coala", "coala-noloop")
    records = []
    for task in TASKS:
        for condition in CONDITIONS:
            for i in range(a.repeats):
                print(f"running {task.id} [{condition}] rep {i+1}/{a.repeats} ...",
                      file=sys.stderr)
                try:
                    rec = run_task(task, condition, a.base_url, a.api_key, a.model)
                except Exception as e:
                    rec = {"task": task.id, "category": task.category,
                           "condition": condition, "error": str(e)}
                records.append(rec)
                print(f"  -> {rec}", file=sys.stderr)

    Path(a.out).write_text(json.dumps(records, indent=2))

    print("\n=== summary ===")
    for condition in CONDITIONS:
        rows = [r for r in records if r.get("condition") == condition and "error" not in r]
        if not rows:
            continue
        n = len(rows)
        succ = sum(r["success"] for r in rows) / n
        trap = sum(r["hit_trap"] for r in rows) / n
        avg_attempts = sum(r["attempts"] for r in rows) / n
        avg_turns = sum(r["turns"] for r in rows) / n
        print(f"{condition:10s}  success={succ:.0%}  hit_trap={trap:.0%}  "
              f"avg_attempts={avg_attempts:.1f}  avg_turns={avg_turns:.1f}  n={n}")

    errors = [r for r in records if "error" in r]
    if errors:
        print(f"\n{len(errors)} run(s) errored -- see {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
