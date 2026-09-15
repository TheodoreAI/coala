"""
Drives one task, under one condition ("baseline" or "coala"), against an
OpenAI-tool-calling-compatible chat endpoint (vLLM serving Gemma 4).

baseline: plain agent instructions, only try_approach/submit_answer tools.
coala:    decision-loop instructions (check first / propose / evaluate /
          select) plus check_episodes and check_decision tools backed by the
          REAL episodic-memory and decision-ledger scripts, pointed at a
          sandboxed per-task store seeded with that task's seed data. This
          exercises the actual scripts, not a simulation of them.

Each run is graded on:
  success        -- did submit_answer match the expected answer
  attempts       -- how many try_approach calls were made
  hit_trap       -- did it ever try the seeded-failure / wrong-default approach
  turns          -- how many model turns the whole episode took
  timed_out      -- hit the turn budget without submitting an answer
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import requests

from tasks import Task

SKILLS_ROOT = Path(r"C:/Users/mateo/.claude/skills")
EPISODES_PY = SKILLS_ROOT / "episodic-memory/scripts/episodes.py"
DECISIONS_PY = SKILLS_ROOT / "decision-ledger/scripts/decisions.py"

MAX_TURNS = 8

BASELINE_SYSTEM = (
    "You are an agent solving a small operational task. You have tools available "
    "for taking actions and submitting your final answer. Use them directly -- "
    "call try_approach for each candidate you want to test, or submit_answer once "
    "you know the answer. Don't explain at length; act."
)

COALA_SYSTEM = (
    "You are an agent solving a small operational task. Before committing to an "
    "approach: (1) check whether this was already tried or decided, using "
    "check_episodes and check_decision -- if a prior attempt failed or a decision "
    "was already made, do not repeat it; (2) if nothing is found, briefly propose "
    "the plausible candidates and pick the one best supported by the stated "
    "constraints; (3) then act, using try_approach or submit_answer. Don't "
    "explain at length; check first, then act."
)

# Isolates the memory TOOLS from the explicit deliberation PROMPTING: same
# check_episodes/check_decision tools as "coala", but the system prompt gives
# no instruction to check first or to propose/evaluate candidates -- it's
# worded exactly like BASELINE_SYSTEM plus one neutral sentence noting the
# tools exist. Tests whether having the tools alone (no discipline) recovers
# the "coala" benefit, or whether the explicit loop is what's doing the work.
NOLOOP_SYSTEM = (
    "You are an agent solving a small operational task. You have tools available "
    "for taking actions and submitting your final answer, including check_episodes "
    "and check_decision for looking things up if you want to. Use them directly -- "
    "call try_approach for each candidate you want to test, or submit_answer once "
    "you know the answer. Don't explain at length; act."
)


def build_tools(task: Task, condition: str):
    tools = []
    if task.approach_outcomes:
        tools.append({
            "type": "function",
            "function": {
                "name": "try_approach",
                "description": "Actually attempt a candidate approach and see if it works.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "Submit your final answer for this task.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    })
    if condition in ("coala", "coala-noloop"):
        tools.append({
            "type": "function",
            "function": {
                "name": "check_episodes",
                "description": "Search the episodic memory log for prior attempts relevant to this task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string"},
                        "terms": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["scope"],
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "check_decision",
                "description": "Check the decision ledger for an already-decided answer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string"},
                        "aspect": {"type": "string"},
                    },
                    "required": ["scope", "aspect"],
                },
            },
        })
    return tools


class Sandbox:
    """Isolated episodic/decision stores for one task run -- never touches the
    real global stores. Seeded only for the 'coala' condition."""

    def __init__(self, task: Task, condition: str):
        self.dir = Path(tempfile.mkdtemp(prefix="coala-bench-"))
        self.episodes_dir = self.dir / "episodes"
        self.decisions_dir = self.dir / "decisions"
        self.episodes_dir.mkdir()
        self.decisions_dir.mkdir()
        self.env = dict(os.environ)
        self.env["EPISODIC_MEMORY_DIR"] = str(self.episodes_dir)
        self.env["DECISION_LEDGER_GLOBAL"] = str(self.decisions_dir)
        if condition in ("coala", "coala-noloop"):
            if task.seed_episode:
                self._run(EPISODES_PY, "log", task.seed_episode["scope"],
                          task.seed_episode["task"],
                          "--outcome", task.seed_episode["outcome"],
                          "--detail", task.seed_episode["detail"],
                          "--lesson", task.seed_episode["lesson"])
            if task.seed_decision:
                self._run(DECISIONS_PY, "add", task.seed_decision["scope"],
                          task.seed_decision["aspect"], task.seed_decision["value"],
                          "--reason", task.seed_decision["reason"], "--global")

    def _run(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args],
                               env=self.env, capture_output=True, text=True)

    def check_episodes(self, scope, terms=None):
        if terms:
            r = self._run(EPISODES_PY, "search", *terms, "--scope", scope)
        else:
            r = self._run(EPISODES_PY, "recent", "--scope", scope)
        return (r.stdout or r.stderr).strip() or "(no episodes found)"

    def check_decision(self, scope, aspect):
        r = self._run(DECISIONS_PY, "check", scope, aspect, "--global")
        return (r.stdout or r.stderr).strip()

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def call_model(base_url, api_key, model, messages, tools):
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "tools": tools, "temperature": 0.2},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def run_task(task: Task, condition: str, base_url: str, api_key: str, model: str) -> dict:
    sandbox = Sandbox(task, condition)
    system = {
        "baseline": BASELINE_SYSTEM,
        "coala": COALA_SYSTEM,
        "coala-noloop": NOLOOP_SYSTEM,
    }[condition]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task.prompt},
    ]
    tools = build_tools(task, condition)

    attempts = 0
    hit_trap = False
    answer = None
    turns = 0

    try:
        for turns in range(1, MAX_TURNS + 1):
            msg = call_model(base_url, api_key, model, messages, tools)
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = "(unknown tool)"
                if name == "try_approach":
                    attempts += 1
                    approach = str(args.get("name", ""))
                    if task.trap_approach and approach == task.trap_approach:
                        hit_trap = True
                    result = task.approach_outcomes.get(approach, "unknown approach")
                elif name == "submit_answer":
                    answer = str(args.get("value", "")).strip()
                    result = "recorded"
                elif name == "check_episodes":
                    result = sandbox.check_episodes(args.get("scope", task.id), args.get("terms"))
                elif name == "check_decision":
                    result = sandbox.check_decision(args.get("scope", task.id), args.get("aspect", "value"))
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"], "content": str(result),
                })
            if answer is not None:
                break
    finally:
        sandbox.cleanup()

    success = (
        answer is not None and task.expected_answer is not None
        and answer.strip().lower() == task.expected_answer.strip().lower()
    )
    return {
        "task": task.id,
        "category": task.category,
        "condition": condition,
        "success": success,
        "answer": answer,
        "attempts": attempts,
        "hit_trap": hit_trap,
        "turns": turns,
        "timed_out": answer is None and turns >= MAX_TURNS,
    }
