# Task 3: Resolver — `capabilities.release` and the `release.targets` member

Spec sections 3 and 4 (per D4, D5, D6, D9, D10). `resolve-project resolve` reports no release capability when no profile publishes, and its snapshot gains a fifth, always-present member `release` listing every bound target with the operations its profile declares on it.

**Files:**
- Modify: `python/agent_tools/release_profile.py` (new pure function `release_targets`)
- Modify: `python/agent_tools/resolve_project.py` (`release_capability`, `build_snapshot`)
- Test: `home/common/agent-skills/tests/test_resolve_project.py`, `home/common/agent-skills/tests/test_resolve_platform.py`

**Interfaces:**
- Consumes (Task 1): `release_profile.phase_nodes(profile, phase) -> list[dict]` (`[]` for a `"none"` phase); the private `_authored(profile)` and `_normalized_target(profile, descriptors, handle) -> {"handle", "kind", <kind members>}` already in `release_profile`; the fixture `tests/fixtures/release/publication-free-profile.json` (one `github_repository` target `repository` for `fagenorn/nix-config` on `main`, bound to adapter alias `forge` = `github-forge`).
- Produces:
  - `release_profile.release_targets(release: object, descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS) -> list[dict[str, Any]]` over a grammar-valid authored `release`.
  - Snapshot member `release`: `{"targets": [{"profile": <profile id>, "adapter": <registered adapter name>, "target": <normalized target>, "operations": [<operation>, ...]}, ...]}`.

**Invariants:**
- `release_targets` is pure (no file, clock, network, environment) and returns plain new values: `[]` for `"unsupported"`; otherwise one entry per `bindings.targets` handle of every profile, ordered by profile id then handle (both `sorted`). `adapter` is `bindings.adapters[<the target's alias>]["adapter"]`. `operations` is the sorted, duplicate-free list of `operation` values of the publication actions and activation units whose `target` is that handle; `[]` when none.
- It reads the grammar-valid authored profile only, never admissibility: an inadmissible profile's targets are listed.
- `release_capability` returns `{"state": "unsupported", "reason_code": None, "repair_id": None}` when `release == "unsupported"` or when no profile has a publication node (`phase_nodes(profile, "publication")` empty for all); that check comes before admissibility and before any executable lookup. Otherwise the existing logic runs unchanged over all profiles, publication-free ones included.
- The snapshot's `schema_version`, `project`, `bindings` and `capabilities` are built exactly as at base for any contract that was valid at base; `release` is added last and is present for every resolved project.
- A refused contract prints only `{"error": ...}`: no `release` member (R6).
- `CAPABILITY_STATES`, `REASON_CODES` and `resolved_schema_version` are unchanged.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_resolve_project.py`, beside the module-level `forge_profile`:

```python
def publication_free_profile() -> dict:
    return json.loads(
        (RELEASE_FIXTURES / "publication-free-profile.json").read_text("utf-8"))
```

Append these members to the existing class `ReleaseMemberTest` (after `test_grammar_and_deploy_conflict_are_contract_errors`; the class already defines `STUBS` and `profiles`, and the module defines `source_contract`, `run_with_path`, `make_stub_bin`):

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

    def test_one_publishing_profile_beside_a_publication_free_one_is_available(self):
        free = publication_free_profile()
        free["target"]["concurrency_keys"] = ["release/fagenorn/nix-config/target-only"]
        snap = self.snapshot(self.declaring(forge_target=free, github_release=forge_profile()))
        self.assertEqual(snap["capabilities"]["release"]["state"], "available")
        self.assertEqual([(t["profile"], t["operations"]) for t in snap["release"]["targets"]],
                         [("forge-target", []), ("github-release", ["release", "tag"])])

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

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py -k ReleaseMemberTest -k five_top_level -k non_current_schema`
Expected: FAIL — `KeyError: 'release'` in the target tests, `available` (and, without the adapter stubs, `blocked`) where `unsupported` is expected, and the two key-set pins report the missing `release` name. `test_a_publication_free_target_for_another_repository_is_refused` and the five tests `ReleaseMemberTest` had at base pass already.

- [ ] **Step 3: Implement**

`python/agent_tools/release_profile.py`, beside `_normalized_target`:

```python
def release_targets(release: object,
                    descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                    ) -> list[dict[str, Any]]:
```

built from `_authored` (for each profile's nodes) and `_normalized_target` (for `target`), meeting the invariants above. Its docstring states the entry shape and ordering from the code.

`python/agent_tools/resolve_project.py`:

- `release_capability`: after the `"unsupported"` return, return the same unsupported entry when no profile in `release["profiles"]` has a publication node, using `release_profile.phase_nodes`; leave the rest of the function as it is. Rewrite its docstring's summary of the states from the code.
- `build_snapshot`: add `"release": {"targets": release_profile.release_targets(source["release"])}` as the fifth member. Nothing else in the snapshot changes; `compute_capabilities` and `conformance_checks` (which calls `compute_capabilities` itself) are not edited.
- Module docstring: where it describes the printed snapshot, add the `release.targets` member, written from the code.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_resolve_platform.py`
Expected: PASS, 0 failures, 0 errors (about 190 tests, under a minute).

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_command.py home/common/agent-skills/tests/test_conformance_checks.py`
Expected: PASS — the inspection command resolves through `resolve()` and conformance through `compute_capabilities`; neither may notice the new member.

Run the never-edited gate of Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_profile.py python/agent_tools/resolve_project.py \
  home/common/agent-skills/tests/test_resolve_project.py \
  home/common/agent-skills/tests/test_resolve_platform.py
```

Commit through `launch-commit` with the message `feat(resolve-project): expose release.targets and report no capability without a publication (#368)`.
