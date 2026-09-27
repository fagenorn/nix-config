# Task 2: ship-issue Phase 5 routes the correctness axis on `capabilities.review.code`

Decisions: D2 (the routing-error action), D4 (ladder order, and routing before
either axis is dispatched), D5 ("installed" for the skill), D8 (the marker keeps
its id and call line), D9 (the `available` rung points to REVIEW.md and does not
restate it), D10 (the helper's anchors and self-check). Spec §1 and §2, and AC1,
AC2 and AC3. Work from the worktree root. Every shell block starts with
`set -euo pipefail` and these abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests/test_workflow_skill_contracts.py
SHIP=home/common/agent-skills/skills/ship-issue/SKILL.md
```

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## Phase 5 —
  Review the PR`, the paragraph between the conformance and correctness
  dispatch markers, plus one new paragraph after the correctness call line)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): nothing by name. The `available` rung's words "on the terms
  in REVIEW.md" point at the configured-review paragraph that Task 1 scoped.
- Produces (for Task 3), as module-level names in `T`:
  - `CORRECTNESS_ROUTE_OPENER: str`, the exact opener sentence that both callers
    use.
  - `assert_correctness_route_ladder(case, route: str, native_target: str) -> None`,
    which raises `AssertionError` on any broken clause. `case` is a
    `unittest.TestCase` with `assert_ordered`. `route` is raw document text and
    is normalized inside the helper.
  - `SHIP_CORRECTNESS_TARGET`, `SHIP_PRE_FIX_ROUTE` and
    `ship_correctness_route(text=None) -> str`.
  - The rung leads `1. `blocked``, `2. `available`` and `3. `unsupported``, and
    the routing-error phrases "routing error", "discard its outcome", "beside
    the correctness verdict", "rung-3 native dispatch" and "no retry, stop or
    suspension". Task 3's sdd prose must use the same words.

**Invariants:**
- The two dispatch markers in this section and their call lines stay byte for
  byte: `ship-issue-full-conformance-review` and
  `ship-issue-full-correctness-fallback`.
- `diff-review` appears in the ladder only in rung 2. Rung 3's text, up to the
  marker, names neither `diff-review` nor `bindings.commands`.
- The sentence "Axis reports are never merged, and when the correctness axis
  came through `diff-review`, its scope is recorded in the PR body per
  REVIEW.md." and everything after it in Phase 5 stay unchanged.
- The degradation gate (`**Pick the path first.**` up to
  `**Merge-delta check (degraded path).**`) and the skill header stay unchanged.

**Existing pins this task touches** (none needs an edit; all must stay green):
`test_calling_controllers_record_the_correctness_scope` (the scope sentence and
the three Phase-5 dispatch ids),
`test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary`,
`test_review_capability_routes_before_command_lookup`, the owner side of
`assert_configured_code_review_pair`,
`test_shared_source_phase_entries_use_one_resolved_project`,
`test_nested_dispatches_stay_unnamed_and_foreground`, and the model-matrix and
dispatch-contract suites.

- [ ] **Step 1: Write the failing tests**

All edits are in `T`.

1. Directly above `def assert_codex_operation_pair(case, support, review_field, headings):`,
   insert:

```python
# Both correctness-axis callers open their route with this sentence and then
# number the three rungs (issue 195, D4, D5).
CORRECTNESS_ROUTE_OPENER = (
    "Choose the correctness route from the retained `capabilities.review.code` "
    "state before either axis is dispatched, never from how a Codex call failed:"
)
SHIP_CORRECTNESS_TARGET = "id=ship-issue-full-correctness-fallback"
# ship-issue Phase 5's correctness sentence before issue 195, kept only so the
# ladder helper's self-check can put it back.
SHIP_PRE_FIX_ROUTE = (
    "Run it in parallel with the correctness axis via `codex-collaboration`'s "
    "`diff-review`; when that capability is unavailable, use this native "
    "first-pass dispatch instead:"
)


def ship_correctness_route(text=None):
    """ship-issue Phase 5's full-review text, up to its scope-recording sentence."""
    if text is None:
        text = SHIP_ISSUE.read_text(encoding="utf-8")
    start = text.index("**Full two-axis review.**")
    return text[start:text.index("Axis reports are never merged", start)]


def assert_correctness_route_ladder(case, route, native_target):
    """Pin one caller's correctness-axis route (issue 195, D2, D4, D5).

    The route opens with CORRECTNESS_ROUTE_OPENER and numbers the `blocked`,
    `available` and `unsupported` rungs in that order. Only the `available` rung
    names `diff-review`, and it names the capacity rejection after it. The
    `unsupported` rung reaches `native_target` without naming `diff-review` or
    `bindings.commands`. The routing-error action follows the ladder, and no
    skill-presence wording survives.
    """
    route = normalized(route)
    case.assert_ordered(
        route, CORRECTNESS_ROUTE_OPENER, "1. `blocked`", "2. `available`",
        "3. `unsupported`", native_target, "routing error", "discard its outcome",
        "beside the correctness verdict", "rung-3 native dispatch",
        "no retry, stop or suspension",
    )
    available_at = route.index("2. `available`")
    unsupported_at = route.index("3. `unsupported`")
    available = route[available_at:unsupported_at]
    unsupported = route[unsupported_at:route.index(native_target, unsupported_at)]
    case.assert_ordered(available, "`diff-review`", "capacity rejection")
    for absent in ("diff-review", "bindings.commands"):
        case.assertNotIn(absent, unsupported)
    case.assertEqual(route.count("diff-review"), available.count("diff-review"))
    case.assertNotIn("unavailable", route.lower())
    case.assertNotIn("skill is available", route)


```

