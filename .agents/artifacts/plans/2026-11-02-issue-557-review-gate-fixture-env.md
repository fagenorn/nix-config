# Review-Gate Capture Test Fixture Environment Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `GateTest.test_capture_refuses_output_no_real_producer_emits` resolves `artifact-budget` from the fixture's source tree, so it passes on a hosted runner with no installed helper (issue 557).

**Architecture:** One test changes. Its in-process `describe('review-package')` and every `capture` call run inside one `patch.dict(os.environ, self.env, clear=True)` block, as the other in-process review tests already do (D1, D2). The block opens with a positive control: the unmutated producer bytes pass `capture` under the same authority, so each refusal case is refused for its own mutation (D3).

**Tech stack:** Python 3 standard library (`unittest`, `unittest.mock.patch`), the source `artifact-budget` launcher, Just.

Spec: `.agents/artifacts/specs/2026-11-02-issue-557-review-gate-fixture-env-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/557.

## Global Constraints

- Base `763d8d48` (`origin/main`), spec commit `d191db65`.
- `tests/test_review_gate.py` is the only product file that changes. `python/agent_tools/review_budget.py`, `python/agent_tools/review_gate.py`, `.github/workflows/ci.yaml`, `justfile` and every other test are left as they are (D1, spec § Out of scope).
- Commits go through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. They are SSH-signed, use the subject form `test(issue-557): …`, say "issue 557" and never `#557`, and end with the session's `Co-Authored-By` trailer.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under `launch-scope scratch`. Never run `just switch`, and never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` (timeout 3600 s each) once, on the final head.

## Test seams

The spec's § Test seams. Implementers test only at these.

1. The existing test, at the in-process `describe`/`capture` API, under `SourceProjectionFixture`'s `self.env` (D2). No new test, helper or fixture.
2. The hosted-runner stand-in: the same test run with every `PATH` directory that holds `artifact-budget` removed. Task 1 defines the exact prefix.

## Delivery estimate and boundaries

- `all` (Task 1) is the only boundary: one test file in one review package, with nothing to split.

## Task index

Task 1 — The capture test runs under the fixture's budget authority — `tests/test_review_gate.py` — low-risk — [task-1.md](2026-11-02-issue-557-review-gate-fixture-env.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_review_gate.py::GateTest::test_capture_refuses_output_no_real_producer_emits`. Locally it runs under Task 1's no-installed-`PATH` stand-in, red before the change and green after it. Its authoritative reading is the PR's hosted Agent Workflow Tests (advisory) summary (D4). |
| AC2 | code | Task 1 | The Agent Workflow Tests (advisory) summary on the first push run to `main` after the merge reports `failed=0`. The ship phase reads it after the merge, and it is not a pre-merge check (D4). |

## Decisions

Per D1 (only the test changes), D2 (one environment block around `describe` and every `capture`), D3 (positive control) and D4 (where each criterion is read). Planning added no ledger row.

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base `763d8d48`, no focus, no fallback. Accepted 1 (should-fix PR-001: the stand-in prefix now prints `$PATH` with a trailing newline so `read` keeps the last directory), rejected 0, deferred 0. No ledger row: a verification-command fix, not a decision.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"022c330e68e5603b0134f5b5105b1c9f59e9903e","kind":"git-range-ownership/v1","process_ranges":[{"base":"763d8d48570c747ad368d0849939328ad12b49ed","boundaries":["all"],"head":"5fd51f34df36339d9f4243b1b6841f845aa1bae2"}],"tree":"70461014650bd21221b93d8facbd6f7c588d60ab"},"boundaries":[{"acceptance":"Issue 557 complete: the capture test green under the no-installed-PATH stand-in, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64],"process_forecast_ids":["s","p","t1"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-557-review-gate-fixture-env.md","spec":".agents/artifacts/specs/2026-11-02-issue-557-review-gate-fixture-env-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-557-review-gate-fixture-env.tasks/task-1.md"]},"tasks":[1]}],"delivery_base":"763d8d48570c747ad368d0849939328ad12b49ed","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":1,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-557-review-gate-fixture-env-design.md"},{"bounds":[{"added_lines":100,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":1,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-557-review-gate-fixture-env.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":1,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-557-review-gate-fixture-env.tasks/task-1.md"}],"proposed_boundary":"all","schema_version":3}
```
