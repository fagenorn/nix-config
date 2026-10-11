# Task 1: Grammar form `"publication": "none"`, `phase_nodes`, the fixture

Spec sections 1 and 2 (per D1, D2, D3, D11). After this task a profile may say `"publication": "none"`; the grammar judges it, the four admissibility rules find nothing, and `compile_profile` returns an empty graph.

**Files:**
- Create: `tests/fixtures/release/publication-free-profile.json`
- Modify: `python/agent_tools/release_profile.py`
- Modify: `tests/release_test_support.py` (one builder)
- Test: `tests/test_release_grammar.py`, `tests/test_release_profile.py` (additions only)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `release_profile.PHASES: tuple[str, str]` = `("publication", "activation")`.
  - `release_profile.phase_nodes(profile: Mapping[str, Any], phase: str) -> list[dict[str, Any]]` — for a grammar-valid profile, a new list of the authored publication actions (`phase == "publication"`) or activation units (`phase == "activation"`) in authored order; `[]` when the phase's value is `"none"`.
  - `tests/release_test_support.publication_free_profile() -> dict` — a fresh copy of the fixture.
  - The fixture profile id used by every suite of this plan: `forge-target`.

**Invariants:**
- `grammar_violations` still never raises on any JSON value and still reports each malformed input once.
- For every profile that was grammar-valid at base, `grammar_violations`, `admissibility_findings`, `lower`, `compile_profile` and `profile_digest` return what they returned at base (the existing suites pin this).
- `{"actions": []}`, an omitted `publication` and any value other than `"none"` or an object stay `contract.release.invalid`.
- The same-repository rule is not edited: it reads `bindings.targets` only.

- [ ] **Step 1: Create the fixture and its builder**

`tests/fixtures/release/publication-free-profile.json` is `tests/fixtures/release/github-release-profile.json` with exactly two members changed: `"publication": "none"` and `"recovery": {"units": {}}`. Everything else (`profile_version` 1, `target`, `requirements`, the four `bindings` groups with the `repository` target `fagenorn/nix-config` on `main`, `"activation": "none"`, `proof` with `convergence_window_ms` 1800000 and `"obligations": []`, `"limits": {}`) is copied byte for byte, 2-space indented with a trailing newline like its sibling.

In `tests/release_test_support.py`, beside `forge_profile`:

```python
def publication_free_profile() -> dict:
    return _load("publication-free-profile.json")
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_release_grammar.py`, above the `if __name__` line:

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

    def test_each_publication_free_rule(self):
        action = support.forge_profile()["publication"]["actions"][0]
        obligation = {"id": "o", "semantic": "liveness", "form": "event", "predicate": "p",
                      "collector": "forge", "required": True, "deps": [], "parameters": {}}
        unit = {"posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}
        cases = [
            (lambda p, c: p.update(activation={"units": [action]}), "invalid", "/activation"),
            (lambda p, c: p["proof"]["obligations"].append(obligation), "invalid",
             "/proof/obligations"),
            (lambda p, c: p["recovery"]["units"].update(tag=unit), "reference_unknown",
             "/recovery/units/tag"),
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
                self.assertIn(("contract.release." + repair, self.BASE + pointer),
                              [(v["repair_id"], v["pointer"]) for v in self.found(mutate)])

    def test_any_other_publication_value_names_the_two_forms(self):
        for value in ("None", "unsupported", "", None, [], 0):
            with self.subTest(value=value):
                self.assertIn(
                    {"pointer": self.BASE + "/publication", "repair_id": "contract.release.invalid",
                     "message": 'publication must be "none" or {actions}'},
                    self.found(lambda p, c: p.update(publication=value)))

```

Append to `tests/test_release_profile.py`, above the `if __name__` line:

```python
class PublicationFreeTest(unittest.TestCase):
    """A publication-free profile compiles to an empty graph and is never bound (#368 D3)."""

    def test_the_four_rules_find_nothing(self):
        self.assertEqual(release_profile.admissibility_findings(
            "forge-target", support.publication_free_profile(), support.base_contract(), D()), [])

    def test_phase_nodes_is_empty_for_none_and_authored_order_otherwise(self):
        free, forge = support.publication_free_profile(), support.forge_profile()
        self.assertEqual(release_profile.PHASES, ("publication", "activation"))
        self.assertEqual([release_profile.phase_nodes(free, phase)
                          for phase in release_profile.PHASES], [[], []])
        self.assertEqual([n["id"] for n in release_profile.phase_nodes(forge, "publication")],
                         ["tag", "github-release"])
        self.assertEqual(release_profile.phase_nodes(forge, "activation"), [])

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

```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py -k PublicationFree`
Expected: FAIL — the fixture's `publication` is reported as `publication must be an object`, `release_profile` has no `PHASES`, and `admissibility_findings` raises `TypeError` indexing the string `"none"`.

- [ ] **Step 4: Implement in `python/agent_tools/release_profile.py`**

Grammar (`_Profile`):

- `_Profile` records whether its profile is publication-free (an attribute set in `phases`, `False` until then).
- `phases`, the `publication` branch, in this order: the value `"none"` marks the profile publication-free and adds no violation; any other non-object adds one violation at `<base>/publication`, message exactly `publication must be "none" or {actions}`, suffix `invalid`; an object keeps today's `closed(..., {"actions"}, ...)` and `node_list` path unchanged (so `{"actions": []}` keeps `actions must be a non-empty list` at `<base>/publication/actions`).
- `phases`, the `activation` branch: `"none"` returns as today. Otherwise, when the profile is publication-free, add exactly one violation at `<base>/activation`, message exactly `activation must be "none" when publication is "none"`, suffix `invalid`, and judge that activation no further (its units are not registered as nodes). When it is not publication-free the branch is unchanged.
- `proof`: after the existing "obligations must be a list" check, when the profile is publication-free and the list is non-empty, add one violation at `<base>/proof/obligations`, message exactly `obligations must be [] when publication is "none"`, suffix `invalid`; each obligation's own shape is still judged as today.
- `recovery` is not edited: with no declared node, its existing rule already reports each key as `contract.release.reference_unknown` at `<base>/recovery/units/<key>` (D11).
- `run` already calls `phases` before `proof` and `recovery`; keep that order, the two later rules depend on it.

Accessor and its readers (below the grammar):

```python
PHASES = ("publication", "activation")
```

beside the other module constants, plus one private mapping from phase to its list member (`publication` → `actions`, `activation` → `units`).

```python
def phase_nodes(profile: Mapping[str, Any], phase: str) -> list[dict[str, Any]]:
```

returns `[]` when `profile[phase] == "none"`, else `list(profile[phase][<list member>])`. Then route every reader in this module through it and delete their own `"none"` checks and `["actions"]`/`["units"]` indexing:

- `_authored`: `(phase, index, node)` for each phase in `PHASES` order, enumerating `phase_nodes`.
- `lower`: `publication` and `activation` are `ordered_nodes(phase_nodes(profile, <phase>))`.
- `compile_profile`: `nodes[phase] = ordered_nodes(phase_nodes(profile, phase))` for each phase.
- `_rule_observation_deadline` keeps deriving its pointer segment (`actions`/`units`) from the phase; it may read the new private mapping instead of its inline conditional.

No admissibility rule is skipped or added, and `compile_profile` gains no publication-free branch: the empty graph falls out of the readers above.

Module docstring: state, from the code as implemented, that `publication` has the two forms, the three rules a publication-free profile must meet and which existing rule covers recovery units, and that `phase_nodes` is the one reader of a phase's authored nodes.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_bridge.py`
Expected: PASS, 0 failures, 0 errors, including every test that existed at base.

Run:

```bash
git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'
if grep -nE '\["(publication|activation)"\]\["(actions|units)"\]|!= "none"' python/agent_tools/release_profile.py; then exit 1; fi
```

Expected: every numstat row has `0` in its second column; the `grep` prints nothing (the only `== "none"` comparisons left are in `_Profile.phases` and `phase_nodes`). Also run the never-edited gate of Global Constraints.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/release_profile.py tests/fixtures/release/publication-free-profile.json \
  tests/release_test_support.py tests/test_release_grammar.py tests/test_release_profile.py
```

Commit through `launch-commit` with the message `feat(release-profile): accept "publication": "none" (#368)`.
