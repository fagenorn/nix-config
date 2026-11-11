# ADR-claims-009 — A release pull request holds the land lock of its head branch

- **Status:** accepted
- **Decided in:** issue 875 (design comment); extends ADR-claims-004 and ADR-claims-005

## Context

A release pull request merges the integration branch into the default branch, so its head is the integration branch itself: every landing moves the release head and restarts its required checks. The land lock could not stop that, because `acquire` accepted only a pull request based on the locked branch, and the holder was derived only from pull requests on that base.

A read-only spike on a real repository (integration branch `dev`, default `main`) settled what the forge's commit lookup lists for an integration tip. `GET commits/<tip>/pulls` listed the open pull requests on `dev` that had merged the tip in (six of the eleven open ones; the five that were behind were absent), and also the merged pull request whose merge commit the tip is. None of them has the tip as its head. Past release pull requests carry head ref `dev`, base ref `main` and the same repository on both sides, and `GET pulls?state=closed&head=<owner>:dev` lists them. So containment of the tip says nothing about who holds it, and the head rule of ADR-claims-004 already separates the release from every lander.

## Decision

`forge-claim land acquire --release` accepts only an open pull request whose head branch is `--branch` at `--sha`, in the same repository, with the repository's default branch as its base. Without the flag, eligibility is unchanged. The lock value is the release head, the integration tip.

Holder derivation needs no flag: besides the pull requests on the locked branch, it counts a same-repository pull request whose head is the locked branch at the lock sha, whatever its base. An open one holds the lock. A merged or closed one makes the lock stale, as for any holder; when the commit lookup and the closed listing of the branch show no pull request headed at the lock, one page of the pull requests headed by the branch, open and closed, is read to find it. Open ones are read too because the commit lookup can leave an open release pull request out while listing a merged lander whose merge commit the lock is; judged by that lander alone, a live release lock would read stale. A fork's branch of the same name is never counted. No new clock is added: a dead release falls to the 45 minute idle takeover of a waiting lander.

A lock contained in a same-repository pull request headed by the locked branch, whatever that pull request's head, never answers `moved`: the branch itself has reached that sha, so a caller that would have moved the lock takes it over as stale and is answered `acquired`, which makes it resync. This covers a lander whose pull request is the only open one containing a published release's lock, and a release whose head moved past its lock.

## Consequences

- A waiter's poll behind a live holder makes the same four forge calls as before. One more read is made only when no pull request headed at the lock is found on the branch, and `--release` reads the default branch once per invocation.
- A release that holds the lock across a long stop can lose it to a waiting lander after 45 minutes; the re-check below covers it.
- While a release's lock sits at a tip its pull request has moved past, the lock reads as held, by the lowest-numbered open pull request containing that tip (the release itself or a lander that merged the tip in), until the release releases it or a waiter's idle takeover passes. It reads stale at once, and a lander takes it, when only merged landers are seen to contain the tip: the release pull request was closed, or the commit lookup left it out.
- Any same-repository pull request headed by the locked branch at the lock counts as the holder, whatever its base; only `--release` checks the base.

## Obligations on the release driver

These bind the second pull request of issue 875, which makes the release core use the lock.

- When the release pull request's head is no longer the lock sha, release the old lock before anything else.
- Immediately before publishing, run a one-shot `acquire --release --sha <current head>` and proceed only on `already_held`. Any other verdict, `acquired` included, means waiting again for the checks on the new head.
- Merge with `--match-head-commit`.
- Release the lock on every exit path.
