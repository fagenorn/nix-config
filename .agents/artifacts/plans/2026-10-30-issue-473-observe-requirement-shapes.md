# Self-Describing Observe Requirements Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every requirement of a direct-owner `observe` reply carries a constant `expects` description of the answer it asks for, `direct-owner --help` names it, and every `workflow-state` reply a skill names passes the `workflow-response` boundary.

**Architecture:** A new pure `agent_tools.attempt_observations` module becomes the one home of the tracker, forge and worktree observation sets and of the `expects` catalogue. `workflow-state` attaches `expects` where the observe envelope is built. The delivery model's `workflow-response` validator gains a closed observe-requirement check and exact-member branches for the worker and progress replies. A contract test derives the skill-named subcommands from the skill text and drives one real reply of each through the boundary.

**Tech stack:** Python 3 standard library (`unittest`, `argparse`, `re`, `ast`), the `agent_tools` package, the flat `workflow-state` and delivery-model scripts, Markdown skill text, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-30-issue-473-observe-requirement-shapes-design.md` (spec commit `eb9d19e3`). A bare "Dn" cites the spec's `## Decision ledger`. This plan appends D10 and D11. Issue: https://github.com/fagenorn/nix-config/issues/473.

## Global Constraints

- Base `8212d8fb` (`origin/main`). Tasks land in index order, each on top of the one before.
- These stay unchanged: the `register-worker`, `release-worker` and `mark-progress` output (D6); the direct-owner request shape and `interface_version` 2 (D9); the shared requirement check that control summaries and delivery blocks use (D4); the orchestrate-control owner-observation shape (https://github.com/fagenorn/nix-config/issues/469); every validator's logic and messages, since only constants move (D3); every instruction-budget ceiling (D7).
- `agent_tools.attempt_observations` is standard-library only, does no I/O and imports nothing from the skill scripts (agent-helpers rule 3). Every catalogue string is ASCII, so canonical JSON round-trips byte for byte.
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` imports nothing from `agent_tools` or from a sibling test module, because the installed tier runs it with no `PYTHONPATH` (D11).
- Comments, docstrings, help text and README sentences describe the code as it behaves at that task's commit. Where the implemented code differs from a clause this plan dictates, rewrite the clause from the code. Write "issue 473", never a bare `#473`. No `TODO` or `FIXME`.
- Stage each new file with `git add` before any `just build`, because the flake sees tracked files only.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration.
- Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are signed (never disable signing) and end with the session's trailer lines. Never run `just switch`, and never push.
- Payload discipline: targeted `rg` over whole-file reads, bounded reads around the lines that matter, and test output cut to its tail.
- **Unit run** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest -q <test file> [-k <pattern>]... 2>&1 | tail -12'`.
- **Build** (timeout 1800 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`; it prints `check: pass`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

Per the spec's § Test seams, with D11's placement:

- **Catalogue and AC1.** `test_workflow_state.py` drives `direct-owner` from source through `LifecycleHarness.direct_owner_at_root` (raw stdout) and `validated_response`. It loads `workflow-state.py` and the contract builder from source with `load_source_module` and imports `agent_tools.attempt_observations`.
- **AC2.** `test_workflow_state.py` runs `workflow-state direct-owner --help` through `LifecycleHarness.run_cli`.
- **Validator.** `test_delivery_model.py` calls `validate_delivery_object(..., expected_kind="workflow-response")` on the delivery model loaded from source, following `OwnerLivenessResponseTest`.
- **AC3.** `test_artifact_budget.py` drives each skill-named subcommand through the real CLI (`DeliveredCustody`) and pipes its stdout through the real `artifact-budget validate-report --boundary workflow-response`.
- **Skill text.** `test_workflow_skill_contracts.py` pins the `expects` key set (read by AST) and the two exemptions, which are JSON key sets and `workflow-state` argv (agent-helpers rule 6).

## Delivery estimate and boundaries

All figures are estimates: 14 changed files (one new) plus this package and the spec ledger, about +700/−35 lines.

- `python/agent_tools/attempt_observations.py`: about +115 (new).
- `workflow-state.py`: about +15/−8. `workflow_delivery_wire.py`: about +6/−4. `delivery_model/_wire.py`: about +60/−2.
- Tests: `test_workflow_state.py` about +200; `test_delivery_model.py` about +140; `test_artifact_budget.py` about +140; `test_delivery_workflow.py`, `_delivery_model_fixtures.py`, `test_attempt_custody.py` and `test_workflow_skill_contracts.py` about +30/−20 together.
- Skill text: one line each in `acquire-direct.md` (−125 bytes) and `from-issue/SKILL.md` (−4 bytes); `home/common/agent-skills/README.md` gains about 2 paragraphs.

The change fits one review package. Tasks 1–3 ship together, since together they make `expects` real. Task 4 can ship alone after Task 2. Task 5 needs Tasks 2 and 4, because its prose describes both.

## Task index

Task 1 — Observation vocabulary and `expects` catalogue — `python/agent_tools/attempt_observations.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/scripts/workflow_delivery_wire.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-10-30-issue-473-observe-requirement-shapes.tasks/task-1.md)
Task 2 — Observe replies carry `expects` and the validator checks it — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/scripts/delivery_model/_wire.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_delivery_model.py`, `home/common/agent-skills/tests/_delivery_model_fixtures.py`, `home/common/agent-skills/tests/test_delivery_workflow.py` — full — [task-2.md](2026-10-30-issue-473-observe-requirement-shapes.tasks/task-2.md)
Task 3 — `direct-owner --help` names `expects` — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — low-risk — [task-3.md](2026-10-30-issue-473-observe-requirement-shapes.tasks/task-3.md)
Task 4 — Worker and progress replies pass the boundary, pinned by the skill-named reply contract — `home/common/agent-skills/scripts/delivery_model/_wire.py`, `home/common/agent-skills/tests/test_delivery_model.py`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/tests/test_attempt_custody.py` — full — [task-4.md](2026-10-30-issue-473-observe-requirement-shapes.tasks/task-4.md)
Task 5 — Skill text and README — `home/common/agent-skills/skills/from-issue/acquire-direct.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-5.md](2026-10-30-issue-473-observe-requirement-shapes.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_workflow_state.py::DirectObserveExpectsTest::test_every_observe_kind_is_described` |
| AC2 | code | Task 3 | `home/common/agent-skills/tests/test_workflow_state.py::DirectOwnerHelpTest::test_direct_owner_help_names_expects_and_its_members` |
| AC3 | code | Task 4 | `home/common/agent-skills/tests/test_artifact_budget.py::SkillNamedReplyTest::test_every_skill_named_reply_passes_the_workflow_response_boundary`, with `::test_the_drivers_cover_exactly_the_skill_named_replies` |
| AC4 | code | Task 5 | `just agent-workflow-tests` on the final head, run by sdd's final gate after Task 5 |

## Decisions

- Task 1 follows D3 and D10. Task 2 follows D1, D2, D4, D8, D9 and D11. Task 3 follows D1. Task 4 follows D5, D6, D8 and D11. Task 5 follows D5, D7 and D11.
- Planning appended D10 and D11 to the spec's ledger.
- Lanes: every task but Task 3 changes a lifecycle wire contract, its validator, or the skill text that states it, so it is full. Task 3 adds help text only.
- Planning trials on 2026-10-30 ran from a scratch worktree of the base and were never committed. At the base, they showed:
  - the derived skill-named set is exactly the 14 subcommands of D5. Each Task 4 driver produces its reply. `register-worker`, `release-worker` and `mark-progress` fail the boundary and the other eleven pass;
  - each Task 2 scenario returns exactly its one requirement kind. Task 1's tracker and worktree examples pass `validate_direct_owner_request` for issue 73 and are refused for issue 74;
  - the Task 5 replacements shrink `acquire-direct.md` by 125 bytes and `SKILL.md` by 4 bytes;
  - `test_workflow_skill_contracts.py` passes with no `PYTHONPATH`.
- With every task's dictated code and text applied to that scratch tree, each task's verification passed. `just agent-workflow-tests` passed with 106 of 106 members (about 19 minutes), and `just build` passed on darwin.

---
