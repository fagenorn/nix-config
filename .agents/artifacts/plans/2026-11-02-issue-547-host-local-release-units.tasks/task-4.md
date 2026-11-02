# Task 4: Fake `launchctl` and the `launchd-agent` read half

Per D1, D4, D5, D6, D7, D8, D13, D17, D19, D21. Read the plan root's Global Constraints and the spec's § `launchd-agent` (target, config, `inspect` table) and § Liveness first: this task implements those two tables exactly.

**Files:**
- Modify: `tests/host_world.py` (fake `launchctl`, program stubs, job seeding)
- Create: `python/agent_tools/launchd_agent_adapter.py` (`describe`, `inspect`; no `invoke` yet, not registered)
- Create: `tests/test_launchd_agent_adapter.py`
- Modify: `justfile` (add the new suite after `tests/test_codesigned_artifact_adapter.py`)

**Interfaces:**
- Consumes: Task 2's `HostWorld` (its patch, `calls`, `fail`, `tree`, `commit`, `dirty`, `head`).
- Produces, in `HostWorld`:
  - `program(name) -> str`: an executable no-op stub in `bin/`, returning its absolute path.
  - `plist_path(label) -> Path`: `home/Library/LaunchAgents/<label>.plist`.
  - `load_job(label, *, path, environment=None, state="running", runs=1, working_directory=None, default_environment=None) -> None` and `job(label) -> dict | None`.
  - `fail(...)` also takes `stdout=""`.
- Produces, in `agent_tools.launchd_agent_adapter`: `describe()`, `inspect(request)`, `INSPECT_BUDGET_SECONDS = 30`, `DETAIL_LIMIT = 240`, `NOT_LOADED_EXIT = 113`, `STAMP_VERSION = "AGENT_RELEASE_VERSION"`, `STAMP_COMMIT = "AGENT_RELEASE_COMMIT"`, `CONFIG_MEMBERS`. Task 5 adds `invoke` and registers it.

**Invariants:**
- `describe()` returns a fresh dict equal to `DESCRIPTOR` in Step 1, with no `descriptor_problems`.
- `inspect` never raises and never mutates. `world.tree()`, `state/launchd.json` and the checkout's `.git/index` bytes are unchanged, and it runs only `launchctl print` and `git --no-optional-locks` (D21).
- The domain is always `gui/<os.getuid()>`, and the plist is always `~/Library/LaunchAgents/<label>.plist` (D7).
- Every non-`satisfied` `running_subject_identity` reason lies in the core's closed space (D19). The module imports only the standard library and `agent_tools.canonical`.

## Fake `launchctl` (`tests/host_world.py`)

It is one more script in the style of the `codesign` fake already in that file (it logs to `calls.jsonl` and obeys `knobs.json`), with knob verbs `print`, `bootout` and `bootstrap` and state `state/launchd.json` (`{"jobs": {}, "next_pid": 4000}`). A knob's `stdout` is written before its stderr. A job is `{path, state, pid, runs, program, arguments, working_directory, environment, default_environment}`.
- `print gui/<uid>/<label>`: with no job, stderr `Bad request.` then `Could not find service "<label>" in domain for user gui: <uid>`, exit 113. Otherwise stdout is this block, exit 0. `\t` is one tab, and blank lines are as captured:
  - `gui/<uid>/<label> = {`, then `\tactive count = 1`, `\tpath = <path>`, `\ttype = LaunchAgent`, `\tstate = <state>`, a blank line;
  - `\tprogram = <program>` and `\targuments = {`, one `\t\t<arg>` per argument, `\t}`, a blank line;
  - `\tworking directory = <dir>` (only when set), a blank line;
  - `\tinherited environment = {` with `\t\tSSH_AUTH_SOCK => /var/run/com.apple.launchd.fake/Listeners` and `\t}`;
  - `\tdefault environment = {` with `\t\tPATH => /usr/bin:/bin:/usr/sbin:/sbin` and each `default_environment` pair, then `\t}`;
  - `\tenvironment = {`, one `\t\t<K> => <V>` per job variable, then `\t\tXPC_SERVICE_NAME => <label>` and `\t}`;
  - `\tLWCR = {`, `\t\t"vers" => 1`, `\t}`;
  - `\tdomain = gui/<uid> [100016]`, `\truns = <runs>`, `\tpid = <pid>` (only when a pid is set), `\timmediate reason = speculative`, `}`.
