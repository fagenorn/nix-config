# Suite Timing CPU Column Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The closing timing report of `just agent-workflow-tests` lists every member's child CPU seconds beside its wall time and ends its summary with the suite's CPU total, and an interrupt can no longer lose a serial member's exit status.

**Architecture:** One new function, `suite_runner._reap`, reaps every member in both modes with a single `os.wait4` and builds its `MemberResult` (D1). Task 1 moves both modes onto it. Parallel workers read the merged output to its end, then reap. Serial mode waits with a non-reaping `os.waitid` and reaps with SIGINT held (D2, D6), which a new interrupt test pins (D5). Task 2 reads the CPU seconds from that same `wait4`, carries them in `MemberResult`, prints them as a column and as a summary total (D3), proves the criterion with a busy and a sleeping member in both modes (D4), and documents the report in `python/README.md`.

**Tech stack:** Python 3.12+ standard library (`os.wait4`, `os.waitid`, `subprocess`, `signal`, `threading`, `unittest`).

Spec: `.agents/artifacts/specs/2026-11-01-issue-497-suite-cpu-time-design.md`. A bare "Dn" cites its `## Decision ledger`, to which this plan appends D5 and D6. "436 Dn" cites `.agents/artifacts/specs/2026-10-26-issue-436-parallel-workflow-tests-design.md`. Issue: https://github.com/fagenorn/nix-config/issues/497 (parent: issue 436).

## Global Constraints

- Base: this plan's commit, on the spec commits `2c2291b2` and `6c45794a` over `8d0bbc25`. Tasks land in index order, each on the one before.
- Standard library only. The runner runs on Python 3.12 (the hosted runner) and 3.13 (the dev hosts), on Linux and darwin. Importing `agent_tools.suite_runner` starts nothing.
- Agent-helpers rules (`docs/standards/agent-helpers.md`): package code never edits `sys.path`, never loads a module by path and never looks anything up from `__file__`. Tests import `agent_tools` normally and run the runner as `python -m agent_tools.suite_runner`.
- Unchanged in every task: `justfile`, `CLAUDE.md`, `lib/agent-tools.nix`, `.agents/project.json` and `.github/`. The same holds for the runner's header, `start`, `begin`, `end`, `interrupted` and `failed` lines, its exit codes (0, 1, 2, 130), `--jobs` and its default of 4, the 436 D14 launch holds, and the bodies of the four existing `InterruptTest` test methods.
- Comments, docstrings and README sentences describe the code at that task's commit. A new comment cites this issue's ledger as `issue 497 Dn`. The bare `Dn` already in `suite_runner.py` and `tests/test_suite_runner.py` cite issue 436 and stay as they are. No `TODO` or `FIXME`.
- Run every test and gate from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files go under the root that `launch-scope scratch …` prints.
- Focused test form (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py [-k <name>]… 2>&1 | tail -6'`. `PYTHONPATH` must be absolute, because the runner tests start the runner in a temporary working directory. At base the module runs 16 tests in about 5 s.
- Final gate (sdd, once on the final head): `just agent-workflow-tests` (timeout 3600 s). Every report row carries `s wall` and `s cpu`, the run ends with `suite-runner: summary … failed=0 … cpu=<seconds>s`, and it exits 0. Then `just build` (timeout 3600 s). A failure in a module this plan does not touch is re-run once, with both outputs recorded. A second failure is BLOCKED and returned.

## Test seams

- `suite_runner.report_lines`, imported and asserted line for line (436 D9, D11).
- `python -m agent_tools.suite_runner` end to end, in a temporary working directory, over generated fixture members (`RunnerCase`). This includes a `python -c` wrapper that patches one standard-library call and then calls `suite_runner.main`, as `STARTUP_INTERRUPT` and `SERIAL_LAUNCH_INTERRUPT` do (436 D14, D5).
- Gates: `just agent-workflow-tests` and `just build`. The PR's CI run of the advisory agent-workflow job is the Linux check of D1, and ship cites it.

## Delivery estimate and boundaries

Estimates only: three changed files, plus this plan and the spec ledger. `python/agent_tools/suite_runner.py` grows by about 45 lines. `tests/test_suite_runner.py` grows by about 130 lines, to about 25 KB. The runner paragraph of `python/README.md` grows by about 1.3 KB. The total is about 14 KB of diff in one review package, with no file near the 64 KB member limit. Task 1 can ship alone: it changes reaping only, and the report looks the same. Task 2 needs Task 1's `_reap`.

## Task index

Task 1 — One `os.wait4` reaps every member, and an interrupt never loses a serial member's status — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py` — full — [task-1.md](2026-11-01-issue-497-suite-cpu-time.tasks/task-1.md)
Task 2 — The timing report shows each member's child CPU and the suite total — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py`, `python/README.md` — full — [task-2.md](2026-11-01-issue-497-suite-cpu-time.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `tests/test_suite_runner.py::CpuTimeTest::test_parallel_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below` and `::test_serial_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below` (sleeper well below wall, busy close to wall, `cpu=` total), plus `ReportTest::test_rows_run_slowest_first_with_ties_in_list_order` (a CPU figure on every row and the unrounded `cpu=` total). `just agent-workflow-tests` runs them in the suite, locally and on the PR's Linux CI run. |

## Decisions

- Measurement and the single reap function: D1. Task 1 builds `_reap`, and Task 2 reads its CPU.
- Parallel read-then-reap, the serial non-reaping wait and the held reap: D2, refined by D6 for the interrupt path, and pinned by the reap-interrupt test per D5 (Task 1).
- The report row, the summary total and their documentation: D3 (Task 2).
- The busy and sleeping members and their bounds: D4 (Task 2).

---
