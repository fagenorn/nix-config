# Task 6: The Argus-shaped profile compiles, resolves and inspects (AC1)

Per D2, D5, D7, D10, D11 and the spec's § The Argus-shaped profile. Read the plan root's Global Constraints first. This task adds no `agent_tools` code: every check runs the real registry.

**Files:**
- Create: `tests/fixtures/release/argus-shaped-profile.json`
- Modify: `tests/release_test_support.py` (add `argus_shaped_profile()`)
- Modify: `tests/test_release_grammar.py` (new `HostLocalProfileTest`)
- Modify: `tests/test_release_profile.py` (new `HostLocalProfileTest`)
- Modify: `home/common/agent-skills/tests/test_resolve_project.py` (new `HostLocalReleaseTest`, plus one `DeployWatchTest` method)
- Modify: `tests/test_release_command.py` (new `HostLocalInspectTest`)
- Modify: `python/README.md` (§ Release profiles: one new paragraph at the end of the section)

**Interfaces:**
- Consumes: `release_adapter.DESCRIPTORS` holding `codesigned-artifact` and `launchd-agent`, and the existing helpers `support.release_of`, `support.base_contract`, `support.CANDIDATE`, `source_contract`, `publication_free_profile`, `make_stub_bin`, `run_with_path`, `RELEASE_FIXTURES`, `ReleaseCommandCase` and `DeployWatchTest.jarbird`.
- Produces: `support.argus_shaped_profile() -> dict`, a fresh copy of the fixture, which Task 7 compiles.

**Invariants:**
- The fixture carries Argus's real values, and no `python/agent_tools/` file gains one (AC2).
- The authored obligation's `parameters.parameters` equals the `daemon` unit's bound parameters without `candidate` (124 D24).
- No existing test's expectation changes.

- [ ] **Step 1: Write the failing tests**

Write the fixture with 2-space indentation and a trailing newline, as the sibling fixtures are, with exactly this content:

```json
{"profile_version": 1,
 "target": {"environment": "local-host", "concurrency_keys": ["release/fagenorn/argus"]},
 "requirements": {"adapters": {"bundle": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
                               "launchd": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}}},
 "bindings": {
   "adapters": {"bundle": {"adapter": "codesigned-artifact"}, "launchd": {"adapter": "launchd-agent"}},
   "targets": {"notifier": {"adapter": "bundle", "kind": "installed_bundle",
                            "path": "~/Library/Application Support/Argus/Argus.app"},
               "daemon": {"adapter": "launchd", "kind": "launchd_gui_agent", "label": "dev.argus.daemon"}},
   "principals": {"owner": {"class": "host_user"}},
   "credentials": {"keychain": {"adapter": "bundle", "class": "codesigning_identity"},
                   "session": {"adapter": "launchd", "class": "gui_session"}}},
 "publication": {"actions": [{
   "id": "notifier", "mode": "materialize", "adapter": "bundle", "operation": "install",
   "target": "notifier", "principal": "owner", "credential": "keychain",
   "effect": "reversible_no_incremental_spend", "config_schema_version": 1,
   "config": {"source": "daemon/notifyd/Argus.app", "identity_prefix": "Apple Development",
              "identity_env": "ARGUS_CODESIGN_IDENTITY", "adhoc_fallback": false},
   "deps": [], "observation_deadline_ms": 120000}]},
 "activation": {"units": [{
   "id": "daemon", "mode": "local_apply", "adapter": "launchd", "operation": "activate",
   "target": "daemon", "principal": "owner", "credential": "session", "effect": "irreversible",
   "config_schema_version": 1, "config": DAEMON_CONFIG,
   "deps": [], "observation_deadline_ms": 300000}]},
 "proof": {"convergence_window_ms": 1800000, "obligations": [{
   "id": "daemon-live", "semantic": "liveness", "form": "snapshot", "predicate": "agent_running",
   "collector": "launchd", "required": true, "deps": ["derived:running_subject_identity:daemon"],
   "parameters": {"parameters": {"action": "daemon", "operation": "activate",
                                 "target": {"handle": "daemon", "kind": "launchd_gui_agent",
                                            "label": "dev.argus.daemon"},
                                 "config": DAEMON_CONFIG}},
   "freshness_ms": 600000}]},
 "recovery": {"units": {
   "notifier": {"posture": "supersedable_only", "anchor": null, "compatibility": null, "edges": []},
   "daemon": {"posture": "supersedable_only", "anchor": null, "compatibility": null, "edges": []}}},
 "limits": {}}
```

