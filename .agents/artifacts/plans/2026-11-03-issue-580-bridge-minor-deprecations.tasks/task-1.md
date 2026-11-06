# Task 1: Closed deprecation entry in the manifest validator

**Files:**
- Modify: `python/agent_tools/agent_platform.py`
- Test: `home/common/agent-skills/tests/test_resolve_platform.py`

**Interfaces:**
- Consumes: the existing private helpers in `agent_platform.py`: `_violation(pointer, message, repair_id)`, `_check_list(value, pointer, section, violations) -> bool`, `_check_exact_members(value, pointer, expected, section, violations)`, `parse_semver(value) -> tuple[int, int, int] | None`.
- Produces (Tasks 2 and 3 rely on these names):
  - `DEPRECATION_MEMBERS = ("id", "kind", "subject", "since", "successor", "migration")`
  - `DEPRECATION_KINDS = ("project_file", "platform_behavior")`
  - `validate_manifest(source)` now rejects any `deprecations` entry outside D1, with repair ids `platform.manifest.deprecations.<code>` for code in `not_array`, `not_object`, `member_missing`, `member_unexpected`, `not_string`, `duplicate_id`, `kind_unknown`, `since_not_minor`, `subject_not_relative_path`.

**Invariants:**
- An empty `deprecations` array stays valid (the committed manifest at base still loads).
- A manifest with a D1-valid entry loads; `resolve` exits 0 against it.
- `removals` entries are still never read: `removals=["whatever", {"anything": [1, 2]}]` loads (D7).
- Every violation is collected in one pass; pointers are `/deprecations`, `/deprecations/<i>` or `/deprecations/<i>/<member>`.
- `subject` is path-checked only when `kind` is `project_file` and `subject` is a non-empty string; a `platform_behavior` subject is free text.
- `since` must parse with `parse_semver`, have patch `0` and minor `>= 1`; one code, `since_not_minor`, covers a non-string, a non-SemVer and a non-minor value. No comparison with `platform_version` (D3).
- `duplicate_id` is checked only when every entry yielded a well-typed id (mirrors `_validate_migrations`).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_resolve_platform.py`:

1. Move the untyped slot of `non_finite_manifest` from `deprecations` to `removals` (D7): replace `'"deprecations": []'` with `'"removals": []'` in the `replace` call and the `[{token}]` target, change its assert message to `"the committed manifest's removals moved"`, and say `removals` in its docstring and in the docstring of `test_platform_status_on_a_non_finite_manifest_prints_one_error_object`.
2. Change `ManifestLifecycleArrayTest`'s docstring to say `deprecations` entries are closed (D1) and `removals` are validated as an array and never read; rename `test_opaque_array_entries_are_never_read` to `test_removals_entries_are_never_read` and make its manifest `mutated_manifest(removals=["whatever", {"anything": [1, 2]}])`. Keep `test_deprecations_and_removals_must_be_arrays` unchanged.
3. Add after `ManifestLifecycleArrayTest`:

```python
VALID_DEPRECATION = {
    "id": "legacy-file",
    "kind": "project_file",
    "subject": ".claude/skills.config.json",
    "since": "1.1.0",
    "successor": "resolve-project resolve",
    "migration": "legacy-file.retire",
}


def deprecation(**changes: object) -> dict:
    entry = dict(VALID_DEPRECATION)
    for name, value in changes.items():
        if value is None:
            entry.pop(name)
        else:
            entry[name] = value
    return entry


