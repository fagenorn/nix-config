# Testing

These deltas bind every test in this repository. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P15. A test has one of three tiers

The tiers are:

| Tier | When it runs | What runs here |
|---|---|---|
| `fast` | every push | A member of the `agent-workflow-tests` recipe that needs only the source tree and the standard library and runs alone in seconds; CI's `Agent Workflow Tests` job runs it on every push of a pull request and of `main`. |
| `integration` | before merge | A member of the same recipe that needs more: git worlds with pinned ancestors, `nix shell`, node or spawned services; `just test` runs it on the final head and `Agent Workflow Tests` gates the merge on it. |
| `nightly` | slow or paid, off the merge path | Never a member of that recipe: `just evals` (model calls), `just agent-installed-skill-tests` (a host build), `just agent-activated-skill-tests` (an activated host) and `just console-screenshots` (a browser); run by hand or on a schedule and never gating a merge. |

([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

`just test-touched` runs the `fast` and `integration` members a branch touches: the touched test files, the test files named for or importing a changed module, the files naming a changed path, the engine's `tests/test_engine_*.py` when an engine module, procedure or test helper changes, and the lifecycle guard's adversarial table when the guard changes. When the branch changes a `.nix` file, `flake.lock` or another host build input, which CI cannot test because it builds no darwin configuration, it runs `just build` and then the whole suite, and its selection names that file. Deliveries run it with `lint` and `conformance` (Conformance over every rule, as the required check runs it) before a pull request (the contract's `workflow.verification_before_pull_request`), the engine's verify step included, and `Agent Workflow Tests` runs the whole suite on the pull request.

### P16. A new test file declares its tier

A Python module has a top-level `TIER = "<tier>"`, a shell member a line `TIER=<tier>`; `tests/test_suite_tiers.py` checks every test file added after commit 9282d2a404f2, found by its name or by its place in a runner recipe. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P17. A test joins its tier's runner

A `fast` or `integration` test is a member of `agent-workflow-tests`, and a `nightly` test is listed by one of the nightly recipes and never by `agent-workflow-tests`. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P18. CI reports suite time growth

CI's `Agent Workflow Tests` runs the suite as parallel shards, each running the members assigned it from the committed timings, and joins the shards' records into the `suite-timing` artifact: each completed run's suite time and every member's time, slowest first. A pull request whose member time grows by more than 60 s over `main`, after the runner speed factor, gets a line in the `Suite Timing` job summary, and its author justifies the growth in the pull request or moves the test to `nightly`. ([ADR-delivery-015](../areas/delivery/adr/015-tests-carry-a-tier-and-ci-reports-suite-time-growth.md))

### P19. A stress probe grows in bounded steps

A stress probe with large or deeply nested inputs fixes a finite cap on time and peak memory before it starts, starts at a size that fits in 1 GiB, grows in steps (for example doubling), measures time and peak memory at each step and stops before a step whose projected peak would exceed the cap or at the first step that grows faster than its input, never an unbounded loop or one giant input on a shared host. A test that proves a memory bound measures the peak at a small capped size (for example with tracemalloc at a nesting depth whose peak stays under a few hundred MiB) and passes only when that peak is within the claimed limit, never by running the large case. ([issue 1859](https://github.com/fagenorn/nix-config/issues/1859))
