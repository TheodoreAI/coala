"""
Task definitions for the CoALA benchmark.

Each task is a small ground-truth simulation, not a real system: `try_approach`
just looks up a canned outcome instead of actually running anything. That's
deliberate — the thing under test is whether the *scaffolding* (episodic
memory / decision ledger / propose-evaluate-select) changes what the model
tries first and how many attempts it needs, not whether Gemma can operate a
real service.

Two categories:

  episodic-avoidance — a prior failed attempt is seeded in episodic memory.
    The CoALA condition can find it via `check_episodes`; the baseline
    condition has no such tool and must discover the failure by trial.

  decision-avoidance / decision-loop — either a settled answer is seeded in
    the decision ledger (decision-avoidance), or there's no seed and the task
    is a judgment call between explicit-tradeoff candidates where a
    propose/evaluate pass should out-perform picking the first obvious option
    (decision-loop).

Each task provides its own seed data (what to write into the sandboxed
episodic/decision stores before the CoALA run) so seeding and grading live
next to the fact they encode instead of drifting apart.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Task:
    id: str
    category: str  # "episodic-avoidance" | "decision-avoidance" | "decision-loop"
    prompt: str  # the user-turn task description given to the model
    approach_outcomes: dict  # approach name -> "success" | "fail", for try_approach tasks
    expected_answer: Optional[str] = None  # for submit_answer-graded tasks (case-insensitive)
    max_attempts: int = 4
    # seed_episode / seed_decision are only written for the CoALA condition
    seed_episode: Optional[dict] = None  # kwargs for episodes.py log
    seed_decision: Optional[dict] = None  # kwargs for decisions.py add
    trap_approach: Optional[str] = None  # the tempting-but-wrong first choice, for repeat-failure scoring


TASKS = [
    Task(
        id="flaky_test_fix",
        category="episodic-avoidance",
        prompt=(
            "A test in our suite fails intermittently (~1 in 5 runs) with no obvious race "
            "condition in the code. You have one action available, try_approach(name), which "
            "actually applies a fix and reports whether the test suite now passes reliably. "
            "Candidates you might consider: 'add_sleep', 'increase_timeout', "
            "'add_retry_with_backoff'. Call try_approach as many times as needed (you have a "
            "budget), then call submit_answer(name) with the fix that worked."
        ),
        approach_outcomes={
            "add_sleep": "fail",
            "increase_timeout": "fail",
            "add_retry_with_backoff": "success",
        },
        expected_answer="add_retry_with_backoff",
        trap_approach="add_sleep",
        seed_episode=dict(
            scope="flaky_test_fix",
            task="fix flaky test by adding a fixed sleep before the assertion",
            outcome="failure",
            detail="Added a 200ms sleep before the flaky assertion. Test still failed "
                   "intermittently under load -- a fixed delay doesn't fix a race, it just "
                   "narrows the window.",
            lesson="Fixed sleeps don't fix flaky tests caused by races; use retry-with-backoff "
                   "on the actual condition instead.",
        ),
    ),
    Task(
        id="service_port_pick",
        category="decision-avoidance",
        prompt=(
            "You need to configure the port for 'service-x' on this host. You have one action "
            "available, try_approach(port), which actually attempts to bind that port and "
            "reports success or failure (already in use). Then call submit_answer(port) with "
            "the port that worked. Common candidates: 8000, 8080, 8005."
        ),
        approach_outcomes={"8000": "fail", "8080": "fail", "8005": "success"},
        expected_answer="8005",
        trap_approach="8080",
        seed_decision=dict(
            scope="service-x", aspect="port", value="8005",
            reason="8000 and 8080 are already bound by other services on this host.",
        ),
    ),
    Task(
        id="gpu_partition_pick",
        category="episodic-avoidance",
        prompt=(
            "You need to run a 2-GPU training job on the cluster. You have one action "
            "available, try_approach(partition), which actually submits a small test job to "
            "that partition and reports whether it completed or got killed. Candidates: "
            "'preempt', 'dgxh', 'ampere'. Then call submit_answer(partition) with one that "
            "completed."
        ),
        approach_outcomes={"preempt": "fail", "dgxh": "success", "ampere": "success"},
        expected_answer="dgxh",  # either dgxh or ampere counts, see grading override below
        trap_approach="preempt",
        seed_episode=dict(
            scope="gpu_partition_pick",
            task="ran a 2-GPU job on the preempt partition targeting an H200 node",
            outcome="failure",
            detail="Job was killed within seconds of starting -- preempt is a scavenger queue "
                   "with zero grace period, and both H200 nodes are owned by other groups.",
            lesson="Never use preempt for a real job that needs to finish; use dgxh or ampere "
                   "instead.",
        ),
    ),
    Task(
        id="deploy_strategy_pick",
        category="decision-loop",
        prompt=(
            "Pick a deployment strategy for a service with these constraints: (1) it must be "
            "trivially reversible if something goes wrong, (2) downtime must be under 1 "
            "minute, (3) the on-call team has never operated this strategy before and there's "
            "no time to train them before the next release. Candidates: 'recreate' (stop then "
            "start, ~2 min downtime), 'rolling-update' (in-place, no rollback until nodes "
            "cycle), 'blue-green' (spin up new version alongside old, and reversible by just "
            "cutting traffic back to it, minimal downtime). This is a judgment call -- no "
            "try_approach tool for this one. Reason about the constraints, then call "
            "submit_answer(name) with your pick."
        ),
        approach_outcomes={},
        expected_answer="blue-green",
    ),
]


def get_task(task_id: str) -> Task:
    for t in TASKS:
        if t.id == task_id:
            return t
    raise KeyError(task_id)
