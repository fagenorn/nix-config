# Attempt Identity Test-Harness Prep Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Land on `main` the behaviour-neutral half of https://github.com/fagenorn/nix-config/issues/337's test sweep (branch `worktree-issue-337-orchestrated`, commit `6ae38b0c`): shared harness helpers with today's bodies, and the existing tests routed through them, so #337's later `-U10` diff of each test file fits 60000 B (https://github.com/fagenorn/nix-config/issues/346).

**Architecture:** Two test modules only. Each task takes one helper family from `6ae38b0c` (names, signatures and routed lines copied, per D1), gives it a body that reproduces today's behaviour on `main`, and routes that family's call sites through it. The last task measures both byte budgets and replays `6ae38b0c`'s files over the head.

**Tech stack:** Python 3 standard library, `unittest`, the `workflow-state` CLI driven in-process by the existing harnesses, git 2.51 CLI.

Spec: `.agents/artifacts/specs/2026-10-10-issue-346-attempt-identity-test-harness-prep-design.md` (its `## Decisions` table of helper bodies and `## Decision ledger` rows D1–D7 are cited by ID). Reference text: `git show 6ae38b0c:<file>`; the branch's in-scope hunks are `git diff -U0 901da282 6ae38b0c -- <file>`.

## Global Constraints

- Only `home/common/agent-skills/tests/test_workflow_state.py` (WS) and `home/common/agent-skills/tests/test_delivery_workflow.py` (DW) change. Nothing under `scripts/`, `python/`, any other test, or the #337 branch.
- Never land anything on the issue's "Stays in #337" list (spec `## Out of scope`): no `attempt_identity` / `attempt_store` / `TransactionStore` import, no `ORCHESTRATED` / `TRANSACTION`, no `--creation-key`, no schema-8 literal or `transaction_id` expectation, no `identity=` / `schema_version=` argument, no `LedgerRefused`, no D14 bound-refusal assertion, no `orchestrate-<issue>-r<n>` mapping in `write_run`, no legacy-inputs/survive rename, no `LedgerClockTest.run_cli`, no `direct_state_path` index lookup, no store `copytree`.
- Main translation rule: where a routed branch line passes `--creation-key <k>`, main passes `--run-id <k>` and keeps the branch's read-back of `run_id` from the reply (D2).
- Behaviour-neutral: every product-produced id (direct ids, `init-run` replies, phase-gate replies) and every ledger byte stays as today (D3, D4); no assertion removed, loosened or skipped (D6, D7).
- Budget: each file's `git diff -U10 "$(git merge-base origin/main HEAD)" -- <file> | wc -c` ≤ 60000; D5 is the only fallback.
- Commands run from the worktree root, in the foreground under `launch-scope exec … --`. Focused tests: `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, timeout at least 1800 s.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- `LifecycleHarness` (WS) and `BuilderHarness`, `ContractLifecycleTest`, `DeliveryAdmissionTest` (DW) — the existing harness classes; no new test file, fixture module or product hook. `LedgerClockTest` (DW) inherits `LifecycleHarness`.
- D7's per-file proxy for AC2: `def test_` count equal to base, `self.assert`/`.assert_called` line count not below base, `skip` token count equal to base.

## Delivery estimate and boundaries

Estimates (issue's model): WS own `-U10` diff ~56.8 KB, DW ~50.0 KB; #337 remainder after replay WS ~36.7 KB, DW ~41.5 KB. WS has the least headroom; D5 governs its overflow. Two changed files plus plan and spec; one review package.

## Task index

Task 1 — Direct-run helpers and their call sites — `home/common/agent-skills/tests/test_workflow_state.py` — low-risk — [task-1.md](2026-10-10-issue-346-attempt-identity-test-harness-prep.tasks/task-1.md)
Task 2 — Legacy-install, init-run and finish helpers and their call sites — `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-2.md](2026-10-10-issue-346-attempt-identity-test-harness-prep.tasks/task-2.md)
Task 3 — Builder run labels and contract-lifecycle routing — `home/common/agent-skills/tests/test_delivery_workflow.py` — full — [task-3.md](2026-10-10-issue-346-attempt-identity-test-harness-prep.tasks/task-3.md)
Task 4 — Admission read-back, clock skew, budgets and #337 replay — `home/common/agent-skills/tests/test_delivery_workflow.py` — full — [task-4.md](2026-10-10-issue-346-attempt-identity-test-harness-prep.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 4 | `git diff --name-only "$(git merge-base origin/main HEAD)" HEAD -- . ':!.agents/artifacts'` prints exactly the two test paths |
| AC2 | code | Task 4 | D7 proxy script over both files on the final head (equal test and skip counts, assert count not below base), plus the reviewer's diff read; acceptance-record row AC2 |
| AC3 | code | Task 4 | `just agent-workflow-tests` on the final head (sdd's final gate); threshold: exit status 0 |
| AC4 | code | Task 4 | `git diff -U10 "$(git merge-base origin/main HEAD)" -- <file> \| wc -c` per file; threshold ≤ 60000 each; both numbers in acceptance-record row AC4 and the PR body |
| AC5 | code | Task 4 | scratch worktree at the head, `git show 6ae38b0c:<file> > <file>`, `git diff -U10 HEAD -- <file> \| wc -c` per file; threshold ≤ 60000 each; both numbers in acceptance-record row AC5 and the PR body |

## Decisions

- Text reuse and docstrings: D1. `init_run` shape without `creation_key`: D2. Which run ids stay and which fixture handles take branch names: D3. `mint_direct_ledger` bytes and unused `prior_run`: D4. WS overflow fallback: D5. Where `assert_bound` calls land: D6.
- Mechanical AC2 proxy alongside the diff review: D7 (appended by this plan).

---
