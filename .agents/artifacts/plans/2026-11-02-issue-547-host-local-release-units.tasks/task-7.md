# Task 7: The core settles an Argus-shaped release over the host world

Per D6, D13 and D16. Read the plan root's Global Constraints first. This task adds tests and one README sentence, and no `agent_tools` code.

**Files:**
- Modify: `tests/test_release_adapter_core.py` (new `HostLocalCoreTest`)
- Modify: `python/README.md` (§ Release adapters: one sentence appended to the paragraph that ends `observed absent by a second inspection (AC8).`)

**Interfaces:**
- Consumes:
  - `support.argus_shaped_profile()` and `support.base_contract()`;
  - `release_profile.compile_profile` and `bind_candidate`, and `release_adapter.REGISTRY` and `core_binding`;
  - `CustodyCase` (`self.store`, a real `TransactionStore` on a `FakeClock`, and `self.acquire`), and `InvocationRefused` from `agent_tools.transaction_storage`;
  - from `tests/host_world.py`: `HostWorld`, `IDENTITY`, and the methods `environ`, `identities`, `bundle`, `program`, `commit`, `head`, `load_job`, `plist_path`, `calls` and `home`.
- Produces: nothing later tasks use.

**Invariants:**
- No release driver: the test calls `TransactionStore` methods directly with one `core_binding` per alias (D16), and the observer of an obligation is the binding of its `collector`.
- Every adapter call runs over the host world. The candidate commit is the temporary checkout's real `HEAD`.
- A job loaded from another plist inspects `diverged`, the core refuses its invoke `not_absent`, and `launchctl` logs no `bootout` or `bootstrap` for it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_release_adapter_core.py`. Add the imports that are missing: `plistlib`, `launchd_agent_adapter`, `InvocationRefused`, and `HostWorld` and `IDENTITY` from `.host_world`.

```python
class HostLocalCoreTest(CustodyCase):
    """Issue 547 D16: the real core settles the Argus-shaped profile over the host world."""

    def setUp(self):
        super().setUp()
        self.world = HostWorld(self)
        self.world.environ(ARGUS_CODESIGN_IDENTITY=None)
        self.world.identities(IDENTITY)
        self.world.bundle("daemon/notifyd/Argus.app", identifier="dev.argus.pings")
        self.world.program("devenv")
        self.compiled = release_profile.compile_profile("argus", support.argus_shaped_profile(),
                                                        support.base_contract())
        self.bindings = {alias: release_adapter.core_binding(
            release_adapter.REGISTRY[identity["adapter"]], self.compiled, alias)
            for alias, identity in self.compiled["adapters"].items()}
        self.alias = {node["id"]: node["adapter"]
                      for node in (*self.compiled["publication"], *self.compiled["activation"])}

    def advance(self, tid, custody, *states):
        for state in states:
            self.store.advance(tid, state, reason="r", custody=custody)

    def begin(self, key, version):
        candidate = {"version": version, "commit": self.world.head(), "title": version, "notes": ""}
        inputs = release_profile.bind_candidate(self.compiled, candidate)
        tid = self.store.create(key, inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                                proof=inputs["proof"], recovery=inputs["recovery"],
                                authority_class="test").transaction_id
        custody = self.acquire(tid)
        self.advance(tid, custody, "awaiting_verification", "ready", "publishing")
        return tid, custody, {unit["name"]: unit["parameters"] for unit in inputs["proof"]["units"]}

    def act(self, custody, name, parameters, invoke=True):
        effect = self.bindings[self.alias[name]]
        after = self.store.inspect_action(custody, name=name, parameters=parameters, effect=effect)
        if invoke:
            after = self.store.invoke_action(custody, name=name, parameters=parameters, effect=effect)
        return [e["outcome"] for e in after.events if e["type"] == "action_inspected"][-1]

    def release(self, key, version):
        tid, custody, units = self.begin(key, version)
        self.assertEqual(self.act(custody, "notifier", units["notifier"]), "satisfied")
        self.advance(tid, custody, "published", "activating")
        self.assertEqual(self.act(custody, "daemon", units["daemon"]), "satisfied")
        self.advance(tid, custody, "proving")
        plan = self.store.load(tid).proof_plan
        collector = {entry["obligation_id"]: entry["collector"] for entry in plan["obligations"]}
        for identity in collector:
            self.store.collect_obligation(custody, obligation_id=identity,
                                          observer=self.bindings[collector[identity]])
        self.store.start_cohort(custody)
        for identity in plan["cohort"]["members"]:
            self.store.collect_obligation(custody, obligation_id=identity,
                                          observer=self.bindings[collector[identity]])
        return self.store.settle_proof(custody)

    def stamp_and_plist(self):
        bundle = self.world.home / "Library/Application Support/Argus/Argus.app/Contents/Info.plist"
        with open(bundle, "rb") as handle:
            info = plistlib.load(handle)
        with open(self.world.plist_path("dev.argus.daemon"), "rb") as handle:
            agent = plistlib.load(handle)
        return (info["AgentReleaseVersion"], info["AgentReleaseCommit"]), agent

    def verbs(self):
        return [call["argv"][0] for call in self.world.calls("launchctl")]

    def test_a_bound_candidate_settles_succeeded(self):
        settled = self.release("release-1", "v1.0.0")
        self.assertEqual(settled.state, "succeeded")
        stamp, agent = self.stamp_and_plist()
        self.assertEqual(stamp, ("v1.0.0", self.world.head()))
        self.assertEqual(agent["EnvironmentVariables"], {"AGENT_RELEASE_VERSION": "v1.0.0",
                                                         "AGENT_RELEASE_COMMIT": self.world.head()})
        self.assertEqual(agent["ProgramArguments"],
                         [str(self.world.bin / "devenv"), "shell", "--", "daemon", "run"])
        self.assertEqual(agent["WorkingDirectory"], str(self.world.checkout))
        self.assertNotIn("bootout", self.verbs())
