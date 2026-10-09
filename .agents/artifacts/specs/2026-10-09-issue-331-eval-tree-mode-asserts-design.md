# Eval asserts that grade the artifact they name, issue 331

## Problem

writing-plans eval 1 fails the same way on main and on the slimmed tree in
`EVAL_TREE` project-skills mode (#324). The agent commits a plan under the
fixture's retained plans directory, yet the run reports "a plan artifact
exists" as FAIL, the decision assert says "decision heading vanished" although
the plan has a `## Decisions` ledger, and the row records 4 of the case's 8
asserts. The measurement, not the skill, is broken, so the eval cannot tell a
good plan from a missing one.

Three defects compose, confirmed by replaying the grading loop on the
retained failing sandbox:

1. **Doubled artifact paths.** The runner exports `SPEC_DIR`/`PLAN_DIR` as
   absolute resolver paths (assert-lib documents this). writing-plans eval 1
   builds `"$REPO/$PLAN_DIR"`, a path that never exists: the has-file assert
   fails, and the task-section and no-placeholder asserts pass vacuously.
   improve-codebase-architecture's evals 2 and 3 carry the same prefix, so
   their negative asserts pass vacuously, and `commits_touch "$WT"
   "$SPEC_DIR"` hands git a path outside the worktree. Only from-issue's cases
   are guarded against the prefix.
2. **A failing assert runs on.** `[ -n "$f" ] || fail "…"; awk … "$f"`:
   `fail` returns 1, the `;` continues, and `awk` with an empty file operand
   reads stdin.
3. **An assert can swallow the rest.** Each per-assert `bash -c` inherits the
   grading loop's stdin, which is the `jq -c '.asserts[]'` stream. The `awk`
   of defect 2 consumes the remaining asserts as input; they are never run or
   reported, and their text produced the "vanished" message.

Separately, ship-issue's **Interim child results** paragraph is a shortened
copy (#296 D8, rewording carried by #317 D2/D7) that no test compares with the
sdd and from-issue copies, so it can drift unseen.

## Solution

1. **Runner (outer guard).** Every per-assert `bash -c` in `run-eval.sh` reads
   `/dev/null` as stdin, so no assert can consume the assert stream or see any
   input the runner did not mean to give it (per D2).
2. **Asserts (inner guard).** writing-plans eval 1 addresses artifact dirs as
   `"$PLAN_DIR"`/`"$SPEC_DIR"` (absolute already) and ends its two
   fail-then-continue chains with an explicit exit, `|| { fail "…"; exit 1; }`,
   so nothing after a failed precondition runs on empty input (per D1, D2).
   improve-codebase-architecture's same-class asserts use the absolute dir for
   `$REPO` and `${X#"$REPO"/}` under `$WT` (per D3). assert-lib helpers and
   their semantics are unchanged.
3. **One canonical interim paragraph.** sdd and from-issue adopt ship-issue's
   shortened text byte for byte; the identity test compares all three copies
   and its ordered anchors follow the shortened text (per D4, D5).
4. **Evidence.** AC1 is measured with `EVAL_TREE=<worktree> just evals
   writing-plans 1` on sonnet at the branch's final head; the runner's
   appended `results.jsonl` row is committed and cited (per D6).

## Decisions

- **Assert path convention** (all skills): an artifact dir under `$REPO` is
  the bare `"$SPEC_DIR"`/`"$PLAN_DIR"`; under any other checkout (`$WT`,
  `$PRE_WT`) it is `"$<checkout>/${X#"$REPO"/}"`. A `<checkout>/$X_DIR`
  concatenation is never valid. This is from-issue's existing convention.
- **Fail-then-exit shape**: in an assert snippet, a `fail` that guards later
  commands is followed by `exit 1` inside a group. A `|| fail "…";` followed
  by another command is invalid; a `fail` as a chain's last step is fine.
  Today only writing-plans eval 1's two asserts violate it.
- **Runner stdin**: `bash -c "source '$ASSERT_LIB'; $snippet" </dev/null`.
  No assert in the corpus reads stdin on purpose, so nothing else changes.
- **Interim paragraph text** is ship-issue's current paragraph (after #317),
  unchanged. Its "follow from-issue's **Writing workers** route" and "this
  skill's handling of a lost child" read correctly in each of the three
  skills, so one text serves all three.
- **Instruction load** falls in sdd's and from-issue's profiles (each copy
  ~150 bytes shorter). No ceiling is raised and no `instruction-budget-raise`
  label is needed; where `just agent-instruction-budget` reports a ceiling
  more than 5% above its measure, that ceiling is lowered with `tighten`
  (#291 D3), and the gate passes unlabelled.

## Test seams

Existing seams only, each with prior art:

- **Assert behaviour** (`test_eval_cases.py`, `run_assert`, the from-issue
  no-artifact precedent): writing-plans eval 1's asserts run on a synthetic
  fixture shaped like production — a git repo with an `origin/main` base,
  absolute `SPEC_DIR`/`PLAN_DIR` under it, and one committed plan with Task
  sections carrying verification lines, an acceptance map covering the
  fixture repository's `issues/001-well-specified.md`, and a `## Decision
  ledger` row. Every assert passes there; the has-file, task-section and
  decision asserts fail when the plan is absent, and the decision assert,
  run with non-empty stdin, fails with its own "no decision section" reason
  and leaves that stdin unread.
- **Assert shape** (`test_eval_cases.py`): the from-issue-only prefix test
  becomes a test over every skill's cases in both roots, forbidding a
  `<checkout>/$SPEC_DIR`/`$PLAN_DIR` concatenation (including in
  `commits_touch`), and a second check over every case forbids `|| fail …;`
  followed by another command.
- **Runner** (`evals/tests/test-run-eval-tree.sh`, the setup-smoke loop): one
  setup-smoke fixture case gains an assert that reads stdin, placed before its
  last assert; the smoke check asserts the row's `total` equals the case's
  assert count and the verdict is PASS. Without `</dev/null` the stdin
  reader swallows the last assert and `total` is short while the row still
  says PASS, which is why the count, not the verdict, is the signal.
- **Interim copies** (`InterimChildResultContractsTest`): `OWNERS` and the
  identity loop include ship-issue; the ordered anchors are re-taken from the
  shortened text. No new test is added.
- **Instruction Budget** gate passes unlabelled.

Verification: `just build` and `just agent-workflow-tests` (which runs the
eval-case and runner tests), foreground with explicit timeouts, plus AC1's
live eval.

## Acceptance handling

- AC1 `[evidence]`: the live run is made in tree mode against the worktree at
  the head whose eval and runner files are the ones that merge. The cited row
  must show `verdict: "PASS"`, `model: "sonnet"`, `failed: 0`, `total: 8`
  and `tree_dirty: false`, with its `tree_rev`. A model-behaviour FAIL with all 8 asserts reported is
  a real measurement, not a harness defect; it is recorded as such and AC1 is
  unmet, not re-graded.
- AC2 `[code]`: met by the extended identity test.

## Out of scope

- Other evals' unrelated failures, and re-running any eval other than
  writing-plans 1.
- assert-lib helper semantics (for example making `fail` exit).
- writing-plans `SKILL.md` and the fixture repository's contract.
- Rewording the interim rule: the change is copy alignment only, every clause
  kept (#296 D8, #317 D2).
- Raising any instruction-load ceiling.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "eval-harness asserts, a runner stdin redirect and a test; the interim paragraph alignment keeps every clause (#296 D8)"}, "concurrency_or_persistence": {"value": "no", "evidence": "no locking or persisted state; results.jsonl gains appended eval rows only"}, "open_design_questions": {"value": "doubt", "evidence": "which interim-paragraph copy becomes canonical (ship-issue's shortened text vs the sdd/from-issue text) is a choice the issue leaves open"}, "criteria_shape": {"value": "hit", "evidence": "AC1 is evidence from a live sonnet eval run, which no deterministic code check verifies"}}, "paths": ["home/common/agent-skills/skills/writing-plans/evals/evals.json", "home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json", "home/common/agent-skills/evals/run-eval.sh", "home/common/agent-skills/evals/tests/test-run-eval-tree.sh", "home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json", "home/common/agent-skills/tests/test_eval_cases.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "home/common/agent-skills/skills/sdd/SKILL.md", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/evals/results/results.jsonl", "home/common/agent-skills/instruction-load.json"]}
Verdict: {"hits":["open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Every skill's asserts use the absolute dir under `$REPO` and `${X#"$REPO"/}` under another checkout; the from-issue-only prefix test is generalized to all cases in both skill roots | assert-lib's documented absolute `SPEC_DIR`/`PLAN_DIR`; from-issue's existing convention and test; root cause 1 | Export repo-relative dirs from the runner: changes the documented contract every from-issue assert already relies on |
| D2 | Fix both sides: the runner's per-assert `bash -c` reads `</dev/null`, and writing-plans' fail-then-continue chains exit; a corpus-wide shape check forbids `|| fail …;` followed by a command | the-bar Defense in depth and Root causes; only writing-plans eval 1 violates the shape today | Runner redirect alone: the assert still runs `awk` on an empty operand and reports the wrong reason; making `fail` exit in assert-lib: changes helper semantics callers use inside `if` (out of scope) |
| D3 | Fix improve-codebase-architecture's same-class asserts in this issue | Generalized D1 test fails on them; Q2 disposition | Defer to a new issue: the generalized test would have to exempt them, keeping vacuous passes |
| D4 | ship-issue's shortened paragraph becomes the canonical text for sdd and from-issue, unchanged | #296 D8 (every clause kept); #317 D7 (ship-issue's copy chosen for byte neutrality); Q1 disposition; lowers instruction load with no label | Grow ship-issue to the long text: raises a ceiling, which needs the user-only `instruction-budget-raise` label |
| D5 | Extend `InterimChildResultContractsTest`'s owners and identity loop to ship-issue and re-take its existing ordered anchors from the shortened text; add no test (partially reverses #296 D8's removal) | AC2 names this test; docs/standards/agent-helpers.md rule 6 forbids only new phrase pins, and AC2 overrides its clause deleting existing pins in a slimming slice; #317 D8 kept the anchors | Delete the ordered-anchor test under rule 6: removes the only content guard on the rule, which the issue does not ask for |
| D6 | AC1 is measured in tree mode on the worktree at its final head and recorded by the runner's committed `results.jsonl` row (with `tree_rev`); no post-merge hold | Tree mode exists to measure an unmerged checkout (#324); branch-tree rows are precedent (from-issue 2/3, ship-issue 5); Q3 disposition | Measure on main after merge with a `needs-verification` hold: the eval files that merge are the ones measured, so a hold adds a cycle for no new information |
| D7 | The behavioural seam is a synthetic production-shaped fixture through `run_assert`, not a replay of the retained sandbox | the-bar Tests that can fail; the from-issue no-artifact test precedent; the retained sandbox is not committed | Commit the failing sandbox as a fixture: large, model-produced and unowned |
| D8 | Grill: the runner smoke grades the row's assert `total` against the fixture's count, and AC1's row must be `tree_dirty: false` | A swallowed tail still yields PASS with `failed: 0` (root cause 3), so the verdict cannot detect it; a dirty-tree row does not name the measured content by `tree_rev` | Grade the smoke on verdict alone: stays green with the bug present (the-bar Tests that can fail) |
| D9 | Plan: writing-plans eval 1's task-section assert grades every plan root under `"$PLAN_DIR"` through assert-lib's index-aware `plan_tasks_verifiable` instead of grepping for `## Task N` headings (amends Solution 2) | Replaying D1's absolute-dir fix on the retained sandbox `eval-writing-plans-1.DRRyFk` still fails this assert: a thin-index plan's members open with `# Task 1:`, which `^##+ Task N` never matches; from-issue case 1 already grades the root this way; all 8 corrected asserts pass on that sandbox | Keep the heading grep with only the dir fixed: AC1 would fail on a correct indexed plan, the measurement defect the issue is about |
| D10 | Plan: `run_assert` mirrors the runner by defaulting stdin to `/dev/null` and takes a keyword `stdin`; "leaves stdin unread" is proven by the shared file offset of a passed file staying 0; the runner smoke's stdin reader is setup-smoke case 3's fourth of five asserts and fails on any input, so a leak shows in both the verdict and `total` | D7, D8; a child reading an inherited fd advances the parent's offset | Feed stdin through `input=` and check output only: cannot tell an unread stdin from one read and ignored |
| D11 | Task 3 updates the three improve-codebase-architecture fragments that `ImproveCodebaseArchitectureSkillContractsTest` pins in `required_shells` in place, adding no pin | Phase-5 review B1: the pinned old shells would fail `test_workflow_skill_contracts.py` once D3 rewrites them; agent-helpers rule 6 forbids only new pins | Delete those fragment pins: widens scope into that test's behavioural checks |
