# Whole-File Deletion Evidence Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A review range that deletes a file outright, where that file's diff record is larger than the review-package member limit, packages as `complete/within_budget`. The record is replaced by a bounded `whole-file-deletion` generated-evidence entry, `artifact-budget` validates the entry strictly, and the sdd reviewer prompts carry its corroboration rule.

**Architecture:** Task 1 teaches `artifact-budget`'s manifest validator the new kind through a closed per-kind dispatch, with one blob-identity helper shared with the EF designer side. Task 2 teaches the generator (`python/agent_tools/review_actual.py`) to read each record's `--name-status -z` operation and to build the deletion entry from the base blob for an oversized `D` record, after the EF designer builder. It also generalises the candidate builder's kind check, makes the shared tree lookup read literal paths, and adds one README sentence. Task 3 rewrites the generated-evidence paragraph of the four sdd reviewer prompts, pins both kind literals as machine text, and raises the two breached `implementation-owner` hot ceilings with a labelled-raise note.

**Tech stack:** Python 3 standard library (`unittest`, `hashlib`, `subprocess`), Git plumbing (`diff --name-status -z`, `ls-tree --literal-pathspecs`, `cat-file`), Markdown skill prompts, the JSON instruction-load model and its `agent_tools.instruction_load` gate, and Just.

Spec: `.agents/artifacts/specs/2026-10-25-issue-439-whole-file-deletion-design.md`. Its `## Decision ledger` rows are cited by ID; this plan appends D13 and D14. Issue: https://github.com/fagenorn/nix-config/issues/439.

## Global Constraints

