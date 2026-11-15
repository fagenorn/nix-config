# ADR-release-013 — A Railway skip is also explained by an unchanged watched tree

- **Status:** accepted
- **Decided in:** the nodo-prod v0.51.1 park; extends ADR-release-007

## Context

The `railway-deploy` watch accepted a `SKIPPED` deployment only on CI evidence: every check run of the released commit green and never re-run, with the serving deployment the immediate predecessor at the commit's first parent. A release whose merge left one service's directory untouched parked `skip_unexplained` although Railway had skipped that service correctly and it still served the right content, because the merge commit's check runs did not meet that bar: two workflows each published a job named `lint`, and one name seen twice was read as a re-run. The check runs say why Railway may have skipped; they say nothing about what the service serves.

## Decision

A skip the CI route cannot explain is `satisfied` when the adapter itself shows that the service serves what the released commit would build:

- Railway states `meta.skippedReason` `No changes to watched files` on the skipped row;
- the first older row that is not itself `SKIPPED` is `SUCCESS` or `SLEEPING`, on the target branch, with a commit and the same `meta.rootDirectory`;
- GitHub's compare of that commit with the released commit shows it is an ancestor, returns fewer than 300 files, and names no path (nor a rename's previous path) under the root directory or equal to `meta.configFile`.

The whole root directory counts as watched, and the route is refused unless `meta.serviceManifest.build.watchPatterns` is absent or exactly `["**"]`: Railway's skip under `["**"]` with a root directory is the only pattern semantics the evidence shows, and its documentation describes patterns as read from the repository root, which would make any other pattern reach outside the root directory. A failed check stays `diverged`/`skipped_after_ci_failure`, and `superseded` and `silent_rollback` are judged first, as before.

On the CI route a check is one name within one check suite. A re-run adds a run of that name to the same suite and still leaves the route incomplete; same-named jobs of two workflows have a suite each and are two checks. A new workflow run of the commit is a new suite, so a failure there stays the latest run of its own check and reads `skipped_after_ci_failure` instead of being hidden by a green namesake.

The serving row is evidence for its own service whatever became of the release that deployed it. A release disposed `failed` because another service failed still leaves this service's `SUCCESS` deployment serving, so the adapter reads no release store.

## Considered Options

- **Railway's `skippedReason` alone** — rejected: it is Railway's claim about its own evaluation, and a row that failed, crashed or was removed since would still carry it.
- **The GitHub commit status Railway posts per service** — rejected: Railway posts success for a skipped deployment, so the status is green whether or not the service serves the commit.
- **The previous succeeded release's deployment** — rejected: a deployment's validity does not depend on the release's disposition, and the lookup would have refused the case that exposed this.

## Consequences

- Rows between the skipped one and the serving one may be older skips; any other status leaves the skip unexplained, since the service may then serve nothing.
- A comparison of 300 files or more is unproven, so a very large release that skips a service still parks and is closed by hand.
- An unexplained skip ends its references with `railway-skip:<service>/<ci gap>/<watch gap>`, so the park reason names the missing evidence; the v0.51.1 park recorded none.
