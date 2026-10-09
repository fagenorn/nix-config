# Task 5: The `release` command and `ReleaseProfileInspection`

**Files:**
- Create: `python/agent_tools/release.py`
- Modify: `lib/agent-tools.nix` (add `"release"` to `commands`, alphabetically between `"promotion"` and `"replay-retained"`)
- Modify: `python/README.md` (new `## Release profiles` section after `## Transaction core`)
- Test: `tests/test_release_command.py`
- Modify: `justfile` (add `tests/test_release_command.py` after `tests/test_release_bridge.py`)

Decisions: D5, D15, D17, D18 (command lands in group A), D23. Spec §5.

**Interfaces:**
- Consumes: `resolve_project.resolve` (raises `ContractError`: `.code`, `.repair_id`, `.violations`, `.reason_code`), `load_contract`, `require_platform_manifest`, `emit_error`, `emit_json`, `resolves_on_path`; Task 2's `release_profile` functions; `transaction_plan.PHASE_CLASS`, `DERIVED_FORMS`, `RESERVED_PREDICATES`, `derived_id` (read only).
- Produces: `python -m agent_tools.release profile inspect <profile-id> [--repo-root PATH]` (launcher `release`); `build_parser()` with a `{profile, adapter}` level (Task 6 adds `adapter inspect`); `inspect_profile(root, source, profile_id, manifest, manifest_path) -> dict`; `main(argv=None) -> int`.

