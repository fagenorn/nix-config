# Task 3: The required `release` member, derived `capabilities.release`, and conformance activation

**Files:**
- Modify: `python/agent_tools/resolve_project.py`
- Modify: `python/agent_tools/conformance_checks.py`, `python/agent_tools/conformance_registry.py`
- Modify: `.agents/project.json` and `home/common/agent-skills/evals/fixture-repo/.agents/project.json`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md` (line 23 only), `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_{resolve_project,conformance_checks,conformance_registry}.py` (the registry suite only if it pins finding codes)

Decisions: D1, D2, D14, D20 (AC6 restore-anchor seam), D21 (ship-release citation), D23 (blocked precedence). Spec §1, §10.

**Interfaces:**
- Consumes: Task 1–2's `grammar_violations`, `admissibility_findings`, `rule_findings`, `RULE_CHECKS`, `release_adapter.DESCRIPTORS`, and the `tests/fixtures/release/*.json` fixtures.
- Produces (`resolve_project`): `TOP_LEVEL_MEMBERS` ends `…, "platform", "release")`; `WORKFLOW_MEMBERS = ("verification", "orchestration", "review")`; `AUTHORED_CAPABILITY_NAMES` = `CAPABILITY_NAMES` without `"release"`; `REASON_CODES` gains `"release_profile_inadmissible"`, `"release_adapter_unavailable"`; `compute_capabilities(bindings, root, declarations, release, source)`; new `release_capability(release, source, root) -> dict` (`{"state", "reason_code", "repair_id"}`).
- Produces (`conformance_checks`): `RELEASE_DESCRIPTORS = release_adapter.DESCRIPTORS` (module global, the S3 patch point); `find_release_profile(context) -> tuple[str, dict | None]` returning `("absent", None)` or `("profiles", <profiles object>)`.

**Invariants:**
- `CAPABILITY_NAMES` and the snapshot's eleven capability entries are unchanged; `capabilities.release` is never authored (D1).
- `CAPABILITY_BINDING_REQUIREMENTS` has no `release` row; `first_unmet_prerequisite` has no `release` branch (it raises `ValueError` for `"release"`, which no caller passes).
- `release_capability`: `"unsupported"` → `{"state": "unsupported", "reason_code": None, "repair_id": None}`. Profiles, in sorted id order: the first profile with non-empty `admissibility_findings` → `blocked`/`release_profile_inadmissible`; else the first missing executable (every referenced alias's descriptor `executables`, each by `resolves_on_path(name, root)`, profiles and aliases in sorted order) → `blocked`/`release_adapter_unavailable`; else `available`. `repair_id` is `f"capability.release.{reason}"` (D23).
- Grammar violations join the one ordered violation list; nothing about a profile is `blocked` that the grammar refuses, and nothing the admissibility rules refuse is `invalid_contract` (D2).
- Conformance: `"unsupported"` → each of the three checks `not_run`, `subject_absent`, facts `{"declared": False}`. Profiles: for each check's rule (`RULE_CHECKS`), profiles in sorted id order, the first profile with a finding of that rule → `failed` with the check's reason code (`RULE_CHECKS[rule][1]`) and repair (`RULE_CHECKS[rule][2]`), facts `{"declared": True, "profile_id": bound_fact(id), "pointer": bound_fact(first finding pointer), "finding": bound_fact(first finding reason)}`; none → `passed`, facts `{"declared": True}`. `profile_unsupported` is gone from the registry (reverses #122 D27, per D14).

- [ ] **Step 1: Write the failing tests**

In `test_resolve_project.py` add near the top `RELEASE_FIXTURES = REPO_ROOT / "tests/fixtures/release"` and `def forge_profile(): return json.loads((RELEASE_FIXTURES / "github-release-profile.json").read_text("utf-8"))`, then:

```python
class ReleaseMemberTest(ResolverTestCase):
    STUBS = ("gh", "git", "just", "codex-companion", "claude-bash-lifecycle-guard")

    def profiles(self, profile=None):
        contract = source_contract()
        contract["release"] = {"profiles": {"github-release": profile or forge_profile()}}
        return contract

    def release_state(self, contract, stubs=STUBS):
        code, out, err = run_with_path(str(make_stub_bin(stubs)), "resolve", "--repo-root",
                                       str(self.make_root(contract)), home=self.home)
        self.assertEqual(code, 0, err or out)
        return json.loads(out)["capabilities"]["release"]

    def test_unsupported_release_resolves_unsupported(self):
        contract = source_contract()
        contract["release"] = "unsupported"
        self.assertEqual(self.release_state(contract),
                         {"state": "unsupported", "reason_code": None, "repair_id": None})

    def test_omitted_release_is_invalid_contract(self):
        contract = source_contract()
        del contract["release"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual([v["pointer"] for v in error["violations"]], ["/release"])
        self.assertEqual(error["repair_id"], "contract.top_level.member_missing")

    def test_leftover_authored_release_flags_are_unexpected(self):
        for mutate, pointer in (
                (lambda c: c["capabilities"].update(release={"support": "unsupported"}),
                 "/capabilities/release"),
                (lambda c: c["bindings"]["workflow"].update(release=None),
                 "/bindings/workflow/release")):
            with self.subTest(pointer=pointer):
                contract = source_contract()
                mutate(contract)
                code, payload, _ = self.resolve(self.make_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertIn(pointer, [v["pointer"] for v in error["violations"]])

    def test_profiles_derive_the_capability(self):
        self.assertEqual(self.release_state(self.profiles())["state"], "available")
        blocked = self.release_state(self.profiles(), stubs=("gh", "git", "just", "codex-companion"))
        self.assertEqual(blocked, {"state": "blocked", "reason_code": "release_adapter_unavailable",
                                   "repair_id": "capability.release.release_adapter_unavailable"})
        profile = forge_profile()
        del profile["publication"]["actions"][0]["observation_deadline_ms"]
        self.assertEqual(self.release_state(self.profiles(profile))["reason_code"],
                         "release_profile_inadmissible")

    def test_grammar_and_deploy_conflict_are_contract_errors(self):
        profile = forge_profile()
        profile["limits"] = {"max_spend": 1}
        code, payload, _ = self.resolve(self.make_root(self.profiles(profile)))
        self.assert_refusal(code, payload, "invalid_contract")
        contract = self.profiles()
        contract["capabilities"]["deploy"]["support"] = "supported"
        contract["bindings"]["deploy"] = {"adapter": "railway", "command": "nix-build", "config": {}}
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertIn("/capabilities/deploy/support", [v["pointer"] for v in error["violations"]])
```

Move `assert_refusal` up from `ErrorOutputTest` to `ResolverTestCase`. In `test_conformance_checks.py`, replace `test_a_declared_release_command_is_unsupported_not_absent` and `test_an_unknown_locator_state_raises`, and make the existing subject-absent test write `contract["release"] = "unsupported"` into the fixture root explicitly (it must not depend on what nix-config declares). Add (`RELEASE_FIXTURES` as above, via this file's repository-root constant):

```python
class ReleaseProfileChecksTest(ReportAssertions, unittest.TestCase):
    def doctor_with(self, profile):
        with fixture() as tmp:
            root = make_root(tmp)
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["release"] = {"profiles": {"github-release": profile}}
            path.write_text(json.dumps(contract), encoding="utf-8")
            report, by_id = doctor(self, root)
            self.assert_validates(report)
            return by_id

    def test_an_admissible_profile_passes_all_three(self):
        by_id = self.doctor_with(release_fixture("github-release-profile.json"))
        for check_id in RELEASE_PROFILE_IDS:
            self.assertEqual([by_id[check_id]["status"], by_id[check_id]["facts"]],
                             ["passed", {"declared": True}])

    def test_each_rule_fails_its_own_check(self):
        missing = release_fixture("github-release-profile.json")
        del missing["publication"]["actions"][0]["observation_deadline_ms"]
        restorable = release_fixture("github-release-profile.json")
        restorable["recovery"]["units"]["tag"] = {
            "posture": "restorable", "anchor": {"target": "repository", "predicate": "p", "parameters": {}},
            "compatibility": {"predicate": "q", "parameters": {}},
            "edges": [{"action": "restore", "operation": "tag", "parameters": {}, "residue": None}]}
        for profile, check_id, reason in (
                (missing, "repository.release_profile.observation_deadline", "observation_deadline_optional"),
                (restorable, "repository.release_profile.rolled_back_reachable", "rolled_back_unreachable")):
            with self.subTest(check_id=check_id):
                check = self.doctor_with(profile)[check_id]
                self.assertEqual([check["status"], check["reason_code"], check["facts"]["profile_id"]],
                                 ["failed", reason, "github-release"])

    def test_restore_anchor_fails_through_the_s3_seam(self):
        """D20: forge declares no in_place operation, so only an injected descriptor reaches it."""
        checks = load_module().CHECKS_MODULE
        store = release_fixture("fixture-store-descriptor.json")
        self.addCleanup(setattr, checks, "RELEASE_DESCRIPTORS", checks.RELEASE_DESCRIPTORS)
        checks.RELEASE_DESCRIPTORS = {**checks.RELEASE_DESCRIPTORS, "fixture-store": store}
        profile = release_fixture("destroyed-anchor-profile.json")
        context = types.SimpleNamespace(contract={"release": {"profiles": {"restorable": profile}}})
        outcome = checks.check_release_profile_restore_anchor(context)
        self.assertEqual((outcome.status, outcome.reason_code), ("failed", "restore_anchor_destroyed"))

    def test_profile_unsupported_is_retired(self):
        registry = load_module().REGISTRY_MODULE
        for check in registry.CHECKS:
            self.assertNotIn("profile_unsupported", [code for code, _ in check.findings])
```

(`release_fixture(name)` loads `RELEASE_FIXTURES / name`. `CHECKS_MODULE`, `REGISTRY_MODULE`, `CHECKS`, `findings`, `status`, `reason_code` follow the existing S3 tests and `conformance_registry.Check`; read them first and adjust only the test's spelling.)

Existing tests: in `test_resolve_project.py` replace each `del …["capabilities"]["release"]` by deleting `capabilities["deploy"]` (the test still needs a missing-member violation, now at `/capabilities/deploy`), and in `test_unsupported_capabilities_impose_no_binding_requirement` assert `contract["release"] == "unsupported"` instead of the `workflow.release` line. The `--require release` refusals stay valid (still `unsupported`) until Task 4.

- [ ] **Step 2: Run and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k ReleaseMember` and `… test_conformance_checks.py -k ReleaseProfileChecks`
Expected: FAIL — the resolver rejects `/release` as `member_unexpected`.

- [ ] **Step 3: Implement**

1. `resolve_project`: the constants above; `validate_capabilities` checks exact members against `AUTHORED_CAPABILITY_NAMES`; `validate_workflow` loses its `release` branch; `validate_contract` appends `release_profile.grammar_violations(source["release"], source)` when `"release" in source`; `compute_capabilities` takes `release` from `release_capability`, the rest as today. Remove or route every other read of an authored release flag (`declared_facts` included).
2. `conformance_checks`: rewrite the section comment and three docstrings for the activated behavior; `release_profile_outcome(context, rule)` implements the conformance invariant above and raises `ValueError` on an unknown locator state.
3. `conformance_registry`: delete the three `("profile_unsupported", …)` finding tuples.
4. Both contracts: add `"release": "unsupported"` as the last top-level member; delete `bindings.workflow.release` and `capabilities.release`.
5. `ship-release/SKILL.md` line 23: delete `` `bindings.workflow.release`, `` from the binding list (the sentence otherwise unchanged); delete `"bindings.workflow.release"` from the `ship-release/SKILL.md` tuple in `test_workflow_skill_contracts.py` (D21).

- [ ] **Step 4: Verify**

Run (each in the foreground, 900 s): `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_adopt_project.py tests/test_release_profile.py`
Expected: PASS, no failures or errors. Then `bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh` exits 0, and `if rg -q 'bindings\.workflow\.release|"workflow"\]\["release"|profile_unsupported' python home/common/agent-skills/skills; then exit 1; fi` exits 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py python/agent_tools/conformance_checks.py \
  python/agent_tools/conformance_registry.py .agents/project.json \
  home/common/agent-skills/evals/fixture-repo/.agents/project.json \
  home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/tests
git commit -m "feat(resolver): required release member, derived capability, live release-profile checks (#124)"
```
