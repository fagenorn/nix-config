# adopt-project Classifies Agent Records and Answers Candidate Questions Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project plan` relocates `.claude/{handoffs,notes,research}` centrally, and every candidate that is still unclassified carries a stable `candidate-class` question that `plan --answer` settles inside `plan_id` and `apply` honours from the stored plan.

**Architecture:** Three new `CLASSIFICATION_RULES` rows plus a widened `no-existing-destination` gate cover the record trees. A second literal question id, `candidate-class`, keyed by a `subject` path, is emitted for every remaining `needs-decision` entry; one policy function in `adopt_planning` applies `--answer` triples to the classified candidates inside `compose_plan`, so `plan` and `apply` share one derivation and the answers enter the D15 digest.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, git fixture repositories.

Spec: `.agents/artifacts/specs/2026-10-09-issue-340-adopt-classify-agent-records-design.md` (its `## Decision ledger` rows D1–D9 are cited by ID).

## Global Constraints

- Base: `eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7` (`origin/main` at planning).
- Unchanged closed sets: `ADOPT_ERROR_CODES`, `ACTIONS`, `PROVENANCES`, `LIFECYCLE_CLASSES`, `READY_GATES`, `COMMIT_GATES`, `OPERATION_KINDS`. `apply` keeps exactly `--plan-id` and `--acknowledge-deletions` (D16). No `resolve_project` change, no new conformance bucket, no Nodo-specific row (spec Out of scope).
- New refusals are `adopt_failure` with repair ids `adopt.decisions.invalid_answer` and `adopt.decisions.unmatched_answer`; a malformed stored answer reuses `adopt.plan.malformed`.
- Prose that lands in code (docstrings, comments, fixed strings, README sentences) describes the code as it behaves at that task's commit; where a task's prose names behaviour a later task adds, that task's step says so and the later task rewrites it.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest <file> -k <pattern>` (timeout at least 900 s; the adopt suites start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s). No `.nix` file changes, so `just build` runs only if one does.

## Test seams

- `plan` on a fixture repository: `AdoptTestCase.plan` / `ready_plan` and the fixture builders in `home/common/agent-skills/tests/test_adopt_project.py`, run as `python -m agent_tools.adopt_project` under a temporary `HOME`.
- `apply` by plan id: `ApplyTestCase.succeed` / `refuse` / `stored_plan` / `rewrite_stored_plan` and `apply_repo` in `home/common/agent-skills/tests/test_adopt_apply.py`.
- `verify` after apply: `VerifyTestCase.report` / `check` in `home/common/agent-skills/tests/test_adopt_verify.py`.
- In-process closed-set dispatch: `agent_tools.adopt_inspection` functions imported by `test_adopt_project.py` (the module already imports `adopt_planning` and `adopt_project` this way).

## Delivery estimate and boundaries

Estimates: 8 changed files — `adopt_inspection.py`, `adopt_planning.py`, `adopt_project.py`, `adopt_apply.py`, the three adopt test modules and `python/README.md` — about +250 production lines and +350 test lines. One review package; no slicing needed. All test modules are already wired in the `justfile`'s `agent-workflow-tests` recipe.

## Task index

Task 1 — Record trees relocate centrally; one destination per move — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-1.md](2026-10-09-issue-340-adopt-classify-agent-records.tasks/task-1.md)
Task 2 — Every undecided candidate opens a `candidate-class` question — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-2.md](2026-10-09-issue-340-adopt-classify-agent-records.tasks/task-2.md)
Task 3 — `plan --answer` settles candidates inside the plan id — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-3.md](2026-10-09-issue-340-adopt-classify-agent-records.tasks/task-3.md)
Task 4 — `apply` honours stored answers; contract documented — `python/agent_tools/adopt_apply.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `home/common/agent-skills/tests/test_adopt_verify.py`, `python/README.md` — full — [task-4.md](2026-10-09-issue-340-adopt-classify-agent-records.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 1 | `test_adopt_project.py`: `RecordTreeClassificationTest.test_the_three_record_trees_plan_to_ready` |
| AC2 | code (classified) | Task 3 | `test_adopt_project.py`: `CandidateAnswerTest.test_answering_reaches_ready_and_changes_the_plan_id` (with Task 2's `CandidateQuestionTest` pinning the stable id on every undecided candidate) |
| AC3 | code (classified) | Task 4 | `just agent-workflow-tests` passes on the final head, run by sdd's final gate after Task 4's suites are green |

## Decisions

- Record-tree rows and targets: D1. Shared-destination gate: D2.
- `candidate-class` literal id plus `subject`: D3; the one answer per provenance and the secret-shaped `value: null`: D4, D7; fixed prose and the human line: D8 (appended by this plan).
- `--answer` on `plan` only, answers authenticated by `plan_id`: D5; validation order and stored-answer validation: D9 (appended by this plan).
- No reference rewriting: D6.

---
