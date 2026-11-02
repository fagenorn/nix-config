# Test Children Reuse Cached Bytecode; workflow-state Imports Its Delivery Module Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every Python process the agent workflow suite starts writes and reuses bytecode in one cache per run, and `workflow-state` loads its delivery module through the import system, so a second `workflow-state` invocation under that cache compiles nothing.

**Architecture:** `run_suite` holds one `tempfile.TemporaryDirectory` for the whole run and hands it to `member_environment(parent, cache)`, which sets `PYTHONPYCACHEPREFIX` and drops `PYTHONDONTWRITEBYTECODE` beside the issue 496 git entries; both launch sites keep receiving the one mapping (D1, D8). The test harnesses that spread the test's environment into a child stop forcing `PYTHONDONTWRITEBYTECODE` (D3). `_delivery()` in `workflow-state` builds a spec from the delivery module's file and executes it through the spec's loader instead of `runpy.run_path` (D4).

**Tech stack:** Python 3 standard library (`tempfile`, `importlib.util`, `subprocess`, `unittest`, `unittest.mock`, `json`), Just.

Spec: `.agents/artifacts/specs/2026-11-02-issue-499-test-bytecode-cache-design.md`. A bare "Dn" cites its `## Decision ledger`; "#496 Dn" and "#436 Dn" cite those issues' design specs. This plan appends D8 and D9. Issue: https://github.com/fagenorn/nix-config/issues/499.

## Global Constraints

