# Measured Owner Rollover Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A `PreToolUse` hook, the context meter, rewrites every `workflow-state progress` call to carry the calling agent's measured context, the phase-budget default drops to 120,000 with 10,000 headroom in one home, and an owner crossing 110,000 is told once, mid-phase, to run its gate.

**Architecture:** A new `agent_tools` command, `context-meter`, is a thin shell plus three policy modules: transcript reading, command lexing and rewriting, and per-agent crossing state (D14). It is registered as a second command hook beside the fail-closed lifecycle guard and grants nothing (D1, D3). A new `agent_tools.phase_budget` module holds the four defaults that `workflow-state progress` and the meter both read (D7). The eval runner starts keeping sessions so the meter and `agent-costs` can read eval transcripts (D13), and the evidence is gathered from a tree-mode eval with no switch (D12, D16).

**Tech stack:** Python 3.13 standard library (`json`, `fcntl`, `re`, `pathlib`, `argparse`), `unittest` driving `python -m agent_tools.<module>` from source, Bash (the eval runner and its test), Nix (`lib/agent-tools.nix` command table, `home/common/claude-code/default.nix` settings), Just.

Spec: `.agents/artifacts/specs/2026-10-25-issue-424-measured-owner-rollover-design.md` (spec commit `2fb3e7f9`; this plan appends ledger rows D13–D16). Issue: https://github.com/fagenorn/nix-config/issues/424.

## Global Constraints

- Base `04a39660` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- Python standard library only. `home/common/claude-code/lifecycle_guard.py` is not edited, and the guard's registration (path, timeout 30, no args) is unchanged (D1).
- `select_phase_action`, the `handoff`/`delegate`/resume-pack paths, the turn defaults' values (120, 2) and `agent_costs` are unchanged (spec § Out of scope).
- The meter never exits 2 and never prints `permissionDecision`, `decision` or `continue` (D3, D6).
- `docs/standards/agent-helpers.md` rules 1–3 and 5–6 bind every new module and test: parser `prog` is the command name, no `sys.path` edit, `importlib` load or `__file__` lookup in package code, tests run `python -m agent_tools.<module>`, and skill-text tests pin only argv.
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit; write "issue 424", never a bare `#424`, in code and docs; no `TODO` or `FIXME`; no mutable default argument.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, ending with the session's two trailer lines. Scratch files live under the root `launch-scope scratch` prints. Never run `just switch`.
- **Meter tests** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_context_meter.py 2>&1 | tail -4'`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- **Guard suite** (timeout 1800 s), after a build:

  ```bash
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

- Final gate (sdd, once on the final head): `just build`, `just agent-workflow-tests` (timeout 3600 s each), the guard suite and `just agent-instruction-budget`, each passing.

## Test seams

- The meter command (spec seam 1): `python -m agent_tools.context_meter` with a `PreToolUse` payload on stdin, fixture transcripts under a temp projects dir, `HOME` at a temp dir; assertions on stdout JSON and exit code, plus the state file's lock for the parallel-call invariant (D9).
- The rewrite proof as a function, `context_meter_commands.proved`, on a tampered rewrite: the one seam below the command, because no command reaches its refusal (D14).
- `workflow-state progress` through the existing `progress` helper with the ceiling flags omitted (spec seam 2), and its parser through `build_parser()` on the loaded script for the defaults' one home and the spellings the meter removes (D15).
- Skill text (spec seam 3): `test_workflow_skill_contracts.py`, a negative argv assertion.
- Settings and guard (spec seam 4): `tests/test_claude_permission_guard.py` against the built settings; the launcher floor in `tests/test_agent_tools_launchers.py` against the built home.
- The eval runner: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`'s fake `claude`, which records its argv and environment (D13).
- Instruction Budget (spec seam 5) and the mbp evidence run (spec seam 6, D16).

## Delivery estimate and boundaries

Estimates only: about 23 changed files (the eval results row included) plus the acceptance record. New: `context_meter.py` (~130 lines), `context_meter_transcript.py` (~110), `context_meter_commands.py` (~200), `context_meter_crossing.py` (~90), `phase_budget.py` (~15), `tests/test_context_meter.py` (~520). Edits of a few lines to ~40 lines each elsewhere; the two READMEs gain one section each. The skill text shrinks. One review package is likely; if a boundary demands a split, Task 2 (defaults and skill text) and Task 5 (eval runner) are each independently deliverable, and Tasks 1, 3 and 4 form the meter slice.

