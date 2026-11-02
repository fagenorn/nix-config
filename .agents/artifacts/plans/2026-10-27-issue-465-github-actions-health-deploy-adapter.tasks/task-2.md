# Task 2: The resolver and grammar accept a registered deploy adapter beside profiles

Spec § Where deploy watching lives, § Resolver acceptance and § Acceptance mapping (AC1); per D1, D3, D4, D9, D15. After this task, the issue's JarBird-shaped contract resolves with `capabilities.deploy` `available` when `gh` is on `PATH`, and `blocked`/`release_adapter_unavailable` when it is not. The resolver contract gains four repairs:

- `contract.deploy.adapter_unwatchable`;
- `contract.deploy.command_conflict`;
- `contract.deploy.config_invalid`;
- `contract.deploy.tracker_not_github`.

The grammar's `deploy_conflict` rule now lets a supported deploy coexist with profiles exactly when `bindings.deploy.adapter` is registered and no profile authors activation units. An unregistered adapter such as `railway` keeps today's rules.

**Files:**
- Modify: `python/agent_tools/resolve_project.py` (new `registered_deploy_adapter`, `validate_deploy`, `validate_bindings`, `validate_capability_bindings`, `first_unmet_prerequisite`, and the D6 comment above `CAPABILITY_BINDING_REQUIREMENTS`)
- Modify: `python/agent_tools/release_profile.py` (`_Grammar.release`, new `_Grammar.deploy_watch_coexists`, the module docstring)
- Test: `home/common/agent-skills/tests/test_resolve_project.py` (new `DeployWatchTest`)
- Test: `tests/test_release_grammar.py` (new `DeployWatchGrammarTest`, its import line)
- Modify: `python/README.md` (§ Release profiles)

**Interfaces:**
- Consumes (Task 1): `release_adapter.REGISTRY`, `DESCRIPTORS`, `watch_operation(descriptor) -> str | None`, `config_problems(schema, config) -> list[str]` with `string_list`, and `actions_health_adapter.describe()`.
- Produces:
  - `resolve_project.registered_deploy_adapter(deploy: object) -> str | None`. It returns the deploy binding's `adapter` when that is a `str` key of `release_adapter.REGISTRY`, and `None` for anything else, a non-dict included. Task 3 imports it.
  - `validate_deploy(deploy: dict, commands: dict | None, tracker: dict | None, violations: list[dict]) -> None`.
  - `_Grammar.deploy_watch_coexists(profiles: dict) -> bool`.

**Invariants:**
- An unregistered adapter other than `none` keeps today's rules: a free-form `config`, a `command` id checked against `commands`, the completeness row, and readiness through `command_missing`. `test_grammar_and_deploy_conflict_are_contract_errors` (railway, a command and profiles) and `test_a_supported_deploy_needs_an_adapter_and_a_command` stay green and are not edited.
- The registered-adapter rules judge shape, so they apply whatever the authored support is. For a registered adapter, a non-null `command` produces exactly one violation, `command_conflict`, and no `commands`-id check (D15).
- The grammar never raises: `bindings.deploy.adapter` is read through `isinstance` guards. Its condition reads only the adapter's registration, so `validate_deploy` reports an unwatchable registered adapter once (D4).
- `REASON_CODES`, `ERROR_CODES` and the snapshot's members are unchanged. `bindings.deploy` passes through `normalize_bindings` byte for byte (D1).
- `CommittedContractTest.test_nix_activate_is_exact_and_deploy_stays_unsupported` stays green: this repository's own deploy stays `none`/`unsupported`.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_resolve_project.py`, insert this class directly before `class ContradictionTest(ResolverTestCase):`:

```python
class DeployWatchTest(ResolverTestCase):
    """Issue 465: a registered deploy adapter beside a release profile (D1, D3, D4, D15)."""

    DEPLOY = {"adapter": "github-actions-health", "command": None,
              "config": {"workflow": "deploy.yml", "branch": "main",
                         "services": ["jarbird", "jarbird-caddy"],
                         "health_url": "https://jarbird.com/health",
                         "health_commit_field": "commit"}}

    def jarbird(self) -> dict:
        """This repository's contract reshaped as the issue's JarBird repro."""
        contract = source_contract()
        contract["release"] = {"profiles": {"forge-main": publication_free_profile()}}
        contract["bindings"]["deploy"] = copy.deepcopy(self.DEPLOY)
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = [
            "GITHUB_TOKEN", "GH_TOKEN"]
        contract["capabilities"]["deploy"]["support"] = "supported"
        return contract

    def snapshot(self, contract: dict, stubs: tuple[str, ...]) -> dict:
        code, out, err = run_with_path(str(make_stub_bin(stubs)), "resolve", "--repo-root",
                                       str(self.make_root(contract)), home=self.home)
        self.assertEqual(code, 0, err or out)
        return json.loads(out)

    def test_a_jarbird_shaped_project_watches_its_deploy(self):
        snap = self.snapshot(self.jarbird(), ("gh", "git", "just", "codex-companion"))
        self.assertEqual(snap["capabilities"]["deploy"],
                         {"state": "available", "reason_code": None, "repair_id": None})
        self.assertEqual(snap["bindings"]["deploy"], self.DEPLOY)
        self.assertEqual(snap["capabilities"]["release"]["state"], "unsupported")
        blocked = self.snapshot(self.jarbird(), ("git", "just", "codex-companion"))
        self.assertEqual(blocked["capabilities"]["deploy"], {
            "state": "blocked", "reason_code": "release_adapter_unavailable",
            "repair_id": "capability.deploy.release_adapter_unavailable"})

    def test_without_profiles_a_registered_adapter_is_available(self):
        contract = self.jarbird()
        contract["release"] = "unsupported"
        self.assertEqual(self.snapshot(contract, ("gh",))["capabilities"]["deploy"]["state"],
                         "available")

    def test_each_registered_adapter_rule_is_one_contract_error(self):
        def unwatchable(contract):
            contract["bindings"]["deploy"] = {"adapter": "github-forge", "command": None,
                                              "config": {}}

        def command(contract):
            contract["bindings"]["deploy"]["command"] = "nix-build"

        def config(contract):
            contract["bindings"]["deploy"]["config"].update(services="jarbird", region="eu")

        def gitlab(contract):
            contract["release"] = "unsupported"
            contract["bindings"]["tracker"]["kind"] = "gitlab"

        cases = (
            (unwatchable, "contract.deploy.adapter_unwatchable", ["/bindings/deploy/adapter"]),
            (command, "contract.deploy.command_conflict", ["/bindings/deploy/command"]),
            (config, "contract.deploy.config_invalid", ["/bindings/deploy/config"] * 2),
            (gitlab, "contract.deploy.tracker_not_github", ["/bindings/deploy/adapter"]),
        )
        for mutate, repair_id, pointers in cases:
            with self.subTest(repair_id=repair_id):
                contract = self.jarbird()
                mutate(contract)
                code, payload, _ = self.resolve(self.make_root(contract))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual(error["repair_id"], repair_id)
                self.assertEqual([v["pointer"] for v in error["violations"]], pointers)
                if repair_id == "contract.deploy.config_invalid":
                    self.assertEqual([v["message"] for v in error["violations"]], [
                        "config member 'region' is not declared",
                        "config member 'services' must be a string_list"])
```

In `tests/test_release_grammar.py`, change the import line to `from agent_tools import actions_health_adapter, forge_adapter, release_adapter, release_profile`. Then insert this class directly before `class PublicationFreeGrammarTest(unittest.TestCase):`:

```python
class DeployWatchGrammarTest(unittest.TestCase):
    """Issue 465 D4: profiles allow a supported deploy only through a registered adapter, and
    only while no profile authors activation units."""

    CONFLICT = {"pointer": "/capabilities/deploy/support",
                "message": "capabilities.deploy must be unsupported while release profiles exist",
                "repair_id": "contract.release.deploy_conflict"}

    def descriptors(self):
        """The fixture registry plus a watcher whose deploy operation a profile may bind."""
        watcher = actions_health_adapter.describe()
        watcher["operations"]["deploy"].update(support="supported", reason=None)
        return {**support.descriptors(), "github-actions-health": watcher}

    def found(self, profile, binding):
        contract = support.base_contract()
        contract["capabilities"]["deploy"]["support"] = "supported"
        contract["bindings"]["deploy"] = binding
        return release_profile.grammar_violations(
            support.release_of("github-release", profile), contract, self.descriptors())

    def watch(self, adapter="github-actions-health"):
        return {"adapter": adapter, "command": None, "config": {}}

    def test_a_registered_adapter_coexists_with_profiles_without_activation(self):
        self.assertEqual(self.found(support.forge_profile(), self.watch()), [])

    def test_activation_units_keep_the_conflict(self):
        profile = support.forge_profile()
        profile["requirements"]["adapters"]["watch"] = {"min_inclusive": "1.0.0",
                                                        "max_exclusive": "2.0.0"}
        profile["bindings"]["adapters"]["watch"] = {"adapter": "github-actions-health"}
        profile["bindings"]["targets"]["site"] = {
            "adapter": "watch", "kind": "github_repository",
            "repository": "fagenorn/nix-config", "branch": "main"}
        profile["bindings"]["credentials"]["gh-cli"] = {"adapter": "watch", "class": "gh_cli"}
        profile["activation"] = {"units": [{
            "id": "deploy", "mode": "publication_triggered", "adapter": "watch",
            "operation": "deploy", "target": "site", "principal": "maintainer",
            "credential": "gh-cli", "effect": "reversible_no_incremental_spend",
            "config_schema_version": 1,
            "config": {"workflow": "deploy.yml", "branch": "main", "services": ["site"],
                       "health_url": "https://example.com/health", "health_commit_field": "commit"},
            "deps": [], "observation_deadline_ms": 600000}]}
        profile["recovery"]["units"]["deploy"] = {"posture": "supersedable_only", "anchor": None,
                                                  "compatibility": None, "edges": []}
        self.assertEqual(self.found(profile, self.watch()), [self.CONFLICT])

    def test_an_unregistered_or_malformed_binding_keeps_the_conflict(self):
        for binding in (self.watch("railway"), self.watch(7), "github-actions-health", None):
            with self.subTest(binding=binding):
                self.assertEqual(self.found(support.forge_profile(), binding), [self.CONFLICT])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Unit run on `home/common/agent-skills/tests/test_resolve_project.py -k DeployWatch`.

Expected: `FAILED (failures=6)`:

- the JarBird test exits 2 with `invalid_contract`;
- each of the four rule subtests gets `contract.capabilities.deploy.binding_incomplete` or `contract.release.deploy_conflict`;
- the no-profiles test is refused.

Run the Unit run on `tests/test_release_grammar.py -k DeployWatchGrammarTest`.

Expected: `FAILED (failures=1)`. Only `test_a_registered_adapter_coexists_with_profiles_without_activation` fails, because the other two pin the conflict that already holds.

- [ ] **Step 3: Write the minimal implementation**

1. `python/agent_tools/resolve_project.py`:
   - Replace `validate_deploy` with the following, and add `registered_deploy_adapter` directly above it:

```python
def registered_deploy_adapter(deploy: object) -> str | None:
    """The deploy binding's adapter when it is a `release_adapter.REGISTRY` key, else None."""
    adapter = deploy.get("adapter") if isinstance(deploy, dict) else None
    return adapter if isinstance(adapter, str) and adapter in release_adapter.REGISTRY else None


def validate_deploy(deploy: dict, commands: dict | None, tracker: dict | None,
                    violations: list[dict]) -> None:
    """Every shape violation of `bindings.deploy`, whatever the authored support.

    A registered release adapter adds four rules (issue 465 D3, D15): `command` must be null,
    the descriptor must have one watch operation, `config` must pass that operation's closed
    schema, and the tracker must be GitHub. Any other adapter keeps a free-form `config` and
    a `command` id checked against `commands`.
    """
    check_exact_members(
        deploy, "/bindings/deploy", DEPLOY_MEMBERS, "deploy", violations)
    if "adapter" in deploy:
        check_string(deploy["adapter"], "/bindings/deploy/adapter", "deploy",
                     violations)
    registered = registered_deploy_adapter(deploy)
    if "command" in deploy and deploy["command"] is not None:
        if registered is not None:
            violations.append(violation(
                "/bindings/deploy/command",
                f"must be null: the registered adapter '{registered}' is the deploy reader",
                "contract.deploy.command_conflict"))
        else:
            check_command_id(
                deploy["command"], "/bindings/deploy/command", commands, violations)
    config_ok = "config" in deploy and check_object(
        deploy["config"], "/bindings/deploy/config", "deploy", violations)
    if registered is None:
        return
    descriptor = release_adapter.DESCRIPTORS[registered]
    operation = release_adapter.watch_operation(descriptor)
    if operation is None:
        violations.append(violation(
            "/bindings/deploy/adapter",
            f"adapter '{registered}' has no single operation a deploy watch can inspect",
            "contract.deploy.adapter_unwatchable"))
    elif config_ok:
        schema = descriptor["operations"][operation]["config_schema"]
        for problem in release_adapter.config_problems(schema, deploy["config"]):
            violations.append(violation(
                "/bindings/deploy/config", problem, "contract.deploy.config_invalid"))
    if isinstance(tracker, dict) and "kind" in tracker and tracker["kind"] != "github":
        violations.append(violation(
            "/bindings/deploy/adapter",
            f"adapter '{registered}' watches a GitHub repository, and the tracker is not GitHub",
            "contract.deploy.tracker_not_github"))
```

   - In `validate_bindings`, call `validate_deploy(present["deploy"], commands, present.get("tracker"), violations)`.
   - In `validate_capability_bindings`, make this the first statement inside `for path, is_complete in CAPABILITY_BINDING_REQUIREMENTS[name]:`:

```python
            if path == ("deploy", "command") and registered_deploy_adapter(
                    bindings.get("deploy")) is not None:
                continue
