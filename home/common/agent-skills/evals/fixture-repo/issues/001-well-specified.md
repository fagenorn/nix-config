# Issue 1 — `tinytask list --state <state>` filter

## Problem

`list` has exactly two views today: open tasks (the default) and everything (`--all`).
There is no way to see *only* the done tasks, which is what I want at the end of a week
when I'm writing up what got finished.

## Proposal

Add a `--state` option to `tinytask list` that filters the backlog to a single state.

- `tinytask list --state open` — open tasks only (same set the bare `list` shows today)
- `tinytask list --state done` — done tasks only
- `--state` and `--all` are mutually exclusive; passing both is a usage error
- An unrecognised state is a usage error, not an empty result

## Acceptance criteria

- [ ] [code] `list --state done` prints only tasks whose state is `done`, in id order, in the existing `id<TAB>state<TAB>title` shape — measured: tests/test_cli.py
- [ ] [code] `list --state open` prints exactly what bare `list` prints for the same task file — measured: tests/test_cli.py
- [ ] [code] `list --state wibble` exits non-zero and writes a message naming the valid states to stderr, and nothing is printed to stdout — measured: tests/test_cli.py
- [ ] [code] `list --all --state done` exits non-zero with a usage error — measured: tests/test_cli.py
- [ ] [code] Bare `list` and `list --all` behave exactly as they do today, with no change — measured: tests/test_cli.py
- [ ] [code] `--state` appears in `tinytask list --help` — measured: a `--help` output test added to tests/test_cli.py
- [ ] [code] Tests cover each of criteria 1-5 with exact expected output lines — measured: tests/test_cli.py

## Notes

The valid states are already enumerated in `tinytask.model.STATES`; don't introduce a
second list of state names.
