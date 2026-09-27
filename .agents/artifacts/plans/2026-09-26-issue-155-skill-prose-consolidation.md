# Skill Prose Consolidation and Instruction-Load Baseline Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give each corrected #99 rule one authoritative explanation, and add a
reproducible per-profile, per-host instruction-load model with a hot-path
ceiling and a committed before/after report
([#155](https://github.com/fagenorn/nix-config/issues/155)).

**Architecture:** Tasks 1–3 make the four consolidation edits (E1–E4) in 14
skill documents. Each edit gets a guard beside its rule's home: #100's
policy-entry helper for E1, the lifecycle anchors for E2 and E3, and #154's
shell-form module for E4. Task 4 adds #153's stray-copy guard. Tasks 5–7 build
`agent_tools.instruction_load`: the model core behind one `read(path)` seam, the
`report` command over two revisions, and the checked-in 36-profile model with
its ceilings. Task 8 re-measures after the sync, generates the report,
commits it alone and runs every gate. On the attempt-2 resume, the sync comes
before sdd entry (D35).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `os`, `re`,
`subprocess`, `unittest`), the `agent_tools` package, Markdown skill prose,
`git`, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-26-issue-155-skill-prose-consolidation-design.md`, D1–D35.

## Global Constraints

- Scope is exactly the spec's (D2, D15, `## Out of scope`). Only E1–E4 change
  skill text. Nothing changes in a held repeated block, leaf clause, carrier
  region, shell example, model routing, helper behavior, `CLAUDE.md`, ADR,
  context doc, `.nix` file or CI. Nothing is recovered from
  `worktree-issue-99-skill-prose-fixes` (tip `3c9709ca`).
- In the 14 edited documents, every sentence a test asserts and every binding,
  path and flag survives byte for byte, except where a task names the exact
  replacement.
- New Python is `python/agent_tools/instruction_load.py`. It uses the standard
  library only, has no command-table row (D9), and does strict JSON loads through
  the `agent_tools.canonical` hooks. Its argparse `prog` is
  `agent-instruction-load`. No `sys.path`, `importlib` or `__file__` lookups.
- `home/common/agent-skills/instruction-load.json` is repository data and is
  never installed. It is written as
  `json.dumps(model, indent=2, ensure_ascii=False) + "\n"`.
- No new file contains a token from `LEGACY_POLICY_SURFACE` in
  `T/test_workflow_skill_contracts.py`. The tracked-source scan reads `python/`,
  `tests/` and `home/common/agent-skills/`.
- Every gate is one plain command, per `worktrees/SKILL.md`'s
  `## Shell forms the isolation checker refuses`: no chain, pipe, redirect or
  heredoc. For long output, read only the `FAIL:`/`ERROR:` lines and the final
  `Ran`/`OK`/`FAILED` lines. Scratch scripts are written with the file-writing
  tool outside the working tree and run by path.
- Suites run under `env WORKFLOW_POLICY_SURFACE=source` (D27). A test that
  imports `agent_tools` runs with `PYTHONPATH=python`, from the worktree root.
- Never run `just switch`. `just build` runs in Task 8 only.
- A commit after Task 8's report commit that changes a measured member, the
  model or the matrix regenerates the report per Task 8 and commits it alone
  (D19).
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the trailer
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`, passed
  as a second `-m`.

Path abbreviations used in members: `SK` = `home/common/agent-skills/skills`,
`CL` = `home/common/claude-code/skills`, `T` = `home/common/agent-skills/tests`,
`IL` = `python/agent_tools/instruction_load.py`,
`MODEL` = `home/common/agent-skills/instruction-load.json`.

## Test seams

1. `T/test_instruction_load.py`, through `instruction_load`'s public functions
   and command. Task 5 drives `load_model`, `resolve`, `validate`, `measure`,
   `over_ceiling` and `tree_reader` with a dict reader over a fixture. Task 6
   runs `python -m agent_tools.instruction_load report` in a hermetic two-commit
   fixture repository. Task 7 reads the live model through
   `tree_reader(REPO_ROOT)`.
2. `T/test_dispatch_contracts.py`: `guarded_documents()` and `stray_copies()`,
   with live-text mutations (Task 4; D3, D21).
3. `T/test_shell_example_contracts.py`: `lacks_guidance_pointer()` over
   `swept_documents()`, with ship-release's pointer removed as the mutation
   (Task 3; D13).
4. `T/test_workflow_skill_contracts.py`: `assert_single_resolution_statement()`
   inside `assert_policy_entries`, with the restatement restored as the mutation
   (Task 1; D13). The D20 and D28 re-anchoring happens here too (Task 2).

No installed-tree class is added (D12).

## Delivery estimate and boundaries

All figures are estimates. About 23 files change, four of them new: the module,
the model, its test file and the report. The skill documents lose about 1.4 KB
in total: E1 is about 65 bytes per entry, E2 about 45–65 bytes per file (D31)
and E3 about 470 bytes. The module is about 520 lines. Tests grow by about 430 lines in
the new file and 110 in the three contract suites. The model is about 24 KB of
JSON, and the report is probably 40–60 KB of Markdown. The product diff exceeds
ship-issue's 20-file degraded-review bound, so ship runs the full two-axis
review.

Tasks run in index order. Tasks 1–4 are independently deliverable. Task 7
needs the module and recipe from Tasks 5–6, and its ceilings must follow
Tasks 1–3, because they are the post-edit values. Task 8 comes last. On the
resume it adds a ceiling commit, a commit that retires attempt 1's report and
the report commit. The sync merge is R1's (D35).

The base suite at `61b9def` ran 1305 tests, OK (skipped=4), in about 700 s. A
planning probe applied every task to a scratch clone. The four contract suites
passed, and the 30 new instruction-load tests passed against the probe
implementation.

### Resume: attempt 2 (D34, D35)

Run `direct-155-000001` executed all eight tasks on this branch and finished
sdd with `review_state: clean`. Its durable review package, relative to the
main checkout, is
`.superpowers/issue-delivery/155/direct-155-000001/sdd-58cb1955adca9025bce5777dcacae2b467b76b52.json`:
18 Minor findings, each parked or deferred with a ruling. Nothing was pushed.
`origin/main` then moved from `affa05e` to `17da7f2` (#196, #197). That changed
the measured `from-issue/ship-handoff.md` and none of Tasks 1–7's files, so
only Task 8 re-runs (D19). The evidence is `git log --oneline affa05e..58cb195`:

| Task | Commits |
|---|---|
| 1 | `8eefa14..f2c1544` |
| 2 | `f2c1544..171e99e` |
| 3 | `171e99e..a0f2b7c` |
| 4 | `a0f2b7c..626d56d` |
| 5 | `626d56d..e8b16ae` |
| 6 | `e8b16ae..ed454fa` |
| 7 | `ed454fa..cd7ded7` |
| 8, superseded | `cd7ded7..58cb195`, the report Task 8 retires |

Setup runs in this order, before sdd pins `DELIVERY_BASE`:

- **R1: sync, run by the from-issue owner before it invokes sdd (D35).** Run
  `git fetch origin main`, then Task 8's merge form (D30):
  `git merge --no-ff origin/main -m "Merge remote-tracking branch 'origin/main' into worktree-issue-155-consolidate-skill-prose" -m "<one short paragraph: what origin/main landed>" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.
  At planning time, the paragraph names #196 (`workflow-state control` no
  longer raises `KeyError 'idle'` on delivery remainders) and #197
  (`build-delivery` serves contracts installed before the builder existed).
  Expected: one signed merge commit. On a conflict, run `git merge --abort` and
  stop with BLOCKED, naming the conflicting paths.
