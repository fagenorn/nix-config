# Task 2: `platform-status` warns on deprecated uses

**Files:**
- Modify: `python/agent_tools/resolve_project.py`
- Test: `home/common/agent-skills/tests/test_resolve_platform_status.py`

**Interfaces:**
- Consumes: Task 1's closed entry (`kind` is `project_file` or `platform_behavior`; a `project_file` `subject` is a safe relative path). The manifest reaching `resolve_project` has already passed `validate_manifest`.
- Produces:
  - `def deprecated_uses(root: Path, manifest: dict) -> list[str] | None` in `resolve_project.py`.
  - `PLATFORM_STATUS_SCHEMA_VERSION = 2` (D4).
  - The `platform-status` `project` block and every `fleet` row carry a `deprecated_uses` member (D2).

**Invariants:**
- `deprecated_uses` is `None` when `root.is_dir()` is false; otherwise the ascending list of `id`s of the `project_file` entries for which `os.path.lexists(root / entry["subject"])` is true. A `platform_behavior` entry is never listed.
- A listed use never changes `compatible`, `reason_code`, `repair_id` or the exit code; `resolve` against the same root exits 0 with an unchanged snapshot.
- Nothing new opens a file, writes, creates a directory or starts a child process (R3.6; `test_platform_status_runs_no_child_process` and the read-only tests in `test_resolve_project.py` stay green).
- `platform.deprecations` is still the manifest's array, verbatim.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_resolve_platform_status.py`:

1. Add `"deprecated_uses"` to `PROJECT_BLOCK_MEMBERS` and to `FLEET_ROW_MEMBERS`, keeping both lists sorted.
2. In `test_with_no_target_the_platform_block_stands_alone`, add `self.assertEqual(payload["schema_version"], 2)`.
3. In `test_a_registered_root_that_is_gone_is_a_reported_row`, add `self.assertIsNone(row["deprecated_uses"])`.
4. Append before the `__main__` guard:

```python
DEPRECATIONS = [
    {"id": "legacy-file", "kind": "project_file",
     "subject": ".claude/skills.config.json", "since": "1.1.0",
     "successor": "resolve-project resolve",
     "migration": "legacy-file.retire"},
    {"id": "legacy-writer", "kind": "platform_behavior",
     "subject": "adopt-project legacy binding config rewrite",
     "since": "1.1.0", "successor": "resolve-project resolve",
     "migration": "legacy-file.retire"},
]


class PlatformStatusDeprecationTest(ResolverTestCase):
    """Issue 580 D2: a project holding a deprecated path is warned through
    `deprecated_uses`, and nothing else about the answer changes."""

    def setUp(self) -> None:
        super().setUp()
        self.set_manifest(mutated_manifest(deprecations=DEPRECATIONS))

    def status(self, *args: str) -> dict:
        code, out, err = run("platform-status", *args, home=self.home)
        self.assertEqual(code, 0, err or out)
        return json.loads(out)

    def legacy_root(self, project_id: str = "fagenorn/nix-config") -> Path:
        contract = source_contract()
        contract["project"]["id"] = project_id
        root = self.make_root(contract)
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / "skills.config.json").write_text("{}\n")
        return root

    def test_a_project_holding_the_file_is_warned_and_stays_compatible(self):
        payload = self.status("--repo-root", str(self.legacy_root()))
        self.assertEqual(payload["project"]["deprecated_uses"],
                         ["legacy-file"])
        self.assertEqual(payload["compatibility"], {
            "compatible": True, "reason_code": None, "repair_id": None})
        self.assertEqual(payload["platform"]["deprecations"], DEPRECATIONS)

    def test_a_project_without_the_file_has_no_use(self):
        payload = self.status("--repo-root", str(self.make_root()))
        self.assertEqual(payload["project"]["deprecated_uses"], [])

    def test_a_dangling_symlink_counts_as_a_use(self):
        root = self.make_root()
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / "skills.config.json").symlink_to(
            root / "absent-target")
        payload = self.status("--repo-root", str(root))
        self.assertEqual(payload["project"]["deprecated_uses"],
                         ["legacy-file"])

    def test_resolve_still_succeeds_on_a_deprecated_use(self):
        code, out, err = run("resolve", "--repo-root",
                             str(self.legacy_root()), home=self.home)
        self.assertEqual(code, 0, err or out)

    def test_fleet_rows_carry_their_own_uses(self):
        # The registry refuses a repeated project id, so each root carries
        # its own, declared in its contract to keep the identity check green.
        legacy = self.legacy_root("fagenorn/legacy")
        clean_contract = source_contract()
        clean_contract["project"]["id"] = "fagenorn/clean"
        clean = self.make_root(clean_contract)
        gone = self.make_root()
        shutil.rmtree(gone)
        entries = [{"project_id": project_id, "root": str(root)}
                   for project_id, root in (("fagenorn/legacy", legacy),
                                            ("fagenorn/clean", clean),
                                            ("fagenorn/gone", gone))]
        install_registry(self.home, registry(*entries))
        rows = {row["root"]: row
                for row in self.status("--fleet")["fleet"]}
        self.assertEqual(rows[str(legacy)]["deprecated_uses"],
                         ["legacy-file"])
        self.assertTrue(rows[str(legacy)]["compatible"])
        self.assertEqual(rows[str(clean)]["deprecated_uses"], [])
        self.assertIsNone(rows[str(gone)]["deprecated_uses"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform_status.py 2>&1 | tail -5`
Expected: FAILED — `KeyError: 'deprecated_uses'` and member-list mismatches; `schema_version` is 1.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/resolve_project.py` (`import os` if absent):

- `PLATFORM_STATUS_SCHEMA_VERSION = 2`; extend its comment: version 2 adds `deprecated_uses` (issue 580 D4).
- Add `deprecated_uses(root, manifest)` in the `platform-status` section, after `declared_facts`, implementing the first invariant. Docstring: presence by `lexists` rather than git tracking because the operation starts no child process (R3.6); a warning, never a verdict (issue 66, D2).
- `evaluate_named_project`: add `"deprecated_uses": deprecated_uses(root, manifest)` to `project`.
- `fleet_row`: add `"deprecated_uses": deprecated_uses(Path(entry["root"]), manifest)` to the row.
- Mention `deprecated_uses` in `command_platform_status`'s docstring and in the `platform-status` parser `description`.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform_status.py 2>&1 | tail -3`
Expected: `OK`.
Then: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k platform_status 2>&1 | tail -3`
Expected: `OK` (read-only and no-child-process cases).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py home/common/agent-skills/tests/test_resolve_platform_status.py
git commit -m "feat(issue-580): platform-status reports deprecated uses per project and fleet row" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
