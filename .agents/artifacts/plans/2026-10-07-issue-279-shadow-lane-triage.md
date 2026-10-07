# Shadow Lane Triage Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `resolve-project` accepts an optional `bindings.workflow.light_lane`, a new read-only `lane-triage evaluate` command turns an owner's triage record into a `light`/`full` verdict, and `from-issue` Phase 0 records that verdict while every attempt still runs full (#279, slice 1 of the light-lane parent design).

**Architecture:** Task 1 adds the public `resolve_project.resolve()` seam (the exact composition `command_resolve` runs today) and the optional `light_lane` member to `validate_workflow`. Task 2 adds the `agent_tools.lane_triage` module, its command-table row and its subprocess tests; it reads policy only through `resolve()`. Task 3 wires the triage step into `from-issue` Phase 0 and Phase 2, the investigation note, `AUTO.md`'s Phase-0 summary bullet and `CLAUDE.md`, raises the instruction-load ceilings that grow, and runs the final gate. Spec: `.agents/artifacts/specs/2026-10-07-issue-279-shadow-lane-triage-design.md` (ledger D1–D9). Its sections **Decisions** (Resolver API, Policy member, `lane-triage` input, behavior and output, Refusals, `from-issue` Phase 0) and **Test seams** are normative. Parent (read-only): `.agents/artifacts/specs/2026-10-06-light-lane-budgets-design.md` (D2, D3, D7, D13).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `fnmatch`), `unittest`, Markdown skill text, Nix command table.

## Global Constraints

- Standard library only, no new dependency.
- `.agents/project.json` is not edited: this repository authors no `light_lane` in this slice (D3). The platform manifest, `project_schema_versions`, `conformance_checks`, the lifecycle guard, the Claude permission allowlist and `COMMAND_VOCABULARY` in `test_shell_example_contracts.py` are unchanged (D2, D9).
- `lane-triage` writes no file. Every refusal exits 2 with empty stdout and exactly one compact, sorted JSON line on stderr, `{"error":{"code":...,"detail":...}}`, with `code` in `invalid_input`, `resolver_refused`, `light_lane_unsupported` (D5).
- Strict JSON loads use `agent_tools.canonical.reject_duplicate_keys` and `reject_nonfinite_literal` (agent-helpers rule 4). Command modules are thin shells (rule 2). Tests run commands as `python -m agent_tools.<module>` (rule 5).
- Every attempt runs full whatever the verdict says; the verdict is recorded, never acted on (D7).
- Run every test command from the worktree root, in the foreground, with `PYTHONPATH="$PWD/python"` and a timeout of at least 600 s.
- The final gate runs once, in Task 3's last step: `just build` and `just agent-workflow-tests`, each with a timeout of at least 2400 s (3600 s recommended).

## Test seams

- `home/common/agent-skills/tests/test_resolve_project.py`: subprocess `resolve` on `make_project_root` temp roots under a temp `HOME` (`ResolverTestCase`), plus in-process `resolve_project.resolve()` with `HOME` patched.
- New `tests/test_lane_triage.py`: `python -m agent_tools.lane_triage` subprocess runs against a copy of `home/common/agent-skills/evals/fixture-repo` under a temp `HOME` holding the committed `platform-manifest.json`. It imports nothing from another test directory.
- `tests/test_agent_tools_launchers.py` `LAUNCHER_FLOOR` (exercised by `just agent-installed-skill-tests`) and `just build`'s import check.
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` phrase-order tests over `normalized()` text, and `home/common/agent-skills/tests/test_instruction_load.py` ceilings over `home/common/agent-skills/instruction-load.json`.

## Delivery estimate and boundaries

Estimates only. About 12 changed files: about 60 lines in `resolve_project.py`, about 170 lines for `lane_triage.py`, about 350 test lines, about 2 KB of skill prose over three `from-issue` files, one `CLAUDE.md` sentence, one command-table row, one justfile line and the ceiling bumps. One slice, far from any review-package boundary.

## Task index

Task 1 — Public `resolve()` and the optional `light_lane` member — python/agent_tools/resolve_project.py, home/common/agent-skills/tests/test_resolve_project.py — full — [task-1.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-1.md)
Task 2 — `lane-triage evaluate` command — python/agent_tools/lane_triage.py, tests/test_lane_triage.py, lib/agent-tools.nix, tests/test_agent_tools_launchers.py, justfile — full — [task-2.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-2.md)
Task 3 — `from-issue` Phase 0 triage step, docs and final gate — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/investigate.md, home/common/agent-skills/skills/from-issue/AUTO.md, CLAUDE.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-3.md](2026-10-07-issue-279-shadow-lane-triage.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_resolve_project.py::LightLaneTest` (valid round-trip, absent stays absent, `null` stays `null`, each refusal) |
| AC2 | code | Task 2 | `tests/test_lane_triage.py::LaneTriageVerdictTest` (`test_an_all_no_record_is_light`, `test_each_hit_or_doubt_is_full_and_named`, `test_a_path_matching_a_glob_adds_risk_path`) |
| AC3 | code | Task 2 | `tests/test_lane_triage.py::LaneTriageRefusalTest::test_an_absent_light_lane_is_unsupported` |
| AC4 | code | Task 3 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageContractsTest::test_phase_zero_runs_lane_triage_in_shadow`, under `just agent-workflow-tests` |

## Decisions

Tasks rest on spec rows D1–D7 and on the plan-level rows D8 (evaluation order, `--input -` only, the `resolve` signature) and D9 (the call is named as an inline span only; no vocabulary or allowlist change). Each member cites the rows it uses.

---
