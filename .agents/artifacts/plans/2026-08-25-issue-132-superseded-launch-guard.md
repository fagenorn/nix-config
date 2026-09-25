# Superseded-launch forge-write guard — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A ship owner re-validates that its launch identity is still the launch
the ledger entitles immediately before every forge write it makes up to and
including the merge, and refuses the write otherwise.

**Architecture:** One new read-only `workflow-state check-launch` verb answers
whether an `issue:attempt:launch` identity is the current launch of the latest
attempt for its issue (no clock, no lock, creates nothing). The from-issue ship
handoff carries that identity so the query is answerable, and ship-issue's prose
places the query immediately before the Phase-4 push, the Phase-4 PR create,
every Phase-5 fix push and the Phase-7 merge, routing any negative or failed
answer to a stop that writes nothing anywhere. Separately, ship-issue's Phase-6
tip check moves from live local `HEAD` to the reviewed `HEAD_SHA`, because two
attempts of one issue share one checkout.

**Spec (the contract):** `.claude/specs/2026-08-25-issue-132-superseded-launch-guard-design.md`.
Read it before any task. Its `## Decision ledger` (D1–D18) is the single home for
rationale; this plan cites rows by ID and never restates them.

**Issue:** https://github.com/fagenorn/nix-config/issues/132

**Tech stack:** Python 3 standard library only (`argparse`, `json`, `re`,
`pathlib`, `unittest`); Markdown skill prose; Nix flake (`just build`).

## Global Constraints

- Python: standard library only; no new third-party dependency, no new file.
- `workflow-state check-launch` writes nothing: no `transact`, no
  `workflow_paths`, no lock, no `--now` (per D4).
- The `reason` value set is closed and 7-valued with the spec's exact precedence
  (per D1, D5). Exit 0 for every answer; exit 2 only for an unreadable ledger or
  a malformed argument (per D3).
- Skill prose is hard-wrapped at ~80 columns. Contract assertions over a wrapped
  sentence must compare against `normalized(text)` (the module helper that
  collapses whitespace runs to one space).
- Prose a task gives inside a `>` block is the **text to insert**, quoted only
  for readability. Insert it as ordinary prose or an ordinary list item — never
  as a Markdown blockquote, and never with the `>` markers.
- The literal `gh pr merge` must not appear in any line this plan adds to
  `ship-issue/SKILL.md` — `test_ship_issue_merge_is_bound_to_the_resolved_repository`
  `assertEqual`s the complete list of lines containing it. Anchor merge ordering
  on `--delete-branch` instead.
- The literal `workflow-state suspend` must not appear in ship-issue's
  `## Launch guard` section (per D8). `workflow-state check-launch` does not
  contain the retired-verb substring `workflow-state launch`; keep it that way.
- Commits are SSH-signed. **Never** pass `-c commit.gpgsign=false` or
  `--no-gpg-sign`; surface signing failures. Every commit carries
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Out of scope, in every task: issue #133 (`last_progress_at` must not become an
  expiry input), issue #125 (epoch-fenced leases), the Claude Code permission
  guard's command grammar, and `control`'s `CONTROL_DISPATCH_KINDS`.

## Test seams

Existing seams only; no new ones (spec, *Test seams*).

- **Seam 1 — the `workflow-state` CLI via subprocess.**
  `home/common/agent-skills/tests/test_workflow_state.py`,
  `WorkflowStateLifecycleTest`, through `run_cli(...)`. The module is never
  imported.
- **Seam 2 — skill prose.**
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
  `WorkflowSkillContractsTest`, through its `section(...)`, `assert_ordered(...)`
  and `normalized(...)` helpers.
- **Seam 3 — the report validator CLI.**
  `home/common/agent-skills/tests/test_artifact_budget.py`,
  `ArtifactBudgetCliTest`, through `run_validate(...)`.
- **Seam 4 — the built Claude settings.** `tests/test_claude_permission_guard.py`.
  Untouched: a gate here, never a target.
- `CLAUDE.md` has no content seam and gets none (per D18); its acceptance
  criterion is gated by `grep` in Task 6.

## Task index