- Base `3f4c5072746747c44bee51b1a24c13288923b27f` (`origin/main` at planning). Tasks land in index order, each on top of the one before.
- The evidence shape, qualification rules and validator rules are the spec's (§ Evidence shape, § Which records qualify, § Validator), per D1–D6 and D11.
- Unchanged in every task: `home/common/agent-skills/artifact-budget-policy.json` (no budget is raised), `RECORD_POLICY` and `PACKING_POLICY` in `review_actual.py` and their digests, `python/agent_tools/review_forecast.py`, `review_projection.py`, `review_issue100.py`, `review_issue121.py`, `review_task7.py`, `home/common/agent-skills/skills/sdd/final-review.md` and `home/common/agent-skills/skills/ship-issue/REVIEW.md` (D8, D12, D14).
- If a retained review replay test (`tests/test_review_issue100.py`, `test_review_issue121.py`, `test_review_task7.py`, their compact twins, projection, history, witness, derivation, replay or evidence) fails, stop as BLOCKED with its failing lines. Never re-derive an anchor in this slice.
- `home/common/agent-skills/instruction-load.json` changes only in Task 3, and only as D9 and D13 say. Only the user applies the `instruction-budget-raise` label: never apply it, never ask a tool to apply it.
- Comments, docstrings, README and prompt sentences describe the code as it behaves at that task's commit. In code and tests, write "issue 439", never a bare `#439`. The instruction-load note keeps its existing `#NNN` form. No `TODO` or `FIXME`.
- Run every long command, each test and gate included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, and end with the session's trailers. Scratch files live under the root that `launch-scope scratch …` prints.
- Focused test form (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <test files> [-k <name>] 2>&1 | tail -6'`.
- Final gate (sdd, once on the final head): `just agent-workflow-tests` (19 min at base; timeout 3600 s; ends `OK (skipped=3)`) and `just build` (timeout 3600 s; on this Linux host it runs `nixos-rebuild build --flake .#anis-desktop`).
- Known flake: in one full-suite dry run of this plan's changes, `tests/test_review_projection_cases.py::IndependentPositiveCases::test_cheaper_unrelated_descendant_is_excluded_with_real_standalone_parity` failed its `count-objects` assertion, because the fixture repo's loose objects were repacked mid-test. It passed on six isolated reruns. If the final gate fails on that assertion alone, re-run that test in isolation, record both outputs in the final report and re-run the gate once. A second failure is BLOCKED.

## Test seams

- The `review-package` CLI, end to end, through `python -m agent_tools.review_package` with the source `artifact-budget` on PATH (`home/common/agent-skills/tests/test_review_package.py`, `ReviewPackageCliTest`).
- `actual_inputs_from_trees`, called directly in the same class, for the literal-path case (D11).
- The candidate builder `pack_input` (`tests/test_review_pack.py`, `ActualSelectionTest`), for the closed kind set (D6).
- `artifact-budget check --kind review-package` as a subprocess (`home/common/agent-skills/tests/test_artifact_budget.py`, `ArtifactBudgetCliTest`).
- Skill machine text through `SDD_MACHINE_TEXT` (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, per D10).
- Gates: `just agent-instruction-budget` with and without `--raise-label`, `just agent-workflow-tests` and `just build`.

## Delivery estimate and boundaries

Estimates only: 12 changed files plus this plan and the spec ledger. `review_actual.py` grows by about 65 lines and `artifact_budget.py` by about 45. The four prompts grow by 137–180 B each, `instruction-load.json` by two values and one note sentence, and `python/README.md` by one paragraph. `test_review_package.py` grows by about 215 lines, `test_artifact_budget.py` by about 85, `tests/test_review_pack.py` by about 20 and `test_workflow_skill_contracts.py` by about 5. That is about 25 KB of diff in one review package, with no file record near the 64 KB member limit. Task 1 can be delivered on its own. Task 2 needs Task 1, because its CLI tests publish through the validator. Task 3 can be delivered on its own but describes behaviour that Tasks 1–2 deliver.

## Task index

Task 1 — `artifact-budget` validates `whole-file-deletion` evidence — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-1.md](2026-10-25-issue-439-whole-file-deletion.tasks/task-1.md)
Task 2 — The generator replaces an oversized whole-file deletion with bounded evidence — `python/agent_tools/review_actual.py`, `python/README.md`, `home/common/agent-skills/tests/test_review_package.py`, `tests/test_review_pack.py` — full — [task-2.md](2026-10-25-issue-439-whole-file-deletion.tasks/task-2.md)
Task 3 — Reviewer prompts name both kinds, with the labelled budget raise — `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/re-review-prompt.md`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-25-issue-439-whole-file-deletion.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_review_package.py::ReviewPackageCliTest::test_oversized_whole_file_deletion_uses_bounded_evidence` (exit 0, `complete/within_budget`, `interface_version` 2 per D7, exactly one entry equal to the independently computed shape). It fails at base with exit 3. |
| AC2 | code | Task 2 | `test_review_package.py::ReviewPackageCliTest::test_oversized_in_place_modification_still_stops` and `::test_oversized_rename_with_edit_still_stops` (exit 3, `decompose_required`, `member_bytes`), with `::test_exact_rename_of_an_oversized_file_keeps_its_rename_record` per D2. |
| AC3 | code | Task 1 | `home/common/agent-skills/tests/test_artifact_budget.py::ArtifactBudgetCliTest::test_whole_file_deletion_evidence_is_strict_in_a_v3_manifest` (a v3 manifest is accepted; a non-null head, a null base and each malformed base exit 2 with empty stdout). |
| AC4 | code | Task 3 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_sdd_documents_carry_their_machine_text`, where both kind literals are pinned in the task, conformance, correctness and re-review prompts (D8, D10). |
| AC5 | code | Task 3 | sdd's final gate on the final head: `just agent-workflow-tests` ends `OK` and `just build` exits 0. The PR head's required CI then runs `just agent-workflow-tests` (`ci.yaml`) and the Instruction Budget check, which passes once the user applies the label (D9). |

## Decisions

- Validator: closed per-kind dispatch and the shared blob-identity helper per D6, with the v3 acceptance case per D7 (Task 1).
- Generator: qualification by `--name-status -z` status per D1 and D14; renames per D2; binary deletions per D3; `line_count` per D4; EF first per D5; the closed kind check per D6; the literal tree lookup per D11; the per-record scope per D12 (Task 2).
- Prompts: the four prompts per D8; the machine-text pin per D10; the wording and the raise to 133,142 B per D9 and D13 (Task 3).

---