- `bootout gui/<uid>/<label>`: with no job, stderr `Boot-out failed: 3: No such process`, exit 3. Otherwise it removes the job, exit 0.
- `bootstrap gui/<uid> <plist>`: `plistlib`-loads the plist. When its `Label` is loaded, stderr `Bootstrap failed: 5: Input/output error`, exit 5. Otherwise it adds the job, exit 0:
  - `path` is the argument, `state` is `running`, `runs` is 1, and `pid` is the next pid;
  - `program` is `ProgramArguments[0]`, `arguments` is `ProgramArguments`, `working_directory` is `WorkingDirectory`, and `environment` is `EnvironmentVariables`.

## The adapter read half

`DESCRIPTOR` below is the spec's table. The first failing shape rule answers `parameters_invalid`, with the rule in `facts.detail`; `python/agent_tools/codesigned_artifact_adapter.py` (Task 2's commit) shows the pattern:
- An effect request is exactly `{kind: "effect", operation, parameters}`, and a predicate request exactly `{kind: "predicate", predicate, operation, parameters}`. The operation is `activate`.
- `parameters` holds `target`, `config` and `candidate`, may hold `action` and `operation`, and holds nothing else.
- `candidate` is exactly `{version: vMAJOR.MINOR.PATCH, commit: 40 lowercase hex}`.
- Strings are non-empty and free of control characters (`[\x00-\x1f\x7f]`).
- `target` is `{kind: "launchd_gui_agent", label}` plus an optional `handle`, where `label` fully matches `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`.
- `candidate` is required for effect and `running_subject_identity` requests. It is optional for `agent_running`, but checked when present.
- `config` takes `program` and `keep_alive` as required, and `arguments`, `background`, `stdout_path` and `stderr_path` as optional:
  - `program` is non-empty with no `/`, is neither `.` nor `..`, and has no control character;
  - `arguments` is a non-empty list of unique non-empty strings without control characters;
  - the two booleans are `bool`;
  - the two paths are relative, with non-empty segments that are neither `.` nor `..`.

The module owns its runner (D1), with the same contract as `codesigned_artifact_adapter`'s:
- It runs `[name, *args]` by name, with stdin `/dev/null`, the environment unchanged, and text with `errors="replace"`.
- Its timeout is what is left of one `INSPECT_BUDGET_SECONDS` deadline per call.
- `TimeoutExpired` is `lookup_timeout`, `OSError` is `executable_missing`, and `ValueError` is `lookup_failed`.
- Stderr goes to `facts.detail`, cut to 240 characters.

The `print` grammar is D21's:
- A field is a line `^\t([^\t][^=]*?) = (.*)$`.
- The environment block runs from the line `\tenvironment = {` to the next line `\t}`, and its lines `^\t\t(\S+) => (.*)$` are variables.
- `path`, `state` and an integer `runs` are required, and a missing one is `unknown`/`payload_invalid`. `pid` (an integer) and `working directory` are optional.
- The stamp is present only when both stamp variables are in that block.

