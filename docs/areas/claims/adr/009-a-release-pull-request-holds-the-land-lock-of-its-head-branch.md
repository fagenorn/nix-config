# ADR-claims-009 — A release pull request holds the land lock of its head branch

- **Status:** accepted
- **Decided in:** issue 875 (design comment); extends ADR-claims-004 and ADR-claims-005

## Context

A release pull request merges the integration branch into the default branch, so its head is the integration branch itself: every landing moves the release head and restarts its required checks. The land lock could not stop that, because `acquire` accepted only a pull request based on the locked branch, and the holder was derived only from pull requests on that base.

A read-only spike on a real repository (integration branch `dev`, default `main`) settled what the forge's commit lookup lists for an integration tip. `GET commits/<tip>/pulls` listed the open pull requests on `dev` that had merged the tip in (six of the eleven open ones; the five that were behind were absent), and also the merged pull request whose merge commit the tip is. None of them has the tip as its head. Past release pull requests carry head ref `dev`, base ref `main` and the same repository on both sides, and `GET pulls?state=closed&head=<owner>:dev` lists them. So containment of the tip says nothing about who holds it, and the head rule of ADR-claims-004 already separates the release from every lander.

## Decision

`forge-claim land acquire --release` accepts only an open pull request whose head branch is `--branch` at `--sha`, in the same repository, with the repository's default branch as its base. Without the flag, eligibility is unchanged. The lock value is the release head, the integration tip.

Holder derivation needs no flag: besides the pull requests on the locked branch, it counts a same-repository pull request whose head is the locked branch at the lock sha, whatever its base. An open one holds the lock. A merged or closed one makes the lock stale, as for any holder; when the commit lookup and the closed listing of the branch show no pull request headed at the lock, one page of the closed pull requests headed by the branch is read to find it. A fork's branch of the same name is never counted. No new clock is added: a dead release falls to the 45 minute idle takeover of a waiting lander.

The lock of a release pull request never moves. A release whose head moved releases its old lock and acquires again, and a lander whose pull request is the only open one containing a published release's lock takes it over as stale, not as its own earlier head.

## Consequences

- A waiter's poll behind a live holder makes the same four forge calls as before. One more read is made only when no pull request headed at the lock is found on the branch, and `--release` reads the default branch once per invocation.
- A release that holds the lock across a long stop can lose it to a waiting lander after 45 minutes, so it must re-check with a one-shot `acquire` before it publishes.
- While a release's lock sits at a tip its pull request has moved past, the lock reads as held by an open lander containing that tip, or by no pull request, until the release releases it or a waiter's idle takeover passes.
- Any same-repository pull request headed by the locked branch at the lock counts as the holder, whatever its base; only `--release` checks the base.
