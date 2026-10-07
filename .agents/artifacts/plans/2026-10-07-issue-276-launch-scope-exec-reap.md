# Launch-Scope Exec and Reap Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** a lifecycle launch's long commands run under `launch-scope exec`, and `launch-scope reap` kills whatever they leave behind: an owner reaps itself before every exit write, and the orchestrate-issues stop pass sweeps every non-current launch (#276, slice S2 of the launch process reaping design).

**Architecture:** Two new `agent_tools` modules. `launch_processes` is the platform seam: the `ps` process table, reading one pid's `AGENT_LAUNCH_SCOPE` marker (`/proc` on Linux, `KERN_PROCARGS2` on darwin), the never-self/ancestor guard, and TERM→KILL termination. `launch_scope` is the `launch-scope` command, with `exec` and `reap`, the registry under the ledger repository's git common dir, and strict `check-launch`/`check-worker` reply parsing. Skill prose in from-issue, sdd, ship-issue and orchestrate-issues adopts it. Spec: `.agents/artifacts/specs/2026-10-07-issue-276-launch-scope-exec-reap-design.md` (ledger D1–D13). Parent: `.agents/artifacts/specs/2026-10-06-launch-process-reaping-design.md` (read-only).

**Tech stack:** Python 3 standard library (`subprocess`, `signal`, `os.waitid`, `ctypes`), Nix command table, Markdown skill text, `unittest`.

## Global Constraints

- Standard library only. No psutil and no new dependency (D7).
- No change to `workflow-state`, the ledger schema, the lifecycle guard, the Claude settings allowlist or the three leaf-agent clauses and their carriers. There is no `scratch` verb and no worktree member in any report (D1, D8).
- External programs are run by name on `PATH`: `workflow-state`, `git` and `ps` (agent-helpers rule 3). A strict JSON load composes `reject_duplicate_keys` and `reject_nonfinite_literal` from `agent_tools.canonical` (rule 4). Every JSON line printed to stdout is `json.dumps(value, sort_keys=True, separators=(",", ":"))` followed by one newline.
- Importing either new module loads no libc, runs no `ps` and reads no `/proc`, so `just build`'s `pythonImportsCheck` passes on both platforms.
- The marker variable is `AGENT_LAUNCH_SCOPE` and its value is `<run-id>/<action-id>/<nonce>`, where the nonce is 32 lowercase hex characters. The registry is `<git common dir>/agent-launch/<run-id>/<action-id>/<nonce>.json`.
- Exit codes. `exec` returns the child's status, 128 plus the signal number for a signalled child, 3 for a refusal, 126 or 127 when the argv cannot run, and 2 for a usage or helper error. `reap` returns 0, 1 when it skipped a launch, and 2 for a usage or helper error. Exit 2 always leaves stdout empty (D6).
- Test processes never inherit the outer environment's `AGENT_LAUNCH_SCOPE`: every fixture env drops it, because the suite itself may run under `launch-scope exec`.
- Run every test command from the worktree root, in the foreground, with `PYTHONPATH="$PWD/python"` and a timeout of at least 600 s.
- The final gate runs once, on the final head: `just build` and `just agent-workflow-tests`, each with a 3600 s timeout. Ship records a darwin run of `tests/test_launch_scope.py` in the PR for AC3.

## Test seams

- `python -m agent_tools.launch_scope` subprocess runs, together with in-process calls to functions that `agent_tools.launch_processes` and `agent_tools.launch_scope` export, all in `tests/test_launch_scope.py`. The ledger is driven through `LifecycleHarness`, loaded from `home/common/agent-skills/tests/test_workflow_state.py` by `spec_from_file_location`, as `tests/test_launch_commit.py` does. A PATH shim runs the source `workflow-state`. Process liveness is observed through `ps`, and a zombie counts as dead (spec **Test seams**, D12).
- Phrase-order contract tests (`assert_ordered` over `normalized()` text) in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
- The instruction-load ceilings in `home/common/agent-skills/tests/test_instruction_load.py` (`LiveModelTest`) over `home/common/agent-skills/instruction-load.json` (D9).
- `tests/test_agent_tools_launchers.py`, unchanged, under `just agent-installed-skill-tests`, together with `just build`'s import check.

## Delivery estimate and boundaries

These are estimates. About 14 changed files: two new modules (about 180 and 300 lines), one new test file (about 550 lines), one command-table row, one justfile line, about 3.5 KB of skill prose over seven skill files, one CLAUDE.md sentence, and the ceiling bumps. The change is one slice. Its review package grows mostly through the test file, and it is far from any boundary.

## Task index

Task 1 — Process seam: table, marker reader, protection, termination — python/agent_tools/launch_processes.py, tests/test_launch_scope.py, justfile — full — [task-1.md](2026-10-07-issue-276-launch-scope-exec-reap.tasks/task-1.md)
Task 2 — `launch-scope exec` with its registry row and liveness check — python/agent_tools/launch_scope.py, lib/agent-tools.nix, tests/test_launch_scope.py — full — [task-2.md](2026-10-07-issue-276-launch-scope-exec-reap.tasks/task-2.md)
Task 3 — `launch-scope reap` by `--action-id` and `--sweep` — python/agent_tools/launch_scope.py, tests/test_launch_scope.py — full — [task-3.md](2026-10-07-issue-276-launch-scope-exec-reap.tasks/task-3.md)
Task 4 — Owner exec, worker sentence and owner self-reap in the skills — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/implementer-prompt.md, home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-4.md](2026-10-07-issue-276-launch-scope-exec-reap.tasks/task-4.md)
Task 5 — Adapter sweep in the stop pass, and CLAUDE.md — home/common/claude-code/skills/orchestrate-issues/SKILL.md, CLAUDE.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-5.md](2026-10-07-issue-276-launch-scope-exec-reap.tasks/task-5.md)

## Acceptance map

| AC | Task | Check |
|----|------|-------|
| exec under a superseded launch exits 3, starts nothing, leaves no row | 2 | `ExecTest.test_a_superseded_launch_starts_nothing_and_leaves_no_row` |
| a backgrounded `sleep 300` does not outlive exec | 2 | `ExecTest.test_a_backgrounded_sleep_does_not_outlive_exec` |
| after SIGKILL of supervisor and leader, sweep kills grandchild and marked setsid escapee, unmarked sibling survives (darwin and Linux) | 3 | `ReapTest.test_a_sweep_kills_orphans_after_the_supervisor_and_leader_die`. Linux runs it in CI's advisory suite, and the darwin run is recorded in the PR |
| from-issue orders release, `reap --action-id`, exit write; orchestrate sweeps after stops; the leaf clause names `launch-scope exec` | 4, 5 | `LaunchScopeWiringContractsTest` and `LaunchScopeSweepContractsTest` under `just agent-workflow-tests`. Per D8, the lifecycle-identity sentences satisfy the "leaf clause" wording |
| `just build` import-checks the module, and the launcher test passes for the new row | 2 | `just agent-installed-skill-tests` (it builds first) |

## Decisions

Tasks rest on spec rows D1–D10 and on the plan-level rows D11 (zombie-held cleanup and the `stat` column), D12 (injectable `terminate`) and D13 (the AUTO.md worker sentence and "writes nothing to the ledger"). Each member cites the rows it uses.

---
