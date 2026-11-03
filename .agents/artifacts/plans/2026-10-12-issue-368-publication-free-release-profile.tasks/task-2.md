# Task 2: The grammar accepts `"publication": "none"`, with the binding refusal and the inspection report

Spec sections 1, 2 and 5 (per D1, D2, D3, D7, D8, D11, D14). This is the one commit in which a publication-free profile becomes a valid contract, so the same commit carries everything that must hold for it: `bind_candidate` refuses it, `release profile inspect` reports it, and the end-to-end resolver cases prove the capability and the target. Do not split this task into several commits.

**Files:**
- Modify: `python/agent_tools/release_profile.py` (`_Profile` grammar, `bind_candidate`, module docstring)
- Modify: `python/agent_tools/release.py` (`_graphs`, `inspect_profile`, module docstring)
- Test (additions only): `tests/test_release_grammar.py`, `tests/test_release_profile.py`, `tests/test_release_adapter_core.py`, `tests/test_release_command.py`, `home/common/agent-skills/tests/test_resolve_project.py`

**Interfaces:**
- Consumes (Task 1): `release_profile.phase_nodes(profile, phase) -> list[dict]` (`[]` for a `"none"` phase), already used by `_authored`, `lower` and `compile_profile`; `resolve_project.release_capability` already `unsupported` when no profile publishes; the snapshot's `release.targets` member; `tests/release_test_support.publication_free_profile()`; in the resolver suite the module-level `publication_free_profile()` and `ReleaseMemberTest.declaring(**profiles)` (keyword `forge_target` becomes profile id `forge-target`), `snapshot(contract, stubs=STUBS)`, `UNSUPPORTED`, `REPOSITORY`.
- Produces: the grammar form; `bind_candidate` raising `ValueError` for a compiled profile with no publication node (signature unchanged); the inspection report for a publication-free profile.

