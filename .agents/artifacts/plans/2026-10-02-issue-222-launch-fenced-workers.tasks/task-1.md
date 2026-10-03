# Task 1: Ledger schema v5 and worker registry verbs

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`migrate`, `migrate_1_to_2`)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (harness helpers and the new `WorkerRegistryTest` class)
- Test (schema literal updates only): `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes: the existing `parse_action_id`, `ACTION_ID_PATTERN`, `read_state_unlocked`, `transact`, `resolve_repo_root`, `RUN_ID_PATTERN`, `print_json`, `_delivery()`, and `command_check_launch`'s verdict logic.
- Produces (used by Tasks 2 and 3):
  - `SCHEMA_VERSION = 5` and `STATE_FIELDS` with `"workers"` added.
  - `WORKER_FIELDS = frozenset({"worker_id", "launch", "parent", "registered_at", "released_at", "release_event"})`
  - `WORKER_ID_PATTERN = re.compile(r"^([1-9][0-9]{0,17}:r?[1-9][0-9]{0,17}:[1-9][0-9]{0,17}):w([1-9][0-9]{0,17})$")`. Group 1 is the launch `action_id`, and group 2 is the ordinal.
  - `WORKER_RELEASE_EVENTS = frozenset({"returned", "stopped"})`
  - `launch_verdict(runtime, state: dict | None, action_id: str) -> tuple[str | None, str]` returns `(current_action_id, reason)` with exactly `command_check_launch`'s semantics and reasons. A `None` state gives `(None, "unknown_run")`. `command_check_launch` is refactored to call it, and its output must stay byte-identical.
  - `worker_verdict(runtime, state: dict | None, worker_id: str) -> tuple[str | None, str]` returns `(current_action_id, reason)`. `current_action_id` comes from `launch_verdict` for the id's launch (null for `unknown_run`). The reason precedence is `unknown_run`, then `unknown_worker`, then `released`, then the launch reason with `current` renamed `live` (per D12). A malformed id raises `WorkflowError("invalid worker_id")`.
  - `live_worker_ids(runtime, state: dict) -> list[str]` lists, in ledger order, every worker whose `worker_verdict` reason is `live`.
  - CLI verbs: `register-worker`, `release-worker` and `check-worker`, with the argv and replies below. The harness helpers `register_worker`, `release_worker`, `check_worker_raw` and `check_worker` go on `LifecycleHarness`.

**Invariants:**
- `workers` is a list of records with exactly `WORKER_FIELDS`. `worker_id` matches `WORKER_ID_PATTERN`, and its group 1 equals `launch`.
- `launch` names an existing launch. For an implementation id `i:a:l`: issue `i` exists, `a <= len(attempts)` and `l <= len(attempts[a-1]["launches"])`. For a remainder id `i:rN:l`, the same check runs against `delivery_remainders`.
- Per launch, the ordinals are exactly 1..n in list order.
- `parent` is null or the `worker_id` of an **earlier** record with the same `launch`.
- `created_at <= registered_at <= updated_at`, and `registered_at >=` the named launch record's `at`.
- `released_at is None` exactly when `release_event is None`. The event is in `WORKER_RELEASE_EVENTS`, and `registered_at <= released_at <= updated_at`.
- A `stopped` record has no unreleased descendant.
- `check-worker` never creates or changes a file, including for an unknown run (whole-tree inventory unchanged).
- A v4 ledger is read by `check-worker` and `check-launch` without a write. The first locked write persists it as schema 5 with `workers: []` (per D10). A schema-4 document that already has `workers` is refused as a hybrid.
- `register-worker` and `release-worker` refuse a `--now` earlier than the state's `updated_at`, with `"<verb> time must not move backward"`.

- [ ] **Step 1: Write the failing tests**

Add these helpers to `LifecycleHarness`, after `check_launch`:

```python
    def register_worker(self, *, action_id, now, parent=None, ok=True):
        args = ["register-worker", "--repo-root", self.root, "--run-id", self.run_id,
                "--now", now, "--action-id", action_id]
        if parent is not None:
            args.extend(("--parent", parent))
        completed = self.run_cli(*args, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def release_worker(self, *, worker_id, event, now, ok=True):
        completed = self.run_cli(
            "release-worker", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--worker-id", worker_id, "--event", event, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def check_worker_raw(self, worker_id, *, run_id=None, ok=True):
        return self.run_cli(
            "check-worker", "--repo-root", self.root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--worker-id", worker_id, ok=ok)

    def check_worker(self, worker_id, **kwargs):
        answer = json.loads(self.check_worker_raw(worker_id, **kwargs).stdout)
        self.assertEqual(set(answer), {"worker_id", "live", "current_action_id", "reason"})
        self.assertEqual(answer["worker_id"], worker_id)
        self.assertIs(answer["live"], answer["reason"] == "live")
        return answer
```

Extend `_as_legacy` so that `if version < 5: state.pop("workers", None)` runs before the existing `version < 4` branch. Extend `_restore_deliveries` so that it also copies `prior["workers"]` into the migrated state when `"workers" in prior`. The harness `finish` round-trips through schema 2, which would otherwise drop the registry.

Add this class before `PhaseGateReplyTest`:

```python
class WorkerRegistryTest(LifecycleHarness, unittest.TestCase):
    """The run-level worker registry of #222: register, release, check-worker."""

    def spawn_14(self):
        self.init_run()
        spawned = self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.assertEqual(spawned["id"], "14:1:1")

    def test_register_assigns_dense_ordinals_and_check_worker_reads_live(self):
        self.spawn_14()
        self.assertEqual(
            self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z"),
            {"worker_id": "14:1:1:w1", "launch": "14:1:1", "parent": None})
        self.assertEqual(
            self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                                 parent="14:1:1:w1"),
            {"worker_id": "14:1:1:w2", "launch": "14:1:1", "parent": "14:1:1:w1"})
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_worker("14:1:1:w2"), {
            "worker_id": "14:1:1:w2", "live": True,
            "current_action_id": "14:1:1", "reason": "live"})
        self.assertEqual(self.check_worker("14:1:1:w9")["reason"], "unknown_worker")
        self.assertEqual(self.state_path.read_bytes(), before)
        state = self.read_state()
        self.assertEqual(state["schema_version"], 5)
        self.assertEqual(state["workers"][0], {
            "worker_id": "14:1:1:w1", "launch": "14:1:1", "parent": None,
            "registered_at": "2026-08-13T20:01:00Z", "released_at": None,
            "release_event": None})

    def test_register_refuses_without_writing(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        before = self.state_path.read_bytes()
        cases = {
            "unknown parent": dict(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                                   parent="14:1:1:w7"),
            "superseded launch": dict(action_id="14:1:9", now="2026-08-13T20:02:00Z"),
            "clock moved backward": dict(action_id="14:1:1", now="2026-08-13T19:59:00Z"),
            "malformed launch": dict(action_id="14:1", now="2026-08-13T20:02:00Z"),
        }
        for name, arguments in cases.items():
            with self.subTest(name):
                refused = self.register_worker(ok=False, **arguments)
                self.assertEqual(refused.returncode, 2)
                self.assertEqual(refused.stdout, "")
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_register_refuses_an_inactive_launch(self):
        self.spawn_14()
        self.suspend(issue=14, attempt=1, blocked_on="transport",
                     now="2026-08-13T20:05:00Z")
        before = self.state_path.read_bytes()
        refused = self.register_worker(action_id="14:1:1", now="2026-08-13T20:06:00Z",
                                       ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("inactive_attempt", refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_returned_release_waits_for_live_children_and_stopped_cascades(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w1")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w2")
        refused = self.release_worker(worker_id="14:1:1:w1", event="returned",
                                      now="2026-08-13T20:03:00Z", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("14:1:1:w2", refused.stderr)
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="stopped",
                                now="2026-08-13T20:03:00Z"),
            {"worker_id": "14:1:1:w1", "release_event": "stopped",
             "released": ["14:1:1:w1", "14:1:1:w2", "14:1:1:w3"]})
        for worker in ("14:1:1:w1", "14:1:1:w2", "14:1:1:w3"):
            self.assertEqual(self.check_worker(worker)["reason"], "released")
        self.assertEqual(
            {w["released_at"] for w in self.read_state()["workers"]},
            {"2026-08-13T20:03:00Z"})
        before = self.state_path.read_bytes()
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="stopped",
                                now="2026-08-13T20:04:00Z")["released"], [])
        self.assertEqual(self.state_path.read_bytes(), before)
        conflict = self.release_worker(worker_id="14:1:1:w2", event="returned",
                                       now="2026-08-13T20:04:00Z", ok=False)
        self.assertEqual(conflict.returncode, 2)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_a_returned_child_lets_its_parent_return(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z",
                             parent="14:1:1:w1")
        self.release_worker(worker_id="14:1:1:w2", event="returned",
                            now="2026-08-13T20:02:00Z")
        self.assertEqual(
            self.release_worker(worker_id="14:1:1:w1", event="returned",
                                now="2026-08-13T20:02:00Z")["released"],
            ["14:1:1:w1"])

    def test_a_resume_after_an_unavailable_owner_fences_its_workers(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"),
                              now="2026-08-13T20:06:00Z", owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        self.assertEqual(self.check_worker("14:1:1:w1"), {
            "worker_id": "14:1:1:w1", "live": False,
            "current_action_id": "14:1:2", "reason": "superseded_launch"})
        self.assertIsNone(self.read_state()["workers"][0]["released_at"])
        self.assertEqual(
            self.register_worker(action_id="14:1:2",
                                 now="2026-08-13T20:07:00Z")["worker_id"],
            "14:1:2:w1")
        refused = self.register_worker(action_id="14:1:1", now="2026-08-13T20:07:00Z",
                                       parent="14:1:1:w1", ok=False)
        self.assertEqual(refused.returncode, 2)

    def test_check_worker_answers_an_unknown_run_without_creating_anything(self):
        inventory = sorted(self.root.rglob("*"))
        self.assertEqual(self.check_worker("14:1:1:w1"), {
            "worker_id": "14:1:1:w1", "live": False,
            "current_action_id": None, "reason": "unknown_run"})
        self.assertEqual(sorted(self.root.rglob("*")), inventory)
        malformed = self.check_worker_raw("14:1:1:w0", ok=False)
        self.assertEqual((malformed.returncode, malformed.stdout), (2, ""))

    def test_a_schema_four_ledger_reads_unlocked_and_upgrades_on_first_write(self):
        self.spawn_14()
        legacy = self._as_legacy(self.read_state(), 4)
        self.assertNotIn("workers", legacy)
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_worker("14:1:1:w1")["reason"], "unknown_worker")
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"], "current")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        upgraded = self.read_state()
        self.assertEqual(upgraded["schema_version"], 5)
        self.assertEqual([w["worker_id"] for w in upgraded["workers"]], ["14:1:1:w1"])
        hybrid = self._as_legacy(upgraded, 4)
        hybrid["workers"] = []
        self.write_state(hybrid)
        self.assertEqual(self.check_worker_raw("14:1:1:w1", ok=False).returncode, 2)

    def test_the_validator_closes_every_worker_record(self):
        self.spawn_14()
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z",
                             parent="14:1:1:w1")
        valid = self.read_state()

        def edited(**fields_by_index):
            value = copy.deepcopy(valid)
            for index, fields in fields_by_index.items():
                value["workers"][int(index[1:])].update(fields)
            return value

        cases = {
            "not a list": self._changed(valid, ("workers",), {}),
            "extra field": edited(w0={"note": "x"}),
            "zero ordinal": edited(w0={"worker_id": "14:1:1:w0"}),
            "id outside its launch": edited(w0={"launch": "14:1:2"}),
            "unknown launch": edited(w0={"worker_id": "14:1:9:w1", "launch": "14:1:9"},
                                     w1={"parent": None}),
            "ordinal gap": edited(w1={"worker_id": "14:1:1:w3"}),
            "parent not earlier": edited(w0={"parent": "14:1:1:w2"}),
            "release time without event": edited(
                w1={"released_at": "2026-08-13T20:02:00Z"}),
            "event without release time": edited(w1={"release_event": "returned"}),
            "unknown event": edited(
                w1={"released_at": "2026-08-13T20:02:00Z", "release_event": "vanished"}),
            "registered after update": edited(w0={"registered_at": "2099-01-01T00:00:00Z"}),
            "released before registered": edited(
                w1={"released_at": "2026-08-13T20:01:30Z", "release_event": "returned"}),
            "stopped with an unreleased child": edited(
                w0={"released_at": "2026-08-13T20:02:00Z", "release_event": "stopped"}),
        }
        for name, state in cases.items():
            with self.subTest(name):
                self.write_state(state)
                refused = self.check_worker_raw("14:1:1:w1", ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, ""))
