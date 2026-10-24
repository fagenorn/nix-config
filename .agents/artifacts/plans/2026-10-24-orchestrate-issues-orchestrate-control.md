# orchestrate-issues through `orchestrate-control` Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The Claude `orchestrate-issues` skill drives every run through `orchestrate-control start` and one `orchestrate-control step` per event, and the admission replay, the evals, the permission surface and the living documents follow, so no orchestrator hand-builds a control round again.

**Architecture:** The skill keeps only the host-bound duties (launches, notification rules (a)–(d), liveness, the stop pass, wait observers, the final report) and hands every lifecycle fact and control round to the helper #403 shipped, whose contract is `python/README.md` § `orchestrate-control`. `orchestrate-control` joins the whole-allowed lifecycle helpers so the heredoc-fed `step` example is a vetted call. The admission replay drives the real command from source in `tests/orchestrate_world.py`'s hermetic world.

**Tech stack:** Markdown skill text under the shell-example and skill-contract suites, Python 3 `unittest`, Nix (`home/common/claude-code/default.nix` settings), `jq`-graded skill evals (`run-eval.sh`).

Spec: `.agents/artifacts/specs/2026-10-24-orchestrate-issues-orchestrate-control-design.md`; its `## Decision ledger` rows are cited by ID, D13–D14 appended by this plan. Issue: https://github.com/fagenorn/nix-config/issues/404

## Global Constraints

