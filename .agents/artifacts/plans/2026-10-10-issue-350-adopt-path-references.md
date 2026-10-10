# adopt-project Carries Path-Scoped Tooling References Across the Moves Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project plan` finds every path literal in a tracked non-Markdown text file that names something the plan moves, opens one `path-reference` question per occurrence, and on an `extend` or `rewrite` answer edits that file in the same atomic adopt commit, with every occurrence and answer published inside `plan_id` and the evidence record.

**Architecture:** One new standard-library module, `agent_tools.adopt_references`, owns the token grammar, the occurrence test, successors and carried forms, the two `extend` shapes and the edited text, with a pure core (`plan_references`, `summary`, `rewritten`) and one thin git reader (`derive_references`). `adopt_planning.apply_answers` derives the references from the settled moves inside its one validation pass and validates `path-reference` answers against them; `compose_plan` publishes the rows, feeds them to `compute_plan_id` as the eighth input and turns each edited file into an ordinary `write-file` in the tail. `adopt_apply` and `adopt_verify` do not change: `apply` re-derives the same plan from the stored answers.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, git fixture repositories.

Spec: `.agents/artifacts/specs/2026-10-10-issue-350-adopt-path-references-design.md` (its `## Decision ledger` rows D1–D12 are cited by ID).

## Global Constraints

- Base: `02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b` (`origin/main` at planning).
- Standard library only, no per-language parser (D6). New helper code lives in `python/agent_tools/` per `docs/standards/agent-helpers.md`; `adopt_references` is imported, never run, and imports `adopt_inspection` and `adopt_links` only.
- Unchanged closed sets: `ADOPT_ERROR_CODES`, `ACTIONS`, `OUTCOMES`, `PLAN_STATES`, `OPERATION_KINDS`, `PROVENANCES`, `LIFECYCLE_CLASSES`, `READY_GATES`, `COMMIT_GATES`, `VERIFY_CHECKS`, `EVIDENCE_RECORD_MEMBERS` (D1, D8, D9). `QUESTION_IDS` gains exactly `path-reference`, last (D7). No new repair id: the refusals are `adopt.decisions.invalid_answer` and `adopt.decisions.unmatched_answer`.
- `python/agent_tools/adopt_apply.py`, `adopt_verify.py` and the link grammar, resolution, mapping and re-emission of `adopt_links.py` are not edited (D9; issue 345's rewriting is out of scope). The one permitted `adopt_links.py` change is Task 1's rename that exports the directory-successor rule (D4).
- Bytes come from the base revision's tree through git, never the working tree; `Composition.overlap` does not grow (D2).
- Prose that lands in code (docstrings, comments, fixed strings, README sentences) describes the code as it behaves at that task's commit.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` (timeout at least 900 s; the adopt suites start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s). No `.nix` file changes, so `just build` runs only if one does.

## Test seams

- `adopt_references` functions, imported in-process by the new `home/common/agent-skills/tests/test_adopt_references.py`.
- `plan` on a fixture repository: `AdoptTestCase.plan` and the fixture builders in `home/common/agent-skills/tests/test_adopt_project.py`, run as `python -m agent_tools.adopt_project` under a temporary `HOME`; in-process `adopt_planning.compute_plan_id`.
- `apply` by plan id: `ApplyTestCase.succeed` and `apply_repo` in `home/common/agent-skills/tests/test_adopt_apply.py`; the fixture's own script run with `sys.executable` on `adopt_inspection.export_commit` exports.

## Delivery estimate and boundaries

Estimates: 10 changed files — new `adopt_references.py` and `test_adopt_references.py`, `adopt_links.py` (one rename), `adopt_inspection.py`, `adopt_planning.py`, `adopt_project.py`, `test_adopt_project.py`, `test_adopt_apply.py`, `justfile`, `python/README.md` — about +380 production lines and +470 test lines. One review package; Task 1 is independently deliverable if a package boundary forces a split.

## Task index

Task 1 — `adopt_references`: tokens, occurrences, successors, shapes and edits — `python/agent_tools/adopt_references.py`, `python/agent_tools/adopt_links.py`, `home/common/agent-skills/tests/test_adopt_references.py`, `justfile` — full — [task-1.md](2026-10-10-issue-350-adopt-path-references.tasks/task-1.md)
Task 2 — `plan` asks, settles, publishes and writes the path references — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-2.md](2026-10-10-issue-350-adopt-path-references.tasks/task-2.md)
Task 3 — `apply` commits the answered references, and the contract is documented — `home/common/agent-skills/tests/test_adopt_apply.py`, `python/README.md` — full — [task-3.md](2026-10-10-issue-350-adopt-path-references.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `test_adopt_project.py`: `PathReferencePlanTest.test_an_open_reference_keeps_the_plan_draft_with_a_stable_question` and `test_answering_extend_reaches_ready_with_one_write` |
| AC2 | code (classified) | Task 3 | `test_adopt_apply.py`: `PathReferenceApplyTest.test_the_extended_script_passes_on_the_adopt_commit_as_on_base` (with `test_a_retained_reference_leaves_the_check_failing`) |
| AC3 | code (classified) | Task 2 | `test_adopt_project.py`: `PathReferencePlanTest.test_markdown_rewriting_is_unchanged_and_other_files_are_untouched` (with Task 3's byte-identity assertion on the unrelated script and the unedited issue-345 suites `LinkRewritePlanTest`, `LinkRewriteApplyTest`) |
| AC4 | code (classified) | Task 2 | `test_adopt_project.py`: `PathReferencePlanTest.test_the_answer_is_covered_by_the_plan_id` (with Task 3's `PathReferenceApplyTest.test_the_evidence_record_lists_the_answer_and_the_row`) |
| AC5 | evidence (classified) | Task 3 | Command `just agent-workflow-tests`, run on the final head after Task 3 by sdd's final gate; threshold: exit code `0` |

## Decisions

- Inventory with questions, no gate and no `verify` check: D1. Scanned files and the fixed exclusion set: D2, D10.
- Tokens and the occurrence test: D3, read with D11 (appended by this plan: the three conditions decide, so a quoted directory name inside a call is an occurrence that offers `retain` only).
- Successors and carried forms: D4. Answers and the two `extend` shapes: D5, D6.
- The question, its subject and the answer replay: D7; where the derivation sits in `apply_answers`: D12 (appended by this plan).
- The `path_references` rows, the evidence record and `plan_id`: D8. `write-file` placement and the single-writer check: D9.

---

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, fresh isolated read-only thread), base `02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b`, no fallback, no focus. Findings: 0 blocking, 3 should-fix, 0 discussion; accepted 3, rejected 0, deferred 0. Each was verified against the live worktree before it was applied.

- PR-S1 (accepted): Task 2 gains a case for a reference created by a candidate answer, checked in both answer orders.
- PR-S2 (accepted): Task 2 gains rejection cases for `check_reference_writes`.
- PR-S3 (accepted): AC5 is classified as evidence, with its command, condition and threshold.
