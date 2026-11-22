# ADR-delivery-015 — Tests carry a tier and CI reports suite time growth

- **Status:** accepted
- **Decided in:** issue 1385 (owner sprint brief v2, ledger D3 and D4)

## Context

Test tiers were implicit: every test sat in one recipe or another with no name for why. The suite's times were kept only to order starts, and CI recorded no times, so a pull request that added a minute to the suite said nothing about it. The suite's parallel wall time moves from 7.9 to 11.6 minutes between runners with the same members ([the measurements](../../../archive/agent-workflow-tests-time-2026-11-17.md)), so the wall alone cannot show growth.

## Decision

- D1. Three tiers, `fast`, `integration` and `nightly` (owner). The first two run in the suite today, the third never does.
- D2. CI keeps each completed run's suite time and every member's time as an artifact (owner).
- D3. The growth threshold is the planner's: 60 s, strictly greater, compared before any rounding, and `--threshold` tunes it.
- D4. The tier runners are the ones in the standard's table: `agent-workflow-tests` for `fast` and `integration`, which share the suite today, and `evals`, `console-screenshots`, `agent-installed-skill-tests` and `agent-activated-skill-tests` for `nightly`.
- D5. A test declares its tier in the file, as `TIER` in a Python module or a `TIER=` line in a shell member, and the gate checks the test files added after 9282d2a404f2. A test file is one named like a test or listed by a runner recipe. A nightly test must be listed by a nightly recipe. A missing base commit fails the gate.
- D6. A member's time is its own wall seconds, and the runner speed factor is the median of head over base across the members common to both with at least 1.0 s in the base, and 1.0 with none. Growth is head minus factor times base, compared unrounded and rounded to 0.1 s only for display.
- D7. The baseline is the Actions cache from main's green push runs, keyed `suite-timing-<sha>`, restored by the base sha with a `suite-timing-` fallback. It needs no token permission.
- D8. Two non-required jobs read the timings. The required job gains `SUITE_RUNNER_REPORT` and an upload step with `if: ${{ !cancelled() }}` after the suite step, so a completed red suite keeps its times and the job stays red. The required-job guard allows that one `if:` and nothing else, and `Suite Timing` runs after a red suite too.
- D9. The new module has no command-table row and the change adds no glossary term.

## Considered options

- **Parallel wall time.** Rejected: too noisy between runners.
- **Downloading main's artifact through the API.** Rejected: it needs `actions: read`, against the permission pins.
- **The committed `suite_timings.json` as the baseline.** Rejected: stale by design.
- **Marking all existing tests.** Rejected: churn on 232 files beside open pull requests.
- **An upload only after a green suite.** Rejected: it loses the times of a red run, which is when they explain the most.
- **`continue-on-error` on the suite step with a later step that fails on its outcome.** Rejected: the evaluating step then reports success, which the required-job guard exists to refuse.

## Consequences

- The first pull request after this lands, and any after a 7-day cache eviction, prints the no-baseline line.
- A suite that does not complete (cancelled, timed out, never started) uploads no artifact, and then `Suite Timing` fails to download one beside the already red required job.
- A red main push keeps no baseline, because failed members can end early.
- New CI steps must be classified in `tests/test_verification_command.py`.
- The fast and integration tiers can be split into separate jobs later without renaming a tier.
