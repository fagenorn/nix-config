# Task 3: Platform 1.1.0 declares the legacy skills config deprecations

**Files:**
- Modify: `home/common/agent-skills/platform-manifest.json`
- Modify: `python/README.md`
- Create: `.agents/artifacts/plans/2026-11-03-issue-580-bridge-minor-deprecations.acceptance.md`
- Test: `home/common/agent-skills/tests/test_resolve_platform.py`

**Interfaces:**
- Consumes: Task 1's validator (the committed manifest must pass it) and Task 2's `deprecated_uses` (documented here).
- Produces: the installed manifest every host activates on its next switch: `platform_version` `1.1.0` with the two D5 entries.

**Invariants:**
- The committed manifest keeps its seven members; `schema_version` 1, `project_schema_versions` `[1]`, `resolved_schema_version` 1, `migrations` `[]`, `removals` `[]` are unchanged.
- Every committed deprecation's `since` is at most `platform_version` and has the same major (D3).
- `1.1.0` lies inside every fleet contract interval `[1.0.0, 2.0.0)`, so no project changes to absorb it.

- [ ] **Step 1: Write the failing test**

In `CommittedManifestTest` of `home/common/agent-skills/tests/test_resolve_platform.py`, replace `test_it_declares_exactly_the_seven_members_with_the_v1_values` with:

```python
    BRIDGE_DEPRECATIONS = [
        {"id": "legacy-skills-config", "kind": "project_file",
         "subject": ".claude/skills.config.json", "since": "1.1.0",
         "successor": "resolve-project resolve",
         "migration": "legacy-skills-config.retire"},
        {"id": "legacy-skills-config-writer", "kind": "platform_behavior",
         "subject": "adopt-project legacy binding config rewrite",
         "since": "1.1.0", "successor": "resolve-project resolve",
         "migration": "legacy-skills-config.retire"},
    ]

    def test_it_declares_exactly_the_seven_members(self):
        manifest = committed_manifest()
        self.assertEqual(sorted(manifest), sorted(MANIFEST_MEMBERS))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["platform_version"], "1.1.0")
        self.assertEqual(manifest["project_schema_versions"], [1])
        self.assertEqual(manifest["resolved_schema_version"], 1)
        for name in ("migrations", "removals"):
            with self.subTest(member=name):
                self.assertEqual(manifest[name], [])

    def test_it_declares_the_bridge_minor_deprecations(self):
        """Issue 580 D5: the legacy skills config and its adoption writer."""
        self.assertEqual(committed_manifest()["deprecations"],
                         self.BRIDGE_DEPRECATIONS)

    def test_every_deprecation_began_in_this_major(self):
        """Issue 580 D3: pinned on the committed file, not in the validator."""
        manifest = committed_manifest()
        version = agent_platform.parse_semver(manifest["platform_version"])
        for entry in manifest["deprecations"]:
            with self.subTest(id=entry["id"]):
                since = agent_platform.parse_semver(entry["since"])
                self.assertEqual(since[0], version[0])
                self.assertLessEqual(since, version)
```

Import `agent_platform` at the top of the file with `from agent_tools import agent_platform` unless the file already imports it under another name (then use that name).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform.py -k CommittedManifestTest 2>&1 | tail -5`
Expected: FAILED — `'1.0.0' != '1.1.0'` and `[] != [...]`.

- [ ] **Step 3: Write the minimal implementation**

1. Set `home/common/agent-skills/platform-manifest.json` to exactly the base file with `"platform_version": "1.1.0"` and `"deprecations"` holding the two objects of `BRIDGE_DEPRECATIONS`, in that order, keeping two-space indentation, one entry member per line, and a trailing newline.
2. Add a section `## Platform deprecations` to `python/README.md`, after `## adopt-project`, of at most 25 lines, stating: the closed entry and its validation (D1, every repair id); `platform-status` republishes `platform.deprecations` and adds `deprecated_uses` to the `project` block and each `fleet` row, its `null` and `lexists` semantics, and that it never changes a verdict, an exit code or `resolve` (D2); the report is interface version 2 (D4); `removals` stays opaque (D7); the declared entries of platform `1.1.0` (D5); and the migration `legacy-skills-config.retire` as four numbered steps: (1) `resolve-project resolve --repo-root R` exits 0; (2) every reader of `.claude/skills.config.json` reads `resolve-project resolve` instead; (3) `git rm .claude/skills.config.json` and commit; (4) `resolve-project platform-status --repo-root R` no longer lists `legacy-skills-config` in `deprecated_uses`. Add that `adopt-project` rewrites only an existing legacy file, so it never recreates a removed one, and that removal waits for the next major with zero fleet users (issue 66).
3. Create the acceptance record `.agents/artifacts/plans/2026-11-03-issue-580-bridge-minor-deprecations.acceptance.md`:

```markdown
# Acceptance record — issue 580

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | C11.a on mbp and eleven-m5: platform.deprecations is not empty after the owner switches each host to a generation containing this change (owner decision 4) | evidence | `resolve-project platform-status` on each host; green when exit 0, `platform.platform_version` is `1.1.0` and `platform.deprecations` holds at least 1 entry | pending owner switch on mbp and eleven-m5 | — | after `just switch` by the owner, per host | unverified |
```

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_resolve_platform_status.py 2>&1 | tail -3`
Expected: `OK`.
Run: `python3 -c 'import json,sys; m=json.load(open("home/common/agent-skills/platform-manifest.json")); sys.exit(0 if m["platform_version"]=="1.1.0" and len(m["deprecations"])==2 else 1)'`
Expected: exit 0 (exit 1 shows the manifest unchanged).
Run: `just build` (timeout 3600 s; the manifest is a Home Manager source file).
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/platform-manifest.json home/common/agent-skills/tests/test_resolve_platform.py python/README.md .agents/artifacts/plans/2026-11-03-issue-580-bridge-minor-deprecations.acceptance.md
git commit -m "feat(issue-580): platform 1.1.0 deprecates the legacy skills config and its writer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
