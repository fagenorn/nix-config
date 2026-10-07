# Rename `tinytask list --all` to `--include-done` (issue 3)

## Problem

`--all` reads as "all the things", but the only thing it does is stop filtering out
done tasks. A reader of `tinytask list --help` cannot tell what it adds.

## Solution

Rename the flag on `tinytask list` from `--all` to `--include-done`. The parser
option, the help text, the README example and the one existing test that exercises
the flag change together. Behaviour does not change: `list --include-done` shows
exactly what `list --all` showed, and bare `list` is untouched.

## Acceptance criteria

1. `tinytask list --include-done` behaves exactly as `tinytask list --all` does today.
2. `tinytask list --all` is a usage error (unrecognised argument).
3. `tinytask list --help` shows `--include-done` and does not mention `--all`.
4. No occurrence of the old flag name remains in the tool's code and docs (`tinytask/`, `tests/` and `README.md`). The `issues/` fixtures and the spec and plan that discuss the rename quote it and are out of scope.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Rename outright, with no deprecation alias | The issue's scope: the tool has one user, and criterion 2 requires `--all` to be a usage error | Keep `--all` as a hidden alias for one release |
| D2 | Change no code but the option, its one reader and the three places that name it | The issue's scope: no behaviour change | Refactor `list` filtering while renaming |
