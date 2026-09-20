# Task 2: Record the initial Ubuntu observation window

**Files:** Modify `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes three completed, non-scheduled GitHub Actions jobs named `Agent Workflow Tests (advisory)` from shipped Task 1. Produces three evidence rows and a documented keep-advisory decision; it changes neither workflow source nor branch protection.

**Invariants:**

- Every row contains a run URL/ID, commit, job conclusion, raw setup/suite outcomes, elapsed duration, and Nix resolution/flake note from real GitHub data; no local Darwin result qualifies.
- Cancellation, timeout, setup failure, missing raw suite outcome, or suite failure keeps the window incomplete and extends it. A completed observation check never implies suite success.
- After three complete raw suite outcomes, the only permitted decision is keep advisory. Promotion needs a future, separately reviewed protection-fixture and offline-test change.

- [ ] **Step 1: Query real observation jobs**

Run: `gh run list --workflow CI --json databaseId,headSha,event,conclusion,url --limit 50`

Expected: identify three non-scheduled runs containing the exact advisory job. If fewer than three exist, stop without editing the record; the evidence gate is incomplete.

- [ ] **Step 2: Capture job evidence before editing**

For each candidate run, run `gh run view <run-id> --json jobs,url,conclusion,updatedAt` and `gh run view <run-id> --log`.

Expected: capture the advisory job conclusion, elapsed duration, and raw step results from its summary/logs. Record a timeout or cancellation with no summary as incomplete; never infer success.

- [ ] **Step 3: Record only verified outcomes**

Fill exactly three rows only when every required field is observable. If a row is incomplete or has a non-success raw suite outcome, retain `evidence incomplete — keep advisory` and add no promotion language. With three successful raw suite outcomes, write `keep advisory — initial three-run Ubuntu window complete` and retain the stronger evidence bar for future promotion.

- [ ] **Step 4: Verify the evidence boundary**

Run: `rg -n "run URL|job conclusion|raw .*outcome|elapsed|resolution|keep advisory" .github/agent-workflow-observation.md`

Expected: exit 0 and show the required evidence columns plus a keep-advisory decision. If Step 1 found an incomplete window, leave this task open and do not claim this gate.

- [ ] **Step 5: Commit only after the evidence gate is met**

Stage only `.github/agent-workflow-observation.md` and create signed commit `docs(ci): record advisory workflow evidence`.