The effect rows run in the spec's order:
1. `os.lstat` of the plist path: present and a symlink or not a regular file is `plist_unexpected`.
2. `launchctl print gui/<uid>/<label>`: exit 113 is not loaded, and any other non-zero exit is `unknown`/`lookup_failed`.
3. Then come the foreign path, the unmanaged job, and another release.
4. When the stamp names the candidate:
   - with no `working directory`, the row is `checkout_moved` with `checkout: null`;
   - otherwise run `git --no-optional-locks -C <dir> rev-parse HEAD` and `git --no-optional-locks -C <dir> status --porcelain --untracked-files=no`. A failed read is `unknown` with the runner's reason, and a different HEAD or any status output is `checkout_moved`.
5. Then not running, then `running`.

`running_subject_identity` maps each row by the table's last column, and an invalid request is `unknown`/`identity_unobservable` (D19). `agent_running` runs `print` only and follows the § Liveness table; its invalid request is `unknown`/`parameters_invalid`. Any other predicate is `unknown`/`predicate_unsupported`. Observation members are per the spec. `observed_subject` is always `{version, commit, pid}`, and `facts` always holds the 11 named keys, plus `detail` on a failure.

- [ ] **Step 1: Write the failing tests**

`tests/test_launchd_agent_adapter.py`, docstring `"""The launchd-agent adapter (issue 547). Run: just agent-workflow-tests"""`:

