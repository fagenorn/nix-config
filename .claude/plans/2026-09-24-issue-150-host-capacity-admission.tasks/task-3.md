# Task 3: Ledger schema 4 and the commit-boundary settle

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`migrate`, `migrate_1_to_2`)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (`LifecycleHarness` extraction, legacy helpers, schema re-pins)
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py` (schema re-pins, `write_run`)
- Test: `home/common/agent-skills/tests/test_host_admission.py`

**Interfaces:**
- Consumes (Task 1): `_host_admission()` → `DIRECT_ROUTE`, `ROUTE_NAME_PATTERN`, `CONTROLLER_ROLES`, `OWNER_ROLE_SET`.
- Produces (`workflow-state.py`):
  - `SCHEMA_VERSION = 4`; `STATE_FIELDS` gains `admission`; `new_run_state` writes `"admission": None`.
  - `ADMISSION_FIELDS = {"route", "releases", "claims"}`, `CLAIM_FIELDS = {"holder", "roles", "acquired_at", "released_at", "release_event", "release_seq"}`, `RELEASE_EVENTS = {"finished", "suspended", "handed_off", "superseded", "owner_unavailable", "launch_refused", "finalized"}`, `CONTROLLER_HOLDER = "controller"`.
  - `parse_claim_holder(holder: str) -> tuple[int, str, int, int]` — `(issue, "implementation"|"remainder", ordinal, launch)` from `ACTION_ID_PATTERN` (group 2 is `r` for a remainder).
  - `release_claim(admission: dict, claim: dict, *, event: str, at: str) -> None` — increments `releases` and stamps `released_at`, `release_event`, `release_seq`.
  - `settle_admission(state: dict, *, at: str) -> bool` — the D5 settle step; `True` when it released anything.
  - `commit_state(run_dir, state_path, state, *, run_id) -> None` — `settle_admission(state, at=state["updated_at"])`, `validate_state`, `atomic_write_state`, in that order.
  - `validate_state` ends by validating `state["admission"]` (Invariants).
- Produces (tests): `LifecycleHarness` in `T/test_workflow_state.py` — a plain mixin holding every helper `WorkflowStateLifecycleTest` defines before its first `test_` method (from `setUpClass` through `run_control_at_root`, with `UNOBSERVED`); `WorkflowStateLifecycleTest(LifecycleHarness, unittest.TestCase)` keeps the tests (per D23).

**Invariants:**
- Every committed state write passes `commit_state`: `transact`, and each `direct-owner` write (today's `validate_state` + `atomic_write_state` pairs, and the `if changed:` write after `complete_direct_policy`, which becomes `commit_state` when changed and `validate_state` otherwise) (per D5).
- `settle_admission` does nothing when `admission` is `None` or its route is `direct`. Otherwise, for each held owner claim in list order whose holder is not its issue's current `active` launch (`runtime.current_custody`), it releases with the first matching event (per D19):
  1. issue delivery complete (`runtime.delivery_complete`) → `finished`;
  2. the holder's record has more launches than the holder's launch ordinal → `superseded`;
  3. record state in `{merged, stopped, failed, completed}` → `finished`;
  4. `suspended` with `blocked_on == "host_capacity"` → `launch_refused`;
  5. other `suspended` → `suspended`; 6. `handed_off` → `handed_off`;
  7. anything else → `WorkflowError("internal error: unreleasable claim")`.
- Admission validation (exact members everywhere; any violation is a `WorkflowError`, so reads and writes refuse): `admission` is `None` or `ADMISSION_FIELDS`; `route` is `direct` or matches `ROUTE_NAME_PATTERN`; `releases` a plain int ≥ 0; each claim has `CLAIM_FIELDS`; holder `controller` with roles exactly `{"controller": 1}`, or a parseable holder with roles exactly `{"owner": 1, "worker": 1, "reviewer": 1}`; `created_at ≤ acquired_at ≤ updated_at`; the release trio is all null or all set; a released claim has `acquired_at ≤ released_at ≤ updated_at`, an event in `RELEASE_EVENTS`, `finalized` exactly for controller claims, and a plain-int `release_seq`; released seqs are exactly `1..releases`; at most one held controller claim; owner holders are unique across all claims; a `direct` block has no claims and `releases == 0`; every held owner claim is its issue's current launch with record state `active`.
- Migration composes 1→2→3→4 on a detached copy; the 3→4 step refuses a v3 document that already has `admission` and otherwise writes `admission: None` (per D11).
- `check-launch` stays unlocked and read-only: it migrates schemas 1, 2 and 3 in memory, validates the candidate, and answers from the raw document.

- [ ] **Step 1: Write the failing tests**

Extract `LifecycleHarness` first (mechanical, no behavior change). Then change its
`_as_legacy(state, version, *, keep_delivery=False)` to pop `admission` for every
`version < 4` and to pop `delivery`/`delivery_remainders` only for `version < 3`
unless `keep_delivery`; make `legacy_expiry_record(prior_schema=True)` write
schema 2 (pop `admission`, `delivery`, `delivery_remainders`). In
`T/test_host_admission.py`, move the `from .test_workflow_state import …` line
below into the module imports and append the rest:

```python
from .test_workflow_state import DEFAULT_NOW, SCRIPT, LifecycleHarness, load_source_module

