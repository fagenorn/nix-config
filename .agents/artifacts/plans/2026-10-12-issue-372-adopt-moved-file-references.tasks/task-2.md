# Task 2: A tracked `.claude/settings.json` is retained by classification

Spec row: D7. Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py`
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes: nothing from another task. At base, `adopt_inspection.CLASSIFICATION_RULES` is a tuple of `(group, match, lifecycle_class, action, target)` rows, first match wins, and `classify_inventory` turns a matched tracked path into one evidence entry for its group.
- Produces: `CLASSIFICATION_RULES` holds the row `(".claude/settings.json", "exact", "legacy-native-store", "retain-product", None)`. Tasks 4 and 5 rely on it: their fixture tracks that file and expects no `candidate-class` question for it.

**Invariants:**
- A tracked `.claude/settings.json` is no candidate: `decisions.open` holds no entry whose `subject` is that path, and no operation names it in `sources` or `targets`.
- Its evidence entry is `provenance` `tracked`, `lifecycle_class` `legacy-native-store`, `action` `retain-product`, `target` null, `count` 1, with a non-null `fingerprint`.
- No other row changes, no row is reordered, and `TARGETED_IGNORED` is not touched: an ignored settings file is out of scope.

- [ ] **Step 1: Write the failing test**

Add to `home/common/agent-skills/tests/test_adopt_project.py`, directly after `class RecordTreeClassificationTest`:

```python
class NativeSettingsTest(AdoptTestCase):
    """#372 D7: a tracked `.claude/settings.json` is retained by its row."""

    PATH = ".claude/settings.json"

    def test_a_tracked_settings_file_is_retained_without_a_question(self):
        root = nix_config_shape_repo(self.home)
        write(root, self.PATH, '{"hooks": {}}\n')
        commit(root, "track the native settings file")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(
            [op for op in doc["changes"]
             if self.PATH in op["sources"] + op["targets"]], [])
        (entry,) = [entry for entry in doc["evidence"]
                    if entry["path"] == self.PATH]
        self.assertEqual(
            (entry["provenance"], entry["lifecycle_class"], entry["action"],
             entry["target"], entry["count"]),
            ("tracked", "legacy-native-store", "retain-product", None, 1))
        self.assertIsNotNone(entry["fingerprint"])
```

`nix_config_shape_repo`, `write`, `commit` and `AdoptTestCase.ready_plan` are existing helpers of that file.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k NativeSettingsTest` (timeout 1800 s)
Expected: FAIL — `'draft' != 'ready'`: at base the file is an unclassified agent path with an open `candidate-class` question offering `archive-history`.

- [ ] **Step 3: Add the row**

In `CLASSIFICATION_RULES` (`python/agent_tools/adopt_inspection.py`), add directly after the `.claude/settings.local.json` row:

```python
    (".claude/settings.json", "exact", "legacy-native-store",
     "retain-product", None),
```

Nothing else in the module changes. The table's leading comment already describes a row of this shape; leave it.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k NativeSettingsTest -k CandidateQuestionTest -k CandidateAnswerTest -k RecordTreeClassificationTest` (timeout 1800 s)
Expected: PASS — the new case, and every existing candidate and classification case unchanged.

Content gate: `grep -c '".claude/settings.json", "exact", "legacy-native-store"' python/agent_tools/adopt_inspection.py` prints `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py home/common/agent-skills/tests/test_adopt_project.py
git commit -m "feat(adopt): retain a tracked native settings file in place (#372)"
```
