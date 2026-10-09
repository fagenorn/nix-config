# Task 1: Record trees relocate centrally; destinations never collide

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`CLASSIFICATION_RULES`)
- Modify: `python/agent_tools/adopt_planning.py` (`evaluate_ready_gates`, `GATE_MESSAGES` unchanged)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: three `CLASSIFICATION_RULES` rows (per D1); `no-existing-destination` fails on a shared or nested destination (per D2, D10). Later tasks rely on `found.moves` being the single list the gate reads.

**Invariants:**
- Each new row is `(group, "prefix", "durable-artifact", "move-canonical", target)` with exactly: `.claude/handoffs` → `.agents/artifacts/handoffs`, `.claude/notes` → `.agents/artifacts/notes`, `.claude/research` → `.agents/artifacts/specs`. Insert them directly after the `.claude/plans` row, in that order.
- `no-existing-destination` keeps its id, its repair id `adopt.destination.occupied` and its `GATE_MESSAGES` text; it fails when any planned destination exists on disk, **or** has an existing non-directory among its ancestors under `root`, **or** names the destination of more than one entry in `found.moves`, **or** is a proper ancestor of another planned destination (one path would have to be both a file and a directory; `adopt_apply.execute_operation` would fail creating the parent) (D2, D10). `READY_GATES` is unchanged.
- No Nodo-specific path, no new conformance bucket, no `resolve_project` edit.

- [ ] **Step 1: Write the failing tests**

Add after `nix_config_shape_repo` (module level):

```python
def record_trees_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus one tracked record under each of
    `.claude/handoffs`, `.claude/notes` and `.claude/research` (#340)."""
    root = nix_config_shape_repo(home)
    write(root, ".claude/handoffs/h.md", "# handoff h\n")
    write(root, ".claude/notes/n.md", "# note n\n")
    write(root, ".claude/research/r.md", "# research r\n")
    commit(root, "add agent records")
    return root
```

Add a test class after `TypedOperationTest`:

```python
class RecordTreeClassificationTest(AdoptTestCase):
    """#340 AC1: the three record trees are classified centrally."""

    def test_the_three_record_trees_plan_to_ready(self):
        doc = self.ready_plan(record_trees_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        for pair in ((".claude/handoffs/h.md",
                      ".agents/artifacts/handoffs/h.md"),
                     (".claude/notes/n.md", ".agents/artifacts/notes/n.md"),
                     (".claude/research/r.md",
                      ".agents/artifacts/specs/r.md")):
            self.assertIn(pair, pairs)
        entries = {entry["path"]: entry for entry in doc["evidence"]}
        for group, target in (
                (".claude/handoffs", ".agents/artifacts/handoffs"),
                (".claude/notes", ".agents/artifacts/notes"),
                (".claude/research", ".agents/artifacts/specs")):
            with self.subTest(group=group):
                entry = entries[group]
                self.assertEqual(
                    (entry["provenance"], entry["lifecycle_class"],
                     entry["action"], entry["target"], entry["count"]),
                    ("tracked", "durable-artifact", "move-canonical",
                     target, 1))

    def test_two_moves_into_one_destination_fail_the_destination_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/research/x.md", "# research x\n")
        commit(root, "collide with .claude/specs/x.md")
        doc = self.ready_plan(root)
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate, {"id": "no-existing-destination",
                                "status": "failed",
                                "repair_id": "adopt.destination.occupied"})
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertIn("no-existing-destination",
                      [blocker["id"] for blocker in doc["plan"]["blockers"]])

    def test_a_destination_inside_another_fails_the_destination_gate(self):
        root = nix_config_shape_repo(self.home)
        # `.agents/artifacts/specs/x.md` is `.claude/specs/x.md`'s destination
        # and this record's destination's parent: distinct paths, one of
        # which would have to be both a file and a directory.
        write(root, ".claude/research/x.md/r.md", "# research r\n")
        commit(root, "nest a destination inside another")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_destination_under_an_existing_file_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".agents/artifacts/notes", "a file, not a directory\n")
        write(root, ".claude/notes/n.md", "# note n\n")
        commit(root, "put a file where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def assert_destination_gate_fails(self, doc: object) -> None:
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate["status"], "failed", gate)
        self.assertEqual(doc["plan"]["state"], "draft")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k RecordTreeClassificationTest`
Expected: FAIL, 4 tests — the first plan is `draft` (the three records are `needs-decision`), and each collision fixture's destination gate is `passed` (its record has no move yet). An implementation that only counts exact duplicates still fails the last two.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection.CLASSIFICATION_RULES`: insert the three rows of the invariants.
2. `adopt_planning.evaluate_ready_gates`: replace the `occupied` computation with one over every destination in `found.moves` that fails when a destination exists under `root`, when an ancestor of it under `root` exists and is not a directory, when it occurs more than once (e.g. a `collections.Counter`), or when one of its `PurePosixPath(...).parents` is itself a planned destination. Any comment added says only what the code does: "a planned destination that already exists or sits under an existing file, or that collides with another: the same path, or one inside the other".

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py`
Expected: PASS, every test in the module (the two new ones included), no failures.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py home/common/agent-skills/tests/test_adopt_project.py
launch-commit … -- -m "feat(adopt): classify handoff, note and research records (#340)"
```
