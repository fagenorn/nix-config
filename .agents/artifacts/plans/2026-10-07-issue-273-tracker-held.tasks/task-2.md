# Task 2: Builder — tracker_held observation and the digest pin

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_build.py`
- Test: `home/common/agent-skills/tests/test_workflow_delivery.py`

**Interfaces:**
- Consumes (Task 1): `delivery_model.OBSERVATION_KINDS`, a frozenset that contains `tracker_held`, and the model's `tracker_held` grammar. The subject has exactly `tracker_repository_id`, `issue`, `state` (`"open"`), `label` (`"needs-verification"`), `comment_url`, `record_path`, `acceptance_state` (`unmet` or `human_pending`) and `observation_identity`.
- Produces: `build-delivery --kind observation` with `observation_kind: "tracker_held"`. Its fact keys are exactly `comment_url`, `record_path`, `acceptance_state` and `observation_identity`, next to the common keys `contract`, `observation_kind`, `source_kind`, `source_reference`, `observed_at` and `evidence`. Task 3's real-CLI loop and Task 4's control harness call it with `source_kind: "tracker"`.
- Produces: two builder refusals, each raised as `ValueError` and reaching CLI stderr unchanged:
  - `builder input keys: acceptance_state must be unmet or human_pending for a hold`
  - `builder input keys: record_path must be a relative POSIX path with no '..' segment`

**Invariants:**
- The builder supplies `tracker_repository_id` and `issue` from the contract, and the literals `state: "open"` and `label: "needs-verification"`. The caller never passes them (spec "build-delivery --kind observation").
- `DeliveryBuilder.__init__` derives its observable kinds from `model.OBSERVATION_KINDS`, not from `STAGE_ACTIONS[...][2]` plus `_OBLIGATIONS` (D1).
- For the fixed contract input below, the contract digest and the initial-intent digest equal literals captured at base 8a2e2631 (criterion 3, D5, D12):
  - contract: `sha256:223862cffef7277068ea22489161662da51773609d3ea38d46ac59267e057d66`
  - intent: `sha256:201db7c9a963061a80d43af0673d2ce1c2a3c9245cca1fe9dd675765e67be9e5`

- [ ] **Step 1: Write the failing test**

Append this class to `home/common/agent-skills/tests/test_workflow_delivery.py` at module end, before any `if __name__ == "__main__":` line. It uses only names the module already defines or imports (`ENTRY`, `NOW`, `resolved_snapshot`, `runpy`, `copy`, `seal`, `unittest`).

```python
class TrackerHeldBuilderTest(unittest.TestCase):
    """#273: build-delivery builds tracker_held; the contract digest does not move."""

    CONTRACT_DIGEST = "sha256:223862cffef7277068ea22489161662da51773609d3ea38d46ac59267e057d66"
    INTENT_DIGEST = "sha256:201db7c9a963061a80d43af0673d2ce1c2a3c9245cca1fe9dd675765e67be9e5"
    RECORD = ".agents/artifacts/plans/2026-10-07-issue-273-tracker-held.acceptance.md"
    COMMENT = "https://github.com/fagenorn/nix-config/issues/273#issuecomment-1"

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)
        cls.built = cls.runtime.build_delivery("contract", {
            "issue": 273, "worktree": "/repo/.worktrees/worktree-issue-273-held",
            "source_kind": "explicit_user", "source_reference": "invocation:/from-issue 273",
            "now": NOW}, policy=resolved_snapshot("/repo"))

    def held(self, **changes):
        value = {"contract": self.built["contract"], "observation_kind": "tracker_held",
                 "source_kind": "tracker", "source_reference": "gh issue view 273",
                 "observed_at": NOW, "evidence": "issue 273 open, labelled",
                 "comment_url": self.COMMENT, "record_path": self.RECORD,
                 "acceptance_state": "unmet",
                 "observation_identity": "github:issue:273:held"}
        value.update(changes)
        return self.runtime.build_delivery("observation", value, policy=None)

    def refusal(self, **changes):
        with self.assertRaises(ValueError) as caught:
            self.held(**changes)
        return str(caught.exception)

    def test_the_contract_digest_for_an_unchanged_input_is_pinned(self):
        model = self.runtime.model
        self.assertEqual(model.canonical_digest(self.built["contract"]), self.CONTRACT_DIGEST)
        self.assertEqual(model.canonical_digest(self.built["initial_intent"]),
                         self.INTENT_DIGEST)
        self.assertEqual(self.built["contract"]["initial_authorization_intent_digest"],
                         self.INTENT_DIGEST)
        close = next(stage for stage in self.built["contract"]["stages"]
                     if stage["kind"] == "close_tracker")
        self.assertEqual((close["action"], close["effect"]), ("close_issue", "tracker_write"))
        self.assertNotIn("tracker_held", model.canonical_bytes(self.built["contract"]).decode())

    def test_the_builder_builds_a_held_observation_the_model_accepts(self):
        for acceptance in ("unmet", "human_pending"):
            with self.subTest(acceptance=acceptance):
                item = self.held(acceptance_state=acceptance)
                self.assertEqual(item["observation_kind"], "tracker_held")
                self.assertEqual(item["subject"], {
                    "tracker_repository_id": "fagenorn/nix-config", "issue": 273,
                    "state": "open", "label": "needs-verification",
                    "comment_url": self.COMMENT, "record_path": self.RECORD,
                    "acceptance_state": acceptance,
                    "observation_identity": "github:issue:273:held"})
                self.assertEqual(item["source"], {"kind": "tracker",
                                                  "reference": "gh issue view 273"})
                self.assertEqual(item["contract_digest"], self.CONTRACT_DIGEST)
                self.runtime.validate(item, "delivery-observation")
        self.assertEqual(self.held(), self.held())

    def test_a_closed_state_subject_is_rejected_by_the_model(self):
        item = copy.deepcopy(self.held())
        item["subject"]["state"] = "closed"
        seal(self.runtime.model, item)
        with self.assertRaises(ValueError):
            self.runtime.validate(item, "delivery-observation")

    def test_a_met_or_not_applicable_hold_is_refused(self):
        for acceptance in ("met", "not_applicable", "pending"):
            with self.subTest(acceptance=acceptance):
                self.assertEqual(self.refusal(acceptance_state=acceptance),
                    "builder input keys: acceptance_state must be unmet or "
                    "human_pending for a hold")

    def test_a_non_relative_record_path_is_refused(self):
        for path in ("/repo/x.acceptance.md", "plans/../x.acceptance.md", "",
                     "plans\\x.acceptance.md"):
            with self.subTest(path=path):
                self.assertIn(self.refusal(record_path=path), {
                    "builder input keys: record_path must be a relative POSIX path "
                    "with no '..' segment",
                    "builder input keys: record_path must be a non-empty string"})

    def test_the_hold_takes_exactly_its_four_facts(self):
        reason = self.refusal(state="open")
        self.assertTrue(reason.startswith("builder input keys: expected exactly "), reason)
        with self.assertRaises(ValueError):
            value = {"contract": self.built["contract"], "observation_kind": "tracker_held",
                     "source_kind": "tracker", "source_reference": "probe",
                     "observed_at": NOW, "evidence": "e", "comment_url": self.COMMENT,
                     "record_path": self.RECORD, "acceptance_state": "unmet"}
            self.runtime.build_delivery("observation", value, policy=None)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py -k TrackerHeldBuilderTest 2>&1 | tail -15`
Expected: `test_the_contract_digest_for_an_unchanged_input_is_pinned` passes, at base and after Task 1. Every other case fails with `unsupported observation kind: 'tracker_held'`.

- [ ] **Step 3: Write the minimal implementation**

In `workflow_delivery_build.py`:
1. Add two checkers next to `_text`, using the exact refusal strings from Interfaces. `_hold_acceptance(value, name)` returns `value` only when `value in {"unmet", "human_pending"}`. `_record_path(value, name)` first calls `_text(value, name)`, which refuses an empty or non-string value with its own `must be a non-empty string` message. It then refuses a value that starts with `/`, contains `\`, or has a `..` segment in `value.split("/")`.
2. Add a `"tracker_held"` entry to `_OBSERVATIONS`:
   ```python
   "tracker_held": ({"comment_url": _text, "record_path": _record_path,
                     "acceptance_state": _hold_acceptance, "observation_identity": _text},
                    lambda context, facts: {
                        "tracker_repository_id": context["repository_id"],
                        "issue": context["issue"], "state": "open",
                        "label": "needs-verification",
                        "comment_url": facts["comment_url"],
                        "record_path": facts["record_path"],
                        "acceptance_state": facts["acceptance_state"],
                        "observation_identity": facts["observation_identity"]}),
   ```
3. In `DeliveryBuilder.__init__`, replace `observable = {item[2] for item in self._actions.values()} | set(_OBLIGATIONS)` with `observable = set(model.OBSERVATION_KINDS)`. Keep the `set(_OBSERVATIONS) <= observable` guard and its message. Keep `_OBLIGATIONS` if other code in the file still uses it, and delete it only if `grep -n _OBLIGATIONS` shows no other use.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py 2>&1 | tail -4`
Expected: `OK`, including the six `TrackerHeldBuilderTest` cases.

Run: `if grep -n 'item\[2\] for item in self._actions' home/common/agent-skills/scripts/workflow_delivery_build.py; then exit 1; fi`
Expected: no output and exit 0. The builder reads the model's observable set (D1).

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_build.py home/common/agent-skills/tests/test_workflow_delivery.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "feat(build-delivery): build tracker_held observations; pin the contract digest (#273)" -m "<trailers>"
```