- Base: `648f833c` (`origin/main` at planning). Tasks land in index order; Task 2 needs Task 1's allow entry, Task 3 needs nothing earlier, Task 4 runs the evals against Tasks 1–2.
- Files this plan changes, and no others: `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/skills/from-issue/acquire-durable.md`, `home/common/agent-skills/README.md`, `python/README.md`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/tests/test_admission_replay.py`, `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`, `home/common/agent-skills/evals/results/results.jsonl` (appended by the eval run), and the acceptance record `.agents/artifacts/plans/2026-10-24-orchestrate-issues-orchestrate-control.acceptance.md`.
- Unchanged: `python/agent_tools/orchestrate_control.py` (a defect that blocks the replay is fixed minimally and logged as a new ledger row; the planning dry run met none), `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py`, `home/common/agent-skills/tests/fixtures/admission-replay/baseline.json`, the Codex stub `home/common/codex/skills/orchestrate-issues/SKILL.md`, the guard source `home/common/claude-code/lifecycle_guard.py`.
- No instruction ceiling rises and no `--raise-label` run; only the user applies `instruction-budget-raise` (D9, D13).
- `docs/standards/agent-helpers.md` rule 5 (commands run from source as `python -m agent_tools.<module>`) and rule 6 (skill-text tests pin only argv, lifecycle key sets and other machine-consumed text; no new English-phrase pins).
- The owner dispatch envelope block, the `agent-dispatch` marker, the `Agent(...)` line and the whole blockquote prompt of the skill stay byte-identical (D7).
- Prose that lands in the repository describes the code as it behaves at that task's commit.
- Every long command, each test run included, runs in the foreground from the worktree root with an explicit timeout above its duration. A worker whose brief carries a `Lifecycle worker:` line runs it as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, creates scratch only under `launch-scope scratch …`, and commits through `launch-commit … -- <git commit args>`; commits are signed and end with the session's trailers.
- Focused tests: `env PYTHONPATH="$PWD/python" python3 -m unittest <files> [-k <pattern>]` (timeout 900 s). `just build`: timeout 3600 s.
- Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each; the suite took about 34 minutes at planning).

## Test seams

- Command seam, unchanged: `tests/test_orchestrate_control.py` already pins every behaviour the skill stops describing (D4).
- Replay seam (AC2): `home/common/agent-skills/tests/test_admission_replay.py` runs `python -m agent_tools.orchestrate_control` in `tests.orchestrate_world.OrchestrateWorld` with the source `workflow-state` (D6, D14).
- Skill-text seam (AC1): `test_shell_example_contracts.py`, `test_dispatch_contracts.py`, `test_workflow_skill_contracts.py` (D4, D14), `test_eval_cases.py`, `test_skill_lint.py` under `just agent-workflow-tests`; `tests/test_claude_permission_guard.py` against the built settings for the allow tuple (D5).
- Budget gate (AC3): `just agent-instruction-budget`, and `test_instruction_load.LiveBudgetTest` inside the suite (D13).
- Eval suite (AC4): `home/common/agent-skills/evals/run-eval.sh orchestrate-issues <id>` with `EVAL_TREE` and `EVAL_SETTINGS` (D10, D14).
- Post-merge evidence (AC5): per D11.

## Delivery estimate and boundaries

Estimates: 14 changed files. The skill shrinks from 27513 to about 20470 bytes; the replay rewrite changes about 300 lines; the contract and shell-example tests about 70; the guard test, `default.nix`, the READMEs, `acquire-durable.md`, `instruction-load.json` and `evals.json` a few lines each; one appended results line and a new acceptance record. One review package is expected to fit. Task 1 is deliverable alone; Task 2 folds the living documents and the lowered ceiling into the skill change so no commit leaves a stale citation or a loose ceiling (D8, D13).

## Task index

Task 1 — Whole-allow `orchestrate-control` — `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `tests/test_claude_permission_guard.py` — full — [task-1.md](2026-10-24-orchestrate-issues-orchestrate-control.tasks/task-1.md)
Task 2 — Drive the skill through `start` and `step` — `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/skills/from-issue/acquire-durable.md`, `home/common/agent-skills/README.md`, `python/README.md`, `home/common/agent-skills/instruction-load.json` — full — [task-2.md](2026-10-24-orchestrate-issues-orchestrate-control.tasks/task-2.md)
Task 3 — Admission replay through `orchestrate-control` — `home/common/agent-skills/tests/test_admission_replay.py` — full — [task-3.md](2026-10-24-orchestrate-issues-orchestrate-control.tasks/task-3.md)
Task 4 — Evals expect `start` and `step`, and one eval-suite run — `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`, `home/common/agent-skills/evals/results/results.jsonl`, `.agents/artifacts/plans/2026-10-24-orchestrate-issues-orchestrate-control.acceptance.md` — full — [task-4.md](2026-10-24-orchestrate-issues-orchestrate-control.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `test_shell_example_contracts.py` (`SourceTreeSweepTest` over the skill's `start` and `step` examples; Task 1's `LifecycleHelperCallTest` `orchestrate step` row), `test_dispatch_contracts.py`, `test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_dispatcher_calls_no_retired_lifecycle_command` and `::test_orchestrate_documents_carry_their_machine_text`, `test_skill_lint.py`, all under `just agent-workflow-tests` |
| AC2 | code | Task 3 | `home/common/agent-skills/tests/test_admission_replay.py`, five tests, with `baseline.json` unchanged and the logged `workflow-state control` calls equal to the summed `control_calls` |
| AC3 | code | Task 2 | `just agent-instruction-budget` (the `Instruction Budget` job's check against `origin/main`, no `--raise-label`) prints `check: pass`; `test_instruction_load.LiveBudgetTest` under `just agent-workflow-tests` |
| AC4 | code | Task 4 | `evals.json` cases 1–3 and 7 with `test_eval_cases.py` and `test_live_evals_grade_strict_policy_and_direct_review`; `run-eval.sh orchestrate-issues 7` under `EVAL_TREE` prints `VERDICT: PASS (4/4 asserts)`, cited in acceptance row `AC4` |
| AC5 | evidence | Task 4 | After `just switch` of the merged `main`, the next `/orchestrate-issues` run of ≥ 3 issues on nodocom or this repository; threshold: the orchestrator's transcript has 0 `Write` calls creating `.py`/`.sh` helpers and ≥ 1 `orchestrate-control step` call per control round. Task 4 fills row `AC5` (not measurable before merge; proxies: eval 1 and Task 3's control-call assertion); final review grades it `human_pending` (D11) |

## Decisions

- Adapter state, the step protocol and reading `start`/`step`: per D1, D2, D3, D12.
- Skill-text pins, kept regions and living documents: per D4, D7, D8; the extra absence pin and the dead key sets: per D14 (appended).
- Permission surface and the vetted heredoc: per D5; its red test: per D14.
- Budget: per D9, refined by D13 (appended): the skill task lowers only the gate-reported loose ceiling.
- Replay world, clock and accounting: per D6, D12, D14. Evals and their one run: per D10, D14. AC5: per D11, refined by D15 (Phase 5).

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, model gpt-6-astra, effort xhigh), isolated read-only mode, no focus; no fallback.
- Base SHA: 648f833c4d3e1f29279988866c5b0cac623b07a1; reviewed plan commit 869c6114.
- Findings: 0 blocking, 2 should-fix, discussion only notes. Accepted 2, rejected 0, deferred 0.
  - PR404-01 (accepted): Task 4 Step 5 runs the build and the eval script as two foreground commands, each within the 3600 s Bash ceiling.
  - PR404-02 (accepted, narrowed): plan-only evals 1–3 are recorded as printed, not graded, and are no longer an AC5 proxy (D15); running them live was weighed and declined.
- Discussion: the issue body was unreadable from the reviewer sandbox (acceptance criteria were supplied); the reviewer found no D11 row in the prior #403 design spec that the issue quotes; that citation is left unresolved and does not change this plan.
