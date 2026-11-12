# ADR-claims-011 — A holder refreshes its land lock through a beat ref

- **Status:** accepted
- **Decided in:** issue 971; extends ADR-claims-005

## Context

A landing train holds the land lock at one sha from its first landing's acquire to its car merge. The first two real trains needed about 31 minutes of car checks and the lock sat unchanged for about 35, ten short of the 45-minute idle takeover of ADR-claims-005. A checks wait long enough to cover the full suite with margin (40 minutes, plus the 6-minute further wait) crosses that bound.

The holder could not say it was alive. A waiter restarts its watch only when the lock's oid changes; the lock's value is the holder's pull-request head, so the holder cannot change it, and a one-shot `acquire` at the same sha answers `already_held` and writes nothing. Releasing and retaking the lock would hand it to any waiter in between. ADR-claims-005 rules out clocks and event timestamps.

## Decision

A second ref, the beat `refs/agent-locks/land-beat/<branch>`, carries the refresh. `forge-claim land refresh --sha <sha>` writes nothing and answers `not_held` unless the lock is at `--sha`; otherwise it moves the beat one step and answers `refreshed`: the beat is created at `--sha` when absent, else swapped by compare-and-swap to the first parent of its value, and deleted when that value is a root commit. A waiter reads the beat in every poll that finds the lock held, and a beat that differs from the one it read before restarts its watch exactly as a changed lock does.

The beat walks down history instead of toggling between two values, because several steps of one train refresh side by side: two refreshes between two polls of a waiter must not bring back the value it read last.

Still no clock is read and nothing is persisted by a waiter. The beat's value means nothing; only its change counts. It holds nothing and releases nothing, and nobody needs to delete it.

The train's checks steps run the refresh at the start of every round of their wait, a round being 8 minutes at most (`deliver-batch.js`, `TRAIN_REFRESH_MIN`).

## Consequences

- A waiter's poll behind a held lock makes one more call, the beat read.
- A waiter built before this decision ignores the beat and still takes a refreshed lock over after 45 minutes, so the longer train wait is safe only once every host that lands on the repository runs the new `forge-claim`.
- A holder that stops refreshing is taken over 45 minutes after its last refresh, as before from its last lock change.
- Anyone who can write refs can move the beat and so delay a takeover; the same party could already move or delete the lock.
- A serial landing does not refresh: its lock moves whenever its head does, and the residual of ADR-claims-005 stands for it.