**Invariants:**
- `grammar_violations` still never raises on any JSON value and reports each malformed input once.
- `{"actions": []}`, an omitted `publication` and any value other than `"none"` or an object stay `contract.release.invalid`; every profile grammar-valid at base keeps its results.
- A publication-free profile with an activation other than `"none"` yields exactly one violation for it, whatever that activation contains (D11).
- The same-repository rule is not edited.
- `bind_candidate`'s refusal comes after the `TypeError` check on `compiled` and before the candidate is read; its message contains the profile id in `repr` form followed by ` declares no publication`.
- `release_adapter.py` and `forge_adapter.py` are not edited; with a publication-free compiled profile no `gh`, `git` or `claude-bash-lifecycle-guard` child process is started by any `CoreBinding` request.
- For every profile with at least one publication action the inspection report is what it was at base. For a publication-free profile `graphs` is exactly `{"phases": ["publication", "activation"], "publication": [], "activation": [], "handoffs": [], "proof": [], "recovery": []}`. `_profile_error` is not edited.
- After this task `release.py` holds no `"none"` literal and no `["publication"]["actions"]` / `["activation"]["units"]` indexing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_release_grammar.py`, above the `if __name__` line. The assertions compare whole violation lists, so an extra, missing or reworded violation fails:

```python
class PublicationFreeGrammarTest(unittest.TestCase):
    """`"publication": "none"` and the rules that hold for it (#368 D1, D2, D11)."""
    BASE = "/release/profiles/forge-target"

    def found(self, mutate=None):
        profile, contract = support.publication_free_profile(), support.base_contract()
        if mutate is not None:
            mutate(profile, contract)
        return violations(support.release_of("forge-target", profile), contract)

    def test_the_fixture_declares_a_target_and_has_no_violation(self):
        profile = support.publication_free_profile()
        self.assertEqual((profile["publication"], profile["activation"]), ("none", "none"))
        self.assertEqual(profile["bindings"]["targets"], {"repository": {
            "adapter": "forge", "kind": "github_repository",
            "repository": "fagenorn/nix-config", "branch": "main"}})
        self.assertEqual(self.found(), [])

    def test_a_stray_activation_is_one_violation_and_is_judged_no_further(self):
        action = support.forge_profile()["publication"]["actions"][0]
        for activation in ({"units": [action]}, {"units": [{"id": "Bad Id"}, 7], "extra": 1},
                           {"units": []}, "nothing", 7):
            with self.subTest(activation=activation):
                self.assertEqual(self.found(lambda p, c: p.update(activation=activation)), [{
                    "pointer": self.BASE + "/activation", "repair_id": "contract.release.invalid",
                    "message": 'activation must be "none" when publication is "none"'}])

    def test_a_stray_obligation_is_one_violation(self):
        obligation = {"id": "o", "semantic": "liveness", "form": "event", "predicate": "p",
                      "collector": "forge", "required": True, "deps": [], "parameters": {}}
        self.assertEqual(self.found(lambda p, c: p["proof"]["obligations"].append(obligation)), [{
            "pointer": self.BASE + "/proof/obligations", "repair_id": "contract.release.invalid",
            "message": 'obligations must be [] when publication is "none"'}])

    def test_a_stray_recovery_unit_is_the_existing_unknown_reference(self):
        unit = {"posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}
        self.assertEqual(self.found(lambda p, c: p["recovery"]["units"].update(tag=unit)), [{
            "pointer": self.BASE + "/recovery/units/tag",
            "repair_id": "contract.release.reference_unknown",
            "message": "recovery key tag names no action or unit"}])

    def test_the_publishing_form_and_the_same_repository_rule_are_unchanged(self):
        cases = [
            (lambda p, c: p.update(publication={"actions": []}), "invalid", "/publication/actions"),
            (lambda p, c: p.pop("publication"), "invalid", ""),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(repository="x/y"),
             "same_repository", "/bindings/targets/repository/repository"),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(branch="dev"),
             "same_repository", "/bindings/targets/repository/branch"),
            (lambda p, c: c["bindings"]["tracker"].update(kind="gitlab"),
             "same_repository", "/bindings/targets/repository/kind"),
        ]
        for index, (mutate, repair, pointer) in enumerate(cases):
            with self.subTest(index=index, pointer=pointer):
                self.assertEqual([(v["repair_id"], v["pointer"]) for v in self.found(mutate)],
                                 [("contract.release." + repair, self.BASE + pointer)])

    def test_any_other_publication_value_names_the_two_forms(self):
        for value in ("None", "unsupported", "", None, [], 0):
            with self.subTest(value=value):
                self.assertEqual(self.found(lambda p, c: p.update(publication=value)), [{
                    "pointer": self.BASE + "/publication", "repair_id": "contract.release.invalid",
                    "message": 'publication must be "none" or {actions}'}])

```

Append to `tests/test_release_profile.py`, above the `if __name__` line (the module defines `compile_`, `tree`, `D`):

```python
class PublicationFreeTest(unittest.TestCase):
    """A publication-free profile compiles to an empty graph and is never bound (#368 D3)."""

    def test_it_compiles_to_an_empty_graph(self):
        compiled = compile_("forge-target", support.publication_free_profile())
        self.assertEqual((compiled["schema"], compiled["profile_id"], compiled["profile_version"]),
                         ("release-profile/v1", "forge-target", 1))
        for member in ("publication", "activation"):
            self.assertEqual(list(compiled[member]), [])
        for member in ("deadlines", "candidate_members"):
            self.assertEqual(dict(compiled[member]), {})
        self.assertEqual(list(compiled["proof_declaration"]["units"]), [])
        self.assertEqual(list(compiled["proof_declaration"]["obligations"]), [])
        self.assertEqual(list(compiled["recovery_declaration"]["units"]), [])
        self.assertEqual(release_profile.thaw(compiled["adapters"]["forge"])["adapter"],
                         "github-forge")
        self.assertEqual(compiled["digest"],
                         release_profile.profile_digest(support.publication_free_profile(), D()))
        self.assertNotEqual(compiled["digest"],
                            compile_("forge-target", support.forge_profile())["digest"])

    def test_bind_candidate_refuses_it_before_reading_the_candidate(self):
        compiled = compile_("forge-target", support.publication_free_profile())
        for candidate in (support.CANDIDATE, None):
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                before = tree(root)
                with self.assertRaisesRegex(ValueError, "'forge-target' declares no publication"):
                    inputs = release_profile.bind_candidate(compiled, candidate)
                    TransactionStore(root).create(
                        "k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                        proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")
                self.assertEqual(tree(root), before)

