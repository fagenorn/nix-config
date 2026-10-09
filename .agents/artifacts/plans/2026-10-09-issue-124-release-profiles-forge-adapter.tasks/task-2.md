# Task 2: Admissibility compiler, `ResolvedReleaseProfile` and `bind_candidate`

**Files:**
- Modify: `python/agent_tools/release_profile.py`
- Modify: `tests/release_test_support.py` (add `CANDIDATE` and the three inadmissible profile builders)
- Test: `tests/test_release_profile.py`
- Modify: `justfile` (add `tests/test_release_profile.py` after `tests/test_release_grammar.py`)

Decisions: D2, D3, D4, D5, D17, D19 (`candidate_members`), D20, D23. Spec §3.

**Interfaces:**
- Consumes: Task 1's `release_adapter`, `grammar_violations` and test support; the core's `compile_proof`, `compile_recovery`, `bind_recovery` (each `(declaration…, *, where)`), `ProofPlanRejected`/`RecoveryPlanRejected` (`.reason`), `MAX_CONVERGENCE_WINDOW_MS`, `TransactionStore`.
- Produces (`release_profile`):
  - `SCHEMA = "release-profile/v1"`; `RULES = ("observation_deadline", "rolled_back_reachable", "restore_anchor", "core_plans")`.
  - `RULE_CHECKS = MappingProxyType({"observation_deadline": ("repository.release_profile.observation_deadline", "observation_deadline_optional", "release_profile.deadline.require"), "rolled_back_reachable": ("repository.release_profile.rolled_back_reachable", "rolled_back_unreachable", "release_profile.compensate.add"), "restore_anchor": ("repository.release_profile.restore_anchor", "restore_anchor_destroyed", "release_profile.materialize.add")})` — `(check id, check reason code, repair id)`; Tasks 3 and 5 read it.
  - `class ProfileInadmissible(Exception)` with `.findings: tuple[dict, ...]` (non-empty).
  - `class ResolvedReleaseProfile(collections.abc.Mapping)` — deep-frozen (nested `MappingProxyType`, tuples), built only here; `thaw(value)` returns a plain deep copy.
  - `rule_findings(rule, profile_id, profile, contract, descriptors=DESCRIPTORS) -> list[dict]`.
  - `admissibility_findings(profile_id, profile, contract, descriptors=DESCRIPTORS) -> list[dict]` — the four rules in `RULES` order, concatenated.
  - `profile_digest(profile, descriptors=DESCRIPTORS) -> str`; `adapter_identities(profile, descriptors=DESCRIPTORS) -> dict`.
  - `ordered_nodes(nodes) -> list[dict]` (deterministic topological order); `lower(profile_id, profile, descriptors=DESCRIPTORS) -> (proof_declaration, recovery_declaration)`, candidate-independent.
  - `compile_profile(profile_id, profile, contract, descriptors=DESCRIPTORS) -> ResolvedReleaseProfile`.
  - `bind_candidate(compiled: ResolvedReleaseProfile, candidate: dict) -> dict` — `{"proof", "recovery", "concurrency_keys", "subject"}`, plain values.

**Invariants:**
- Every function here is pure: no file, clock, network or environment read.
- A finding is exactly `{"rule", "pointer", "reason", "detail"}`; `rule` ∈ `RULES`; pointers are `/release/profiles/<id>/…`.
- All findings are reported (every rule over every node), unlike the core's first-failure compilers; rule 4 contributes at most one `proof.*` and one `recovery.*` finding.
- `compile_profile` raises `ValueError` if `grammar_violations(release_of(id, profile), contract, descriptors)` is non-empty (callers resolve first), and `ProfileInadmissible` if `admissibility_findings` is non-empty.
- The compiled object and its digest are identical across two calls on equal input; mutating the input after compile changes nothing in the compiled object.
- No proof or recovery vocabulary is copied: rule 4's reasons are `"proof." + error.reason` / `"recovery." + error.reason` verbatim.

## Rules (spec §3, D3)

1. **`observation_deadline`** — every publication action and activation unit: missing `observation_deadline_ms` → reason `observation_deadline_optional`; outside `[1, transaction_plan.MAX_CONVERGENCE_WINDOW_MS]` → `observation_deadline_out_of_bounds`. Pointer: the node (missing) or its `/observation_deadline_ms` member.
2. **`rolled_back_reachable`** — when any recovery unit has `posture == "restorable"`, every node whose descriptor operation has `mutability == "create_if_absent"` must have posture `compensatable` and only `compensate` edges each with a non-empty string `residue`; otherwise reason `rolled_back_unreachable`, pointer `/recovery/units/<id>`.
3. **`restore_anchor`** — a `restorable` unit whose `anchor.target` equals the `target` of any node whose operation has `mutability == "in_place"` → reason `restore_anchor_destroyed`, pointer `/recovery/units/<id>/anchor/target`.
4. **`core_plans`** — `proof_decl, recovery_decl = lower(...)`; run `compile_recovery(recovery_decl, where=…)`, then `compile_proof(proof_decl, where=…)`, then (both compiled) `bind_recovery`. A `ProofPlanRejected` is one finding, reason `proof.<reason>`, pointer `/release/profiles/<id>/proof`; a `RecoveryPlanRejected` is reason `recovery.<reason>`, pointer `…/recovery`; `detail` is the exception's message.

