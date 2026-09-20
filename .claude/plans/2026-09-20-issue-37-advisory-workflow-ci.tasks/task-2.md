# Task 2: Record completed pinned Ubuntu evidence

**Files:** Modify `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes the immutable `/private/tmp/issue-37-observations/cohort-summary.json` manifest and its raw artifacts; three V1 records for runs `35513790832`, `35514069941`, and `35514254859`; and the current `.github/agent-workflow-observation.md`. Produces a ledger that replaces its retired success-only definition with original-cohort, non-passing, and incomplete/fallback classifications, records the pinned cohort, and makes only the D9 keep-advisory decision.

**Invariants:**

- The completed cohort is exactly runs `35513790832`, `35514069941`, and `35514254859` at `d1094c968ea16818de8073889d25ea9f99bd8deb`; each is `workflow_dispatch`, completed on `ubuntu-24.04`, has one valid V1 record, successful raw checkout/install_nix/provision_just, raw `suite: failure`, and elapsed 111/122/121 seconds.
- A complete `AGENT_WORKFLOW_OBSERVATION_V1=` JSON object with schema exactly `agent-workflow-observation/v1`, trigger `workflow_dispatch`, four raw-string outcomes, and non-negative integer elapsed seconds is a valid raw observation when its run/job completed on Ubuntu without cancellation or timeout. `suite: failure` remains valid and non-passing. Unknown/missing/malformed records, cancellation, timeout, and setup failures are separately classified; metadata fallback never supplies raw outcomes or a passing result.
- The manifest's `qualifies: false` is retained raw historical D4 success-only output. Do not copy it to the ledger or use it as D9 validity; derive validity from the V1 record and preserve the suite failure separately.
- Do not dispatch, watch, poll, replace, or otherwise create a run. The original cohort is complete; no additional evidence may be collected for this decision.

- [ ] **Step 1: Verify the retained completed cohort**

Read `/private/tmp/issue-37-observations/cohort-summary.json` and the referenced immutable raw artifacts. Confirm its pinned head, three run IDs, V1 schema/trigger/raw values, runner, and elapsed seconds against the manifest. Treat the three historical dispatches and watches as complete facts; do not make any lifecycle, forge, or workflow call.

- [ ] **Step 2: Replace the ledger's retired success-only contract**

In `.github/agent-workflow-observation.md`, replace the definition requiring raw `suite: success` and the headings `## Qualifying observations` and `## Failed attempts`. Define `## Original cohort observations` as complete valid V1 records, whether passing or non-passing; add `## Non-passing suite observations` and `## Incomplete or fallback records`. State that the original cohort is fixed, `suite: failure` is valid but non-passing, and metadata fallback/incomplete evidence cannot become a passing result.

- [ ] **Step 3: Record the cohort and decision**

Record each run URL/ID, pinned commit, job conclusion, four raw outcomes, elapsed seconds, and resolution/flake note under `## Original cohort observations`. Record all three under `## Non-passing suite observations`: valid observations `3`, passing suite outcomes `0`, non-passing suite outcomes `3`, and incomplete/fallback records `0`. State `keep advisory — original three-run Ubuntu cohort evaluated`; cite follow-up #160 and say it must be resolved before any future promotion decision. Do not copy the manifest's legacy `qualifies` field.

- [ ] **Step 4: Assert the ledger decision exactly**

Run the following content assertions; any missing required value or surviving retired heading/definition fails the task:

```sh
set -euo pipefail
ledger=.github/agent-workflow-observation.md
for required in \
  '35513790832' '35514069941' '35514254859' \
  'd1094c968ea16818de8073889d25ea9f99bd8deb' \
  '111' '122' '121' 'valid observations: 3' \
  'passing suite outcomes: 0' 'non-passing suite outcomes: 3' \
  'incomplete/fallback records: 0' 'keep advisory' '#160' \
  '## Original cohort observations' '## Non-passing suite observations' \
  '## Incomplete or fallback records'; do
  rg -Fq -- "$required" "$ledger"
done
if rg -Fq -- '## Qualifying observations' "$ledger" ||
   rg -Fq -- '## Failed attempts' "$ledger" ||
   rg -Fq -- 'and has successful raw' "$ledger"; then
  exit 1
fi
```

- [ ] **Step 5: Verify and commit the consumed evidence**

Run: `git diff --check -- .github/agent-workflow-observation.md` and the Step 4 assertion.

Expected: both commands exit 0. A failure means the live ledger still contradicts D9 or lacks measured evidence. Stage only the ledger and create signed commit `docs(ci): record advisory workflow evidence`. Do not dispatch, promote, PR, merge, close, or clean up.
