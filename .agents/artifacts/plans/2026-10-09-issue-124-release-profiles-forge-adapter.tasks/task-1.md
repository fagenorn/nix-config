# Task 1: Descriptor schema, closed registry, forge descriptor and profile grammar

**Files:**
- Create: `python/agent_tools/release_adapter.py` (descriptor half only; Task 6 adds results and `core_binding`)
- Create: `python/agent_tools/forge_adapter.py` (`describe()` only; Tasks 6–7 add `inspect`/`invoke`)
- Create: `python/agent_tools/release_profile.py` (grammar only; Task 2 adds the compiler)
- Create: `tests/release_test_support.py`
- Create: `tests/fixtures/release/github-release-profile.json`, `tests/fixtures/release/fixture-store-descriptor.json`, `tests/fixtures/release/restorable-profile.json`, `tests/fixtures/release/destroyed-anchor-profile.json` (JSON fixtures, so the suites under `home/common/agent-skills/tests/` load the same data by path)
- Test: `tests/test_release_grammar.py`
- Modify: `justfile` (add `tests/test_release_grammar.py` to `agent-workflow-tests`, after `tests/test_transaction_core_sweep.py`)

Decisions: D2, D4, D7, D8, D17, D18, D19 (descriptor shape), D23 (obligation ids are not pattern-checked). Spec §2, §6, §7 (descriptor only).

