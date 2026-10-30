# Evidence Freshness Against the Measured Tree Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Evidence measured at commit C stays fresh at a later commit that changes only the acceptance record and goes stale when a measured file changes, judged by a deterministic `verified-tree fresh` verb that sdd's final review and conformance reviewer call instead of judging a "measured surface" in prose.

**Architecture:** `agent_tools.verified_tree` gains a third verb, `fresh` (D1, D3). It diffs the `--since` commit's tree against the existing build-visible `current_tree`, through one `_tree_diff` helper that `changed_paths` also uses, and drops the record's own path (D2, D4, D8). The three freshness sentences in `sdd/final-review.md` and `sdd/conformance-reviewer-prompt.md` become the verb's argv, each document ending no larger than at base (D5). The argv literal is pinned in `SDD_MACHINE_TEXT` (D6).

**Tech stack:** Python 3 standard library (`argparse`, `pathlib`, `subprocess`, `unittest`), git plumbing (`rev-parse`, `diff-tree`, `write-tree`), Markdown under the Instruction Budget gate, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-30-issue-477-evidence-freshness-design.md`. A bare "Dn" cites its `## Decision ledger`, and this plan appends D9 and D10. Issue: https://github.com/fagenorn/nix-config/issues/477.

## Global Constraints

- Base `79cf7e3f` (`origin/main` at planning). Spec commit `2a5a02d5`. Tasks land in index order, each on top of the one before.
- Declared verification: `just build`, `just agent-workflow-tests` (in that order, from `bindings.workflow.verification`).
- Not edited: `lib/agent-tools.nix` (`fresh` is a verb of an existing command), `home/common/agent-skills/instruction-load.json`, `.agents/project.json`, every ship-issue and from-issue document, every existing `*.acceptance.md` record, and the `check`/`record` semantics and the `verified-tree.json` and `verified-tree-plan.json` schemas.
- Instruction load: never apply the user-only raise label, never name it in a command, and never edit `instruction-load.json`. Each edited sdd document ends no larger in bytes than at `79cf7e3f` (D5).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 477", never a bare `#477`. No `TODO` or `FIXME`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -1'`. A passing run prints `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each; the suite took about 890 s in the planning trial), plus the Budget run, which neither recipe covers.

## Test seams

- The command's process boundary (spec § Test seams, D7): `tests/test_verified_tree.py`'s `VerifiedTreeTest` drives `python -m agent_tools.verified_tree` in a throwaway copy of `home/common/agent-skills/evals/fixture-repo` and asserts exit code, canonical stdout JSON and stderr. No test imports `verified_tree`.
- The guidance (D6): `home/common/agent-skills/tests/test_workflow_skill_contracts.py`'s `SDD_MACHINE_TEXT`, checked by `WorkflowSkillContractsTest.test_sdd_documents_carry_their_machine_text` on whitespace-normalized text. The Budget run checks the byte ceilings.

## Delivery estimate and boundaries

All figures are estimates. Six changed files, plus this package and two spec ledger rows, about +215/−27 lines:

| File | Change |
|------|--------|
| `python/agent_tools/verified_tree.py` | about +65/−4 (verb, helper, docstring) |
| `tests/test_verified_tree.py` | about +135/−3 |
| `python/README.md` | one sentence appended, two phrases edited |
| `sdd/final-review.md` | −50 bytes |
| `sdd/conformance-reviewer-prompt.md` | −12 bytes |
| `test_workflow_skill_contracts.py` | +2 lines |

One review package. If a split is forced, each task is its own slice: S1 = Task 1 (AC1, AC2), S2 = Task 2 (AC3, AC4).

## Task index

Task 1 — `verified-tree fresh` verb and its contract — `python/agent_tools/verified_tree.py`, `tests/test_verified_tree.py`, `python/README.md` — full — [task-1.md](2026-10-30-issue-477-evidence-freshness.tasks/task-1.md)
Task 2 — sdd freshness guidance runs the verb — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-30-issue-477-evidence-freshness.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_verified_tree.py::VerifiedTreeTest::test_a_commit_that_changes_only_the_record_stays_fresh` (at base it fails: no `fresh` verb), run by `just agent-workflow-tests` |
| AC2 | code | Task 1 | `tests/test_verified_tree.py::VerifiedTreeTest::test_a_commit_that_changes_a_measured_file_is_stale`, run by `just agent-workflow-tests` |
| AC3 | code | Task 2 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_sdd_documents_carry_their_machine_text` with the argv pinned for both documents (D6), run by `just agent-workflow-tests` |
| AC4 | code | Task 2 | `just agent-workflow-tests`, on the Declared verification line, run by sdd's final gate on the final head |

## Decisions

- Task 1 rests on D1, D2, D3, D4, D7, D8 and D9. Task 2 rests on D5, D6 and D10.
- Planning appended D9 (`fresh`'s validation order, error lines and the top-level record refusal) and D10 (the conformance bullet's wording inside its byte budget).
- A planning trial ran at `2a5a02d5` in a scratch worktree, then discarded. With Task 1's tests and no implementation, `tests/test_verified_tree.py` ran 41 tests with `FAILED (failures=16)` (the ten new tests; the refusal test fails in all seven subtests because argparse prints two stderr lines). With Task 1 applied it ran 41 tests, `OK`. With both tasks applied, `test_workflow_skill_contracts.py` gave `OK (skipped=1)` (155 tests; without the guidance edits the pin test failed for both documents), `test_dispatch_contracts.py` gave `OK (skipped=1)`, the Budget run gave `check: pass`, the documents measured 12882 and 8950 bytes against 12932 and 8962 at base, and `just agent-workflow-tests` passed 106 of 106 members.

---
