# Task 1: `artifact-budget` validates `whole-file-deletion` evidence

Spec § Validator (artifact-budget), per D6 and D7. The manifest validator dispatches each `generated_evidence` entry on its `kind` over a closed set: `ef-core-migration-designer` keeps its rules, and `whole-file-deletion` gets its own strict shape. The blob-identity checks become one helper that both kinds use. Manifest versions, coverage rules and `validate-report` do not change.

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py` (`_validate_ef_designer_side`, `_validate_generated_evidence`; new helpers beside them)
- Test: `home/common/agent-skills/tests/test_artifact_budget.py` (class `ArtifactBudgetCliTest`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `artifact-budget check --kind review-package` accepts, in a v2 or v3 manifest's `generated_evidence`, an entry `{"path", "kind": "whole-file-deletion", "source_diff_bytes", "base": {"blob_sha", "bytes", "content_sha256", "line_count"}, "head": null}`. Task 2's CLI tests publish through this check.

**Invariants:**
- An entry's `kind` must be a `str` that names one of exactly two kinds. Anything else, including an unhashable value such as a list, raises `ArtifactBudgetError("invalid generated evidence kind")`. The CLI then exits 2 with empty stdout and never a traceback.
- `whole-file-deletion`: `head` is `None` and `base` is not `None`, else `ArtifactBudgetError("invalid whole-file deletion sides")`. `base` has exactly the keys `{blob_sha, bytes, content_sha256, line_count}`, else `"invalid generated evidence side"`. `line_count` is a non-`bool` `int` ≥ 0, else `"invalid generated evidence metric"`.
- The blob identity is one helper for both kinds. `blob_sha` is matched by `SHA_RE` (40 lowercase hex), else `"invalid generated evidence blob"`. `content_sha256` is a `str` matched by `SHA256_RE`, else `"invalid generated evidence digest"`. `bytes` passes `_integer`, else `"invalid generated evidence metric"`.
- `ef-core-migration-designer` behaves as before: at least one side (`"generated evidence has no side"`), and each present side has the EF keys and rules. The existing `test_generated_evidence_manifest_is_strict_and_within_budget` passes unmodified.
- The path checks, the `source_diff_bytes` rule (`_integer(…, minimum=1)`), uniqueness and coverage accounting are untouched.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_artifact_budget.py`, add this method to `ArtifactBudgetCliTest` directly after `test_generated_evidence_manifest_is_strict_and_within_budget`. `json`, `deepcopy`, `tempfile` and `Path` are already imported.

```python
    def test_whole_file_deletion_evidence_is_strict_in_a_v3_manifest(self):
        # Issue 439: an oversized whole-file deletion travels as bounded evidence.
        with tempfile.TemporaryDirectory() as raw:
            root, _, manifest = self.review_manifest(Path(raw), size=256)
            manifest["interface_version"] = 3
            manifest["source_diff_bytes"] = 82_259
            manifest["total_review_bytes"] = manifest.pop("total_diff_bytes")
            manifest["stat"] = {"files_changed": 1, "insertions": 0, "deletions": 1_000}
            manifest["packaging"] = {
                "context_lines": 7,
                "shard_strategy": "stable-first-fit-whole-file",
            }
            manifest["generated_evidence"] = [{
                "path": "landing/src/app/app/page.tsx",
                "kind": "whole-file-deletion",
                "source_diff_bytes": 82_259,
                "base": {
                    "blob_sha": "c" * 40,
                    "bytes": 80_975,
                    "content_sha256": "d" * 64,
                    "line_count": 1_000,
                },
                "head": None,
            }]
            manifest["coverage"] = {
                "complete": True,
                "file_diff_count": 1,
                "byte_complete_file_count": 0,
                "generated_evidence_file_count": 1,
            }
            root.write_text(json.dumps(manifest), encoding="utf-8")
            accepted = self.run_check("review-package", root)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(json.loads(accepted.stdout)["status"], "within_budget")

            ef_side = {
                "blob_sha": "c" * 40, "bytes": 80_975, "content_sha256": "d" * 64,
                "migration_id": "20260826010101_AddWidgets", "product_version": "10.0.10",
                "entity_types": 12, "properties": 70, "indexes": 5, "foreign_keys": 3,
                "tables": 12,
            }

            def entry(m):
                return m["generated_evidence"][0]

            mutations = {
                "non-null head": (
                    lambda m: entry(m).__setitem__("head", dict(entry(m)["base"])),
                    "invalid whole-file deletion sides"),
                "null base": (
                    lambda m: entry(m).__setitem__("base", None),
                    "invalid whole-file deletion sides"),
                "EF-shaped base": (
                    lambda m: entry(m).__setitem__("base", ef_side),
                    "invalid generated evidence side"),
                "missing line count": (
                    lambda m: entry(m)["base"].pop("line_count"),
                    "invalid generated evidence side"),
                "boolean line count": (
                    lambda m: entry(m)["base"].__setitem__("line_count", True),
                    "invalid generated evidence metric"),
                "negative line count": (
                    lambda m: entry(m)["base"].__setitem__("line_count", -1),
                    "invalid generated evidence metric"),
                "boolean bytes": (
                    lambda m: entry(m)["base"].__setitem__("bytes", True),
                    "invalid generated evidence metric"),
                "bad digest": (
                    lambda m: entry(m)["base"].__setitem__("content_sha256", "D" * 64),
                    "invalid generated evidence digest"),
                "bad blob sha": (
                    lambda m: entry(m)["base"].__setitem__("blob_sha", "c" * 39),
                    "invalid generated evidence blob"),
                "non-string kind": (
                    lambda m: entry(m).__setitem__("kind", ["whole-file-deletion"]),
                    "invalid generated evidence kind"),
            }
            for name, (mutate, message) in mutations.items():
                with self.subTest(name=name):
                    invalid = deepcopy(manifest)
                    mutate(invalid)
                    root.write_text(json.dumps(invalid), encoding="utf-8")
                    result = self.run_check("review-package", root)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertIn(message, result.stderr)
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `home/common/agent-skills/tests/test_artifact_budget.py -k test_whole_file_deletion_evidence_is_strict_in_a_v3_manifest`.
Expected: FAIL. `AssertionError: 2 != 0 : artifact-budget: invalid input: invalid generated evidence kind`, because the validator accepts only the EF kind at base.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/artifact_budget.py`, around `_validate_ef_designer_side` and `_validate_generated_evidence`:

