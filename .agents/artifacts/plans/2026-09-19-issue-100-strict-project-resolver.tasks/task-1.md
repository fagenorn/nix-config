# Task 1: Pin workflow-facing resolver refusals

**Files:**
- Modify: `home/common/agent-skills/tests/test_resolve_project.py`

**Interfaces:**
- Consumes: existing `ResolverTestCase.make_root()`, `run()`, and `tree_snapshot()` test helpers.
- Produces: `WorkflowRefusalFixtureTest`, the regression contract later consumer migrations rely on.

**Invariants:**
- Per D5, all four workflow-facing refusals exit 2, emit exactly `{"error": ...}`, name the exact code and repair ID, and expose no snapshot member.
- A refusal does not create, remove, rewrite, or retimestamp any fixture path.
- These tests exercise the resolver subprocess itself; they do not simulate resolver results in a consumer.

- [ ] **Step 1: Add the four exact regression fixtures**

Append this test class beside the existing resolver refusal tests. It deliberately overlaps lower-level cases: this table is the workflow migration's single observable contract.

```python
class WorkflowRefusalFixtureTest(ResolverTestCase):
    SNAPSHOT_MEMBERS = ("schema_version", "project", "bindings", "capabilities")

    def assert_workflow_refusal(self, root, code_name, repair_id):
        before = tree_snapshot(root)
        code, out, err = run("resolve", "--repo-root", str(root))
        self.assertEqual(code, 2, err)
        self.assertEqual(tree_snapshot(root), before)
        payload = json.loads(out)
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(payload["error"]["code"], code_name)
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertTrue(payload["error"]["violations"])
        for member in self.SNAPSHOT_MEMBERS:
            self.assertNotIn(member, payload)

    def test_missing_contract_fails_closed(self):
        self.assert_workflow_refusal(
            self.make_root(contract=False),
            "not_onboarded",
            "onboarding.contract.missing",
        )

    def test_malformed_contract_fails_closed(self):
        root = self.make_root()
        (root / ".agents" / "project.json").write_text("{", encoding="utf-8")
        self.assert_workflow_refusal(root, "invalid_contract", "contract.parse")

    def test_non_repository_without_contract_fails_closed(self):
        root = Path(tempfile.mkdtemp()).resolve()
        self.assert_workflow_refusal(
            root,
            "not_onboarded",
            "onboarding.contract.missing",
        )

    def test_stale_projection_fails_closed(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("\nhand edit\n")
        self.assert_workflow_refusal(
            root,
            "invalid_projection",
            "projection.codex.entry.stale",
        )
```

- [ ] **Step 2: Run the focused subprocess contract**

Run: `python3 home/common/agent-skills/tests/test_resolve_project.py WorkflowRefusalFixtureTest -v`

Expected: PASS, four tests. A non-2 exit, a second top-level member, the wrong repair ID, or a changed tree fails the task. This is a regression-only task: the behavior is already present at baseline, so a passing first run is the expected no-op implementation result.

- [ ] **Step 3: Run the complete resolver suite**

Run: `python3 home/common/agent-skills/tests/test_resolve_project.py -q`

Expected: PASS. Any existing schema, normalization, capability, or projection case failing means the consolidated fixture changed the resolver contract and must be fixed before commit.

- [ ] **Step 4: Commit**

```bash
git add home/common/agent-skills/tests/test_resolve_project.py
git commit -S -m "test(workflows): pin strict resolver refusals" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