- **R2: the sdd controller's check.**
  `git log --merges --first-parent --format=%H affa05e..HEAD` prints the sync
  merge `<sync>` first. `git merge-base HEAD origin/main` prints what
  `git rev-parse <sync>^2` prints. Then
  `git diff --name-only cd7ded7 HEAD -- python justfile home/common/claude-code/skills home/common/agent-skills/instruction-load.json "home/common/agent-skills/skills/*/SKILL.md" home/common/agent-skills/skills/from-issue/AUTO.md "home/common/agent-skills/tests/test_*_contracts.py" home/common/agent-skills/tests/test_instruction_load.py`
  prints nothing. The 22 files Tasks 1–7 changed are then byte for byte what
  attempt 1 reviewed. If any check fails, the controller pins nothing and
  stops with BLOCKED, naming R1.
- **R3: seed the ledger (D34).** After the identity line, the controller
  appends `Task <N>: complete (commits <range>, review clean)` for N = 1 to 7,
  with the ranges above. It then appends
  `Resume: Tasks 1–7 adopted from run direct-155-000001; attempt-1 findings in its package`.
  It dispatches no implementer or reviewer for Tasks 1–7.

After setup, sdd runs as written. The `DELIVERY_BASE` it pins,
`git merge-base HEAD origin/main`, is `<sync>^2`. It runs the cumulative gate
and dispatches Task 8. Its mandatory final two-axis review
still covers the whole branch, `DELIVERY_BASE..HEAD`, including Tasks 1–7, and
the ledger pointer lets the conformance axis triage the attempt-1 findings.
The planning probe replayed R1 and Task 8 against `17da7f2`. From `17da7f2`,
the cumulative package was 361,207 bytes in 8 files, within budget. From
`affa05e`, it was already 605,512 bytes in 12 files at the merge, over budget.

## Task index

Resume status (D34): Tasks 1–7 are complete from attempt 1. They are recorded
in the ledger, not re-dispatched. Task 8 is the remaining work.

