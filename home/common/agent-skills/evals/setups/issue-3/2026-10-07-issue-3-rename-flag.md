# Rename `list --all` to `--include-done` Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `tinytask list --include-done` replaces `tinytask list --all`, and the old name appears nowhere in the tool's code and docs (issue 3).

**Architecture:** One argparse option in `tinytask/cli.py` is renamed, together with its single reader. The README example and the one existing test follow it. Spec: `.claude/specs/2026-10-07-issue-3-rename-flag-design.md`.

## Global Constraints

- Standard library only; `python3 -m unittest discover` from the repo root is the test command.
- No deprecation alias. `list --all` must be a usage error (argparse exit 2).
- No file outside `tinytask/cli.py`, `README.md` and `tests/test_cli.py` changes.
- No test, comment or doc may contain the old flag name, because the spec's criterion 4 bans it from `tinytask/`, `tests/` and `README.md`.

## Test seams

- The CLI through `main(argv)` in `tests/test_cli.py`, the seam the existing tests use.
- The removal of the old flag is checked from outside the committed tree (see Task 1's verification), never by a committed test.

## Task index

Task 1 — Rename the flag — tinytask/cli.py, README.md, tests/test_cli.py — full — [task-1.md](2026-10-07-issue-3-rename-flag.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 1 | `test_list_include_done_includes_done_tasks` in `tests/test_cli.py` under `python3 -m unittest discover` |
| AC2 | code (classified) | Task 1 | Task 1 verification: `list --all` run from outside the tree exits 2 |
| AC3 | code (classified) | Task 1 | Task 1 verification: `list --help` shows `--include-done` and no `--all` |
| AC4 | code (classified) | Task 1 | Task 1 verification: `git grep` for the old flag over the tool's code and docs prints nothing |
