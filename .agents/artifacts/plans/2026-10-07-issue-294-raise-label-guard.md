# Raise-Label Guard Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The Claude `PreToolUse` lifecycle guard refuses any `gh` invocation that adds the `instruction-budget-raise` label, the global frame says only the user applies it, and the repository `CLAUDE.md` records the rule's limits, with the PR passing the `Instruction Budget` gate unlabelled.

**Architecture:** Task 1 adds a fifth, mention-gated, context-free `label` operation to `home/common/claude-code/lifecycle_guard.py` beside the four existing verbs, reusing its splitter, tokeniser and evaluator detection, and judged before any `Context` is built; its adversarial rows go into `tests/test_claude_permission_guard.py`. Task 2 adds the frame sentence, cuts the redundant `doc-grounded-questions/REFERENCE.md` sentence that pays for it, and amends the `CLAUDE.md` guard bullet.

**Tech stack:** Python 3 standard library (`os`, `re`, `shlex`), `unittest`, Nix/home-manager (unchanged wiring), Markdown.

Spec: `.agents/artifacts/specs/2026-10-07-issue-294-raise-label-guard-design.md`.

## Global Constraints

- The guard stays standard-library only and imports nothing from `agent_tools`. Its policy schema (`POLICY_KEYS`), store wrapper, hook registration and the 22-entry allow surface (`EXPECTED_ALLOW`) stay unchanged (spec "The label operation", D2).
- The four existing verbs (`merge`, `pr-create`, `branch`, `push`) keep their exact behavior: `GUARDED_LITERALS` and `GUARDED_TOKEN_LITERALS` are not edited, and every existing test stays green unchanged (D1, D5).
- The label name is the one module constant `RAISE_LABEL = "instruction-budget-raise"`; matching is a case-insensitive substring test (D1, D2).
- Only adding is refused; `--remove-label` passes (D3). The rule is restated in `AGENTS.md` only, never in a skill (D3).
- No edit to `home/common/agent-skills/instruction-load.json`, to the gate's files, or to `.github/`; `instruction_load tighten` is not run (D4).
- No test pins the `AGENTS.md` sentence (`docs/standards/agent-helpers.md` rule 6).
- Guard tests run the installed store hook, so every guard-test command rebuilds first and reads the generated settings (D6):
  `just build >/dev/null && CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest <selection> tests/test_claude_permission_guard.py 2>&1 | tail -15`
- Run every command from the worktree root, in the foreground, with a timeout of at least 1800 s for any command that runs `just build`.
- **Final gate** (sdd's final gate, once, on the final head; no task runs it as a per-task gate): `just build`, `just agent-workflow-tests` and the full guard suite (the D6 command with an empty `<selection>`), each with a 3600 s timeout, and `PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main` (= `just agent-instruction-budget`) **without** `--raise-label`, which must print `check: pass`.

## Test seams

- The installed hook executable, through `tests/test_claude_permission_guard.py`'s `run_guard` / `invoke_command_in` (JSON payload on stdin, settings-registered command). New methods go in the adversarial-table section. No in-process import of `lifecycle_guard`.
- The `Instruction Budget` gate: `agent_tools.instruction_load check --base origin/main`, no label.
- `just build` (builds the guard wrapper and the settings the guard test reads).

## Delivery estimate and boundaries

Estimates only. Four changed files plus this plan and the spec: about 60 added lines in `lifecycle_guard.py`, about 110 added test lines, one 59-byte sentence in `AGENTS.md`, a 116-byte cut in `REFERENCE.md`, and one amended `CLAUDE.md` bullet. One slice, far from any review-package boundary. Corpus growth is net −55 B by the spec's arithmetic (D4); a trial of exactly these two doc edits against `origin/main` (`ef2c1cb8`) printed `check: pass`.

## Task index

Task 1 — The guard refuses adding the raise label — home/common/claude-code/lifecycle_guard.py, tests/test_claude_permission_guard.py — full — [task-1.md](2026-10-07-issue-294-raise-label-guard.tasks/task-1.md)
Task 2 — Frame sentence, budget offset and CLAUDE.md limits note — home/common/agent-guidance/AGENTS.md, home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md, CLAUDE.md — full — [task-2.md](2026-10-07-issue-294-raise-label-guard.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_raise_label_additions_are_refused_in_every_spelling`, `::test_raise_label_refusal_precedes_every_other_verb` and `::test_other_label_edits_and_mentions_pass`, run by the D6 command |
| AC2 | code | Task 1 | `just build` locally (final gate) and the required `Nix Eval` CI job on the PR |

## Decisions

Tasks rest on spec rows D1–D5 and on the plan-level rows D6 (the guard suite runs against the built settings, outside `agent-workflow-tests`) and D7 (label findings are refused before any other verb is adjudicated).

---
