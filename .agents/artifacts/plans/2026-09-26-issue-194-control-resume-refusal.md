# Control Refuses One Issue's Resume Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** a truthful `absent` or `mismatch` recorded-worktree observation that
leaves a resume unable to proceed refuses only that issue in
`workflow-state control`: it is reported in the issue's summary, and the rest
of the sweep dispatches as usual
([#194](https://github.com/fagenorn/nix-config/issues/194)).

**Architecture:** Task 1 teaches the control-response validator in
`delivery_model/_wire.py` the closed `worktree_fact` rules (per D6, D11). Task 2
adds the nested `worktree_unresumable` check to `command_control`'s resume lane.
When it holds, the lane replans the issue with dispatch withheld and does not
raise (per D1, D4, D5). The lane records the observation, and the summary chain
renders it as one `worktree_fact` requirement (per D3, D13). Task 2 also adds
the orchestrate-issues §5 sentence (per D9, D12).

**Tech stack:** Python 3 stdlib (`subprocess`, `json`, `unittest`), `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-26-issue-194-control-resume-refusal-design.md`, D1–D14.

## Global Constraints

- Scope is exactly the spec's, and its `## Out of scope` list binds. The shared
  policy is not edited (D10). That covers `_apply_one_issue_policy`,
  `DeliveryRuntime.remainder_policy`, `remainder_worktree_requirements` and the
  direct owner. The retry and spawn lanes' raises, the remainder `mismatch`
  raise, and every caller-protocol raise stay whole-sweep errors.
- Code names say "unresumable", never "refused" or "refusal" (D12).
- The action loop, the `refuse` branch, the expiry fallback and `admit` stay
  byte-unchanged.
- No test calls `worktree_unresumable`, `control_summary` or the projection
  directly. Tests drive the CLI (S1) and the `workflow-response` boundary (S3), per D8.
- Tests use temporary repo roots and `HOME`s. Never open
  `.superpowers/workflows/` in the primary checkout.
- The helpers under `~/.agents/bin` are `main`'s build. Every gate runs this
  worktree's `home/common/agent-skills/scripts/*` through the tests.
- No file is created. No `.nix` file changes. `just build` runs once, in the
  final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest <test file> -k <name>`. Summarize the
  output to the `FAIL:`/`ERROR:` ids, the `AssertionError` lines and the
  `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the attribution trailers the
  executing session's rules require: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
  plus any `Claude-Session:` line they name, added as further `-m` paragraphs.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`,
`O` = `home/common/claude-code/skills/orchestrate-issues/SKILL.md`.

## Test seams

- **S1, the `workflow-state` CLI subprocess** on the `claude-code` route with a
  fixture declaration: `LifecycleHarness` in `T/test_workflow_state.py` (T1,
  T2, T4 and the two revisited tests) and `DeliveryAdmissionTest.remainder_sweeps`
  in `T/test_delivery_workflow.py` (T3), per D8, D14.
- **S3, the `workflow-response` boundary.** In-process through
  `validate_delivery_object` for T5 (`T/test_delivery_model.py`). As
  `artifact_budget.py validate-report --boundary workflow-response` bytes for
  every CLI case.

## Delivery estimate and boundaries

These figures are estimates. Nine files change and none is created. The three
producer scripts gain about 45 lines and lose about 6. `S/delivery_model/_wire.py`
gains about 10 and loses 3. `O` gains about 4. The tests gain about 190 lines
and lose about 20. The diff should be about 20 KB, which fits one review
package. Task 2's S3 checks need Task 1's validator, so the tasks run in index
order.

## Task index

Task 1 — The control boundary admits the unresumable worktree fact — `S/delivery_model/_wire.py`, `T/test_delivery_model.py` — full — [task-1.md](2026-09-26-issue-194-control-resume-refusal.tasks/task-1.md)

Task 2 — Control refuses an unresumable resume per issue — `S/workflow-state.py`, `S/workflow_delivery.py`, `S/workflow_delivery_wire.py`, `T/test_workflow_state.py`, `T/test_delivery_workflow.py`, `O`, `T/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-26-issue-194-control-resume-refusal.tasks/task-2.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| Acceptance: an absent suspended resume next to a spawnable issue returns a validating response that spawns the other and reports the first | 2 (T1), on Task 1's validator |
| The same for `mismatch` | 2 (T2) |
| The remainder custody row of the spec's table | 2 (T3) |
| A reap on the refused issue persists (D4) | 2 (T4) |
| The validator's closed rules (D6, D11) | 1 (T5) |
| Existing whole-sweep tests revisited deliberately | 2 (owner-unavailable split, Phase-1 flip, unobserved handoff kept) |
| The dispatcher reports the issue as unable to resume (D9) | 2 |

## Decisions

The spec's `## Decision ledger` is authoritative. The tasks cite D1–D12 from
design. Planning added two rows. **D13** says where the refusal is rendered and
sorted. **D14** places the tests and corrects the spec's reading of the Phase-1
handoff's summary: that summary is contracted.

A planning probe applied both tasks' code and tests to a scratch copy of
`60f3ebf`. At the base, T5 failed in seven subtests. All of them passed after
Task 1. With Task 2's code, T1 to T4 passed. The owner-unavailable candidate
subtests exited 2 with `current control action requires a recorded worktree
observation`. Without a candidate, they exited 0 with the refusal on an
`active` summary and the owner's claim released `owner_unavailable`. The Phase-1
handoff sweep left the ledger bytes unchanged. At Task 1's state, Task 2's new
and revisited tests failed as its member states. With T4's replan removed, T4
failed. Across the six lifecycle, admission and delivery suites, the only
failures under Task 2's code were the two tests Task 2 revisits. The copy's
other errors came from files it lacked (`.agents/project.json`, `.git`).
`just build` was not probed.

## Standards review provenance

- **Reviewer:** Claude fallback (native `reviewer`, isolated, read-only) after a
  Codex `plan-review` run whose JSONL carried no runtime-selection event naming
  model `gpt-6-astra` / effort `xhigh`, so Codex identity was not established.
  The Codex run's one finding was still verified on its merits.
- **Base SHA:** `d8fe6ca2f9123abcdc9bd55f94d79abedd232628`; reviewed plan HEAD `81cd303`.
- **Accepted (5):** Codex S1 — the T1/T2 test gains `max_parallel=1` subtests
  and an empty-`waiting` assertion (per D15); NPR194-02 — Step 2's expected
  count becomes `failures=10`; NPR194-03 — Step 3 rewords the suspended-skip
  comment; NPR194-06 (part) — the spec's Test seams now calls the Phase-1
  summary contracted (per D14). NPR194-04 accepted as a decision, no code (per D16).
- **Rejected (1):** NPR194-01 — the `itertools` use it cites was an in-flight
  edit, replaced by an explicit tuple list before it was committed.
- **Deferred (2):** NPR194-05 — an active-remainder reap-then-absent subcase;
  D4's reap persistence is pinned by T4 and the remainder path's
  `changed=reaped` is existing behaviour. NPR194-06 (rest) — the
  orchestrate-issues "recorded worktree observed" wording stays: "on the issue
  branch" would be wrong for the Phase-0 absent exception.