`DAEMON_CONFIG` stands for this object, written out in both places: `{"program": "devenv", "arguments": ["shell", "--", "daemon", "run"], "keep_alive": true, "background": true, "stdout_path": "home/daemon/logs/daemon.out.log", "stderr_path": "home/daemon/logs/daemon.err.log"}`.

Add to `tests/release_test_support.py`: `def argus_shaped_profile() -> dict: return _load("argus-shaped-profile.json")`.

`tests/test_release_grammar.py`:

```python
class HostLocalProfileTest(unittest.TestCase):
    """Issue 547 AC1, against the real registry."""

    def grammar(self, profile, contract=None):
        return release_profile.grammar_violations(
            support.release_of("argus", profile), contract or support.base_contract())

    def test_the_argus_shaped_profile_has_no_violations(self):
        self.assertEqual(self.grammar(support.argus_shaped_profile()), [])

    def test_a_target_naming_another_domain_is_a_violation(self):
        profile = support.argus_shaped_profile()
        profile["bindings"]["targets"]["daemon"]["domain"] = "system"
        self.assertEqual([(v["pointer"], v["repair_id"]) for v in self.grammar(profile)],
                         [("/release/profiles/argus/bindings/targets/daemon", "contract.release.invalid")])

    def test_an_activation_profile_still_refuses_a_supported_deploy(self):
        contract = support.base_contract()
        contract["capabilities"]["deploy"]["support"] = "supported"
        contract["bindings"]["deploy"] = {"adapter": "github-actions-health", "command": None,
                                          "config": {}}
        self.assertIn("contract.release.deploy_conflict",
                      [v["repair_id"] for v in self.grammar(support.argus_shaped_profile(), contract)])
```

`tests/test_release_profile.py`:

```python
class HostLocalProfileTest(unittest.TestCase):
    def test_the_argus_shaped_profile_compiles_and_binds(self):
        compiled = release_profile.compile_profile("argus", support.argus_shaped_profile(),
                                                   support.base_contract())
        self.assertEqual(([n["id"] for n in compiled["publication"]],
                          [n["id"] for n in compiled["activation"]]), (["notifier"], ["daemon"]))
        self.assertEqual(dict(compiled["deadlines"]), {"notifier": 120000, "daemon": 300000})
        self.assertEqual(sorted(compiled["adapters"]), ["bundle", "launchd"])
        inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        units = {unit["name"]: unit for unit in inputs["proof"]["units"]}
        self.assertEqual((units["notifier"]["phase"], units["daemon"]["phase"]),
                         ("publication", "activation"))
        daemon = units["daemon"]["parameters"]
        self.assertEqual(daemon["target"], {"handle": "daemon", "kind": "launchd_gui_agent",
                                            "label": "dev.argus.daemon"})
        self.assertEqual(daemon["candidate"], {"version": "v1.2.3", "commit": "1" * 40})
        self.assertEqual(inputs["proof"]["obligations"][0]["parameters"]["parameters"],
                         {key: value for key, value in daemon.items() if key != "candidate"})
        self.assertEqual([unit["posture"] for unit in inputs["recovery"]["units"]],
                         ["supersedable_only", "supersedable_only"])
```

