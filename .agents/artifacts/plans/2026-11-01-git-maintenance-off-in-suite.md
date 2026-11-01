# Git Maintenance Off in the Suite's Children Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every member `agent_tools.suite_runner` launches runs with `maintenance.auto=false` and `gc.auto=0` appended to `GIT_CONFIG_PARAMETERS`, so a commit in a test's repository starts no `git maintenance` process, proved by git's own trace.

**Architecture:** One pure function, `member_environment`, composes the members' environment from the runner's own environment (D2, D5). `run_suite` computes it once and passes it to both launch sites, `_run_serial` and `_run_parallel`, which hand it to `subprocess.Popen` as `env=` (D1). The runner's contract paragraph in `python/README.md` states the entries, their composition and their reach (D3).

**Tech stack:** Python 3 standard library (`subprocess`, `unittest`, `json`), git trace2 (`GIT_TRACE2_EVENT`), bash for one fixture member, Just.

Spec: `.agents/artifacts/specs/2026-11-01-git-maintenance-off-in-suite-design.md`. A bare "Dn" cites its `## Decision ledger`; "#436 Dn" cites `2026-10-26-issue-436-parallel-workflow-tests-design.md`. This plan appends D5. Issue: https://github.com/fagenorn/nix-config/issues/496.

## Global Constraints

- Base `8d0bbc25` (`origin/main` at planning). Spec commit `0518859a`. Tasks land in index order, each on top of the one before.
- `python/agent_tools/suite_runner.py` stays standard-library only. `--jobs` stays its only option and no environment variable configures it (#436 D4). `main`'s and `run_suite`'s signatures are unchanged (D5). The runner never writes to `os.environ`.
- The suite's entries are exactly `'maintenance.auto'='false' 'gc.auto'='0'`, carried only by `GIT_CONFIG_PARAMETERS`, never by `GIT_CONFIG_COUNT` (D2).
- Not edited: the `justfile` (recipe, pinned first line and member list), every `.nix` file, `.github/`, every fixture and test-support module (`tests/retained_review_test_support.py`, `tests/test_review_task7.py`, `tests/test_review_history.py` included), and every existing test case in `tests/test_suite_runner.py` (spec § Out of scope).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 496", never a bare `#496`. No `TODO` or `FIXME`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Runner module** (timeout 300 s, about 5 s). `PYTHONPATH` must be absolute, because the runner tests start `python -m agent_tools.suite_runner` from a temporary directory. Append `-k <pattern>` (repeatable) to focus it:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py 2>&1 | tail -4'
  ```

  At base it ends `Ran 16 tests` and `OK`.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

All in `tests/test_suite_runner.py`, already a suite member (spec § Test seams, D4):

- `suite_runner.member_environment`, imported directly, observed only through `git config --get` under its result in a scratch directory with global and system config nulled (Task 1).
- `python -m agent_tools.suite_runner` end to end over a fixture `.sh` member that commits under `GIT_TRACE2_EVENT`, once with `--jobs 1` and once with `--jobs 2`, beside a control that runs the same member with `bash` outside the runner with `maintenance.autoDetach=false` (Task 2).
- Every environment these cases build starts from the test's own with `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and every `GIT_CONFIG_KEY_*` and `GIT_CONFIG_VALUE_*` removed, through the module-level helper `without_command_git_config` (D4, D5).

## Delivery estimate and boundaries

All figures are estimates. Three changed files, plus this package and one spec ledger row, about +180/−8 lines: `suite_runner.py` about +35/−7, `tests/test_suite_runner.py` about +145, `python/README.md` one sentence rewritten and three added (about +1.2 KB). This is one review package. If a split is forced, each task is its own slice: S1 = Task 1, S2 = Task 2 (AC1, AC2).

## Task index

Task 1 — The members' git environment, composed and observed through git — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py` — full — [task-1.md](2026-11-01-git-maintenance-off-in-suite.tasks/task-1.md)
Task 2 — Both launch sites pass it; a traced commit under the runner starts no maintenance child; README contract — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py`, `python/README.md` — full — [task-2.md](2026-11-01-git-maintenance-off-in-suite.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `tests/test_suite_runner.py::GitMaintenanceTest::test_a_commit_in_serial_mode_starts_no_maintenance_child` and `::test_a_commit_in_parallel_mode_starts_no_maintenance_child` (the trace holds the commit's `start` event and no argv holding `maintenance`), made non-vacuous by `::test_the_same_commit_outside_the_runner_starts_a_maintenance_child`; no lock-file assertion, per D4 |
| AC2 | code | Task 2 | CI `Agent Workflow Tests (advisory)` at the PR head, read per #436 D15: the `AGENT_WORKFLOW_OBSERVATION_V1` record with `"suite":"success"` and the log's `suite-runner: summary … failed=0` line, not the job's colour; locally, sdd's final-gate `just agent-workflow-tests` (default `--jobs 4`) ending with that summary line |

## Decisions

- Task 1 rests on D2 and D5. Task 2 rests on D1, D3, D4 and D5.
- Planning appended D5 (the interface of `member_environment` and where it is computed, and how the new cases strip the inherited git configuration).
- A planning trial ran at `0518859a` in a scratch worktree, then discarded, on git 2.51.2. Task 1's cases errored at base (6 errors), passed with the function, and each of four wrong compositions (overwrite, a bare space join, prepend, `GIT_CONFIG_COUNT` slots) was killed by its own case. Task 2's two commit cases failed before the wiring, each listing `['git', 'maintenance', 'run', '--auto', '--quiet', '--detach']`, while the control passed. After the wiring, removing `env=` from either launch site failed only that site's case, and removing the strip override failed the control when the module ran under the runner. With both tasks applied the module ran 25 tests `OK`, and the first 19 members of `just agent-workflow-tests`, among them `tests/test_review_history.py` and `tests/test_review_task7.py`, which set their own `GIT_CONFIG_COUNT`, passed before that run was stopped for host load; the whole suite runs in sdd's final gate.