## Task index

Task 1 — The meter command: measured `--context-tokens` on every progress call — `python/agent_tools/context_meter.py`, `python/agent_tools/context_meter_transcript.py`, `python/agent_tools/context_meter_commands.py`, `tests/test_context_meter.py`, `justfile` — full — [task-1.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-1.md)
Task 2 — One home for the phase budget, and skill text that stops restating it — `python/agent_tools/phase_budget.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/rollover.md`, `home/common/agent-skills/skills/from-issue/delegated-owner.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-2.md)
Task 3 — Owners and the once-per-crossing instruction — `python/agent_tools/context_meter_crossing.py`, `python/agent_tools/context_meter_commands.py`, `python/agent_tools/context_meter.py`, `python/agent_tools/phase_budget.py`, `tests/test_context_meter.py` — full — [task-3.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-3.md)
Task 4 — Registration beside the guard, the command row and the contract docs — `lib/agent-tools.nix`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `tests/test_agent_tools_launchers.py`, `home/common/claude-code/README.md`, `python/README.md` — full — [task-4.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-4.md)
Task 5 — Eval runs keep their sessions — `home/common/agent-skills/evals/run-eval.sh`, `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`, `home/common/agent-skills/evals/README.md` — low-risk — [task-5.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-5.md)
Task 6 — Evidence on mbp and the acceptance record — `.agents/artifacts/plans/2026-10-25-issue-424-measured-owner-rollover.acceptance.md`, `home/common/agent-skills/evals/results/results.jsonl` — low-risk — [task-6.md](2026-10-25-issue-424-measured-owner-rollover.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_context_meter.py::ProgressRewriteTest::test_the_87412_fixture_replaces_a_missing_or_wrong_count` (no count, separate, `=`, abbreviated forms all carry exactly 87412) and `::test_other_commands_pass_through_untouched`, run by `just agent-workflow-tests`. |
| AC2 | code | Task 3 | `tests/test_context_meter.py::CrossingTest::test_105k_to_112k_injects_once_and_118k_does_not`, same recipe. |
| AC3 | code | Task 2 | `home/common/agent-skills/tests/test_workflow_state.py::PhaseBudgetDefaultsTest::test_default_ceiling_hands_off_at_110000_and_continues_at_109999` and `::test_the_four_defaults_have_one_home`, and `test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_owner_has_executable_phase_gate_and_action_semantics` (no `--context-ceiling`, `--context-headroom` or `--context-tokens` in from-issue text), same recipe. |
| AC4 | code | Task 4 | The guard suite (`tests/test_claude_permission_guard.py`) against the built settings: discovery finds exactly the guard and the meter in the one Bash entry, guard checks as before, adversarial table unchanged; prints `OK`. |
| AC5 | evidence | Task 6 | On mbp at the final code head, `EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> just evals from-issue 1`; the audit of its copied transcripts shows every `workflow-state progress` tool call joined to a meter note naming a measured value (a zero count recorded as vacuous, with the live probe, per D16), and `just agent-costs --report cache --projects-dir <copied transcripts> --days 0` plus the audit show no owner transcript peaking above 125,000. Acceptance-record row `AC5`. |
| AC6 | evidence | Task 6 | The same eval run's `VERDICT:` line reads `PASS`. Acceptance-record row `AC6`. |
| AC7 | code | Task 2 | `just agent-instruction-budget` exits 0 without `--raise-label`. |

## Decisions

- The command, its registration and its timeout per D1, D2; the decision-less rewrite per D3 (Tasks 1, 4).
- Measurement per D4 with the window of D14 (Task 1); the rewrite per D5 and the lexer and spellings per D15 (Task 1).
- Failure posture per D6 (Tasks 1, 3); module boundaries and fixed texts per D14 (Tasks 1, 3).
- Phase-budget home per D7, skill text per D11 (Task 2).
- Owners per D8 with the `--action-id` qualifier of D15; crossing state per D9; the two notes per D10 (Task 3).
- Verification and evidence per D12, D16; eval sessions kept per D13 (Tasks 4–6).

---
