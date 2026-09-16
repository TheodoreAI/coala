#!/usr/bin/env bash
set -uo pipefail
MODELS=("qwen3.5:0.8b" "qwen2.5-coder:7b" "qwen3.5:9b" "gpt-oss:20b" "gemma4:e4b")
for m in "${MODELS[@]}"; do
  safe=$(echo "$m" | tr ':/' '__')
  echo "=== $m ===" >&2
  python3 run_benchmark.py --base-url http://localhost:11434/v1 --model "$m" \
    --out "results_${safe}.json" --repeats 3 > "summary_${safe}.txt" 2>&1
  echo "done $m" >&2
done
