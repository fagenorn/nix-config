# Task 2: `owner_liveness` reply at the workflow-response boundary

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Test: `home/common/agent-skills/tests/test_delivery_model.py` (new `OwnerLivenessResponseTest`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `validate_delivery_object(value, expected_kind="workflow-response", …)` accepts the closed `owner_liveness` reply below and rejects every shape the invariants exclude. Task 3's verb prints this reply, and Task 5's adapter validates it through `artifact-budget validate-report --boundary workflow-response`.
- Produces, in `_wire.py`: `_LAUNCH_REASONS`, a module-level `frozenset` of the seven `check-launch` reasons (`unknown_run`, `unknown_issue`, `unknown_attempt`, `superseded_attempt`, `inactive_attempt`, `superseded_launch`, `current`), used by the existing `check-launch` branch of `_workflow_response` and by `_owner_liveness`. One home for that set (the-bar DRY).

**Invariants (D3, D4, D5, D10):**
- Members are exactly `interface_version`, `kind`, `action_id`, `reason`, `verdict`, `since`, `progress_at`, `stall_at`, `wait_seconds`. `interface_version` is the integer `1` (not `True`, not `1.0`). `kind` is `"owner_liveness"`. `action_id` is a non-empty string. `reason` is in `_LAUNCH_REASONS`. `verdict` is one of `live`, `stalled`, `past_deadline`, `not_current`. `since` is a whole-second UTC timestamp (`_utc`).
- `verdict == "not_current"` exactly when `reason != "current"`.
- For `not_current`: `progress_at`, `stall_at` and `wait_seconds` are all `None`.
- Otherwise `progress_at` and `stall_at` are whole-second UTC timestamps, and `stall_at − max(progress_at, since)` is a positive whole number of minutes (a positive multiple of 60 seconds).
- `wait_seconds` is an integer ≥ 1 (not a boolean) when `verdict == "live"`, and `None` for every other verdict. Its value is not checked against any clock (the validator has none).
- The existing `check-launch` branch behaves exactly as before.

- [ ] **Step 1: Write the failing test**

Append to `test_delivery_model.py`:

```python
class OwnerLivenessResponseTest(unittest.TestCase):
    """#310 D5, D10: the closed `owner_liveness` reply at the workflow-response boundary."""

    LIVE = {"interface_version": 1, "kind": "owner_liveness", "action_id": "14:1:1",
            "reason": "current", "verdict": "live", "since": "2026-08-13T20:10:00Z",
            "progress_at": "2026-08-13T20:00:00Z", "stall_at": "2026-08-13T20:40:00Z",
            "wait_seconds": 1800}

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_owner_liveness_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def changed(self, **members):
        value = copy.deepcopy(self.LIVE)
        value.update(members)
        return value

    def accepted(self):
        return {
            "live": self.LIVE,
            "live_progress_later": self.changed(
                progress_at="2026-08-13T20:20:00Z", stall_at="2026-08-13T20:50:00Z"),
            "stalled": self.changed(verdict="stalled", wait_seconds=None),
            "past_deadline": self.changed(verdict="past_deadline", wait_seconds=None),
            "not_current": self.changed(reason="superseded_launch", verdict="not_current",
                                        progress_at=None, stall_at=None, wait_seconds=None),
            "unknown_run": self.changed(reason="unknown_run", verdict="not_current",
                                        progress_at=None, stall_at=None, wait_seconds=None),
        }

    def test_each_verdict_shape_is_accepted_unchanged(self):
        for name, value in self.accepted().items():
            with self.subTest(name=name):
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_every_broken_invariant_is_rejected(self):
        missing = copy.deepcopy(self.LIVE)
        del missing["since"]
        rejected = {
            "extra_member": self.changed(now="2026-08-13T20:10:00Z"),
            "missing_member": missing,
            "version_two": self.changed(interface_version=2),
            "version_bool": self.changed(interface_version=True),
            "unknown_reason": self.changed(reason="late"),
            "unknown_verdict": self.changed(verdict="dead"),
            "empty_action": self.changed(action_id=""),
            "fractional_since": self.changed(since="2026-08-13T20:10:00.5Z"),
            "current_but_not_current": self.changed(verdict="not_current", progress_at=None,
                                                    stall_at=None, wait_seconds=None),
            "superseded_but_live": self.changed(reason="superseded_launch"),
            "not_current_with_times": self.changed(reason="superseded_launch",
                                                   verdict="not_current", wait_seconds=None),
            "live_without_progress": self.changed(progress_at=None),
            "stall_not_whole_minutes": self.changed(stall_at="2026-08-13T20:40:30Z"),
            "stall_before_since": self.changed(stall_at="2026-08-13T20:09:00Z",
                                               progress_at="2026-08-13T19:00:00Z"),
            "stall_at_base": self.changed(stall_at="2026-08-13T20:10:00Z"),
            "stall_before_base": self.changed(stall_at="2026-08-13T20:05:00Z"),
            "live_zero_wait": self.changed(wait_seconds=0),
            "live_bool_wait": self.changed(wait_seconds=True),
            "live_null_wait": self.changed(wait_seconds=None),
            "stalled_with_wait": self.changed(verdict="stalled"),
            "past_deadline_with_wait": self.changed(verdict="past_deadline"),
        }
        for name, value in rejected.items():
            with self.subTest(name=name):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.validate(value)

    def test_the_check_launch_reply_is_unchanged(self):
        reply = {"action_id": "14:1:1", "current": True, "current_action_id": "14:1:1",
                 "reason": "current"}
        self.assertEqual(self.validate(copy.deepcopy(reply)), reply)
        with self.assertRaises(self.model.DeliveryModelError):
            self.validate({**reply, "reason": "late"})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k OwnerLivenessResponse`
Expected: FAIL. Every accepted shape raises `DeliveryModelError`, because `_workflow_response` has no `owner_liveness` branch.

- [ ] **Step 3: Write the minimal implementation**

In `_wire.py`:
- Add `from datetime import datetime` to the imports.
- Add `_LAUNCH_REASONS` (the seven reasons above) and use it in the `check-launch` branch's reason test, replacing the inline set.
- Add `_owner_liveness(value) -> dict` implementing the invariants in the order listed: `_object` with the exact member set and label `"owner liveness"`, the version check, `_string(value["action_id"], …)`, the two closed sets, `_utc(value["since"], …)`, the `not_current` ⇔ `reason != "current"` check, then either the three-nulls check or `_utc` on both times plus the minutes check, then the `wait_seconds` check (`_integer(…, minimum=1)` for `live`, `is None` otherwise). Parse times with `datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")` after `_utc` has accepted them. The minutes check is `seconds = (stall_at - max(progress_at, since)).total_seconds()`, rejected when `seconds <= 0 or seconds % 60`.
- In `_workflow_response`, add `if value.get("kind") == "owner_liveness": return _owner_liveness(value)` immediately before the `if "kind" not in value: return _control_response(…)` line.
- Reject through `_reject()` everywhere, as the module does.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py`
Expected: PASS, the whole module, including `test_workflow_response_validation_is_structural_only`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(delivery-model): validate the owner_liveness workflow response (#310)"
```
