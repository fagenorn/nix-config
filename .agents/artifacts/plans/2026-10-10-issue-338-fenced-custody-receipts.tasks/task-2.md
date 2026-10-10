# Task 2: The pure `attempt_custody` module and the vocabulary's one home

The pure half of attempt custody: every rule that needs no file, lock or clock. Read the root's Global Constraints first. Decisions: D1, D3, D5, D8, D11, D16, D18, D19, D21.

**Files:**
- Create: `python/agent_tools/attempt_custody.py`
- Create: `tests/test_attempt_custody.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the suspension constants and `suspend_attempt`)
- Modify: `justfile` (recipe `agent-workflow-tests`: add the line `    tests/test_attempt_custody.py \` after `    tests/test_attempt_identity.py \`)

**Interfaces:**
- Consumes: `agent_tools.attempt_identity.MigrationRefused(reason, detail)`; `agent_tools.canonical.telemetry_digest`; `agent_tools.transaction_history.Transaction` (fields `state`, `custody`, `events`, `subject`), `TERMINALS`; `agent_tools.transaction_storage.is_id`.
- Produces (all in `agent_tools.attempt_custody`; nothing here reads a file, lock, clock or environment variable):
  - Constants: `SUBJECT_SCHEMA = "attempt-custody/v1"`, `AUTHORITY_CLASS = "attempt-custody"`, `FENCING_REASONS = ("custody_misbound", "superseded_launch", "launch_identity_required", "custody_unavailable")`, `BLOCKED_ON_VALUES`, `OWNER_BLOCKED_ON_VALUES`, `AUTO_RESUMABLE_BLOCKED_ON`, `STALL_LIMIT` (the shipped values, moved from `workflow-state.py` with the comment block above them), `LIVE_STATES = ("active", "handed_off", "suspended")`, `OPERATIONS = ("create", "acquire", "release", "reap", "park", "unpark", "renew", "record_result", "seal")`.
  - `stall_count(*, phase: int, suspend_phase: int | None, stalled_resumes: int) -> int`: `stalled_resumes + 1` when `suspend_phase == phase`, else `0`. `stalled(count: int) -> bool`: `count >= STALL_LIMIT`.
  - `suspension_reason(blocked_on: str) -> str`: `"suspended:<blocked_on>"`; `ValueError` outside `BLOCKED_ON_VALUES`. `blocked_on_of(reason: str) -> str | None`: `"unknown"` for `"expiry"`, the cause of a `suspended:<cause>` reason in the closed set, else `None`.
  - `at_ms(stamp: str) -> int`: an RFC 3339 UTC `…Z` ledger timestamp as epoch milliseconds.
  - `worktree_key(worktree: str) -> str`: `"attempt-worktree:<worktree>"`. `creation_key(run: str, issue: int, attempt: int) -> str`: `"attempt-custody/v1:<run>:<issue>:<attempt>"`. `launch_id(issue: int, attempt: int, launch: int) -> str`: `"<issue>:<attempt>:<launch>"`.
  - `subject(*, run, issue, attempt, worktree, prior, bound_launch) -> dict`: the closed object of the spec's subject table; `ValueError` carrying `subject_violation`'s text. `subject_violation(value) -> str | None`: `run` and a non-null `prior` are core ids, `issue`, `attempt` and a non-null `bound_launch` are `int`s of at least 1 (never `bool`), `worktree` is an absolute path equal to its `os.path.normpath`. `creation_arguments(subject: Mapping) -> dict`: the keyword arguments of `TransactionStore.create`: one concurrency key `worktree_key(subject["worktree"])`, the empty proof and recovery declarations `attempt_identity.creation_arguments` uses, `authority_class=AUTHORITY_CLASS`.
  - `plan_custody_migration(document: Mapping) -> dict[tuple[int, int], int]`: for each issue whose latest attempt is in `LIVE_STATES`, `(issue, attempt ordinal) -> len(launches)`; a worktree that is not absolute raises `MigrationRefused("invalid_state", …)`.
  - `launch_fence(transaction, executor_id: str) -> dict | None`: the fence, as plain dicts, of the latest `lease_acquired` or `lease_reacquired` event with that executor. `reaped(transaction, executor_id) -> bool`: a `stop_synthesized` event carries that fence. `result_recorded(transaction, executor_id, digest: str) -> bool`: an `owner_result` on that fence whose `result` has that `telemetry_digest`.
  - `merge_recorded(issue_state: Mapping, attempt: Mapping) -> bool`: the attempt's result is `merged` or has a non-null `merge_sha`, or `issue_state["delivery"]["postconditions"]` has `pr_merged` in state `observed`.
  - `span_lapsed(custody, lease: Mapping | None, now_ms: int) -> bool`: true unless the lease record still names the custody's epoch and instance and `now_ms < expires_at` (the core's own lapse comparison; a custody transaction has one key).
  - `@dataclass(frozen=True) class Operation`: `kind: str`, `executor_id: str | None = None`, `ttl_ms: int | None = None`, `reason: str | None = None`.
  - `class ProjectionMismatch(ValueError)`.
  - `settle_plan(issue_state, attempt, transaction, *, lease, now_ms, latest, report_digest=None) -> tuple[Operation, ...]`, specified below.

**The settle planner.** Inputs: the ledger's issue object and one of its attempts; that attempt's custody `Transaction` or `None`; `lease`, the record `inspect_lease` returns for the subject's worktree key (`None` with no transaction); `now_ms`; `latest`, whether this is the issue's last attempt; `report_digest`, the digest of an owner report this write submits for this attempt. It returns the operations that bring the core to the spec's projection table, in order. `current` is `launch_id(issue, attempt, len(launches))`, `span` the transaction's open custody, `parked` whether its state is `attention_required`.

1. **No transaction** (D19, D11): not `latest`, or the attempt state outside `LIVE_STATES` → `()`. Otherwise the plan starts with `Operation("create")` and continues below as a transaction in `created` with no span.
2. **Terminal transaction** (D18): attempt state in `LIVE_STATES` → `ProjectionMismatch`; otherwise `()`.
3. **`active`**, with `deadline = at_ms(deadline_at)`:
   - `span` is `current`'s: nothing when the lease record still names this span and expires at `deadline`, or when `deadline <= now_ms`; otherwise `acquire(current, ttl_ms=deadline - now_ms)` when the span has lapsed (D16) and `renew(ttl_ms=deadline - now_ms)` when it is live.
   - otherwise close any open span (`release` when live, `reap("expiry")` when lapsed), then `acquire(current, ttl_ms=deadline - now_ms)` when `deadline > now_ms`, then `unpark("resumed")` when the transaction was parked or the reap just parked it.
4. **`handed_off`**: close any open span the same way, then `unpark("resumed")` when parked.
5. **`suspended`** with cause `blocked_on`: span lapsed → `reap(reason)`, where reason is `"expiry"` for `unknown` and `suspension_reason(blocked_on)` otherwise; span live → `park(suspension_reason(blocked_on))`, `release`; no span → `park(suspension_reason(blocked_on))` unless already parked.
6. **A synthetic verdict** (`result_source` `stalled` or `expiry`): the same three cases with the source as both reasons. It never seals.
7. **Any other verdict** (`owner`, `refused`, `superseded`), in this order: `reap("expiry")` when an open span has lapsed; `record_result(current)` when the source is `owner`, a `report_digest` was given, `launch_fence(transaction, current)` is not `None` and `result_recorded` is false (D21); then `release` of a still-live span when `merge_recorded`, else `seal("<result_source>:<state>")`.

Operation fields: `acquire` and `record_result` carry `executor_id`; `acquire` and `renew` carry `ttl_ms`; `reap`, `park`, `unpark` and `seal` carry `reason`; every other field is `None`.

**Invariants:**
- The planner is total over `ATTEMPT_STATES` and raises only `ProjectionMismatch`; applying its plan and planning again at the same clock yields `()` or, for a verdict that seals, the single `seal`.
- The four vocabulary constants have one definition, in the package; `workflow-state.py` imports them under their existing names and defines none.
- `suspend_attempt` in `workflow-state.py` computes its count through `stall_count` and its bound through `stalled`; its observable behaviour does not change.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_attempt_custody.py`:

```python
"""Attempt custody's pure rules (#338): vocabulary, subject, migration plan, settle planner.

Run: just agent-workflow-tests
"""

import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_custody as ac
from agent_tools.attempt_identity import MigrationRefused
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import TransactionStore

RUN = "rel_01890a5d-ac96-774b-bcce-b302099a8057"
WORKTREE = "/work/wt-14"
T0 = 1_786_651_200_000  # 2026-08-13T20:00:00Z
DEADLINE = "2026-08-13T20:30:00Z"
MINUTE = 60_000
Op = ac.Operation


def attempt(state, *, launches=1, blocked_on=None, source=None, result=None,
            deadline=DEADLINE):
    return {"issue": 14, "attempt": 1, "state": state, "worktree": WORKTREE,
            "launches": [{"kind": "fresh"}] * launches, "deadline_at": deadline,
            "blocked_on": blocked_on, "result_source": source, "result": result}


def result(state, merge_sha=None):
    return {"issue": 14, "state": state, "pr_url": None, "merge_sha": merge_sha,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "n"}


def issue(merged=False):
    post = {"pr_merged": {"state": "observed", "observation_id": "sha256:" + "a" * 64}}
    return {"delivery": {"postconditions": post if merged else {}}}


class VocabularyTest(unittest.TestCase):
    def test_the_closed_sets_are_the_shipped_ones(self):
        self.assertEqual(ac.BLOCKED_ON_VALUES, {
            "usage_limit", "transport", "human_gate", "external", "unknown",
            "host_capacity", "agent_dispatch", "deadline"})
        self.assertEqual(ac.OWNER_BLOCKED_ON_VALUES,
                         ac.BLOCKED_ON_VALUES - {"unknown", "host_capacity"})
        self.assertEqual(ac.AUTO_RESUMABLE_BLOCKED_ON, {
            "usage_limit", "transport", "unknown", "host_capacity", "deadline"})
        self.assertEqual(ac.STALL_LIMIT, 3)
        self.assertEqual(ac.FENCING_REASONS, (
            "custody_misbound", "superseded_launch", "launch_identity_required",
            "custody_unavailable"))

    def test_stall_arithmetic(self):
        self.assertEqual(ac.stall_count(phase=2, suspend_phase=None, stalled_resumes=0), 0)
        self.assertEqual(ac.stall_count(phase=2, suspend_phase=1, stalled_resumes=2), 0)
        self.assertEqual(ac.stall_count(phase=2, suspend_phase=2, stalled_resumes=1), 2)
        self.assertEqual([ac.stalled(count) for count in (2, 3, 4)], [False, True, True])

    def test_parking_reasons_round_trip_the_cause(self):
        for cause in sorted(ac.BLOCKED_ON_VALUES):
            self.assertEqual(ac.blocked_on_of(ac.suspension_reason(cause)), cause)
        self.assertEqual(ac.suspension_reason("transport"), "suspended:transport")
        self.assertEqual(ac.blocked_on_of("expiry"), "unknown")
        for reason in ("stalled", "suspended:nonsense", "resumed"):
            self.assertIsNone(ac.blocked_on_of(reason))
        with self.assertRaises(ValueError):
            ac.suspension_reason("nonsense")


class SubjectTest(unittest.TestCase):
    def subject(self, **changes):
        return {**ac.subject(run=RUN, issue=14, attempt=2, worktree=WORKTREE, prior=RUN,
                             bound_launch=None), **changes}

    def test_keys_and_subject(self):
        self.assertEqual(ac.creation_key(RUN, 14, 2), f"attempt-custody/v1:{RUN}:14:2")
        self.assertEqual(ac.worktree_key(WORKTREE), "attempt-worktree:/work/wt-14")
        self.assertEqual(ac.launch_id(14, 2, 3), "14:2:3")
        self.assertEqual(ac.at_ms(DEADLINE), T0 + 30 * MINUTE)
        self.assertEqual(self.subject(), {
            "schema": "attempt-custody/v1", "run": RUN, "issue": 14, "attempt": 2,
            "worktree": WORKTREE, "prior": RUN, "bound_launch": None})
        self.assertEqual(ac.creation_arguments(self.subject()), {
            "concurrency_keys": ["attempt-worktree:/work/wt-14"],
            "proof": {"units": [], "obligations": [], "collectors": {}},
            "recovery": {"effects": {}, "units": []}, "authority_class": "attempt-custody"})

    def test_subject_violations(self):
        self.assertIsNone(ac.subject_violation(self.subject(bound_launch=3, prior=None)))
        for changes in ({"schema": "attempt-run/v1"}, {"run": "orchestrate-14"},
                        {"issue": 0}, {"attempt": True}, {"worktree": "wt-14"},
                        {"worktree": "/work/../wt"}, {"prior": "x"}, {"bound_launch": 0},
                        {"extra": 1}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ac.subject_violation(self.subject(**changes)))
        with self.assertRaises(ValueError):
            ac.subject(run=RUN, issue=14, attempt=1, worktree="relative", prior=None,
                       bound_launch=None)


class MigrationPlanTest(unittest.TestCase):
    def document(self, *attempts):
        return {"issues": {"14": {"attempts": list(attempts)}}}

    def test_only_a_live_latest_attempt_is_bound_at_its_launch_count(self):
        stopped = {**attempt("stopped", source="owner"), "attempt": 1}
        live = {**attempt("suspended", launches=3, blocked_on="transport"), "attempt": 2}
        self.assertEqual(ac.plan_custody_migration(self.document(stopped, live)),
                         {(14, 2): 3})
        self.assertEqual(ac.plan_custody_migration(self.document(stopped)), {})
        self.assertEqual(ac.plan_custody_migration({"issues": {"14": {"attempts": []}}}), {})

    def test_a_relative_worktree_is_invalid_state(self):
        with self.assertRaises(MigrationRefused) as caught:
            ac.plan_custody_migration(self.document({**attempt("active"), "worktree": "wt"}))
        self.assertEqual(caught.exception.reason, "invalid_state")


class SettlePlanTest(unittest.TestCase):
    """The planner over real core snapshots; the store's clock is this test's `now`."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = T0
        self.store = TransactionStore(Path(directory.name), clock=lambda: self.now)
        subject = ac.subject(run=RUN, issue=14, attempt=1, worktree=WORKTREE, prior=None,
                             bound_launch=None)
        self.id = self.store.create(ac.creation_key(RUN, 14, 1), subject,
                                    **ac.creation_arguments(subject)).transaction_id

    def acquire(self, launch=1, minutes=30):
        return self.store.acquire(self.id, executor_id=f"14:1:{launch}",
                                  subject_path=WORKTREE, ttl_ms=minutes * MINUTE).custody

    def plan(self, attempt_, *, issue_=None, latest=True, digest=None, bare=False):
        transaction = None if bare else self.store.load(self.id)
        lease = None if bare else self.store.inspect_lease(ac.worktree_key(WORKTREE))
        return ac.settle_plan(issue_ or issue(), attempt_, transaction, lease=lease,
                              now_ms=self.now, latest=latest, report_digest=digest)

    def test_an_attempt_without_a_transaction(self):
        self.assertEqual(self.plan(attempt("active"), bare=True),
                         (Op("create"), Op("acquire", executor_id="14:1:1",
                                           ttl_ms=30 * MINUTE)))
        self.now = T0 + 30 * MINUTE  # bound while expired: no span (D11)
        self.assertEqual(self.plan(attempt("active"), bare=True), (Op("create"),))
        self.assertEqual(self.plan(attempt("handed_off"), bare=True), (Op("create"),))
        self.assertEqual(
            self.plan(attempt("suspended", blocked_on="human_gate"), bare=True),
            (Op("create"), Op("park", reason="suspended:human_gate")))
        self.assertEqual(self.plan(attempt("stopped", source="owner"), bare=True), ())
        self.assertEqual(self.plan(attempt("active"), bare=True, latest=False), ())

    def test_an_active_attempt(self):
        self.acquire()
        self.assertEqual(self.plan(attempt("active")), ())
        self.now = T0 + 31 * MINUTE  # lapsed and unreaped: still the active row
        self.assertEqual(self.plan(attempt("active")), ())
        self.now = T0 + 5 * MINUTE
        self.assertEqual(self.plan(attempt("active", deadline="2026-08-13T20:20:00Z")),
                         (Op("renew", ttl_ms=15 * MINUTE),))
        self.now = T0 + 31 * MINUTE  # re-based after the old window passed (D16)
        self.assertEqual(self.plan(attempt("active", deadline="2026-08-13T21:00:00Z")),
                         (Op("acquire", executor_id="14:1:1", ttl_ms=29 * MINUTE),))

    def test_a_new_launch(self):
        custody = self.acquire()
        self.now = T0 + 5 * MINUTE
        takeover = (Op("release"), Op("acquire", executor_id="14:1:2", ttl_ms=25 * MINUTE))
        self.assertEqual(self.plan(attempt("active", launches=2)), takeover)
        self.store.release(custody)  # a handoff released it already
        self.assertEqual(self.plan(attempt("active", launches=2)), takeover[1:])

    def test_a_resume_after_an_unreaped_expiry_and_after_a_parking(self):
        self.acquire()
        self.now = T0 + 31 * MINUTE
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        acquire = Op("acquire", executor_id="14:1:2", ttl_ms=30 * MINUTE)
        self.assertEqual(self.plan(resumed), (Op("reap", reason="expiry"), acquire,
                                              Op("unpark", reason="resumed")))
        self.store.reap(self.id, reason="expiry")
        self.assertEqual(self.plan(resumed), (acquire, Op("unpark", reason="resumed")))

    def test_a_handoff(self):
        self.acquire()
        self.assertEqual(self.plan(attempt("handed_off")), (Op("release"),))

    def test_a_suspension(self):
        self.acquire()
        owner = attempt("suspended", blocked_on="transport")
        self.assertEqual(self.plan(owner),
                         (Op("park", reason="suspended:transport"), Op("release")))
        self.now = T0 + 30 * MINUTE
        self.assertEqual(self.plan(owner), (Op("reap", reason="suspended:transport"),))
        reaper = attempt("suspended", blocked_on="unknown")
        self.assertEqual(self.plan(reaper), (Op("reap", reason="expiry"),))
        self.store.reap(self.id, reason="expiry")
        self.assertEqual(self.plan(reaper), ())

    def test_an_expired_handoff_is_parked_without_a_stop(self):
        self.store.release(self.acquire())
        self.now = T0 + 30 * MINUTE
        self.assertEqual(self.plan(attempt("suspended", blocked_on="unknown")),
                         (Op("park", reason="suspended:unknown"),))

    def test_a_stalled_stop_parks_and_never_seals(self):
        stalled = attempt("stopped", source="stalled", result=result("stopped"))
        self.acquire()
        self.assertEqual(self.plan(stalled), (Op("park", reason="stalled"), Op("release")))
        self.now = T0 + 30 * MINUTE
        self.assertEqual(self.plan(stalled), (Op("reap", reason="stalled"),))
        self.store.reap(self.id, reason="stalled")
        self.assertEqual(self.plan(stalled), ())

    def test_an_owner_verdict_records_then_seals_or_releases(self):
        self.acquire()
        stopped = attempt("stopped", source="owner", result=result("stopped"))
        self.assertEqual(self.plan(stopped, digest="sha256:" + "1" * 64), (
            Op("record_result", executor_id="14:1:1"), Op("seal", reason="owner:stopped")))
        self.assertEqual(self.plan(stopped), (Op("seal", reason="owner:stopped"),))
        merged = attempt("merged", source="owner", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(merged, digest="sha256:" + "1" * 64), (
            Op("record_result", executor_id="14:1:1"), Op("release")))
        failed = attempt("failed", source="owner", result=result("failed"))
        self.assertEqual(self.plan(failed, issue_=issue(merged=True)), (Op("release"),))

    def test_a_late_owner_verdict_reaps_first_and_is_recorded_once(self):
        custody = self.acquire()
        self.now = T0 + 31 * MINUTE
        report = {"state": "stopped"}
        digest = telemetry_digest(report)
        stopped = attempt("stopped", source="owner", result=result("stopped"))
        self.assertEqual(self.plan(stopped, digest=digest), (
            Op("reap", reason="expiry"), Op("record_result", executor_id="14:1:1"),
            Op("seal", reason="owner:stopped")))
        self.store.reap(self.id, reason="expiry")
        self.store.record_owner_result(self.id, executor_id="14:1:1", subject_path=WORKTREE,
                                       fence=custody.fence, result=report)
        self.assertEqual(self.plan(stopped, digest=digest),
                         (Op("seal", reason="owner:stopped"),))
        transaction = self.store.load(self.id)
        self.assertTrue(ac.reaped(transaction, "14:1:1"))
        self.assertTrue(ac.result_recorded(transaction, "14:1:1", digest))
        self.assertEqual(ac.launch_fence(transaction, "14:1:1"),
                         {key: dict(entry) for key, entry in custody.fence.items()})
        self.assertIsNone(ac.launch_fence(transaction, "14:1:2"))
        self.assertFalse(ac.reaped(transaction, "14:1:2"))

    def test_a_verdict_on_a_launch_without_a_span_is_not_recorded(self):
        stopped = attempt("stopped", source="owner", result=result("stopped"))
        self.assertEqual(self.plan(stopped, digest="sha256:" + "1" * 64),
                         (Op("seal", reason="owner:stopped"),))

    def test_superseded_and_refused_verdicts(self):
        self.acquire()
        superseded = attempt("merged", source="superseded", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(superseded), (Op("release"),))
        refused = attempt("failed", source="refused", result=result("failed"))
        self.assertEqual(self.plan(refused, latest=False),
                         (Op("seal", reason="refused:failed"),))

    def test_a_sealed_transaction_is_final(self):
        self.store.advance(self.id, "abandoned", reason="owner:failed", external_state="known")
        merged = attempt("merged", source="superseded", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(merged), ())
        with self.assertRaises(ac.ProjectionMismatch):
            self.plan(attempt("active"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_custody.py`
