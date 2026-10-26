# Parallel Agent Workflow Tests Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `just agent-workflow-tests` runs its test files concurrently under a fixed default cap of 4, with pass/fail unchanged, each file's output in one block, a `--jobs 1` serial mode and a closing per-file timing report. The advisory CI job reports the suite truthfully.

**Architecture:** A new standard-library module, `agent_tools.suite_runner`, takes the recipe's curated member list (test files and the eval-tree script) and runs each member as its own child process. Worker threads take members in list order, at most `--jobs` at a time, and write each member's captured output as one locked block when it exits. Task 1 builds the runner and its end-to-end tests, and Task 2 wires the recipe to it. Tasks 3 and 4 remove the two causes that keep the advisory CI job red: a shallow checkout, and an adoption fixture whose verdict depends on the host. Task 5 hunts concurrency hazards with repeated full runs, takes the serial-mode evidence and writes the acceptance record.

**Tech stack:** Python 3.12+ standard library (`argparse`, `subprocess`, `threading`, `unittest`), Just, GitHub Actions YAML.

Spec: `.agents/artifacts/specs/2026-10-26-issue-436-parallel-workflow-tests-design.md`. Its `## Decision ledger` rows are cited by ID; this plan appends D11–D13. Issue: https://github.com/fagenorn/nix-config/issues/436.

## Global Constraints