Task 1 — One resolver statement per policy entry (E1) and its guard (done) — `SK/{design,doc-grounded-questions,from-issue,grill-with-docs,research,ship-issue,ship-release,to-issues,wayfind,worktrees,writing-plans}/SKILL.md`, `CL/{codex-collaboration,orchestrate-issues}/SKILL.md`, `T/test_workflow_skill_contracts.py` — full — [task-1.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-1.md)

Task 2 — Fold the PATH fallback and the direct-acquisition restatement (E2, E3) (done) — `SK/from-issue/SKILL.md`, `CL/orchestrate-issues/SKILL.md`, `SK/from-issue/AUTO.md`, `T/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-2.md)

Task 3 — Point ship-release at the shell-form home (E4) and guard checker mentions (done) — `SK/ship-release/SKILL.md`, `T/test_shell_example_contracts.py` — full — [task-3.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-3.md)

Task 4 — Guard leaf clauses against copies outside enrolled regions (done) — `T/test_dispatch_contracts.py` — low-risk — [task-4.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-4.md)

Task 5 — Instruction-load model core: load, validate, measure, ceilings (done) — `IL`, `python/agent_tools/agent_model_matrix.py`, `T/test_instruction_load.py`, `justfile` — full — [task-5.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-5.md)

Task 6 — The `report` command and the `agent-instruction-load` recipe (done) — `IL`, `T/test_instruction_load.py`, `justfile` — full — [task-6.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-6.md)

Task 7 — The live 36-profile model and its ceilings (done) — `MODEL`, `T/test_instruction_load.py` — full — [task-7.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-7.md)

Task 8 — Re-measure after the sync, regenerate the report, final gates (remaining) — `.agents/artifacts/specs/<generation-date>-issue-155-instruction-load-report.md` (new), `.agents/artifacts/specs/2026-09-26-issue-155-instruction-load-report.md` (retired), `MODEL` (ceilings and notes) — full — [task-8.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-8.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| One authoritative explanation per corrected rule; other surfaces derive or link | 1, 2, 3 (edits and guards), 4 (leaf-clause guard) |
| A fresh before/after report of bytes, words and loaded members per profile and host | 5, 6, 7 (model and command), 8 (the committed report) |
| Hot entry surface smaller, or the preserved behavior named; unexplained growth fails | 7 (notes, ceilings), 8 (the no-growth gate, D26) |
| #153 and #154 suites green on source and installed trees | 8 |
| No unrelated content from the retained aggregate branch | 8 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D21 from design
and grill. Planning added D22–D30:

- **D22:** the matrix gets a text-level `parse_matrix`.
- **D23:** the roster rules — prompt source and grouping — give 36 profiles.
- **D24:** hot or conditional tie-breaks.
- **D25:** the case-exact tree reader.
- **D26:** ceiling-test slack and the meaning of `affected`.
- **D27:** gates run as `WORKFLOW_POLICY_SURFACE=source`.
- **D28:** D20's anchor move covers three tests, and E3 needs a whitespace-normalized union.
- **D29:** ceilings are written only by scratch scripts over `measure`.
- **D30:** Task 8 syncs by a signed merge, and a conflict is reported BLOCKED.

Phase-5 standards review added D31–D33:

- **D31:** E2 keeps each PATH fallback in a sentence that covers every call.
- **D32:** the plain `agent-workflow-tests` run's pre-activation failure is recorded.
- **D33:** the E4 pointer is conditional, the report cells are pinned, and there is one `SUBAGENT_TYPE`.

The attempt-2 resume added D34–D35:

- **D34:** Tasks 1–7 are adopted from git evidence, and attempt 1's report is retired in its own commit.
- **D35:** the sync runs before sdd entry, so `DELIVERY_BASE` is the post-sync merge-base.

## Standards review provenance

- Reviewer: Claude fallback (one fresh native `reviewer`, Opus/high), isolated and
  read-only, against `REVIEW-CONTRACT.md`. Codex `plan-review` ran first on the
  same packet. It completed with exit 0, but its output failed validation: no
  JSONL event reported the selected model `gpt-6-astra` and effort `xhigh`.
  That is a metadata mismatch, not a capacity rejection, so the one-time native
  fallback ran, and Codex was not retried. The earlier Codex attempt, at
  launch 4, had hit its usage limit.
- Base `affa05e7392caeb456f92b4dad0850bbd01b4d86`, plan reviewed at `a4ccbd6`;
  focus none.
- Findings: 0 Blocking, 5 Should-fix, 2 Discussion. All 7 were verified against
  the live worktree and accepted, with 0 rejected and 0 deferred. S1 is D31
  (Task 2). S2 is D32 (Task 8). S3 fixes Task 6's determinism test and red
  count. S4 is D33, as Task 6's row literals. S5 fixes Task 1's red-phase
  list. D1 is D33, Task 7's two conditional members. D2 is D33, Task 5's
  shared `SUBAGENT_TYPE`.

---