Task 1 — The read-only `check-launch` query — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-1.md)
Task 2 — Launch identity in the ship handoff — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-2.md)
Task 3 — The launch guard before every pre-merge forge write — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-3.md)
Task 4 — Phase-6 tip check against the reviewed `HEAD_SHA` — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-4.md)
Task 5 — from-issue's pre-`finish` guard — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-5.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-5.md)
Task 6 — Shared-bucket and wall-clock-expiry documentation, then the whole-change gate — `CLAUDE.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-6.md](2026-08-25-issue-132-superseded-launch-guard.tasks/task-6.md)

Lane notes: every task is `full`. Tasks 1–5 are lifecycle, concurrency or
public-contract work outright. Task 6 is `full` too, despite being two
documentation sentences: the `low-risk` lane excludes anything touching
lifecycle or public contracts, and Task 6 rewrites from-issue's expiry
instructions — semantic documentation about the lifecycle, pinned by a contract
test. A change being small is not what qualifies a lane. Nothing here is
`mechanical`; even the action-id extraction in Task 1 ships a new public verb
alongside it.

## Acceptance-criteria coverage

| AC | Discharged by |
|----|---------------|
| AC1 — read-only query, unknown coordinates answer "not current" | Task 1 |
| AC2 — the query before push / PR create / merge, refusal path | Task 3 |
| AC3 — handoff carries launch identity; ship owner still writes no ledger | Task 2 (handoff), Task 3 (never-writes sentence) |
| AC4 — tip check against reviewed `HEAD_SHA`, escalate as unreviewed commits | Task 4 |
| AC5 — both supersession shapes in `test_workflow_state.py` | Task 1 |
| AC6 — `test_workflow_skill_contracts.py` pins the guard, the refusal route and the handoff identity | Task 2 (handoff), Task 3 (guard + refusal), Task 4, Task 5, Task 6 |
| AC7 — `CLAUDE.md` shared bucket; skill prose says expiry is wall-clock | Task 6 |
| AC8 — permission-guard suite green, `just build` succeeds | Task 6 (whole-change gate) |

## Decisions

Spec rows D1–D15 are the design record; cite them, never restate them. Planning
appended three rows to the **spec's** ledger:

- **D16** — `command_control`'s dispatch-action `id` is routed through the same
  extracted render helper (Task 1).
- **D17** — the Phase-5 fix-push guard and the reviewed-`HEAD_SHA` re-fix land in
  `ship-issue/REVIEW.md`, one file beyond the spec's Files-touched list
  (Tasks 3, 4).
- **D18** — falsifiable anchoring: no new `CLAUDE.md` seam, and every new
  contract assertion anchors where it is false at base (Tasks 2, 6).

The Phase-5 standards review appended three more:

- **D19** — Task 4 also realigns `ship-issue/evals/evals.json` with the new
  tip-check prose, pinned by a contract test (Task 4).
- **D20** — the pre-`finish` guard is installed in both terminal routes, the
  direct-autonomous bookkeeper included (Task 5).
- **D21** — red-phase selectors, whole-answer assertions, and Task 6's lane
  (Tasks 1, 2, 3, 6).

## Standards review provenance

- **Reviewer:** Codex (isolated, read-only runtime; fresh `CODEX_HOME`, approval
  policy `never`, sandbox `read-only`), job `reviewer-mt8fxhh2-30ltjp`.
- **Base SHA:** `ec31bcd47cc02a631b564786b620857cd5a92aab`; plan reviewed at
  `362e547af6bed2b68830d2758f2965da5d7f6ffc`.
- **Focus:** none configured (`codex.planReview.focus` unset).
- **Fallback:** none — the Codex route completed; no native fallback was used.
- **Dispositions:** 5 accepted, 0 rejected, 0 deferred. Both Blocking findings
  (B-132-01 eval realignment, B-132-02 the direct-autonomous bookkeeper) and all
  three Should-fix findings (S-132-01 red-phase selectors, S-132-02 Task 6's
  lane, S-132-03 whole-answer assertions) were verified against the live
  worktree and applied. The single Discussion item endorsed spec row D8's
  no-suspension departure after checking it against `command_suspend` and
  `resume_attempt`; D8 is retained unchanged.

## Verification

Whole-change gates, all run from the worktree root:

```sh
just build
just agent-workflow-tests
just show-claude-settings > "$TMPDIR/claude-settings.json" \
  && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" \
     python3 tests/test_claude_permission_guard.py -v
```

`just agent-workflow-tests` covers `test_workflow_state.py`,
`test_workflow_skill_contracts.py` and `test_artifact_budget.py` — the three
suites this change touches. The permission-guard suite is not in that recipe and
must be run separately against the built settings artifact; it must stay green
untouched (Seam 4). Task 6 runs all three; every earlier task runs the single
suite it moves.
