#!/usr/bin/env python3
"""Interactive bounded view over the issue #79 adoption-plan prototype."""

from __future__ import annotations

import argparse
import json
from typing import Any

from inspect_repo import inspect
from model import VIEW_KEYS, build_plan, reduce_view


BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def line(label: str, value: Any) -> str:
    return f"{BOLD}{label}:{RESET} {value}"


def render_summary(plan: dict[str, Any]) -> list[str]:
    gap = plan["decisions"]["gap_verdict"]
    return [
        line("Question", "Does real nix-config inspection reveal a missing core contract surface?"),
        line("Outcome", f"{plan['plan']['mode']} / {plan['plan']['state']}"),
        line("Base", plan["plan"]["base_revision"][:12]),
        line("Evidence groups", len(plan["evidence"])),
        line("Material questions", len(plan["decisions"]["open"])),
        line("Readiness blockers", len(plan["plan"]["blockers"])),
        line("Prototype answer", gap["prototype_answer"]),
        "",
        f"{DIM}The prototype answer is provisional until the human review accepts or revises it.{RESET}",
    ]


def render_project(plan: dict[str, Any]) -> list[str]:
    return json.dumps(plan["plan"]["proposed_project_json"], indent=2, sort_keys=True).splitlines()


def render_classifications(plan: dict[str, Any]) -> list[str]:
    rows = []
    for item in plan["evidence"]:
        action = item["action"] or "observe-only"
        rows.append(f"{BOLD}{item['path']}{RESET} [{item['provenance']}; {item['count']}] → {action}")
        rows.append(f"  {DIM}{item['lifecycle_class']}: {item['note']}{RESET}")
    return rows


def render_questions(plan: dict[str, Any]) -> list[str]:
    rows = [line("Open material frontier", len(plan["decisions"]["open"]))]
    if not plan["decisions"]["open"]:
        rows.append("None. Observable facts and strong authored evidence fill the plan; exact-plan approval ratifies recommendations.")
    rows.append("")
    rows.append(f"{BOLD}Recommendations awaiting whole-plan approval{RESET}")
    for decision in plan["decisions"]["recommended"]:
        rows.append(f"- {decision['id']}: {decision['value']}")
        rows.append(f"  {DIM}{decision['basis']}{RESET}")
    rows.append("")
    rows.append(f"{BOLD}Non-question blockers{RESET}")
    for blocker in plan["plan"]["blockers"]:
        rows.append(f"- {blocker['id']} → {blocker['repair_id']}")
    return rows


def render_operations(plan: dict[str, Any]) -> list[str]:
    rows = []
    for index, operation in enumerate(plan["changes"], 1):
        rows.append(f"{BOLD}{index}. {operation['type']}{RESET} [{operation['approval_class']}]")
        rows.append(f"  {DIM}{', '.join(operation['sources']) or '(no source)'} → {', '.join(operation['targets'])}{RESET}")
    return rows


def render_verification(plan: dict[str, Any]) -> list[str]:
    rows = [line("Purpose", plan["verification"]["purpose"]), ""]
    for check in plan["verification"]["checks"]:
        detail = check.get("repair_id") or check.get("blocked_by") or ""
        rows.append(f"{BOLD}{check['status']:<10}{RESET} {check['id']} {DIM}{detail}{RESET}")
    return rows


def render_handoff(plan: dict[str, Any]) -> list[str]:
    handoff = plan["handoff"]
    rows = [line("State", handoff["state"]), line("Run", handoff["next_command"]), ""]
    rows.append(f"{BOLD}Human review{RESET}")
    rows.extend(f"- {question}" for question in handoff["review_questions"])
    return rows


def render_gaps(plan: dict[str, Any]) -> list[str]:
    gap = plan["decisions"]["gap_verdict"]
    rows = [
        line("Missing bindings", len(gap["missing_bindings"])),
        line("Missing capabilities", len(gap["missing_capabilities"])),
        line("Missing artifact classes", len(gap["missing_artifact_classes"])),
        line("Prototype answer", gap["prototype_answer"]),
        line("Human verdict", gap["human_verdict"]),
        "",
        f"{BOLD}Pressure-tested edges already covered{RESET}",
    ]
    rows.extend(f"- {item}" for item in gap["covered_edge_cases"])
    return rows


RENDERERS = {
    "summary": render_summary,
    "project": render_project,
    "classifications": render_classifications,
    "questions": render_questions,
    "operations": render_operations,
    "verification": render_verification,
    "handoff": render_handoff,
    "gaps": render_gaps,
}


def render(plan: dict[str, Any], view: str) -> None:
    print("\033[2J\033[H", end="")
    print(f"{BOLD}PROTOTYPE — nix-config adoption dry run{RESET}  {DIM}[{view}]{RESET}")
    print("=" * 72)
    print("\n".join(RENDERERS[view](plan)))
    print("\n" + "-" * 72)
    shortcuts = "  ".join(f"[{key}] {name}" for key, name in VIEW_KEYS.items())
    print(f"{DIM}{shortcuts}  [x] exit{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--dump-json", action="store_true")
    args = parser.parse_args()

    plan = build_plan(inspect(args.repo))
    if args.dump_json:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    view = "summary"
    done = False
    while not done:
        render(plan, view)
        try:
            key = input("view> ").strip().lower()[:1]
        except (EOFError, KeyboardInterrupt):
            print()
            break
        view, done = reduce_view(view, key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
