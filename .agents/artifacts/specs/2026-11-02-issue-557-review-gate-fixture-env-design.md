# Review-gate capture test: resolve the budget authority from the fixture — issue 557

Issue: https://github.com/fagenorn/nix-config/issues/557. Designed autonomously
(`from-issue --auto`); every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals":{"contract_change":{"value":"no","evidence":"test-only change; review_budget/review_gate interfaces untouched"},"concurrency_or_persistence":{"value":"no","evidence":"scopes os.environ inside one test via patch.dict; no locking or persisted state"},"open_design_questions":{"value":"no","evidence":"tests/test_review_history.py and test_review_issue121.py already wrap in-process describe() in patch.dict(os.environ, env, clear=True)"},"criteria_shape":{"value":"doubt","evidence":"two criteria; the post-merge failed=0 reading is a CI observation, not a pre-merge code check"}},"paths":["tests/test_review_gate.py"]}
Verdict: {"hits":["criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every push run to `main` since #227 reports the Agent Workflow Tests (advisory) suite as
`failed=1`. The failing test is `GateTest.test_capture_refuses_output_no_real_producer_emits`,
so a real regression in the suite shows up as one more failure on an already-red summary.

The test describes the `review-package` budget authority and runs `capture` in the test
process itself. The authority is the external `artifact-budget` command, resolved by name on
the process's `PATH`. Its source launcher then reads the implementation from `$HOME`. The
fixture builds an environment that points both at the source tree, but it passes that
environment only to subprocesses. The test's own calls therefore see the caller's
environment:

- **On a hosted runner** nothing is installed, so the description raises
  `BudgetError: budget authority unavailable`. This was reproduced locally by removing the
  installed command directory from `PATH`.
- **On a workstation** the description uses whatever authority the last `just switch`
  installed, not the source tree's. If that policy ever differs from the source policy,
  every refusal case is refused for a policy-identity mismatch, and the test passes without
  testing anything.

## Solution

Inside that one test, the authority description and every in-process `capture` call run
under the fixture's environment. This is the convention the other in-process review tests
already follow. The same block gains one positive control. With it, the test proves that the
authority it built accepts the unmutated producer output, so each refusal case is refused for
its own mutation.

This is the issue's second route for criterion 1: the CLI reaches the test the same way the
suite's other helpers do, through the fixture's source `PATH` and fixture `HOME`.

## Decisions

- **Fix locus (D1).** Only the test changes. `agent_tools.review_budget` keeps resolving
  `artifact-budget` by command name on `PATH`. `agent_tools.review_gate.capture` keeps
  inheriting the process environment. Neither interface changes.
- **Environment scope (D2).** One `patch.dict(os.environ, self.env, clear=True)` block covers
  `describe('review-package')` and every `capture` call in the test: all six refusal cases,
  the stderr-reason case and the new positive control. The producer run that yields the good
  bytes already passes the fixture environment explicitly, so it can stay outside the block.
  The `capture` children are `sys.executable -c` scripts. Those scripts run identically under
  the fixture environment, so no case changes meaning. Patching `os.environ`, which every
  thread in the process shares, is safe here: the suite runner gives each member its own
  process, and `unittest` runs a member's tests one at a time.
- **Positive control (D3).** Within the block, before the refusal cases, the unmutated
  producer bytes emitted with exit 0 must pass `capture` under the same authority with exit 0.
  The refusal cases and their table are otherwise unchanged.

## Test seams

- The seam is the existing test, at the in-process `describe`/`capture` API, using the
  `SourceProjectionFixture` environment. The change adds no new test, helper or fixture.
- **Prior art.** `test_review_history` wraps in-process `describe` and its consumers in the
  same `patch.dict(..., clear=True)`, and `retained_review_test_support.source_budget_env`
  documents that convention.
- **Verification.** Pre-merge, run the test locally with the installed `artifact-budget`
  directory removed from `PATH`, as a stand-in for the hosted runner. It is red before the
  change and green after it. Also run the project's configured verification. A design probe
  on 2026-11-02 confirmed both halves. With the fixture environment, the authority described
  without the installed directory on `PATH`, and the positive control passed with exit 0. An
  authority with a different policy digest refused the good bytes with
  `result policy identity mismatch`, which is what D3 guards against. On the hosted run, this
  file's other tests already reach `artifact-budget` through the fixture environment, both
  directly and through the `gate` subprocess, and they pass.
- **Criteria evidence (D4).** Criterion 1 is read from the Agent Workflow Tests (advisory)
  summary on the PR's hosted run. Criterion 2 is read from the push run on `main` after the
  merge, which must report `failed=0`. That reading belongs to the ship phase and is not a
  pre-merge check.

## Out of scope

- How `review_budget` resolves its CLI, the CI workflow and the `justfile`.
- Other tests' in-process `describe` calls. The latest `main` run shows this test as the
  suite's only failure.
- Pinning a refusal reason for each case, and the subprocess `gate`/`confirm` tests.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Test-only fix: scope the fixture env around the test's in-process calls; `review_budget` keeps by-name `PATH` resolution | `docs/standards/agent-helpers.md` rule 3 (an executable outside the package runs by its command name on `PATH`); issue scope boundary; `source_budget_env` convention used by ten review test files | A production resolution change contradicts rule 3 and widens a seam every review command shares. Putting the scripts dir on `PATH` in CI/`justfile` still fails: the launcher reads `$HOME/.agents/lib/python`, which is empty on the runner |
| D2 | One `patch.dict(os.environ, self.env, clear=True)` block covers `describe` and every `capture` call in the test | `test_review_history` wraps `describe` with the in-process calls that consume its authority; issue scope names describe/capture | Wrapping `describe` alone is enough today, but `capture` stays on the caller's env, so a later authority call inside it would quietly use the installed CLI locally and fail only on CI, as in this issue |
| D3 | Add a positive control: unmutated producer bytes with exit 0 pass `capture` under the same authority | the-bar "Tests that can fail"; `validate_result` checks policy identity before exit/budget agreement; the 2026-11-02 probe shows a mismatched authority refusing the good bytes; same test, within the issue's In scope | Per-case reason regexes pin English message text and grow the change. Relying on the subprocess gate tests misses this test's in-process authority |
| D4 | Criterion 1 is read from the PR's hosted advisory summary plus the local no-installed-`PATH` run; criterion 2 is the post-merge `main` push-run summary `failed=0`, owned by ship | triage `criteria_shape` doubt; the advisory job runs on `pull_request` and `push` | Claiming criterion 2 from the PR run reads a different event on a different commit than the one the issue names |
