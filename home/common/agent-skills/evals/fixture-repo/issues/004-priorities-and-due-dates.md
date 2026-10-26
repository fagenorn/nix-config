# Issue 4 — priorities and due dates

## Problem

The backlog is a flat list. When it grows I cannot tell what to do first, and nothing
reminds me that a task has a date attached. I want to rank tasks and give some of them a
due date, and to see both from the terminal.

## Proposal

One feature across the model, the store, the CLI and the docs.

- A task gains `priority`: one of `low`, `normal`, `high`, default `normal`.
- A task gains an optional `due`: an ISO date (`YYYY-MM-DD`), absent by default.
- The store loads task files written before this change: a task without the fields is a
  `normal` task with no due date.
- `tinytask add TITLE [--priority P] [--due YYYY-MM-DD]` creates a task with them.
- `tinytask list --sort id|priority|due` orders the listing, `id` being the default.
  `--sort priority` orders high, then normal, then low, ties by id. `--sort due` puts
  dated tasks first in date order (ties by id), then undated tasks by id.
- `tinytask list --long` prints `id<TAB>state<TAB>priority<TAB>due-or-dash<TAB>title`, with
  `-` for a task that has no due date. Bare `list` keeps printing `id<TAB>state<TAB>title`.
- `tinytask edit ID [--priority P] [--due D | --clear-due]` changes a task and echoes it in
  the bare `list` shape. `--due` and `--clear-due` together are a usage error, and so is
  `edit` with none of the three options.
- The README usage section and the backlog area's `CONTEXT.md` glossary describe both new
  fields; the area's out-of-scope section no longer lists priorities and due dates.

## Acceptance criteria

- [ ] [code] A task has `priority` (`low`, `normal` or `high`, default `normal`) and an optional ISO `due`; an unknown priority or a date that is not `YYYY-MM-DD` is rejected when the task is built — measured: tests/test_store.py
- [ ] [code] The store loads a task file that has no `priority` or `due` as `normal` tasks with no due date, and a saved task round-trips both fields — measured: tests/test_store.py
- [ ] [code] `add --priority P --due D` creates the task with both; a bad priority or date exits non-zero with a message on stderr and nothing on stdout — measured: tests/test_cli.py
- [ ] [code] `list --sort priority` and `list --sort due` order tasks exactly as the proposal says, ties broken by id — measured: tests/test_cli.py
- [ ] [code] `list --long` prints `id<TAB>state<TAB>priority<TAB>due-or-dash<TAB>title`, and bare `list` and `list --all` print exactly what they print today — measured: tests/test_cli.py
- [ ] [code] `edit ID` changes the priority, sets a due date or clears it; an unknown id exits 1 with `no such task: <id>` on stderr; `--due` with `--clear-due`, and `edit` with no option, are usage errors — measured: tests/test_cli.py
- [ ] [code] The README usage section shows `--priority`, `--due`, `--sort`, `--long` and `edit`, and the backlog `CONTEXT.md` defines the two new fields — measured: a test in tests/test_cli.py that reads both files
- [ ] [code] `TINYTASK_ACCEPTANCE=1 python3 -m unittest tests.test_acceptance` passes — measured: that command

## Notes

`tests/test_acceptance.py` is the slow end-to-end check and stays skipped unless
`TINYTASK_ACCEPTANCE=1`; it takes a few minutes, so run it once the feature is done, not
on every edit. The ordinary suite, `python3 -m unittest discover`, stays fast.

The valid states stay as they are in `tinytask.model`; define the priority names once, in
the model, as `STATES` is.