OWNER_ROLES = {"owner": 1, "worker": 1, "reviewer": 1}


def claim(holder, roles, at, released=None):
    """One claim record; `released` is (released_at, event, seq) or None."""
    released_at, event, seq = released or (None, None, None)
    return {"holder": holder, "roles": dict(roles), "acquired_at": at,
            "released_at": released_at, "release_event": event, "release_seq": seq}


class ClaimLedgerTest(LifecycleHarness, unittest.TestCase):
    """D5, D11, D19: schema 4 records claims; the commit boundary releases them."""

    LATER = "2026-08-13T20:30:00Z"

    def admitted(self):
        """A v4 run: contractless issue 14 active, its launch and the controller claimed."""
        self.init_run()
        workflow = load_source_module(SCRIPT, "host_admission_ledger")
        state = self.read_state()
        attempt = workflow.new_control_attempt(
            issue=14, attempt_number=1, worktree=str(self.root / "wt-14"),
            now=DEFAULT_NOW, deadline_at="2026-08-13T23:00:00Z")
        state["issues"]["14"] = {"issue": 14, "attempts": [attempt], "outcome": None,
                                 "delivery": self.empty_delivery(),
                                 "delivery_remainders": []}
        state["admission"] = {"route": "claude-code", "releases": 0, "claims": [
            claim("controller", {"controller": 1}, DEFAULT_NOW),
            claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)]}
        self.write_state(state)
        return state

    def released(self, holder):
        item = {c["holder"]: c for c in self.read_state()["admission"]["claims"]}[holder]
        return item["released_at"], item["release_event"], item["release_seq"]

    def finish_14(self, now, *, ok=True):
        result = self.root / "result.json"
        result.write_text(json.dumps(self.merged_result(14)), encoding="utf-8")
        return self.run_cli("finish", "--repo-root", self.root, "--run-id", self.run_id,
                            "--issue", 14, "--attempt", 1, "--result-file", result,
                            "--now", now, ok=ok)

    def test_finish_releases_the_claim_in_its_own_write(self):
        self.admitted()
        self.finish_14(self.LATER)
        state = self.read_state()
        self.assertEqual(state["issues"]["14"]["attempts"][0]["state"], "merged")
        self.assertEqual(state["updated_at"], self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "finished", 1))
        self.assertEqual((state["admission"]["releases"], self.released("controller")),
                         (1, (None, None, None)))

    def test_suspend_releases_suspended(self):
        self.admitted()
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit", now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "suspended", 1))

    def test_handoff_releases_handed_off(self):
        self.admitted()
        self.progress(turn_count=118, context_tokens=20000,
                      handoff_path=self.write_handoff(14), now=self.LATER)
        self.assertEqual(self.released("14:1:1"), (self.LATER, "handed_off", 1))

    def test_a_refused_write_leaves_record_and_claim_unchanged(self):
        self.admitted()
        before = self.state_path.read_bytes()
        refused = self.finish_14("2026-08-13T19:00:00Z", ok=False)
        self.assertEqual((refused.returncode, self.state_path.read_bytes()), (2, before))

    def test_state_validation_closes_the_admission_block(self):
        valid = self.admitted()
        check = ("check-launch", "--repo-root", self.root, "--run-id", self.run_id,
                 "--action-id", "14:1:1")
        self.assertEqual(self.run_cli(*check).returncode, 0)
        owner = claim("14:1:1", OWNER_ROLES, DEFAULT_NOW)
        block = lambda claims, releases=0, route="claude-code": {
            "route": route, "releases": releases, "claims": claims}
        for label, admission in (
                ("stale holder", block([claim("14:1:9", OWNER_ROLES, DEFAULT_NOW)])),
                ("two controllers", block([claim("controller", {"controller": 1},
                                                 DEFAULT_NOW)] * 2)),
                ("duplicate holder", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                  (DEFAULT_NOW, "suspended", 1)), owner], 1)),
                ("partial release", block([{**owner, "released_at": DEFAULT_NOW,
                                            "release_seq": 1}], 1)),
                ("counter mismatch", block([owner], 2)),
                ("wrong roles", block([claim("14:1:1", {"controller": 1}, DEFAULT_NOW)])),
                ("owner finalized", block([claim("14:1:1", OWNER_ROLES, DEFAULT_NOW,
                                                 (DEFAULT_NOW, "finalized", 1))], 1)),
                ("direct with claims", block([owner], route="direct")),
                ("extra member", {**block([]), "slots": 4})):
            with self.subTest(label):
                self.write_state({**valid, "admission": admission})
                self.assertEqual(self.run_cli(*check, ok=False).returncode, 2)

    def test_schema_three_reads_migrate_to_a_null_admission(self):
        self.admitted()
        self.write_state(self._as_legacy(self.read_state(), 3))
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"], "current")
        self.init_run()  # a locked read persists the migration
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["admission"]), (4, None))

    def test_direct_runs_carry_no_admission(self):
        self.acquire_direct()
        state = json.loads(self.direct_state_path("direct-73-000001").read_text())
        self.assertIsNone(state["admission"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_host_admission.py 2>&1 | tail -4`
Expected: FAIL — schema 3 ledgers carry no `admission` (`KeyError`/`invalid workflow state schema`).

- [ ] **Step 3: Implement**

The Produces and Invariants above, plus: `validate_state` loads the library once per call; `settle_admission`'s docstring states the D19 order and that it is the only release site besides control's `owner_unavailable` and `finalized` releases; `commit_state`'s docstring names it as the one write boundary. `migrate`'s docstring becomes "Compose schema 1→2→3→4"; its v1/v2 legacy issue-schema check stays scoped to those versions; `migrate_1_to_2` also pops `admission`.

Re-pin existing tests to schema 4 (numbers only, plus renaming tests whose names say "schema three"): `T/test_workflow_state.py` lines asserting `schema_version` 3 (≈2198, 5009, 5030–5032, 5057) and the literal schema-3 states (≈2593, 2640, which gain `"admission": None`); `T/test_delivery_workflow.py` ≈250, 263–264, 1929, and `ContractLifecycleTest.write_run`, whose default becomes `schema=4` and which pops `admission` for `schema < 4`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_host_admission.py 2>&1 | tail -3`
Expected: `OK` (the ClaimLedgerTest cases fail at the base commit).

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery.py \
  home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py \
  home/common/agent-skills/tests/test_host_admission.py
git commit -m "feat(workflow-state): record admission claims in schema 4 and settle them at commit (#150)"
```
