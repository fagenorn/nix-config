# Delivery Contract Gaps Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** a legacy attempt whose slugless recorded worktree is on a slugged
branch can be resumed or retried (A1), and a remainder whose PR needs a sync of
the integration branch after review reaches `pr_merged` and cleanup without an
out-of-band merge (A2)
([#192](https://github.com/fagenorn/nix-config/issues/192)).

**Architecture:** Gap 1 keeps the contract builder pure. The builder gains a
predicate, `requires_worktree_branch`, and a `worktree_branch` keyword that it
uses only when the worktree name is not an issue branch (Task 1). workflow-state
reads that branch from the live checkout with a read-only `git` probe (Task 2),
and AUTO.md's owner check reads the branch from the contract (Task 3). Gap 2
adds `selected-output/v2`, the **sync selection**, and makes the delivery model
follow one **selection chain** per slot, whose tip is the **current selection**
(Task 4). A new `sync-selection` builder kind seals each link (Task 5), and
ship-issue gains the post-selection sync route in CI-MERGE.md (Task 6).

**Tech stack:** Python 3 stdlib (`subprocess`, `os`, `re`, `unittest`), `git`,
Markdown skill prose, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-27-issue-192-delivery-contract-gaps-design.md`,
D1–D23.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds. #191's
  `progress`/`suspend` replies and the workflow-response result slot in
  `S/artifact_budget.py` are a concurrent PR: never edit that file. There is no
  schema bump, no relocation or ledger write for gap 1, no helper-side git check
  of sync parents, and no move into `agent_tools` (D2, D7, D16).
- The builder and the delivery model do no I/O. `MODEL_INTERFACE_VERSION`,
  `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION`,
  `WORKFLOW_DELIVERY_INTERFACE_VERSION` and state schema 4 stay as they are
  (D16).
- A contract that builds at base builds byte for byte the same, and reads no
  git (D2, T3).
- Every refusal exits 2 with empty stdout and exactly one stderr line,
  `workflow-state: <message>\n`, through the existing `main`. Existing refusal
  texts stay. The new texts are the §2 clauses and D21's texts, exactly as the
  members give them (D4, D19, D21).
- `git` runs by name on `PATH`, read-only, with a 60-second timeout (D3).
- Skill prose never contains the literal substring `Agent(`, adds no dispatch
  marker, and keeps every inline command a single plain command. Shell-example
  and dispatch contract suites stay green unchanged.
- Tests use only the seams below, with temporary roots and `HOME`s. Never open or
  repair `.superpowers/workflows/` in the primary checkout. The helpers under
  `~/.agents/bin` are `main`'s build, so every gate runs this worktree's scripts
  directly or through the tests.
- No task merges `origin/main`. `instruction-load.json` changes only in a task
  whose hot prose breaches a ceiling (D23).
- No file is created except as a task's `Files:` block says, and no `.nix` file
  changes. `just build` runs once, in Task 6's final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <pattern>`.
  Summarize output to the `FAIL:`/`ERROR:` ids and the `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Every commit message ends with the trailer
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`, which
  each member's commit command already carries.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`M` = `S/delivery_model`, `T` = `home/common/agent-skills/tests`,
`K` = `home/common/agent-skills/skills`.

## Test seams

- **Runtime facade:** `T/test_workflow_delivery.py`, a `DeliveryRuntime` loaded
  with `runpy` and a resolver-shaped `resolved_snapshot`. It covers the
  predicate, rule 2 and the refusal composer (D23).
- **Builder CLI:** `BuilderHarness` in `T/test_delivery_workflow.py`, driving
  `S/workflow-state.py` as a subprocess. It carries a new `linked_worktree`
  helper: a real `git worktree add` of the committed synthetic project (D14).
  It covers T1–T3, the help pins and the `sync-selection` refusals.
- **Lifecycle round trips:** `ContractLifecycleTest` (T4, T5) and
  `DeliveryLoopTest` (T7–T9) in the same file, through `control`,
  `direct-owner`, `checkpoint-delivery` and `finish`, with every wire object
  piped through `artifact-budget validate-report`.
- **Model facade:** `DeliveryModelTest` in `T/test_delivery_model.py`, with the
  fixtures of `T/_delivery_model_fixtures.py` plus a new `sync_selection` and
  `at_head`. It covers T10 and D20.
- **Skill pins:** `WorkflowSkillContractsTest` in
  `T/test_workflow_skill_contracts.py` (T6, T11), and `LiveModelTest` in
  `T/test_instruction_load.py` for the ceilings.

## Delivery estimate and boundaries

Estimates from the planning probe. Sixteen files change and none is created.
Product code grows by about 250 lines net across `S/workflow_delivery_build.py`,
`S/workflow_delivery.py`, `S/workflow-state.py` and the three `M/` modules.
Tests grow by about 780 lines across five files. Prose grows by about 90 lines
across CI-MERGE.md, ship-issue SKILL.md and CLAUDE.md, and AUTO.md changes one
sentence at the same byte count. The unified diff should be about 115 KB. That
fits one review package, and it is past ship-issue's small-diff bound, so the
ship review is the full two-axis one.

Tasks run in index order, and each depends on every earlier one. Tasks 1–3 are
gap 1 and can ship alone as A1. Tasks 4–6 are gap 2 (A2). The plan adds about
21 tests: 4 in Task 1, 5 in Task 2, 7 in Task 4, 4 in Task 5 and 1 in Task 6.
Task 3 edits one pin. The main risks are the chain rules leaking into the
single-selection behaviour every existing delivery test pins, and a sync fold
tripping the reducer's intermediate validation. D20 handles the second, and
Task 4's gate runs every model and delivery suite.

## Task index

Task 1 — The builder takes a live branch for a worktree name that is not an issue branch — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `T/test_workflow_delivery.py` — full — [task-1.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-1.md)

Task 2 — workflow-state probes the live checkout, and a legacy attempt resumes and retries — `S/workflow-state.py`, `T/test_delivery_workflow.py`, `CLAUDE.md` — full — [task-2.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-2.md)

Task 3 — AUTO.md's delegated owner takes `expected_branch` from the contract — `K/from-issue/AUTO.md`, `T/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-3.md)

Task 4 — The delivery model follows one selection chain per slot — `M/_objects.py`, `M/_wire.py`, `M/_reconcile.py`, `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py` — full — [task-4.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-4.md)

Task 5 — The `sync-selection` builder kind, and a remainder merges after a sync — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `S/workflow-state.py`, `T/test_delivery_workflow.py`, `CLAUDE.md` — full — [task-5.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-5.md)

Task 6 — ship-issue's post-selection sync route, then the final gate — `K/ship-issue/CI-MERGE.md`, `K/ship-issue/SKILL.md`, `T/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-6.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-6.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| A1: a slugless recorded worktree on a slugged branch gets a contract | 1 (rule 2), 2 (probe, T1–T3) |
| A1: it resumes or retries through a documented route | 2 (T4 control resume, T5 direct retry, help, CLAUDE.md), 3 (AUTO.md) |
| A2: a post-review sync is selected, and publish/open/merge follow the tip | 4 (chain, T10), 5 (`sync-selection`, T7, T9) |
| A2: a merge that landed at a sync run folds, and cleanup completes | 4 (final once merged), 5 (T8) |
| A2: the documented route, and a mergeability refusal is not a denial | 6 (CI-MERGE.md, SKILL.md pointers, T11) |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D18 from design
and grill. Planning added five rows. **D19** gives the kept refusal prefix one
home, the builder's `worktree_pattern_refusal`, and fixes the probe's failure
details. **D20** resets the reducer's facts before its intermediate validation,
because a sync selection un-matches facts observed at the prior head. **D21**
binds the chain to the contract's slot in `match_scope` and the builder, and
names the new refusals. **D22** stops on a Should-fix finding that no amend can
apply. **D23** fixes the seams, leaves `origin/main` to the ship sync, and
raises ceilings per #155 D10.

A planning probe applied every member's code, tests and prose, as written, to a
scratch copy of `70946b0`. Each targeted gate passed, and Task 4's
watch-it-fail run failed as its member says. Three mutants were caught: the
reducer without D20's reset, `implementation_delivered` without the tip rule,
and the `delivery` validator without the final-once-merged rule. The probe also
made two plan fixes. Task 2's `ContractLifecycleTest.attempt` now builds an
attempt at the path it is given, because the launch event records the same
worktree. Task 6's step 6 names the builder by its kind and not by
`build-delivery`, whose callers are pinned. The ship-owner ceiling measured
54480 bytes. `just agent-workflow-tests` gave `Ran 1362 tests` and
`OK (skipped=3)` at base, and `Ran 1383 tests` and `OK (skipped=3)` on the
probed copy. `just build` was not probed.

---
