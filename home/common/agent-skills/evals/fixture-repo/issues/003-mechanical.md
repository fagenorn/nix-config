# Issue 3 — rename `list --all` to `list --include-done`

`--all` reads as "all the things" but the only thing it actually does is stop filtering
out done tasks. `--include-done` says what it does.

## Scope

Rename the flag on `tinytask list` from `--all` to `--include-done`. Update the help
text, the README example, and the existing test that exercises it.

No behaviour change: `list --include-done` shows exactly what `list --all` shows today,
and bare `list` is untouched. No deprecation alias — this tool has one user.

## Acceptance criteria

1. `tinytask list --include-done` behaves exactly as `tinytask list --all` does today.
2. `tinytask list --all` is a usage error (unrecognised argument).
3. `tinytask list --help` shows `--include-done` and does not mention `--all`.
4. No occurrence of the old flag name remains in the repo.
