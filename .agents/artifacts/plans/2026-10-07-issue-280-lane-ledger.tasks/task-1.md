# Task 1: Ledger schema 7 — lane fields, validator, defaults, migration

Per D3 and D5. Spec section "Schema 7".

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify (fixtures only): `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes: the existing `parse_utc`, `require_plain_int(value, label, *, minimum=0)`, `validate_attempt`, `new_control_attempt` and `DeliveryRuntime.migrate`.
- Produces (Task 2 relies on these exact names in `workflow-state.py`):
  - `SCHEMA_VERSION = 7`
  - `LANES = frozenset({"light", "full"})`
  - `LANE_HISTORY_FIELDS = frozenset({"lane", "reason", "at"})`
  - `LANE_TRANSITION_REASONS: dict[tuple[str | None, str], frozenset[str]]`, exactly `{(None, "light"): {"triage"}, (None, "full"): {"triage"}, ("light", "full"): {"important_finding", "second_fix_round", "light_deadline", "unpredicted_risk"}}` (D2). There are no other keys.
  - `LANE_REASONS = frozenset().union(*LANE_TRANSITION_REASONS.values())`
  - `LANE_DEFAULTS = {"lane": None, "lane_budget_minutes": None, "lane_history": []}`. Spread a fresh copy with `copy.deepcopy`, or build the list inline, so that no two attempts share one list object.
  - `ATTEMPT_FIELDS` gains `"lane"`, `"lane_budget_minutes"` and `"lane_history"`.
- Test harness: `LifecycleHarness._as_legacy(state, version)` drops the three lane fields when `version < 7`.

**Invariants:**
- A ledger loads only when `lane is None` ⇔ `lane_budget_minutes is None` ⇔ `lane_history == []`.
- When set, `lane_budget_minutes` is a plain `int` ≥ 1, and `True` is rejected.
- Every history entry has exactly the keys `{lane, reason, at}`, a lane in `LANES`, and a reason in `LANE_TRANSITION_REASONS[(previous_lane, lane)]`, where `previous_lane` starts at `None`. A pair absent from the table is rejected. Each `at` parses as UTC, is ≥ `started_at`, and is ≥ the previous entry's `at`.
- The last entry's `lane` equals the attempt's `lane`.
- Every attempt that `new_control_attempt` creates, fresh or retry, carries `None`, `None`, `[]` (D5).
- `migrate` turns a schema-6 document into schema 7 by adding `None`, `None`, `[]` to every attempt. A schema-6 attempt that already carries any of the three keys raises `ValueError`, so nothing is written.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, first extend `LifecycleHarness._as_legacy` with this block, placed before the existing `if version < 6:` block:

```python
        if version < 7:
            for issue in state["issues"].values():
                for attempt in issue["attempts"]:
                    for field in ("lane", "lane_budget_minutes", "lane_history"):
                        attempt.pop(field, None)
