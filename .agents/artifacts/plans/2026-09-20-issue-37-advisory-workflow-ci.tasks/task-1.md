# Task 1: Add deterministic advisory CI observation

**Files:** Modify `.github/workflows/ci.yaml`, `tests/test_branch_protection.py`, and `CLAUDE.md`; create `.github/agent-workflow-observation.md`.

**Interfaces:** Consumes current CI triggers/concurrency/permissions and `just agent-workflow-tests`. Produces job key `agent-workflow-tests`, reported name `Agent Workflow Tests (advisory)`, and the exact V1 record `AGENT_WORKFLOW_OBSERVATION_V1={"schema":"agent-workflow-observation/v1","trigger":"<event>","raw":{"checkout":"<outcome>","install_nix":"<outcome>","provision_just":"<outcome>","suite":"<outcome>"},"elapsed_seconds":<integer>}`.

**Invariants:**

- The job runs on `ubuntu-24.04` for PRs, main pushes, and manual dispatch; it skips schedules, has `timeout-minutes: 10`, no path filter, `needs`, matrix, job continuation, or permission override.
- `checkout`, `install_nix`, `provision_just`, and `suite` have stable IDs and their own `continue-on-error: true`. The summary is `always()`, labels each raw `steps.<id>.outcome`, and writes the byte-identical V1 JSON marker to both log and summary.
- The record uses `unknown` when a raw value cannot be observed, an integer elapsed time, and never turns a step conclusion into a raw outcome. The empty ledger separates valid structured observations, including a raw suite failure, from setup failure, missing/malformed summary, cancellation, timeout, and metadata fallback (D9).
- The protection payload remains exactly one `Nix Eval` context from app `15368`; `CLAUDE.md:23` says this advisory job runs in CI.

- [ ] **Step 1: Write failing offline contracts**

Add focused `WorkflowShape` assertions that parse the actual summary-shell body with a fixture event and temporary `GITHUB_STEP_SUMMARY`, then assert separately for each named measurement step: its exact ID, its immediately owned `continue-on-error: true`, and its own `steps.<id>.outcome` reference. Assert a missing step's continuation cannot satisfy another step. Assert the V1 marker, every JSON field (`schema`, `trigger`, four raw keys, `elapsed_seconds`), both output sinks, `github.event_name`, PR/main-push/manual triggers, schedule exclusion, commands, timeout, runner, lack of job continuation/needs, and advisory name. Retain the existing exact full branch-protection payload equality assertion.

- [ ] **Step 2: Run the focused test and observe failure**

Run: `python3 -m unittest tests.test_branch_protection -v`

Expected: FAIL because the advisory job and its V1 record are absent.

- [ ] **Step 3: Implement the workflow, ledger, and guidance**

Add the independent job. `started` emits an epoch value; checkout, Nix install, provisioning (`nix shell --inputs-from . nixpkgs#just --command just --version`), and suite (`nix shell --inputs-from . nixpkgs#just --command just agent-workflow-tests`) use the specified IDs and continuation. The `always()` summary computes elapsed seconds from `started`, substitutes `unknown` only for absent raw values, constructs the compact V1 JSON in the stated field order, and sends exactly that line through `tee -a "$GITHUB_STEP_SUMMARY"`; this makes it retrievable in logs and summary without a dependency.

Create the ledger with its schema, fields, three empty original-cohort slots, and separately labelled non-passing/fallback section. It requires the exact marker to parse all fields, retains a complete valid raw record with `suite: failure` as an observation, and separately classifies malformed/missing marker, `unknown`, cancelled/timed-out run/job, and setup failure. Treat GitHub job metadata as fallback only for cancellation/timeout/missing-summary status and duration; it never supplies raw outcomes or a passing result. Reserve a tracked-follow-up field for an observed suite failure before any future promotion decision (D9). Update `CLAUDE.md:23` to state that CI also runs this advisory suite while `Nix Eval` remains the sole required context.

- [ ] **Step 4: Verify changed seams**

Run: `python3 -m unittest tests.test_branch_protection -v` — expected PASS, including independent per-step, record, trigger, and full-payload assertions.

Run: `just agent-workflow-tests` — expected PASS; failure means the slice is not publishable.

Run: `just build` — expected PASS with only the known system-to-hostPlatform rename warning.

Run: `git diff --check -- .github/workflows/ci.yaml tests/test_branch_protection.py .github/agent-workflow-observation.md CLAUDE.md` — expected exit 0.

- [ ] **Step 5: Commit and hand off the bounded lifecycle action**

Stage exactly the four task files and create signed commit `ci: observe agent workflow tests`. After the local gates pass, the signed commit exists, and an independent task review accepts it, the **issue owner** checks the current lifecycle launch identity and publishes only the feature branch under the existing grant. Do not open a PR, merge, close the issue, or clean up. Task 2 remains open and normal SDD final review and ship follow only after real evidence.
