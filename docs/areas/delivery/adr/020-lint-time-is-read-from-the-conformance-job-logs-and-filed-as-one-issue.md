# ADR-delivery-020 — Lint time is read from the Conformance job logs and filed as one issue

- **Status:** accepted
- **Decided in:** issue 1472 (per issue 1422, issue 1414, issue 1421)

## Context

Each new rule adds a lint that the never-rise check (ADR-project-contract-017) pays for twice, once on the merge base and once on the branch, and nothing measured what that cost. A slow Conformance run is felt by every change, yet no one was told which lint made it slow.

## Decision

**D1. A lint and its time.** A lint is one never-rise enforcer (`conformance_checks.never_rise_enforcers`), the rules that run on both sides. Its time is the wall time of its `find` on the merge base (the first call) plus the branch (any later call), in integer milliseconds, rounded per side. The total is the sum of every lint's two sides. The standards lint and the context-map lint run once and are not lints in this sense. The Ruff rules share one memoised Ruff run per revision and it is measured as it happens, so the first Ruff rule carries it.

**D2. The record.** The record is kept in the Conformance job log as exactly one stderr line, `lint-times v1 <json>`, printed after the report by `conformance run --lint-times` and only when an enforcer ran. The report, its facts and stdout are unchanged. Only the own-tree form of the rendered workflow gains `--lint-times`, which amends ADR-project-contract-015 D3 for that form; the locked form other projects commit is unchanged, so no other project's workflow goes stale. Nothing is committed.

**D3. Reading.** One listing of the newest 50 completed `push` runs of `conformance.yaml` on the branch, newest first, uses the first 20 whose `Conformance` job log carries a record. A run with no such job, a gone log (404 or 410) or no record line is skipped. A malformed record or a second record line is a `ForgeError`: exit 2, nothing filed.

**D4. The budget.** The budget is breached only when the median of the 20 totals is strictly above 60 000 ms. The slowest lint is the one with the highest median over the records that carry it; ties go to the lint id that sorts first.

**D5. One issue.** The marker is the whole line `<!-- agent:lint-time v1 -->`, recognised only on issues by trusted authors (the listing of `cleanup_issue.GitHubTracker`, ADR-delivery-017 D4 and D5). There is at most one open lint-time issue, counted apart from the cleanup issue. The command never asks, labels, comments or closes.

**D6. The workflow.** `.github/workflows/lint-time.yaml` runs on `push` to `main` only and grants `contents: read`, `actions: read` and `issues: write`. Its write set is the cleanup filer's. `actions: read` is added because the token must list runs and download job logs, and a permission a workflow does not name is `none`. One concurrency group that cancels nothing queues pushes one after another. A slow run never fails a change: the job is not a required context and the command exits 0 whatever it reads.

**D7. Output.** The command prints one JSON line: `{"action", "issue", "runs", "median_seconds", "slowest"}`. `lint-time observed` judges the newest Lint Time job's line for the evidence check.

**D8. Reviews.** Reviews of this change were Claude-only while Codex was out of quota.

## Consequences

- On a push run the base is the head, so the Ruff memo puts Ruff's whole cost on the first Ruff rule's base side.
- Another project gets no lint-time issue until it has a workflow and an own-tree flag of its own.
- Runs whose logs have expired are skipped.
- Rejected: an Actions artifact, because it adds an upload step to every rendered workflow and a zip download.
- Rejected: facts in the report, because the report carries no time and the failed never-rise facts already use the 8-key bound.
- Rejected: committed timings, because the issue forbids committing them.
- Rejected: always-on stderr output for `ci`, because it changes other projects' CI output.
- Rejected: counting lint-time issues against the one cleanup issue, because the two queues serve different work.