In `home/common/agent-skills/tests/test_resolve_project.py`, add `HostLocalReleaseTest(ResolverTestCase)` (docstring: issue 547 AC1). It has `STUBS = ("gh", "git", "just", "codex-companion", "claude-bash-lifecycle-guard", "codesign", "security", "launchctl")` and a `contract()` that is `source_contract()` with `release = {"profiles": {"argus": <fixture>, "forge-target": publication_free_profile()}}` (the spec's § The Argus-shaped profile: guard rows need a `github_repository` target). Its `test_the_argus_shaped_contract_resolves_available` resolves with `run_with_path(str(make_stub_bin(stubs)), "resolve", "--repo-root", …, home=self.home)` and asserts:
- `capabilities.release == {"state": "available", "reason_code": None, "repair_id": None}`;
- `[(t["profile"], t["adapter"], t["target"], t["operations"]) for t in release.targets]` equals
  `[("argus", "launchd-agent", {"handle": "daemon", "kind": "launchd_gui_agent", "label": "dev.argus.daemon"}, ["activate"]), ("argus", "codesigned-artifact", {"handle": "notifier", "kind": "installed_bundle", "path": "~/Library/Application Support/Argus/Argus.app"}, ["install"]), ("forge-target", "github-forge", {"handle": "repository", "kind": "github_repository", "repository": "fagenorn/nix-config", "branch": "main"}, [])]`;
- the same contract with `STUBS[:-1]` (no `launchctl`) gives `{"state": "blocked", "reason_code": "release_adapter_unavailable", "repair_id": "capability.release.release_adapter_unavailable"}`.

Add `DeployWatchTest.test_a_local_apply_adapter_is_unwatchable` (issue 547 D10). `self.jarbird()` with `bindings.deploy = {"adapter": "launchd-agent", "command": None, "config": {}}` is refused `invalid_contract`, with `repair_id` `contract.deploy.adapter_unwatchable` and violation pointers exactly `["/bindings/deploy/adapter"]`. It passes as soon as it is written: it pins D10 end to end.

In `tests/test_release_command.py`, add `HostLocalInspectTest(ReleaseCommandCase)`. Its `test_the_argus_shaped_profile_is_admissible` writes the contract with the same two profiles, read from `REPO / "tests/fixtures/release"`, runs `profile inspect argus`, and asserts:
- exit 0, `profile.admissible` true, and `conformance.findings == []`;
- the publication and activation graph ids `["notifier"]` and `["daemon"]`;
- `graphs.handoffs == [{"from": "publication", "to": "activation", "receipt": "publication_receipt"}]`;
- `[(o["id"], o["predicate"]) for o in graphs.proof] == [("derived:published_artifact_identity:notifier", "publication_visible"), ("derived:running_subject_identity:daemon", "running_subject_identity"), ("daemon-live", "agent_running")]`;
- `bindings.adapters.bundle.adapter == "codesigned-artifact"`, and `conformance.adapters.launchd.modes == {"activate": "supported"}`.

- [ ] **Step 2: Run the tests and watch them fail**

Write the tests before the fixture and the support function.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_command.py -k HostLocal 2>&1 | tail -4'`
Expected: FAIL — `AttributeError: module 'tests.release_test_support' has no attribute 'argus_shaped_profile'` and `FileNotFoundError` for the fixture.

- [ ] **Step 3: Write the minimal implementation**

Add the fixture and `argus_shaped_profile()`. At the end of § Release profiles, add one paragraph under 700 bytes, written from the code. It names the liveness route:
- an authored obligation with `semantic: liveness`, `form: snapshot`, `predicate: agent_running` and the `launchd-agent` alias as collector, usually depending on `derived:running_subject_identity:<unit>`;
- its `parameters.parameters` restates the unit's `action`, `operation`, normalized `target` and `config` (124 D24);
- `tests/fixtures/release/argus-shaped-profile.json` is the worked example.

Edit no other README line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_command.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k "HostLocal" -k "DeployWatch" -k "ReleaseMember" 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if grep -rqi argus python/agent_tools/; then exit 1; fi`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/release/argus-shaped-profile.json tests/release_test_support.py tests/test_release_grammar.py tests/test_release_profile.py home/common/agent-skills/tests/test_resolve_project.py tests/test_release_command.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T6): the Argus-shaped profile compiles, resolves and inspects" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":6,"records":[{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r6a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r6a","last_task":6,"owner":6,"path":"tests/fixtures/release/argus-shaped-profile.json"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r6b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6b","last_task":6,"owner":6,"path":"tests/release_test_support.py"},{"bounds":[{"added_lines":32,"boundary":"all","deleted_lines":2,"record_bytes":6144,"support":{"covers":["r3e","r5e","r6c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6c","last_task":6,"owner":6,"path":"tests/test_release_grammar.py"},{"bounds":[{"added_lines":26,"boundary":"all","deleted_lines":0,"record_bytes":4096,"support":{"covers":["r6d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6d","last_task":6,"owner":6,"path":"tests/test_release_profile.py"},{"bounds":[{"added_lines":50,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r6e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6e","last_task":6,"owner":6,"path":"home/common/agent-skills/tests/test_resolve_project.py"},{"bounds":[{"added_lines":26,"boundary":"all","deleted_lines":0,"record_bytes":5120,"support":{"covers":["r6f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6f","last_task":6,"owner":6,"path":"tests/test_release_command.py"},{"bounds":[{"added_lines":7,"boundary":"all","deleted_lines":1,"record_bytes":30720,"support":{"covers":["r1c","r3f","r5f","r6g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r6g","last_task":7,"owner":6,"path":"python/README.md"}]}}
```
