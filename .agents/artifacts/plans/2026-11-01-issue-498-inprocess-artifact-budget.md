# In-process Artifact-Budget Validation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state` checks every report, detail input and review package against the artifact budget inside its own process. It reaches the CLI's verdict, exit code and error text, and starts no child Python process to do it.

**Architecture:** Task 1 splits the artifact-budget CLI's `main` into an importable core, `invoke(argv, read_stdin) -> Outcome`, and a shell that only writes the two streams, so the CLI and every in-process caller share one code path (D3). Task 2 makes `workflow-state` load that module once per process, from the resolved file the CLI runs (D2, D7). Both of its call sites then run through one in-process helper that keeps their refusal texts (D1, D4), and an audit hook proves that no process starts (D5).

**Tech stack:** the Python 3.12+ standard library (`importlib.util`, `dataclasses`, `io`, `traceback`, `sys.addaudithook`, `unittest`), plus one comment in `home/common/agent-skills/default.nix`.

Spec: `.agents/artifacts/specs/2026-11-01-issue-498-inprocess-artifact-budget-design.md`. A bare "Dn" cites its `## Decision ledger`, to which this plan appends D7. "472 Dn" cites issue 472's ledger. Issue: https://github.com/fagenorn/nix-config/issues/498 (parent: issue 436).

## Global Constraints

- Base: this plan's commit, on the spec commit `236aaf28` and its D7 ledger row, over `a731801d`. The tasks land in index order, each on the one before.
- Standard library only. The code runs on Python 3.12 (the hosted runner) and 3.13 (the dev hosts and the installed `workflow-state` interpreter), on Linux and darwin.
- These stay unchanged in every task: the artifact-budget CLI's argv, exit codes, stdout bytes and refusal lines, and every `workflow-state` argv, exit code and `workflow-state:` line. Also unchanged: the `scripts/artifact-budget` wrapper and its install entry, every other caller of the CLI, `justfile`, `CLAUDE.md`, `lib/agent-tools.nix`, `.agents/project.json` and `.github/` (spec § Out of scope).
- Both scripts stay legacy flat scripts under `home/common/agent-skills/scripts/`, and nothing moves into `python/agent_tools`. Agent-helpers rule 3 binds them only at their cluster move (D2).
- A new comment or docstring cites this issue's ledger as `issue 498 Dn`. The bare `Dn` already in these files cite other issues and stay. Comments and docstrings describe the code at their task's commit. No `TODO` or `FIXME`.
- Run every test and gate from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files go under the root that `launch-scope scratch …` prints.
- Focused test form (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<module>.py [-k <pattern>]… 2>&1 | tail -6'`. At base, `test_artifact_budget.py` runs 57 tests, in 366 s on a host at load 60.
- Final gate (sdd, once on the final head): `just agent-workflow-tests` (timeout 3600 s), which exits 0 and ends with `suite-runner: summary … failed=0`. Then `just build` (timeout 3600 s), since Task 2 edits `default.nix`. A failure in a module this plan does not touch is re-run once, with both outputs recorded. A second failure is BLOCKED and returned.

## Test seams

- `artifact_budget.invoke`, imported by `test_artifact_budget.py` and compared row by row with a `sys.executable` run of the source script (D3, D5).
- The lifecycle harness's in-process `workflow-state` (`LifecycleHarness.finish`, the legacy `--result-file` transport), run inside a recording window of a process-creation audit hook, with the CLI's verdict computed outside the window (D5).
- The installed-layout probe of `ArtifactBudgetPolicyResolutionTest`: a `sys.executable -c` child with the same hook, no wrapper, and the module linked into a stand-in store (D5, D7).
- The regression net, unchanged: the exact-byte refusal pinned by `test_delivered_control.py`'s `test_a_rejected_reply_leaves_the_ledger_byte_identical`, and the lifecycle classes' refusal texts.
- Gates: `just agent-workflow-tests` and `just build`.

## Delivery estimate and boundaries

These are estimates. Five files change, besides this plan and the spec ledger:
- `artifact_budget.py` grows by about 26 lines net, and `test_artifact_budget.py` by about 95.
- `workflow-state.py` grows by about 50 lines net, though its two call sites shrink. `test_workflow_state.py` grows by about 150 lines.
- `default.nix` gains three comment lines.

That is about 16 KB of diff, in one review package. Task 1 ships alone: the CLI stays byte-identical, and `workflow-state` still spawns it. Task 2 needs Task 1's `invoke` and `Outcome`.

## Task index

Task 1 — The artifact-budget CLI becomes `invoke` plus two stream writes — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-1.md](2026-11-01-issue-498-inprocess-artifact-budget.tasks/task-1.md)
Task 2 — workflow-state validates in-process and starts no child — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/default.nix` — full — [task-2.md](2026-11-01-issue-498-inprocess-artifact-budget.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_workflow_state.py::InProcessArtifactBudgetTest` has three tests: the result file at `ship-summary`, a `present` detail through `check`, and an `unpublished` detail through `validate-detail-input`. Each runs accepted and refused, records no process-creation audit event, matches the CLI's verdict, and on refusal prints the exact `workflow-state:` line with exit 2. `::ArtifactBudgetPolicyResolutionTest::test_installed_symlinked_policy_validates_a_terminal_result` covers the installed layout: no wrapper, no spawn, and the module's store target loaded. Task 1's `test_artifact_budget.py::InvokeParityTest` proves the core matches the CLI. `just agent-workflow-tests` runs them all, locally and on the PR's Linux CI run. |
| AC2 | evidence | Task 2 | Post-merge only, measured by ship (D6). Conditions: the merge commit's push run to `main`, job "Agent Workflow Tests (advisory)", hosted ubuntu-24.04, default cap 4. Run these two commands for that run and again for the last push run to `main` before the merge. First `gh run view <run-id> --repo fagenorn/nix-config --log > <log>`. Then `awk '/Agent Workflow Tests \(advisory\)/ && match($0, /suite-runner: +[0-9]+\.[0-9]s /) { split(substr($0, RSTART, RLENGTH), f, " "); s += f[2] } END { printf "%.1f\n", s }' <log>`. The awk sums the module seconds of the timing rows. It reads the rows with and without the `wall`/`cpu` columns, and skips `end` and `summary` lines. Threshold: the merge run's sum is at least 200 s below the earlier run's (2,033 s on run 41314186007 when the issue was filed). Acceptance-record row `AC2` stays `unverified` on the branch, with no branch gate, and ship fills it after the merge. The PR's CI run is the pre-merge reading cited in the PR. |

## Decisions

- The shared core and the CLI shell: D3 (Task 1).
- Loading the module once per process: D2, from the resolved target per D7 (Task 2).
- The one invocation helper, its exception mapping and the load-failure text: D1, D4 (Task 2).
- The parity table and the audit-hook proof: D5 (Tasks 1 and 2). D7's installed-layout pins are in Task 2.
- AC2 as post-merge evidence, and the per-call costs left in place: D6.

---
