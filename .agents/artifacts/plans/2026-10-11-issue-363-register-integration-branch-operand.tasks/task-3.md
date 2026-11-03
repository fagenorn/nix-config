# Task 3: Checkout isolation, registry lifecycle cases and the documented contract

**Files:**
- Modify: `python/README.md` (the `## adopt-project` section)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Task 1): `OVERRIDE` in the test file. (Task 2): `verify --register --integration-branch NAME`; the report member `branch_override`; the registry entry member `branch_override`; `stale_default_repo(home, *, project_id="fixture/target", contract=True) -> Path`, whose local `main` is the adoption commit, `main~1` the same contract (naming `dev`) without the adoption, and `stale` the lagging default. Existing: `VerifyTestCase` (`report`, `registry`, `registry_path`), `publish(root, refs, *, default) -> Path` (returns the bare `origin`), `verifiable_repo`, `write_adoption_records(root, digest)`, `tree_snapshot`, `git`, `write`, `commit`.
- Produces: nothing a later task consumes.

**Invariants:**
- No production module changes in this task: the cases pin behaviour Task 2 implemented. A case that fails here is a Task 2 defect to fix in `adopt_verify.py` or `adopt_project.py`, never by weakening the case.
- An operand-selected registration reads nothing from the checkout and writes only fetched objects and `refs/remotes/origin/<branch>` (R9).
- A registration that did not need the operand drops the project's stored override; another project's registration keeps it; a repeated operand registration is byte-identical (R8).
- No existing test class or helper in `home/common/agent-skills/tests/test_adopt_verify.py` is edited.
- The README states the contract as the code behaves at this commit; earlier specs are not edited.

- [ ] **Step 1: Write the tests**

