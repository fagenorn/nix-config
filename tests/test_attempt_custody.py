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

    def test_the_cutover_vocabulary(self):
        self.assertEqual(ac.SUSPENSION_CAUSES - ac.BLOCKED_ON_VALUES, {"owner_unavailable"})
        self.assertNotIn("owner_unavailable", ac.OWNER_BLOCKED_ON_VALUES)
        self.assertEqual(ac.blocked_on_of(ac.suspension_reason("owner_unavailable")),
                         "owner_unavailable")
        roles = {"worker": 1, "owner": 1}
        reference = ac.claim_reference(roles, "claude-code")
        self.assertEqual(reference, '{"roles":{"owner":1,"worker":1},"route":"claude-code"}')
        self.assertEqual((ac.claim_roles(reference), ac.claim_id("14:r1:2", 3),
                          ac.seal_executor("14:1:3"), ac.seal_executor("14:r2:1")),
                         (roles, "admission-claim:14:r1:2:3", "14:1:seal", "14:r2:seal"))
        with self.assertRaises(ValueError):
            ac.claim_roles('{"roles":{"owner":"1"},"route":"x"}')

        def claim(holder, event=None, seq=None):
            return {"holder": holder, "roles": roles, "release_event": event,
                    "release_seq": seq, "released_at": None if event is None else "t"}

        claims = [claim("12:1:1"), claim("14:1:1", "launch_refused", 2),
                  claim("16:1:1", "owner_unavailable", 1), claim("18:1:1", "launch_refused", 3)]
        block = {"route": "claude-code", "claims": claims}
        self.assertEqual((ac.held_claim(block, "12:1:1"), ac.held_claim(block, "14:1:1"),
                          ac.held_claim(None, "12:1:1")), (reference, None, None))
        self.assertEqual((ac.owner_gone(block, "16:1:1"), ac.owner_gone(block, "12:1:1"),
                          ac.owner_gone(None, "16:1:1")), (True, False, False))
        # Only a later release that is not itself a refusal opens the gate.
        self.assertEqual((ac.gate_open(claims, "14:1:1"), ac.gate_open(claims, "12:1:1")),
                         (False, False))
        claims.append(claim("20:1:1", "finished", 4))
        self.assertEqual((ac.gate_open(claims, "14:1:1"), ac.gate_open(claims, "18:1:1")),
                         (True, True))

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
        self.fresh()

    def fresh(self):
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

    def plan(self, attempt_, *, issue_=None, latest=True, digest=None, bare=False,
             bound=False, **facts):
        transaction = None if bare else self.store.load(self.id)
        lease = None if bare else self.store.inspect_lease(ac.worktree_key(WORKTREE))
        return ac.settle_plan(issue_ or issue(), attempt_, transaction, lease=lease,
                              now_ms=self.now, latest=latest, report_digest=digest,
                              bound=bound, **facts)

    def apply(self, operations, report):
        """Apply `operations` to the store the way the settle step maps them."""
        for op in operations:
            held = self.store.load(self.id).custody
            if op.kind == "acquire":
                self.store.acquire(self.id, executor_id=op.executor_id,
                                   subject_path=WORKTREE, ttl_ms=op.ttl_ms)
            elif op.kind == "release":
                self.store.release(held)
            elif op.kind == "reap":
                self.store.reap(self.id, reason=op.reason)
            elif op.kind == "claim":
                self.store.record_evidence(
                    held, evidence_id=ac.claim_id(op.executor_id, ac.span_epoch(held)),
                    form="snapshot", reference=op.reference)
            elif op.kind in ("park", "unpark"):
                target = "attention_required" if op.kind == "park" else "created"
                self.store.advance(self.id, target, reason=op.reason, custody=held)
            elif op.kind == "record_result":
                fence = ac.launch_fence(self.store.load(self.id), op.executor_id)
                self.store.record_owner_result(self.id, executor_id=op.executor_id,
                                               subject_path=WORKTREE, fence=fence,
                                               result=report)
            elif op.kind == "seal":
                self.store.advance(self.id, "abandoned", reason=op.reason,
                                   external_state="known", custody=held)
            else:
                self.fail(f"unexpected operation {op}")

    def held(self):
        transaction = self.store.load(self.id)
        holder = self.store.inspect_lease(ac.worktree_key(WORKTREE))["holder"]
        return (transaction.state,
                None if transaction.custody is None else transaction.custody.executor_id,
                None if holder is None else holder["executor_id"],
                [event["type"] for event in transaction.events
                 if event["type"] in ("stop_synthesized", "owner_result")])

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

    def test_an_attempt_its_binding_write_ended_is_still_created(self):
        stopped = attempt("stopped", source="owner", result=result("stopped"))
        self.assertEqual(self.plan(stopped, bare=True, bound=True, digest="sha256:" + "1" * 64),
                         (Op("create"), Op("seal", reason="owner:stopped")))
        merged = attempt("merged", source="owner", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(merged, bare=True, bound=True), (Op("create"),))
        stalled = attempt("stopped", source="stalled", result=result("stopped"))
        self.assertEqual(self.plan(stalled, bare=True, bound=True, latest=False),
                         (Op("create"), Op("park", reason="stalled")))

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

    def test_a_plan_interrupted_after_any_operation_converges(self):
        report = {"state": "stopped"}
        digest = telemetry_digest(report)
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        stopped = attempt("stopped", source="owner", result=result("stopped"))
        merged = attempt("merged", source="owner", result=result("merged", "b" * 40))

        def lapse():
            self.now = T0 + 31 * MINUTE

        def reap():
            lapse()
            self.store.reap(self.id, reason="expiry")

        def later():
            self.now = T0 + 5 * MINUTE

        cases = {
            "suspension": (None, attempt("suspended", blocked_on="transport"), 2),
            "stalled stop": (None, attempt("stopped", source="stalled",
                                           result=result("stopped")), 2),
            "resume after a reap": (reap, resumed, 2),
            "resume after an unreaped expiry": (lapse, resumed, 3),
            "takeover": (later, attempt("active", launches=2), 2),
            "expired handoff resumed": (lapse, attempt("handed_off"), 2),
            "late verdict": (lapse, stopped, 3),
            "verdict": (None, stopped, 2),
            "merged verdict": (None, merged, 2)}
        for name, (prepare, attempt_, length) in cases.items():
            def start():
                self.fresh()
                self.acquire()
                if prepare is not None:
                    prepare()

            start()
            whole = self.plan(attempt_, digest=digest)
            self.assertEqual(len(whole), length, name)
            self.apply(whole, report)
            reached = self.held()
            self.assertEqual(self.plan(attempt_, digest=digest), (), name)
            for cut in range(1, length):
                with self.subTest(case=name, applied=cut):
                    start()
                    self.apply(self.plan(attempt_, digest=digest)[:cut], report)
                    self.apply(self.plan(attempt_, digest=digest), report)
                    self.assertEqual(self.held(), reached)
                    self.assertEqual(self.plan(attempt_, digest=digest), ())

    def test_a_claimed_launch_records_its_claim_once_per_span(self):
        claim = ac.claim_reference({"owner": 1}, "claude-code")
        entry = Op("claim", executor_id="14:1:1", reference=claim)
        self.assertEqual(self.plan(attempt("active"), bare=True, claim=claim), (
            Op("create"), Op("acquire", executor_id="14:1:1", ttl_ms=30 * MINUTE), entry))
        custody = self.acquire()
        # An open span the store holds without a claim gets one (the route's first sweep).
        self.assertEqual(self.plan(attempt("active"), claim=claim), (entry,))
        self.store.record_evidence(
            custody, evidence_id=ac.claim_id("14:1:1", ac.span_epoch(custody)),
            form="snapshot", reference=claim)
        self.assertEqual(ac.claimed(self.store.load(self.id), "14:1:1"), claim)
        self.assertEqual(self.plan(attempt("active"), claim=claim), ())
        self.now = T0 + 31 * MINUTE
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        # A resume claims its new span, as the plan's last operation.
        self.assertEqual([op.kind for op in self.plan(resumed, claim=claim)],
                         ["reap", "acquire", "unpark", "claim"])
        self.assertEqual(self.plan(resumed, claim=claim)[-1],
                         Op("claim", executor_id="14:1:2", reference=claim))
        # An expired launch that is not reacquired claims nothing.
        self.assertEqual(self.plan(attempt("active"), claim=claim), ())
        self.assertIsNone(ac.claimed(self.store.load(self.id), "14:1:2"))

    def test_an_unavailable_owner_gives_the_span_up(self):
        self.assertEqual(self.plan(attempt("active"), bare=True, owner_gone=True),
                         (Op("create"),))
        self.acquire()
        self.assertEqual(self.plan(attempt("active"), owner_gone=True, claim="c"),
                         (Op("release"),))
        self.now = T0 + 31 * MINUTE
        self.assertEqual(self.plan(attempt("active"), owner_gone=True),
                         (Op("reap", reason="expiry"), Op("unpark", reason="resumed")))

    def test_the_capacity_gate_parks_and_a_release_wakes(self):
        refused = attempt("suspended", blocked_on="host_capacity")
        park, wake = (Op("park", reason="suspended:host_capacity"),
                      Op("unpark", reason="capacity_released"))
        self.acquire()
        # A refusal and a later release in one write keep their order.
        self.assertEqual(self.plan(refused, gate_open=True), (park, Op("release"), wake))
        self.assertEqual(self.plan(refused), (park, Op("release")))
        self.apply(self.plan(refused), None)
        self.assertEqual(self.plan(refused), ())
        self.assertEqual(self.plan(refused, gate_open=True), (wake,))
        self.apply(self.plan(refused, gate_open=True), None)
        self.assertEqual((self.held()[0], self.plan(refused, gate_open=True)), ("created", ()))
        # The gate is read from the block: closed again, the transaction parks again.
        self.assertEqual(self.plan(refused), (park,))
        # No other suspension is woken by an open gate.
        self.assertEqual(self.plan(attempt("suspended", blocked_on="transport"),
                                   gate_open=True), (Op("park", reason="suspended:transport"),))

    def test_a_remainder_record_is_planned_by_the_same_rows(self):
        remainder = {"remainder": 1, "state": "active", "worktree": WORKTREE,
                     "launches": [{"kind": "fresh"}], "deadline_at": DEADLINE,
                     "blocked_on": None, "result_source": None, "result": None}
        self.assertEqual(self.plan(remainder, bare=True, current="14:r1:1", claim="c"), (
            Op("create"), Op("acquire", executor_id="14:r1:1", ttl_ms=30 * MINUTE),
            Op("claim", executor_id="14:r1:1", reference="c")))
        gone = {**remainder, "state": "suspended", "blocked_on": "owner_unavailable"}
        self.assertEqual(self.plan(gone, bare=True, current="14:r1:1"), (
            Op("create"), Op("park", reason="suspended:owner_unavailable")))
        failed = {**remainder, "state": "failed", "result_source": "owner",
                  "result": result("failed")}
        self.assertEqual(self.plan(failed, bare=True, bound=True, current="14:r1:1"),
                         (Op("create"), Op("seal", reason="owner:failed")))

    def test_a_delivered_issue_gives_up_launch_spans_and_plans_the_succeeded_seal(self):
        seal = Op("seal_succeeded", executor_id="14:1:seal", reason="delivered")
        merged = attempt("merged", source="owner", result=result("merged", "b" * 40))
        self.assertEqual(self.plan(attempt("active"), bare=True, delivered=True),
                         (Op("create"), seal))
        self.assertEqual(self.plan(merged, bare=True, delivered=True, latest=False), ())
        self.acquire()
        self.assertEqual(self.plan(attempt("active"), delivered=True, claim="c"),
                         (Op("release"), seal))
        self.assertEqual(self.plan(merged, delivered=True, digest="sha256:" + "1" * 64),
                         (Op("record_result", executor_id="14:1:1"), Op("release"), seal))
        self.now = T0 + 31 * MINUTE
        self.assertEqual(self.plan(attempt("active"), delivered=True),
                         (Op("reap", reason="expiry"), seal))
        self.assertEqual(self.plan(
            {"remainder": 2, "state": "active", "launches": [{}], "deadline_at": DEADLINE,
             "blocked_on": None, "result_source": None, "result": None},
            delivered=True, current="14:r2:1")[-1],
            Op("seal_succeeded", executor_id="14:r2:seal", reason="delivered"))

    def test_only_a_delivered_record_may_be_in_the_seals_forward_states(self):
        seal = Op("seal_succeeded", executor_id="14:1:seal", reason="delivered")
        held = self.store.acquire(self.id, executor_id="14:1:seal", subject_path=WORKTREE,
                                  ttl_ms=MINUTE).custody
        # The seal's own span is left open, at every state the seal passes.
        self.assertEqual(self.plan(attempt("active"), delivered=True), (seal,))
        for target in ac.FORWARD_STATES:
            self.store.advance(self.id, target, reason="delivered", custody=held)
            self.assertEqual(self.plan(attempt("active"), delivered=True), (seal,), target)
            with self.assertRaises(ac.ProjectionMismatch):
                self.plan(attempt("active"))
        self.store.settle_proof(self.store.start_cohort(held).custody)
        self.assertEqual(self.store.load(self.id).state, "succeeded")
        self.assertEqual(self.plan(attempt("active"), delivered=True), ())
        with self.assertRaises(ac.ProjectionMismatch):
            self.plan(attempt("active"))

    def test_a_cutover_plan_interrupted_after_any_operation_converges(self):
        resumed = attempt("active", launches=2, deadline="2026-08-13T21:01:00Z")
        refused = attempt("suspended", blocked_on="host_capacity")
        for lapsed, attempt_, facts, length in (
                (True, resumed, {"claim": "c"}, 4), (False, refused, {"gate_open": True}, 3),
                (True, attempt("active"), {"owner_gone": True}, 2)):
            def start():
                self.fresh()
                self.acquire()
                self.now = T0 + (31 * MINUTE if lapsed else 0)

            start()
            whole = self.plan(attempt_, **facts)
            self.assertEqual(len(whole), length, facts)
            self.apply(whole, None)
            reached = self.held()
            self.assertEqual(self.plan(attempt_, **facts), (), facts)
            for cut in range(1, length):
                with self.subTest(facts=facts, applied=cut):
                    start()
                    self.apply(self.plan(attempt_, **facts)[:cut], None)
                    self.apply(self.plan(attempt_, **facts), None)
                    self.assertEqual((self.held(), self.plan(attempt_, **facts)),
                                     (reached, ()))


if __name__ == "__main__":
    unittest.main()