## Lowering (`lower`, D23)

- Nodes: publication actions in `ordered_nodes` order, then activation units likewise (`activation == "none"` contributes none). `ordered_nodes` is Kahn's algorithm that always takes the earliest-authored ready node.
- Normalized target for handle `h`: `{"handle": h, "kind": t["kind"], **{m: t[m] for m in descriptor.target_kinds[kind]}}`.
- Proof unit: `{"name": id, "parameters": {"action": id, "operation": op, "target": <normalized>}, "phase": "publication" | "activation", "collector": <alias>}`.
- `collectors[alias] = {"basis": "deterministic", "predicates": sorted(p for p, v in descriptor["predicates"].items() if v["support"] == "supported"), **descriptor["collector"]}`.
- `obligations` = authored obligations, deep-copied unchanged; `convergence_window_ms` = `proof.convergence_window_ms`.
- Recovery unit: `{"name": id, "parameters": <same as the proof unit>, "effect": <alias>, "operation": op, "posture", "anchor", "compatibility", "edges"}`; a profile anchor `{target, predicate, parameters}` lowers to `{"predicate": predicate, "parameters": {**parameters, "target": <normalized target of anchor.target>}}`; compatibility and edges pass through.
- `effects[alias] = {"operations": sorted(op for op, e in descriptor operations if e["support"] == "supported" or e["recovery_capable"])}`.

## `ResolvedReleaseProfile` members (spec §3)

The test's thirteen keys: `adapters` = `adapter_identities` (alias → `{adapter, adapter_contract_version, descriptor_digest}`), `publication`/`activation` ordered node tuples, `deadlines` id → ms, `candidate_members` id → the operation's tuple; the rest as named. `digest = telemetry_digest({"profile": profile, "adapters": adapter_identities(profile)})` (D23).

## `bind_candidate` (D5)

- `compiled` not a `ResolvedReleaseProfile` → `TypeError` (D20). `candidate` must be exactly `{version, commit, title, notes}`: `version` matches `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`, `commit` matches `^[0-9a-f]{40}$`, `title` a non-empty string free of `"`, `$`, `` ` ``, `\`, NUL, CR, LF; `notes` a string — else `ValueError`.
- Every proof and recovery unit's `parameters` gains `"candidate": {"version", "commit"}` and `"config": <the node's config>`, plus each member named in that node's `candidate_members` (forge `release`: `notes`, `title`). Proof and recovery units stay identical so `bind_recovery` pairs them.
- Returns `{"proof", "recovery", "concurrency_keys": list(target.concurrency_keys), "subject": {"profile_id", "profile_version", "profile_digest", "candidate": {"version", "commit"}}}`.

- [ ] **Step 1: Extend `tests/release_test_support.py`**

