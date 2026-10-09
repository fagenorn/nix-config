# Slim the Repository CLAUDE.md Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Cut the repository `CLAUDE.md` from 5,342 words (base `8e2bfb72`) to at most 2,136, moving every removed fact verbatim to one home beside the code it describes.

**Architecture:** Documentation relocation only. Tasks 1–4 each move one group of blocks out of `CLAUDE.md` into one home (`python/README.md`, `home/common/claude-code/README.md`, `home/common/agent-skills/README.md`, `home/linux/claude-local/README.md`), leave dictated pointer sentences behind, and delete the `CLAUDE.md` phrase pins whose prose they remove. Task 5 condenses the remaining blocks whose facts already live in code and measures the result. Each task member carries its block's rows of the fact-to-home table (D4, D8).

**Tech stack:** Markdown; Python 3 `unittest` contract tests; `resolve-project` projections; Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-09-issue-330-slim-claude-md-design.md` (its `## Decision ledger` rows D1–D8 are cited by ID below).

## Global Constraints

- No change to behaviour or code: no Nix, Python source, guard, helper or CI edit. The only non-Markdown edit is deleting the four `CLAUDE.md` phrase pins in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (D5). No new test (spec Test seams).
- Out of scope, never edited: `.agents/instructions/bootstrap.md`, `AGENTS.md`, `.agents/project.json`, `home/common/agent-guidance/AGENTS.md`, `instruction-load.json`, and the generated import line `@.agents/instructions/bootstrap.md`, which stays the last line of `CLAUDE.md`, exactly once (D3, spec Out of scope).
- The base is `8e2bfb72`. Sentence references `L<n>` are line numbers in `git show 8e2bfb72:CLAUDE.md` (the worktree's `CLAUDE.md` is identical to it when execution starts).
- Text moves without being rewritten. Allowed edits only: name the subject where the sentence leaned on `CLAUDE.md` context, split a paragraph into one subsection per concern, rebase a moved markdown link to the new file's directory, and repair the dead pointer `.out-of-scope/host-contention-scheduling.md` to `.agents/knowledge/rejections/host-contention-scheduling.md` (D2, D7). A sentence kept in `CLAUDE.md` is not copied into a README (D7).
- A moved fact that contradicts the code beside it is not corrected: the implementer reports it (file, line, sentence) for the owner to file as an issue (spec "How moved text is written").
- Each pointer sentence left in `CLAUDE.md` also says that new detail of its kind goes to the home, not to `CLAUDE.md` (D1). Past plans and specs under `.agents/artifacts/` keep their wording.
- Anchor gates normalise whitespace (`" ".join(text.split())`) on both sides, so README line wrapping never fails them. Anchors are plan-only checks and are never committed as tests (D6, D8).
- Commands run from the worktree root, in the foreground under `launch-scope exec … --`. Unit tests: `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, timeout at least 600 s.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s), `just agent-instruction-budget` with no `--raise-label` (timeout 600 s, must print `check: pass`), `resolve-project check-projections --repo-root .` (every projection in sync), and `wc -w < CLAUDE.md` printing at most `2136`. No agent applies the `instruction-budget-raise` label (spec Out of scope, #291 D2).

## Test seams

- `just agent-workflow-tests`: `CommittedProjectionTest`, the `check-projections` tests, and every remaining contract test after the pin deletion (spec Test seams).
- `just build`, unchanged code, still the project verification.
- `wc -w CLAUDE.md` against `git show 8e2bfb72:CLAUDE.md | wc -w`, recorded as evidence (D6).
- Reviewer audit of the fact-to-home rows in each task member, both directions (D4, D8).

## Delivery estimate and boundaries

Estimates: 6 changed files plus the acceptance record — `CLAUDE.md` (about −3,800 words, to roughly 1,500), three new READMEs (`python/`, `home/common/claude-code/`, `home/linux/claude-local/`, about 900, 1,500 and 350 words), `home/common/agent-skills/README.md` (about +1,400 words), and `test_workflow_skill_contracts.py` (four test methods and one class removed, about −45 lines). Net repository words roughly zero. One review package; no slicing needed.

## Task index

Task 1 — Move the helper package and #117 decision to `python/README.md` — `CLAUDE.md`, `python/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-10-09-issue-330-slim-claude-md.tasks/task-1.md)
Task 2 — Move the guard, plugins and patch procedure to `home/common/claude-code/README.md` — `CLAUDE.md`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-09-issue-330-slim-claude-md.tasks/task-2.md)
Task 3 — Move skill sourcing and lifecycle-helper contracts to `home/common/agent-skills/README.md` — `CLAUDE.md`, `home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-09-issue-330-slim-claude-md.tasks/task-3.md)
Task 4 — Move the local-model detail to `home/linux/claude-local/README.md` — `CLAUDE.md`, `home/linux/claude-local/README.md` — low-risk — [task-4.md](2026-10-09-issue-330-slim-claude-md.tasks/task-4.md)
Task 5 — Condense CI and Homebrew, measure, record AC1 — `CLAUDE.md`, `.agents/artifacts/plans/2026-10-09-issue-330-slim-claude-md.acceptance.md` — low-risk — [task-5.md](2026-10-09-issue-330-slim-claude-md.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 5 | Command: `wc -w < CLAUDE.md` at the task's head, against `git show 8e2bfb72:CLAUDE.md \| wc -w` (5342). Conditions: the worktree head after Task 5. Threshold: head ≤ 2136 (0.40 × 5342, rounded down). Task 5's implementer fills acceptance-record row AC1. |
| AC2 | code | Task 5 | Reviewer audit of the diff against the fact-to-home rows in Tasks 1–5 (F1–F100), both directions: every deleted base sentence maps to a row, and every row's destination holds the fact at HEAD (D4, D8). Task 5 owns the row because it lands the last deletion; its gate checks that the kept skeleton and kept sentences are still present and that no base prose line survives unlisted. |
| AC3 | code | Task 5 | `CommittedProjectionTest` and the `check-projections` tests, run by `just agent-workflow-tests`, plus `resolve-project check-projections --repo-root .` |

## Decisions

- Retention rule and redirecting pointers: D1. One home, verbatim moves: D2. `CLAUDE.md` stays the architecture binding: D3. Fact-to-home audit: D4. Pins deleted with their prose: D5. No committed size check: D6.
- Link rebasing, no duplication of kept sentences, dictated summaries: D7 (appended by this plan). Table split into task members with anchor gates: D8 (appended by this plan).

---

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base `b5246e50`, no fallback. Findings: 1 accepted (B1, Blocking: L72's third sentence was unmapped; added row F100 to Task 3 with its anchors and widened AC2 to F1–F100), 0 rejected, 0 deferred. The reviewer reconstructed the dictated final `CLAUDE.md` at 1,492 words with the managed import once, and confirmed the four test-pin deletions against live tests.
