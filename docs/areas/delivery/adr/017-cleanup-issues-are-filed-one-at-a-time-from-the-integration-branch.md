# ADR-delivery-017 — Cleanup issues are filed one at a time from the integration branch

- **Status:** accepted
- **Decided in:** #1462 (per #1414, #1420)

## Context

The never-rise check (ADR-project-contract-017) stops a branch from adding violations of a rule, but nothing shrinks the violations the integration branch already holds: files over the 1,500-line limit stay over it until someone chooses to split them. #1414 asks for that work to reach the tracker as issues sized to one delivery, and #1420 asks for the comment rule's cleanup to go file by file.

## Decision

**D1. Counts at one revision.** Counts are read at one committed revision (default `HEAD`; in CI the pushed integration-branch commit) with the never-rise enforcers. `cleanup_issue.RULES` pairs each enforcer with its `batch` and `guidance`, and a test pins its enforcers to `conformance_checks.NEVER_RISE_ENFORCERS`, so a new enforcer cannot land without saying how its cleanup is sized and worded.

**D2. Selection.** The rule with the smallest count above zero is selected; equal counts take the earlier rule in `RULES`.

**D3. Listing.** Violations are grouped by file; files are ordered by (violations in the file, largest line in the file, path) ascending; whole files are taken while the total stays at most `batch`; the first file is always taken whole, even when it alone exceeds `batch`. A file is never split across two issues. B17's batch is 1, so each B17 issue is one file, the smallest first. The Ruff rules PY6 to PY13 share a batch of 10 violations.

**D4. Recognition.** An open issue is a cleanup issue when its author is trusted and any line of its body, trailing carriage return and spaces stripped, is exactly `<!-- agent:cleanup v1 rule=<id> -->`. Trusted is the login the workflow token files as, `github-actions[bot]`, or an `author_association` of `OWNER` or `MEMBER` (the convention of `look_marker.TRUSTED`). Title and labels are ignored.

**D5. Lookup.** The lookup lists every open issue through the REST listing, every page, not the search API, which lags, so a second run right after a filing sees it. A page that is not a list of objects is a `ForgeError` and nothing is filed.

**D6. Own workflow file.** The job is `.github/workflows/cleanup-issue.yaml`, not a job in `ci.yaml`, whose `contents: read` and no-job-permissions rule are pinned by tests. The file grants `contents: read` and `issues: write` only and runs on `push` to `main` only. One concurrency group with `cancel-in-progress: false` and `queue: max` runs pushes one after another.

**D7. Stored token.** `forge_api` drops token variables, so the job stores the workflow token with `gh auth login --with-token --insecure-storage` before the command runs; the command reads no token.

**D8. No asking, no closing.** The command never asks, labels, comments or closes: a stalled count only keeps its issue open.

**D9. Criterion.** The filed issue's acceptance criterion bounds both promises: the rule's total falls by the listed count and no listed file still has a violation of the rule, measured by `cleanup-issue violations --rule <id>`, because a total alone falls when some other file is fixed.

**D10. Writer and tip.** Before it files, the command checks that the account it files as would be trusted by D4 (the workflow token, which answers 403 to `GET user`, files as `github-actions[bot]`; otherwise the owner or an active organization member), and refuses with exit 2 when not, because an issue by anyone else is invisible to the next run, which would file a second one. With `--branch`, it also files nothing when the revision is no longer that branch's tip on the forge: a delayed run for an older commit would otherwise file work a newer merge completed. A listing item without a `body` field is a `ForgeError`, because its body could hold the marker.

## Consequences

- Each B17 cleanup issue is one file, the smallest first; a file is never split across issues.
- A marker written by an untrusted author is invisible, so an outsider cannot stop the queue.
- An issue closed by hand lets the next push file again.
- Up to 100 runs wait in the queue and GitHub cancels a run beyond that; the next push repeats its work.
- This change ships the command and this repository's workflow only: another project runs the job only once that project has a workflow of its own.
- Rejected: a label as the identity, because anyone with triage rights can add or remove it and it says nothing about the author.
- Rejected: the search API for the lookup, because its index lags and a second run could file a duplicate.
- Rejected: a job inside `ci.yaml`, because its token is read-only and tests pin that.
- Rejected: trusting any author's marker, because an outsider could then hold the queue shut.
- Rejected: a total-only criterion, because the total falls when some other file is fixed.
