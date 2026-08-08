# tinytask — context and glossary

tinytask is a single-user backlog you drive from the terminal. It has no server, no
daemon, and no dependencies outside the Python standard library. Everything it knows
lives in one file on disk.

## Glossary

- **Task** — one unit of work. Has an `id`, a `title`, and a `state`. Nothing else;
  every request to bolt a new field on gets weighed against "does the file stay
  readable by a human with `cat`".
- **Backlog** — the ordered list of every Task in the task file, done ones included.
  "The backlog" always means *all* tasks; the default `list` view is a *filtered* view
  of it, not the backlog itself.
- **State** — exactly two values, `open` and `done`. There is no `in-progress`, no
  `blocked`, no `cancelled`. A state that is not one of the two is a hard error at
  construction time, not a warning.
- **Task file** — the JSON document holding the backlog, `tasks.json` unless `--file`
  says otherwise. It is the whole database.
- **Store** — the object that owns reading and writing the task file. It is the only
  code allowed to touch the file.

## Invariants

- Ids are assigned by the Store, monotonically, and never reused — a `done` task keeps
  its id forever so that scripts and shell history stay meaningful.
- The Store rewrites the whole task file on every mutation, atomically. Partial writes
  are not a state the program can observe.
- The CLI is the only layer that prints. `tinytask.store` and `tinytask.model` never
  write to stdout or stderr — they raise or return.
- Listing output is one task per line, tab separated, `id<TAB>state<TAB>title`. People
  pipe this into `cut` and `awk`; the column order is a contract, not a detail.

## Deliberately out of scope

Priorities, due dates, tags, assignees, sub-tasks, sync between machines, and anything
that needs a schema migration. Proposals in those directions need an ADR before code.
