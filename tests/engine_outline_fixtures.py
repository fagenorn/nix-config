"""The planner, design-review and implementer replies the stubbed `deliver --plan outline` scenarios script."""

from __future__ import annotations

import copy

SLICE_ONE = {"n": 1, "change": "Add greet() to the fixture module", "files": ["fixture/greet.py"],
             "test": "checks/check_greet.py", "assertion": "greet() returns the greeting"}
SLICE_TWO = {"n": 2, "change": "SECOND SLICE CHANGE", "files": ["fixture/farewell.py"],
             "test": "checks/check_greet.py", "assertion": "farewell() returns the farewell"}
CRITERION = {"id": "AC1", "text": "greet() returns the greeting", "kind": "code", "slice": 1}
OUTLINE = {"status": "planned", "approach": "Add greet() to the fixture module.",
           "rejected": "Rewrite the module around a class.", "slices": [SLICE_ONE], "criteria": [CRITERION],
           "risks": [], "questions": []}
TWO_SLICES = dict(OUTLINE, slices=[SLICE_ONE, SLICE_TWO])
UNMAPPED = dict(OUTLINE, criteria=[dict(CRITERION, slice=9)])
UNPROVEN = dict(OUTLINE, slices=[dict(SLICE_ONE, test="")])

FINDING = {"severity": "important", "file": "slice 1", "failing_input": "the proving test passes without the change",
           "summary": "slice 1's test cannot fail", "kind": "weak-test"}
DESIGN_PASS = {"verdict": "pass", "findings": []}
DESIGN_FINDINGS = {"verdict": "findings", "findings": [FINDING]}

READS = ["<worktree>/fixture/greet.py", "<worktree>/README.md"]
TWO_CRITERIA_BODY = ("Add a greet() function to the fixture module, next to `secrets/x.yaml`.\n\n"
                     "## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n"
                     "- [ ] [code] farewell() returns the farewell\n")


def with_reads(entry: dict, worktree) -> dict:
    """`entry` (a reply, or an entry of the stub's `{"reply": ...}` form) with the planner reads of `READS` in `worktree`."""
    shaped = copy.deepcopy(entry) if "reply" in entry else {"reply": copy.deepcopy(entry)}
    shaped["reads"] = [path.replace("<worktree>", str(worktree)) for path in READS]
    return shaped
