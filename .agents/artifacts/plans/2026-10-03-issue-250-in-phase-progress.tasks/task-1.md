# Task 1: Ledger schema 6 — `progress_marker` and the 5→6 migration

Lane: full (ledger migration). Decisions: per D4 of the spec's ledger.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Test: `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Task 2 relies on these exact names):
  - `SCHEMA_VERSION = 6` in `workflow-state.py`.
  - Attempt field `progress_marker`: `None` or a `str` matching
    `PROGRESS_MARKER_PATTERN`, a module constant
    `re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")` used with `fullmatch`.
  - `new_control_attempt(...)` returns an attempt with `"progress_marker": None`.
  - `LifecycleHarness._as_legacy(state, version)` removes `progress_marker`
    from every attempt when `version < 6`.

**Invariants:**
- A schema-5 ledger migrates by gaining `progress_marker: null` on every
  attempt of every issue and nothing else: `suspend_phase` and
  `stalled_resumes` keep their stored values.
- A schema-5 document in which any attempt already has a `progress_marker` key
  is refused; nothing is written.
- `validate_attempt` refuses a missing `progress_marker` key and every value
  other than `None` or a 40- or 64-character lowercase hexadecimal string.
- `read_state_unlocked` accepts schema 5 without writing; the first locked
  write persists schema 6.
- The delivery remainder record's keys and validation are unchanged.

## Steps

- [ ] **Step 1: Write the failing tests**

Append this class to `home/common/agent-skills/tests/test_workflow_state.py`,
directly after `WorkerRegistryTest` (before `class OwnerExitFenceTest`):

```python
class ProgressMarkerSchemaTest(LifecycleHarness, unittest.TestCase):
    """#250 D4: schema 6 gives every attempt a nullable `progress_marker`."""

    def spawn_16(self):
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=10)

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def with_marker(self, state, marker):
        value = copy.deepcopy(state)
        value["issues"]["16"]["attempts"][0]["progress_marker"] = marker
        return value

    def assert_refused_unchanged(self, state):
        self.write_state(state)
        before = self.state_path.read_bytes()
        refused = self.check_launch_raw(action_id="16:1:1", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_a_new_attempt_starts_with_a_null_marker_at_schema_six(self):
        self.spawn_16()
        self.assertEqual(self.read_state()["schema_version"], 6)
        self.assertIsNone(self.attempt()["progress_marker"])

    def test_a_schema_five_ledger_keeps_its_stall_count_and_upgrades_on_first_write(self):
        self.spawn_16()
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:02:00Z")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:03:00Z")
        self.assertEqual(self.attempt()["stalled_resumes"], 1)
        legacy = self._as_legacy(self.read_state(), 5)
        self.assertEqual(legacy["schema_version"], 5)
        self.assertNotIn("progress_marker", legacy["issues"]["16"]["attempts"][0])
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="16:1:2")["reason"],
                         "inactive_attempt")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:04:00Z")
        upgraded = self.read_state()
        attempt = upgraded["issues"]["16"]["attempts"][0]
        self.assertEqual(
            (upgraded["schema_version"], attempt["progress_marker"],
             attempt["stalled_resumes"], attempt["suspend_phase"]),
            (6, None, 1, 0))

    def test_a_schema_five_hybrid_is_refused_without_a_write(self):
        self.spawn_16()
        hybrid = self._as_legacy(self.read_state(), 5)
        hybrid["issues"]["16"]["attempts"][0]["progress_marker"] = None
        self.assert_refused_unchanged(hybrid)
        before = self.state_path.read_bytes()
        refused = self.suspend(issue=16, attempt=1, blocked_on="external",
                               now="2026-08-13T20:02:00Z", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_the_validator_closes_the_marker(self):
        self.spawn_16()
        valid = self.read_state()
        for marker in ("a" * 40, "0123456789abcdef" * 4):
            with self.subTest(accepted=marker):
                self.write_state(self.with_marker(valid, marker))
                self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                                 "current")
        rejected = {
            "abbreviated": "abc1234", "uppercase": "A" * 40, "41 characters": "a" * 41,
            "63 characters": "a" * 63, "not hexadecimal": "g" * 40, "empty": "",
            "trailing newline": "a" * 40 + "\n", "integer": 7, "boolean": True,
        }
        for label, marker in rejected.items():
            with self.subTest(rejected=label):
                self.assert_refused_unchanged(self.with_marker(valid, marker))
        missing = copy.deepcopy(valid)
        del missing["issues"]["16"]["attempts"][0]["progress_marker"]
        self.assert_refused_unchanged(missing)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ProgressMarkerSchemaTest 2>&1 | tail -15`

Expected: a non-zero exit status (`pipefail` carries the runner's failure
past `tail`) and 4 tests, all failing or erroring — the first with `5 != 6`, the
others with `KeyError: 'progress_marker'` or a `0 != 2` return code. (At the
starting commit the class does not exist and the same command prints
`NO TESTS RAN`.)

- [ ] **Step 3: Implement the schema step**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. `SCHEMA_VERSION = 6`.
2. Add `"progress_marker"` to `ATTEMPT_FIELDS`. Do **not** add it to
   `SUSPENSION_DEFAULTS`: that mapping is also the list of fields the
   schema-1 legacy builders strip, and the marker is not a suspension field.
