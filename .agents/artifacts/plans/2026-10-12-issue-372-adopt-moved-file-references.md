# adopt-project Rewrites Path Literals Inside Moved Files, by Class Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project plan` surfaces path literals inside the non-Markdown files it moves, decides them by one `reference-policy` answer per (moved tree, file class) with per-occurrence overrides, reads regex-form spellings of a moved prefix, retains a tracked `.claude/settings.json` in place, and `apply` writes each edited moved file at its destination in the one adoption commit.

**Architecture:** `adopt_references` stays the pure core: it gains a second, pattern reading of a token, reads move sources, and gives every occurrence a `target` and (inside a moved tree) a derived policy subject; one `effective_answer` function feeds the rows, the per-policy counts and the edits. `adopt_planning` validates the new answer id in the existing sorted pass, opens the policy questions, admits a write onto a move destination and takes `reference_policies` as the ninth `plan_id` input; `adopt_project` only composes and prints. `adopt_inspection` gains one question id and one classification row. `adopt_apply` is not changed.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, real `git init` fixture repositories under a temporary `HOME`.

Spec: `.agents/artifacts/specs/2026-10-12-issue-372-adopt-moved-file-references-design.md`. Its `## Decision ledger` rows D1–D10 are cited by ID; "350 Dn" names a row of `2026-10-10-issue-350-adopt-path-references-design.md`.

## Global Constraints

