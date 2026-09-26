# Control Queues Only Dispatches Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state control` no longer raises `KeyError: 'idle'` or
`KeyError: 'terminal'` when an issue's current custody is a live or stall-bound
delivery remainder, and it never lists a live remainder in `admission.waiting`
([#190](https://github.com/fagenorn/nix-config/issues/190)).

**Architecture:** Task 1 adds a nested `admit` helper inside `command_control`'s
inner `control(state)`. It becomes the only place where a planned result is
queued into `proposal_order` and charged a `max_parallel` unit and a role-set
claim. It queues only `CONTROL_DISPATCH_KINDS`, and all five dispatch lanes call
it (per D3, D8). Task 2 changes `DeliveryRuntime.remainder_policy` in
`workflow_delivery.py` so that it labels a live remainder `desired: idle` and a
stall-bound failure `desired: terminal`. Neither then enters the resume lane
(per D2).

**Tech stack:** Python 3 stdlib (`subprocess`, `json`, `unittest`), `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-26-issue-190-control-idle-remainder-design.md`, D1–D11.

## Global Constraints

- Scope is exactly the spec's, and its `## Out of scope` list binds. That
  excludes the `expired` delta's attribution, `human_directed` gating of
  remainders, claims for finish-minted remainders, re-emitted recover semantics,
  the move into `agent_tools`, and the action loop's error type.
- `operation`, `changed`, the reaper and the stall bound do not change (D2).
  Remainder operations, ledger transitions and direct-owner behaviour do not
  change (D1).
- The action loop's closed `{spawn, resume, retry}` delta map is not edited.
  The expiry fallback's `issue not in planned` guard stays (D3, D6).
- Each lane keeps its own pre-checks and its own `observe` refusal. `refuse` is
  still queued without a charge, outside `admit` (D3).
- No test calls `admit` or `remainder_policy` directly. T1–T4 drive the CLI
  (D6).
- Tests use temporary repo roots and `HOME`s from `make_home()`. Never open
  `.superpowers/workflows/` in the primary checkout.
- The helpers under `~/.agents/bin` are `main`'s build. Every gate runs this
  worktree's `home/common/agent-skills/scripts/*` through the tests.
- No file is created and no `.nix` or documentation file changes (D11).
  `just build` runs once, in the final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k <name>`.
  Summarize the output to the `FAIL:`/`ERROR:` ids, the `KeyError`/`AssertionError`
  lines and the `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the trailer
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`.

## Test seams

- **S1, the `workflow-state` CLI subprocess.** It runs `init-run`, `control`,
  `finish` and `checkpoint-delivery` with `HOME` at a `make_home()` fixture, on
  the `claude-code` route, in `DeliveryAdmissionTest` of
  `T/test_delivery_workflow.py`. It covers T1–T4 (D6, D10).
- **S3, the `workflow-response` boundary**
  (`artifact_budget.py validate-report --boundary workflow-response`). It covers
  T1 only (D6).

## Delivery estimate and boundaries

These figures are estimates. Three files change and none is created.
`S/workflow-state.py` gains about 17 lines and loses about 22.
`S/workflow_delivery.py` gains about 7 and loses 3. `T/test_delivery_workflow.py`
gains about 140. The diff should be about 12 KB, which fits one review package.
Task 2 consumes Task 1's test fixture, so the tasks run in index order (D9).

## Task index

Task 1 — One admission step for every dispatch lane — `S/workflow-state.py`, `T/test_delivery_workflow.py` — full — [task-1.md](2026-09-26-issue-190-control-idle-remainder.tasks/task-1.md)

Task 2 — Truthful remainder classification — `S/workflow_delivery.py`, `T/test_delivery_workflow.py` — full — [task-2.md](2026-09-26-issue-190-control-idle-remainder.tasks/task-2.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: an active remainder with one free slot returns a valid response instead of raising | 1 (T1; T3 for the stall-bound shape, D4) |
| AC1: a suspended remainder with one free slot returns a valid response | 1 (T4, baseline) |
| AC2: `main`'s helper no longer crashes on the reproduction | 1 (T1, T3, per D7); 2 (final gate) |
| D5: a live remainder is not in `admission.waiting` | 2 (T2) |

## Decisions

The spec's `## Decision ledger` is authoritative. The tasks cite D1–D8 from
design. Planning added three rows. **D9** orders the two halves so that each
task starts from a red test. **D10** fixes the shared CLI fixture and how T1
copies the ledger. **D11** records that no documentation changes.

A planning probe applied both tasks' tests and code, exactly as written, to a
scratch copy of `2f2093f`. At the base, T1 failed on `KeyError: 'idle'` and T3
on `KeyError: 'terminal'`, while T4 passed. After Task 1, T1, T3, T4 and the
three contract tests passed, and T2 then failed on
`Lists differ: [151] != []`. After Task 2 all four passed. The five
lifecycle, admission and delivery suites ran 230 tests, OK, and
`just agent-workflow-tests` ran 1309 tests. Its only two errors were
`git ls-files` calls, which a copy without `.git` cannot answer. `just build`
was not probed, because no `.nix` file and no tracked-file set changes.
