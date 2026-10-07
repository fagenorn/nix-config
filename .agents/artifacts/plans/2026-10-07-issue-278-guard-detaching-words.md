# Guard Refuses Detaching Words Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The `PreToolUse` lifecycle guard refuses `nohup`, `setsid` and `disown`
globally and before any policy, naming `run_in_background: true` and
`launch-scope exec` as the routes (issue #278, slice S4 of the launch process
reaping design).

**Architecture:** One new policy-free pass, `detaching_word(command)`, in
`home/common/claude-code/lifecycle_guard.py` reuses `split_segments`,
`tokenize_segment` and `command_position_flags`, and `main` runs it right after
hook-input validation (per D1). `nohup` leaves `COMMAND_WRAPPERS` (per D1).
Spec: `.agents/artifacts/specs/2026-10-07-issue-278-guard-detaching-words-design.md`.

**Tech stack:** Python 3 standard library (the guard), `unittest` (the guard
suite), Nix (`just build` embeds and load-checks the guard).

## Global Constraints

- The guard stays standard-library-only and imports nothing from `agent_tools` (`docs/standards/agent-helpers.md`).
- The four guarded verbs, their grammars and their messages do not change (spec "No other behaviour changes"); the existing guard suite stays green unchanged.
- Refusal prefix is exactly ``lifecycle guard: detaching command `<word>` refused:``; tests assert only that prefix plus the substrings `run_in_background` and `launch-scope exec` (per D2).
- Long commands: `just build` / `just show-claude-settings` (up to 15 min) run in the foreground with Bash timeout 1800000, output to a log ending in an `exit=<status>` line; if the host backgrounds one, wait for that line within the same turn.
- Commits go through `launch-commit` with the dispatch's `Lifecycle worker:` values, SSH-signed, ending with the session's Co-Authored-By and Claude-Session lines.

## Test seams

- `tests/test_claude_permission_guard.py`, run with `CLAUDE_SETTINGS_PATH` naming a settings artifact; the suite invokes that artifact's registered guard (spec "Test seams").

## Delivery estimate and boundaries

Estimate: 3 changed files — the guard (~50 added lines), the guard suite (~90
added lines), one `CLAUDE.md` sentence. One review package; no slicing.

## Task index

Task 1 — Policy-free detaching-word refusal — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `CLAUDE.md` — full — [task-1.md](2026-10-07-issue-278-guard-detaching-words.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_detaching_words_are_refused_globally` |
| AC2 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_detaching_word_mentions_pass` |
| AC3 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_detaching_refusal_precedes_the_push_grammar` |
| AC4 | code | Task 1 | `just build` exits 0, the whole guard suite reports `OK` against the built settings artifact, and the `agent_tools` import grep in Task 1 Step 4 finds nothing |

## Decisions

The spec's `## Decision ledger` owns every decision: D1–D5 from design, D6
appended at planning (path-spelled evaluators and earliest-offset word naming).
