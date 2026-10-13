# adopt-project Surfaces and Rewrites Depth-Relative Paths in Moved Trees Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project plan` reads `../` climbs and Python parent-count chains in the files it moves, asks about each one that leaves the moved tree and lands elsewhere after the move under its own `<tree>:<class>/depth` policy, and `rewrite` shifts the climb by the file's depth delta so it lands where it landed on base.

**Architecture:** `adopt_references` gains a fourth, depth reading: text climbs over tokens and Python chains by standard-library regular expressions, judged against the tree root and the landing point, producing ordinary `Occurrence`s marked `depth` whose class is `<file class>/depth`. `derive_references` feeds it a second read set (moved files holding `..` or `__file__`) beside the unchanged first-segment prefilter. Questions, answers, rows, edits, `plan_id`, the evidence record, `apply` and `verify` are the existing mechanism, unchanged.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`), `unittest`, real `git init` fixture repositories under a temporary `HOME`.

Spec: `.agents/artifacts/specs/2026-10-12-issue-380-adopt-depth-relative-paths-design.md`. Its `## Decision ledger` rows D1–D13 are cited by ID.

## Global Constraints

- Base: `15ccdd44bb73330e49be63cffa8b7c03f56c709c` (`origin/main` at planning).
- Standard library only; no per-language parser (issue 350 D6, D2). Policy lives in `adopt_references`; `adopt_project` parses, composes and prints (`docs/standards/agent-helpers.md` rule 2).
- Unchanged: `python/agent_tools/adopt_apply.py`, `adopt_verify.py`, `adopt_project.py`, `adopt_links.py`, `resolve_project.py`, the contract schema; `QUESTION_IDS`, `EVIDENCE_RECORD_MEMBERS`, `ADOPT_SCHEMA_VERSION`, `READY_GATES`, `COMMIT_GATES`, `OPERATION_KINDS`, `ADOPT_ERROR_CODES`, `REWRITE_CLASSES`, `RETAIN_CLASSES`; the `plan_id` inputs; the twelve members of a `path_references` row and the thirteen of a `reference_policies` row (D6).
- Nothing is edited without an answer; `/depth` has no recommendation (D5, D9).
- Every existing occurrence keeps its members and values, and no existing test is edited (D7, D10; AC4).
- No repository-specific name in production code: fixture paths (`.claude/notes/tool`, `vendor/lib`, `uv.lock`, …) appear in tests only.
- Instruction budget: no edit to `CLAUDE.md`, `AGENTS.md` or `.agents/instructions/`. Contract detail goes to `python/README.md` § `adopt-project` only.
- Prose that lands in code (docstrings, comments, README sentences) describes the code as it behaves at that task's commit. Where a task lists facts instead of a sentence, write the sentence from the implemented code; a docstring the change makes false is corrected in the same commit.
- Tests pin JSON key sets, values and subjects; no test pins the prose of a `basis`, `impact`, `recommendation` or error message.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>.py [-k <pattern>]` (timeout at least 1800 s for `test_adopt_project.py`, `test_adopt_apply.py` and `test_adopt_verify.py`: they start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s) and `just build` (timeout 3600 s).

## Test seams

- `adopt_references` functions, imported (`test_adopt_references.py`): `split_climb`, `climb_form`, `python_climbs`, `plan_references` (with `depth_texts`), `effective_answer`, `policy_summary`, `rewritten`, `derive_references`, `Occurrence.depth`, `Occurrence.occurrence_class`, `Occurrence.policy`.
- `plan` on a fixture repository, as a child process `python -m agent_tools.adopt_project` (`AdoptTestCase.plan`) (`test_adopt_project.py`).
- `apply` by plan id, as a child process (`ApplyTestCase.succeed`), reading the adoption branch through `git show`/`git rev-parse` (`test_adopt_apply.py`).
- `verify` as a child process on the merged branch (`VerifyTestCase.report`, `check`) (`test_adopt_verify.py`).

## Delivery estimate and boundaries

Estimates: 8 changed files — `adopt_references.py`, `adopt_planning.py` (docstring), four test files, `python/README.md`, the spec — about +200 production lines and +450 test lines, one review package. Tasks 1–2 are pure-core slices; Task 3 makes them reachable from `plan`. At Tasks 1 and 2 no caller passes `depth_texts`, so `plan` output is unchanged until Task 3. Aggregate-growth risks (estimates): `test_adopt_project.py` (2940 lines at base, about 3040 after) and `test_adopt_references.py` (790, about 1050).

## Task index

Task 1 — The depth reading's text climbs, landing point and `/depth` class — `python/agent_tools/adopt_references.py`, `home/common/agent-skills/tests/test_adopt_references.py` — full — [task-1.md](2026-10-12-issue-380-adopt-depth-relative-paths.tasks/task-1.md)
Task 2 — Python parent-count chains — `python/agent_tools/adopt_references.py`, `home/common/agent-skills/tests/test_adopt_references.py` — full — [task-2.md](2026-10-12-issue-380-adopt-depth-relative-paths.tasks/task-2.md)
Task 3 — The depth read set, depth occurrences in plan, apply and verify, and the documented contract — `python/agent_tools/adopt_references.py`, `python/agent_tools/adopt_planning.py`, `python/README.md`, `home/common/agent-skills/tests/test_adopt_references.py`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-3.md](2026-10-12-issue-380-adopt-depth-relative-paths.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 3 | `test_adopt_apply.py::DepthPolicyApplyTest::test_rewrite_lands_where_the_base_climb_landed` and `::test_retain_keeps_the_base_blobs`; the plan side `test_adopt_project.py::DepthPolicyPlanTest::test_climbs_to_the_root_open_their_own_policies` |
| AC2 | code (classified) | Task 3 | `test_adopt_project.py::DepthPolicyPlanTest::test_climbs_to_the_root_open_their_own_policies` (the fixture's inside-tree `HERE.parent` and `"../data/x"` have no row); the unit side: Task 1 `TextClimbTest::test_climbs_inside_the_tree_are_not_surfaced`, Task 2 `PythonClimbTest::test_chains_inside_the_tree_are_not_surfaced` |
| AC3 | code (classified) | Task 1 | `test_adopt_references.py::TextClimbTest::test_a_same_depth_move_surfaces_nothing_new` (no classification row moves at the same depth, so the seam is `plan_references`) |
| AC4 | code (classified) | Task 3 | every existing class of `test_adopt_references.py`, `test_adopt_project.py`, `test_adopt_apply.py`, `test_adopt_verify.py` and `test_adopt_project_boundaries.py` green with no existing test edited; `TextClimbTest::test_the_depth_read_set_gets_the_depth_reading_only` |
| AC5 | code (classified) | Task 3 | `test_adopt_verify.py::DepthRewriteVerifyTest::test_a_rewritten_climb_verifies_as_derived` |
| AC6 | evidence | Task 3 | command `just agent-workflow-tests` (timeout 3600 s), run once on the final head after every task is committed; threshold: exit status `0` |

## Decisions

- Climbs, landing point, tree root and when a climb is surfaced: per D1, D4, D8; the text climb: per D3; the Python chain: per D2.
- The rewrite and `retain`-only offers: per D1, D3; `/depth` class, policy and lock files: per D5, D6; `draft` until answered: per D9.
- The separate depth read set: per D7.
- The core's interface (`depth_texts`, `Occurrence.depth`, one read per blob): per D10.
- Grammar edges (a rest holding `..`, a chain continued after `.parents[N]`, a chain overlapping another reading's occurrence): per D11.
- Planning added D10–D11 to the spec's ledger; the Phase-5 review added D12 (chain inside a text climb) and D13 (rebinding, CRLF bindings).

---

## Standards review provenance

- Reviewer: Codex (`gpt-6-astra`, effort `xhigh`), fresh thread, isolated read-only mode, no fallback. Base SHA `15ccdd44bb73330e49be63cffa8b7c03f56c709c`.
- Counts: 5 accepted, 0 rejected, 0 deferred.
- B1 accepted: a Python chain overlapping an accepted text climb is dropped, with a rewritten-bytes regression (Task 2; D12).
- B2 accepted: a bound name rebound anywhere (augmented, `:=`, `for`/`as`/`del`/`global`/`nonlocal`, any indentation) is not followed, with negative cases (Task 2; D13).
- B3 accepted: `_BINDING` accepts a `\r\n` line end over the original text, with a CRLF regression (Task 2; D13).
- S1 accepted: Task 3 qualifies the README's "A variable is never followed to its definition" with the Python-binding exception.
- S2 accepted: AC6 is `evidence`, owned by Task 3, with its command, final-head condition and exit-status threshold.
