# Task 4: nix-config's `github-release` profile and the legacy deploy bridge

**Files:**
- Modify: `.agents/project.json` (`"release": "unsupported"` → the `github-release` profile)
- Create: `python/agent_tools/release_bridge.py`
- Modify: `python/agent_tools/adopt_planning.py` (`legacy_binding_operations` only)
- Create: `tests/fixtures/legacy-skills-config-1722a65d.json` (exact bytes of `git show 1722a65d^:.claude/skills.config.json`, 81 bytes, trailing newline)
- Test: `tests/test_release_bridge.py`; modify `home/common/agent-skills/tests/test_adopt_project.py`, `test_conformance_checks.py`, `test_resolve_project.py`, `test_resolve_platform.py`, `test_conformance.py`, `test_conformance_registry.py`
- Modify: `justfile` (add `tests/test_release_bridge.py` after `tests/test_release_profile.py`)

Decisions: D6, D13, D23 (bridge question ids), D14. Spec §4, §9. AC5 is owned here.

**Interfaces:**
- Consumes: `release_profile.grammar_violations`/`compile_profile`; `adopt_inspection.authored_bytes(value)` (indent 2, `ensure_ascii=False`, trailing newline); Task 1's `github-release-profile.json`.
- Produces (`release_bridge`):
  - `BRIDGE_QUESTION_IDS = ("release.legacy_unreadable", "release.deploy_adapter_unrepresentable", "release.watch_doc_to_operations", "release.forge_unavailable")`.
  - `forge_only_profile(contract: dict) -> dict` — the spec §4 shape with `target.environment = "github-" + vcs.default_branch`, `concurrency_keys = ["release/" + tracker.repo_slug]`, target `repository`/`branch` from `tracker.repo_slug` / `vcs.default_branch`.
  - `plan_legacy_release(legacy_bytes: bytes | None, contract: dict) -> dict` — exactly `{"release": <release value or None>, "questions": [{"id": <BRIDGE_QUESTION_IDS member>, "pointer": <JSON pointer into the legacy file>}]}`.
  - `project_legacy_deploy(legacy_bytes: bytes, release: object) -> bytes`.