```

Then add this class directly after `ProgressMarkerSchemaTest`:

```python
class LaneSchemaTest(LifecycleHarness, unittest.TestCase):
    """#280 D3, D5: schema 7 gives every attempt a lane, a lane budget and a lane history."""

    LATER = "2026-08-13T20:05:00Z"
    ESCALATIONS = ("important_finding", "second_fix_round", "light_deadline",
                   "unpredicted_risk")

    def spawn_16(self):
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=240)

    def attempt(self):
        return self.read_state()["issues"]["16"]["attempts"][-1]

    def lane_of(self, attempt):
        return (attempt["lane"], attempt["lane_budget_minutes"], attempt["lane_history"])

    @staticmethod
    def with_lane(state, lane, budget, history):
        value = copy.deepcopy(state)
        value["issues"]["16"]["attempts"][0].update(
            lane=lane, lane_budget_minutes=budget, lane_history=history)
        return value

    def assert_refused_unchanged(self, state):
        self.write_state(state)
        before = self.state_path.read_bytes()
        refused = self.check_launch_raw(action_id="16:1:1", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_a_new_attempt_starts_without_a_lane_at_schema_seven(self):
        self.spawn_16()
        self.assertEqual(self.read_state()["schema_version"], 7)
        self.assertEqual(self.lane_of(self.attempt()), (None, None, []))

    def test_a_retry_attempt_does_not_inherit_its_predecessors_lane(self):
        self.spawn_16()
        self.write_state(self.with_lane(
            self.read_state(), "light", 90,
            [{"lane": "light", "reason": "triage", "at": DEFAULT_NOW}]))
        self.fail_owner(issue=16, attempt=1, now="2026-08-13T20:01:00Z")
        self.retry(issue=16, worktree=self.root / "wt-16b", now="2026-08-13T20:10:00Z")
        issue = self.read_state()["issues"]["16"]
        self.assertEqual(self.lane_of(issue["attempts"][0])[0], "light")
        self.assertEqual(self.lane_of(issue["attempts"][1]), (None, None, []))

    def test_a_schema_six_ledger_migrates_with_null_lane_fields(self):
        self.spawn_16()
        legacy = self._as_legacy(self.read_state(), 6)
        self.assertEqual(legacy["schema_version"], 6)
        for field in ("lane", "lane_budget_minutes", "lane_history"):
            self.assertNotIn(field, legacy["issues"]["16"]["attempts"][0])
        self.write_state(legacy)
        before = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="16:1:1")["reason"], "current")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        upgraded = self.read_state()
        self.assertEqual(
            (upgraded["schema_version"],
             self.lane_of(upgraded["issues"]["16"]["attempts"][0])),
            (7, (None, None, [])))

    def test_a_schema_six_hybrid_is_refused_without_a_write(self):
        self.spawn_16()
        valid = self.read_state()
        for field, value in (("lane", None), ("lane_budget_minutes", None),
                             ("lane_history", [])):
            with self.subTest(field=field):
                hybrid = self._as_legacy(valid, 6)
                hybrid["issues"]["16"]["attempts"][0][field] = value
                self.assert_refused_unchanged(hybrid)

    def test_the_validator_closes_the_lane_fields(self):
        self.spawn_16()
        valid = self.read_state()
        light = {"lane": "light", "reason": "triage", "at": DEFAULT_NOW}
        full = {"lane": "full", "reason": "triage", "at": DEFAULT_NOW}
        accepted = {"light": ("light", 90, [light]), "full": ("full", 240, [full])}
        for reason in self.ESCALATIONS:
            accepted[f"escalated by {reason}"] = ("full", 240, [
                light, {"lane": "full", "reason": reason, "at": self.LATER}])
        for label, lane in accepted.items():
            with self.subTest(accepted=label):
                self.write_state(self.with_lane(valid, *lane))
                self.assertEqual(self.check_launch(action_id="16:1:1")["reason"],
                                 "current")
        escalated = {"lane": "full", "reason": "important_finding", "at": self.LATER}
        rejected = {
            "lane without a budget": ("light", None, [light]),
            "budget without a lane": (None, 90, []),
            "lane without a history": ("light", 90, []),
            "history without a lane": (None, None, [light]),
            "unknown lane": ("medium", 90, [{**light, "lane": "medium"}]),
            "last entry disagrees with the lane": ("full", 90, [light]),
            "zero budget": ("light", 0, [light]),
            "boolean budget": ("light", True, [light]),
            "string budget": ("light", "90", [light]),
            "history that is not a list": ("light", 90, {"0": light}),
            "entry with an extra key": ("light", 90, [{**light, "note": "x"}]),
            "entry missing its time": ("light", 90, [{"lane": "light", "reason": "triage"}]),
            "unknown reason": ("light", 90, [{**light, "reason": "whim"}]),
            "escalation reason on a first entry": (
                "light", 90, [{**light, "reason": "important_finding"}]),
            "triage on an escalation": ("full", 240, [light, {**escalated, "reason": "triage"}]),
            "full to light": ("light", 90, [full, {**light, "at": self.LATER}]),
            "light to light": ("light", 90, [light, {**escalated, "lane": "light"}]),
            "full to full": ("full", 240, [full, escalated]),
            "time moving backward": ("full", 240, [
                {**light, "at": self.LATER}, {**escalated, "at": DEFAULT_NOW}]),
            "entry before the attempt started": (
                "light", 90, [{**light, "at": "2026-08-13T19:59:59Z"}]),
            "unparseable time": ("light", 90, [{**light, "at": "yesterday"}]),
        }
        for label, lane in rejected.items():
            with self.subTest(rejected=label):
                self.assert_refused_unchanged(self.with_lane(valid, *lane))
        for field in ("lane", "lane_budget_minutes", "lane_history"):
            with self.subTest(missing=field):
                missing = copy.deepcopy(valid)
                del missing["issues"]["16"]["attempts"][0][field]
                self.assert_refused_unchanged(missing)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest -k LaneSchemaTest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -5`
Expected: FAILED. The schema assertions read `6` instead of `7`, and `KeyError: 'lane'` is raised.

- [ ] **Step 3: Implement schema 7**

In `workflow-state.py`:
1. Set `SCHEMA_VERSION = 7`. Add the constants listed under **Produces**, add the three names to `ATTEMPT_FIELDS`, and in `new_control_attempt` add `"lane": None, "lane_budget_minutes": None, "lane_history": []` after `"progress_marker": None`.
2. Add `validate_attempt_lane(value: dict[str, Any], *, started_at: datetime) -> None` and call it from `validate_attempt` after the progress-marker check. It checks, in this order:
   1. `lane_history` is a `list`.
   2. It walks the history with `previous = None` and `previous_at = started_at`. Each entry must be a `dict` with `set(entry) == LANE_HISTORY_FIELDS` and `entry["lane"] in LANES`. Its reason must be in `LANE_TRANSITION_REASONS.get((previous, entry["lane"]), frozenset())`; this check raises `"invalid attempt lane transition"`. Then `at = parse_utc(entry["at"], "lane history time")` must be ≥ `previous_at`. Then `previous, previous_at = entry["lane"], at`.
   3. `value["lane"] != previous` raises `"attempt lane does not match its history"`. Because `previous` is `None` exactly when the history is empty, this check also covers lane ⇔ history.
   4. `(value["lane"] is None) != (value["lane_budget_minutes"] is None)` raises. A set budget passes `require_plain_int(..., "attempt lane budget", minimum=1)`.

   Every failure raises `WorkflowError`. Check `isinstance(entry["lane"], str)` before testing membership, so that an unhashable value fails closed with `WorkflowError` and not `TypeError`.
3. In the legacy-reader branch near line 3745, change `{1, 2, 3, 4, 5}` to `{1, 2, 3, 4, 5, 6}`, and change the docstring's "1–5" to "1–6".
4. In `command_mark_progress`'s docstring, change "a pre-schema-6 ledger is persisted at schema 6" to "a pre-schema-6 ledger is persisted at the current schema".

In `workflow_delivery.py`, `DeliveryRuntime.migrate`:
- Change the docstring to `1→2→3→4→5→6→7`, the loop condition to `!= 7`, and the accepted set to `{1, 2, 3, 4, 5, 6}`.
- Insert a `version == 6` branch ahead of the `version == 5` branch. Make `version == 5` an `elif`, and keep the rest of the chain unchanged:

```python
            if version == 6:
                # Schema 7 adds the attempt's lane (#280 D3); a schema-6 attempt
                # that already carries any lane field is a hybrid.
                for issue in issues.values():
                    if isinstance(issue, dict) and isinstance(issue.get("attempts"), list):
                        for attempt in issue["attempts"]:
                            if isinstance(attempt, dict):
                                if {"lane", "lane_budget_minutes", "lane_history"} & set(attempt):
                                    raise ValueError("invalid schema-six lane")
                                attempt.update(lane=None, lane_budget_minutes=None,
                                               lane_history=[])
                candidate["schema_version"] = 7
