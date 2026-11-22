# ADR-delivery-016 — A live-fault verify run is next for a verify slot

- **Status:** accepted
- **Decided in:** issue 1434

## Context

A live fault is delivered in its own lane (ADR-delivery-013), yet its verify run waited behind ordinary runs for a verify slot: ADR-delivery-014 D8 promised no order among waiters, so a run that polled at the right moment overtook an older one, and a live fault could be overtaken by every ordinary run queued before or after it.

## Decision

- D1. A live-lane verify run is next for a slot when one frees, and never preempts a run in progress. The owner answered this in the sprint brief. The self-hosted CI ordering the same answer asks for, where queued live runs start first, is split to issue 1593, because nix-config's CI runs on GitHub-hosted runners.
- D2. `verify-slot run` takes the option `--live`, written before `--`. The delivery program passes it for every verification command of the live lane.
- D3. A live waiter registers in one marker file, `live-waiting.lock`, in the slot directory. It holds a shared `flock` on it while it waits, so any number of live waiters hold it at once, and an ordinary run reads it with an exclusive non-blocking probe. Ordinary probes take turns on a second file, `live-probe.lock`, which a live waiter never takes, so one probe's exclusive lock is never mistaken for a live waiter; a live waiter registers with a non-blocking lock retried inside its timed wait, so a stalled probe cannot hold it past `--wait-limit`; a marker that cannot be opened is a setup error, exit 2. The marker is not a slot and no slot count includes it. It is created with mode 0666 so every account of the host can lock it. The kernel drops the lock when the waiter dies, so nothing goes stale and nothing is recorded in the file, for the reason ADR-delivery-014 D2 gives.
- D4. An ordinary run checks the marker after it took a slot, with the other recheck, and gives the slot back while a live waiter holds the marker. A live waiter registers before its first try, so a slot freed after it registered is taken by an ordinary run only until that run's check, which then returns it; checking before the take would leave a window between the check and the take. The deferring run prints one line of its own, in place of the waiting line.
- D5. A live run drops its marker as soon as it holds a slot, or ends for any other reason, so a running live holder holds back nothing beyond its slot.
- D6. No order among live waiters and none among ordinary waiters is promised; every live waiter goes before every ordinary one. This amends ADR-delivery-014 D8: live waiters go before ordinary ones; ADR-delivery-014 D3 stands.

## Considered options

- **Preempting a running holder.** Rejected by ADR-delivery-014 D3 and by the owner: a run in progress is never stopped.
- **A per-waiter pid file.** Rejected: a pid can be reused and a file outlives a killed waiter, so a stale entry would hold ordinary runs back.
- **A check before the take only.** Rejected: it is racy, because a live waiter can register between the check and the take.
- **Ordering the CI runner queue.** Split to issue 1593.

## Consequences

- A steady stream of live waiters can starve ordinary runs. Accepted, because live faults are rare.
- Between two `--wait-limit` attempts of the verify clerk the marker is briefly absent, so an ordinary run can take a slot in that gap.
- A live waiter ended by SIGKILL frees the ordinary runs at once.
