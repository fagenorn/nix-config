# Delivery Contract Gaps Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** a legacy attempt whose slugless recorded worktree is on a slugged
branch can be resumed or retried (A1), and a remainder whose PR needs a sync of
the integration branch after review reaches `pr_merged` and cleanup without an
out-of-band merge (A2)
([#192](https://github.com/fagenorn/nix-config/issues/192)).

**Architecture:** Gap 1 keeps the builder pure: it takes a live branch through
a `worktree_branch` keyword only when the worktree name is not an issue branch
(Task 1), workflow-state reads that branch with a read-only `git` probe (Task
2), and AUTO.md's owner check reads branch and path from the contract (Task 3).
Gap 2 adds the **sync selection** (`selected-output/v2`) and one **selection
chain** per slot, whose tip is the **current selection** (Task 4).
`sync-selection` seals each link, and a read-only `current-selection` kind
serves the installing ledger's current selection (Task 5). ship-issue gains the
post-selection sync route in CI-MERGE.md (Task 6).

**Tech stack:** Python 3 stdlib (`subprocess`, `os`, `re`, `unittest`), `git`,
Markdown skill prose, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-27-issue-192-delivery-contract-gaps-design.md`,
D1–D28.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds. #191's
  `progress`/`suspend` replies and the workflow-response result slot in
  `S/artifact_budget.py` are a concurrent PR: never edit that file, and change
  no `workflow-response` shape (`delivery_remainder`, checkpoint replies) (D24).
  There is no schema bump, no relocation or ledger write for gap 1, no
  helper-side git check of sync parents, and no move into `agent_tools` (D2,
  D7, D16).
- The builder and the delivery model do no I/O. `build-delivery` reads a ledger
  only for a non-re-deriving contract's installed intent and for
  `--kind current-selection`, and never locks or writes (D24, D25).
  `MODEL_INTERFACE_VERSION`,
  `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION`,
  `WORKFLOW_DELIVERY_INTERFACE_VERSION` and state schema 4 stay as they are
  (D16).
- A contract that builds at base builds byte for byte the same, and reads no
  git (D2, T3).
- Every refusal exits 2 with empty stdout and exactly one stderr line,
  `workflow-state: <message>\n`, through the existing `main`. Existing refusal
  texts stay. The new texts are the §2 clauses and D21's and D25's, exactly as
  the members give them (D4, D19, D21, D25).
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
- Commits are conventional and SSH-signed; never disable signing, and surface a
  signing failure. Each member's commit command carries the trailer
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`M` = `S/delivery_model`, `T` = `home/common/agent-skills/tests`,
`K` = `home/common/agent-skills/skills`.

## Test seams

- **Runtime facade:** `T/test_workflow_delivery.py`, a `DeliveryRuntime` loaded
  with `runpy` and a resolver-shaped `resolved_snapshot`: the predicate, rule 2,
  the refusal composer (D23) and the installed-delivery re-check (D25).
- **Builder CLI:** `BuilderHarness` in `T/test_delivery_workflow.py`, driving
  `S/workflow-state.py` as a subprocess. It carries a new `linked_worktree`
  helper: a real `git worktree add` of the committed synthetic project (D14).
  It covers T1–T3, the help pins and the `sync-selection` refusals.
- **Lifecycle round trips:** `ContractLifecycleTest` (T4, T5) and
  `DeliveryLoopTest` (T7–T9, T12) in the same file, through `control`,
  `direct-owner`, `checkpoint-delivery` and `finish`, with every wire object
  piped through `artifact-budget validate-report`.
- **Model facade:** `DeliveryModelTest` in `T/test_delivery_model.py`, with the
  fixtures of `T/_delivery_model_fixtures.py` plus a new `sync_selection` and
  `at_head`. It covers T10, D20 and `current_selection`.
- **Skill pins:** `WorkflowSkillContractsTest` in
  `T/test_workflow_skill_contracts.py` (T6, T11), and `LiveModelTest` in
  `T/test_instruction_load.py` for the ceilings.

## Delivery estimate and boundaries

Estimates from the planning probes. Seventeen files change and none is
created. Product code grows by about 330 lines net, tests by about 870 lines
across five files, and prose by about 110 lines. The unified diff should be
about 130 KB: one review package, past ship-issue's small-diff bound, so the
ship review is the full two-axis one.

Tasks run in index order, and each depends on every earlier one. Tasks 1–3 are
gap 1 and can ship alone as A1. Tasks 4–6 are gap 2 (A2). The plan adds 24
tests: 4 in Task 1, 5 in Task 2, 8 in Task 4, 6 in Task 5 and 1 in Task 6.
Task 3 edits one pin. The main risks are the chain rules leaking into the
single-selection behaviour every existing delivery test pins, and a sync fold
tripping the reducer's intermediate validation. D20 handles the second, and
Task 4's gate runs every model and delivery suite.

## Task index

Task 1 — The builder takes a live branch for a worktree name that is not an issue branch — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `T/test_workflow_delivery.py` — full — [task-1.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-1.md)

Task 2 — workflow-state probes the live checkout, and a legacy attempt resumes and retries — `S/workflow-state.py`, `T/test_delivery_workflow.py`, `CLAUDE.md` — full — [task-2.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-2.md)

Task 3 — AUTO.md's delegated owner takes `expected_branch` and its path from the contract — `K/from-issue/AUTO.md`, `home/common/agent-skills/instruction-load.json`, `T/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-3.md)

Task 4 — The delivery model follows one selection chain per slot — `M/_objects.py`, `M/_wire.py`, `M/_reconcile.py`, `M/__init__.py`, `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py` — full — [task-4.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-4.md)

Task 5 — The `sync-selection` and `current-selection` builder kinds, and a remainder merges after a sync — `S/workflow_delivery_build.py`, `S/workflow_delivery.py`, `S/workflow-state.py`, `T/test_delivery_workflow.py`, `T/test_workflow_delivery.py`, `CLAUDE.md` — full — [task-5.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-5.md)

Task 6 — ship-issue's post-selection sync route, then the final gate — `K/ship-issue/CI-MERGE.md`, `K/ship-issue/SKILL.md`, `T/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-6.md](2026-09-27-issue-192-delivery-contract-gaps.tasks/task-6.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| A1: a slugless recorded worktree on a slugged branch gets a contract | 1 (rule 2), 2 (probe, T1–T3) |
| A1: it resumes or retries through a documented route | 2 (T4 control resume, T5 direct retry, help, CLAUDE.md), 3 (AUTO.md) |
| A2: a post-review sync is selected, and publish/open/merge follow the tip | 4 (chain, T10), 5 (`sync-selection`, T7, T9) |
| A2: a remainder obtains the current selection it did not build | 4 (`current_selection`), 5 (`current-selection`, T7, T8, T12) |
| A2: a merge that landed at a sync run folds, and cleanup completes | 4 (final once merged), 5 (T8, both checkpoint shapes) |
| A2: the documented route, and a mergeability refusal is not a denial | 6 (CI-MERGE.md, SKILL.md pointers, T11) |

## Decisions

The spec's `## Decision ledger` is authoritative, and tasks cite its rows by
ID. D1–D18 come from design and grill, D19–D23 from planning, and D24–D28 from
the standards-review loop below.

The first planning probe applied every member as written to a scratch copy of
`70946b0`. Each gate passed, and three mutants were caught (D20's reset, the tip
rule, final-once-merged). `just agent-workflow-tests` gave `Ran 1362 tests` and
`OK (skipped=3)` at base. The review loop re-probed Tasks 1, 4 and 5 as revised:
every gate passed, 247 regression tests passed, and four mutants were caught
(final-once-merged without `merged` or without repository and base, a
first-match selection lookup, and a builder without its digest re-check). Tasks
3 and 6 passed their suites on a scratch copy that measured the ceilings they
name. `just build` was not probed.

## Standards review provenance

Phase 5 reviewed base `6ab576e` at HEAD `6307110`, read-only. Codex ran first
and completed, but its JSONL carried no runtime-selection event, so the
`Claude fallback` reviewer ran with the same packet. The controller verified
every finding against live code. Accepted: 9. Rejected: 1. Deferred: 0.

- **Accepted.** B1 (Blocking, no sanctioned source of the selection a remainder
  did not build) triggered a spec back-up loop: D24, D25, Tasks 4–6. Codex S1,
  independently verified, S1, S3 and D5: D26, Task 6. S2: D27, Task 3. D1: D28,
  Task 4. D2: T8's two checkpoint shapes, Task 5. D4: Task 2's helper edit.
- **Rejected.** D3: reusing `authored_policy()` for a test-only mapping.

---
