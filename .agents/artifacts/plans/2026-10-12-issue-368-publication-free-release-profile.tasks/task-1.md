# Task 1: Readers below the grammar — `phase_nodes`, `release_targets`, `capabilities.release`, the `release` member

Spec sections 1 (last paragraph), 3 and 4 (per D4, D5, D6, D10, D14). This task builds everything that reads a profile after the grammar, and the snapshot's new `release.targets` member, while the grammar still refuses `"publication": "none"`. No contract that resolves at base resolves differently except for gaining the `release` member; the publication-free branches are exercised by calling the functions directly on the fixture profile (D14). Task 2 then opens the grammar.

**Files:**
- Create: `tests/fixtures/release/publication-free-profile.json`
- Modify: `python/agent_tools/release_profile.py` (`phase_nodes`, its readers, `release_targets`)
- Modify: `python/agent_tools/resolve_project.py` (`release_capability`, `build_snapshot`)
- Modify: `tests/release_test_support.py` (one builder)
- Test: `tests/test_release_profile.py` (additions only), `home/common/agent-skills/tests/test_resolve_project.py`, `home/common/agent-skills/tests/test_resolve_platform.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `release_profile.PHASES: tuple[str, str]` = `("publication", "activation")`.
  - `release_profile.phase_nodes(profile: Mapping[str, Any], phase: str) -> list[dict[str, Any]]` — a new list of the authored publication actions (`phase == "publication"`) or activation units (`phase == "activation"`) in authored order; `[]` when the phase's value is `"none"`.
  - `release_profile.release_targets(release: object, descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS) -> list[dict[str, Any]]`.
  - Snapshot member `release`: `{"targets": [{"profile": <profile id>, "adapter": <registered adapter name>, "target": <normalized target>, "operations": [<operation>, ...]}, ...]}`.
  - `tests/release_test_support.publication_free_profile() -> dict`, and in the resolver suite a module-level `publication_free_profile()` plus `ReleaseMemberTest.declaring`, `snapshot`, `UNSUPPORTED`, `REPOSITORY`.
  - The fixture profile id every suite of this plan uses: `forge-target`.

**Invariants:**
- `grammar_violations` is not edited by this task: `"publication": "none"` is still `contract.release.invalid` at this task's commit, so no resolvable contract reaches a publication-free branch.
- For every profile that is grammar-valid at base, `admissibility_findings`, `lower`, `compile_profile`, `profile_digest` and `bind_candidate` return what they returned at base.
- `release_targets` is pure (no file, clock, network, environment) and returns plain new values: `[]` for `"unsupported"`; otherwise one entry per `bindings.targets` handle of every profile, ordered by profile id then handle (both `sorted`, whatever the authored order). `adapter` is `bindings.adapters[<the target's alias>]["adapter"]`. `operations` is the sorted, duplicate-free list of `operation` values of the publication actions and activation units whose `target` is that handle, and of no other handle; `[]` when none.
- It reads the authored profile only, never admissibility: an inadmissible profile's targets are listed.
- `release_capability` returns `{"state": "unsupported", "reason_code": None, "repair_id": None}` when `release == "unsupported"` or when no profile has a publication node; that check comes before admissibility and before any executable lookup. Otherwise the existing logic runs unchanged over all profiles.
- The snapshot's `schema_version`, `project`, `bindings` and `capabilities` are built exactly as at base; `release` is added last and is present for every resolved project. A refused contract prints only `{"error": ...}` (R6).
- `python/agent_tools/release.py` is not edited by this task.

- [ ] **Step 1: Create the fixture and its builders**

`tests/fixtures/release/publication-free-profile.json` is `tests/fixtures/release/github-release-profile.json` with exactly two members changed: `"publication": "none"` and `"recovery": {"units": {}}`. Everything else (`profile_version` 1, `target`, `requirements`, the four `bindings` groups with the `repository` target `fagenorn/nix-config` on `main`, `"activation": "none"`, `proof` with `convergence_window_ms` 1800000 and `"obligations": []`, `"limits": {}`) is copied byte for byte, 2-space indented with a trailing newline like its sibling.

In `tests/release_test_support.py`, beside `forge_profile`:

```python
def publication_free_profile() -> dict:
    return _load("publication-free-profile.json")
```

In `home/common/agent-skills/tests/test_resolve_project.py`, beside the module-level `forge_profile`:

```python
def publication_free_profile() -> dict:
    return json.loads(
        (RELEASE_FIXTURES / "publication-free-profile.json").read_text("utf-8"))
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_release_profile.py`, above the `if __name__` line (the module already defines `D` and imports `support`):

```python
class PublicationFreeReadersTest(unittest.TestCase):
    """The readers below the grammar over a profile whose publication is `"none"` (#368 D3, D6, D14)."""

    def test_phase_nodes_is_empty_for_none_and_authored_order_otherwise(self):
        free, forge = support.publication_free_profile(), support.forge_profile()
        self.assertEqual(release_profile.PHASES, ("publication", "activation"))
        self.assertEqual([release_profile.phase_nodes(free, phase)
                          for phase in release_profile.PHASES], [[], []])
        self.assertEqual([n["id"] for n in release_profile.phase_nodes(forge, "publication")],
                         ["tag", "github-release"])
        self.assertEqual(release_profile.phase_nodes(forge, "activation"), [])
        self.assertIsNot(release_profile.phase_nodes(forge, "publication"),
                         forge["publication"]["actions"])

    def test_the_four_rules_find_nothing_and_lowering_has_no_unit(self):
        profile = support.publication_free_profile()
        self.assertEqual(release_profile.admissibility_findings(
            "forge-target", profile, support.base_contract(), D()), [])
        proof, recovery = release_profile.lower("forge-target", profile, D())
        self.assertEqual((proof["units"], proof["obligations"], recovery["units"]), ([], [], []))

    def test_release_targets_orders_entries_and_scopes_operations_to_their_handle(self):
        repository = {"adapter": "forge", "kind": "github_repository",
                      "repository": "fagenorn/nix-config", "branch": "main"}
        publishing = support.forge_profile()
        publishing["bindings"]["targets"] = {"zeta": dict(repository),
                                             "repository": dict(repository),
                                             "alpha": dict(repository)}
        tag, release = publishing["publication"]["actions"]
        release["target"] = "alpha"
        publishing["publication"]["actions"].append(dict(tag, id="tag-again", deps=["tag"]))
        publishing["recovery"]["units"]["tag-again"] = dict(publishing["recovery"]["units"]["tag"])
        authored = {"profiles": {"zulu": publishing,
                                 "alpha": support.publication_free_profile()}}
        self.assertEqual(release_profile.grammar_violations(
            {"profiles": {"zulu": publishing}}, support.base_contract(), D()), [])

        def entry(profile, handle, operations):
            return {"profile": profile, "adapter": "github-forge", "operations": operations,
                    "target": {"handle": handle, "kind": "github_repository",
                               "repository": "fagenorn/nix-config", "branch": "main"}}
        self.assertEqual(release_profile.release_targets(authored, D()), [
            entry("alpha", "repository", []),
            entry("zulu", "alpha", ["release"]),
            entry("zulu", "repository", ["tag"]),
            entry("zulu", "zeta", [])])
        self.assertEqual(release_profile.release_targets("unsupported", D()), [])

```

Append these members to the existing class `ReleaseMemberTest` in the resolver suite, after `test_grammar_and_deploy_conflict_are_contract_errors` (the class already defines `STUBS` and `profiles`; the module defines `source_contract`, `run_with_path`, `make_stub_bin` and imports `resolve_project` and `Path`):

```python
    # Issue 368: a forge target without a publication, and the `release.targets` member.

    UNSUPPORTED = {"state": "unsupported", "reason_code": None, "repair_id": None}
    REPOSITORY = {"handle": "repository", "kind": "github_repository",
                  "repository": "fagenorn/nix-config", "branch": "main"}

    def declaring(self, **profiles):
        contract = source_contract()
        contract["release"] = {"profiles": {name.replace("_", "-"): profile
                                            for name, profile in profiles.items()}}
        return contract

    def snapshot(self, contract, stubs=STUBS):
        code, out, err = run_with_path(str(make_stub_bin(stubs)), "resolve", "--repo-root",
                                       str(self.make_root(contract)), home=self.home)
        self.assertEqual(code, 0, err or out)
        return json.loads(out)

    def test_a_publishing_profile_lists_its_target_with_its_operations(self):
        snap = self.snapshot(self.profiles())
        self.assertEqual(snap["release"], {"targets": [{
            "profile": "github-release", "adapter": "github-forge",
            "target": self.REPOSITORY, "operations": ["release", "tag"]}]})
        self.assertEqual(snap["capabilities"]["release"]["state"], "available")

    def test_unsupported_release_lists_no_target(self):
        contract = source_contract()
        contract["release"] = "unsupported"
        self.assertEqual(self.snapshot(contract)["release"], {"targets": []})

    def test_targets_are_sorted_and_operations_belong_to_their_handle(self):
        repository = {"adapter": "forge", "kind": "github_repository",
                      "repository": "fagenorn/nix-config", "branch": "main"}
        profile = forge_profile()
        profile["bindings"]["targets"] = {"zeta": dict(repository), "repository": dict(repository),
                                          "alpha": dict(repository)}
        tag, release = profile["publication"]["actions"]
        release["target"] = "alpha"
        profile["publication"]["actions"].append(dict(tag, id="tag-again", deps=["tag"]))
        profile["recovery"]["units"]["tag-again"] = dict(profile["recovery"]["units"]["tag"])
        snap = self.snapshot(self.declaring(zulu=profile))
        self.assertEqual(snap["release"], {"targets": [
            {"profile": "zulu", "adapter": "github-forge", "operations": operations,
             "target": dict(self.REPOSITORY, handle=handle)}
            for handle, operations in (("alpha", ["release"]), ("repository", ["tag"]),
                                       ("zeta", []))]})
        self.assertEqual(snap["capabilities"]["release"]["state"], "available")

    def test_release_capability_is_unsupported_when_no_profile_publishes(self):
        release = {"profiles": {"forge-target": publication_free_profile()}}
        self.assertEqual(
            resolve_project.release_capability(release, source_contract(), Path("/nonexistent")),
            self.UNSUPPORTED)

    def test_an_inadmissible_profile_still_lists_its_target(self):
        profile = forge_profile()
        del profile["publication"]["actions"][0]["observation_deadline_ms"]
        snap = self.snapshot(self.profiles(profile))
        self.assertEqual(snap["capabilities"]["release"]["reason_code"],
                         "release_profile_inadmissible")
        self.assertEqual(snap["release"]["targets"][0]["operations"], ["release", "tag"])
```

Three existing pins of the snapshot's member set move from four members to five (D10); these are edits to existing lines, in the resolver suites only:

1. `test_resolve_project.py`, `SnapshotShapeTest.test_resolve_returns_exactly_four_top_level_members`: rename to `test_resolve_returns_exactly_five_top_level_members`, expect `sorted(snap) == ["bindings", "capabilities", "project", "release", "schema_version"]`, and add `self.assertEqual(sorted(snap["release"]), ["targets"])`.
2. `test_resolve_project.py`, `WorkflowRefusalFixtureTest.SNAPSHOT_MEMBERS`: add `"release"` to the tuple, so every refusal that class drives is also asserted to print no `release` member.
3. `home/common/agent-skills/tests/test_resolve_platform.py`, `test_a_supported_non_current_schema_resolves`: expect the same five-name list, and reword its docstring's "still four members" to five.

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py -k PublicationFreeReaders -k ReleaseMemberTest -k five_top_level -k non_current_schema`
Expected: FAIL — `release_profile` has no `PHASES`, `phase_nodes` or `release_targets`; `admissibility_findings` raises `TypeError` indexing the string `"none"`; the snapshot tests raise `KeyError: 'release'`; `release_capability` raises `TypeError` for the fixture; the two key-set pins report the missing `release` name. The five tests `ReleaseMemberTest` had at base pass.

- [ ] **Step 4: Implement**

`python/agent_tools/release_profile.py`, below the grammar classes:

- `PHASES = ("publication", "activation")` beside the other module constants, plus one private mapping from phase to its list member (`publication` → `actions`, `activation` → `units`).
- `phase_nodes` returns `[]` when `profile[phase] == "none"`, else `list(profile[phase][<list member>])`.
- Route every post-grammar reader in this module through it and delete their own `"none"` checks and `["actions"]`/`["units"]` indexing: `_authored` yields `(phase, index, node)` for each phase in `PHASES` order; `lower` uses `ordered_nodes(phase_nodes(profile, <phase>))` for both phases; `compile_profile` builds `nodes[phase] = ordered_nodes(phase_nodes(profile, phase))`. `_rule_observation_deadline` keeps deriving its pointer segment from the phase and may read the private mapping. No admissibility rule is skipped or added.
- `release_targets`, beside `_normalized_target`, built from `_authored` (each profile's nodes) and `_normalized_target` (the `target` member), meeting the invariants above. Its docstring states the entry shape and ordering from the code.
- Module docstring: add, from the code, that `phase_nodes` is the one post-grammar reader of a phase's authored nodes and that `release_targets` lists the bound targets.

`python/agent_tools/resolve_project.py`:

- `release_capability`: after the `"unsupported"` return, return the same unsupported entry when no profile in `release["profiles"]` has a publication node, using `release_profile.phase_nodes`; leave the rest as it is. Rewrite its docstring's summary of the states from the code.
- `build_snapshot`: add `"release": {"targets": release_profile.release_targets(source["release"])}` as the fifth member. `compute_capabilities` and `conformance_checks` are not edited.
- Module docstring: add one sentence on the derived `release.targets` member, written from the code.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_bridge.py tests/test_release_command.py tests/test_release_adapter_core.py home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py home/common/agent-skills/tests/test_conformance_checks.py`
Expected: PASS, 0 failures, 0 errors, every test that existed at base included.

Run:

```bash
git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'
git diff --quiet 40fa1f82c5a5 -- python/agent_tools/release.py
if grep -nE '\["(publication|activation)"\]\["(actions|units)"\]|!= "none"' python/agent_tools/release_profile.py; then exit 1; fi
if ! env PYTHONPATH="$PWD/python" python3 -c 'import json, sys; from agent_tools import release_profile as r; from tests import release_test_support as s; sys.exit(0 if r.grammar_violations(s.release_of("forge-target", s.publication_free_profile()), s.base_contract(), s.descriptors()) else 1)'; then exit 1; fi
```

Expected: every numstat row has `0` in its second column; `git diff --quiet` exits 0; the `grep` prints nothing; the last line exits 0 because the grammar still refuses the fixture (the half-wired state D14 forbids would make it exit 1). Also run the never-edited gate of Global Constraints.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/release_profile.py python/agent_tools/resolve_project.py \
  tests/fixtures/release/publication-free-profile.json tests/release_test_support.py \
  tests/test_release_profile.py home/common/agent-skills/tests/test_resolve_project.py \
  home/common/agent-skills/tests/test_resolve_platform.py
```

Commit through `launch-commit` with the message `feat(resolve-project): expose release.targets and read phases through phase_nodes (#368)`.
