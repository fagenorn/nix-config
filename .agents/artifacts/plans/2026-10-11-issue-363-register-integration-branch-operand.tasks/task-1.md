# Task 1: Registry entry admits the optional `branch_override`

**Files:**
- Modify: `python/agent_tools/agent_platform.py` (the registry constants near line 46, `validate_registry`, `write_registry`)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes: nothing from another task. Existing: `agent_platform.validate_registry(source: object) -> list[dict]` (violations `{pointer, message, repair_id}`), `write_registry(entries: list[dict]) -> None`, `read_registry() -> list[dict]`, `PlatformManifestError` (`repair_id`, `violations`), `_registry_violation(pointer, message, code)` which prefixes `platform.registry.`.
- Produces (Tasks 2 and 3 rely on these exact names):
  - `agent_platform.REGISTRY_ENTRY_OPTIONAL_MEMBERS = ("branch_override",)`
  - `agent_platform.BRANCH_OVERRIDE_MEMBERS = ("branch", "default_branch", "reason")`
  - `agent_platform.BRANCH_OVERRIDE_REASONS = ("default_contract_unresolved",)`
  - `write_registry` keeps an entry's `branch_override` when the entry has one; `validate_registry` accepts a well-formed one.
  - In `home/common/agent-skills/tests/test_adopt_verify.py`: the module constant `OVERRIDE` and the import `from agent_tools import agent_platform`.

**Invariants:**
- `REGISTRY_ENTRY_MEMBERS` stays `("project_id", "root")` and both stay required non-empty strings; `REGISTRY_SCHEMA_VERSION` stays 1 (D4).
- An entry member other than `project_id`, `root` and `branch_override` is still refused `platform.registry.projects.member_unexpected` by the validator and still stripped by the writer (D3).
- A `branch_override` is an object with exactly `BRANCH_OVERRIDE_MEMBERS`, each a non-empty string, and `reason` a member of `BRANCH_OVERRIDE_REASONS`. Nothing dispatches on `reason`; the validator's membership test is the only place its value is read (D9).
- A registry file valid at the base stays valid and is rewritten to the same bytes: an entry without the member gains none.
- Sorting by `project_id`, the duplicate-id refusal, `read_registry` and `registry_transaction` are untouched. `resolve_project.py` and `adopt_planning.py` are not edited: they read `project_id` and `root` only.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_verify.py`, add the line `from agent_tools import agent_platform` directly after `from agent_tools import adopt_verify` (a new line; do not edit the existing one). Insert the following between the end of `RegisterProjectInnerCheckTest` and the `if __name__ == "__main__":` block:

```python
OVERRIDE = {"branch": "dev", "default_branch": "main",
            "reason": "default_contract_unresolved"}