```python
def _validate_blob_identity(value: dict) -> None:
    """The blob id, length and SHA-256 that every generated-evidence side carries."""

def _validate_ef_designer_sides(base: object, head: object) -> None:
    """At least one side; each present side is EF-shaped (the existing rules)."""

def _validate_whole_file_deletion_sides(base: object, head: object) -> None:
    """A null head and a base of exactly the blob identity plus `line_count`."""

GENERATED_EVIDENCE_SIDES = {
    "ef-core-migration-designer": _validate_ef_designer_sides,
    "whole-file-deletion": _validate_whole_file_deletion_sides,
}
```

1. `_validate_blob_identity(value)` holds the existing `blob_sha` check, the existing `content_sha256` check and an `_integer(value["bytes"])` check, with the three messages listed under Invariants. It runs after the caller's exact-keys check, so all three keys exist.
2. `_validate_ef_designer_side` keeps its exact-keys check and calls `_validate_blob_identity(value)` in place of its own blob and digest checks. It then keeps the `migration_id` and `product_version` checks. Its metric loop covers `{"entity_types", "properties", "indexes", "foreign_keys", "tables"}`; `bytes` now goes through the helper.
3. `_validate_ef_designer_sides(base, head)` is the current tail of `_validate_generated_evidence`: the "no side" check, then `_validate_ef_designer_side` on each non-`None` side.
4. `_validate_whole_file_deletion_sides(base, head)` checks, in this order: the sides rule, `_exact_keys(base, {"blob_sha", "bytes", "content_sha256", "line_count"})`, `_validate_blob_identity(base)`, then `_integer(base["line_count"])`.
5. `_validate_generated_evidence` keeps its key and path checks. It replaces `if value["kind"] != "ef-core-migration-designer"` with `kind = value["kind"]` and `validate_sides = GENERATED_EVIDENCE_SIDES.get(kind) if isinstance(kind, str) else None`. If `validate_sides is None`, it raises `"invalid generated evidence kind"`. The `isinstance` guard comes first because `dict.get` on a list raises `TypeError`. The `source_diff_bytes` check stays where it is, and `validate_sides(value["base"], value["head"])` replaces the old side loop.

- [ ] **Step 4: Verify**

Run the focused form on `home/common/agent-skills/tests/test_artifact_budget.py -k generated_evidence`, then on `-k whole_file_deletion`.
Expected: both `OK`. The first runs the unchanged EF test and the second runs the new test with all ten subtests.

Run the focused form on the whole module, `home/common/agent-skills/tests/test_artifact_budget.py`.
Expected: `OK`, with no failure or error.

Run (timeout 60 s): `git diff --quiet 3f4c5072746747c44bee51b1a24c13288923b27f -- home/common/agent-skills/artifact-budget-policy.json python/agent_tools`
Expected: exit 0, so no policy or generator file changed in this task.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/test_artifact_budget.py
launch-commit … -- -m "feat(artifact-budget): validate whole-file-deletion generated evidence (issue 439)" -m "<session trailers>"
```

Verify: `git status --short -- home python` prints nothing.
