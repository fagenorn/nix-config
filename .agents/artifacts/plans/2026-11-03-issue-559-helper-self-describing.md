# Self-Describing Lifecycle Helpers Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Owners produce and fix lifecycle inputs from installed material alone: `review-feasibility forecast` writes the forecast blocks, the ship-summary refusals name the failing member and rule, and no skill file points into nix-config's `python/` tree (issue 559).

**Architecture:** The budget authority relays `artifact-budget check`'s own refusal line (D12). A new module, `agent_tools.review_forecast_writer`, turns the plan bytes, the base, the spec and a planner's estimate into the canonical blocks, checks them with the gate loader's validators and writes them in place, and `review-feasibility forecast` is its thin shell (D1–D5). In `artifact_budget.py` the ship-summary and shared detail checks return named reasons (D6, D7). AC3's check is a live-tree test in `test_skill_lint.py` that finds no python-tree path in the three skill trees once three skill files stop naming it; `skill_lint.py`, an Instruction Budget gate file, stays unchanged (D8, D9, D16).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `unittest`, `subprocess`, `tempfile`), Git, the source `artifact-budget` script, Just.

Spec: `.agents/artifacts/specs/2026-11-03-issue-559-helper-self-describing-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/559.

## Global Constraints

- Base `5dfe65ef` (`origin/main`). The spec was committed at `5dde2d81`, and this plan's commit adds its D13 row.
- New helper code is an `agent_tools` module behind a thin command shell (`docs/standards/agent-helpers.md` rules 1, 2). A strict JSON load goes through `agent_tools.review_forecast.strict_json` (rule 4). Tests run commands as `python -m agent_tools.<module>` under `PYTHONPATH=python` (rule 5). Skill-text tests pin only machine-consumed text (rule 6).
- A `review-feasibility` refusal exits 2 with empty stdout and one stderr line `review-feasibility: <reason>` of at most 400 characters. An `artifact-budget validate-report` refusal exits 2 with empty stdout and one line `artifact-budget: invalid report: <reason>` (issue 472 D1). No new reason echoes an input value (D5, D13).
- Out of scope (spec § Out of scope): child boundaries; any change to forecast schema v3 or to what `project`, `gate`, `confirm` and `sdd-gate record` accept; refusals other than the ship-summary composites and the shared detail check; the `from-issue` standards-review and REVIEW-CONTRACT documents (D10); installing `python/README.md` or adding skill reference files (D9).
- No skill edit may raise the Instruction Budget: `just agent-instruction-budget` passes with no raise, and only the user applies the `instruction-budget-raise` label. `writing-plans/SKILL.md` and `sdd/SKILL.md` stay no larger than at `8d0bbc25` (the issue 227 no-growth tests).
- Commits go through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. They are SSH-signed, use the subject form `<type>(issue-559): …`, say "issue 559" and never `#559`, and end with the session's `Co-Authored-By` trailer.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under `launch-scope scratch`. Never run `just switch`, and never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` (timeout 3600 s each) once, on the final head.

## Test seams

The spec's § Test seams. Implementers test only at these.

