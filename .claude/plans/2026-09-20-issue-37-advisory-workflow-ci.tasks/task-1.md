# Task 1: Add the measured advisory CI job

**Files:** Modify `.github/workflows/ci.yaml` and `tests/test_branch_protection.py`; create `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes current CI triggers/concurrency/permissions and `just agent-workflow-tests`. Produces plain job key `agent-workflow-tests`, reported name `Agent Workflow Tests (advisory)`, and an empty three-row observation record.

**Invariants:**

- Run on `ubuntu-24.04` for PRs, main pushes, and manual dispatch, but skip schedules; add no path filter.
- Set `timeout-minutes: 10`; do not add `needs`, a matrix, job-level `continue-on-error`, or a job permission override.
- Stable `started`, `checkout`, `install_nix`, `provision_just`, and `suite` steps preserve raw outcomes with step-level continuation. An `always()` summary writes raw outcomes and elapsed seconds to `$GITHUB_STEP_SUMMARY`.
- The complete protection payload remains semantically identical: only `Nix Eval` from app `15368` is required.
- The record says no Ubuntu evidence exists and three real raw suite outcomes can yield only keep-advisory.

- [ ] **Step 1: Write the failing offline contract test**

Add this `WorkflowShape` test; it must fail on the base because the job is absent.

    def test_advisory_workflow_suite_job_is_a_measured_observation(self):
        names = job_names()
        self.assertIn("Agent Workflow Tests (advisory)", names)
        block = job_blocks()[names["Agent Workflow Tests (advisory)"]]
        body = "\n".join(block)
        self.assertIn("    if: github.event_name != 'schedule'", block)
        self.assertIn("    runs-on: ubuntu-24.04", block)
        self.assertIn("    timeout-minutes: 10", block)
        self.assertNotIn("    continue-on-error: true", block)
        self.assertNotIn("    needs:", block)
        for step in ("started", "checkout", "install_nix", "provision_just", "suite"):
            self.assertRegex(body, rf"(?ms)^      - id: {step}$.*?^        continue-on-error: true$")
        self.assertIn("nix shell --inputs-from . nixpkgs#just --command just --version", body)
        self.assertIn("nix shell --inputs-from . nixpkgs#just --command just agent-workflow-tests", body)
        self.assertRegex(body, r"(?m)^        if: \$\{\{ always\(\) \}\}$")

Also assert `required_contexts() == ["Nix Eval"]`; retain the existing full-payload equality assertion.

- [ ] **Step 2: Run the focused test and observe failure**

Run: `python3 -m unittest tests.test_branch_protection -v`

Expected: FAIL because the advisory job name is absent from `job_names()`.

- [ ] **Step 3: Implement the workflow and observation template**

Add the plain job with the interface and invariants above, independent of `nix-eval`. Do not edit either existing job. The provisioning command is exactly `nix shell --inputs-from . nixpkgs#just --command just --version`; the suite command is the same prefix followed by `just agent-workflow-tests`.

Give the first step ID `started` and make it emit an epoch output. Give checkout, Nix install, provisioning, and suite exactly the IDs in the invariants and mark each measurement step `continue-on-error: true`. The final summary uses `if: ${{ always() }}`, labels values as raw outcomes, and emits all five outcomes and elapsed seconds. It must never call completed observation a successful suite.

Create `.github/agent-workflow-observation.md` with the job purpose; a three-run non-scheduled Ubuntu window; a table for run URL/ID, commit, GitHub job conclusion, raw checkout/Nix/provision/suite outcomes, elapsed seconds, and Nix resolution/flake note; and `keep advisory — evidence not yet collected`. State that timeout/cancellation may lack a summary and must use GitHub job conclusion/duration.

- [ ] **Step 4: Verify changed seams**

Run: `python3 -m unittest tests.test_branch_protection -v` — expected PASS, including advisory-job and unchanged required-check assertions.

Run: `just agent-workflow-tests` — expected PASS; a failure means the workflow contract is not ready to ship.

Run: `just build` — expected PASS with only the known system-to-hostPlatform rename warning.

Run: `git diff --check -- .github/workflows/ci.yaml tests/test_branch_protection.py .github/agent-workflow-observation.md` — expected exit 0.

- [ ] **Step 5: Commit the advisory slice**

Stage exactly the three task files and create signed commit `ci: observe agent workflow tests`.
