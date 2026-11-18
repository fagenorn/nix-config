# ADR-console-043 — A merged console change not active on this host is one line in the Work column

- **Status:** accepted; amended by ADR-system-004, ADR-console-072
- **Decided in:** #1114

## Context

On 16 November the console ran stale after a console change merged: nothing on the page said that the host still ran the old build, so the owner learned it only by noticing the missing change. The change reaches the host only when the owner runs `just switch`, and the console is the one place the owner already looks. This decision gives the page one line that says a merged console change is not active on this host and what to run.

## Decision

**D1. The reading.** The console compares the files its own running package holds with the files of the same paths on origin's integration branch, by git blob id. The files are everything under `agent_tools/console/` plus each `agent_tools` module those files import, transitively, with the `__init__.py` of every package on the way. A path that differs, or a console file origin holds that the package does not, makes the line; a change elsewhere (docs, nix, other `agent_tools` modules the console does not import) shows none. The system revision is not used: it changes on every commit and reads `<sha>-dirty` for a dirty build, while the running package's own files are exact.

**D2. Origin as last fetched.** Origin is read from the checkout's `refs/remotes/origin/<integration branch>` as last fetched. The console never fetches: it writes nothing to a checkout, and every delivery step already fetches origin into the shared refs.

**D3. The checkout and the branch.** The integration branch is the project contract's `vcs.integration_branch`. The checkout named is the first registered root, by sorted root, whose origin tree carries `python/agent_tools/console/console.py`.

**D4. The line.** Exactly: "A console change merged and is not active on this host: run just switch in <root>." The command is `just switch`, the recipe both the macOS and the Linux `switch` of the justfile define; a test pins it to the justfile. The command is drawn in a code span in the system monospace stack, and the root breaks after a slash (ADR-console-037). When the checkout's own `HEAD` does not yet hold a changed file as origin does (or its read failed), the line instead ends "once it is updated to origin's integration branch", because `just switch` builds the local tree and would reinstall the same console. When nothing differs the page draws nothing, not an empty line.

**D5. Not counted.** The line is not an inbox item and not in the statement: the headline and the inbox count do not change, and no action is attached to it.

**D6. Placement.** The line is the first element after the Work heading, above the empty-fleet sentence and above the running sprint blocks, so it shows with no project registered.

**D7. The poll.** The activation thread reads once at start and then every 60 seconds, and runs only when a reader is given. The reading is held in memory and handed to the view; no row is logged.

**D8. A failed read keeps the line.** A root with no project contract, no remote-tracking ref, or an origin tree without the console entry is not a candidate. A git error, a timeout, an `OSError` or any other resolver refusal is a failed read: it is never read as "nothing differs". The service keeps the last reading and writes one line to stderr, as the tracker poll keeps its last read state.

## Consequences

- A scoped exception to ADR-console-001 (every fact is a log row and the view is rebuilt from the log): the activation reading is a recomputable observation of this host, held in memory only and never logged, like the polled profile directories. After a restart the line is absent until the activation thread's start-time read, which recomputes it within one poll.
- ADR-console-002's Projects and Sprints bullets are amended: the line precedes the running blocks at the head of the Work column, and it names a command and the checkout's path.
- A scoped exception to ADR-console-035's no-command, no-path rule, which governs the registration flow.
- A host running an unmerged console change also shows the line until it is switched from the integration branch.
- Related: ADR-console-001, ADR-console-002, ADR-console-035, ADR-console-037.