- Base: `32807f90d4a4a4eae6ec969adf4e1fb3d5570dca` (`origin/main` at planning).
- Standard library only; no per-language parser (350 D6). Policy lives in `adopt_references`, `adopt_planning` and `adopt_inspection`; `adopt_project` parses, composes and prints (`docs/standards/agent-helpers.md` rule 2).
- Unchanged: `python/agent_tools/adopt_apply.py`, `adopt_links.py`, `adopt_verify.py`; `EVIDENCE_RECORD_MEMBERS`, `ADOPT_SCHEMA_VERSION`, `READY_GATES`, `COMMIT_GATES`, `OPERATION_KINDS`, `ADOPT_ERROR_CODES`; the `--answer` flag's shape; `adopt.decisions.invalid_answer` and `adopt.decisions.unmatched_answer` as the only answer refusals.
- Nothing is edited without an answer (350 D5, D3): a recommendation is printed and never applied.
- The plain reading of a token decides alone whenever it yields an occurrence (D6); every existing `path_references` row keeps its `subject`, `literal`, `answers`, `additions` and `replacement`.
- No repository-specific name in production code: `.claude/notes/study`, `tools/…` and every fixture file name appear in tests only. The one new production path literal is the `.claude/settings.json` classification row (D7).
- Instruction budget: no edit to `CLAUDE.md`, `AGENTS.md` or `.agents/instructions/`. Contract detail goes to `python/README.md` § `adopt-project` only.
- Prose that lands in code (docstrings, comments, error messages, README sentences) describes the code as it behaves at that task's commit. Where a task lists facts instead of a sentence, write the sentence from the implemented code; a docstring this plan does not mention but the change makes false is corrected in the same commit.
- Tests pin JSON key sets, values and the two human-view line formats the spec fixes; no test pins the prose of a `basis`, `impact`, `recommendation` or error message beyond asserting that it does not name a subject.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>.py [-k <pattern>]` (timeout at least 1800 s for `test_adopt_project.py` and `test_adopt_apply.py`: they start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s) and `just build` (timeout 3600 s).

## Test seams

- `adopt_references` functions, imported (`test_adopt_references.py`): `split_pattern`, `pattern_form`, `file_class`, `recommended_answer`, `plan_references`, `derive_references`, `effective_answer`, `summary`, `policy_summary`, `rewritten`.
- `plan` on a fixture repository, as a child process `python -m agent_tools.adopt_project` (`AdoptTestCase.plan`, `run`), plus the imported `adopt_planning.compute_plan_id` and `check_reference_writes` the existing cases already import (`test_adopt_project.py`).
- `apply` by plan id, as a child process (`ApplyTestCase.succeed`), reading the adoption branch through `git show` and `adopt_inspection.export_commit` (`test_adopt_apply.py`).

## Delivery estimate and boundaries

Estimates: 8 changed files — `adopt_references.py`, `adopt_planning.py`, `adopt_inspection.py`, `adopt_project.py`, three test files, `python/README.md` — about +330 production lines and +650 test lines, one review package. Tasks 1 and 2 are each independently deliverable; Tasks 3 to 5 deliver together. Aggregate-growth risks (estimates): `test_adopt_project.py` (2055 lines at base, about 2450 after) and `adopt_references.py` (385, about 560). Between Task 3 and Task 4 an occurrence in a moved file opens its own `path-reference` question; that intermediate head is correct (nothing is edited unanswered) and is not shipped alone.

## Task index

Task 1 — Pattern spellings: the second reading of a token and its carried form — `python/agent_tools/adopt_references.py`, `home/common/agent-skills/tests/test_adopt_references.py` — full — [task-1.md](2026-10-12-issue-372-adopt-moved-file-references.tasks/task-1.md)
Task 2 — Tracked `.claude/settings.json` is retained by classification — `python/agent_tools/adopt_inspection.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-2.md](2026-10-12-issue-372-adopt-moved-file-references.tasks/task-2.md)
Task 3 — Moved files are read, each occurrence has a target and a policy, and the edit lands at the destination — `python/agent_tools/adopt_references.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_references.py`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py` — full — [task-3.md](2026-10-12-issue-372-adopt-moved-file-references.tasks/task-3.md)
Task 4 — The `reference-policy` question, its answers, `reference_policies`, the ninth `plan_id` input and the human view — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-4.md](2026-10-12-issue-372-adopt-moved-file-references.tasks/task-4.md)
Task 5 — The answered fixture applies in one commit, and the documented contract — `home/common/agent-skills/tests/test_adopt_apply.py`, `python/README.md` — full — [task-5.md](2026-10-12-issue-372-adopt-moved-file-references.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 4 | `test_adopt_project.py::ReferencePolicyPlanTest::test_moved_files_open_one_question_per_class` and `::test_answering_every_policy_and_outside_occurrence_reaches_ready` |
| AC2 | code (classified) | Task 5 | `test_adopt_apply.py::ReferencePolicyApplyTest::test_rewritten_files_land_at_their_destinations_in_one_commit` and `::test_the_outside_command_runs_on_the_adopt_commit_as_on_base` |
| AC3 | code (classified) | Task 5 | `test_adopt_apply.py::ReferencePolicyApplyTest::test_the_pattern_exclusion_is_extended` (the row and its offer: Task 1 `PatternTest`, Task 4 `test_moved_files_open_one_question_per_class`) |
| AC4 | code (classified) | Task 5 | `test_adopt_apply.py::ReferencePolicyApplyTest::test_the_settings_file_stays_in_place_with_a_null_destination` (the plan's evidence entry: Task 2 `NativeSettingsTest`) |
| AC5 | code (classified) | Task 4 | `test_adopt_project.py::ReferencePolicyPlanTest::test_an_occurrence_answer_overrides_its_policy` and `::test_markdown_rewriting_is_unchanged`; the existing `PathReferencePlanTest` and `LinkRewritePlanTest` cases stay green (bytes after `apply`: Task 5 `ReferencePolicyApplyTest::test_retained_and_unnamed_files_keep_their_bytes`) |
| AC6 | code (classified) | Task 5 | `test_adopt_apply.py::ReferencePolicyApplyTest::test_the_evidence_record_lists_the_policy_answers_and_rows` (the id: Task 4 `::test_the_policy_answer_is_covered_by_the_plan_id`) |
| AC7 | code (classified) | Task 5 | `just agent-workflow-tests` exits 0 on the final head |

## Decisions

- Pattern spellings: per D6; the prefilter limit per D9.
- The settings row: per D7.
- Scanning move sources, the base-path subject, the target and the write at the destination: per D1 and D8; the `trees` mapping, the shared precedence function and the class of a file name: per D10.
- Policy subjects, answers, the recommendation table, precedence and which questions open: per D2, D3 and D4.
- Row members, `reference_policies`, the ninth `plan_id` input and the human view: per D5.
- Planning added D9 and D10 to the spec's ledger; no other decision was forced.

---

## Standards review provenance

- Reviewer: Codex (`plan-review`, isolated read-only, no fallback), base SHA `32807f90d4a4a4eae6ec969adf4e1fb3d5570dca`, no focus.
- Findings: 0 blocking, 2 should-fix, 0 actionable discussion. Accepted 2, rejected 0, deferred 0.
- PR-S1 (accepted): Task 4 Step 5 now updates the `plan --answer` help text to name `reference-policy`.
- PR-S2 (accepted): Task 5 documentation item 9 now limits the settings claim to the `candidate-class` question and relocation; literals inside the file may still be answered and edited in place.
