# ADR-claims-009 — A release pull request holds the land lock of its head branch

- **Status:** accepted
- **Decided in:** issue 875 (design comment), amended by issue 901; extends ADR-claims-004 and ADR-claims-005

## Context

A release pull request merges the integration branch into the default branch, so its head is the integration branch itself: every landing moves the release head and restarts its required checks. The land lock could not stop that, because `acquire` accepted only a pull request based on the locked branch, and the holder was derived only from pull requests on that base.

A read-only spike on a real repository (integration branch `dev`, default `main`) settled what the forge's commit lookup lists for an integration tip. `GET commits/<tip>/pulls` listed the open pull requests on `dev` that had merged the tip in (six of the eleven open ones; the five that were behind were absent), and also the merged pull request whose merge commit the tip is. None of them has the tip as its head. Past release pull requests carry head ref `dev`, base ref `main` and the same repository on both sides, and `GET pulls?state=closed&head=<owner>:dev` lists them. So containment of the tip says nothing about who holds it, and the head rule of ADR-claims-004 already separates the release from every lander.

## Decision

`forge-claim land acquire --release` accepts only an open pull request whose head branch is `--branch` at `--sha`, in the same repository, with the repository's default branch as its base. Without the flag, eligibility is unchanged. The lock value is the release head, the integration tip.

Holder derivation needs no flag: besides the pull requests on the locked branch, it counts a same-repository pull request whose head is the locked branch at the lock sha, whatever its base. An open one holds the lock. A merged or closed one makes the lock stale, as for any holder; when the commit lookup and the closed listing of the branch show no pull request headed at the lock, one page of the pull requests headed by the branch, open and closed, is read to find it. Open ones are read too because the commit lookup can leave an open release pull request out while listing a merged lander whose merge commit the lock is; judged by that lander alone, a live release lock would read stale. A fork's branch of the same name is never counted. No new clock is added: a dead release falls to the 45 minute idle takeover of a waiting lander.

A lock contained in a same-repository pull request headed by the locked branch, whatever that pull request's head, never answers `moved`: the branch itself has reached that sha, so a caller that would have moved the lock takes it over as stale and is answered `acquired`, which makes it resync. This covers a lander whose pull request is the only open one containing a published release's lock, and a release whose head moved past its lock.

A waiting release follows its pull request (issue 901). Every landing ahead of a waiting release moves the release head, so a wait pinned to the sha it started with could never acquire behind a lander: the first real release lost three rounds to `no_open_pr`. Each poll of `acquire --release --wait` therefore reads the open pull requests headed by the branch, keeps the same-repository one based on the default branch, and attempts the lock at that pull request's current head. `--sha` is the caller's starting belief only, and `no_open_pr` means no such pull request is open. The answer keeps `sha` as given, names the head the lock is at in `lock_sha`, and adds `head_moved`. A one-shot `acquire --release` never follows: it is the release driver's pre-merge check, which must refuse a head that moved.

When that wait finds the lock held at `--sha` while the head is another sha, the lock is the release's own from before the move. It is released and acquired again, not moved: the wait sends the same compare-and-swap delete of `--sha` that `land release --sha` sends, then attempts at the new head in the same poll, in competition with every other waiter. The answer is `acquired` or `already_held`, never `moved`. A `moved` verdict tells a holder it kept the lock without a gap and may merge without a resync, which is false for a release whose branch advanced under it; the review of issue 875 found the same hazard for a lander. Deleting first adds no authority, since any caller may already release a lock at a sha it names, and it keeps the rule that the release never uses `moved`. The cost is that a waiting lander can take the lock in the gap; the release then waits behind it and follows the head again.

## Consequences

- A waiter's poll behind a live holder makes the same four forge calls as before. One more read is made only when no pull request headed at the lock is found on the branch, and `--release` reads the default branch once per invocation. A waiting release's poll is four calls before and after issue 901: the listing of the branch's open pull requests replaces the commit lookup of `--sha`. Releasing its own old lock costs one swap and one more attempt, once.
- A release that holds the lock across a long stop can lose it to a waiting lander after 45 minutes; the re-check below covers it.
- While a release's lock sits at a tip its pull request has moved past, the lock reads as held, by the lowest-numbered open pull request containing that tip (the release itself or a lander that merged the tip in), until the release releases it or a waiter's idle takeover passes. It reads stale at once, and a lander takes it, when only merged landers are seen to contain the tip: the release pull request was closed, or the commit lookup left it out.
- Any same-repository pull request headed by the locked branch at the lock counts as the holder, whatever its base; only `--release` checks the base.

## Obligations on the release driver

These bind the second pull request of issue 875, which makes the release core use the lock.

- When the release pull request's head is no longer the lock sha, release the old lock before anything else. A waiting acquire given that sha as `--sha` does this itself.
- After a waiting acquire, continue with its `lock_sha` as the release commit, for the preview and every later lock command.
- Immediately before publishing, run a one-shot `acquire --release --sha <current head>` and proceed only on `already_held`. Any other verdict, `acquired` included, means waiting again for the checks on the new head.
- Merge with `--match-head-commit`.
- Release the lock on every exit path.
