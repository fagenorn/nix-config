# adopt-project Formats What It Rewrote and Reads Variable-Joined Shell Paths Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project` reads `$name/` and `${name}/`-joined paths in shell-class files as occurrences under their own `<tree>:<class>/variable` policy, and runs an operator-named contract command over the files the reference answers edit, inside `apply` and before the commit gates, so a rewrite that crosses the target's formatter limit still commits atomically.

**Architecture:** `adopt_references` gains a third, variable reading of a token (shell classes only, tried last) and a derived occurrence class that feeds the policy subject. `adopt_planning` validates a fourth `--answer` id, `reference-format`, after the other three, derives `reference_formatting` rows from the reference edits, and takes them as the tenth `plan_id` input and an evidence-record member; `adopt_project` composes and prints. `adopt_apply` gains one formatting step between the checked operations and the commit gates, with its own confinement proof.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, real `git init` fixture repositories under a temporary `HOME`.

Spec: `.agents/artifacts/specs/2026-10-12-issue-376-adopt-format-step-and-variable-paths-design.md`. Its `## Decision ledger` rows D1–D15 are cited by ID; "372 Dn" names a row of `2026-10-12-issue-372-adopt-moved-file-references-design.md`.

## Global Constraints

- Base: `69a1047920707528fc97729b57b705332a360d27` (`origin/main` at planning).
- Standard library only; no shell parser and no per-language formatter in the package (350 D6, D1). Policy lives in `adopt_references`, `adopt_planning` and `adopt_apply`; `adopt_project` parses, composes and prints (`docs/standards/agent-helpers.md` rule 2).
- Unchanged: `python/agent_tools/adopt_verify.py`, `adopt_links.py`, `resolve_project.py`, the contract schema; `QUESTION_IDS`, `EVIDENCE_RECORD_MEMBERS`, `ADOPT_SCHEMA_VERSION`, `READY_GATES`, `COMMIT_GATES`, `OPERATION_KINDS`, `ADOPT_ERROR_CODES`; the `--answer` flag's shape; the twelve members of a `path_references` row and the thirteen of a `reference_policies` row.
- Nothing is edited without an answer, and a plan with no `reference-format` answer formats nothing and runs no extra resolver call (D2, D12).
- The plain reading decides first and the pattern reading second; the variable reading is tried only after both leave a token without an occurrence, so every existing `path_references` row keeps its members and values (D6).
- No repository-specific name in production code: fixture paths (`.claude/notes/jobs`, `tests/test_analyzer.py`, `tools/format.py`, …) appear in tests only.
- Instruction budget: no edit to `CLAUDE.md`, `AGENTS.md` or `.agents/instructions/`. Contract detail goes to `python/README.md` § `adopt-project` only.
- Prose that lands in code (docstrings, comments, error messages, README sentences) describes the code as it behaves at that task's commit. Where a task lists facts instead of a sentence, write the sentence from the implemented code; a docstring the change makes false is corrected in the same commit.
- Tests pin JSON key sets, values, repair ids and the human-view line format the spec fixes; no test pins the prose of a `basis`, `impact`, `recommendation` or error message.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>.py [-k <pattern>]` (timeout at least 1800 s for `test_adopt_project.py`, `test_adopt_apply.py` and `test_adopt_verify.py`: they start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s) and `just build` (timeout 3600 s).

## Test seams

- `adopt_references` functions, imported (`test_adopt_references.py`): `split_variable`, `variable_form`, `plan_references`, `effective_answer`, `policy_summary`, `rewritten`, `Occurrence.policy`, `Occurrence.occurrence_class`.
- `plan` on a fixture repository, as a child process `python -m agent_tools.adopt_project` (`AdoptTestCase.plan`, `run`), plus the imported `adopt_planning.compute_plan_id` the existing cases already import (`test_adopt_project.py`).
- `apply` by plan id, as a child process (`ApplyTestCase.succeed`, `assert_retained`), reading the adoption branch through `git show` and `adopt_inspection.export_commit`, then `verify` as a child process on the merged branch (`test_adopt_apply.py`).

## Delivery estimate and boundaries

Estimates: 9 changed files — `adopt_references.py`, `adopt_planning.py`, `adopt_project.py`, `adopt_apply.py`, three test files, `python/README.md`, the spec — about +250 production lines and +600 test lines, one review package. Tasks 1–2 (variable reading) and Tasks 3–4 (formatting) are independently deliverable slices; Task 2 needs Task 1, Task 4 needs Task 3. Aggregate-growth risks (estimates): `test_adopt_project.py` (2674 lines at base, about 2900 after) and `test_adopt_apply.py` (1271, about 1500). Between Task 3 and Task 4 a `reference-format` answer is accepted and published but `apply` formats nothing, so such a plan is refused at the verification gate exactly as without the answer; that intermediate head is not shipped alone.

## Task index

Task 1 — The variable reading, its carried form and the occurrence class — `python/agent_tools/adopt_references.py`, `home/common/agent-skills/tests/test_adopt_references.py` — full — [task-1.md](2026-10-12-issue-376-adopt-format-step-and-variable-paths.tasks/task-1.md)
Task 2 — Variable-joined paths in plan and apply, and their documentation — `python/agent_tools/adopt_planning.py`, `python/README.md`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py` — full — [task-2.md](2026-10-12-issue-376-adopt-format-step-and-variable-paths.tasks/task-2.md)
Task 3 — The `reference-format` answer, `reference_formatting`, the tenth `plan_id` input and the human line — `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-3.md](2026-10-12-issue-376-adopt-format-step-and-variable-paths.tasks/task-3.md)
Task 4 — The formatting step in `apply`, its confinement proof, and the documented contract — `python/agent_tools/adopt_apply.py`, `python/agent_tools/adopt_project.py`, `python/README.md`, `home/common/agent-skills/tests/test_adopt_apply.py` — full — [task-4.md](2026-10-12-issue-376-adopt-format-step-and-variable-paths.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 4 | `test_adopt_apply.py::ReferenceFormattingApplyTest::test_the_formatted_rewrite_commits_and_passes_the_lint` and `::test_without_a_format_answer_the_lint_gate_refuses`, with the refusal cases of the same class |
| AC2 | code (classified) | Task 2 | `test_adopt_apply.py::VariablePolicyApplyTest::test_rewrite_lands_at_the_destination` and `::test_retain_keeps_the_base_blob`; the plan side: `test_adopt_project.py::VariablePolicyPlanTest::test_variable_paths_open_their_own_policy` |
| AC3 | code (classified) | Task 2 | `test_adopt_project.py::VariablePolicyPlanTest::test_a_non_shell_class_reads_no_variable` and the existing `PathReferencePlanTest`, `ReferencePolicyPlanTest`, `LinkRewritePlanTest`, `PathReferenceApplyTest` and `ReferencePolicyApplyTest` cases green (the unit side: Task 1 `VariableReadingTest::test_tokens_the_earlier_readings_take_are_unchanged`) |
| AC4 | code (classified) | Task 4 | `test_adopt_apply.py::ReferenceFormattingApplyTest::test_the_evidence_record_lists_the_format_answer_and_rows` (the id: Task 3 `ReferenceFormattingPlanTest::test_a_format_answer_names_the_command_and_changes_the_id`, `::test_compute_plan_id_covers_the_rows`) |
| AC5 | code (classified) | Task 4 | `just agent-workflow-tests` exits 0 on the final head |

## Decisions

- The formatter is run in `apply`, named by an optional answer whose value is a `bindings.commands` key: per D1, D2; its validation order and refusals: per D11.
- `reference_formatting` rows, the tenth `plan_id` input and the evidence member: per D3; existing tests that change: per D14.
- The step's place, its confinement proof and its failures: per D4, D5, D9; its resolver observation: per D12.
- The variable reading, its shell classes and its limits: per D6, D7, D10; the occurrence class and the `/variable` policy: per D8, D13.
- The AC1 fixture's lint and formatter scripts: per D15.
- Planning added D11–D15 to the spec's ledger; no other decision was forced.

---