```

Add two more methods:
- `test_a_second_release_replaces_both_units`: `release("release-1", "v1.0.0")`, then `world.commit()`, then `release("release-2", "v1.0.1")`. It asserts:
  - the second `state` is `succeeded`;
  - `stamp_and_plist()` names `v1.0.1` and the new HEAD in both the bundle and `EnvironmentVariables`;
  - the launchctl verbs after the first release are `print`, `bootout` and `bootstrap` in that order, among `print`s;
  - `Library/Application Support/Argus/` lists only `Argus.app`.
- `test_a_job_from_a_foreign_plist_parks_the_daemon_without_mutation`: before `begin`, `world.load_job("dev.argus.daemon", path=str(world.home / "Library/LaunchAgents/other.plist"))`. The test then:
  - runs the notifier to `satisfied` and advances to `published` and `activating`;
  - asserts `act(custody, "daemon", units["daemon"], invoke=False) == "diverged"`;
  - asserts that `store.invoke_action(...)` with the `launchd` binding raises `InvocationRefused` whose `.reason` is `not_absent`;
  - asserts that the launchctl verbs since the seed are all `print`, and that `world.plist_path("dev.argus.daemon")` does not exist.

- [ ] **Step 2: Run the test and watch it fail**

First write `release` without the `collect_obligation` loops, so that `settle_proof` judges an uncollected proof.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_adapter_core.py -k HostLocalCore 2>&1 | tail -4'`
Expected: FAIL. `test_a_bound_candidate_settles_succeeded` does not see `succeeded`: `settle_proof` raises `ProofRefused` or leaves the state `proving`. That proves the assertion can fail.

- [ ] **Step 3: Write the minimal implementation**

Restore the two collection loops as above. Append one sentence, under 400 bytes and written from the test, to the README paragraph that ends `(AC8).`. It says that `HostLocalCoreTest` in the same file drives the Argus-shaped fixture profile to `succeeded` through both host-local adapters over `tests/host_world.py`, and replaces both units at a new commit (issue 547 D16). Edit no other line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_adapter_core.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if git diff --name-only HEAD~1 -- python/agent_tools | grep -q .; then exit 1; fi`
Expected: exit 0 (no `agent_tools` change in this task's commit; run it after the commit).

- [ ] **Step 5: Commit**

```bash
git add tests/test_release_adapter_core.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T7): the core settles a host-local release" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":7,"records":[{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["r1b","r3d","r5d","r7a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7a","last_task":7,"owner":7,"path":"tests/test_release_adapter_core.py"},{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":2,"record_bytes":32768,"support":{"covers":["r1c","r3f","r5f","r6g","r7b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7b","last_task":7,"owner":7,"path":"python/README.md"}]}}
```
