# Task 4: `release profile inspect` reports a publication-free profile

Spec section 5 (per D7). The inspection command must report a declared publication-free profile like any other: exit 0, the same seven members, empty graphs and no handoff. At this task's starting commit it answers `resolver_failure` (exit 2) for such a profile, because `release.py` indexes `profile["publication"]["actions"]` on the string `"none"`.

**Files:**
- Modify: `python/agent_tools/release.py` (`_graphs`, `inspect_profile`, module docstring)
- Test: `tests/test_release_command.py` (additions only)

**Interfaces:**
- Consumes (Task 1): `release_profile.phase_nodes(profile: Mapping[str, Any], phase: str) -> list[dict[str, Any]]` — the authored nodes of `"publication"` or `"activation"`, `[]` when that phase is `"none"`; the fixture `tests/fixtures/release/publication-free-profile.json`.
- Produces: no new name. `python -m agent_tools.release profile inspect <id>` output for a publication-free profile, as pinned below.

**Invariants:**
- For every profile with at least one publication action the report is what it was at base, `graphs.handoffs` included (one entry, receipt `publication_receipt` or `activation_not_applicable`).
- For a publication-free profile `graphs` is exactly `{"phases": ["publication", "activation"], "publication": [], "activation": [], "handoffs": [], "proof": [], "recovery": []}`.
- `"unsupported"` stays `release_unsupported` and an unknown id stays `profile_unknown`, both exit 2; `_profile_error` is not edited.
- `release.py` holds no `"none"` literal and no `["publication"]["actions"]` / `["activation"]["units"]` indexing after this task; it reads phases through `release_profile.phase_nodes` only.
- The command stays read-only: no adapter call, no write, one `git rev-parse HEAD` child.

- [ ] **Step 1: Write the failing test**

Insert into `tests/test_release_command.py`, above `class AdapterInspectTest` (the module already defines `ReleaseCommandCase`, `REPO` and imports `json`):

```python
class PublicationFreeInspectTest(ReleaseCommandCase):
    """A publication-free profile is a declared profile: reported, with nothing in it (#368 D7)."""

    def test_reports_empty_graphs_and_no_handoff(self):
        contract = self.contract()
        profile = json.loads((REPO / "tests/fixtures/release/publication-free-profile.json")
                             .read_text("utf-8"))
        contract["release"] = {"profiles": {"forge-target": profile}}
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "forge-target")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(report), ["bindings", "conformance", "graphs", "profile",
                                          "repairs", "schema_version", "subject"])
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual(report["profile"]["deadlines"], {})
        self.assertEqual(report["graphs"], {
            "phases": ["publication", "activation"], "publication": [], "activation": [],
            "handoffs": [], "proof": [], "recovery": []})
        self.assertEqual(report["bindings"]["targets"], profile["bindings"]["targets"])
        self.assertEqual(report["bindings"]["adapters"]["forge"]["adapter"], "github-forge")
        self.assertEqual(report["bindings"]["adapters"]["forge"]["config"], {})
        self.assertEqual(report["conformance"]["adapters"]["forge"]["modes"], {})
        self.assertEqual(report["conformance"]["findings"], [])
        for check in report["conformance"]["checks"].values():
            self.assertEqual(check, {"status": "passed", "reason_code": None})
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "profile_unknown"))

```

`ReleaseCommandCase.setUp` copies this repository's contract into a temporary project, so the fixture's `fagenorn/nix-config` on `main` target satisfies the same-repository rule there.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_command.py -k PublicationFree`
Expected: FAIL — `AssertionError: 2 != 0` (the command printed `resolver_failure`).

- [ ] **Step 3: Implement in `python/agent_tools/release.py`**

- `_graphs`: `publication` and `activation` are `release_profile.ordered_nodes(release_profile.phase_nodes(profile, <phase>))`. `handoffs` is the existing one-entry list when `publication` is non-empty and `[]` when it is empty; the receipt choice for a non-empty publication is unchanged.
- `inspect_profile`: the `nodes` list is `ordered_nodes` over `phase_nodes(profile, "publication") + phase_nodes(profile, "activation")`.
- `_bindings`, `_conformance`, `_repairs`, `_profile_error` and the argument parser are not edited: with no node they already yield an empty per-adapter `config`, empty `modes` and three `passed` checks.
- Module docstring: add, from the code, that a publication-free profile is reported with empty graphs and no handoff and still exits 0.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_command.py`
Expected: PASS, 0 failures, 0 errors, the three `ProfileInspectTest` tests that existed at base included.

Run:

```bash
git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'
if grep -nE '"none"|\["(publication|activation)"\]\["(actions|units)"\]' python/agent_tools/release.py; then exit 1; fi
```

Expected: every numstat row has `0` in its second column; the `grep` prints nothing. Also run the never-edited gate of Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release.py tests/test_release_command.py
```

Commit through `launch-commit` with the message `feat(release): inspect reports a publication-free profile (#368)`.
