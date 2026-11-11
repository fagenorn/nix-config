# ADR-release-011 — A two-branch release holds the integration land lock until it has merged

- **Status:** accepted
- **Decided in:** issue 875 (design comment); applies ADR-claims-009, extends ADR-release-006, ADR-release-008 and ADR-release-010

## Context

A release pull request's head is the integration branch, so every landing there moves the release head and restarts its required checks; with landers queued the release keeps losing a CI cycle. The cycle it loses is the wait for the preview to become runnable, before `run` exists, so a hold taken inside `run` would start too late. `preview` must stay write-free, and the driver has no checks wait of its own.

## Decision

The hold has two owners. The caller of the driver (the ship-release skill) acquires the lock of the integration branch at the release pull request's head, with a wait, once that pull request exists and before the first preview, and releases it whenever it stops short of a run, or before it starts again on a moved head. The driver never acquires for the caller and never waits: `preview` makes no lock call, and `run` makes one one-shot `acquire --release` at the candidate commit and proceeds only on `already_held`. A new release is checked before its transaction is created, so a refusal writes nothing; a resumed one is checked right before its merge is invoked, and gives custody up before it refuses. `acquired` or `moved` refuses `land_lock_lost`, `held_by` or `lost_to` refuses `land_lock_held`, and a check that cannot answer refuses `land_lock_unavailable`. The merge keeps `--match-head-commit`.

A run that began before the merge releases the lock at the candidate commit when it ends, unless it ends `confirm` or `wait` with the merge still to come: on `done`, on `attention` whether or not the merge happened, and before the post-release sync, so the sync pull request is never behind the release's own lock. `abandon` releases it too. The answer is the result's `lock` member, `{verdict, lock_sha, detail}`. The lock is kept across the confirmation stop, because dropping it there would let a landing move the head and forfeit the green run. Only a profile with a post-release sync (ADR-release-010) has a lock; every other profile makes no lock call and has no `lock` member.

## Consequences

- No clock is added. A release that dies holding the lock, a run whose effect raised, and a lock whose release failed all fall to the land lock's own staleness rules: stale at once when the release pull request is merged or closed, else a waiting lander's 45 minute idle takeover.
- A lock call that fails after publication is reported in `lock` and changes nothing else, as a failed sync does.
- A release held longer than 45 minutes at the confirmation stop can lose the lock to a waiting lander; `run` then refuses, and the caller acquires again and previews again.
- A landing that passed its own lock check before the release acquired is the one race left. It moves the head, and the release answers it as before: `release_pr_stale`, `confirmation_stale` or a merge refused by `--match-head-commit`.
- `release` now imports `claims.forge_land_lock`, through `release_lock` only.