```

Update the schema literals that the bump changes: `test_workflow_state.py` (the `schema_version` assertions near the former lines 2371, 5293, 5314–5316 and 5341), `test_delivery_workflow.py` (near 263, 276–277 and 3090) and `test_host_admission.py` (line 234). Each asserts `5` and, where it compares a whole migrated document, expects `"workers": []`. The `expected_state` documents near `test_workflow_state.py` 2767 and 2814 are expected **output** compared against newly written state, not migration inputs: they become `"schema_version": 5` with `"workers": []`. Every legacy fixture builder that derives an older schema from `new_run_state` (for example `legacy()` near `test_delivery_workflow.py` 139) also pops `"workers"`, so a derived v1–v4 document never carries the v5 member and the `invalid schema-four workers` refusal fires only where a test asks for it. Only the fixtures that **write** a raw `"schema_version": 4` document as migration input (near `test_delivery_workflow.py` 2254–2266) stay at 4; they must keep migrating. Before Step 4, `grep -n '"schema_version": [1-4]\|new_run_state' ` over the three test modules and classify each hit as expected output (bump to 5) or legacy input (keep, and strip `workers`). This step's scope is those schema literals and legacy builders, nothing else.

- [ ] **Step 2: Run the tests and watch them fail**

Run (from the worktree root): `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k WorkerRegistry 2>&1 | tail -3`
Expected: FAIL. argparse rejects `register-worker` (`invalid choice`).

- [ ] **Step 3: Implement**

1. In `workflow-state.py`, set `SCHEMA_VERSION = 5`, add `"workers"` to `STATE_FIELDS`, add the three constants above, and set `"workers": []` in `new_run_state`.
2. In `workflow_delivery.py` `migrate`, the loop target becomes 5 and the docstring says `1→2→3→4→5`. Add a `version == 4` step: raise `ValueError("invalid schema-four workers")` if `"workers" in candidate`, else set `candidate["workers"] = []` and `candidate["schema_version"] = 5`. Accept `4` in the supported-version set. In `migrate_1_to_2`, also `candidate.pop("workers", None)`.
3. `read_state_unlocked` migrates `{1, 2, 3, 4}` on a detached copy, and its docstring says "Schemas 1–4".
4. Add `validate_workers(value)` with every invariant above, and call it from `validate_state` after the issue loop. Raise `WorkflowError("invalid workflow workers")` (with a short detail) on any breach.
5. Extract `launch_verdict` from `command_check_launch` by moving the reason computation unchanged, then add `worker_verdict` and `live_worker_ids`.
6. `command_register_worker(args)`: validate `run_id` and the action id, then run `transact`. Inside the mutation, refuse (raise) unless `launch_verdict(...)[1] == "current"`, naming the reason in the message. Refuse a `--parent` that does not match the pattern, is absent, belongs to another launch, or whose `worker_verdict` is not `live`. Refuse when `now < updated_at`. The ordinal is the launch's record count plus 1. Append the record, set `updated_at = now`, and return `{"worker_id", "launch", "parent"}`.
7. `command_release_worker(args)`: inside `transact`, refuse an unknown id. A repeat with the same event returns `(reply with released=[], False)`. A different event on a released record is refused as `conflicting release`. For `returned`, refuse (naming the ids) while any record with `parent == id` is `live`. For `stopped`, release the record and every unreleased transitive descendant at `now` with event `stopped`. Release ignores whether the launch is current. Reply as D12 says.
8. `command_check_worker(args)` follows `command_check_launch`'s read-only shape: validate `run_id`, parse the id **before** touching the ledger (a malformed id exits 2), map a missing `state.json` to `unknown_run`, and print exactly `{"worker_id", "live", "current_action_id", "reason"}`.
9. Register the three subparsers. `register-worker` takes `--repo-root --run-id --now --action-id [--parent]` (use `add_run_arguments`). `release-worker` takes `--repo-root --run-id --now --worker-id --event {returned,stopped}`. `check-worker` takes `--repo-root --run-id --worker-id`, with no `--now`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -3`
Expected: `OK`. At the base commit, `-k WorkerRegistry` fails (the gate can fail).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py
git commit -m "feat(workflow-state): schema v5 worker registry with register, release and check-worker (#222)"
```

Decisions: per D2, D3, D8, D10, D12.
