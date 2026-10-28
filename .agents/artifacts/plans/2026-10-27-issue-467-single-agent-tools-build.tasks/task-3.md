# Task 3: JarBird-shape derive cases

Spec § Acceptance and § Test seams (Source); per D5, D9 and D10. Add the hermetic equivalent of the reporter's row-check shape at the existing source-command seam. The current code already handles it. The regression is red under pre-466 source, and green at this task's starting commit; no resolver or guard fix is expected.

**Files:**
- Modify and test: `tests/test_guard_policy.py`

**Interfaces:**
- Consumes: `DeriveTest.derived(repository: str) -> dict`, `GuardPolicyWorld.project(project_id, slug, *, integration_branch, publication_free, mutate) -> Path`, `contract`, `commit_contract`, and `git`. `GuardPolicyWorld.derive(repository, *, env=None)` runs the command from source and returns `(exit_status, report, stderr)`.
- Consumes: the existing `CONFIG` constant from `tests/actions_world.py`, the canonical JarBird `github-actions-health` configuration used by `DeployInspectTest`. Import it as `from .actions_world import CONFIG`; creating an HTTP server is unnecessary for derivation.
- Produces: the two exact `DeriveTest` test names in the code below and a test-only mutator `jarbird_deploy(contract) -> None`, a static method on `DeriveTest`.

**Invariants:**
- Both projects have slug `elevenyellow/jarbird`, project id `jarbird`, default `main`, integration `dev` and publication-free release profile `forge-main`.
- The first fixture puts the adapter only on `dev`, leaving `main`'s valid contract at the prior shape. The second publishes it on both branches. Both derive a row `main`/`dev`, no refused entries, the expected source commit and `forge-main` profile.
- The tests drive `guard-policy derive` through `GuardPolicyWorld`, never built wrappers. Guard code, fixture support and production package code stay untouched.
- Reporter-host AC1 and AC3 remain `human_pending`; these passing tests establish only their hermetic equivalents (D10).

- [ ] **Step 1: Add both fixtures and tests**

Add the CONFIG import and these members to `DeriveTest`:

```python
    @staticmethod
    def jarbird_deploy(contract):
        contract["bindings"]["deploy"] = {
            "adapter": "github-actions-health", "command": None, "config": dict(CONFIG)}
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = [
            "GITHUB_TOKEN", "GH_TOKEN"]
        contract["capabilities"]["deploy"]["support"] = "supported"

    def test_a_jarbird_shaped_project_derives_while_its_adapter_waits_on_dev(self):
        slug = "elevenyellow/jarbird"
        root = self.world.project("jarbird", slug, integration_branch="dev",
                                  publication_free=True)
        self.world.git(root, "checkout", "--quiet", "dev")
        contract = self.world.contract("jarbird", slug, integration_branch="dev",
                                       publication_free=True)
        self.jarbird_deploy(contract)
        self.world.commit_contract(root, contract, "deploy adapter on dev")
        self.world.git(root, "push", "--quiet", "origin", "dev")
        report = self.derived(slug)
        self.assertEqual(report["refused"], [])
        row = report["row"]
        self.assertEqual((row["default_branch"], row["integration_branch"]), ("main", "dev"))
        self.assertEqual(row["evidence"]["source"], {
            "ref": "refs/remotes/origin/dev",
            "commit": self.world.git(root, "rev-parse", "dev").strip()})
        self.assertEqual([profile["id"] for profile in row["evidence"]["profiles"]],
                         ["forge-main"])

    def test_a_jarbird_shaped_project_derives_once_its_adapter_reaches_main(self):
        slug = "elevenyellow/jarbird"
        root = self.world.project("jarbird", slug, integration_branch="dev",
                                  publication_free=True, mutate=self.jarbird_deploy)
        report = self.derived(slug)
        self.assertEqual(report["refused"], [])
        row = report["row"]
        self.assertEqual((row["default_branch"], row["integration_branch"]), ("main", "dev"))
        self.assertEqual(row["evidence"]["source"], {
            "ref": "refs/remotes/origin/dev",
            "commit": self.world.git(root, "rev-parse", "dev").strip()})
        self.assertEqual([profile["id"] for profile in row["evidence"]["profiles"]],
                         ["forge-main"])
```

Run the Unit run for `tests/test_guard_policy.py -k jarbird`. Expected: two tests pass. At this task's start neither test exists; require a count of two, so a zero-test run cannot masquerade as success.

- [ ] **Step 2: Verify the historical red without editing source**

The planning trial on 2026-10-27 already proved these two shapes refuse under `5ae1b9dc`, the pre-466 source: `branch_unresolved` for the adapter waiting on `dev`, and `contract_unresolved` for the adapter on both branches. Retain that finding. If execution needs to reproduce it, export that revision's `python/` into `$SCRATCH/pre-466` with `git archive` and run a scratch probe using the current `GuardPolicyWorld` fixtures. Construct the projects with the current resolver first (the `project` and `commit_contract` steps above); then call `world.derive(slug, env=dict(world.env, PYTHONPATH=<absolute pre-466 python directory>))` and assert exit 1 and those respective refusal codes. Do not set that old PYTHONPATH while rendering fixture projections, which intentionally use the current resolver. Never alter the worktree package or commit a historical-source shim.

This historical red is the regression gate: if a fixture derives under the old source, it does not pin the reported adapter incompatibility and must be corrected. No manufactured production fix is needed when the current source is green.

- [ ] **Step 3: Run the focused suite and inspect scope**

Run the Unit run for `tests/test_guard_policy.py` (timeout 900 s). Expected: all tests pass, including both new names. No Build is needed for this Python-test-only task; sdd runs the declared Build and workflow suite once on the final head. Inspect `git diff -- tests/test_guard_policy.py`: only the CONFIG import, mutator and two cases are added, with the contract members from `DeployInspectTest` and the assertions above.

In the execution hand-back, identify both checks and leave reporter-host AC1 and AC3 as `human_pending`, since nobody here switched the reporter's host or ran its PR command. Do not perform either host action from this task.

- [ ] **Step 4: Commit**

```bash
git add tests/test_guard_policy.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "test(guard-policy): derive the JarBird deploy-adapter shape (issue 467)" \
  -m "<session trailer lines>"
```

Scope check: `git diff --stat HEAD~1 -- tests/test_guard_policy.py` lists that test file alone.