```

   - In `first_unmet_prerequisite`, make the `deploy` branch:

```python
    elif name == "deploy":
        adapter = registered_deploy_adapter(bindings["deploy"])
        if adapter is not None:
            executables = release_adapter.DESCRIPTORS[adapter]["executables"]
            return None if all(resolves_on_path(executable, root)
                               for executable in executables) else "release_adapter_unavailable"
        ids = [bindings["deploy"]["command"]]
```

   - Append one line to the D6 comment above `CAPABILITY_BINDING_REQUIREMENTS`: `# The deploy command row is skipped for a registered release adapter, which is itself the deploy reader (issue 465 D3).`
   - Append this sentence to `first_unmet_prerequisite`'s docstring: `` A deploy binding that names a registered release adapter is ready when every executable its descriptor declares resolves on `PATH`, else `release_adapter_unavailable` (issue 465 D3). ``

2. `python/agent_tools/release_profile.py`:
   - In `_Grammar.release`, add `and not self.deploy_watch_coexists(profiles)` as the last conjunct of the `deploy_conflict` condition. Wrap the condition in parentheses: `if (isinstance(deploy, dict) and "support" in deploy and deploy["support"] != "unsupported" and not self.deploy_watch_coexists(profiles)):`.
   - Add this method to `_Grammar`, after `release`:

```python
    def deploy_watch_coexists(self, profiles: dict) -> bool:
        """Issue 465 D4: a supported deploy may sit beside profiles when `bindings.deploy`
        names a registered adapter and no profile authors `activation` as an object."""
        bindings = self.contract.get("bindings")
        binding = bindings.get("deploy") if isinstance(bindings, dict) else None
        adapter = binding.get("adapter") if isinstance(binding, dict) else None
        return (isinstance(adapter, str) and adapter in self.descriptors
                and not any(isinstance(profile, dict) and isinstance(profile.get("activation"), dict)
                            for profile in profiles.values()))
```

   - In the module docstring, replace `` `contract["bindings"]["tracker"]`, `contract["bindings"]["vcs"]["default_branch"]` and `contract["capabilities"]["deploy"]` `` with `` `contract["bindings"]["tracker"]`, `contract["bindings"]["vcs"]["default_branch"]`, `contract["bindings"]["deploy"]["adapter"]` and `contract["capabilities"]["deploy"]` ``.

3. In `python/README.md` § Release profiles, insert the following directly after the sentence that ends `` is a grammar violation, never a lookup fallback (D7). ``, in the same paragraph:

```text
While any profile exists, the grammar's `contract.release.deploy_conflict` refuses a `capabilities.deploy` other than `unsupported` at `/capabilities/deploy/support` (#124 D1), unless `bindings.deploy.adapter` is a registered adapter and no profile authors `activation` as an object: a deploy watch through a registered adapter then coexists with profiles while one activation authority remains (issue 465 D4). `resolve-project` holds such a binding, whatever its support, to `command: null` (`contract.deploy.command_conflict`), a descriptor with exactly one inspectable activation-mode operation (`contract.deploy.adapter_unwatchable`), a `config` that passes that operation's closed schema (`contract.deploy.config_invalid`, one violation per problem) and a GitHub tracker (`contract.deploy.tracker_not_github`); a supported one needs no `command`, and it is `available` when every executable the descriptor declares resolves on `PATH`, else `blocked` with `release_adapter_unavailable` (issue 465 D3). An unregistered adapter such as `railway` keeps a free-form `config` and a required `command`.
```

- [ ] **Step 4: Verify**

1. Run the Unit run on `home/common/agent-skills/tests/test_resolve_project.py tests/test_release_grammar.py tests/test_release_profile.py tests/test_release_bridge.py tests/test_actions_health_adapter.py` (timeout 1800 s).

   Expected: `OK`. This includes the unedited railway and completeness tests, and `test_nix_activate_is_exact_and_deploy_stays_unsupported`.

2. Run the Unit run on `home/common/agent-skills/tests/test_conformance_checks.py` (timeout 1800 s).

   Expected: `OK`, because the release-profile conformance items read the same grammar.

3. Run `bash -c 'git diff --quiet HEAD -- .agents/project.json python/agent_tools/release_adapter.py'`.

   Expected: exit 0. The contract and the adapter contract are untouched in this task.

4. Run the Build.

   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py python/agent_tools/release_profile.py home/common/agent-skills/tests/test_resolve_project.py tests/test_release_grammar.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(resolve-project): a registered deploy adapter beside release profiles (issue 465)" -m "<trailers>"
```