```python
import os
import unittest
from unittest import mock

from agent_tools import launchd_agent_adapter as adapter, release_adapter
from .host_world import HostWorld

LABEL = "dev.example.notifier"
CONFIG = {"program": "notifierd", "arguments": ["serve", "--quiet"], "keep_alive": True,
          "background": True, "stdout_path": "logs/out.log", "stderr_path": "logs/err.log"}
DESCRIPTOR = {"name": "launchd-agent", "adapter_contract_version": "1.0.0",
              "operations": {"activate": {
                  "mode": "local_apply", "support": "supported", "inspect": "supported",
                  "reason": None, "mutability": "in_place", "config_schema_version": 1,
                  "config_schema": {"members": {"arguments": "string_list", "background": "boolean",
                                                "keep_alive": "boolean", "program": "string",
                                                "stderr_path": "string", "stdout_path": "string"},
                                    "required": ["keep_alive", "program"]},
                  "effects": ["reversible_no_incremental_spend", "irreversible"],
                  "recovery_capable": False, "candidate_members": []}},
              "predicates": {"agent_running": {"support": "supported", "reason": None},
                             "publication_visible": {"support": "unsupported",
                                                     "reason": "no_publication_mode"},
                             "running_subject_identity": {"support": "supported", "reason": None}},
              "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
              "target_kinds": {"launchd_gui_agent": ["label"]},
              "credential_classes": ["gui_session"], "executables": ["git", "launchctl"],
              "host_capacity": "not_required"}

class Case(unittest.TestCase):
    def setUp(self):
        self.world = HostWorld(self)
        self.world.program("notifierd")
        self.candidate = {"version": "v1.2.3", "commit": self.world.head()}

    def parameters(self, candidate=True, **config):
        parameters = {"action": "agent", "operation": "activate",
                      "target": {"handle": "agent", "kind": "launchd_gui_agent", "label": LABEL},
                      "config": {**CONFIG, **config}}
        if candidate:
            parameters["candidate"] = dict(self.candidate)
        return parameters

    def effect(self, parameters=None):
        return adapter.inspect({"kind": "effect", "operation": "activate",
                                "parameters": parameters or self.parameters()})

    def predicate(self, name, parameters=None):
        return adapter.inspect({"kind": "predicate", "predicate": name, "operation": "activate",
                                "parameters": parameters or self.parameters(
                                    candidate=name != "agent_running")})

    def managed(self, stamp="candidate", **changes):
        stamp = (self.candidate["version"], self.candidate["commit"]) if stamp == "candidate" else stamp
        environment = {} if stamp is None else {adapter.STAMP_VERSION: stamp[0],
                                                adapter.STAMP_COMMIT: stamp[1]}
        self.world.load_job(LABEL, path=str(self.world.plist_path(LABEL)), environment=environment,
                            working_directory=str(self.world.checkout), **changes)

class ClassificationTest(Case):
    def test_each_row_of_the_inspect_table(self):
        plist = lambda: self.world.plist_path(LABEL)
        rows = (
            ("plist symlink", lambda: plist().parent.mkdir(parents=True) or
             plist().symlink_to(self.world.checkout), ("diverged", "plist_unexpected"),
             ("unsatisfied", "subject_mismatch")),
            ("plist directory", lambda: plist().mkdir(parents=True), ("diverged", "plist_unexpected"),
             ("unsatisfied", "subject_mismatch")),
            ("not loaded", lambda: None, ("absent", "agent_not_loaded"), ("unsatisfied", "subject_absent")),
            ("foreign path", lambda: self.world.load_job(LABEL, path="/Library/LaunchAgents/x.plist"),
             ("diverged", "agent_path_foreign"), ("unsatisfied", "subject_mismatch")),
            ("unmanaged", lambda: self.managed(stamp=None), ("absent", "agent_unmanaged"),
             ("unsatisfied", "unrelated_subject_running")),
            ("stamp only in default environment", lambda: self.managed(
                stamp=None, default_environment={adapter.STAMP_VERSION: "v1.2.3",
                                                 adapter.STAMP_COMMIT: self.candidate["commit"]}),
             ("absent", "agent_unmanaged"), ("unsatisfied", "unrelated_subject_running")),
            ("other release", lambda: self.managed(stamp=("v1.2.2", "f" * 40)),
             ("absent", "agent_other_release"), ("unsatisfied", "subject_mismatch")),
            ("head moved", lambda: self.managed() or self.world.commit(),
             ("diverged", "checkout_moved"), ("unsatisfied", "subject_mismatch")),
            ("tracked change", lambda: self.managed() or self.world.dirty(),
             ("diverged", "checkout_moved"), ("unsatisfied", "subject_mismatch")),
            ("not running", lambda: self.managed(state="not running"),
             ("in_progress", "agent_not_running"), ("unsatisfied", "subject_absent")),
            ("running", lambda: self.managed(), ("satisfied", "running"), ("satisfied", "running")),
            ("print exit 5", lambda: self.world.fail("launchctl", "print", exit=5),
             ("unknown", "lookup_failed"), ("unknown", "identity_unobservable")),
            ("no runs line", lambda: self.world.fail("launchctl", "print", exit=0,
                                                     stdout=f"gui/1/{LABEL} = {{\n\tpath = x\n}}\n"),
             ("unknown", "payload_invalid"), ("unknown", "identity_unobservable")),
            ("launchctl missing", lambda: (self.world.bin / "launchctl").unlink(),
             ("unknown", "executable_missing"), ("unknown", "identity_unobservable")))
        for name, arrange, effect, identity in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                observed = self.effect()
                self.assertEqual((observed["outcome"], observed["reason"]), effect)
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.predicate("running_subject_identity")
                self.assertEqual((predicate["outcome"], predicate["reason"]), identity)
```

`load_job`'s `state="not running"` must leave `pid` `None`. With a running state it gets the next pid. Add, each a separate method:
- `LivenessTest.test_each_row_of_the_liveness_table`: `predicate("agent_running")` with no candidate in the parameters. Not loaded is `unsatisfied`/`agent_not_loaded`. `load_job` from a foreign path is `unsatisfied`/`agent_path_foreign`. `managed(state="not running")` is `unsatisfied`/`agent_not_running`. `managed(runs=2)` is `unsatisfied`/`agent_restarted`. `managed(stamp=None)` (running, `runs` 1) is `satisfied`/`running`. A `print` knob with exit 5 is `unknown`/`lookup_failed`. No `git` call is logged.
- `ObservationTest.test_a_satisfied_observation_names_service_plist_and_pid`, after `managed()`:
  - `observed_subject == {"version": "v1.2.3", "commit": <head>, "pid": 4000}`;
  - `references == [f"gui/{os.getuid()}/{LABEL}", str(world.plist_path(LABEL))]`;
  - `facts` has keys `checkout`, `domain`, `label`, `loaded`, `path`, `pid`, `plist`, `runs`, `stamp`, `state` and `working_directory`, with `checkout == {"head": <head>, "clean": True}` and `loaded is True`.
