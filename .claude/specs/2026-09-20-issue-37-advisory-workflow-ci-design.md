# Issue 37: advisory workflow-suite CI

## Problem

The workflow-contract suite protects lifecycle helpers, artifact boundaries, and
CI assertions, but it currently runs only on the author's machine. A pull
request can therefore pass the existing Linux CI while the suite cannot run on
Ubuntu. Making its first CI run a required check would turn unmeasured package
resolution, cache, and runtime behavior into a merge gate.

## Solution

Add one Ubuntu observation job that executes the existing workflow-suite
recipe. It checks out the revision, installs Nix as the existing jobs do, then
uses `nix shell --inputs-from . nixpkgs#just` so `just` resolves from the
checkout's locked Nixpkgs input. The job has a bounded timeout and is absent
from the branch-protection payload.

The job is a measured advisory wrapper. Checkout, Nix setup, and the suite each
have a stable step identifier and step-level `continue-on-error`; a final
`always()` summary writes one compact `AGENT_WORKFLOW_OBSERVATION_V1=` JSON
record, with its raw `steps.<id>.outcome` values and elapsed time, identically
to logs and `$GITHUB_STEP_SUMMARY`. The step conclusion becomes successful for the observation job, which
keeps the current all-check `gh pr checks --watch --fail-fast` shipping wait
from halting on an advisory failure. The summary distinguishes observation-job
completion from suite success. A setup failure remains visible as its raw
outcome and logs; cancellation or timeout may prevent the summary, so the
follow-up records the GitHub job conclusion and duration as authoritative for
those runs.

Run the job for pull requests to `main`, pushes to `main`, and manual dispatch;
skip the daily schedule. Do not add path filters. The recipe's broad contract
surface makes a narrow path list a weak observation sample, while the required
`Nix Eval` workflow continues to receive every PR event.

The initial implementation records raw setup and suite outcomes, elapsed time,
and Nix package-resolution/flake output in the Actions summary and logs. A
tracked observation record defines a fixed cohort of the original three
completed, non-scheduled Ubuntu manual runs, the fields to copy from those
runs, and a follow-up decision template. A complete valid V1 record counts as
an observation even when its suite raw outcome is `failure`; its non-passing
result remains explicit. The initial follow-up may only keep the job advisory,
and it must preserve every setup failure, suite failure, cancellation, timeout,
or unavailable/malformed record without replacing an attempt to seek a green
sample. Promotion is a separate future decision requiring stronger evidence, an
updated protection fixture/test, and disposition of the tracked observed
failure in issue #160.

## Decisions

- The advisory job uses the existing workflow permissions and runner shape,
  then runs `just agent-workflow-tests` through `nix shell --inputs-from .
  nixpkgs#just`. It does not install Python packages or activate a host
  configuration.
- The job has a distinct stable name, no dependency on the required job, and a
  ten-minute timeout. Its individual observation steps continue so the shipping
  watcher sees a completed advisory check, while the raw outcomes remain in the
  summary and logs.
- The observation record is the durable handoff from the advisory rollout to
  the later promotion decision. A successful local Darwin run is baseline
  context only and never counts toward the Ubuntu window.
- The existing required-check interface remains exactly one provider-bound
  `Nix Eval` context from GitHub Actions app ID `15368`.

## Test seams

- The existing branch-protection contract suite remains the offline seam for
  workflow shape, permissions, trigger behavior, and the exact required `Nix
  Eval` payload. New assertions prove the advisory job's explicit setup,
  timeout, non-scheduled behavior, and non-required name without broadening
  the required-context assertion.
- The existing `just agent-workflow-tests` recipe remains the execution seam.
  The first CI runs provide the new Ubuntu evidence rather than treating local
  execution as a platform substitute.
- The tracked observation record is the decision seam: it must hold actual run
  links/identifiers, GitHub job conclusion, raw setup/suite outcomes, elapsed
  duration, and package-resolution or flake result before a promotion proposal
  can be made.

## Out of scope

- Applying or changing live branch protection, adding a required context, or
  altering the sole `Nix Eval` context, app ID, job behavior, or permissions.
- Promoting the job or treating absent Linux evidence as evidence of reliability.
  Recording the original finite cohort truthfully, including non-passing valid
  observations, is the follow-up task's only allowed keep-advisory outcome.
