# ADR-claims-012 — Waiters on the land lock queue in forge-clock order

- **Status:** accepted
- **Decided in:** issue 1001; extends ADR-claims-004 and ADR-claims-005

## Context

`forge-claim land acquire --wait` polled every 120 seconds and nothing ordered the waiters. A released lock went to whichever waiter polled first. One wait for a single pull request ran 49 minutes and lost two free windows of 43 and 50 seconds to landers that had arrived later, and the lock waits of one four-issue batch added up to 101.7 minutes.

Only ref operations and reads are available across hosts, and the hosts' clocks cannot be trusted against each other (ADR-claims-003).

## Decision

The queue decides only who tries. The lock is still granted by nothing but the create and the compare-and-swap of ADR-claims-004, so no queue state, true, false or forged, can make two holders.

A waiter registers as a ref `refs/agent-locks/land-wait/<branch>/<since>-<pr>-<beat>` at its waiting head. `<since>` and `<beat>` are seconds of the forge's clock, the `Date` header of the free `rate_limit` call, read once in every poll: `<since>` when the waiter first asked, `<beat>` at its last refresh. The name carries everything, so one listing (`GET git/matching-refs`) gives the whole queue and no commit object is written. A refresh creates the ref with the new beat and then deletes the old one.

- **Order.** A pull request's place is the smallest `<since>` of its live registrations, ties going to the smaller number. The clock is read before the registration is written, so two waiters that arrive within the seconds between one's clock read and its registration being listed can both find themselves first; the create then decides, as it did before. No host clock is compared.
- **Liveness.** A registration whose beat is more than 390 seconds (three polls and a margin) behind the forge's clock is dead: skipped, and deleted by whoever lists it. A waiter ahead whose pull request is not open is skipped and deleted too; only the oldest one ahead is read, so the check costs one call a poll.
- **Who tries.** A waiter with a live open pull request ahead of it creates no lock and takes none over, closed or idle. It still answers `already_held` and `moved`, which concern only its own lock, so a holder that runs `--wait` again is never held behind the queue.
- **The free-lock grace.** A waiter that has itself watched the lock free for 60 seconds tries whatever its place. A live first waiter takes a free lock within 20 seconds, so this costs the order nothing while it works and bounds what a hung or dead first waiter costs to a minute instead of 390 seconds.
- **Poll rate.** While nobody is ahead of it, a waiter reads the lock ref alone every 20 seconds between two polls and polls at once when it changed. The issue asked for the faster poll when the holder's pull-request state suggests a release is near; reading only the lock ref is cheaper than judging that state and sees every release, so the rate depends on the place alone.
- **A wait that runs into its bound keeps its place.** The issue asked that the registration be removed on `land-contended`. The delivery programs ask again at once after that answer, and a removed registration would send a pull request that waited 50 minutes to the back of the line. The registration is left instead, the next `--wait` of that pull request adopts the `<since>` of a registration still live, and one nobody comes back to dies after 390 seconds, passed after a minute by the grace above. Every other exit deletes the registration: the lock taken, `no_open_pr`, an error.
- **A wait that takes the lock in its first poll never registers.** It registers once an attempt did not give it the lock.
- **Not ordered:** a one-shot `acquire` and a client that predates this decision. They register nothing and take a free lock when they find one. The holders' rechecks before a merge are one-shot calls and are unchanged, at two forge calls.

`acquire --wait` answers two more members on success and on `land-contended`: `position` (1 is first in line) and `ahead` (the pull requests ahead, oldest first), as of its last completed poll.

## Consequences

- Forge calls of one waiter behind a held lock and behind another waiter: 9 per 120-second poll (was 5), of which 2 are writes of its registration and none is a write of the lock (was 1 refused create): 4.5 calls and 1 write a minute. The first in line reads no pull request ahead (8 per poll) and adds 5 reads of the lock ref between two polls: 6.5 calls a minute, about 390 an hour, with the same 1 write a minute. One call of every poll is the `rate_limit` read, which the forge does not count. A waiter no longer sends a create for a lock it read as held.
- Mixed fleet. Among registered waiters the order is first come, first served, within the tolerance above. An old client or a one-shot `acquire` is outside the order: it is never held back by the queue and cannot deadlock it, because registered waiters wait only for the lock, for a live registered waiter ahead, and never more than a minute before a free lock. A registered waiter can still lose a free window to an old client; only the first in line competes with them, with a poll six times as fast, and the waiters behind it do not compete until they are first. Strict order therefore holds only once every waiting host runs the new `forge-claim`.
- A waiter behind another no longer takes over a closed or idle lock. When the first in line starts a new `--wait` it starts a new 45-minute watch (ADR-claims-005), so the takeover of a dead holder's lock can come up to one watch later than the longest-waiting process alone would have made it. The first in line still completes it within one wait.
- A lock that is released and retaken between two polls of a waiter that is not first looks continuously free to it; after the grace it tries, which can cost a place, never the lock.
- Anyone who can write refs can forge a registration and so delay registered waiters by up to a minute per free window; the same party could already move or delete the lock.
- A listing reads one page of 100 registrations; more are not seen.
