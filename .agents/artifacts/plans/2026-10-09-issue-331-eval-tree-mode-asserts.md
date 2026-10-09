# Eval Asserts That Grade the Artifact They Name Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** writing-plans eval 1 grades the plan it names in tree mode and reports all 8 asserts, and ship-issue's **Interim child results** paragraph is the one canonical copy the identity test compares across sdd, from-issue and ship-issue.

**Architecture:** Two guards against a mis-graded eval: the runner feeds every per-assert `bash -c` from `/dev/null`, and the asserts address the absolute `SPEC_DIR`/`PLAN_DIR` directly and exit after a guarding `fail`. Corpus-wide shape tests in `test_eval_cases.py` keep both conventions, and a synthetic production-shaped fixture pins writing-plans eval 1's behaviour. The interim paragraph is copy alignment plus an extended identity test, and AC1 closes with one live sonnet run in tree mode.

**Tech stack:** Bash (`run-eval.sh`, `assert-lib.sh`, `test-run-eval-tree.sh`), JSON eval cases, Python 3 `unittest`, Markdown skill text, `agent_tools.instruction_load`.

Spec: `.agents/artifacts/specs/2026-10-09-issue-331-eval-tree-mode-asserts-design.md` (its `## Decision ledger` rows D1–D10 are cited by ID).

## Global Constraints

- Base: `13cb52971064b0b5c10b2991e5771b5405df92c5` (`origin/main` at planning).
- assert-lib helper semantics are unchanged (`fail` still returns 1); only its header comment changes. writing-plans `SKILL.md` and the fixture repository are unchanged (spec Out of scope).
- Assert path convention (D1): under `$REPO` an artifact dir is the bare `"$SPEC_DIR"`/`"$PLAN_DIR"`; under another checkout it is `"$<checkout>/${X#"$REPO"/}"`. Fail-then-exit shape (D2): a `fail` that guards later commands is written `|| { fail "…"; exit 1; }`.
- No instruction-load ceiling is raised and no agent applies the `instruction-budget-raise` label. Planning measured `check: pass` with the D4 edit applied; if a tightness violation appears, lower it with `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load tighten` (no label needed).
- Every long command, each test command included, runs in the foreground as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` from the worktree root, with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, timeout at least 600 s.
- Final gate, once on the final head (sdd's final gate, not per task; Task 5's commit touches no measured path): `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s; it runs `test_eval_cases.py`, `test_workflow_skill_contracts.py` and `test-run-eval-tree.sh`) and `just agent-instruction-budget` with no `--raise-label` (timeout 600 s), which prints `check: pass`.
- AC1's measured surface is `home/common/agent-skills/skills/writing-plans/`, `home/common/agent-skills/evals/run-eval.sh`, `home/common/agent-skills/evals/assert-lib.sh` and `home/common/agent-skills/evals/fixture-repo/`. Any commit after Task 5's measured head that touches it re-runs Task 5 (D6).

## Test seams

- Assert behaviour: `run_assert` in `home/common/agent-skills/tests/test_eval_cases.py` over a synthetic production-shaped fixture (D7, D10).
- Assert shape: corpus checks over `case_files()` in `test_eval_cases.py` (D1, D2).
- Runner: the setup-smoke loop of `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` with `tests/fixtures/setup-smoke-evals.json` (D8, D10).
- Interim copies: `InterimChildResultContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (D5).
- The Instruction Budget gate `just agent-instruction-budget`.

## Delivery estimate and boundaries

Estimates: 13 changed files — runner, assert-lib, smoke fixture and smoke test; two `evals.json`; two test modules; two `SKILL.md`; `results.jsonl`, the acceptance record and the plan/spec artifacts. Net skill bytes fall by about 300 (−150 each in sdd and from-issue). One review package; no slicing needed.

## Task index

Task 1 — Runner reads asserts' stdin from /dev/null, smoke grades the row total — `home/common/agent-skills/evals/run-eval.sh`, `home/common/agent-skills/evals/assert-lib.sh`, `home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json`, `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` — low-risk — [task-1.md](2026-10-09-issue-331-eval-tree-mode-asserts.tasks/task-1.md)
Task 2 — writing-plans eval 1 grades the absolute plan dir and exits on a failed precondition — `home/common/agent-skills/skills/writing-plans/evals/evals.json`, `home/common/agent-skills/tests/test_eval_cases.py` — low-risk — [task-2.md](2026-10-09-issue-331-eval-tree-mode-asserts.tasks/task-2.md)
Task 3 — No eval prefixes an absolute artifact dir — `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`, `home/common/agent-skills/tests/test_eval_cases.py`, `home/common/agent-skills/evals/assert-lib.sh` — low-risk — [task-3.md](2026-10-09-issue-331-eval-tree-mode-asserts.tasks/task-3.md)
Task 4 — One canonical Interim child results paragraph — `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-10-09-issue-331-eval-tree-mode-asserts.tasks/task-4.md)
Task 5 — Measure AC1: writing-plans eval 1 in tree mode — `home/common/agent-skills/evals/results/results.jsonl`, `.agents/artifacts/plans/2026-10-09-issue-331-eval-tree-mode-asserts.acceptance.md` — full — [task-5.md](2026-10-09-issue-331-eval-tree-mode-asserts.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 5 | Command: `EVAL_TREE=. EVAL_MODEL=sonnet just evals writing-plans 1` from the worktree root. Conditions: tree mode on the worktree at its final head, every measured-surface change committed, `git status --porcelain` empty. Threshold: the appended `results.jsonl` row has `verdict` `PASS`, `model` `sonnet`, `failed` 0, `total` 8, `tree_dirty` false and `tree_rev` equal to the measured `HEAD`. Task 5's implementer fills acceptance-record row AC1. |
| AC2 | code | Task 4 | `test_workflow_skill_contracts.py`: `InterimChildResultContractsTest.test_the_paragraph_copies_stay_identical` and `test_each_owner_skill_carries_the_paragraph_once` over sdd, from-issue and ship-issue, run by `just agent-workflow-tests` |

## Decisions

- Assert path convention: D1; improve-codebase-architecture fixed here: D3. Runner `</dev/null` plus fail-then-exit plus the corpus shape check: D2.
- Canonical interim text: D4; identity test and re-taken anchors: D5.
- AC1 in tree mode at the final head, `tree_dirty: false`: D6, D8. Synthetic fixture seam: D7.
- Task-section assert grades each plan root through `plan_tasks_verifiable`: D9 (appended by this plan).
- `run_assert` stdin default and the offset proof; the smoke's stdin reader: D10 (appended by this plan).

---