```

Append to `tests/test_release_adapter_core.py`, above the `if __name__` line. The request is the exact `release` unit a publishing profile for the same repository binds, so the refusal cannot come from a malformed request; `ForgeWorld` replaces `PATH` with its own `gh`, `git` and guard and logs every call:

```python
class PublicationFreeBindingTest(unittest.TestCase):
    """No request reaches the adapter through a publication-free profile (#368 D3, D8)."""

    def test_every_request_is_refused_before_any_child_process(self):
        world = ForgeWorld(self)
        publishing = release_profile.compile_profile("github-release", support.forge_profile(),
                                                     support.base_contract())
        release = release_profile.bind_candidate(publishing, support.CANDIDATE)["proof"]["units"][1]
        self.assertEqual(release["parameters"]["operation"], "release")
        compiled = release_profile.compile_profile(
            "forge-target", support.publication_free_profile(), support.base_contract())
        binding = release_adapter.core_binding(forge_adapter, compiled, "forge")
        requests = {"inspect": {"parameters": release["parameters"]},
                    "invoke": {"parameters": release["parameters"]},
                    "observe": {"predicate": "publication_visible",
                                "parameters": {"parameters": release["parameters"]}}}
        for name, request in requests.items():
            with self.subTest(request=name):
                with self.assertRaisesRegex(ValueError, "is not a node bound to this alias"):
                    getattr(binding, name)(request)
        self.assertEqual(world.calls(), [])

