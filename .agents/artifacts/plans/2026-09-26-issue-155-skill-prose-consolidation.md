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
its ceilings. Task 8 syncs `origin/main`, generates the report, commits it
alone and runs every gate.

**Tech stack:** Python 3 standard library (`argparse`, `json`, `os`, `re`,
`subprocess`, `unittest`), the `agent_tools` package, Markdown skill prose,
`git`, `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-26-issue-155-skill-prose-consolidation-design.md`, D1–D28.

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
the model, its test file and the report. The skill documents lose about 1.6 KB
in total: E1 is about 65 bytes per entry, E2 about 165 bytes per file and E3
about 470 bytes. The module is about 520 lines. Tests grow by about 430 lines in
the new file and 110 in the three contract suites. The model is about 24 KB of
JSON, and the report is probably 40–60 KB of Markdown. The product diff exceeds
ship-issue's 20-file degraded-review bound, so ship runs the full two-axis
review.

Tasks run in index order. Tasks 1–4 are independently deliverable. Task 7's
ceilings must follow Tasks 1–3, because they are the post-edit values. Task 8
comes last.

The base suite at `61b9def` ran 1305 tests, OK (skipped=4), in about 700 s. A
planning probe applied every task to a scratch clone. The four contract suites
passed, and the 30 new instruction-load tests passed against the probe
implementation.

## Task index

Task 1 — One resolver statement per policy entry (E1) and its guard — `SK/{design,doc-grounded-questions,from-issue,grill-with-docs,research,ship-issue,ship-release,to-issues,wayfind,worktrees,writing-plans}/SKILL.md`, `CL/{codex-collaboration,orchestrate-issues}/SKILL.md`, `T/test_workflow_skill_contracts.py` — full — [task-1.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-1.md)

Task 2 — Fold the PATH fallback and the direct-acquisition restatement (E2, E3) — `SK/from-issue/SKILL.md`, `CL/orchestrate-issues/SKILL.md`, `SK/from-issue/AUTO.md`, `T/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-2.md)

Task 3 — Point ship-release at the shell-form home (E4) and guard checker mentions — `SK/ship-release/SKILL.md`, `T/test_shell_example_contracts.py` — full — [task-3.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-3.md)

Task 4 — Guard leaf clauses against copies outside enrolled regions — `T/test_dispatch_contracts.py` — low-risk — [task-4.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-4.md)

Task 5 — Instruction-load model core: load, validate, measure, ceilings — `IL`, `python/agent_tools/agent_model_matrix.py`, `T/test_instruction_load.py`, `justfile` — full — [task-5.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-5.md)

Task 6 — The `report` command and the `agent-instruction-load` recipe — `IL`, `T/test_instruction_load.py`, `justfile` — full — [task-6.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-6.md)

Task 7 — The live 36-profile model and its ceilings — `MODEL`, `T/test_instruction_load.py` — full — [task-7.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-7.md)

Task 8 — Sync, generate and commit the report, final gates — `.agents/artifacts/specs/<generation-date>-issue-155-instruction-load-report.md`, `MODEL` (ceilings and notes, only after a sync) — full — [task-8.md](2026-09-26-issue-155-skill-prose-consolidation.tasks/task-8.md)

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
and grill. Planning added D22–D28:

- **D22:** the matrix gets a text-level `parse_matrix`.
- **D23:** the roster rules — prompt source and grouping — give 36 profiles.
- **D24:** hot or conditional tie-breaks.
- **D25:** the case-exact tree reader.
- **D26:** ceiling-test slack and the meaning of `affected`.
- **D27:** gates run as `WORKFLOW_POLICY_SURFACE=source`.
- **D28:** D20's anchor move covers three tests, and E3 needs a whitespace-normalized union.

---