- Changing the workflow-suite recipe, adding a Python dependency, activating a
  NixOS or Darwin host, or incorporating unmerged issues 98 or 100.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Run the suite as a visible advisory Ubuntu job before any protection change. | #37's 2026-09-19 audit acceptance and `CLAUDE.md` say the suite is local-only while `Nix Eval` is the required Linux gate. | Make it required immediately; Linux suite runtime and package-resolution evidence do not yet exist. |
| D2 | Use `nix shell --inputs-from . nixpkgs#just`, a ten-minute timeout, and PR/main/manual events while skipping the daily schedule with no path filter. | Nix supports `--inputs-from`; the checkout lock pins Nixpkgs `871b9fd…`; the local 762-test baseline is 118.505 seconds, and the suite's broad helper surface makes a path filter an incomplete sample. | Use the mutable registry `nixpkgs#just`, inherit unbounded/scheduled execution, or maintain a guessed path allowlist. |
| D3 | Use step-level continuation plus an always-run summary to separate completed observation from raw setup/suite result. | `gh pr checks --fail-fast` exits on any check failure; GitHub documents job-level continuation only as workflow success, while step `outcome` retains the pre-continuation result. | Job-level continuation, whose individual check conclusion is not the documented guarantee, or a failing advisory check that halts autonomous shipping. |
| D4 | Collect three non-scheduled Ubuntu raw suite outcomes, then make only a keep-advisory decision; any missing, failed, cancelled, or timed-out outcome extends the sample. | The audit requires a bounded observation window and evidence-grounded follow-up; the standards require truthful claims and observable tests. | Invent a long wait to force promotion, count local Darwin runs, or promote from incomplete Linux data. |
| D5 | Preserve the exact sole required `Nix Eval` provider-bound context and app ID 15368. | The checked protection fixture and live contract bind that context to the Linux evaluation job. | Add the advisory job to required checks in this rollout. |
| D6 | Report the advisory job as `Agent Workflow Tests (advisory)` and pin that name offline. | The job name is the human-facing check interface distinguishing a completed observation from the required `Nix Eval` gate. | Reuse or leave an unspecified check name, which obscures advisory status in CI output. |
| D7 | After Task 1 passes locally, is signed committed, and receives independent task review, the issue owner verifies the current lifecycle launch and publishes only the feature branch; Task 2 then dispatches and records evidence while the issue stays open. | The accepted Phase-5 review found shipping-after-SDD circular; lifecycle writes require the owner to re-check the active launch. | Have an unowned worker dispatch from an unpublished revision, or wait for PR/merge/closure before evidence can exist. |
| D8 | Make one labeled V1 JSON record the raw-outcome source in both logs and summary; parse it exactly and use GitHub metadata only as a labelled fallback for missing-summary cancellation/timeout status and duration. | The accepted review found that summary-only data was not deterministically retrievable and continued-step conclusions lose raw outcomes. | Infer raw outcomes from job/step conclusions or use an unstructured log scrape. |
| D9 | Supersede D4: evaluate the original finite cohort of three completed non-scheduled Ubuntu manual runs at the pinned published head as observations when each has one complete valid V1 raw record, including a raw `suite: failure`; retain non-passing counts and make only a keep-advisory decision. Never replace a failed attempt to obtain a green sample. Setup failure, cancellation, timeout, missing, malformed, or fallback-only records remain separately classified and cannot become passing outcomes. Cite observed publication failure follow-up #160 before any future promotion decision. | Run `35513790832` at `d1094c968ea16818de8073889d25ea9f99bd8deb` is a completed Ubuntu V1 record with successful checkout/Nix/just, `suite: failure`, and 111 seconds; excluding it would bias the required measured evidence and leave the D4 window unbounded. The existing `directory-before-first` failure is tracked by #160. | Count only successful suites, extend/retry the cohort for green samples, treat incomplete/fallback data as a passing record, or promote without the tracked-failure follow-up. |

## Planning revision provenance

Accepted Phase-5 dispositions B1, B2, S1, and S2 came from
`/root/issue37_plan_review`, reviewed at
`117e8cedcc5d4fa11b1ab972828b62604b431b2d` against `a656dd9`. The review was a
native independent first pass; the requested Sol/high model identity was not
attested by the reviewer runtime.
