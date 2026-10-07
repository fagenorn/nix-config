# Task 1: Delivery model — tracker_held grammar and the satisfies-mappings

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_objects.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_reconcile.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/__init__.py`
- Test: `home/common/agent-skills/tests/test_delivery_model.py`

**Interfaces:**
- Consumes: existing `_STAGE_ACTIONS` (stage kind → `(action, effect, primary observation kind)`), `_POSTCONDITIONS`, `_stage_observation_matches`, `_postcondition_observation_matches`, and the `_canonical` helpers `_object`, `_members`, `_string`, `_integer`, `_reject`.
- Produces, in `_objects.py`:
  - `_STAGE_OBSERVATION_KINDS: Mapping[str, frozenset[str]]` (a `MappingProxyType`), derived from `_STAGE_ACTIONS`. Every stage kind maps to `{its tuple's third element}`. `close_tracker` also gets `tracker_held`.
  - `_POSTCONDITION_OBSERVATION_KINDS: Mapping[str, frozenset[str]]` (a `MappingProxyType`). Every postcondition `name` maps to `{name}`. `tracker_closed` also gets `tracker_held`.
  - `OBSERVATION_KINDS: frozenset[str]`, the union of every value of both mappings.
  - `_HOLD_LABEL = "needs-verification"` and `_HOLD_ACCEPTANCE = frozenset({"unmet", "human_pending"})`.
- Produces, in `__init__.py`: the public `delivery_model.OBSERVATION_KINDS`, added to the import line and to `__all__`. Task 2's builder reads it.

**Invariants:**
- `STAGE_ACTIONS["close_tracker"] == ("close_issue", "tracker_write", "tracker_closed")`, and every tuple stays unchanged (D1, D5).
- A `tracker_held` subject has exactly the members `tracker_repository_id`, `issue`, `state`, `label`, `comment_url`, `record_path`, `acceptance_state` and `observation_identity`. Any other member set is rejected (D2).
- In a `tracker_held` subject, `state == "open"`, `label == "needs-verification"` and `acceptance_state ∈ {unmet, human_pending}`. `record_path` is a non-empty string with no leading `/`, no backslash and no `..` segment. `comment_url`, `tracker_repository_id` and `observation_identity` are non-empty strings, and `issue` is an int of at least 1 (D2, D3).
- `close_tracker` and the `tracker_closed` postcondition match a `tracker_held` subject only when it names the contract's repository and issue and its state is `open`. A `tracker_closed` subject still has to be `closed` (D4).
- One delivery holds at most one distinct tracker outcome. A held subject and a closed subject that both match make reduction raise `DeliveryModelError`, through the existing distinct-subject rule (D4).
- The five single-kind checks are: the observation-kind admission, the reducer's stage match, the reducer's postcondition match, the wire stage-fact check and the wire postcondition check. Each reads the mappings, and none keeps a literal kind comparison (D1).

- [ ] **Step 1: Write the failing test**

Append this class to `home/common/agent-skills/tests/test_delivery_model.py`, immediately before its `if __name__ == "__main__":` line. If the file has no such line, append it at the end. Add `cleanup_contract_and_delivery`, `with_observed`, `observation`, `evaluation`, `stage_state` and `post_state` to the `_delivery_model_fixtures` import only if one of them is missing. They are imported today.

```python
class TrackerHeldModelTest(unittest.TestCase):
    """#273 D1-D4: a tracker_held observation satisfies close_tracker and tracker_closed."""

    HELD = {"tracker_repository_id": "sim-repo", "issue": 151, "state": "open",
            "label": "needs-verification",
            "comment_url": "https://sim.invalid/issues/151#issuecomment-1",
            "record_path": ".agents/artifacts/plans/2026-10-07-x.acceptance.md",
            "acceptance_state": "unmet",
            "observation_identity": "github:issue:151:held"}
    CLOSED = {"tracker_repository_id": "sim-repo", "issue": 151, "state": "closed",
              "close_reason": "completed", "observation_identity": "tracker:151:closed"}

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_tracker_held_test")

    def merged(self):
        contract, delivery = cleanup_contract_and_delivery(self.model)
        return contract, with_observed(self.model, contract, delivery,
                                       ["select", "publish", "open", "merge"])

    def reduce_with(self, contract, delivery, *items):
        candidate = copy.deepcopy(delivery)
        candidate["delivery_observations"] = sorted(
            candidate["delivery_observations"] + list(items), key=lambda item: item["id"])
        return self.model.reduce_delivery(contract, candidate, evaluation=evaluation())

    def assert_rejected(self, item):
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.validate_delivery_object(
                item, expected_kind="delivery-observation", notes_max_characters=4096)

    def test_the_observable_set_adds_tracker_held_and_keeps_the_stage_tuple(self):
        self.assertIn("tracker_held", self.model.OBSERVATION_KINDS)
        self.assertIn("tracker_closed", self.model.OBSERVATION_KINDS)
        self.assertEqual(self.model.STAGE_ACTIONS["close_tracker"],
                         ("close_issue", "tracker_write", "tracker_closed"))
        self.assertEqual(
            self.model.OBSERVATION_KINDS - {"tracker_held"},
            {item[2] for item in self.model.STAGE_ACTIONS.values()}
            | {"implementation_delivered", "pr_merged", "tracker_closed", "cleanup_complete"})

    def test_a_held_observation_folds_close_tracker_and_the_postcondition(self):
        contract, delivery = self.merged()
        for acceptance in ("unmet", "human_pending"):
            with self.subTest(acceptance=acceptance):
                held = observation(self.model, contract, "tracker_held",
                                   {**self.HELD, "acceptance_state": acceptance})
                reduced = self.reduce_with(contract, delivery, held)
                self.assertEqual(stage_state(reduced, "close"), "observed")
                self.assertEqual(post_state(reduced, "tracker_closed"), "observed")
                self.assertEqual(
                    reduced["next_delivery"]["postconditions"]["tracker_closed"]
                    ["observation_id"], held["id"])
                fact = next(item for item in reduced["next_delivery"]["stage_facts"]
                            if item["stage_id"] == "close")
                self.assertEqual(fact["observation_id"], held["id"])

    def test_a_closed_observation_still_folds_close_tracker(self):
        contract, delivery = self.merged()
        closed = observation(self.model, contract, "tracker_closed", self.CLOSED)
        reduced = self.reduce_with(contract, delivery, closed)
        self.assertEqual((stage_state(reduced, "close"),
                          post_state(reduced, "tracker_closed")), ("observed", "observed"))

    def test_malformed_held_subjects_are_rejected(self):
        contract, _ = self.merged()
        changes = {
            "closed state": {"state": "closed"},
            "other label": {"label": "verify"},
            "met": {"acceptance_state": "met"},
            "not applicable": {"acceptance_state": "not_applicable"},
            "unknown acceptance": {"acceptance_state": "pending"},
            "absolute record": {"record_path": "/abs/x.acceptance.md"},
            "parent record": {"record_path": "plans/../x.acceptance.md"},
            "backslash record": {"record_path": "plans\\x.acceptance.md"},
            "empty record": {"record_path": ""},
            "null record": {"record_path": None},
            "empty comment": {"comment_url": ""},
            "empty identity": {"observation_identity": ""},
            "issue zero": {"issue": 0},
            "boolean issue": {"issue": True},
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                self.assert_rejected(observation(self.model, contract, "tracker_held",
                                                 {**self.HELD, **change}))
        missing = {key: value for key, value in self.HELD.items() if key != "record_path"}
        for label, subject in (("extra member", {**self.HELD, "close_reason": None}),
                               ("missing member", missing)):
            with self.subTest(label=label):
                self.assert_rejected(observation(self.model, contract, "tracker_held",
                                                 subject))

    def test_a_foreign_held_subject_leaves_the_stage_pending(self):
        contract, delivery = self.merged()
        for label, change in (("foreign issue", {"issue": 152}),
                              ("foreign repository", {"tracker_repository_id": "other"})):
            with self.subTest(label=label):
                foreign = observation(self.model, contract, "tracker_held",
                                      {**self.HELD, **change})
                reduced = self.reduce_with(contract, delivery, foreign)
                self.assertEqual((stage_state(reduced, "close"),
                                  post_state(reduced, "tracker_closed")),
                                 ("pending", "pending"))

    def test_held_and_closed_in_one_delivery_reject(self):
        contract, delivery = self.merged()
        held = observation(self.model, contract, "tracker_held", self.HELD)
        closed = observation(self.model, contract, "tracker_closed", self.CLOSED)
        with self.assertRaises(self.model.DeliveryModelError):
            self.reduce_with(contract, delivery, held, closed)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k TrackerHeldModelTest 2>&1 | tail -15`
Expected: FAIL or ERROR. At base the module has no `OBSERVATION_KINDS` attribute, and the model rejects `tracker_held` as an unknown observation kind. Only `test_a_closed_observation_still_folds_close_tracker` and the rejection-only cases pass.

- [ ] **Step 3: Write the minimal implementation**

In `_objects.py`, below `_POSTCONDITIONS`, derive the mappings so that the stage table stays the one source of each primary kind (D1):

```python
_EXTRA_STAGE_KINDS = {"close_tracker": ("tracker_held",)}
_EXTRA_POSTCONDITION_KINDS = {"tracker_closed": ("tracker_held",)}
_STAGE_OBSERVATION_KINDS = MappingProxyType({
    kind: frozenset({actions[2], *_EXTRA_STAGE_KINDS.get(kind, ())})
    for kind, actions in _STAGE_ACTIONS.items()})
_POSTCONDITION_OBSERVATION_KINDS = MappingProxyType({
    name: frozenset({name, *_EXTRA_POSTCONDITION_KINDS.get(name, ())})
    for name in _POSTCONDITIONS})
OBSERVATION_KINDS = frozenset().union(*_STAGE_OBSERVATION_KINDS.values(),
                                      *_POSTCONDITION_OBSERVATION_KINDS.values())
_HOLD_LABEL = "needs-verification"
_HOLD_ACCEPTANCE = frozenset({"unmet", "human_pending"})
```

Then make these changes:
1. In `_delivery_observation`, admit a kind only when `value["observation_kind"] in OBSERVATION_KINDS`.
2. In the same function, add a `tracker_held` branch after the `tracker_closed` branch. It calls `_object` over the eight members and `_integer(subject["issue"], "tracker issue", minimum=1)`. It checks with `_string` that `tracker_repository_id`, `comment_url` and `observation_identity` are non-empty. It calls `_reject()` unless `state == "open"`, `label == _HOLD_LABEL` and `isinstance(subject["acceptance_state"], str) and subject["acceptance_state"] in _HOLD_ACCEPTANCE` (the type check precedes set membership so a JSON array or object raises `DeliveryModelError`, not `TypeError`; add array and object rejection cases, PR273-3). It then checks `record_path`, rejecting the value when `_string` refuses it, when it starts with `/`, when it contains `\`, or when `".." in value.split("/")`.
3. Add one helper, `_tracker_outcome_matches(contract, item) -> bool`. It returns `subject["tracker_repository_id"] == contract["project"]["repository_id"] and subject["issue"] == contract["issue"] and subject["state"] == ("open" if item["observation_kind"] == "tracker_held" else "closed")`. Use it in both the `close_tracker` branch of `_stage_observation_matches` and the `tracker_closed` branch of `_postcondition_observation_matches`, so the two rules cannot drift.
4. In `_reconcile.py`, import `_STAGE_OBSERVATION_KINDS` and `_POSTCONDITION_OBSERVATION_KINDS`. The stage loop's `item["observation_kind"] == expected` becomes `item["observation_kind"] in _STAGE_OBSERVATION_KINDS[stage["kind"]]`. The postcondition loop's `== name` becomes `in _POSTCONDITION_OBSERVATION_KINDS[name]`. The distinct-subject `_reject()` lines stay as they are, and they now span both kinds (D4).
5. In `_wire.py`, the stage-fact check's `!= _STAGE_ACTIONS[stage["kind"]][2]` becomes `not in _STAGE_OBSERVATION_KINDS[stage["kind"]]`. The postcondition check's `!= key` becomes `not in _POSTCONDITION_OBSERVATION_KINDS[key]`. Import both mappings, and drop `_STAGE_ACTIONS` from the import only if nothing else in the file uses it.
6. In `__init__.py`, export `OBSERVATION_KINDS`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -4`
Expected: `OK`, including the six `TrackerHeldModelTest` cases. The existing `tracker_closed` cases stay green.

Run: `if grep -nE 'observation_kind"\] (==|!=) (expected|name|key|_STAGE_ACTIONS)' home/common/agent-skills/scripts/delivery_model/_reconcile.py home/common/agent-skills/scripts/delivery_model/_wire.py; then exit 1; fi`
Expected: no output and exit 0. This proves that no single-kind comparison is left (D1).

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py 2>&1 | tail -4`
Expected: `OK`. The tracker_closed delivery loops still complete.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_objects.py home/common/agent-skills/scripts/delivery_model/_reconcile.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/scripts/delivery_model/__init__.py home/common/agent-skills/tests/test_delivery_model.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "feat(delivery-model): tracker_held observation satisfies close_tracker (#273)" -m "<trailers>"
```
