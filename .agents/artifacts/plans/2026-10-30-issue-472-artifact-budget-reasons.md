# Artifact-Budget Refusal Reasons and Over-Budget Overages Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every `artifact-budget` refusal adds a reason that names the failing member or bound to its one stderr line. Every `check` result reports, for each violated dimension, the limit and how far over it the artifact is. Existing consumers of `violations` keep parsing it.

**Architecture:** One writer, `_refuse`, renders every refusal as `artifact-budget: <class>: <reason>` (D1, D2). Each validator raises a message that names what failed, through a shared members check, a shared notes check, the producer's artifact-fault check and the finding index (D3, D4). `check` derives `violations` and a new `overages` member from one bounds table (D6, D7). The review budget authority, the only strict consumer, pins `overages` in the same commit (D8).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `os`, `unittest`), the flat script `home/common/agent-skills/scripts/artifact_budget.py`, the `agent_tools` package, Just and Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-30-issue-472-artifact-budget-reasons-design.md` (spec commit `2d0791d2`). A bare "Dn" cites the spec's `## Decision ledger`. This plan appends D12–D14. Issue: https://github.com/fagenorn/nix-config/issues/472.

## Global Constraints

- Base `8212d8fb` (`origin/main`, the merge of issue 467). Tasks land in index order, each on top of the one before.
- These stay unchanged (spec § Out of scope; D4, D7, D9, D11): exit codes (0 within budget, 3 over budget, 2 refusal); the stdout of a successful validation; `describe` output; producer-report schemas; `home/common/agent-skills/artifact-budget-policy.json`; `home/common/agent-skills/scripts/delivery_model/`; `home/common/agent-skills/scripts/workflow-state.py`; `python/agent_tools/review_publish.py`; `BudgetCheck`; `interface_version` 1; every skill, README and doc file.
- Every validator accepts and refuses exactly the inputs it does at base. Only the reason changes. The existing matrix tests keep their inputs and expectations, and only their stderr assertion moves to `assert_refusal`.
- The refusal line is exactly `artifact-budget: <class>: <reason>\n`. `<class>` is `invalid report`, `cannot read report`, `invalid detail input`, `cannot read detail input` or `invalid input`, and stdout stays empty (D1).
- A reason names members by wire path (`notes`, `artifact.kind`, `findings[2].ruling`) and bounds by value. It quotes input-supplied member names with `json.dumps` (ASCII-escaped). It never contains a value from the report or the detail input, or a path the CLI opened (D2, D12).
- Comments and docstrings describe the code as it behaves at that task's commit, and cite decisions as "issue 472 Dn", never a bare `#472` or `Dn`. No `TODO` or `FIXME`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Make scratch directories only under the path `launch-scope scratch` prints.
- Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed (never disable signing) and end with the session's trailer lines. Never run `just switch`, and never push.
- **Unit run** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest -v <test file> [-k <pattern>]... 2>&1 | tail -12'`. At base, `home/common/agent-skills/tests/test_artifact_budget.py` runs 46 tests in about 37 s.
- **Build** (timeout 1800 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`. Task 3 runs it, because it changes the `agent_tools` package.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests`, with a timeout of 3600 s each.

## Test seams

Per the spec's § Test seams (D10, D14):

- **CLI.** `home/common/agent-skills/tests/test_artifact_budget.py` runs the script as a subprocess through `run_validate`, `run_check` and direct `subprocess.run` calls. A new shared `assert_refusal` pins the refusal line. The in-process exceptions are named in D12.
- **Descriptors.** `tests/fixtures/artifact-budgets/{small,oversized}-issue.json` carry `expected.overages`.
- **Consumer.** The `tests/test_sdd_gate.py` budget shim fakes the check's wire form. The sdd-gate `decompose_required` case and `tests/test_review_feasibility.py::SequentialCandidateTest::test_owned_candidate_matches_independent_actual_range` send the real checker's over-budget result through the review budget authority.
- **Relay.** `tests/test_agent_tools_launchers.py` asserts the substring `artifact-budget exited 2: artifact-budget: invalid report` in the installed tier. It keeps passing unchanged because the class prefix holds (D1). No task edits or runs it.

## Delivery estimate and boundaries

All figures are estimates: 6 changed files plus this package and the spec ledger, about +430/−130 lines.

- `artifact_budget.py`: Task 1 about +45/−25, Task 2 about +110/−55, Task 3 about +25/−15.
- `test_artifact_budget.py`: Task 1 about +90/−35, Task 2 about +120, Task 3 about +30/−5.
- The two descriptor fixtures: about +12/−0. `review_budget.py`: about +10/−2. `tests/test_sdd_gate.py`: about +40/−12.

The change fits one review package. Tasks 1 and 3 could each ship alone. Task 2 needs Task 1's writer, because without it no reason reaches stderr.

## Task index

Task 1 — The refusal line — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-1.md](2026-10-30-issue-472-artifact-budget-reasons.tasks/task-1.md)

Task 2 — Validator reasons that name the member or bound — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-2.md](2026-10-30-issue-472-artifact-budget-reasons.tasks/task-2.md)

Task 3 — Over-budget overages and the strict consumer — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json`, `home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json`, `python/agent_tools/review_budget.py`, `tests/test_sdd_gate.py` — full — [task-3.md](2026-10-30-issue-472-artifact-budget-reasons.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_artifact_budget.py::ArtifactBudgetCliTest::test_a_producer_refusal_names_its_member_or_bound` |
| AC2 | code | Task 2 | `home/common/agent-skills/tests/test_artifact_budget.py::ArtifactBudgetCliTest::test_a_detail_refusal_names_the_failing_finding_member` |
| AC3 | code | Task 3 | `home/common/agent-skills/tests/test_artifact_budget.py::ArtifactBudgetCliTest::test_an_over_budget_check_reports_limit_and_overage` and `::test_repository_descriptors_drive_cli_results`, with the existing `violations` consumers `tests/test_sdd_gate.py::ReviewTest::test_a_decompose_required_report_is_refused_at_validate_report`, `::test_an_over_budget_package_is_refused_at_budget_check` and `tests/test_review_feasibility.py::SequentialCandidateTest::test_owned_candidate_matches_independent_actual_range` |
| AC4 | code | Task 3 | `just agent-workflow-tests` exits 0 on the final head, run by sdd's final gate after Task 3 |

## Decisions

- Task 1 follows D1, D2, D5 and D13. Task 2 follows D2, D3, D4 and D12. Task 3 follows D6, D7, D8 and D14. D10 shapes every task's tests, and D9 and D11 keep every task out of the wrappers, the package move and the docs.
- Planning appended D12–D14 to the spec's ledger.
- All three tasks are in the full lane. Task 1 changes the refusal wire line that relays match. Task 2 rewrites the checks at public report boundaries, whose accept and refuse sets must not move. Task 3 changes the check result's public contract.
- Planning trials on 2026-10-30 at base: the test file is green, with 46 tests in about 37 s. The sdd-gate over-budget and decompose cases are green in about 17 s. The review-feasibility full-range case is green in about 58 s. A scratch probe, never committed, ran a shim built from one dict three times in one sdd-gate case, and each run reached `budget-check`.

---