In `home/common/agent-skills/tests/test_adopt_verify.py`, insert the following directly before the `if __name__ == "__main__":` block (after Task 2's `IntegrationBranchOperandTest`):

```python
class IntegrationBranchOperandLifecycleTest(VerifyTestCase):
    """Issue 363: what an operand-selected registration reads, and how its
    registry entry lives beside later registrations."""

    def register_through_the_operand(self, root: Path) -> dict:
        return self.report(root, "--register", "--integration-branch", "dev")

    def test_nothing_is_read_from_the_checkout(self):
        root = stale_default_repo(self.home)
        adoption = git(root, "rev-parse", "main").strip()
        # Freshness: origin's `dev` first holds the commit before the
        # adoption, and is advanced on origin itself, so the checkout's
        # `refs/remotes/origin/dev` is stale when registration starts.
        bare = publish(root, ("stale:main", "main~1:dev"))
        git(root, "push", "--quiet", "origin",
            f"{adoption}:refs/staging/adopt")
        git(bare, "update-ref", "refs/heads/dev", adoption)
        # A checkout that could answer nothing: unrelated local `main` and
        # `dev`, no contract in the working tree, an unstaged edit and an
        # untracked file.
        git(root, "checkout", "--quiet", "--orphan", "elsewhere")
        git(root, "rm", "--quiet", "-r", "-f", ".")
        write(root, "README.md", "# unrelated\n")
        commit(root, "unrelated history")
        git(root, "branch", "--quiet", "-f", "dev", "HEAD")
        write(root, "more.md", "# more\n")
        commit(root, "more unrelated history")
        git(root, "branch", "--quiet", "-f", "main", "HEAD")
        write(root, "README.md", "# unstaged edit\n")
        untracked = write(root, "scratch.txt", "untracked bytes\n")
        self.assertFalse((root / ".agents" / "project.json").exists())
        local = {name: git(root, "rev-parse", f"refs/heads/{name}").strip()
                 for name in ("main", "dev")}
        self.assertNotIn(adoption, local.values())
        status = git(root, "status", "--porcelain")
        snapshot = tree_snapshot(root)

        report = self.register_through_the_operand(root)

        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/dev", "commit": adoption})
        self.assertEqual(report["branch_override"], OVERRIDE)
        self.assertEqual(
            {name: git(root, "rev-parse", f"refs/heads/{name}").strip()
             for name in ("main", "dev")}, local)
        self.assertEqual(git(root, "status", "--porcelain"), status)
        self.assertEqual(tree_snapshot(root), snapshot)
        self.assertEqual(untracked.read_text("utf-8"), "untracked bytes\n")
        self.assertFalse((root / ".git" / "FETCH_HEAD").exists())

    def test_a_repeated_operand_registration_is_byte_identical(self):
        root = stale_default_repo(self.home)
        publish(root, ("stale:main", "main:dev"))
        self.register_through_the_operand(root)
        first = self.registry_path().read_bytes()
        self.register_through_the_operand(root)
        self.assertEqual(self.registry_path().read_bytes(), first)
        self.assertEqual(self.registry()["projects"][0]["branch_override"],
                         OVERRIDE)

    def test_a_later_registration_without_the_operand_drops_the_override(self):
        root = stale_default_repo(self.home)
        publish(root, ("stale:main", "main:dev"))
        self.register_through_the_operand(root)
        self.assertIn("branch_override", self.registry()["projects"][0])
        # The default branch catches up: its contract now resolves and names
        # `dev`, so the ordinary hop reaches it.
        git(root, "push", "--quiet", "--force", "origin", "main:main")
        report = self.report(root, "--register")
        self.assertIs(report["registered"], True)
        self.assertNotIn("branch_override", report)
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])

    def test_another_projects_registration_keeps_the_override(self):
        alpha = stale_default_repo(self.home, project_id="fixture/alpha")
        publish(alpha, ("stale:main", "main:dev"))
        self.register_through_the_operand(alpha)
        beta = verifiable_repo(self.home, project_id="fixture/beta")
        publish(beta)
        self.report(beta, "--register")
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/alpha", "root": str(alpha),
             "branch_override": OVERRIDE},
            {"project_id": "fixture/beta", "root": str(beta)},
        ])

    def test_a_non_conformant_operand_branch_reports_and_writes_nothing(self):
        root = stale_default_repo(self.home)
        write_adoption_records(root, digest="b2" * 32)
        commit(root, "a second adoption record")
        publish(root, ("stale:main", "main:dev"))
        report = self.register_through_the_operand(root)
        self.assertEqual(report["result"], "not_conformant", report)
        self.assertEqual(report["branch_override"], OVERRIDE)
        self.assertIs(report["registered"], False)
        self.assertFalse(self.registry_path().exists())
```

The non-conformant case commits a second evidence record on purpose: a drifted projection would make `resolve` itself refuse, and the operand branch would then be refused as unresolved before any report exists (D10).

- [ ] **Step 2: Run the tests**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k IntegrationBranchOperandLifecycleTest`
Expected: OK, 5 tests, on Task 2's head. Show that each can fail before keeping it: in a scratch copy of the worktree (under the `launch-scope scratch` root, never in the worktree), make `adopt_verify.branch_override` return `None` unconditionally and run the same command; expected FAILED, with all 5 cases failing or erroring. Record that observation in the task report.

- [ ] **Step 3: Document the contract**

In `python/README.md`, add one paragraph at the end of the `## adopt-project` section (after the paragraph that begins "`adopt-project plan` asks about every path literal", before `## Transaction core`), written from the code at this commit and naming https://github.com/fagenorn/nix-config/issues/363 by full URL. It must state, and nothing in it may contradict the code:

1. The branch-reach order of `verify --register`: `origin` is listed once; its default branch is fetched into `refs/remotes/origin/<branch>`, pinned, exported and resolved; a resolving contract that names another listed branch is the one hop; every check then reads the one pinned commit and nothing is read from the checkout.
2. The operand `--integration-branch <name>`: accepted only with `--register` and at most once (the two `adopt_failure` repair ids); it takes effect only when the default branch's contract does not resolve; the named branch must be listed by `origin`, must not be the default branch, and its own contract must resolve and name it; there is no further hop.
3. A resolving default contract stays the authority: an operand naming the branch it names changes nothing, any other operand refuses.
4. The `branch_override` object (`branch`, `default_branch`, `reason` with the one value `default_contract_unresolved`): present in the report and in the registry entry exactly for an operand-selected registration, absent otherwise, dropped by a later registration that did not need the operand; report `schema_version` 2 and registry `schema_version` 1 are unchanged; no reader decides anything from it.
5. The refusals: `not_integrated` with `adopt.registration.integration_branch_unresolved` for every operand the remote or the branch's contract does not confirm, and `adopt.registration.not_integrated` when the pinned commit carries no adoption evidence record, whose message names the operand when the default contract did not resolve and none was given.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py`
Expected: OK, no failures or errors.

Run: `git diff --numstat 96174d0ec1a6 -- home/common/agent-skills/tests/test_adopt_verify.py`
Expected: second column `0`.

Run: `grep -c -- "--integration-branch" python/README.md`
Expected: a count of at least 1 (0, with exit 1, at this task's starting commit).

Run: `if grep -n "#363" python/README.md; then exit 1; fi`
Expected: no output, exit 0 (the issue is cited by full URL).

AC6 is measured by sdd's final gate on the final head, not here: `just agent-workflow-tests`, threshold exit code `0`, recorded in acceptance-record row `AC6` with the commit and conditions.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_adopt_verify.py python/README.md
git commit -m "test(issue-363): pin checkout isolation and the override's registry lifecycle; document verify --register"
```
