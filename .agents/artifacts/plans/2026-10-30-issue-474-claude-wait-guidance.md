# Claude-Compatible Wait Guidance Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** No skill tells an agent to chain a check onto a foreground `sleep`; every former `no-wait-loops` site names Monitor with an until-condition or one short bare `sleep N` call, and from-issue ends the turn on a blocker another session owns.

**Architecture:** Task 1 rewrites the `no-wait-loops` clause in its one constant (`CONTRACTS` in `test_dispatch_contracts.py`) and in all nine carriers at once, guarded by a new contract class in `test_workflow_skill_contracts.py` that bans the chained shapes across the three skill trees and checks both wait forms at each former site (D1, D2, D4, D7). Task 2 renames from-issue's external-wait item in the Suspension procedure and adds the class's from-issue check (D3). The clause shrink funds the rule, so no instruction ceiling moves (D5).

**Tech stack:** Markdown skill documents, Python 3 standard library `unittest` and `re`, `just`, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-30-issue-474-claude-wait-guidance-design.md` (a bare "Dn" cites its `## Decision ledger`; D1–D6 come from design and grill, and this plan appended D7). Issue: https://github.com/fagenorn/nix-config/issues/474

## Global Constraints

- Base `be4292708ff96d5b3da1fa3d09c48ea1ae609fba` (`origin/main` at planning); spec commit `edc73af8`. Tasks run in index order.
- Files this plan changes, and no others: the nine carriers `home/common/agent-skills/skills/sdd/{implementer,task-reviewer,re-review,correctness-reviewer,conformance-reviewer}-prompt.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`; and the tests `home/common/agent-skills/tests/test_dispatch_contracts.py` (the `no-wait-loops` constant only) and `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one appended class). sdd's final review adds its acceptance record beside this plan.
- Unchanged: the agent definitions under `home/common/claude-code/agents/` (they keep only `own-commands`), the other three clauses, `REMAINDER_PLACEHOLDER`, the **Interim child results** paragraphs, orchestrate-issues' background observer `sleep <wait_seconds>`, `home/common/codex/`, every helper and hook, and every Instruction Budget gate file including `home/common/agent-skills/instruction-load.json` (D5, spec § Out of scope).
- Write every dictated text byte for byte, including its line breaks and indentation. The wrapping was measured: with both tasks applied, hot bytes move implementation-owner +5 (13 B headroom left), from-issue-controller +23 (22 B left), orchestrated-issue-owner +8 and orchestration-dispatcher −3. A re-wrap is a plan deviation, because it can break the 13 B margin. Never add the `instruction-budget-raise` label and never raise a ceiling (D5).
- `docs/standards/agent-helpers.md` rule 3 holds: no `sys.path` edit and no import from `test_dispatch_contracts.py` in `test_workflow_skill_contracts.py`. Rule 6's phrase-pin exception covers only the class this plan adds (D4, D7).
- Process custody: every test, build or gate command runs in the foreground from the worktree root as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, written `launch-scope exec … --` below, with the stated timeout. `<R>`, `<I>` and `<W>` come from the dispatch's `Lifecycle worker:` line. Scratch lives under what `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>`; they are SSH-signed and end with the session's attribution trailer. Never push, never `just switch`.
- **Wait-class tests** (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ClaudeCompatibleWait 2>&1 | tail -4'`.
- **Skill contract tests** (timeout 900 s): `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -4'`. At the base: `Ran 232 tests`, `OK (skipped=3)`.
- **Budget** (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`, whose last line must be `check: pass`.
- **Installed tier** (timeout 3600 s; about 3 min on mbp): `launch-scope exec … -- bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 | tail -4'`. It runs `just build` first, then checks the carriers in the built home's `.claude/skills` and `.agents/skills` views.
- Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Budget command.

## Test seams

- The dispatch-contract suite (existing, `test_dispatch_contracts.py`): `SourceTreeContractsTest`, `InstalledTreeContractsTest`, `StrayCopyGuardTest` and `CheckerMutationTest` cover the new clause through the changed `CONTRACTS["no-wait-loops"]` constant alone.
- The new class `ClaudeCompatibleWaitContractsTest` in `test_workflow_skill_contracts.py`: the ban and its pattern self-test, the per-site wait forms and the from-issue rule (D4, D7).
- The Instruction Budget gate, `just agent-instruction-budget`, with no raise label (D5).

## Delivery estimate and boundaries

Estimates: 11 files; about 24 changed lines of skill text across the nine carriers, 3 lines in the constant and about 80 added test lines. One review package. No independent slice is needed.

## Task index

Task 1 — The Claude-compatible wait clause in its constant and nine carriers — `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_dispatch_contracts.py`, `home/common/agent-skills/skills/sdd/implementer-prompt.md`, `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/re-review-prompt.md`, `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md` — full — [task-1.md](2026-10-30-issue-474-claude-wait-guidance.tasks/task-1.md)
Task 2 — End the turn on a blocker another session owns — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-30-issue-474-claude-wait-guidance.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::ClaudeCompatibleWaitContractsTest::test_no_skill_document_chains_a_check_onto_a_foreground_sleep`, with `::test_the_shapes_match_the_chained_forms_and_spare_the_rest` proving the shapes, run by `just agent-workflow-tests` |
| AC2 | code | Task 2 | `ClaudeCompatibleWaitContractsTest::test_each_former_site_names_both_claude_compatible_waits` (added by Task 1) and `::test_from_issue_ends_the_turn_on_another_sessions_blocker` (added by Task 2) in the same file, run by `just agent-workflow-tests` |
| AC3 | code | Task 2 | `just agent-workflow-tests` passes on the final head, run by sdd's final gate; Task 2's Skill contract tests are its focused subset |

## Decisions

- The clause text and its meaning: per D1. One host-neutral clause in the shared tree: per D2. Agents that arm Monitor follow the existing rules: per D6.
- The end-the-turn rule's place and wording: per D3.
- The contract class: per D4, with its region-free site check, its fragment fixture and its shell argument class per D7 (appended by this plan).
- No ceiling moves, and the dictated wrapping keeps every profile under its ceiling: per D5.

## Standards review provenance

- **Reviewer:** Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), fresh isolated read-only thread.
- **Base SHA:** be429270; plan reviewed at commit 9720281c.
- **Focus:** none configured.
- **Findings:** 0 blocking, 0 should-fix, 0 discussion items; 0 accepted, 0 rejected, 0 deferred. Unknowns: the reviewer ran no verification commands, by contract.
- **Fallback:** not used.

---