class ManifestDeprecationEntryTest(ResolverTestCase):
    """Issue 580 D1: a `deprecations` entry is closed on six members."""

    def refuse(self, entries: object) -> dict:
        self.set_manifest(mutated_manifest(deprecations=entries))
        code, out, _ = run("resolve", "--repo-root", str(self.make_root()),
                           home=self.home)
        self.assertEqual(code, 2, out)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "resolver_failure")
        return error

    def assert_refused(self, entries: object, pointer: str,
                       repair_id: str) -> None:
        error = self.refuse(entries)
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         [pointer])
        self.assertEqual(error["repair_id"],
                         f"platform.manifest.deprecations.{repair_id}")

    def test_valid_entries_of_both_kinds_load(self):
        entries = [VALID_DEPRECATION,
                   deprecation(id="writer", kind="platform_behavior",
                               subject="adopt-project ../ rewrite")]
        self.set_manifest(mutated_manifest(deprecations=entries))
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err or out)

    def test_an_entry_must_be_an_object(self):
        self.assert_refused(["x"], "/deprecations/0", "not_object")

    def test_every_member_is_required(self):
        for name in VALID_DEPRECATION:
            with self.subTest(member=name):
                self.assert_refused([deprecation(**{name: None})],
                                    f"/deprecations/0/{name}",
                                    "member_missing")

    def test_an_unexpected_member_is_refused(self):
        self.assert_refused([deprecation(note="x")],
                            "/deprecations/0/note", "member_unexpected")

    def test_string_members_must_be_non_empty_strings(self):
        for name in ("id", "subject", "successor", "migration"):
            for value in ("", 1, ["a"]):
                with self.subTest(member=name, value=value):
                    self.assert_refused([deprecation(**{name: value})],
                                        f"/deprecations/0/{name}",
                                        "not_string")

    def test_an_unknown_kind_is_refused(self):
        for value in ("file", "", 1):
            with self.subTest(kind=value):
                self.assert_refused([deprecation(kind=value)],
                                    "/deprecations/0/kind", "kind_unknown")

    def test_since_must_be_a_minor_release(self):
        for value in ("1.1", "v1.1.0", "1.1.1", "2.0.0", "1.0.0", 1):
            with self.subTest(since=value):
                self.assert_refused([deprecation(since=value)],
                                    "/deprecations/0/since",
                                    "since_not_minor")

    def test_a_project_file_subject_must_be_a_relative_path(self):
        for value in ("/abs/file", "../x", "a/../b", "./a", "a//b", "a/",
                      "a\\b"):
            with self.subTest(subject=value):
                self.assert_refused([deprecation(subject=value)],
                                    "/deprecations/0/subject",
                                    "subject_not_relative_path")

    def test_ids_must_be_distinct(self):
        self.assert_refused(
            [VALID_DEPRECATION, deprecation(subject="other/file")],
            "/deprecations", "duplicate_id")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform.py -k ManifestDeprecationEntryTest -k ManifestLifecycleArrayTest -k non_finite 2>&1 | tail -5`
Expected: FAILED — the refusal cases exit 0 because entries are still opaque; `test_valid_entries_of_both_kinds_load`, the lifecycle and non-finite cases pass.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/agent_platform.py`:

- Add `DEPRECATION_MEMBERS` and `DEPRECATION_KINDS` next to `MIGRATION_MEMBERS`, with a comment citing issue 580 D1.
- Add `_validate_deprecation_entry(entry: object, pointer: str, violations: list[dict]) -> object` returning the entry's id when it is a non-empty string, else None. Order: not a dict → `not_object` at `pointer`, return None; `_check_exact_members(entry, pointer, DEPRECATION_MEMBERS, "deprecations", violations)`; for each of `id`, `subject`, `successor`, `migration` present and not a non-empty `str` → `not_string` at `{pointer}/{name}`; `kind` present and not in `DEPRECATION_KINDS` (test membership only for a `str`) → `kind_unknown`; `since` present and (`parse_semver` None, or patch != 0, or minor < 1) → `since_not_minor` with message `must be a minor release: MAJOR.MINOR.0 with MINOR at least 1`; when `kind == "project_file"` and `subject` is a non-empty string, refuse `subject_not_relative_path` when it starts with `/`, contains `\` or NUL, or any `subject.split("/")` segment is `""`, `"."` or `".."`.
- Add `_validate_deprecations(source, violations)`: absent member → return; `_check_list(..., "/deprecations", "deprecations", ...)`; validate each entry at `/deprecations/<i>`; if every entry yielded an id and the ids repeat → `duplicate_id` at `/deprecations` with message `each entry must carry a distinct id`.
- In `validate_manifest`, call `_validate_deprecations` after `_validate_migrations`; the remaining loop covers only `removals`. Replace the "opaque at v1" comment with one saying `removals` stays opaque until a major declares one (issue 580 D7) and `deprecations` is closed (D1).

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform.py 2>&1 | tail -3`
Expected: `OK` for the whole file (the committed manifest, still `[]`, keeps loading).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_platform.py home/common/agent-skills/tests/test_resolve_platform.py
git commit -m "feat(issue-580): close the platform manifest's deprecation entry shape" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