Add `CANDIDATE = {"version": "v1.2.3", "commit": "1" * 40, "title": "v1.2.3 — release", "notes": "notes body"}` and three builders returning fresh copies (Task 1 already loads `destroyed_anchor_profile()`): `derived_class_profile()` (forge profile + obligation `{"id": "visible", "semantic": "published_artifact_identity", "form": "event", "predicate": "release_visible", "collector": "forge", "required": True, "deps": [], "parameters": {}}`), `missing_deadline_profile()` (forge profile without `tag`'s `observation_deadline_ms`), `unreachable_rollback_profile()` (restorable profile with `publish-artifact` recovery `{"posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}`).

- [ ] **Step 2: Write the failing test `tests/test_release_profile.py`**

```python
"""Release profile compiler (#124 AC1). Run: just agent-workflow-tests"""
import copy
import tempfile
import unittest
from pathlib import Path

from agent_tools import release_profile
from agent_tools.transaction_core import TransactionStore
from . import release_test_support as support

D = support.descriptors

def compile_(profile_id, profile):
    return release_profile.compile_profile(profile_id, profile, support.base_contract(), D())

def tree(root):
    """Every path under the store root: create must add none (D20)."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))

def reasons(error):
    return [f["reason"] for f in error.findings]

class AcceptanceOneTest(unittest.TestCase):
    def test_accepts_the_forge_and_the_restorable_profile(self):
        forge = compile_("github-release", support.forge_profile())
        self.assertEqual(forge["schema"], "release-profile/v1")
        self.assertEqual([n["id"] for n in forge["publication"]], ["tag", "github-release"])
        self.assertEqual(dict(forge["deadlines"]), {"tag": 600000, "github-release": 600000})
        restorable = compile_("restorable", support.restorable_profile())
        self.assertEqual([n["id"] for n in restorable["publication"]],
                         ["publish-artifact", "promote-pointer"])

    def test_rejects_the_three_issue_cases(self):
        cases = (("github-release", support.derived_class_profile(), "proof.derived_class_named"),
                 ("github-release", support.missing_deadline_profile(), "observation_deadline_optional"),
                 ("restorable", support.unreachable_rollback_profile(), "rolled_back_unreachable"))
        for profile_id, profile, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(release_profile.ProfileInadmissible) as caught:
                    compile_(profile_id, profile)
                self.assertIn(reason, reasons(caught.exception))
                for finding in caught.exception.findings:
                    self.assertEqual(sorted(finding), ["detail", "pointer", "reason", "rule"])

    def test_nothing_reaches_the_store(self):
        """D20: the pipeline compile -> bind -> create raises with an empty store root."""
        cases = (("github-release", support.derived_class_profile()),
                 ("github-release", support.missing_deadline_profile()),
                 ("restorable", support.unreachable_rollback_profile()))
        for profile_id, profile in cases:
            with self.subTest(profile_id=profile_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                store = TransactionStore(root)
                before = tree(root)
                with self.assertRaises(release_profile.ProfileInadmissible):
                    inputs = release_profile.bind_candidate(compile_(profile_id, profile), support.CANDIDATE)
                    store.create("k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                                 proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")
                self.assertEqual(tree(root), before)

class RulesTest(unittest.TestCase):
    def test_every_finding_is_reported(self):
        profile = support.missing_deadline_profile()
        del profile["publication"]["actions"][1]["observation_deadline_ms"]
        with self.assertRaises(release_profile.ProfileInadmissible) as caught:
            compile_("github-release", profile)
        self.assertEqual([f["pointer"] for f in caught.exception.findings],
                         ["/release/profiles/github-release/publication/actions/0",
                          "/release/profiles/github-release/publication/actions/1"])

    def test_out_of_bounds_and_destroyed_anchor(self):
        profile = support.forge_profile()
        profile["publication"]["actions"][0]["observation_deadline_ms"] = 7_200_001
        self.assertEqual([f["reason"] for f in release_profile.rule_findings(
            "observation_deadline", "github-release", profile, support.base_contract(), D())],
            ["observation_deadline_out_of_bounds"])
        found = release_profile.rule_findings("restore_anchor", "restorable",
                                              support.destroyed_anchor_profile(),
                                              support.base_contract(), D())
        self.assertEqual([(f["reason"], f["pointer"]) for f in found],
                         [("restore_anchor_destroyed",
                           "/release/profiles/restorable/recovery/units/promote-pointer/anchor/target")])

class FrozenAndBoundTest(unittest.TestCase):
    def test_compiled_profile_is_frozen_deterministic_and_detached(self):
        profile = support.forge_profile()
        first = compile_("github-release", profile)
        self.assertEqual(first["digest"], compile_("github-release", support.forge_profile())["digest"])
        profile["publication"]["actions"][0]["id"] = "changed"
        self.assertEqual(first["publication"][0]["id"], "tag")
        with self.assertRaises(TypeError):
            first["target"]["environment"] = "x"
        self.assertEqual(set(first), {"schema", "profile_id", "profile_version", "digest", "target",
                                      "adapters", "publication", "activation", "deadlines",
                                      "proof_declaration", "recovery_declaration", "limits",
                                      "candidate_members"})

    def test_bind_candidate_is_exactly_the_create_input(self):
        compiled = compile_("github-release", support.forge_profile())
        inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        self.assertEqual(sorted(inputs), ["concurrency_keys", "proof", "recovery", "subject"])
        self.assertEqual(inputs["subject"], {
            "profile_id": "github-release", "profile_version": 1, "profile_digest": compiled["digest"],
            "candidate": {"version": "v1.2.3", "commit": "1" * 40}})
        tag, release = inputs["proof"]["units"]
        self.assertNotIn("title", tag["parameters"])
        self.assertEqual((release["parameters"]["title"], release["parameters"]["notes"]),
                         ("v1.2.3 — release", "notes body"))
        self.assertEqual(release["parameters"]["target"], {
            "handle": "repository", "kind": "github_repository",
            "branch": "main", "repository": "fagenorn/nix-config"})
        with tempfile.TemporaryDirectory() as tmp:
            TransactionStore(Path(tmp).resolve()).create(
                "k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")

    def test_bind_candidate_refuses_bad_input(self):
        compiled = compile_("github-release", support.forge_profile())
        with self.assertRaises(TypeError):
            release_profile.bind_candidate(release_profile.thaw(compiled), support.CANDIDATE)
        for bad in ({"version": "1.2.3"}, {"commit": "abc"}, {"title": 'a "quoted" title'},
                    {"extra": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    release_profile.bind_candidate(compiled, {**support.CANDIDATE, **bad})

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py`
Expected: ERROR — `AttributeError: module 'agent_tools.release_profile' has no attribute 'compile_profile'` (and `support` lacks `CANDIDATE`).

- [ ] **Step 4: Implement** the rules, lowering, freezing, digest and binding above in `release_profile.py`. `TransactionStore(root)` requires an absolute existing directory; `create(creation_key, subject, *, concurrency_keys, proof, recovery, authority_class)` compiles before any lock, so the tree under the root is unchanged by a refused create.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py tests/test_release_grammar.py`
Expected: PASS, 19 tests.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/release_profile.py tests/release_test_support.py tests/test_release_profile.py justfile
git commit -m "feat(release): admissibility compiler and candidate binding (#124)"
```
