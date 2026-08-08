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

1. `list --state done` prints only tasks whose state is `done`, in id order, in the
   existing `id<TAB>state<TAB>title` shape.
2. `list --state open` prints exactly what bare `list` prints for the same task file.
3. `list --state wibble` exits non-zero and writes a message naming the valid states to
   stderr. Nothing is printed to stdout.
4. `list --all --state done` exits non-zero with a usage error.
5. Bare `list` and `list --all` behave exactly as they do today — no change.
6. `--state` appears in `tinytask list --help`.
7. Tests cover each of 1-5 with exact expected output lines.

## Notes

The valid states are already enumerated in `tinytask.model.STATES`; don't introduce a
second list of state names.
