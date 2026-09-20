# Task 2: Publish, dispatch, and record bounded Ubuntu evidence

**Files:** Modify `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes Task 1's signed, independently reviewed commit and its published feature ref; the issue owner's current lifecycle launch; `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches` using API version `2026-03-10`; and V1 records. Produces the retained original three-run evidence cohort, separately labelled non-passing/fallback rows, and only a documented keep-advisory decision after the cohort is evaluated (D9).

**Invariants:**

- The issue owner, never an unowned worker, repeats the lifecycle launch check and verifies the exact published feature head before every dispatch. The feature ref comes from owner context; do not hardcode a lifecycle identifier.
- The original initial cohort is exactly three serial manual attempts. Each accepted response must be HTTP 200 with `workflow_run_id`, `run_url`, and `html_url`. Validate the observed run's `workflow_dispatch` event, feature branch, and exact head before one bounded `gh run watch <workflow_run_id> --exit-status` foreground watch of 15 minutes.
- A complete `AGENT_WORKFLOW_OBSERVATION_V1=` JSON object with schema exactly `agent-workflow-observation/v1`, trigger `workflow_dispatch`, four raw-string outcomes, and non-negative integer elapsed seconds is a valid raw observation when its run/job completed on Ubuntu without cancellation or timeout. `suite: failure` remains a valid, non-passing observation. Unknown/missing/malformed records, cancellation, timeout, and setup failures are separately classified; job metadata fallback is labelled and never supplies raw outcomes or a passing result.
- Do not replace a failed, missing, or non-passing attempt to seek success, do not poll guessed run IDs, and do not mark Task 2 or the issue complete before all real evidence and the later lifecycle phases.

- [ ] **Step 1: Establish the owner-controlled preconditions**

The issue owner checks the current lifecycle launch, confirms Task 1's signed commit and independent task-review acceptance, and verifies that the published feature branch resolves to that exact commit. If any condition is false, leave Task 2 open and record no invented evidence.

- [ ] **Step 2: Dispatch one exact published revision at a time**

For the original three serial attempts, re-run the precondition guard, then POST the versioned GitHub workflow-dispatch API with the published feature ref. Accept only HTTP 200 structured responses containing non-empty `workflow_run_id`, `run_url`, and `html_url`; otherwise retain the failure detail in that cohort position and stop that attempt. Do not replace this response with a `gh run list` search, guessed-ID polling, or another attempt.

- [ ] **Step 3: Validate and watch the returned run**

Using the returned ID, retrieve the identified run and prove its event is `workflow_dispatch`, branch is the feature branch, and head SHA is the published SHA. Run `gh run watch <workflow_run_id> --exit-status` once in the foreground with a 15-minute timeout. Retain a watch timeout/cancellation/failure as evidence; do not dispatch a replacement attempt for that reason.

- [ ] **Step 4: Extract and record deterministic outcomes**

Read the returned run's log/summary record. Parse the single labeled JSON line exactly; copy run URL/ID, commit, job conclusion, all raw outcomes, elapsed seconds, and resolution/flake note to the ledger. A completed non-scheduled Ubuntu run with a complete valid record enters its original-cohort position even if `raw.suite` is `failure`; record the non-passing result, failure count, and the required observed-failure follow-up #160. For summary absence, cancellation, timeout, setup failure, or malformed/unknown raw data, retain the separate classification and metadata-derived conclusion/duration where available; leave unavailable raw outcomes missing. Never use fallback metadata to make a passing result.

- [ ] **Step 5: Verify the evidence boundary and commit only a qualified window**

Run: `rg -n 'AGENT_WORKFLOW_OBSERVATION_V1=|workflow_run_id|raw checkout|raw install_nix|raw provision_just|raw suite|elapsed|metadata fallback|keep advisory' .github/agent-workflow-observation.md`

Expected: exit 0 and show the deterministic fields and decision. After all three original cohort positions are recorded, write a truthful `keep advisory — initial three-run Ubuntu cohort evaluated` decision that includes the valid-observation count, non-passing suite count, every fallback/incomplete classification, and observed-failure follow-up #160 before any future promotion decision. If a cohort position lacks complete evidence, say so and do not claim it passed. Stage only the ledger, and create signed commit `docs(ci): record advisory workflow evidence`. Do not promote, PR, merge, close, or clean up.
