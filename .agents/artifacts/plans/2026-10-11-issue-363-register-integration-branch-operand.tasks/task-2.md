# Task 2: `--integration-branch` operand, branch reach, report and registration

**Files:**
- Modify: `python/agent_tools/adopt_verify.py` (`VerificationSource`, `remote_source`, `require_integrated`, `verify_repository`, `register_project`, module docstring)
- Modify: `python/agent_tools/adopt_project.py` (`command_verify`, `build_parser`, module docstring, the `verify` section comment)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Task 1): `agent_platform.write_registry` keeps an entry's `branch_override`; `agent_platform.BRANCH_OVERRIDE_REASONS`; in the test file, `OVERRIDE` (`{"branch": "dev", "default_branch": "main", "reason": "default_contract_unresolved"}`) and `agent_platform`. Existing, unchanged: `adopt_inspection.remote_heads(root) -> RemoteHeads` (`default: str | None`, `branches: frozenset[str]`), `fetch_pinned(root, branch) -> str`, `export_commit(root, commit, destination)`, `refuse(code, repair_id, pointer, message) -> AdoptError`; `adopt_verify.unresolved_integration_branch(message) -> AdoptError`, `integration_branch(payload) -> str | None`; test helpers `verifiable_repo(home, *, project_id, tracker_cli, integration_branch)`, `publish(root, refs, *, default)`, `VerifyTestCase`.
- Produces:
  - `VerificationSource` gains three keyword fields with defaults, after `branch`: `override_default: str | None = None`, `override_reason: str | None = None`, `default_contract_resolved: bool = True`.
  - `adopt_verify.branch_override(source: VerificationSource) -> dict | None`: `None` when `source.override_default is None`, else `{"branch": source.branch, "default_branch": source.override_default, "reason": source.override_reason}`.
  - `adopt_verify.remote_source(root: Path, run_resolver: Resolver, operand: str | None = None)`, still a context manager yielding one `VerificationSource`.
  - CLI: `verify --integration-branch NAME`; repair ids `adopt.verify.integration_branch_without_register` and `adopt.verify.integration_branch_repeated`.
  - In `home/common/agent-skills/tests/test_adopt_verify.py` (Task 3 relies on it): `stale_default_repo(home, *, project_id="fixture/target", contract=True) -> Path`.

**Invariants:**
- With `operand=None`, `remote_source` makes the same git and resolver calls in the same order as at the base and yields a source for which `branch_override` is `None` (R2, R3, R4).
- The operand is consulted only after the default branch `D` was fetched, exported and resolved. `default_contract_resolved` is exactly "that `resolve` exited 0" (D2).
- Default resolves: an operand different from the branch the contract names (or from `D` when the contract names none) refuses `not_integrated` / `adopt.registration.integration_branch_unresolved` before any further fetch; an equal operand changes nothing (R3).
- Default does not resolve and an operand `B` is given: `B` is tested for membership in the step-one listing before any git command receives it, then refused if it is `D`; it is fetched, pinned and exported; its contract must resolve and name `B`; no further hop. Every failure is `not_integrated` / `adopt.registration.integration_branch_unresolved` (R5).
- The override's `branch` is never stored on the source: `branch_override` reads `source.branch`, so the object cannot name a branch other than the pinned one (D9).
- The report has the member `branch_override` exactly when `branch_override(source)` is not `None`; `schema_version` stays 2. `register_project` writes the entry member under the same condition, inside the existing locked transaction, and its three inner checks are unchanged (R6, R7, R8).
- Both operand misuse checks run in `command_verify` after `require_manifest()` and before `require_repository`, as `AdoptError`s through the existing `main` handler (D5, D8).
- No existing test class or helper in `home/common/agent-skills/tests/test_adopt_verify.py` is edited.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_verify.py`, insert the following directly before the `if __name__ == "__main__":` block (after Task 1's `RegistryBranchOverrideTest`):

```python
def stale_default_repo(home: Path, *, project_id: str = "fixture/target",
                       contract: bool = True) -> Path:
    """`verifiable_repo` naming `dev`, plus a local `stale` branch (issue 363 D7).

    `main` is the adoption and `main~1` the same contract without it. `stale`
    forks from `main~1` and is the lagging default branch a case publishes as
    `stale:main`: its contract lacks the required top-level `release` member,
    or, with `contract=False`, it has no contract at all.
    """
    root = verifiable_repo(home, project_id=project_id,
                           integration_branch="dev")
    git(root, "checkout", "--quiet", "-b", "stale", "HEAD~1")
    if contract:
        document = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        del document["release"]
        write(root, ".agents/project.json",
              json.dumps(document, indent=2) + "\n")
    else:
        git(root, "rm", "--quiet", ".agents/project.json")
    commit(root, "a default branch that lags")
    git(root, "checkout", "--quiet", "main")
    return root