- Base `9d2abb3f` (the spec commit on `ca6ba1ae`). Tasks land in index order, each on top of the one before.
- The runner is standard library only and runs on Python 3.12 (the hosted runner's `python3`) and 3.13 (the dev hosts). Importing it starts nothing (D1).
- Agent-helpers rules: the runner has `prog="agent-workflow-tests"` and no row in `lib/agent-tools.nix` and no launcher (D1). Package code never edits `sys.path`, loads a module through `importlib` or by path, or looks anything up from `__file__`. Tests import `agent_tools` normally and run the command as `python -m agent_tools.suite_runner`.
- Unchanged in every task: `CLAUDE.md`, `lib/agent-tools.nix`, `.agents/project.json` (the `agent-workflow-tests` id and argv), the CI job's invocation, name, step names and ids, `continue-on-error`, `timeout-minutes: 45` and the required checks (D4, D8). The 102 existing member paths keep their order (D3).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 436", never a bare `#436`. No `TODO` or `FIXME`.
- Run each long command, every test and gate included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files go under the root that `launch-scope scratch …` prints.
- Focused test form (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <test files> [-k <name>] 2>&1 | tail -6'`. `PYTHONPATH` must be absolute, because the runner tests start the runner in a temporary working directory.
- Final gate (sdd, once on the final head): `just agent-workflow-tests` (now parallel at the default cap; about 6 min on eleven-m5; timeout 3600 s; ends with a `suite-runner: summary … failed=0 …` line and exit 0) and `just build` (timeout 3600 s).
- Known flake (seen in issue 439's plan): `tests/test_review_projection_cases.py::IndependentPositiveCases::test_cheaper_unrelated_descendant_is_excluded_with_real_standalone_parity` can fail its `count-objects` assertion when the fixture repository is repacked mid-test. A run that fails on that assertion alone is re-run once, with both outputs recorded. A second failure is BLOCKED.
- After the PR opens, ship owns CI. A failure that appears only on CI is fixed in this slice only when it comes from missing history or a host-dependent fixture. Any other cause returns to the caller (D8). A step reading over 360 s at the default is recorded and returned, never answered by raising the default (D10).

## Test seams

- `python -m agent_tools.suite_runner` end to end, in a temporary working directory, over generated fixture members that meet at a filesystem barrier (D9): `tests/test_suite_runner.py`.
- `suite_runner.report_lines` (ordering, per D9) and `suite_runner.validate_members` (the recipe's member list), imported directly in the same module.
- `tests/test_branch_protection.py` `WorkflowShape` for the advisory checkout's history depth (D8).
- The four adoption test modules run under a `PATH` that lacks `codex-companion`, the way the hosted runner does (D8, D13).
- Gates: `just agent-workflow-tests` (the runner itself, including the `--jobs 1` run in Task 5) and `just build`.

## Delivery estimate and boundaries

Estimates only: 9 changed files plus this plan, the spec ledger and the acceptance record. `python/agent_tools/suite_runner.py` is about 230 lines and `tests/test_suite_runner.py` about 430 (about 19 KB). `python/README.md` gains one paragraph (about 2 KB). `justfile` changes about 5 lines, `ci.yaml` 3, `tests/test_branch_protection.py` 1, and the two adoption test modules about 20 together. That is about 40 KB of diff in one review package, with no file record near the 64 KB member limit. Tasks 3 and 4 can each be delivered alone. Task 2 needs Task 1, and Task 5 needs all four.

## Task index

Task 1 — `agent_tools.suite_runner` and its end-to-end tests — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py`, `python/README.md` — full — [task-1.md](2026-10-26-issue-436-parallel-workflow-tests.tasks/task-1.md)
Task 2 — The recipe hands its curated members to the runner — `justfile`, `tests/test_suite_runner.py` — full — [task-2.md](2026-10-26-issue-436-parallel-workflow-tests.tasks/task-2.md)
Task 3 — The advisory checkout fetches full history — `.github/workflows/ci.yaml`, `tests/test_branch_protection.py` — low-risk — [task-3.md](2026-10-26-issue-436-parallel-workflow-tests.tasks/task-3.md)
Task 4 — Adoption fixtures resolve the same on every host — `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — low-risk — [task-4.md](2026-10-26-issue-436-parallel-workflow-tests.tasks/task-4.md)
Task 5 — Concurrency audit, serial-mode evidence and the acceptance record — `.agents/artifacts/plans/2026-10-26-issue-436-parallel-workflow-tests.acceptance.md` (plus only the test modules a surfaced hazard names) — full — [task-5.md](2026-10-26-issue-436-parallel-workflow-tests.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_suite_runner.py::FailureIsolationTest::test_a_failing_member_fails_the_run_and_keeps_its_output_in_one_block` (exit 1; every marker of the failing member lies between its `begin` and `end` lines with no runner line or peer marker there), run in the suite by `just agent-workflow-tests` once Task 2 enrols it. |
| AC2 | code | Task 1 | `tests/test_suite_runner.py::CapTest`: `test_two_jobs_reach_two_open_members_and_never_exceed_them`, `test_the_default_cap_is_four`, `test_help_names_the_command_and_documents_the_default` and `test_one_job_runs_members_one_at_a_time_with_their_output_live`. The default is the constant 4, documented in `--help`, the recipe comment (Task 2) and `python/README.md` (D5). |
| AC3 | code | Task 1 | `tests/test_suite_runner.py::ReportTest::test_every_run_ends_with_a_report_covering_every_member` and `::test_rows_run_slowest_first_with_ties_in_list_order`. |
| AC4 | code | Task 5 | Parallel: sdd's final gate `just agent-workflow-tests`, and the advisory CI job on the PR and on the merge push (D8; cited by ship). Serial: `just agent-workflow-tests --jobs 1` at the final code head, exit 0 with `failed=0`. Its summary line is recorded in acceptance row `AC4` and cited in the PR. |
| AC5 | evidence | Task 5 | Per D10, on the merge commit's push run to `main`: `gh run view <run> --repo fagenorn/nix-config --json jobs`, `completedAt − startedAt` of step "Run agent workflow tests" in job "Agent Workflow Tests (advisory)". Conditions: hosted ubuntu-24.04, default cap. Threshold: ≤ 360 s (baseline 1,092 s, run 40194721214 at `0bce14ca`). Task 5 writes row `AC5` as measured by ship after merge. The PR's CI run is the pre-merge reading cited in the PR. |

## Decisions

- Runner placement, invocation and stdlib-only: D1. Members, suffix dispatch and list order: D2, D3. The one `--jobs` option, serial mode and stdio: D4. The default of 4: D5. Output contract and exit codes: D6, refined by D11. Interrupt handling and its test: D12 (Task 1).
- Recipe wiring: D3, D4, with the default named in its comment per D5 (Task 2).
- CI truthfulness: the checkout's history per D8 (Task 3), and the review-command rebinding per D13, which refines D8 (Task 4).
- Hazard audit and its fixes: D7. AC4 and AC5 evidence: D10 (Task 5).

---