```

- [ ] **Step 4: Move every existing fixture to schema 7 (mechanical)**

These changes are fixtures only, with no change to any test's intent:
- `test_workflow_state.py`:
  - Every assertion that the current schema is `6` becomes `7`. Today these are near lines 2448, 5371, 5392, 5394, 5419, 6297, 6413 and 6490, plus the `6` in the expected tuple of `test_a_schema_five_ledger_keeps_its_stall_count_and_upgrades_on_first_write`.
  - The two hand-built expected ledgers near lines 2841 and 2889 get `"schema_version": 7` and `"lane": None, "lane_budget_minutes": None, "lane_history": []`.
  - Tests that build a schema-5 document by popping `progress_marker` themselves also pop the three lane fields. Otherwise the new `6 → 7` step reads them as a hybrid.
- `test_delivery_workflow.py`: near 145, 2122 and 3234, the schema-5 builders also pop the three lane fields. The current-schema assertions near 264–284 and 3241 become `7`. `write_run(..., schema=6)` becomes `schema=7`, with an `if schema < 7:` filter that drops the three lane fields, placed ahead of the existing `schema < 6` filter.
- `test_host_admission.py`: line 234 expects `(7, None)`.

Find any others with `grep -n 'schema_version.*6\|progress_marker' <file>` and the failing-test list from Step 5. Leave `tests/test_eval_cases.py` alone unless it fails.

- [ ] **Step 5: Verify**

Run each command and report only the summary line and any failures:
- `PYTHONPATH=python timeout 900 python3 -m unittest -k LaneSchemaTest -k ProgressMarkerSchemaTest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3`. Expected: `OK`.
- `PYTHONPATH=python timeout 1800 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_workflow_delivery.py 2>&1 | tail -3`. Expected: `OK`.
- `cd home/common/agent-skills/scripts && if grep -n 'get("schema_version") != 6' workflow_delivery.py; then exit 1; fi`. Expected: no output, exit 0. At the base commit this prints the loop line, so the check can fail.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(workflow-state): ledger schema 7 with attempt lane fields (#280)"
```