2. In `ProjectPolicySurfaceTest`, directly above
   `def test_context_map_selection_uses_only_authored_order(self):`, add:

```python
    def test_ship_correctness_route_is_the_capability_ladder(self):
        route = ship_correctness_route()
        assert_correctness_route_ladder(self, route, SHIP_CORRECTNESS_TARGET)
        route = normalized(route)
        self.assertIn(
            "This is the only rung that reaches Codex and the only one where a "
            "capacity rejection binds, on the terms in REVIEW.md.", route)
        self.assertIn(
            "record the routing error in the PR body beside the correctness "
            "verdict", route)

    def test_correctness_route_ladder_rejects_each_broken_route(self):
        # The helper is not vacuous: putting the pre-fix route back, or breaking
        # one clause of the ladder, makes it raise (issue 195, D3).
        ship = SHIP_ISSUE.read_text(encoding="utf-8")
        ladder = ship[
            ship.index("Run it in parallel with the correctness axis"):
            ship.index("<!-- agent-dispatch: id=ship-issue-full-correctness-fallback")
        ]
        mutants = {
            "pre-fix route": (ladder, SHIP_PRE_FIX_ROUTE + "\n\n"),
            "diff-review in rung 3": (
                "3. `unsupported`, or", "3. `unsupported` via `diff-review`, or"),
            "capacity rule leaves rung 2": (
                "a capacity rejection binds", "a refusal binds"),
            "routing-error outcome kept": (
                "discard its outcome", "keep its outcome"),
        }
        for name, (old, new) in mutants.items():
            with self.subTest(mutant=name):
                self.assertTrue(old in ship, f"mutant anchor missing: {old!r}")
                with self.assertRaises(AssertionError):
                    assert_correctness_route_ladder(
                        self, ship_correctness_route(ship.replace(old, new)),
                        SHIP_CORRECTNESS_TARGET)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
PYTHONPATH=python python3 -m unittest $T -k correctness_route 2>&1 \
  | grep -E '^(FAIL|ERROR):|^AssertionError|^Ran |^OK|^FAILED' | cut -c1-200
```

Expected: `Ran 2 tests` and `FAILED (failures=4)`. The ladder test fails on the
missing `CORRECTNESS_ROUTE_OPENER`. Three mutant subtests fail with
`mutant anchor missing` (`3. `unsupported`, or`, `a capacity rejection binds`
and `discard its outcome`). The `pre-fix route` subtest already passes, because
the pre-fix text is what is there now.

- [ ] **Step 3: Edit Phase 5**

In `$SHIP`, replace exactly this block (it runs from the line after the
conformance call line to the start of the scope sentence):

```text
Run it in parallel with the correctness axis via `codex-collaboration`'s `diff-review`; when that capability is unavailable, use this native first-pass dispatch instead:

<!-- agent-dispatch: id=ship-issue-full-correctness-fallback role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full correctness fallback review.

Axis reports are never merged,
```

with this block. The marker and call lines are copied unchanged, the lines are
not hard-wrapped (this section does not wrap), and the numbered list starts at
column 0:

```text
Run it in parallel with the correctness axis. Choose the correctness route from the retained `capabilities.review.code` state before either axis is dispatched, never from how a Codex call failed:

1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
2. `available`, with `codex-collaboration` installed → its `diff-review` operation. This is the only rung that reaches Codex and the only one where a capacity rejection binds, on the terms in REVIEW.md. A completed non-capacity failure takes that skill's one native fallback.
3. `unsupported`, or `available` without `codex-collaboration` installed → this native first-pass dispatch, directly; `codex-collaboration` is never invoked on this rung:

<!-- agent-dispatch: id=ship-issue-full-correctness-fallback role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the full correctness fallback review.

A Codex call made under `unsupported` anyway is a routing error: discard its outcome — verdict, refusal or failure — record the routing error in the PR body beside the correctness verdict, and run the rung-3 native dispatch, with no retry, stop or suspension.

Axis reports are never merged,
```

The rest of the "Axis reports are never merged, …" paragraph is unchanged. Under
`unsupported` the marker id still says "fallback", but it is the documented
primary route there. Do not rename it (D8).

- [ ] **Step 4: Verify**

```bash
if LC_ALL=C tr -s '[:space:]' ' ' < $SHIP | grep -qF 'when that capability is unavailable'; then exit 1; fi
if git diff HEAD -- $SHIP | grep -qE '^[-+](<!-- agent-dispatch|Agent\()'; then exit 1; fi
PYTHONPATH=python python3 -m unittest $T -k correctness_route 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T home/common/agent-skills/tests/test_dispatch_contracts.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
git diff --numstat HEAD -- home/common/agent-skills/skills
```

Expected: both prohibitions pass. Then `Ran 2 tests` and `OK`. Then the four
suites give `Ran 220 tests` and `OK (skipped=3)`, which is Task 1's 218 plus 2.
The numstat shows only `home/common/agent-skills/skills/ship-issue/SKILL.md`,
with 7 lines added and 1 deleted.

- [ ] **Step 5: Commit**

```bash
git add $T $SHIP
git commit -m "fix(ship-issue): route the correctness axis on review.code (#195)" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