3. Next to `MERGE_SHA_PATTERN`, add the constant with a one-line comment
   saying why two lengths exist (SHA-1 and SHA-256 object formats, #250 D4):
   `PROGRESS_MARKER_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")`.
4. In `new_control_attempt`, add `"progress_marker": None` to the returned
   attempt (beside `**SUSPENSION_DEFAULTS`).
5. In `validate_attempt`, directly after the `stalled_resumes` check, refuse
   with `WorkflowError("invalid attempt progress marker")` unless the value is
   `None` or (`type(value) is str` and
   `PROGRESS_MARKER_PATTERN.fullmatch(value)`). `fullmatch`, not `match`: a
   trailing newline must not validate.
6. In `read_state_unlocked`, widen the legacy set from `{1, 2, 3, 4}` to
   `{1, 2, 3, 4, 5}` and change the docstring's "Schemas 1–4" to
   "Schemas 1–5". The function still returns the document as stored.

In `home/common/agent-skills/scripts/workflow_delivery.py`, method `migrate`:

1. Docstring: "Compose schema 1→2→3→4→5→6 …".
2. The loop runs while `schema_version != 6`; the accepted set becomes
   `{1, 2, 3, 4, 5}`.
3. Add a `version == 5` branch ahead of the `version == 4` branch. It walks
   `issues.values()`, and for every `dict` issue whose `attempts` is a `list`,
   every `dict` attempt: if `"progress_marker" in attempt`, raise
   `ValueError("invalid schema-five progress marker")`; otherwise set
   `attempt["progress_marker"] = None`. Then `candidate["schema_version"] = 6`.
   Guard the shapes with `isinstance` exactly as the `version == 1` branch
   does — a malformed issue is the validator's to refuse, not the migration's
   to crash on. Comment the branch like its neighbours: schema 6 adds the
   attempt's progress marker (#250 D4); a schema-5 document that already
   carries one is a hybrid.

- [ ] **Step 4: Bring the existing suites to schema 6**

These edits are required because the validator is exact-key; each is a
fixture or a version literal, never a behaviour change.

In `home/common/agent-skills/tests/test_workflow_state.py`:

- `LifecycleHarness._as_legacy`: before the existing `if version < 5:` line add

  ```python
          if version < 6:
              for issue in state["issues"].values():
                  for attempt in issue["attempts"]:
                      attempt.pop("progress_marker", None)
  ```

- Every assertion that the current schema is `5` becomes `6`: the
  `assertEqual(..., 5)` lines in
  `test_legacy_expiry_record_stays_provisional_until_the_owner_reports`,
  `test_schema_one_migrates_through_two_and_three_to_four_with_one_atomic_write`,
  `test_schema_one_and_two_mutations_write_only_final_schema_four_once`
  (three literals), `test_legacy_terminal_and_active_rows_migrate_byte_exact`,
  `test_register_assigns_dense_ordinals_and_check_worker_reads_live` and
  `test_a_schema_four_ledger_reads_unlocked_and_upgrades_on_first_write`. Find
  them with `grep -n '"schema_version"\], 5)' home/common/agent-skills/tests/*.py`
  and `grep -n '"schema_version": 5' home/common/agent-skills/tests/*.py`.
- The two hand-written expected states (`"schema_version": 5, "run_id": …`, in
  `test_non_direct_phase_order_and_ledger_bytes_remain_exact` and
  `test_zero_sequence_direct_shaped_dispatcher_keeps_non_direct_progress_and_reopen_bytes`)
  become `6`, and their `expected_attempt` dictionaries gain
  `"progress_marker": None`.
- `test_legacy_terminal_and_active_rows_migrate_byte_exact` compares each
  migrated issue's `attempts` with the schema-2 rows. After this change the
  migrated attempts carry the new key. Keep the byte-exact claim for every
  legacy field: assert each migrated attempt's `progress_marker` is `None`,
  then compare the attempt with that one key removed against the legacy row.

In `home/common/agent-skills/tests/test_delivery_workflow.py`:

- `legacy(self, version)` and `test_v1_owners_survive_the_migration_to_interface_two`
  build pre-schema-6 states from `new_run_state` / `new_control_attempt`; each
  must also drop `progress_marker` from the attempts it writes.
- `write_run(self, run_id, attempts, *, schema=5)`: the default becomes `6`,
  and for `schema < 6` it removes `progress_marker` from each attempt it was
  handed (on a copy; do not mutate the caller's list).
- The four `schema_version` assertions equal to `5` become `6`.

In `home/common/agent-skills/tests/test_host_admission.py`:
`test_schema_three_reads_migrate_to_a_null_admission` expects `(6, None)`.

Then run the whole recipe and fix only failures of these three kinds (a
version literal, a hand-built attempt missing the key, a legacy fixture
carrying the key). Any other failure is a defect in Step 3; fix it there.

- [ ] **Step 5: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ProgressMarkerSchemaTest 2>&1 | tail -4`
Expected: `Ran 4 tests`, `OK`.

Run: `set -o pipefail; just agent-workflow-tests 2>&1 | tail -6`
Expected: `OK` with no failures or errors. On a failure, re-run only the
failing test id and read its last 30 lines.

Run:
```bash
if grep -nE '\{1, 2, 3, 4\}' home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py; then exit 1; fi
```
Expected: no output, exit 0 (no reader still stops at schema 4).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/workflow_delivery.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_delivery_workflow.py \
  home/common/agent-skills/tests/test_host_admission.py
git commit -m "feat(workflow-state): ledger schema 6 adds the attempt progress marker (#250)"
```

The message ends with the co-author trailer from the plan's Global Constraints.
