# Testing

These deltas bind every test in this repository. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P14. A test has one of three tiers

The tiers are:

| Tier | When it runs | What runs here |
|---|---|---|
| `fast` | every push | A member of the `agent-workflow-tests` recipe that needs only the source tree and the standard library and runs alone in seconds; CI's `Agent Workflow Tests` job runs it on every push of a pull request and of `main`. |
| `integration` | before merge | A member of the same recipe that needs more: git worlds with pinned ancestors, `nix shell`, node or spawned services; `just test` runs it on the final head and `Agent Workflow Tests` gates the merge on it. |
| `nightly` | slow or paid, off the merge path | Never a member of that recipe: `just evals` (model calls), `just agent-installed-skill-tests` (a host build), `just agent-activated-skill-tests` (an activated host) and `just console-screenshots` (a browser); run by hand or on a schedule and never gating a merge. |

([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P15. A new test file declares its tier

A Python module has a top-level `TIER = "<tier>"`, a shell member a line `TIER=<tier>`; `tests/test_suite_tiers.py` checks every test file added after commit 9282d2a404f2, found by its name or by its place in a runner recipe. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P16. A test joins its tier's runner

A `fast` or `integration` test is a member of `agent-workflow-tests`, and a `nightly` test is listed by one of the nightly recipes and never by `agent-workflow-tests`. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P17. CI reports suite time growth

CI keeps each completed run's suite time and every member's time, slowest first, as the `suite-timing` artifact. A pull request whose member time grows by more than 60 s over `main`, after the runner speed factor, gets a line in the `Suite Timing` job summary, and its author justifies the growth in the pull request or moves the test to `nightly`. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))