**Invariants:**
- Both functions are pure and never invent a value (D13).
- `plan_legacy_release`: `None` bytes (no file) behaves as a parsed `{}`. Bytes that are not UTF-8 JSON or not an object → `release: None`, questions `[{"id": "release.legacy_unreadable", "pointer": ""}]`. With `deploy` = the parsed member (absent → `{}`): a `watchDoc` member → question `release.watch_doc_to_operations` at `/deploy/watchDoc`; any member other than `adapter`/`watchDoc`, or `adapter` present and ≠ `"none"` → `release.deploy_adapter_unrepresentable` at `/deploy`. With no unrepresentable question: `tracker.kind == "github"` → `release = {"profiles": {"github-release": forge_only_profile(contract)}}`; otherwise `release: None` and `release.forge_unavailable` at `/deploy`. Questions are ordered by pointer.
- `project_legacy_deploy`: `release == "unsupported"` → input unchanged. Otherwise `release` must be a profiles object whose every profile binds only `github-forge` adapters and has `activation == "none"` (else `ValueError("release profile has no legacy deploy rendering")`); the rendering is *absent*. Unparseable or non-object bytes → `ValueError`. No `deploy` member → input bytes returned unchanged (identity, not re-serialization). A `deploy` member → `authored_bytes(parsed without "deploy")`.
- `legacy_binding_operations` (#148 D30): `candidate` = `authored_bytes(config)` if the key merge changed the value, else the current bytes; when `contract.get("release")` is `"unsupported"` or a profiles object and `release_profile.grammar_violations(release, contract)` is empty, `candidate = project_legacy_deploy(candidate, release)`; emit an operation only when `candidate != current`; never create a file.
- nix-config's `.agents/project.json` `release` member equals `{"profiles": {"github-release": <github-release-profile.json>}}` and `forge_only_profile(<nix-config contract>)` equals that profile (D6).

- [ ] **Step 1: Write the failing tests**

`tests/test_release_bridge.py`:

```python
"""Legacy skills-config bridge (#124 AC5). Run: just agent-workflow-tests"""
import json
import unittest
from pathlib import Path

from agent_tools import release_bridge, release_profile

REPO = Path(__file__).resolve().parents[1]
LEGACY = (Path(__file__).parent / "fixtures/legacy-skills-config-1722a65d.json").read_bytes()

def contract():
    return json.loads((REPO / ".agents/project.json").read_text("utf-8"))

class NixConfigProfileTest(unittest.TestCase):
    def test_committed_profile_is_the_fixture_and_the_bridge_shape(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/release/github-release-profile.json")
                             .read_text("utf-8"))
        source = contract()
        self.assertEqual(source["release"], {"profiles": {"github-release": fixture}})
        self.assertEqual(release_bridge.forge_only_profile(source), fixture)
        release_profile.compile_profile("github-release", fixture, source)

class ProjectionTest(unittest.TestCase):
    def test_nix_config_last_legacy_bytes_are_identical(self):
        self.assertEqual(len(LEGACY), 81)
        self.assertEqual(release_bridge.project_legacy_deploy(LEGACY, contract()["release"]), LEGACY)

    def test_no_file_generates_nothing(self):
        self.assertFalse((REPO / ".claude/skills.config.json").exists())

    def test_a_present_deploy_member_is_regenerated(self):
        legacy = json.dumps({"deploy": {"adapter": "none"}, "orchestration": {"maxParallel": 2}}).encode()
        self.assertEqual(release_bridge.project_legacy_deploy(legacy, contract()["release"]),
                         b'{\n  "orchestration": {\n    "maxParallel": 2\n  }\n}\n')

    def test_unsupported_and_unrenderable(self):
        self.assertEqual(release_bridge.project_legacy_deploy(b"{ }", "unsupported"), b"{ }")
        profile = json.loads(json.dumps(contract()["release"]))
        profile["profiles"]["github-release"]["activation"] = {"units": []}
        with self.assertRaises(ValueError):
            release_bridge.project_legacy_deploy(LEGACY, profile)

class PlannerTest(unittest.TestCase):
    def test_forge_representable_inputs_become_the_forge_profile(self):
        expected = {"profiles": {"github-release": release_bridge.forge_only_profile(contract())}}
        for legacy in (None, LEGACY, b'{"deploy": {"adapter": "none"}}'):
            with self.subTest(legacy=legacy):
                self.assertEqual(release_bridge.plan_legacy_release(legacy, contract()),
                                 {"release": expected, "questions": []})

    def test_railway_input_is_a_question_never_a_value(self):
        legacy = json.dumps({"deploy": {"adapter": "railway", "project": "p", "services": ["api"],
                                        "watchDoc": "docs/deploy.md"}}).encode()
        self.assertEqual(release_bridge.plan_legacy_release(legacy, contract()), {
            "release": None,
            "questions": [{"id": "release.deploy_adapter_unrepresentable", "pointer": "/deploy"},
                          {"id": "release.watch_doc_to_operations", "pointer": "/deploy/watchDoc"}]})

    def test_unreadable_and_non_forge(self):
        self.assertEqual(release_bridge.plan_legacy_release(b"[", contract())["questions"],
                         [{"id": "release.legacy_unreadable", "pointer": ""}])
        gitlab = contract()
        gitlab["bindings"]["tracker"]["kind"] = "gitlab"
        self.assertEqual(release_bridge.plan_legacy_release(None, gitlab)["questions"],
                         [{"id": "release.forge_unavailable", "pointer": "/deploy"}])

if __name__ == "__main__":
    unittest.main()
```

In `test_adopt_project.py`, beside `test_the_legacy_binding_config_gains_the_three_keys`, add `test_the_legacy_deploy_member_is_generated`: write `.claude/skills.config.json` in `nix_config_shape_repo(self.home)` as `{"deploy": {"adapter": "none"}, "orchestration": {"maxParallel": 2}}`, commit, take the ready plan's only write to that file, and assert its `after` hash equals `sha256_hash(authored_bytes({"orchestration": {"maxParallel": 2}, "specDir": …, "planDir": …, "rejectionsDir": …}))` computed by hand as the existing test does (key order: the authored keys, then the merged ones).

In `test_conformance_checks.py` add `test_nix_config_contract_passes_all_three` to `ReleaseProfileChecksTest`: `doctor` on an unmodified `make_root(tmp)` gives `passed` for the three `RELEASE_PROFILE_IDS`.

Make the capability-state tests independent of nix-config's release declaration: remove `"release"` from the two `for name in ("release", "deploy", …)` loops in `test_resolve_project.py`; in `RequireTest` require `knowledge.hints` where it required `release` (the pointer list becomes `["/capabilities/deploy", "/capabilities/knowledge.hints"]`, repair ids `capability.knowledge.hints.unsupported` / `capability.deploy.unsupported`); in `test_resolve_platform.py`, `test_conformance.py` and `test_conformance_registry.py` replace `"--require", "release"` and `("release",)` by `deploy` (expected `required_capabilities` `["deploy"]`).

- [ ] **Step 2: Run and watch them fail**

Run: `unittest tests/test_release_bridge.py`
Expected: ERROR — `ImportError: cannot import name 'release_bridge'`.

- [ ] **Step 3: Implement** `release_bridge` per the invariants (imports: `json`, `copy`, `adopt_inspection.authored_bytes`, `release_adapter`), the `legacy_binding_operations` change, the fixture file (`git show 1722a65d^:.claude/skills.config.json > tests/fixtures/legacy-skills-config-1722a65d.json`), and the contract edit (the `release` value copied from `github-release-profile.json`, two-space indented like the rest of the file).

- [ ] **Step 4: Verify**

Run (900 s): `unittest tests/test_release_bridge.py home/common/agent-skills/tests/test_{adopt_project,adopt_project_boundaries,conformance_checks,conformance,conformance_registry,resolve_project,resolve_platform}.py`
Expected: PASS. Then `cmp tests/fixtures/legacy-skills-config-1722a65d.json <(git show 1722a65d^:.claude/skills.config.json)` exits 0.

- [ ] **Step 5: Commit** exactly the **Files** above as `feat(release): nix-config github-release profile and legacy deploy projection (#124)`.
