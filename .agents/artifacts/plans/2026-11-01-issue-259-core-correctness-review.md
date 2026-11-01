# CORE Full-Scope Correctness Review Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every one of the 25 product files of https://github.com/fagenorn/nix-config/pull/246 gets a whole-file correctness review by fresh reviewers independent of CORE's authors, every Critical and Important finding is fixed with a failing-first regression test or tracked by an open issue, and the record is committed and posted on https://github.com/fagenorn/nix-config/issues/259.

**Architecture:** Task 1's implementer pins `REVIEW_SHA`, dispatches five read-only `reviewer` subagents in parallel (one per cluster batch), checks their coverage lines against Git, triages and dispositions every finding, and commits the record with transient Evidence tokens (`fix pending`, `issue pending (bar <k>)`). Task 2 fixes the fix-bound findings test-first and fills their evidence. Task 3 files the rest, adds the record's `## Verification`, posts the demo comment and writes AC1–AC3 into the acceptance record. The record is the only carrier between tasks (per D9).

**Tech stack:** Markdown records, Python 3.13 standard library `unittest`, Git, `gh`, `just`, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-design.md` (a bare "Dn" cites its `## Decision ledger`). Issue: https://github.com/fagenorn/nix-config/issues/259

## Global Constraints

- Subject: PR 246, merge `93e6059a6fece769a621657c5889278b9cb9e0d7`. The 25 paths are `git diff --name-only 93e6059a6fece769a621657c5889278b9cb9e0d7^1 93e6059a6fece769a621657c5889278b9cb9e0d7` minus every path under `.agents/artifacts/`, in that order (per D1).
- `REVIEW_SHA` is the 40-hex value on the `Delivery base:` line of `"$(sdd-workspace .agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.md)/progress.md"` (`8c475824d7ea3b766183e5514b5ed33f623b1749` at planning). A missing line is NEEDS_CONTEXT, never a guess (per D1).
- Record: `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md`, with the formats Task 1 defines (per D7). Acceptance record: `.agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.acceptance.md`.
- Severity per D4; dispositions are the closed set `fixed`, `filed`, `tracked`, `rejected`, `recorded`, under the fix-here bar of D5 as refined by D9.
- Never fix a Minor finding, never reopen CR-001 to CR-003 (fixed in `6cdb9b90282b782c2ab34c9783ed2d2567448ddb`), never re-file the topic of https://github.com/fagenorn/nix-config/issues/255, and change no file outside the 25 except a fix's regression test and the two records.
- Tracker: `gh` with `--repo fagenorn/nix-config` on every call; full URLs, never a bare `#N`. Never add the `instruction-budget-raise` label and never raise a ceiling.
- Any commit after Task 3 that changes the record's `## Reviewer`, `## Coverage` or `## Findings` also edits the posted comment to match and re-measures AC1–AC3 (per D8).
- Process custody: every test, build or gate command runs in the foreground from the worktree root as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, written `launch-scope exec … --` below, with the stated timeout. `<R>`, `<I>`, `<W>` come from the dispatch's `Lifecycle worker:` line. Scratch lives under what `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints, written `$S`. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>` (written `launch-commit … --`), SSH-signed, ending with the session's `Co-Authored-By` trailer. Never push, never `just switch`.
- **Focused test** (timeout 900 s): `launch-scope exec … -- bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest -v <test file> -k <test name>'`. A test ID is written `<test file>::<Class>.<test name>`; `-k` matching nothing exits 5.
- Declared verification (`just agent-workflow-tests`, about 16 min; `just build`) runs once, in sdd's Final verification, not in any task (per D10).

## Test seams

