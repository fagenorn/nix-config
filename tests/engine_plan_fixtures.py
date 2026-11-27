"""The planner and plan-reviewer replies the stubbed `deliver` scenarios script for a planned issue."""

from __future__ import annotations

PLAN_TEXT = "PLAN: task 1 adds greet() to fixture/greet.py; its proving test is checks/check_greet.py."
REVISED_PLAN_TEXT = "REVISED PLAN: task 1 adds greet() and names checks/check_greet.py as its proving test."
NOHUP_PLAN_TEXT = "PLAN: task 1 adds greet(); the doc says never start a run with nohup."


def plan_file(text: str) -> dict:
    """The plan.md a planner session leaves in the worktree: the engine posts the plan from the files."""
    return {"path": ".superpowers/plans/issue-41/plan.md", "text": text}


# the stubbed planner leaves plan.md only, so the reply declares no task file: the engine reads exactly those declared
PLANNED = {"status": "planned", "evidence": PLAN_TEXT, "notes": "", "declines": [], "tasks": [], "task_numbers": []}
BLOCKED = {"status": "blocked", "evidence": "", "notes": "Which of the two options?", "declines": [], "tasks": [],
           "task_numbers": []}
PLANNED_ENTRY = {"reply": PLANNED, "leave": plan_file(PLAN_TEXT)}
REVISED = dict(PLANNED, evidence=REVISED_PLAN_TEXT)
REVISED_ENTRY = {"reply": REVISED, "leave": plan_file(REVISED_PLAN_TEXT)}
PLAN_FINDING = {"severity": "important", "file": "task-1.md", "failing_input": "the proving test is not named",
                "summary": "task 1 names no proving test", "kind": "plan-step-not-executable"}
PLAN_PASS = {"verdict": "pass", "findings": []}
PLAN_FINDINGS = {"verdict": "findings", "findings": [PLAN_FINDING]}
PLAN_PASS_BLOCKED = {"verdict": "pass", "findings": [PLAN_FINDING]}
PLANNED_REPLIES = {"plan": PLANNED_ENTRY, "plan-review": PLAN_PASS}
REVISED_REPLIES = {"plan": PLANNED_ENTRY, "plan-review": PLAN_FINDINGS, "plan-revise": REVISED_ENTRY,
                   "plan-rereview": PLAN_PASS}
REFUSED_REPLIES = {**REVISED_REPLIES, "plan-rereview": PLAN_FINDINGS}
