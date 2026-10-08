# Shadow Lane Triage Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `resolve-project` accepts an optional `bindings.workflow.light_lane`, a new read-only `lane-triage evaluate` command turns an owner's triage record into a `light`/`full` verdict, and `from-issue` Phase 0 records that verdict while every attempt still runs full (#279, slice 1 of the light-lane parent design).

**Architecture:** Task 1 adds the public `resolve_project.resolve()` seam (the exact composition `command_resolve` runs today) and the optional `light_lane` member to `validate_workflow`. Task 2 adds the `agent_tools.lane_triage` module, its command-table row and its subprocess tests; it reads policy only through `resolve()`. Task 3 wires the triage step into `from-issue` Phase 0 and Phase 2, the investigation note, `AUTO.md`'s Phase-0 summary bullet and `CLAUDE.md`. **Amendment (no-raise, 2026-10-07):** Tasks 1–3 are done. Task 3's ceiling raise (`ec089c67`) is refused. Task 4 reverts it and merges `origin/main`. Task 5 fits the from-issue text under main's ceilings and re-pins AC4 by key set (D12–D16). Task 6 re-syncs, re-checks the budget against the then-current main, and runs the final gate. Spec: `.agents/artifacts/specs/2026-10-07-issue-279-shadow-lane-triage-design.md` (ledger D1–D16). Its sections **Decisions** (Resolver API, Policy member, `lane-triage` input, behavior and output, Refusals, `from-issue` Phase 0), **Instruction budget** and **Test seams** are normative. Parent (read-only): `.agents/artifacts/specs/2026-10-06-light-lane-budgets-design.md` (D2, D3, D7, D13).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `fnmatch`), `unittest`, Markdown skill text, Nix command table.

## Global Constraints

- Standard library only, no new dependency.
- `.agents/project.json` is not edited: this repository authors no `light_lane` in this slice (D3). The platform manifest, `project_schema_versions`, `conformance_checks`, the lifecycle guard, the Claude permission allowlist and `COMMAND_VOCABULARY` in `test_shell_example_contracts.py` are unchanged (D2, D9).
- `lane-triage` writes no file. Every refusal exits 2 with empty stdout and exactly one compact, sorted JSON line on stderr, `{"error":{"code":...,"detail":...}}`, with `code` in `invalid_input`, `resolver_refused`, `light_lane_unsupported` (D5).
- Strict JSON loads use `agent_tools.canonical.reject_duplicate_keys` and `reject_nonfinite_literal` (agent-helpers rule 4). Command modules are thin shells (rule 2). Tests run commands as `python -m agent_tools.<module>` (rule 5).
- Every attempt runs full whatever the verdict says; the verdict is recorded, never acted on (D7).
- Run every test command from the worktree root, in the foreground, with `PYTHONPATH="$PWD/python"` and a timeout of at least 600 s.
- No instruction-load ceiling is raised. `home/common/agent-skills/instruction-load.json` ends byte-identical to `origin/main`'s, and `instruction_load check --base origin/main` passes with no `--raise-label` (issue AC5; D15).
- The final gate runs once, in Task 6: `just build` and `just agent-workflow-tests`, each with a timeout of at least 2400 s (3600 s recommended).

## Test seams