class IntegrationBranchOperandTest(VerifyTestCase):
    """Issue 363: `--register --integration-branch` reaches the integration branch
    when the default branch's contract does not resolve, and only then."""

    def refuse_with(self, root: Path, code: str, repair_id: str,
                    *extra: str) -> dict:
        payload = self.refuse(root, code, "--register", *extra)
        self.assertEqual(payload["error"]["repair_id"], repair_id, payload)
        self.assertFalse(self.registry_path().exists())
        return payload

    def tracking(self, root: Path, branch: str) -> str:
        return git(root, "for-each-ref", "--format=%(objectname)",
                   f"refs/remotes/origin/{branch}").strip()

    def assert_registered_through_the_operand(self, root: Path) -> None:
        adoption = git(root, "rev-parse", "main").strip()
        report = self.report(root, "--register", "--integration-branch", "dev")
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/dev", "commit": adoption})
        self.assertEqual(report["branch_override"], OVERRIDE)
        self.assertEqual(sorted(report),
                         sorted([*VERIFY_MEMBERS, "branch_override"]))
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(self.registry(), {
            "schema_version": 1,
            "projects": [{"project_id": "fixture/target", "root": str(root),
                          "branch_override": OVERRIDE}],
        })

    def test_the_stale_fixture_contract_is_refused_invalid_contract(self):
        root = stale_default_repo(self.home)
        git(root, "checkout", "--quiet", "stale")
        detail = self.check(self.report(root), "contract-resolves")
        self.assertEqual(detail["status"], "failed")
        self.assertIn("invalid_contract", detail["detail"])

    def test_the_operand_registers_against_the_integration_branch(self):
        root = stale_default_repo(self.home)
        publish(root, ("stale:main", "main:dev"))
        self.assert_registered_through_the_operand(root)
        self.assertEqual(self.fleet(), [{
            "project_id": "fixture/target",
            "root": str(root),
            "project_schema_version": 1,
            "platform_interval": {"min_inclusive": "1.0.0",
                                  "max_exclusive": "2.0.0"},
            "compatible": True,
            "reason_code": None,
            "repair_id": None,
        }])

    def test_a_default_branch_without_a_contract_takes_the_operand_too(self):
        root = stale_default_repo(self.home, contract=False)
        publish(root, ("stale:main", "main:dev"))
        self.assert_registered_through_the_operand(root)

    def test_an_operand_branch_without_the_record_refuses_not_integrated(self):
        root = stale_default_repo(self.home)
        publish(root, ("stale:main", "main~1:dev"))
        payload = self.refuse_with(
            root, "not_integrated", "adopt.registration.not_integrated",
            "--integration-branch", "dev")
        self.assertNotIn("--integration-branch",
                         payload["error"]["violations"][0]["message"])

    def test_a_stale_default_without_the_operand_refuses_and_names_it(self):
        root = stale_default_repo(self.home)
        publish(root, ("stale:main", "main:dev"))
        payload = self.refuse_with(
            root, "not_integrated", "adopt.registration.not_integrated")
        self.assertIn("--integration-branch",
                      payload["error"]["violations"][0]["message"])

    def test_an_operand_the_remote_and_its_contract_do_not_confirm_refuses(self):
        cases = {
            "not listed by origin": (("stale:main", "main:dev"), "absent"),
            "the default branch itself": (("stale:main", "main:dev"), "main"),
            "a contract that does not resolve": (
                ("stale:main", "main:dev", "stale:old"), "old"),
            "a contract naming another branch": (
                ("stale:main", "main:dev", "main:other"), "other"),
        }
        for name, (refs, operand) in cases.items():
            with self.subTest(name):
                root = stale_default_repo(self.home)
                publish(root, refs)
                self.refuse_with(
                    root, "not_integrated",
                    "adopt.registration.integration_branch_unresolved",
                    "--integration-branch", operand)
        # The unlisted name never reached a fetch.
        self.assertEqual(self.tracking(root, "absent"), "")

    def test_a_resolving_default_ignores_an_agreeing_operand(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        publish(root, ("HEAD~1:main", "main:dev"))
        plain = self.report(root, "--register")
        stored = self.registry_path().read_bytes()
        self.registry_path().unlink()
        self.assertEqual(
            self.report(root, "--register", "--integration-branch", "dev"),
            plain)
        self.assertEqual(self.registry_path().read_bytes(), stored)
        self.assertNotIn("branch_override", plain)
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])

    def test_a_resolving_default_refuses_a_disagreeing_operand(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        publish(root, ("HEAD~1:main", "main:dev"))
        git(root, "update-ref", "-d", "refs/remotes/origin/dev")
        self.refuse_with(
            root, "not_integrated",
            "adopt.registration.integration_branch_unresolved",
            "--integration-branch", "main")
        # Refused before any further fetch: `dev` was never fetched.
        self.assertEqual(self.tracking(root, "dev"), "")

    def test_a_resolving_default_that_names_itself_accepts_its_own_name(self):
        root = verifiable_repo(self.home)
        publish(root)
        report = self.report(root, "--register", "--integration-branch", "main")
        self.assertIs(report["registered"], True)
        self.assertEqual(sorted(report), VERIFY_MEMBERS)
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])

    def test_the_operand_without_register_refuses_before_the_repository(self):
        exit_code, payload, err = self.verify(
            Path(tempfile.mkdtemp()), "--integration-branch", "dev")
        self.assertEqual(exit_code, 2, err or payload)
        self.assertEqual(
            (payload["error"]["code"], payload["error"]["repair_id"]),
            ("adopt_failure",
             "adopt.verify.integration_branch_without_register"))

    def test_a_repeated_operand_refuses(self):
        exit_code, payload, err = self.verify(
            Path(tempfile.mkdtemp()), "--register",
            "--integration-branch", "dev", "--integration-branch", "dev")
        self.assertEqual(exit_code, 2, err or payload)
        self.assertEqual(
            (payload["error"]["code"], payload["error"]["repair_id"]),
            ("adopt_failure", "adopt.verify.integration_branch_repeated"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k IntegrationBranchOperandTest`
Expected: FAILED, 11 tests; only `test_the_stale_fixture_contract_is_refused_invalid_contract` passes (it proves the fixture's premise against today's resolver). The others fail or error because argparse rejects `--integration-branch` with a usage error and no JSON, and the unresolved-default message does not name the operand.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/adopt_verify.py`:

1. `VerificationSource`: add the three fields and `branch_override` exactly as under Produces. Extend the class docstring with what each new field holds.
2. `remote_source`: add the `operand` parameter. The order of the new branch is the decision, so it is given in full; it replaces the single line `named = integration_branch(payload) if exit_code == 0 else None`, and the existing hop block that follows (`if named is not None and named != default:`) stays as it is:

```python
        default_resolved = exit_code == 0
        named = integration_branch(payload) if default_resolved else None
        override_default = None
        if default_resolved:
            if operand is not None and operand != (named or default):
                raise unresolved_integration_branch(
                    "the default branch's contract resolves and names another "
                    "integration branch than `--integration-branch`")
        elif operand is not None:
            if operand not in heads.branches:
                raise unresolved_integration_branch(
                    "`--integration-branch` names a branch `origin` does not "
                    "list")
            if operand == default:
                raise unresolved_integration_branch(
                    "`--integration-branch` names the default branch, whose "
                    "contract does not resolve")
            branch = operand
            pinned = fetch_pinned(root, branch)
            exported = Path(scratch) / "integration"
            export_commit(root, pinned, exported)
            exit_code, payload = run_resolver(exported, "resolve")
            if exit_code != 0 or integration_branch(payload) != branch:
                raise unresolved_integration_branch(
                    "the contract on the `--integration-branch` branch does "
                    "not resolve or does not name that branch")
            override_default = default
```

   The yielded source additionally gets `override_default=override_default`, `override_reason` (`agent_platform.BRANCH_OVERRIDE_REASONS[0]`, the string `"default_contract_unresolved"`, when `override_default` is set, else `None`; it is read from the closed set so the value written and the value the validator accepts cannot drift, per D9) and `default_contract_resolved=default_resolved`. Rewrite the docstring from the implemented function: it must state the operand's two preconditions (the default contract did not resolve; `origin` lists the branch), the self-naming requirement, that there is no further hop, that a resolving default refuses a disagreeing operand, and that an unresolving default without the operand is still yielded as it is.
3. `require_integrated`: with evidence candidates, return. Without them, when `not source.default_contract_resolved and source.override_default is None`, refuse `not_integrated` / `adopt.registration.not_integrated` with the message `"the contract on the remote default branch does not resolve and that branch carries no adoption evidence record; name the integration branch with `--integration-branch`"`; otherwise refuse with today's message unchanged (D6). Extend the docstring with that distinction.
4. `verify_repository`: add `"branch_override": branch_override(source)` to the report dict only when it is not `None`. No other member changes.
5. `register_project`: the entry handed to `agent_platform.write_registry` is `{"project_id": project_id, "root": str(root)}` plus `"branch_override": branch_override(source)` when that is not `None`. Update the docstring's first line and the module docstring's sentence "What registration persists is exactly an identity and a location" to state the optional member and when it is written and dropped; update the module docstring's `--register` paragraph for the operand.

`python/agent_tools/adopt_project.py`:

6. `build_parser`: after `--register`, add

```python
    verify.add_argument("--integration-branch", action="append", default=[],
                        metavar="NAME",
                        help="with --register, the integration branch on "
                             "origin to register against when the default "
                             "branch's contract does not resolve; origin "
                             "must list it and its own contract must resolve "
                             "and name it")
```

   `action="append"` is what makes a repeated operand visible (D8). Leave the `--register` help as it is unless the implemented behaviour contradicts it.
7. `command_verify`: directly after `require_manifest()`, raise `adopt_inspection.refuse("adopt_failure", "adopt.verify.integration_branch_repeated", "", "`--integration-branch` may be given at most once")` when more than one value was given, then `adopt_inspection.refuse("adopt_failure", "adopt.verify.integration_branch_without_register", "", "`--integration-branch` is accepted only with `--register`")` when one was given without `--register`. Pass the single value, or `None`, as `remote_source`'s third argument. Bring the module docstring's `verify` paragraph and the `# verify` section comment in line: both describe the branch reach and say what is stored.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k IntegrationBranchOperandTest`
Expected: OK, 11 tests.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py`
Expected: OK, no failures or errors (the unedited issue-341 classes included).

Run: `git diff --numstat 96174d0ec1a6 -- home/common/agent-skills/tests/test_adopt_verify.py`
Expected: second column `0`.

Run: `git diff --stat 96174d0ec1a6 -- python/agent_tools/adopt_inspection.py python/agent_tools/resolve_project.py python/agent_tools/adopt_planning.py`
Expected: no output.

Run: `just build` (timeout 3600 s). Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_verify.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py
git commit -m "feat(issue-363): reach the integration branch through --integration-branch when the default contract is stale"
```
