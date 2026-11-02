# Task 3: Follow the contract's integration branch, and rewrite the docs

Spec: `.agents/artifacts/specs/2026-10-09-issue-341-register-against-remote-integration-branch-design.md`, `## Solution` step 4 and `## Decisions` "Docs" (D3, D4, D6). Task 2 left `remote_source` refusing whenever the contract at the remote default `D` names a different branch `B`. This task follows `B` once, and rewrites the prose that still describes local-branch registration.

**Files:**
- Modify: `python/agent_tools/adopt_verify.py`
- Modify: `python/agent_tools/adopt_project.py` (module docstring, the `verify` section comment, the `--register` help)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Tasks 1–2): `adopt_verify.remote_source(root, run_resolver)`, `VerificationSource(ref, commit, resolver_root, inventory, branch)`, `integration_branch(payload)`; `adopt_inspection.RemoteHeads(default, branches)`, `remote_heads`, `fetch_pinned(root, branch) -> str`, `export_commit(root, commit, destination)`, `tree_inventory(root, revision)`; test helpers `publish(root, refs=("main",), *, default="main")`, `verifiable_repo`, `VerifyTestCase.refuse`.
- Produces: `verifiable_repo(home, *, project_id="fixture/target", tracker_cli="gh", integration_branch="main")` — the new keyword sets `contract["bindings"]["vcs"]["integration_branch"]`. No new production name.

**Invariants:**
- In `remote_source`, after the contract at `R` (the pinned `origin/D`) resolves and names `B != D`:
  1. `B not in heads.branches` → `not_integrated`/`adopt.registration.integration_branch_unresolved`. No fetch of `B` is attempted (D3, D4).
  2. `R2 = fetch_pinned(root, B)`, `export_commit(root, R2, scratch/"integration")`, `run_resolver(scratch/"integration", "resolve")`.
  3. A non-zero exit, or `integration_branch(payload) != B` → `not_integrated`/`adopt.registration.integration_branch_unresolved`. There is no second hop.
  4. Otherwise yield `VerificationSource(ref=f"refs/remotes/origin/{B}", commit=R2, resolver_root=scratch/"integration", inventory=tree_inventory(root, R2), branch=B)`.
- The `D`-equals-`B` and contract-does-not-resolve paths from Task 2 are unchanged.
- Refusal messages are fixed sentences (no interpolated branch names), as every other `refuse` in the module.
- Docs describe the code as it now behaves; write them from the implemented code. They must state: plain `verify` reads `HEAD` (resolver on the working tree, inventory from the index, records at the `HEAD` commit it pins, D10); `--register` reads nothing from the checkout's branches or files, lists `origin`, fetches the contract's integration branch into `refs/remotes/origin/<branch>` (the only repository write), exports the pinned commit with `git archive` into a temporary directory removed on every exit, and runs every check there; it refuses `not_integrated` when that commit carries no evidence record or the adoption commit is not its ancestor; the registry entry is `{project_id, root}` with the real root (#148 D18). Point-in-time specs under `.agents/artifacts/` are not edited.

- [ ] **Step 1: Write the failing tests**

Add the `integration_branch` keyword to `verifiable_repo` (set `contract["bindings"]["vcs"]["integration_branch"] = integration_branch` beside the tracker override). Add to `RemoteRegistrationTest`:

```python
    def test_registration_follows_the_contracts_integration_branch(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        adoption = git(root, "rev-parse", "HEAD").strip()
        # The remote default carries the contract (naming `dev`) but not the
        # adoption; `dev` carries both.
        publish(root, ("HEAD~1:main", "main:dev"))
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/dev", "commit": adoption})
        self.assertEqual(
            git(root, "rev-parse", "refs/remotes/origin/dev").strip(), adoption)
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])

    def test_an_integration_branch_missing_on_origin_refuses(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        publish(root, ("HEAD~1:main",))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.integration_branch_unresolved")

    def test_a_second_branch_mismatch_refuses(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        contract["bindings"]["vcs"]["integration_branch"] = "release"
        write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
        commit(root, "contract names release")
        # origin/main names dev; origin/dev names release: no second hop.
        publish(root, ("HEAD~2:main", "HEAD:dev", "HEAD:release"))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.integration_branch_unresolved")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k test_registration_follows_the_contracts_integration_branch`
Expected: FAIL — exit 2 with `not_integrated`/`adopt.registration.integration_branch_unresolved` (Task 2's refusal). The other two new tests already pass; they pin the refusals the hop must keep.

Run: `if PYTHONPATH="$PWD/python" python3 -m agent_tools.adopt_project verify --help | tr -s ' \n' ' ' | grep -q 'fetched from origin'; then exit 1; fi`
Expected: exit 0 (the help does not yet say it).

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_verify.remote_source`: replace Task 2's `B != D` refusal with the four-step hop in the invariants, reusing the same `TemporaryDirectory`.
2. `adopt_verify` module docstring, `remote_source` and `register_project` docstrings: describe the two sources and the pinned-commit inner checks per the docs invariant.
3. `adopt_project.py`: rewrite the module docstring's `verify` paragraph and the `# `verify`` section comment above `command_verify` per the docs invariant. Set the `--register` help to exactly:
   `"record the project in the user-scope fleet registry; conformance and integration are proven against the contract's integration branch fetched from origin, never the local checkout"`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS, 32 tests.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.adopt_project verify --help | tr -s ' \n' ' ' | grep -q 'fetched from origin'`
Expected: exit 0.

Run: `PYTHONPATH="$PWD/python" python3 -c 'import agent_tools.adopt_project as m; d = m.__doc__; assert "refs/remotes/origin" in d and "git archive" in d, d'`
Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_verify.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py
git commit -m "feat(adopt): follow the contract's integration branch on origin (#341)"
```
