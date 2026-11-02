# Task 5: `launchd-agent` activation, registration, AC2 and docs

Per D1, D2, D3, D7, D8, D12, D15, D18 and AC2. Read the plan root's Global Constraints and the spec's § `launchd-agent` `invoke` steps and § Shared rules first. This task implements those steps.

**Files:**
- Modify: `python/agent_tools/launchd_agent_adapter.py` (add `invoke`, `INVOKE_BUDGET_SECONDS = 60`, docstring)
- Modify: `tests/test_launchd_agent_adapter.py` (new `InvokeTest`; Task 4's `DescribeTest` absence assertion becomes a registration assertion)
- Modify: `python/agent_tools/release_adapter.py` (import the module, add `"launchd-agent"` to `REGISTRY`)
- Modify: `tests/test_release_adapter_core.py` (extend `RegistryTest`)
- Modify: `tests/test_release_grammar.py` (`test_registry_is_closed` expects four names)
- Modify: `python/README.md` (§ Release adapters: one new paragraph after the `codesigned-artifact` one)

**Interfaces:**
- Consumes: `tests/host_world.py` (`program`, `plist_path`, `load_job`, `job`, `fail` with `launchctl` verbs `print`/`bootout`/`bootstrap`, `calls`, `tree`, `dirty`), the suite's `Case` (`parameters`, `effect`, `managed`), `LABEL` and `CONFIG`, and `RegistryTest` in `tests/test_release_adapter_core.py`.
- Produces: `launchd_agent_adapter.invoke(request) -> {"result", "error_class", "reference"}` and `release_adapter.REGISTRY["launchd-agent"]` (Tasks 6 and 7).

**Invariants:**
- `invoke` returns only a closed `InvokeResult` and never raises. It runs only `git` and `launchctl`, by name, and never `claude-bash-lifecycle-guard` or `kickstart` (D2, D12).
- A refusal before the first host write sends no `bootout` or `bootstrap`, and writes no plist.
- On `accepted`, the plist at `~/Library/LaunchAgents/<label>.plist` is mode `0644` and is exactly the rendered dict in Step 1, and the agent was bootstrapped from it.
- `watch_operation` is `None` for `launchd-agent` and for `codesigned-artifact`, and `deploy` for `github-actions-health` (D10).
- No `python/agent_tools/*.py` file contains `argus` in any case (AC2).

## `invoke`, in order, stopping at the first refusal

The reference of a refusal is `<step>: <detail>`, cut to 240 characters. One `INVOKE_BUDGET_SECONDS` deadline covers every child. A child started with no budget left is a timeout.
1. **Shape.** The request is exactly `{kind: "effect", operation, parameters}`, else `invalid_input`. An operation that `describe()` does not declare is `unsupported_operation`. Parameters that fail the module's existing shape check (the one effect `inspect` applies, `candidate` required) are `invalid_input`. No child starts.
2. **Authority.** `os.getuid() == 0` is `authorization_denied`.
3. **Checkout** (124 D23). `git rev-parse --show-toplevel` in the process's working directory gives the root, which must be absolute. `git -C <root> rev-parse HEAD` must equal the candidate commit, and `git -C <root> status --porcelain --untracked-files=no` must print nothing, else `precondition_failed`. A read that times out is `transient_transport`, and one that cannot start or exits non-zero is `provider_unavailable`.
4. **Program.** `shutil.which(program)` must resolve, else `precondition_failed`.
5. **Plist path.** An existing plist path that is a symlink or not a regular file is `precondition_failed`.
6. **Loaded state.** Run `launchctl print gui/<uid>/<label>`.
   - Exit 113 means the agent is not loaded.
   - Exit 0 means it is loaded, and its parsed `path` must equal the plist path, else `precondition_failed`. A block that the module's existing `print` parser refuses (D21) is `provider_unavailable`.
   - Any other exit, or a missing `launchctl`, is `rejected`/`provider_unavailable`, and a timeout is `rejected`/`transient_transport`.
7. **Bootout** (only when loaded). `launchctl bootout gui/<uid>/<label>`: a non-zero exit is `rejected`/`transient_transport`, and a timeout is `unknown`/`transient_transport`.
8. **Plist write.** Create `~/Library/LaunchAgents` when it is missing. Write the rendered plist (`plistlib`, XML, `sort_keys=True`) to a `tempfile.mkstemp` file in that directory, `chmod` it `0o644`, and `os.replace` it onto the plist path.
   - An `OSError` before the replace removes the temporary file.
   - It answers `rejected`/`provider_unavailable` when nothing was loaded, and `unknown`/`transient_transport` after a bootout (D15).
9. **Bootstrap.** `launchctl bootstrap gui/<uid> <plist>`: exit 0 is `accepted` with reference `gui/<uid>/<label>`. Anything else, a timeout included, is `unknown`/`transient_transport`.

The rendered plist (D8, D18) holds:
- `Label`;
- `ProgramArguments` as `[shutil.which(program), *arguments]`;
- `WorkingDirectory` as the checkout root;
- `RunAtLoad: True`, and `KeepAlive` as `keep_alive`;
- `EnvironmentVariables` with exactly the two stamp variables;
- `ProcessType: "Background"`, only when `background` is true;
- `StandardOutPath` and `StandardErrorPath` as `os.path.join(root, <path>)`, only when configured.

- [ ] **Step 1: Write the failing tests**

In `tests/test_launchd_agent_adapter.py` (add `import plistlib, stat`), first retire Task 4's absence assertion: rename `DescribeTest.test_descriptor_is_exact_valid_fresh_and_unregistered` to `test_descriptor_is_exact_valid_fresh_and_registered`, and replace its `"launchd-agent"` not-in-`REGISTRY` assertion with `self.assertIs(release_adapter.REGISTRY["launchd-agent"], adapter)`. Then add:

```python
class InvokeTest(Case):
    def invoke(self, parameters=None):
        return adapter.invoke({"kind": "effect", "operation": "activate",
                               "parameters": parameters or self.parameters()})

    def rendered(self, **overrides):
        root = str(self.world.checkout)
        plist = {"Label": LABEL, "ProgramArguments": [str(self.world.bin / "notifierd"), "serve", "--quiet"],
                 "WorkingDirectory": root, "RunAtLoad": True, "KeepAlive": True,
                 "ProcessType": "Background",
                 "EnvironmentVariables": {"AGENT_RELEASE_VERSION": "v1.2.3",
                                          "AGENT_RELEASE_COMMIT": self.candidate["commit"]},
                 "StandardOutPath": os.path.join(root, "logs/out.log"),
                 "StandardErrorPath": os.path.join(root, "logs/err.log")}
        plist.update(overrides)
        return {key: value for key, value in plist.items() if value is not None}

    def test_bootstraps_a_rendered_plist_then_inspects_satisfied(self):
        service, path = f"gui/{os.getuid()}/{LABEL}", self.world.plist_path(LABEL)
        self.assertEqual(self.invoke(), {"result": "accepted", "error_class": None, "reference": service})
        with open(path, "rb") as handle:
            self.assertEqual(plistlib.load(handle), self.rendered())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual([c["argv"] for c in self.world.calls("launchctl")],
                         [["print", service], ["bootstrap", f"gui/{os.getuid()}", str(path)]])
        self.assertEqual(self.world.calls("claude-bash-lifecycle-guard"), [])
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))
```

Add:
- `InvokeTest.test_a_loaded_older_release_is_booted_out_and_back_in`: `managed(stamp=("v1.2.2", "f" * 40))`. Expect `accepted`, the launchctl verbs `["print", "bootout", "bootstrap"]`, and `world.job(LABEL)` with `runs == 1`, a new pid and the candidate stamp.
- `InvokeTest.test_optional_members_are_omitted`: config `{"program": "notifierd", "keep_alive": False}` renders exactly `rendered(ProgramArguments=[<bin>/notifierd], KeepAlive=False, ProcessType=None, StandardOutPath=None, StandardErrorPath=None)`. `background=False` with the other members also omits `ProcessType`.
- `InvokeTest.test_each_refusal`, a table. For each row, `self.setUp()`, arrange, snapshot `world.tree()`, invoke, and assert `(result, error_class)` and the reference fragment. A `rejected` row's tree is unchanged except where noted. Rows:
  - label `-x`: `invalid_input`, `world.calls() == []`;
  - operation `install`: `unsupported_operation`, no calls;
  - `getuid` patched to 0: `authorization_denied`, no calls;
  - commit `"f" * 40`: `precondition_failed`, no `launchctl` call;
  - `world.dirty()`: `precondition_failed`, no `launchctl` call;
  - program `missingd`: `precondition_failed`, `program`, no `launchctl` call;
  - plist path a symlink: `precondition_failed`, the symlink intact, no `launchctl` call;
  - `load_job` from `/Library/LaunchAgents/x.plist`: `precondition_failed`, verbs `["print"]`, the job unchanged;
  - `print` knob exit 5: `provider_unavailable`;
  - `managed(stamp=("v1.2.2", "f" * 40))` with a `bootout` knob exit 1: `rejected`/`transient_transport`, the job still loaded, no plist;
  - the same with the budget patched to 1 and a `bootout` knob of exit 0 and sleep 3: `unknown`/`transient_transport`;
  - a `bootstrap` knob exit 5: `unknown`/`transient_transport`, the plist written;
  - `os.replace` patched to raise `OSError`, nothing loaded: `rejected`/`provider_unavailable`, no plist and no temporary file in `LaunchAgents` (the directory itself may exist);
  - the same after `managed(stamp=("v1.2.2", "f" * 40))`: `unknown`/`transient_transport`.

In `tests/test_release_adapter_core.py`'s `RegistryTest` (add `REPO = Path(__file__).resolve().parents[1]` and import `launchd_agent_adapter`):

```python
    def test_the_registry_holds_four_adapters_and_one_deploy_watch(self):
        self.assertIs(release_adapter.REGISTRY["launchd-agent"], launchd_agent_adapter)
        self.assertEqual(release_adapter.DESCRIPTORS["launchd-agent"], launchd_agent_adapter.describe())
        self.assertEqual({name: release_adapter.watch_operation(descriptor)
                          for name, descriptor in release_adapter.DESCRIPTORS.items()},
                         {"codesigned-artifact": None, "github-actions-health": "deploy",
                          "github-forge": None, "launchd-agent": None})

    def test_no_agent_tools_module_names_argus(self):
        """AC2: the vocabulary is neutral."""
        modules = sorted((REPO / "python/agent_tools").glob("*.py"))
        self.assertGreater(len(modules), 50)
        for path in modules:
            with self.subTest(module=path.name):
                self.assertNotIn("argus", path.read_text("utf-8").lower())
```

`test_registry_is_closed` expects `["codesigned-artifact", "github-actions-health", "github-forge", "launchd-agent"]`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launchd_agent_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py 2>&1 | tail -4'`
Expected: FAIL. `InvokeTest` fails with `AttributeError` (no `invoke`), and the registry tests and `test_descriptor_is_exact_valid_fresh_and_registered` with `KeyError: 'launchd-agent'`. The `argus` scan passes: it pins.

- [ ] **Step 3: Write the minimal implementation**

Implement `invoke` and the renderer, update the module docstring for `invoke`, and register the module.

Add one paragraph to § Release adapters after the `codesigned-artifact` one, written from the implemented code. It states:
- the registered name and module;
- the `activate` operation (`local_apply`, `in_place`, supported, both non-spend effect classes) and its three predicates;
- the `launchd_gui_agent` `label` rule, the fixed `gui/<uid>` domain and plist path, and the uid-0 refusal;
- the closed config, noting that `arguments` is the `string_list` type, so it is non-empty with unique items;
- the rendered plist and its stamp variables;
- the `invoke` steps, with the `rejected`/`unknown` boundary;
- that install, restart and status are this one operation and its inspection;
- the `print` grammar, and that both classifications are the issue 547 spec's tables;
- that `watch_operation` is `None` for it (D10);
- that the world fakes `launchctl` too.

Keep it under 1,800 bytes, and edit no other line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launchd_agent_adapter.py tests/test_codesigned_artifact_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py tests/test_release_profile.py tests/test_actions_health_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k Release 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run (timeout 3600 s): `just build`
Expected: exit 0 (`DESCRIPTORS` builds four adapters).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/launchd_agent_adapter.py tests/test_launchd_agent_adapter.py python/agent_tools/release_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T5): activate and register launchd-agent" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":5,"records":[{"bounds":[{"added_lines":460,"boundary":"all","deleted_lines":0,"record_bytes":34816,"support":{"covers":["r4b","r5a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5a","last_task":5,"owner":5,"path":"python/agent_tools/launchd_agent_adapter.py"},{"bounds":[{"added_lines":445,"boundary":"all","deleted_lines":0,"record_bytes":33792,"support":{"covers":["r4c","r5b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5b","last_task":5,"owner":5,"path":"tests/test_launchd_agent_adapter.py"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":5,"record_bytes":6144,"support":{"covers":["r1a","r3c","r5c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5c","last_task":5,"owner":5,"path":"python/agent_tools/release_adapter.py"},{"bounds":[{"added_lines":90,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r1b","r3d","r5d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5d","last_task":7,"owner":5,"path":"tests/test_release_adapter_core.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r3e","r5e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5e","last_task":6,"owner":5,"path":"tests/test_release_grammar.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":2,"record_bytes":43008,"support":{"covers":["r1c","r3f","r5f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5f","last_task":7,"owner":5,"path":"python/README.md"}]}}
```