1. The `review-feasibility` CLI over a real-Git fixture: `python -m agent_tools.review_feasibility` with `SourceProjectionFixture`'s fixture home, `PATH` and `PYTHONPATH` (`tests/test_review_feasibility.py`). Tasks 1 and 2.
2. The `artifact-budget validate-report` CLI through `run_validate` and `assert_refusal` (`home/common/agent-skills/tests/test_artifact_budget.py`). Task 3.
3. The python-tree pointer check over `dict_snapshot` fixtures (`PythonTreePointerTest`) and over the live tree (`LiveTreeTest.test_the_live_tree_names_no_python_tree_path`), both in `home/common/agent-skills/tests/test_skill_lint.py` (D16). Task 4.
4. The skill contract tests (`ProjectionCallerContractsTest` and the no-growth tests in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`) and `just agent-instruction-budget`. Task 4.

## Delivery estimate and boundaries

- `all` (Tasks 1–4) is the only boundary (D4): four sequential packages that review as one delivery.
- The blocks below are written by hand because the generator lands in Task 2. Each task record is a conservative whole-record size at 10 lines of context rather than D2's rule, since `python/README.md`'s paragraph-long lines put its hunk near 16 KB where D2 gives about 3 KB. The process records follow D3.

## Task index

Task 1 — Budget check relays the checker's reason — `python/agent_tools/review_budget.py`, `python/README.md`, `tests/test_review_feasibility.py` — full — [task-1.md](2026-11-03-issue-559-helper-self-describing.tasks/task-1.md)
Task 2 — `review-feasibility forecast` writes the forecast blocks — `python/agent_tools/review_forecast_writer.py`, `python/agent_tools/review_feasibility.py`, `python/README.md`, `tests/test_review_feasibility.py` — full — [task-2.md](2026-11-03-issue-559-helper-self-describing.tasks/task-2.md)
Task 3 — Ship-summary and SDD detail refusals name the member and rule — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-3.md](2026-11-03-issue-559-helper-self-describing.tasks/task-3.md)
Task 4 — Python-tree pointer check and skill text without python-tree pointers — `home/common/agent-skills/tests/test_skill_lint.py`, `home/common/agent-skills/skills/writing-plans/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/retro/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-11-03-issue-559-helper-self-describing.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `tests/test_review_feasibility.py::ForecastGeneratorTest::test_generated_blocks_pass_the_gate_and_a_rerun_writes_nothing`: `forecast` on a two-task fixture (task 1 adds a file and modifies a base file, task 2 modifies task 1's file and deletes a base file), a commit, then `gate --completed-through 0` exits 0 with `state` `complete` (D4). |
| AC2 | code | Task 3 | `home/common/agent-skills/tests/test_artifact_budget.py::ArtifactBudgetCliTest::test_ship_summary_refusals_name_the_member_and_rule`: every ship-summary rule on the v1 and v2 `ship-summary` boundaries, including the over-long `notes` row that asserts `notes` and the policy bound (D7). |
| AC3 | code | Task 4 | `home/common/agent-skills/tests/test_skill_lint.py::LiveTreeTest::test_the_live_tree_names_no_python_tree_path`, over every `.md` file of the three skill trees; `PythonTreePointerTest::test_a_path_into_the_python_tree_is_found_in_any_markdown_file` shows the check can fail (D8, D16). |
| AC4 | evidence | Task 4 | Post-merge (D11): over the next 10 orchestrated issues in any project, owner Bash calls matching `nix/store\|agent_tools\|\.agents/lib/python` are at most 1 per issue (baseline about 3.8 per owner transcript). Measured per issue, read-only, summed over its owner transcripts: `jq -r 'select(.type=="assistant") \| .message.content[]? \| select(.type=="tool_use" and .name=="Bash") \| .input.command' <owner-transcript.jsonl> \| grep -cE 'nix/store\|agent_tools\|\.agents/lib/python'`. Acceptance-record row `AC4` stays `unverified` at merge, and ship's acceptance handling holds or closes the issue. |

## Decisions

Per D1–D5 (the generator's input, rule, blocks and writing), D6 and D7 (refusal breadth and AC2's table), D8 and D9 (AC3's tree coverage, no relocated document), D10 (Phase-5 documents unchanged), D11 (AC4 is post-merge) and D12 (the budget reason relay). Planning appended D13: the relay text, key-set refusals that echo no key, and the L6 key. Execution appended D16: AC3's check moved from a skill-lint rule L6 into `test_skill_lint.py`, leaving `skill_lint.py` unchanged.

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, isolated read-only, no fallback), base `5dfe65ef`, plan head `7b7abbff`, no focus. Accepted 4, rejected 0, deferred 0: B1 gives AC4 a read-only measurement command; B2 shortens the Task 2 and Task 4 subjects to the 64-byte forecast; S1 keeps test exit codes through `pipefail`; S2 limits Task 2's no-change guarantee to validation refusals (D14). One discussion note recorded no defect.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"cebb1eef4b418e053af22f5120f2671fec81d317","kind":"git-range-ownership/v1","process_ranges":[{"base":"5dfe65efbae09024aaf259d5a013d5658eeec0a0","boundaries":["all"],"head":"adcd766afdcd524463e445b0f055d51d6feab590"},{"base":"f813f5150b17c1afd457f3ffa6b49d7932ef3bdc","boundaries":["all"],"head":"0fc1d735392c9e25d69e04da51571b2230b4b749"},{"base":"147e4e8101750a79d7abd8048c4102060d183729","boundaries":["all"],"head":"11e0ba5a606674ac1aeda6b0689c80f08a7e4fdf"},{"base":"924028a61a5dc3c6125d5ab32840b0aa3906daaf","boundaries":["all"],"head":"cd9b10e260f615ec191c52e6395c338f520cc064"}],"tree":"df15adf71190dbc28721b005a88b915eaf4ad54a"},"boundaries":[{"acceptance":"Issue 559 complete: Tasks 1-4 green, just agent-workflow-tests and just build pass, AC4 pending post-merge evidence","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.md","spec":".agents/artifacts/specs/2026-11-03-issue-559-helper-self-describing-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-2.md",".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-3.md",".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-4.md"]},"tasks":[1,2,3,4]}],"delivery_base":"5dfe65efbae09024aaf259d5a013d5658eeec0a0","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":366,"boundary":"all","deleted_lines":0,"record_bytes":31838,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":4,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-559-helper-self-describing-design.md"},{"bounds":[{"added_lines":145,"boundary":"all","deleted_lines":0,"record_bytes":18707,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.md"},{"bounds":[{"added_lines":152,"boundary":"all","deleted_lines":0,"record_bytes":14576,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-1.md"},{"bounds":[{"added_lines":348,"boundary":"all","deleted_lines":0,"record_bytes":38824,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-2.md"},{"bounds":[{"added_lines":237,"boundary":"all","deleted_lines":0,"record_bytes":21878,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-3.md"},{"bounds":[{"added_lines":212,"boundary":"all","deleted_lines":0,"record_bytes":20423,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-559-helper-self-describing.tasks/task-4.md"}],"proposed_boundary":"all","schema_version":3}
```