- Review modules: the existing test module that already covers the fixed module, at the seam it uses — `python -m agent_tools.<module>` under the recipe `PYTHONPATH` against real temporary Git repositories, or a normal import where that module's tests already import. No new harness, no mocked Git.
- `home/common/agent-skills/tests/test_artifact_budget.py` for `artifact_budget.py`; `tests/test_agent_tools_launchers.py`, through `just agent-installed-skill-tests`, for installed launchers.
- Skill text, `CLAUDE.md` and recipes: only text a tool or subagent consumes, through the existing contract tests (agent-helpers rules 5 and 6).
- The record and the comment: `evidence` commands, never a committed test (per D8).

## Delivery estimate and boundaries

Estimates: 2 new record files (about 15–30 KB together); 0–3 fixes of at most 150 changed lines each (per D5, D9), so at most about 6 product and test files and 450 lines. One review package. Tracker writes: 0–n follow-up issues and one comment. No independent slice: Tasks 2 and 3 consume Task 1's dispositions.

## Task index

Task 1 — Whole-file review and triaged record — `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md` — full — [task-1.md](2026-11-01-issue-259-core-correctness-review.tasks/task-1.md)
Task 2 — Fix the fix-bound findings test-first — the `fix pending` rows' files among the 25, their seam's test modules, the record — full — [task-2.md](2026-11-01-issue-259-core-correctness-review.tasks/task-2.md)
Task 3 — File follow-ups, verify, post the record, acceptance evidence — the record, `.agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.acceptance.md`, tracker — full — [task-3.md](2026-11-01-issue-259-core-correctness-review.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 3 | The posted comment's body (`gh api repos/fagenorn/nix-config/issues/comments/<id> --jq .body`) against the 25 Git paths, by Task 3's comment check at the record commit; threshold: first line exactly `Correctness review record — CORE (PR 246), scope full: 25 of 25 product files`, path difference empty, 25 coverage rows, every `Read` `whole`. Acceptance-record row `AC1` (per D8). |
| AC2 | evidence (classified) | Task 3 | The same body: its `## Reviewer` section equals the record's at the record commit and holds the agent type, model, effort, five or more agent IDs and the independence line with the tally `Codex ×13` and `Claude Opus 5.5 ×1`; threshold: all present and equal. Row `AC2` (per D8). |
| AC3 | evidence (classified) | Task 3 | The record's `## Findings` at the final head, by Task 3's findings check: every Critical or Important row not `rejected` is `fixed` with a test that fails at `<fix>^` (test overlaid) and passes at head, or `filed`/`tracked` with an issue whose `gh issue view <n> --repo fagenorn/nix-config --json state --jq .state` prints `OPEN`; threshold: 0 violating rows. Row `AC3` (per D5, D6, D10). |
| AC4 | code (classified) | Task 2 | `just agent-workflow-tests` and `just build`, sdd's Final verification on the final head (per D10). |

## Decisions

- File set, pinned tree and anchoring: per D1. Reviewers, batches and the brief: per D2. Coverage lines and the one retry: per D3.
- Severity and the controller's checks: per D4. Dispositions and the fix-here bar: per D5. Failing-first evidence: per D6.
- The record's path and parts: per D7. The demo comment and AC1/AC2 as evidence rows: per D8.
- Who acts as the controller, the record as carrier, the bar's measured form and the no-seam rule: per D9.
- What the record's Verification holds, AC classification and the acceptance-record writer: per D10.
- Where AC3 is measured and how launcher regressions replay: per D11.

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, model gpt-6-astra, effort xhigh), isolated read-only reviewer thread; no fallback used.
- Base SHA: `8c475824d7ea3b766183e5514b5ed33f623b1749`; plan reviewed at `1f91dabb`. Focus: none beyond the plan-review contract.
- Findings: 3 accepted, 0 rejected, 0 deferred. PR259-01 (Blocking: AC3 measured at the record commit, per D11, Task 3 Steps 6–7); PR259-02 (Blocking: launcher regressions replay through `just agent-installed-skill-tests` and reject skips, per D11, Task 3 Step 3); PR259-03 (Should fix: `set -o pipefail` on Task 2 Step 5's piped gates).

---