- `home/common/agent-skills/tests/test_resolve_project.py`: subprocess `resolve` on `make_project_root` temp roots under a temp `HOME` (`ResolverTestCase`), plus in-process `resolve_project.resolve()` with `HOME` patched.
- New `tests/test_lane_triage.py`: `python -m agent_tools.lane_triage` subprocess runs against a copy of `home/common/agent-skills/evals/fixture-repo` under a temp `HOME` holding the committed `platform-manifest.json`. It imports nothing from another test directory.
- `tests/test_agent_tools_launchers.py` `LAUNCHER_FLOOR` (exercised by `just agent-installed-skill-tests`) and `just build`'s import check.
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageRecordKeysTest`: Phase 0's backticked spans name the record keys, verdict keys and modes, read from the modules' source without importing them (D16). No phrase pins (rule 6, D14).
- `PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main`, which is the local proxy for the required `Instruction Budget` CI check.

## Delivery estimate and boundaries

Estimates only. About 12 changed files: about 60 lines in `resolve_project.py`, about 170 lines for `lane_triage.py`, about 350 test lines, about 2 KB of skill prose over three `from-issue` files, one `CLAUDE.md` sentence, one command-table row, one justfile line and the ceiling bumps. One slice, far from any review-package boundary.

**Amendment estimate.** About 5 files: the three from-issue skill files, with a summed delta of about −19 bytes against main per the probe; one test file, with about −100 net lines; and the acceptance record. There is also one revert commit and one or two merge commits.

## Task index

Task 1 — Public `resolve()` and the optional `light_lane` member — python/agent_tools/resolve_project.py, home/common/agent-skills/tests/test_resolve_project.py — full — done — [task-1.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-1.md)
Task 2 — `lane-triage evaluate` command — python/agent_tools/lane_triage.py, tests/test_lane_triage.py, lib/agent-tools.nix, tests/test_agent_tools_launchers.py, justfile — full — done — [task-2.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-2.md)
Task 3 — `from-issue` Phase 0 triage step, docs and final gate — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/investigate.md, home/common/agent-skills/skills/from-issue/AUTO.md, CLAUDE.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — done (its raise is reverted by Task 4) — [task-3.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-3.md)
Task 4 — Drop the ceiling raise and sync with `origin/main` — home/common/agent-skills/instruction-load.json (revert), merge of origin/main — full — [task-4.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-4.md)
Task 5 — Fit the from-issue text under the ceilings and re-pin AC4 — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/agent-skills/skills/from-issue/investigate.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-5.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-5.md)
Task 6 — Re-sync, budget check against current main, final gate and acceptance record — .agents/artifacts/plans/2026-10-07-issue-279-shadow-lane-triage.acceptance.md, merge of origin/main if moved — full — [task-6.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_resolve_project.py::LightLaneTest` (valid round-trip, absent stays absent, `null` stays `null`, each refusal) |
| AC2 | code | Task 2 | `tests/test_lane_triage.py::LaneTriageVerdictTest` (`test_an_all_no_record_is_light`, `test_each_hit_or_doubt_is_full_and_named`, `test_a_path_matching_a_glob_adds_risk_path`) |
| AC3 | code | Task 2 | `tests/test_lane_triage.py::LaneTriageRefusalTest::test_an_absent_light_lane_is_unsupported` |
| AC4 | code | Task 5 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageRecordKeysTest`, under `just agent-workflow-tests` (D16) |
| AC5 | code | Task 6 | The required `Instruction Budget` CI check on the PR, passing without the `instruction-budget-raise` label. Local proxy: `instruction_load check --base origin/main`, exit 0 with no `--raise-label`, re-run against the then-current main |

## Decisions

Tasks rest on spec rows D1–D7 and on the plan-level rows D8 (evaluation order, `--input -` only, the `resolve` signature) and D9 (the call is named as an inline span only; no vocabulary or allowlist change). The amendment tasks rest on D12–D15 and on the plan-level row D16, which reverses part of D14 and keeps AC4 measured by a key-set pin. Each member cites the rows it uses.

---

## Standards review provenance

Reviewer: Claude fallback (one native `reviewer`, Opus), after the configured Codex `plan-review` (`codex-companion task --fresh --reviewer plan-review`) completed with a runtime failure (job timed out after 1680 s, no payload). Base SHA 07f4f954c31a871a5144df2224d6d3152e42937b; isolated, read-only. Findings: 0 Blocking, 4 Should-fix, 1 Discussion. Accepted 5 (SF-1 → task-3 R-SF1, SF-2 → task-3 R-SF2, SF-3 → task-1 R-SF3, SF-4 → task-1 R-SF4, D-1 → task-2/task-3 R-D1), rejected 0, deferred 0. Amendments are appended to each task member (per D10).

Amendment review (tasks 4–6): reviewer Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra/xhigh), no fallback. Base SHA ef2c1cb8d6f89a0e5e6fa6335a215b419542fb17; isolated, read-only. Findings: 1 Blocking, 2 Should-fix, 0 Discussion. Accepted 3, rejected 0, deferred 0: B-001 → task-4 Step 3b restores the whole gate file from `origin/main` (per D17); SF-001 → tasks 4–6 capture each command's own exit status, no pipe or `PIPESTATUS`; SF-002 → task-6 records AC5 as `unverified` until the PR's check is green.