class RegistryBranchOverrideTest(VerifyTestCase):
    """The entry's one optional member (issue 363 D3), through the imported
    validator and writer: no CLI path can hand them a malformed override."""

    def document(self, **members: object) -> dict:
        return {"schema_version": 1, "projects": [
            {"project_id": "fixture/target", "root": "/checkout", **members}]}

    def violations(self, **members: object) -> list[tuple[str, str]]:
        return [(entry["pointer"], entry["repair_id"]) for entry in
                agent_platform.validate_registry(self.document(**members))]

    def test_an_entry_with_and_without_the_override_is_valid(self):
        self.assertEqual(self.violations(), [])
        self.assertEqual(self.violations(branch_override=dict(OVERRIDE)), [])

    def test_a_malformed_override_is_refused_member_by_member(self):
        pointer = "/projects/0/branch_override"
        prefix = "platform.registry.projects.branch_override"
        cases = {
            "not_object": ("dev", [(pointer, f"{prefix}.not_object")]),
            "member_missing": (
                {"branch": "dev", "reason": "default_contract_unresolved"},
                [(f"{pointer}/default_branch", f"{prefix}.member_missing")]),
            "member_unexpected": (
                {**OVERRIDE, "commit": "0" * 40},
                [(f"{pointer}/commit", f"{prefix}.member_unexpected")]),
            "not_string": (
                {**OVERRIDE, "branch": 7},
                [(f"{pointer}/branch", f"{prefix}.not_string")]),
            "empty_string": (
                {**OVERRIDE, "default_branch": ""},
                [(f"{pointer}/default_branch", f"{prefix}.not_string")]),
            "reason_unknown": (
                {**OVERRIDE, "reason": "operator_said_so"},
                [(f"{pointer}/reason", f"{prefix}.reason_unknown")]),
        }
        for name, (override, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(
                    self.violations(branch_override=override), expected)

    def test_any_other_extra_entry_member_is_still_refused(self):
        self.assertEqual(
            self.violations(branch_override=dict(OVERRIDE), compatible=True),
            [("/projects/0/compatible",
              "platform.registry.projects.member_unexpected")])

    def test_the_writer_keeps_the_override_and_strips_everything_else(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            agent_platform.write_registry([
                {"project_id": "fixture/beta", "root": "/beta",
                 "compatible": True},
                {"project_id": "fixture/alpha", "root": "/alpha",
                 "branch_override": dict(OVERRIDE), "compatible": True},
            ])
            entries = agent_platform.read_registry()
        self.assertEqual(entries, [
            {"project_id": "fixture/alpha", "root": "/alpha",
             "branch_override": OVERRIDE},
            {"project_id": "fixture/beta", "root": "/beta"},
        ])
        self.assertEqual(self.registry(),
                         {"schema_version": 1, "projects": entries})

    def test_the_writer_refuses_a_malformed_override_and_writes_nothing(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            with self.assertRaises(
                    agent_platform.PlatformManifestError) as caught:
                agent_platform.write_registry([
                    {"project_id": "fixture/target", "root": "/checkout",
                     "branch_override": {**OVERRIDE, "reason": "other"}}])
        self.assertEqual(
            caught.exception.repair_id,
            "platform.registry.projects.branch_override.reason_unknown")
        self.assertFalse(self.registry_path().exists())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k RegistryBranchOverrideTest`
Expected: FAILED, 5 tests, every one failing — at the base an entry with `branch_override` is refused `projects.member_unexpected` and the writer strips it.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/agent_platform.py`:

1. Beside `REGISTRY_ENTRY_MEMBERS`, add the three constants named under Produces. Rewrite the comment above the registry constants so that it states what the code now does: an entry is a stable identity and a location, plus one optional record of how a registration reached its branch; still no version stamp and no cached verdict, and no reader decides anything from the optional member.
2. `validate_registry`: the per-entry "member is not part of this schema" loop admits the names in `REGISTRY_ENTRY_MEMBERS + REGISTRY_ENTRY_OPTIONAL_MEMBERS`. When an entry has `branch_override`, append the violations of a new private helper:

```python
def _branch_override_violations(pointer: str, override: object) -> list[dict]:
    """Every violation of one entry's `branch_override`, at `pointer`."""
```

   Its contract, in this order: a non-dict returns the single violation code `projects.branch_override.not_object` at `pointer`. Otherwise, for each name in `BRANCH_OVERRIDE_MEMBERS` in order: absent is `projects.branch_override.member_missing` at `<pointer>/<name>`; present but not a non-empty `str` is `projects.branch_override.not_string`; for `reason` only, a non-empty string outside `BRANCH_OVERRIDE_REASONS` is `projects.branch_override.reason_unknown`. Then, for each other name in sorted order, `projects.branch_override.member_unexpected`. Build every violation with `_registry_violation`. Update the `validate_registry` docstring: the entry is closed on the required members plus the one optional member, and the override is closed on its own members.
3. `write_registry`: the reduction keeps every name of `REGISTRY_ENTRY_MEMBERS` (a missing one still raises `KeyError` as today) and keeps `branch_override` exactly when the entry has that key; everything else is dropped. The existing `validate_registry(document)` call then refuses a malformed override before anything is written. Update the docstring sentence "an entry is reduced to exactly `REGISTRY_ENTRY_MEMBERS` (D18)" to say what the reduction now keeps.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k RegistryBranchOverrideTest`
Expected: OK, 5 tests.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py home/common/agent-skills/tests/test_resolve_platform_status.py`
Expected: OK, no failures (the existing registration and fleet-view suites still read and write the two-member entry).

Run: `git diff --numstat 96174d0ec1a6 -- home/common/agent-skills/tests/test_adopt_verify.py`
Expected: second column `0`.

Run: `just build` (timeout 3600 s). Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_platform.py home/common/agent-skills/tests/test_adopt_verify.py
git commit -m "feat(issue-363): let a fleet registry entry carry an optional branch_override"
```
