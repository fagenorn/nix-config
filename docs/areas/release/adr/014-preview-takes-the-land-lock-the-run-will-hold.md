# ADR-release-014 — Preview takes the land lock the run will hold

- **Status:** accepted
- **Decided in:** issue 1376; amends ADR-release-008 for the land lock only and the sentence of ADR-release-011 that preview makes no lock call

## Context

A caller that held no land lock when it previewed got a runnable preview, and its first `run` then refused `land_lock_lost`: the one-shot check of `run` finds a free lock, takes it and refuses, because the head may have moved in between. Only the next preview and run could succeed, and each lost cycle is a CI wait of the release's required checks. The first such run after a preview cost about 4.5 hours on 20 Nov, together with the lifecycle guard's refusal of the merge.

## Decision

`preview` of a profile with a sync takes the land lock of the integration branch at the candidate commit with one one-shot `acquire`, through the router `run` uses, so the tracker credential stays excluded. It makes the call only when the plan is runnable and the merge is not yet satisfied. A free lock is taken, and the run's check then finds it already held. The preview keeps `already_held` and `acquired`, and a resumed release also keeps `no_open_pr`, which parks at its run. Every other answer makes the document not runnable, with no confirmations and the refusal `run` would raise for it: `moved` is `land_lock_lost`, `held_by` and `lost_to` are `land_lock_held`, and `error` is `land_lock_unavailable`. The document of such a profile carries `lock`, the answer of the acquire or null when no call was made. `preview` never releases the lock.

No other rule of ADR-release-008 changes: the preview creates no directory, no transaction and no store lock, calls no adapter, and its plan digest and tokens do not depend on the lock answer. `run` is unchanged: it makes its own one-shot check and refuses `land_lock_lost` when the lock was lost between the preview and the run.

## Consequences

- A preview that no run follows leaves the lock it took for the caller's stop rule or, failing that, the land lock's staleness rules: stale at once when the release pull request is merged or closed, else a waiting lander's 45 minute idle takeover.
- A preview can now be unrunnable for a lock reason, and the caller sees it in the document before it confirms anything.
- A lock lost between the preview and the run is still refused and creates nothing.
