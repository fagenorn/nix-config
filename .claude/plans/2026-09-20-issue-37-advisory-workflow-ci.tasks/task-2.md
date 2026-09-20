# Task 2: Publish, dispatch, and record bounded Ubuntu evidence

**Files:** Modify `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes Task 1's signed, independently reviewed commit and its published feature ref; the issue owner's current lifecycle launch; `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches` using API version `2026-03-10`; and V1 records. Produces retained evidence rows and failed-attempt rows, then only a documented keep-advisory decision when three rows qualify.

**Invariants:**

- The issue owner, never an unowned worker, repeats the lifecycle launch check and verifies the exact published feature head before every dispatch. The feature ref comes from owner context; do not hardcode a lifecycle identifier.
- Initial dispatches are serial, limited to three, and each accepted response must be HTTP 200 with `workflow_run_id`, `run_url`, and `html_url`. Validate the observed run's `workflow_dispatch` event, feature branch, and exact head before one bounded `gh run watch <workflow_run_id> --exit-status` foreground watch of 15 minutes.
- Parse only a complete `AGENT_WORKFLOW_OBSERVATION_V1=` JSON object with schema exactly `agent-workflow-observation/v1`, trigger `workflow_dispatch`, four raw-string outcomes, and non-negative integer elapsed seconds. Preserve all attempts. Unknown/missing/malformed records, cancellation, timeout, and setup failures are honestly non-qualifying; job metadata fallback is separately labelled and never supplies raw outcomes.
- Do not retry a failed/missing attempt to seek success, do not poll guessed run IDs, and do not mark Task 2 or the issue complete before all real evidence and the later lifecycle phases.

- [ ] **Step 1: Establish the owner-controlled preconditions**

The issue owner checks the current lifecycle launch, confirms Task 1's signed commit and independent task-review acceptance, and verifies that the published feature branch resolves to that exact commit. If any condition is false, leave Task 2 open and record no invented evidence.

- [ ] **Step 2: Dispatch one exact published revision at a time**

For up to three serial attempts, re-run the precondition guard, then POST the versioned GitHub workflow-dispatch API with the published feature ref. Accept only HTTP 200 structured responses containing non-empty `workflow_run_id`, `run_url`, and `html_url`; otherwise retain the failure detail and stop that attempt. Do not replace this response with a `gh run list` search or guessed-ID polling.

- [ ] **Step 3: Validate and watch the returned run**

Using the returned ID, retrieve the identified run and prove its event is `workflow_dispatch`, branch is the feature branch, and head SHA is the published SHA. Run `gh run watch <workflow_run_id> --exit-status` once in the foreground with a 15-minute timeout. Retain a watch timeout/cancellation/failure as evidence; do not dispatch a replacement attempt for that reason.

- [ ] **Step 4: Extract and record deterministic outcomes**

Read the returned run's log/summary record. Parse the single labeled JSON line exactly; copy run URL/ID, commit, job conclusion, all raw outcomes, elapsed seconds, and resolution/flake note to the ledger. For summary absence, cancellation, or timeout, record metadata-derived conclusion/duration in the fallback fields and leave raw outcomes missing. Every non-qualifying outcome is retained in the failed-attempt section; only completed non-scheduled Ubuntu records with all required raw values and successful setup/suite enter the three-row window.

- [ ] **Step 5: Verify the evidence boundary and commit only a qualified window**

Run: `rg -n 'AGENT_WORKFLOW_OBSERVATION_V1=|workflow_run_id|raw checkout|raw install_nix|raw provision_just|raw suite|elapsed|metadata fallback|keep advisory' .github/agent-workflow-observation.md`

Expected: exit 0 and show the deterministic fields and decision. If fewer than three qualifying rows exist, leave Task 2 open; “declaring observation window complete” is out of scope only as a premature claim. With exactly three qualifying rows, write `keep advisory — initial three-run Ubuntu window complete`, stage only the ledger, and create signed commit `docs(ci): record advisory workflow evidence`. Do not promote, PR, merge, close, or clean up.