- Base `aabcd693` (`origin/main` at planning). Spec commit `a51a4ce0`. Tasks land in index order, each on top of the one before.
- `python/agent_tools/suite_runner.py` stays standard-library only. `--jobs` stays its only option, with no switch or variable that turns the cache off (#436 D4). `main`'s and `run_suite`'s signatures are unchanged, and the runner never writes to `os.environ`.
- Not edited: the `justfile` (recipe, pinned first line, member list), every `.nix` file, `.github/`, `home/common/agent-skills/scripts/workflow_delivery.py` and the modules it loads, `home/common/agent-skills/tests/test_eval_cases.py` (its acceptance child keeps `PYTHONDONTWRITEBYTECODE`, D3), the in-process `runpy` loads in `test_delivery_model.py` and `test_workflow_delivery.py`, and the control-cutover base generation's own loader (spec § Out of scope).
- No suite member is added (D6). No assertion depends on timing, and neither `-X importtime` nor `python -v` is a seam (D6). No test pins an English phrase (`docs/standards/agent-helpers.md` rule 6).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 499", never a bare `#499`. No `TODO` or `FIXME`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Runner module** (timeout 300 s, about 20 s). `PYTHONPATH` must be absolute, because the runner tests start `python -m agent_tools.suite_runner` from a temporary directory. Append `-k <pattern>` (repeatable) to focus it. At base it ends `Ran 29 tests` and `OK`:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py 2>&1 | tail -4'
  ```

- **Harness check** (spec § Test seams): beside the runner tests' sentinel, the eval-case child is the only test child still given `PYTHONDONTWRITEBYTECODE`. It exits 1 at base, listing five files, and after Task 1, listing six; it passes from Task 2 on:

  ```bash
  bash -c 'set -e; got=$(grep -rlF --include="*.py" "\"PYTHONDONTWRITEBYTECODE\": \"1\"" tests home/common/agent-skills/tests | sort | paste -sd " " -); echo "$got"; test "$got" = "home/common/agent-skills/tests/test_eval_cases.py tests/test_suite_runner.py"'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

The spec's three seams (§ Test seams, D6), nothing else:

- `suite_runner.member_environment(parent, cache)`, imported and called directly in `tests/test_suite_runner.py` (Task 1).
- `python -m agent_tools.suite_runner` end to end over two fixture members that record the cache they see, once with `--jobs 1` and once with `--jobs 2`, in `tests/test_suite_runner.py`. The inner runner inherits a sentinel `PYTHONPYCACHEPREFIX` of the test's own and `PYTHONDONTWRITEBYTECODE=1` (Task 1).
- The source-layout `workflow-state init-run` CLI, run twice under one fresh test-owned cache with `PYTHONDONTWRITEBYTECODE` removed, in `home/common/agent-skills/tests/test_delivery_workflow.py` (Task 3).
- A cache file's path is derived with CPython's own `importlib.util.cache_from_source` in both cache seams (per D9). The harness edits carry no test of their own; Task 2 is gated by the harness check and by the edited modules passing under the runner.

## Delivery estimate and boundaries

All figures are estimates, from a scratch run of the three tasks while planning. Eight changed files plus this package, one acceptance record and two spec ledger rows, about +185/−42 lines: `suite_runner.py` about +30/−17, `tests/test_suite_runner.py` about +88/−11, `python/README.md` one clause and ten sentences added (about +2.5 KB), seven one-line harness edits in four files, `workflow-state.py` about +13/−6, `test_delivery_workflow.py` about +39/−5. One review package. If a split is forced, each task is its own slice: S1 = Task 1, S2 = Task 2, S3 = Task 3 (AC1, AC2).

## Task index

Task 1 — The runner gives a run's members one bytecode cache — `python/agent_tools/suite_runner.py`, `tests/test_suite_runner.py`, `python/README.md` — full — [task-1.md](2026-11-02-issue-499-test-bytecode-cache.tasks/task-1.md)
Task 2 — Test harness children inherit the cache — `tests/orchestrate_world.py`, `home/common/agent-skills/tests/test_control_cutover.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_delivered_control.py`, `python/README.md` — full — [task-2.md](2026-11-02-issue-499-test-bytecode-cache.tasks/task-2.md)
Task 3 — workflow-state imports its delivery module; a second `init-run` compiles nothing — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `.agents/artifacts/plans/2026-11-02-issue-499-test-bytecode-cache.acceptance.md` — full — [task-3.md](2026-11-02-issue-499-test-bytecode-cache.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `home/common/agent-skills/tests/test_delivery_workflow.py::DeliveryAdmissionTest::test_a_second_init_run_compiles_nothing_into_its_bytecode_cache` (Task 3, the issue's "no recompilation on the second invocation" test), with `tests/test_suite_runner.py::MemberEnvironmentTest` and `::BytecodeCacheTest` (Task 1) and the harness check (Task 2) for "suite child processes write and reuse bytecode in a per-run cache". Task 3's gate runs all of them. `just agent-workflow-tests` runs the three tests in the suite at the final gate, with `failed=0`; it does not run the harness check, a separate command whose own result the acceptance record cites. |
| AC2 | evidence | Task 3 | Command: for each run, `gh run view <run-id> --repo fagenorn/nix-config --log \| grep -F "suite-runner: summary"`, over the push-triggered `ci.yaml` runs on `main` that `gh run list --repo fagenorn/nix-config --workflow ci.yaml --branch main --event push` lists. Conditions (per D7): the "Agent Workflow Tests (advisory)" job of the merge commit's run and of the last push run before it, both with `failed=0`, `jobs=4` and the same `members=`; a non-qualifying merge run is read from its re-run, and a non-qualifying baseline gives way to the latest earlier qualifying push run, with the reason recorded. Threshold: the baseline's `cpu=` minus the merge run's `cpu=` is at least 150.0 s; the record quotes both summary lines with their run links. Task 3's implementer writes acceptance-record row `AC2` as `not measured — post-merge (D7)`; ship holds the issue for verification. |

## Decisions

Per D1 (the runner owns one cache per run; `member_environment(parent, cache)`), D2 (reach and same-size limits documented, not closed), D3 (which harness sites drop `PYTHONDONTWRITEBYTECODE`; the eval-case child keeps it), D4 (the spec-loader `_delivery()`), D5 (installed bytecode hazard recorded, not closed), D6 (the seams), D7 (AC2 read after merge, issue held). Planning appends D8 (`run_suite` holds the cache in a `tempfile.TemporaryDirectory` context, which covers the interrupt and error exits without a new seam) and D9 (cache paths derived with `importlib.util.cache_from_source`).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus, base aabcd693, no fallback. Blocking: none. Should fix: 2 accepted, 0 rejected, 0 deferred — PR-001 (the acceptance map and AC1 record row cite the harness check separately from `just agent-workflow-tests`, which does not run it) and PR-002 (Task 3 Step 4 times the issue's demo, recorded in the acceptance record's `## Demo` section without an assertion). Discussion: none.

---