```

Insert into `tests/test_release_command.py`, above `class AdapterInspectTest`:

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

Append to `ReleaseMemberTest` in `home/common/agent-skills/tests/test_resolve_project.py`, after the members Task 1 added:

```python
    def test_a_publication_free_profile_exposes_its_target_and_no_capability(self):
        snap = self.snapshot(self.declaring(forge_target=publication_free_profile()))
        self.assertEqual(snap["release"], {"targets": [{
            "profile": "forge-target", "adapter": "github-forge",
            "target": self.REPOSITORY, "operations": []}]})
        self.assertEqual(snap["capabilities"]["release"], self.UNSUPPORTED)
        self.assertEqual(sorted(snap), ["bindings", "capabilities", "project", "release",
                                        "schema_version"])

    def test_a_publication_free_profile_needs_no_adapter_executable(self):
        snap = self.snapshot(self.declaring(forge_target=publication_free_profile()),
                             stubs=("just", "codex-companion"))
        self.assertEqual(snap["capabilities"]["release"], self.UNSUPPORTED)

    def test_a_publication_free_target_for_another_repository_is_refused(self):
        for member, value in (("repository", "elsewhere/other"), ("branch", "dev")):
            with self.subTest(member=member):
                profile = publication_free_profile()
                profile["bindings"]["targets"]["repository"][member] = value
                code, payload, _ = self.resolve(
                    self.make_root(self.declaring(forge_target=profile)))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual(
                    [v["pointer"] for v in error["violations"]],
                    ["/release/profiles/forge-target/bindings/targets/repository/" + member])
                self.assertEqual(error["repair_id"], "contract.release.same_repository")
                self.assertNotIn("release", payload)

    def test_one_publishing_profile_beside_a_publication_free_one_is_available(self):
        free = publication_free_profile()
        free["target"]["concurrency_keys"] = ["release/fagenorn/nix-config/target-only"]
        snap = self.snapshot(self.declaring(forge_target=free, github_release=forge_profile()))
        self.assertEqual(snap["capabilities"]["release"]["state"], "available")
        self.assertEqual([(t["profile"], t["operations"]) for t in snap["release"]["targets"]],
                         [("forge-target", []), ("github-release", ["release", "tag"])])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_adapter_core.py tests/test_release_command.py home/common/agent-skills/tests/test_resolve_project.py -k PublicationFreeGrammar -k PublicationFreeTest -k PublicationFreeBinding -k PublicationFreeInspect -k ReleaseMemberTest`
Expected: every test added in Step 1 FAILS or ERRORS — the grammar reports `publication must be an object`, so `compile_profile` raises `ValueError`, the resolver refuses `invalid_contract` and the inspection command exits 2. The `ReleaseMemberTest` members that existed before this task pass.

- [ ] **Step 3: Implement the grammar in `python/agent_tools/release_profile.py`**

- `_Profile` records whether its profile is publication-free (an attribute set in `phases`, `False` until then).
- `phases`, the `publication` branch, in this order: the value `"none"` marks the profile publication-free and adds no violation; any other non-object adds one violation at `<base>/publication`, message exactly `publication must be "none" or {actions}`, suffix `invalid`; an object keeps today's `closed(..., {"actions"}, ...)` and `node_list` path unchanged.
- `phases`, the `activation` branch: `"none"` returns as today. Otherwise, when the profile is publication-free, add exactly one violation at `<base>/activation`, message exactly `activation must be "none" when publication is "none"`, suffix `invalid`, and return without judging that activation (no shape check, its units are not registered as nodes). When the profile is not publication-free the branch is unchanged.
- `proof`: after the existing "obligations must be a list" check, when the profile is publication-free and the list is non-empty, add one violation at `<base>/proof/obligations`, message exactly `obligations must be [] when publication is "none"`, suffix `invalid`; each obligation's own shape is still judged as today.
- `recovery` is not edited: with no declared node its existing rule reports each key as `contract.release.reference_unknown` (D11).
- `run` already calls `phases` before `proof` and `recovery`; keep that order.
- `bind_candidate`: directly after the `isinstance(compiled, ResolvedReleaseProfile)` check and before `_candidate_problem`, when `compiled["publication"]` is empty raise `ValueError` naming `compiled["profile_id"]` with `!r` and saying it declares no publication, so no release candidate can be bound to it. Extend its docstring with that refusal.
- Module docstring: state, from the code, the two `publication` forms, the rules a publication-free profile must meet and which existing rule covers recovery units.

- [ ] **Step 4: Implement the report in `python/agent_tools/release.py`**

- `_graphs`: `publication` and `activation` are `release_profile.ordered_nodes(release_profile.phase_nodes(profile, <phase>))`. `handoffs` is the existing one-entry list when `publication` is non-empty and `[]` when it is empty.
- `inspect_profile`: `nodes` is `ordered_nodes` over `phase_nodes(profile, "publication") + phase_nodes(profile, "activation")`.
- `_bindings`, `_conformance`, `_repairs`, `_profile_error` and the parser are not edited.
- Module docstring: add, from the code, that a publication-free profile is reported with empty graphs and no handoff and still exits 0.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_bridge.py tests/test_release_command.py tests/test_release_adapter_core.py home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_conformance_checks.py`
Expected: PASS, 0 failures, 0 errors.

Run:

```bash
git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'
if grep -nE '"none"|\["(publication|activation)"\]\["(actions|units)"\]' python/agent_tools/release.py; then exit 1; fi
```

Expected: every numstat row has `0` in its second column; the `grep` prints nothing. Also run the never-edited gate of Global Constraints (it covers both adapter modules and the guard).

- [ ] **Step 6: Commit (one commit)**

```bash
git add python/agent_tools/release_profile.py python/agent_tools/release.py \
  tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_adapter_core.py \
  tests/test_release_command.py home/common/agent-skills/tests/test_resolve_project.py
```

Commit through `launch-commit` with the message `feat(release-profile): accept "publication": "none" (#368)`.