Expected: an import error, `cannot import name 'attempt_custody' from 'agent_tools'`.

- [ ] **Step 3: Implement the module**

Write `python/agent_tools/attempt_custody.py` to the interfaces and the planner rules above, with a module docstring that says what the module holds and that `agent_tools.attempt_store` owns the effects, written from the implemented code. Give each public function a contract docstring.

- [ ] **Step 4: Move the vocabulary**

In `workflow-state.py`, delete the definitions of `BLOCKED_ON_VALUES`, `OWNER_BLOCKED_ON_VALUES`, `AUTO_RESUMABLE_BLOCKED_ON` and `STALL_LIMIT` with the comment block above them (it moves to the module, above the same constants), and import the four names from `agent_tools.attempt_custody` beside the existing `agent_tools` imports. In `suspend_attempt`, replace the inline arithmetic with `stall_count(phase=…, suspend_phase=…, stalled_resumes=…)` and the comparison with `stalled(…)`. Add the `justfile` line.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_custody.py`
Expected: `OK`, 20 tests.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py` (timeout 1800 s)
Expected: `OK`: the suspension and stall cases pass on the moved vocabulary.

Run: `if grep -nE '^(BLOCKED_ON_VALUES|OWNER_BLOCKED_ON_VALUES|AUTO_RESUMABLE_BLOCKED_ON|STALL_LIMIT) *=' home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi; grep -c 'tests/test_attempt_custody.py' justfile`
Expected: exit 0 and `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/attempt_custody.py tests/test_attempt_custody.py home/common/agent-skills/scripts/workflow-state.py justfile
launch-commit … -- -m "feat(attempt-custody): pure custody rules and the suspension vocabulary's home (#338)"
```