**Invariants:**
- Read-only: no provider call, no write anywhere, no network; the one child process is `git rev-parse HEAD` in the project root (bounded timeout 10 s; failure → `source_revision: null`).
- Success prints one compact sorted-key JSON object (`resolve_project.emit_json`) and exits 0, admissible or not (#69: diagnosis never mutates).
- A resolver refusal propagates exactly: the same `{"error": …}` object `resolve-project resolve` would print, exit 2.
- `"release": "unsupported"` → `{"error": {"code": "release_unsupported", "repair_id": "release.profile.declare", "violations": [{"pointer": "/release", "message": "the project declares no release profile"}]}}`, exit 2. An unknown id → code `profile_unknown`, repair `release.profile.unknown`, pointer `/release/profiles/<id>`, exit 2.
- The report has exactly seven members (`schema_version`, `subject`, `profile`, `graphs`, `bindings`, `conformance`, `repairs`), each exactly as below. No secret, environment value or credential material appears; credentials are handles and classes only.

## Report members (exact)

- `schema_version`: `1`.
- `subject`: `{"project_id", "project_root", "source_revision": str|null, "platform": {"manifest_path": str(manifest_path), "platform_version": manifest["platform_version"]}}`.
- `profile`: `{"id", "version", "digest": profile_digest(profile), "target", "deadlines": {node id: ms or null}, "limits", "admissible": not findings}`.
- `graphs`: `{"phases": ["publication", "activation"], "publication": [node…], "activation": [node…], "handoffs": [{"from": "publication", "to": "activation", "receipt": "publication_receipt" if activation units else "activation_not_applicable"}], "proof": [obligation…], "recovery": [unit…]}`. A node is `{"id", "mode", "adapter", "operation", "target", "deps"}` in `ordered_nodes` order. Proof: first one derived entry per node, `{"id": derived_id(class, node id), "derived": true, "class", "form": DERIVED_FORMS[class], "predicate": RESERVED_PREDICATES[class], "roots": node id}` with `class = PHASE_CLASS[phase]`, then each authored obligation `{"id", "derived": false, "semantic", "form", "predicate", "collector", "required", "deps"}`. Recovery: per node id in node order, `{"unit", "posture", "anchor", "compatibility", "edges"}` as authored.
- `bindings`: `{"adapters": {alias: {**adapter_identities(profile)[alias], "config": {node id: config for nodes of that alias}}}, "targets", "principals", "credentials"}` (authored objects).
- `conformance`: `{"adapters": {alias: {"modes": {op: descriptor support for each operation the profile references}, "predicates": {name: support for every descriptor predicate}, "executables": {name: resolves_on_path(name, root)}}}, "checks": {check id: {"status": "failed" | "passed", "reason_code": RULE_CHECKS reason or null}}, "findings": [every admissibility finding]}`.
- `repairs`: one per finding — `{"repair_id": RULE_CHECKS[rule][2] for the three linted rules, else "release_profile." + reason, "pointer", "safety_class": "user_action"}` — then one per missing executable — `{"repair_id": "capability.release.release_adapter_unavailable", "pointer": "/release/profiles/<id>/bindings/adapters/<alias>", "safety_class": "user_action"}`.

- [ ] **Step 1: Write the failing test `tests/test_release_command.py`**

```python
"""The release command: profile inspection (#124 spec §5). Run: just agent-workflow-tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "python"
SHARE = REPO / "home/common/agent-skills"

class ReleaseCommandCase(unittest.TestCase):
    """Runs `python -m agent_tools.release` against a temporary copy of this repository's
    contract under a temporary HOME holding the committed platform manifest, as the
    resolver suite's `install_home` does."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        for name in ("platform-manifest.json", "host-declaration.json"):
            shutil.copy(SHARE / name, self.home / ".agents/share" / name)
        self.root = Path(tmp.name).resolve() / "project"
        (self.root / ".agents").mkdir(parents=True)
        shutil.copytree(REPO / ".agents/instructions", self.root / ".agents/instructions")
        for name in ("AGENTS.md", "CLAUDE.md"):
            shutil.copy(REPO / name, self.root / name)
        self.write_contract(json.loads((REPO / ".agents/project.json").read_text("utf-8")))
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)

    def write_contract(self, contract):
        (self.root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")

    def contract(self):
        return json.loads((self.root / ".agents/project.json").read_text("utf-8"))

    def run_release(self, *args):
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home))
        result = subprocess.run([sys.executable, "-m", "agent_tools.release", *args,
                                 "--repo-root", str(self.root)],
                                capture_output=True, text=True, env=env, timeout=120)
        return result.returncode, json.loads(result.stdout), result.stderr

class ProfileInspectTest(ReleaseCommandCase):
    def test_reports_exactly_seven_members_for_nix_config(self):
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(report), ["bindings", "conformance", "graphs", "profile",
                                          "repairs", "schema_version", "subject"])
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual([n["id"] for n in report["graphs"]["publication"]], ["tag", "github-release"])
        self.assertEqual(report["graphs"]["handoffs"],
                         [{"from": "publication", "to": "activation", "receipt": "activation_not_applicable"}])
        derived = [o for o in report["graphs"]["proof"] if o["derived"]]
        self.assertEqual([(o["class"], o["predicate"], o["roots"]) for o in derived],
                         [("published_artifact_identity", "publication_visible", "tag"),
                          ("published_artifact_identity", "publication_visible", "github-release")])
        self.assertEqual(sorted(report["conformance"]["checks"]),
                         ["repository.release_profile.observation_deadline",
                          "repository.release_profile.restore_anchor",
                          "repository.release_profile.rolled_back_reachable"])
        for check in report["conformance"]["checks"].values():
            self.assertEqual(check, {"status": "passed", "reason_code": None})
        self.assertEqual(report["bindings"]["adapters"]["forge"]["adapter"], "github-forge")
        self.assertEqual(report["subject"]["project_id"], "fagenorn/nix-config")

    def test_an_inadmissible_profile_still_reports_in_full(self):
        contract = self.contract()
        del contract["release"]["profiles"]["github-release"]["publication"]["actions"][0][
            "observation_deadline_ms"]
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertFalse(report["profile"]["admissible"])
        check = report["conformance"]["checks"]["repository.release_profile.observation_deadline"]
        self.assertEqual(check, {"status": "failed", "reason_code": "observation_deadline_optional"})
        self.assertIn({"repair_id": "release_profile.deadline.require",
                       "pointer": "/release/profiles/github-release/publication/actions/0",
                       "safety_class": "user_action"}, report["repairs"])

    def test_typed_errors_and_resolver_refusals(self):
        code, payload, _ = self.run_release("profile", "inspect", "nope")
        self.assertEqual((code, payload["error"]["code"]), (2, "profile_unknown"))
        contract = self.contract()
        contract["release"] = "unsupported"
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "release_unsupported"))
        del contract["release"]
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "invalid_contract"))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_command.py`
Expected: ERROR — `No module named agent_tools.release` (stdout empty, `json.loads` raises).

- [ ] **Step 3: Implement** `agent_tools.release` (argparse; `resolve` → `load_contract` → typed errors → `inspect_profile` → `emit_json`), the `lib/agent-tools.nix` row, and the README section. The README section describes only code at this commit: the member's two forms, the grammar/admissibility tiers and outcomes, `bind_candidate` as `create`'s exact input, the inspection contract, and the bridge projection with the sweep as its one writer (cite #124 decision IDs).

- [ ] **Step 4: Verify**

Run (600 s): `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_command.py`
Expected: PASS, 3 tests. Then `just build` (3600 s) succeeds (the new launcher row's module exists and imports).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release.py lib/agent-tools.nix python/README.md tests/test_release_command.py justfile
git commit -m "feat(release): read-only release profile inspection command (#124)"
```
