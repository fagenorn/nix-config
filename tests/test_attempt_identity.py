"""Attempt run identity: grammar, plan, subject and report (#337 D1-D3, D6, D7).

Run: just agent-workflow-tests
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_identity as ai
from agent_tools import attempt_store
from agent_tools.transaction_core import StateInvalid, TransactionStore

CORE_ID = "rel_0190f0e0-0000-7000-8000-000000000000"


def schema7(run_id, *, issues=("41",), prior_run=None):
    return {"schema_version": 7, "run_id": run_id, "prior_run": prior_run,
            "issues": {key: {} for key in issues}}


class GrammarTest(unittest.TestCase):
    def test_each_dialect_classifies_and_aliases_exactly(self):
        cases = {
            "direct-100-000003": ("direct", [100], None, None),
            "orchestrate-21-24-r2": ("orchestrate", [21, 24], None, 2),
            "issues-29-30-20260817-r2": ("issues", [29, 30], "20260817", 2),
            "issues-29-30": ("issues", [29, 30], None, None),
            "run-20261009-337-338-339": ("run", [337, 338, 339], "20261009", None),
        }
        for run_id, (dialect, issues, date, retry) in cases.items():
            with self.subTest(run_id=run_id):
                self.assertEqual(ai.classify(run_id), dialect)
                self.assertEqual(ai.legacy_alias(run_id), {
                    "dialect": dialect, "run_id": run_id, "issues": issues,
                    "date": date, "retry": retry})
        self.assertEqual(ai.classify(CORE_ID), "core")

    def test_anything_else_is_unknown_dialect(self):
        for run_id in ("issue-14-test", "replay", "direct-41-000000", "direct-41-1",
                       "orchestrate", "orchestrate-21-r0", "issues-12345678",
                       "run-20261399-337", "run-20261009", "orchestrate-021",
                       "Orchestrate-21", CORE_ID, "rel_not-a-uuid", 7, None):
            with self.subTest(run_id=run_id):
                if run_id != CORE_ID:
                    self.assertIsNone(ai.classify(run_id))
                if isinstance(run_id, str):
                    with self.assertRaises(ai.MigrationRefused) as caught:
                        ai.legacy_alias(run_id)
                    self.assertEqual(caught.exception.reason, "unknown_dialect")

    def test_keys(self):
        self.assertEqual(ai.direct_key(41, 2), "attempt-run/v1:direct:41:2")
        self.assertEqual(ai.legacy_key("run-20261009-337"),
                         "attempt-run/v1:legacy:run-20261009-337")
        self.assertEqual(ai.run_key("orchestrate-issues:1791590400:337-338"),
                         "attempt-run/v1:run:orchestrate-issues:1791590400:337-338")
        for bad in ("", "-x", "a/b", "a b", "x" * 129):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                ai.run_key(bad)


class PlanTest(unittest.TestCase):
    def test_direct_plan_keeps_recorded_lineage(self):
        plan = ai.plan_migration(schema7("direct-41-000002", prior_run="direct-41-000001"))
        self.assertEqual(plan.creation_key, "attempt-run/v1:direct:41:2")
        self.assertEqual(plan.subject_json(), {
            "schema": "attempt-run/v1", "kind": "direct", "issue": 41, "sequence": 2,
            "prior_run": "direct-41-000001", "alias": ai.legacy_alias("direct-41-000002")})

    def test_grouped_run_records_its_name_not_membership(self):
        plan = ai.plan_migration(schema7("run-20261009-337-338-339", issues=("337",)))
        self.assertEqual(plan.creation_key, "attempt-run/v1:legacy:run-20261009-337-338-339")
        subject = plan.subject_json()
        self.assertEqual((subject["kind"], subject["issue"], subject["prior_run"]),
                         ("orchestrated", None, None))
        self.assertEqual(subject["alias"]["issues"], [337, 338, 339])
        self.assertNotIn("issues", subject)

    def test_retry_suffix_links_nothing(self):
        subject = ai.plan_migration(schema7("orchestrate-21-24-r2", issues=())).subject_json()
        self.assertEqual((subject["prior_run"], subject["alias"]["retry"]), (None, 2))

    def test_refusals_carry_closed_reasons(self):
        cases = {
            "unknown_dialect": [schema7("issue-14-test"), schema7(CORE_ID)],
            "ambiguous_lineage": [
                schema7("orchestrate-21-24", prior_run="orchestrate-21"),
                schema7("direct-41-000002", issues=("41", "42")),
                schema7("direct-41-000002", issues=()),
                schema7("direct-41-000002", prior_run="direct-42-000001"),
                schema7("direct-41-000002", prior_run="direct-41-000002"),
                schema7("direct-41-000002", prior_run="direct-41-000003"),
                schema7("direct-41-000002", prior_run="orchestrate-41")],
        }
        for reason, documents in cases.items():
            for document in documents:
                with self.subTest(reason=reason, document=document), \
                        self.assertRaises(ai.MigrationRefused) as caught:
                    ai.plan_migration(document)
                self.assertEqual(caught.exception.reason, reason)
                self.assertIn(caught.exception.reason, ai.REFUSAL_REASONS)

    def test_schema_refusal(self):
        for version in (1, 7, 8, 9, 10):
            self.assertIsNone(ai.schema_refusal({"schema_version": version}))
        for document in ({"schema_version": 11}, {"schema_version": 0},
                         {"schema_version": True}, {"schema_version": "7"}, {}, [], None):
            with self.subTest(document=document):
                self.assertEqual(ai.schema_refusal(document), "unknown_schema")

    def test_plans_are_immutable_and_deterministic(self):
        document = schema7("direct-41-000001")
        first, second = ai.plan_migration(document), ai.plan_migration(document)
        self.assertEqual(first, second)
        first.subject_json()["kind"] = "x"
        self.assertEqual(first.subject["kind"], "direct")
        with self.assertRaises(TypeError):
            first.subject["kind"] = "x"


class SubjectTest(unittest.TestCase):
    def test_minted_subjects_and_handles(self):
        direct = ai.minted_plan(identity=ai.RunIdentity("direct", 41, 3),
                                prior_run="direct-41-000002", caller_key=None)
        self.assertEqual(direct.creation_key, "attempt-run/v1:direct:41:3")
        self.assertIsNone(direct.subject["alias"])
        orchestrated = ai.minted_plan(identity=ai.RunIdentity("orchestrated", None, None),
                                      prior_run=None, caller_key="k1")
        self.assertEqual(orchestrated.creation_key, "attempt-run/v1:run:k1")
        for plan in (direct, orchestrated):
            self.assertIsNone(ai.subject_violation(plan.subject_json()))
        self.assertEqual(ai.subject_handle(direct.subject, CORE_ID), CORE_ID)
        legacy = ai.plan_migration(schema7("direct-41-000001"))
        self.assertEqual(ai.subject_handle(legacy.subject, CORE_ID), "direct-41-000001")
        self.assertEqual(ai.identity_of(legacy.subject), ai.RunIdentity("direct", 41, 1))
        self.assertIsNotNone(ai.subject_violation({**legacy.subject_json(), "extra": 1}))

    def test_prior_run_rule(self):
        direct = ai.RunIdentity("direct", 41, 3)
        successor = "rel_0190f0e0-0000-7000-8000-000000000001"  # a run other than CORE_ID
        for prior in (None, CORE_ID, "direct-41-000002"):
            self.assertIsNone(ai.prior_run_violation(direct, prior, run_id=successor))
        for prior in ("direct-41-000003", "direct-40-000001", "orchestrate-41", 5):
            with self.subTest(prior=prior):
                self.assertIsNotNone(ai.prior_run_violation(direct, prior, run_id="x"))
        # A run cannot precede itself.
        self.assertIsNotNone(ai.prior_run_violation(direct, CORE_ID, run_id=CORE_ID))
        orchestrated = ai.RunIdentity("orchestrated", None, None)
        self.assertIsNone(ai.prior_run_violation(orchestrated, None, run_id="x"))
        self.assertIsNotNone(ai.prior_run_violation(orchestrated, "direct-41-000001", run_id="x"))

    def test_creation_arguments_are_the_inert_ones(self):
        plan = ai.plan_migration(schema7("direct-41-000001"))
        arguments = ai.creation_arguments(plan)
        self.assertEqual(arguments, {
            "concurrency_keys": ["attempt-run:attempt-run/v1:direct:41:1"],
            "proof": {"units": [], "obligations": [], "collectors": {}},
            "recovery": {"effects": {}, "units": []}, "authority_class": "attempt-run"})
        arguments["proof"]["units"].append(1)
        self.assertEqual(ai.creation_arguments(plan)["proof"]["units"], [])


class ReportTest(unittest.TestCase):
    def row(self, ledger, verdict, reason=None):
        return {**{field: None for field in ai.REPORT_ROW_FIELDS},
                "ledger": ledger, "verdict": verdict, "reason": reason}

    def test_rows_sorted_and_counted(self):
        value = ai.report("dry_run", [self.row("b", "migrate"),
                                      self.row("a", "refused", "unknown_dialect")])
        self.assertEqual(value["schema"], "attempt-migration-report/v1")
        self.assertEqual([row["ledger"] for row in value["ledgers"]], ["a", "b"])
        self.assertEqual(value["counts"],
                         {"current": 0, "migrate": 1, "migrated": 0, "refused": 1})

    def test_malformed_input_is_refused(self):
        for mode, rows in (("other", []), ("apply", [{"ledger": "a"}]),
                           ("apply", [self.row("a", "maybe")]),
                           ("apply", [self.row("a", "refused", "because")])):
            with self.subTest(mode=mode, rows=rows), self.assertRaises(ValueError):
                ai.report(mode, rows)


class StoreRoundTripTest(unittest.TestCase):
    def test_a_created_run_transaction_is_found_by_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TransactionStore(Path(tmp))
            plan = ai.plan_migration(schema7("direct-41-000001"))
            created = store.create(plan.creation_key, plan.subject_json(),
                                   **ai.creation_arguments(plan))
            self.assertEqual(store.lookup(plan.creation_key), created.transaction_id)
            self.assertEqual(created.state, "created")


class IssueSetKeyTest(unittest.TestCase):
    def test_the_key_is_the_sorted_unique_issue_numbers_and_an_ordinal(self):
        self.assertEqual(ai.issue_set_caller_key([14, 12, 14], 2), "issue-set:12-14:2")
        self.assertEqual(ai.run_key(ai.issue_set_caller_key((7,), 1)),
                         "attempt-run/v1:run:issue-set:7:1")
        for issues, ordinal in (([], 1), ([0], 1), ([True], 1), (["7"], 1), ([7], 0),
                                (list(range(1, 60)), 1)):
            with self.subTest(issues=issues, ordinal=ordinal):
                with self.assertRaises(ValueError):
                    ai.issue_set_caller_key(issues, ordinal)


class HoldGrammarTest(unittest.TestCase):
    """Issue 475 D5: the issue-hold/v1 key and closed subject."""

    def test_the_key_and_subject_name_the_issue_and_the_run(self):
        plan = ai.hold_plan(73, 2, CORE_ID)
        self.assertEqual((plan.creation_key, plan.subject_json()), (
            "issue-hold/v1:73:2", {"schema": "issue-hold/v1", "issue": 73, "run": CORE_ID}))
        self.assertIsNone(ai.hold_violation(plan.subject_json()))
        self.assertEqual(ai.creation_arguments(plan)["concurrency_keys"],
                         ["attempt-run:issue-hold/v1:73:2"])

    def test_anything_else_is_not_a_hold_subject(self):
        good = {"schema": "issue-hold/v1", "issue": 73, "run": CORE_ID}
        for subject in ({**good, "extra": 1}, {**good, "schema": "attempt-run/v1"},
                        {**good, "issue": 0}, {**good, "issue": True}, {**good, "issue": "73"},
                        {**good, "run": "orchestrate-73"}, [], None):
            with self.subTest(subject=subject):
                self.assertIsNotNone(ai.hold_violation(subject))
        for ordinal in (0, True, "1"):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(ValueError):
                    ai.hold_plan(73, ordinal, CORE_ID)


class HoldPointerStoreTest(unittest.TestCase):
    """Issue 475 D5, D6: `settle_holds` writes the pointers `hold_runs` reads."""

    ORCHESTRATED = ai.RunIdentity("orchestrated", None, None)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Path(directory.name) / "attempt-transactions"

    def run_transaction(self, key):
        return attempt_store.mint_run(self.store, attempt_store.creation_key_plan(key))

    @staticmethod
    def state(run, **states):
        return {"transaction_id": run, "issues": {
            str(issue): {"attempts": [{"state": state}], "delivery_remainders": []}
            for issue, state in ((int(name[1:]), value) for name, value in states.items())}}

    def settle(self, state, identity=ORCHESTRATED):
        attempt_store.settle_holds(self.store, state, identity, now_ms=1_790_000_000_000)

    def pointers(self, issue):
        core = TransactionStore(self.store)
        found, ordinal = [], 1
        while (transaction_id := core.lookup(ai.hold_key(issue, ordinal))) is not None:
            found.append(core.load(transaction_id).subject["run"])
            ordinal += 1
        return found

    def test_each_held_issue_gets_one_pointer_however_often_the_run_writes(self):
        run = self.run_transaction("first")
        for _ in range(2):
            self.settle(self.state(run, i73="suspended", i74="merged", i75="active"))
        self.assertEqual((self.pointers(73), self.pointers(74), self.pointers(75)),
                         ([run], [], [run]))
        self.assertEqual(list(attempt_store.hold_runs(self.store, 73)), [run])

    def test_a_second_run_holding_the_issue_takes_the_next_ordinal(self):
        first, second = self.run_transaction("first"), self.run_transaction("second")
        self.settle(self.state(first, i73="active"))
        self.settle(self.state(second, i73="handed_off"))
        self.settle(self.state(first, i73="active"))
        self.assertEqual(self.pointers(73), [first, second])
        self.assertEqual(list(attempt_store.hold_runs(self.store, 73)), [first, second])

    def test_a_direct_run_and_a_settled_run_create_nothing(self):
        self.settle(self.state(CORE_ID, i73="active"), ai.RunIdentity("direct", 73, 1))
        self.assertFalse(self.store.exists())
        run = self.run_transaction("first")
        self.settle(self.state(run, i73="active"))
        before = sorted(path for path in self.store.rglob("*"))
        self.settle(self.state(run, i73="active"))
        self.assertEqual(sorted(path for path in self.store.rglob("*")), before)
        self.assertEqual(list(attempt_store.hold_runs(self.store, 99)), [])

    def test_an_index_entry_that_is_not_a_hold_pointer_is_refused(self):
        run = self.run_transaction("first")
        plan = ai.hold_plan(73, 1, run)
        TransactionStore(self.store).create(plan.creation_key, {"schema": "other"},
                                            **ai.creation_arguments(plan))
        with self.assertRaises(attempt_store.StoreRefused):
            list(attempt_store.hold_runs(self.store, 73))