**Interfaces:**
- Consumes: `canonical.telemetry_digest`, `agent_platform.parse_semver` (triple or None), `transaction_plan.RESERVED_PREDICATES` and `MAX_COLLECTION_LATENCY_MS` (read, never copied).
- Produces (`release_adapter`):
  - string tuples, in this order: `PUBLICATION_MODES` (materialize, promote, index), `ACTIVATION_MODES` (local_apply, provider_deploy, publication_triggered, convergent_pull), `EFFECT_CLASSES` (reversible_no_incremental_spend, reversible_bounded_spend, irreversible), `MUTABILITIES` (create_if_absent, pointer_cas, in_place), `SUPPORT` (supported, unsupported), `HOST_CAPACITY` (not_required, required), `CONFIG_TYPES` (string, integer, boolean).
  - `descriptor_problems(descriptor: object) -> list[str]` — every schema violation, `[]` when valid.
  - `descriptor_digest(descriptor: dict) -> str` = `telemetry_digest(descriptor)`.
  - `build_descriptors(modules: Mapping[str, ModuleType]) -> MappingProxyType[str, dict]` — calls each module's `describe()`, raises `ValueError` naming the first problem, or when a descriptor's `name` differs from its key.
  - `REGISTRY = MappingProxyType({"github-forge": forge_adapter})`; `DESCRIPTORS = build_descriptors(REGISTRY)` (built at import, so a bad descriptor fails `just build`'s import check).
  - `config_problems(schema: dict, config: object) -> list[str]`.
- Produces (`forge_adapter`): `describe() -> dict`, a fresh plain dict each call, exactly the value pinned below.
- Produces (`release_profile`):
  - `ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")`.
  - `GRAMMAR_REPAIR_IDS = ("contract.release.invalid", "contract.release.reference_unknown", "contract.release.adapter_unsupported", "contract.release.config_invalid", "contract.release.effect_unsupported", "contract.release.same_repository", "contract.release.deploy_conflict")`.
  - `grammar_violations(release: object, contract: object, descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS) -> list[dict]` — each `{"pointer", "message", "repair_id"}`, unsorted, never raises on any JSON value.
- Produces (`tests/release_test_support.py`): `FIXTURES = Path(__file__).parent / "fixtures/release"`, `FIXTURE_STORE` (dict loaded from `fixture-store-descriptor.json`), `descriptors()` (`{"github-forge": forge_adapter.describe(), "fixture-store": FIXTURE_STORE}`), `base_contract()`, `forge_profile()`, `restorable_profile()`, `destroyed_anchor_profile()`, `release_of(profile_id, profile)` (`{"profiles": {profile_id: profile}}`). Every function returns a fresh deep copy.

**Invariants:**
- `grammar_violations` reads only `release`, `contract["bindings"]["tracker"]`, `contract["bindings"]["vcs"]["default_branch"]` and `contract["capabilities"]["deploy"]`, each through `isinstance` guards; a malformed contract yields no extra violation and no exception.
- Every object in the profile is closed: unknown or missing members are `contract.release.invalid`.
- The grammar does **not** judge proof `semantic`/`form`/`predicate`, recovery `posture`/edge `action` values, nor the presence or range of `observation_deadline_ms` (only that it is an `int`, not a `bool`, when present) (D2).
- Every `repair_id` emitted is in `GRAMMAR_REPAIR_IDS`.
- `forge_adapter` never imports `release_adapter` (the registry imports it); it imports only the standard library here, and Task 7 adds `adopt_planning`.

## The forge descriptor (exact, D8, D19)

```python
{"name": "github-forge", "adapter_contract_version": "1.0.0",
 "operations": {
   "pr_merge": {"mode": "materialize", "support": "unsupported", "inspect": "supported",
                "reason": "target_cas_unproven", "mutability": "pointer_cas",
                "config_schema_version": 1, "config_schema": {"members": {}, "required": []},
                "effects": ["irreversible"], "recovery_capable": False, "candidate_members": []},
   "tag": {"mode": "index", "support": "supported", "inspect": "supported", "reason": None,
           "mutability": "create_if_absent", "config_schema_version": 1,
           "config_schema": {"members": {}, "required": []}, "effects": ["irreversible"],
           "recovery_capable": False, "candidate_members": []},
   "release": {... same as "tag" ..., "candidate_members": ["notes", "title"]}},
 "predicates": {"publication_visible": {"support": "supported", "reason": None},
                "running_subject_identity": {"support": "unsupported", "reason": "no_activation_mode"}},
 "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
 "target_kinds": {"github_repository": ["branch", "repository"]},
 "credential_classes": ["gh_keyring"],
 "executables": ["claude-bash-lifecycle-guard", "gh", "git"],
 "host_capacity": "not_required"}
```

## Descriptor schema rules (`descriptor_problems`, D19)

1. Exactly the nine top-level members above; `name` matches `ID_PATTERN`; `adapter_contract_version` parses with `parse_semver`.
2. `operations` is a non-empty object; each key matches `^[a-z][a-z0-9_]{0,62}$`; each entry has exactly `mode, support, inspect, reason, mutability, config_schema_version, config_schema, effects, recovery_capable, candidate_members`.
3. `mode` ∈ `PUBLICATION_MODES + ACTIVATION_MODES` or `None`; `None` only when `recovery_capable` is `True` (a recovery-only operation).
4. `support`, `inspect` ∈ `SUPPORT`; `reason` is a non-empty string exactly when `support == "unsupported"`, else `None`.
5. `mutability` ∈ `MUTABILITIES`; `effects` a non-empty list of unique `EFFECT_CLASSES`; `recovery_capable` a bool; `config_schema_version` a positive int (not bool); `candidate_members` a sorted unique list drawn from `("notes", "title")`.
6. `config_schema` is exactly `{"members": {name: CONFIG_TYPE}, "required": [names ⊆ members]}`.
7. `predicates`: every value exactly `{"support", "reason"}` with rule 4's reason rule; every value of `transaction_plan.RESERVED_PREDICATES` is a key; when any operation has `support == "supported"` and a mode in `PUBLICATION_MODES`, `publication_visible` is `supported`.
8. `collector` exactly `{max_collection_latency_ms: int in [1, transaction_plan.MAX_COLLECTION_LATENCY_MS], max_concurrent_collections: int ≥ 1}`.
9. `target_kinds`: non-empty object kind → sorted unique list of member names, none of them `adapter` or `kind`; `credential_classes` and `executables`: non-empty sorted unique lists of non-empty strings; `host_capacity` ∈ `HOST_CAPACITY`.

`config_problems(schema, config)`: `config` must be an object whose keys ⊆ `schema["members"]`, ⊇ `schema["required"]`, each value of its declared type (`integer` excludes `bool`).

## Grammar rules (`grammar_violations`, spec §1–§2)

Shapes are spec §2's table; pointers are under `/release`; profiles in sorted id order; every rule runs and all violations are collected. Repair id suffixes (`contract.release.<suffix>`):

| # | Rule | Suffix |
|---|------|--------|
| G1 | `release` is `"unsupported"` or exactly `{profiles}`, a non-empty object with `ID_PATTERN` keys | invalid |
| G2–G5 | the nine groups exactly; `profile_version` positive int; `target`, `requirements` (both SemVer bounds, min < max), `bindings` (exactly four maps, `ID_PATTERN` keys; a target carries `adapter`, `kind` and exactly its kind's `target_kinds` members, all non-empty strings) closed per spec §2 | invalid |
| G6 | `requirements.adapters` keys == `bindings.adapters` keys; target/credential `adapter` names an alias | reference_unknown |
| G7 | unregistered adapter name; selected `adapter_contract_version` outside `[min, max)`; target `kind` / credential `class` not declared | adapter_unsupported |
| G8 | `publication` `{actions}` and `activation` `"none"` or `{units}` (non-empty lists); node members exactly spec §2's plus optional int (not bool) `observation_deadline_ms`; node `id` `ID_PATTERN`, unique across phases; mode in its phase's set; `effect` ∈ `EFFECT_CLASSES` | invalid |
| G9 | node `adapter`/`target`/`principal`/`credential` exist; target's and credential's `adapter` equal the node's; `deps` same-phase ids, no self, no cycle (pointer: first cycle node in authored order) | reference_unknown |
| G10 | `effect == "reversible_bounded_spend"` | effect_unsupported |
| G11 | operation unknown, not `supported`, mode ≠ node mode, or effect not in its `effects` | adapter_unsupported |
| G12 | `config_schema_version` ≠ the operation's, or `config_problems` non-empty | config_invalid |
| G13 | `proof` exactly `{convergence_window_ms: positive int, obligations: list}`; obligation members per spec §2 (+ optional int `freshness_ms`), strings non-empty, `id` not pattern-checked (D23) | invalid |
| G14 | obligation `collector` names an alias | reference_unknown |
| G15 | `recovery` `{units}`; unit exactly `{posture, anchor, compatibility, edges}` with spec §2's shapes (edge `residue` str or null) | invalid |
| G16 | recovery keys == node ids (missing → `…/recovery/units`); `anchor.target` names a target handle | reference_unknown |
| G17 | `github_repository`: `repository` ≠ `tracker.repo_slug`, `tracker.kind` ≠ `github`, or `branch` ≠ `vcs.default_branch` | same_repository |
| G18 | profiles while `capabilities.deploy.support` ≠ `unsupported` (pointer `/capabilities/deploy/support`) | deploy_conflict |
| G19 | `limits` ≠ `{}` | invalid |

A rule whose input is already reported malformed adds no second violation for that node.

- [ ] **Step 1: Write the fixtures and `tests/release_test_support.py`**

`base_contract()` returns `{"bindings": {"tracker": {"kind": "github", "repo_slug": "fagenorn/nix-config"}, "vcs": {"default_branch": "main"}}, "capabilities": {"deploy": {"support": "unsupported"}}}`. `forge_profile()` loads `github-release-profile.json`, whose content is the spec §4 profile exactly as `.agents/project.json` will carry it (Task 4 asserts equality), pretty-printed with two-space indentation from:

```json
{"profile_version": 1, "target": {"environment": "github-main", "concurrency_keys": ["release/fagenorn/nix-config"]}, "requirements": {"adapters": {"forge": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}}}, "bindings": {"adapters": {"forge": {"adapter": "github-forge"}}, "targets": {"repository": {"adapter": "forge", "kind": "github_repository", "repository": "fagenorn/nix-config", "branch": "main"}}, "principals": {"maintainer": {"class": "forge_write"}}, "credentials": {"forge-keyring": {"adapter": "forge", "class": "gh_keyring"}}}, "publication": {"actions": [{"id": "tag", "mode": "index", "adapter": "forge", "operation": "tag", "target": "repository", "principal": "maintainer", "credential": "forge-keyring", "effect": "irreversible", "config_schema_version": 1, "config": {}, "deps": [], "observation_deadline_ms": 600000}, {"id": "github-release", "mode": "index", "adapter": "forge", "operation": "release", "target": "repository", "principal": "maintainer", "credential": "forge-keyring", "effect": "irreversible", "config_schema_version": 1, "config": {}, "deps": ["tag"], "observation_deadline_ms": 600000}]}, "activation": "none", "proof": {"convergence_window_ms": 1800000, "obligations": []}, "recovery": {"units": {"tag": {"posture": "supersedable_only", "anchor": null, "compatibility": null, "edges": []}, "github-release": {"posture": "supersedable_only", "anchor": null, "compatibility": null, "edges": []}}}, "limits": {}}
```

`fixture-store-descriptor.json` holds a valid descriptor named `fixture-store`, version `1.4.0`, with operations: `publish` (materialize, create_if_absent, config `{"members": {"bucket": "string"}, "required": ["bucket"]}`, effects `["irreversible", "reversible_no_incremental_spend"]`), `promote` (promote, pointer_cas), `overwrite` (materialize, in_place), `repoint` (mode `None`, pointer_cas, `recovery_capable: True`), `retain` (mode `None`, create_if_absent, `recovery_capable: True`), `legacy` (index, `support: "unsupported"`, `reason: "fixture_unsupported"`); all others supported, `config_schema_version` 1, empty config schema, effects `["reversible_no_incremental_spend"]`, `candidate_members: []`. Predicates: `publication_visible`, `pointer_at`, `schema_compatible` supported; `running_subject_identity` unsupported/`no_activation_mode`. Collector `{1000, 2}`; `target_kinds: {"object_store": ["bucket_url"]}`; `credential_classes: ["fixture_token"]`; `executables: ["fixture-store-cli"]`; `host_capacity: "not_required"`.

`restorable_profile()` loads `restorable-profile.json`: alias `store` → `fixture-store` (range `1.0.0`–`2.0.0`); target `bucket` = `{adapter: store, kind: object_store, bucket_url: "s3://fixture"}`; principal `operator` `{class: "deployer"}`; credential `store-token` `{adapter: store, class: fixture_token}`; actions `publish-artifact` (materialize/publish, effect `reversible_no_incremental_spend`, config `{"bucket": "artifacts"}`, deadline 60000) and `promote-pointer` (promote/promote, config `{}`, deps `["publish-artifact"]`, deadline 60000); activation `"none"`; proof `{1800000, []}`; recovery `publish-artifact`: compensatable with one edge `{action: compensate, operation: retain, parameters: {}, residue: "artifact retained unreferenced"}`; `promote-pointer`: restorable, anchor `{target: bucket, predicate: pointer_at, parameters: {}}`, compatibility `{predicate: schema_compatible, parameters: {}}`, edges `[{action: restore, operation: repoint, parameters: {}, residue: None}]`; limits `{}`.

`destroyed-anchor-profile.json` is `restorable-profile.json` plus action `{"id": "overwrite-index", "mode": "materialize", "adapter": "store", "operation": "overwrite", "target": "bucket", "principal": "operator", "credential": "store-token", "effect": "reversible_no_incremental_spend", "config_schema_version": 1, "config": {}, "deps": [], "observation_deadline_ms": 60000}` with recovery unit `{"posture": "supersedable_only", "anchor": null, "compatibility": null, "edges": []}`; it is grammar-valid and inadmissible only by Task 2's rule 3.

- [ ] **Step 2: Write the failing test `tests/test_release_grammar.py`**

```python
"""Release profile grammar and adapter descriptors (#124). Run: just agent-workflow-tests"""
import copy
import unittest

from agent_tools import forge_adapter, release_adapter, release_profile
from . import release_test_support as support

def violations(release, contract=None):
    return release_profile.grammar_violations(
        release, contract or support.base_contract(), support.descriptors())

class DescriptorTest(unittest.TestCase):
    def test_forge_and_fixture_descriptors_are_valid(self):
        self.assertEqual(release_adapter.descriptor_problems(forge_adapter.describe()), [])
        self.assertEqual(release_adapter.descriptor_problems(support.FIXTURE_STORE), [])

    def test_registry_is_closed(self):
        self.assertEqual(sorted(release_adapter.REGISTRY), ["github-forge"])
        self.assertEqual(sorted(release_adapter.DESCRIPTORS), ["github-forge"])

    def test_forge_descriptor_pins_pr_merge_unsupported(self):
        op = forge_adapter.describe()["operations"]["pr_merge"]
        self.assertEqual((op["mode"], op["support"], op["inspect"], op["reason"], op["mutability"]),
                         ("materialize", "unsupported", "supported", "target_cas_unproven", "pointer_cas"))
        self.assertEqual(forge_adapter.describe()["host_capacity"], "not_required")

    def test_descriptor_problems_catch_each_rule(self):
        cases = {
            "extra member": lambda d: d.update(extra=1),
            "bad version": lambda d: d.update(adapter_contract_version="1.0"),
            "mode null without recovery": lambda d: d["operations"]["tag"].update(mode=None),
            "reserved predicate missing": lambda d: d["predicates"].pop("running_subject_identity"),
            "publication without visibility": lambda d: d["predicates"]["publication_visible"].update(
                support="unsupported", reason="r"),
            "latency over core cap": lambda d: d["collector"].update(max_collection_latency_ms=300_001),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                descriptor = forge_adapter.describe()
                mutate(descriptor)
                self.assertNotEqual(release_adapter.descriptor_problems(descriptor), [])

    def test_build_descriptors_refuses_a_name_mismatch(self):
        with self.assertRaises(ValueError):
            release_adapter.build_descriptors({"other-name": forge_adapter})

class GrammarAcceptsTest(unittest.TestCase):
    def test_valid_shapes_have_no_violations(self):
        self.assertEqual(violations("unsupported"), [])
        self.assertEqual(violations(support.release_of("github-release", support.forge_profile())), [])
        self.assertEqual(violations(support.release_of("restorable", support.restorable_profile())), [])
        self.assertEqual(violations(support.release_of("restorable", support.destroyed_anchor_profile())), [])

    def test_vocabularies_left_to_the_core_are_not_judged(self):
        profile = support.forge_profile()
        del profile["publication"]["actions"][0]["observation_deadline_ms"]
        profile["proof"]["obligations"].append({
            "id": "derived:published_artifact_identity:tag", "semantic": "published_artifact_identity",
            "form": "event", "predicate": "publication_visible", "collector": "forge",
            "required": True, "deps": [], "parameters": {}})
        profile["recovery"]["units"]["tag"]["posture"] = "not-a-posture"
        self.assertEqual(violations(support.release_of("github-release", profile)), [])

class GrammarRefusesTest(unittest.TestCase):
    def refused(self, mutate, repair_id, pointer_prefix="/release"):
        profile = support.forge_profile()
        contract = support.base_contract()
        mutate(profile, contract)
        found = violations(support.release_of("github-release", profile), contract)
        self.assertTrue(found, "expected a violation")
        self.assertIn(repair_id, [v["repair_id"] for v in found])
        for v in found:
            self.assertIn(v["repair_id"], release_profile.GRAMMAR_REPAIR_IDS)
            self.assertEqual(sorted(v), ["message", "pointer", "repair_id"])
        self.assertTrue(any(v["pointer"].startswith(pointer_prefix) for v in found))

    def test_top_level_shapes(self):
        for value in (None, "", "Unsupported", {}, {"profiles": {}}, {"profiles": {"Bad_Id": {}}},
                      {"profiles": {}, "extra": 1}, []):
            with self.subTest(value=value):
                self.assertIn("contract.release.invalid",
                              [v["repair_id"] for v in violations(value)])

    def test_each_rule(self):
        def act(**kw):
            return lambda p, c: p["publication"]["actions"][0].update(**kw)
        cases = [
            (lambda p, c: p.pop("limits"), "invalid"),
            (lambda p, c: p.update(limits={"max_spend": 1}), "invalid"),
            (lambda p, c: p["requirements"]["adapters"]["forge"].update(min_inclusive="2.0.0"), "invalid"),
            (lambda p, c: p["requirements"]["adapters"].update(
                forge={"min_inclusive": "2.0.0", "max_exclusive": "3.0.0"}), "adapter_unsupported"),
            (lambda p, c: p["bindings"]["adapters"]["forge"].update(adapter="railway"), "adapter_unsupported"),
            (act(target="nowhere"), "reference_unknown"),
            (act(deps=["github-release"]), "reference_unknown"),
            (act(effect="reversible_bounded_spend"), "effect_unsupported"),
            (act(operation="pr_merge", mode="materialize"), "adapter_unsupported"),
            (act(mode="promote"), "adapter_unsupported"),
            (act(config_schema_version=2), "config_invalid"),
            (act(config={"x": 1}), "config_invalid"),
            (act(observation_deadline_ms=True), "invalid"),
            (lambda p, c: p["recovery"]["units"].pop("tag"), "reference_unknown"),
            (lambda p, c: p["proof"]["obligations"].append({
                "id": "o", "semantic": "liveness", "form": "event", "predicate": "p",
                "collector": "nobody", "required": True, "deps": [], "parameters": {}}), "reference_unknown"),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(repository="x/y"), "same_repository"),
            (lambda p, c: p["bindings"]["targets"]["repository"].update(branch="dev"), "same_repository"),
            (lambda p, c: c["bindings"]["tracker"].update(kind="gitlab"), "same_repository"),
        ]
        for index, (mutate, repair) in enumerate(cases):
            with self.subTest(index=index, repair=repair):
                self.refused(mutate, "contract.release." + repair)

    def test_profiles_force_deploy_unsupported(self):
        self.refused(lambda p, c: c["capabilities"]["deploy"].update(support="supported"),
                     "contract.release.deploy_conflict", "/capabilities/deploy/support")

    def test_malformed_contract_never_raises(self):
        for contract in ({}, {"bindings": []}, {"bindings": {"tracker": None}}, []):
            with self.subTest(contract=contract):
                violations(support.release_of("github-release", support.forge_profile()), contract)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `unittest tests/test_release_grammar.py`
Expected: ERROR — `ImportError: cannot import name 'forge_adapter' from 'agent_tools'`.

- [ ] **Step 4: Implement**

`forge_adapter.describe()` returns the pinned dict (build it fresh each call). `release_adapter` implements the schema rules in order, `build_descriptors`, `REGISTRY`, `DESCRIPTORS`, `config_problems`, `descriptor_digest`. `release_profile.grammar_violations` implements G1–G19 in that order per profile (profiles in sorted id order), collecting every violation; it imports `release_adapter` and `agent_platform` only (plus `re`, `copy`). Module docstrings state the contract each module owns, citing #124 D2/D7/D19.

- [ ] **Step 5: Verify**

Run: `unittest tests/test_release_grammar.py`
Expected: PASS, 11 tests. Then `PYTHONPATH="$PWD/python" python3 -c "import agent_tools.release_profile"` exits 0 (the import-time registry build passes).

- [ ] **Step 6: Commit** exactly the **Files** above as `feat(release): adapter descriptors, closed registry and profile grammar (#124)`.