- `ObservationTest.test_inspect_never_mutates`: for `managed()` and for the `head moved` arrangement, `world.tree()`, `state/launchd.json` and `checkout/.git/index` bytes are equal before and after `effect()`. The launchctl calls satisfy `{c["argv"][0] for c in world.calls("launchctl")} == {"print"}`, and every `world.calls("git")` argv starts with `--no-optional-locks`.
- `ObservationTest.test_a_print_past_the_budget_is_lookup_timeout`: patch `adapter.INSPECT_BUDGET_SECONDS` to 1, with a `print` knob of exit 0 and sleep 3. The effect is `unknown`/`lookup_timeout`.
- `ShapeTest.test_requests_outside_the_closed_shape_start_no_child`: each mutation is `unknown`/`parameters_invalid` from `effect` and from `agent_running`, and `unknown`/`identity_unobservable` from `running_subject_identity`, with `world.calls() == []`. The mutations:
  - label `-x`, `a b` and `"a" * 129`;
  - target extra member `domain`, and kind `installed_bundle`;
  - program `/usr/bin/x`, `""` and `..`;
  - `arguments` `[]` and `["a", "a"]`;
  - `keep_alive` `"true"`, and `background` `1`;
  - `stdout_path` `/tmp/x` and `../x`;
  - config extra `run_at_load`, and config missing `program`;
  - candidate version `1.2.3`;
  - operation `install`.
  Missing `candidate` is `parameters_invalid` from `effect` only.
- `ShapeTest.test_undeclared_predicates_are_unsupported`: `publication_visible` and `liveness` are `unknown`/`predicate_unsupported`.
- `DescribeTest.test_descriptor_is_exact_valid_fresh_and_unregistered`: `describe() == DESCRIPTOR`, `descriptor_problems(describe()) == []`, clearing one result's `operations` leaves the next `describe()` equal to `DESCRIPTOR`, and `"launchd-agent"` is not in `REGISTRY`. An `ast` parse of the module source shows that its only `agent_tools` import is `agent_tools.canonical`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launchd_agent_adapter.py 2>&1 | tail -4'`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_tools.launchd_agent_adapter'`.

- [ ] **Step 3: Write the minimal implementation**

Extend `tests/host_world.py`, and update its docstring to name `launchctl`. Then write the module as above. Its docstring states the surface, the imports, the shape rules, the `print` grammar, the budget and the two classifications by reference to the issue 547 spec, and mentions no `invoke`. Add the suite to `justfile`.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launchd_agent_adapter.py tests/test_codesigned_artifact_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if grep -qi argus python/agent_tools/launchd_agent_adapter.py tests/host_world.py; then exit 1; fi`
Expected: exit 0.

Run (timeout 3600 s, after `git add`): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/host_world.py python/agent_tools/launchd_agent_adapter.py tests/test_launchd_agent_adapter.py justfile
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T4): fake launchctl and launchd-agent inspection" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":4,"records":[{"bounds":[{"added_lines":380,"boundary":"all","deleted_lines":0,"record_bytes":26624,"support":{"covers":["r2a","r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":4,"owner":4,"path":"tests/host_world.py"},{"bounds":[{"added_lines":270,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r4b","last_task":5,"owner":4,"path":"python/agent_tools/launchd_agent_adapter.py"},{"bounds":[{"added_lines":270,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["r4c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r4c","last_task":5,"owner":4,"path":"tests/test_launchd_agent_adapter.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2d","r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":4,"owner":4,"path":"justfile"}]}}
```
