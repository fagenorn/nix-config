"""Attempt run identity on workflow-state ledgers (#337), driven through the CLI from source.

Run: just agent-workflow-tests
"""

import hashlib
import json
import re
import shutil
import unittest

from agent_tools import attempt_identity as ai
from agent_tools.transaction_core import TransactionStore

from .test_delivered_control import DeliveredControlHarness
from .test_workflow_state import DEFAULT_NOW, LifecycleHarness

CORE = re.compile(
    r"^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class MigrationFixtures(LifecycleHarness):
    """Legacy-dialect ledgers shaped like the retained ones (D21, D24).

    The fixtures run on `LifecycleHarness` (its root, `run_cli`, `read_state`,
    `control`). The issue-207 ledger comes from the #220 driver run in its own
    root and HOME; only its parsed state crosses into this test's root.
    """

    def store(self):
        return TransactionStore(self.store_root)

    def delivered_207(self):
        class Driver(DeliveredControlHarness, unittest.TestCase):
            def runTest(self):
                pass

        Driver.setUpClass()
        driver = Driver()
        self.addCleanup(driver.doCleanups)
        driver.deliver_through_remainder()
        return json.loads(driver.ledger.read_text(encoding="utf-8"))

    def install_orchestrated(self, handle):
        source = self.delivered_207()
        self.install_legacy(source, handle)
        return source

    def run_cli_json(self, *args, ok=True):
        completed = self.run_cli(*args, ok=ok)
        return completed, (json.loads(completed.stdout) if ok else None)


class InitRunMintTest(MigrationFixtures, unittest.TestCase):
    def test_creation_key_mints_one_core_run(self):
        args = ("init-run", "--repo-root", self.root, "--creation-key", "k-337", "--now",
                DEFAULT_NOW)
        first = json.loads(self.run_cli(*args).stdout)
        second = json.loads(self.run_cli(*args).stdout)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertRegex(first["run_id"], CORE)
        self.run_id = first["run_id"]
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["transaction_id"]), (8, first["run_id"]))
        self.assertEqual(self.store().lookup(ai.run_key("k-337")), first["run_id"])
        runs = [p.name for p in self.workflows_dir.iterdir() if not p.name.startswith(".")]
        self.assertEqual(runs, [first["run_id"]])
        self.assertEqual((self.store_root / ".gitignore").read_text(), "*\n")

    def test_run_id_only_rebootstraps_and_never_creates(self):
        self.init_run()
        before = self.tree_snapshot()
        refused = self.run_cli("init-run", "--repo-root", self.root, "--run-id", "new-x",
                               ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), before)
        again = json.loads(self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                                        self.run_id).stdout)
        self.assertEqual(again["run_id"], self.run_id)
        self.assertEqual(self.tree_snapshot(), before)

    def test_bad_or_doubled_arguments_are_usage_errors(self):
        for extra in (("--creation-key", "-bad"), ("--creation-key", "a b"),
                      ("--creation-key", "k", "--run-id", "x"), ()):
            with self.subTest(extra=extra):
                refused = self.run_cli("init-run", "--repo-root", self.root, *extra, ok=False)
                self.assertEqual(refused.returncode, 2)
                self.assertFalse((self.root / ".superpowers").exists())


class MigrateOnWriteTest(MigrationFixtures, unittest.TestCase):
    def test_a_locked_write_binds_a_legacy_ledger_under_its_handle(self):
        self.install_orchestrated("orchestrate-21-24-r2")
        # A no-op locked command: its only write is the migration (D14).
        self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id)
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["run_id"]), (8, "orchestrate-21-24-r2"))
        key = ai.legacy_key("orchestrate-21-24-r2")
        self.assertEqual(self.store().lookup(key), state["transaction_id"])
        subject = self.store().load(state["transaction_id"]).subject
        self.assertEqual((subject["kind"], subject["prior_run"], subject["alias"]["retry"]),
                         ("orchestrated", None, 2))

    def test_unlocked_reads_check_without_writing(self):
        self.install_orchestrated("orchestrate-21-24-r2")
        before = self.tree_snapshot()
        reply = self.run_cli("check-launch", "--repo-root", self.root, "--run-id", self.run_id,
                             "--action-id", "207:r1:1")
        self.assertEqual(self.tree_snapshot(), before)
        self.assertIn('"action_id":"207:r1:1"', reply.stdout)

    def test_refused_ledgers_keep_their_bytes_and_get_no_index_entry(self):
        source = self.delivered_207()
        cases = {"issue-14-test": "unknown_dialect",
                 "orchestrate-21": "ambiguous_lineage"}
        for handle, reason in cases.items():
            with self.subTest(handle=handle):
                state = dict(source)
                if handle == "orchestrate-21":
                    state = {**source, "prior_run": "orchestrate-20"}
                self.install_legacy(state, handle)
                before = self.tree_snapshot()
                for refused in (
                        self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                                     handle, "--action-id", "207:r1:1", ok=False),
                        self.progress(issue=207, ok=False)):
                    self.assertEqual(refused.returncode, 2)
                    self.assertIn(reason, refused.stderr)
                self.assertEqual(self.tree_snapshot(), before)

    def test_a_schema_8_ledger_whose_binding_breaks_is_refused(self):
        self.init_run()
        state = self.read_state()
        other = json.loads(self.run_cli("init-run", "--repo-root", self.root,
                                        "--creation-key", "other").stdout)["run_id"]
        self.write_state({**state, "transaction_id": other})
        before = self.tree_snapshot()
        refused = self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                               self.run_id, "--action-id", "1:1:1", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), before)


class DirectReservationTest(MigrationFixtures, unittest.TestCase):
    def test_control_and_rebootstrap_refuse_a_direct_identity_by_identity(self):
        # Task 3 adds the minted (rel_) direct case; here the legacy name is the identity.
        self.init_run()
        self.install_legacy(self.read_state(), "direct-14-000001")
        before = self.tree_snapshot()
        refused = self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                               "direct-14-000001", ok=False)
        self.assertIn("reserved for direct-owner", refused.stderr)
        self.assertEqual(self.tree_snapshot(), before)


class DirectOwnerIdentityTest(MigrationFixtures, unittest.TestCase):
    def first_direct_run(self, issue=41):
        return self.acquire_direct(issue=issue)["run_id"]

    def install_terminal_legacy_direct(self, handle):
        """Leave issue 41 with one terminal run, retained as a legacy-named schema-7 ledger.

        The run is driven like the new-run test of `test_direct_new_run_records_the_prior_run_link`;
        its minted directory and index entry are then removed, so only `handle` names
        sequence 1.
        """
        owner = self.acquire_direct(issue=41)
        minted = owner["run_id"]
        self.run_id = minted
        self.finish(1, {**self.merged_result(41), "state": "stopped", "pr_url": None,
                        "merge_sha": None, "issue_closed": False, "notes": "semantic stop"},
                    issue=41, now="2026-08-20T10:05:00Z")
        self.terminal_worktree = owner["worktree"]
        state = self.read_state()
        self.install_legacy(state, handle)
        shutil.rmtree(self.workflows_dir / minted)
        key = ai.direct_key(41, 1)
        (self.store_root / "creation-keys" /
         f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json").unlink()
        self.assertIsNone(self.store().lookup(key))

    def new_run_fields(self, issue):
        return {"issue": issue, "new_run": True, "now": "2026-08-20T10:10:00Z",
                "tracker": self.tracker_fact(issue),
                "worktree": self.worktree_fact(issue, recorded={
                    "path": self.terminal_worktree, "state": "matching_issue_branch"})}

    def test_a_first_direct_run_is_minted_and_named_by_its_transaction(self):
        run_id = self.first_direct_run()
        self.assertRegex(run_id, CORE)
        self.assertEqual(self.direct_run_id(41, 1), run_id)
        self.run_id = run_id
        state = self.read_state()
        self.assertEqual((state["transaction_id"], state["prior_run"]), (run_id, None))
        subject = self.store().load(run_id).subject
        self.assertEqual((subject["kind"], subject["issue"], subject["sequence"],
                          subject["alias"]), ("direct", 41, 1, None))
        self.assertFalse(any(p.name.startswith("direct-41-")
                             for p in self.workflows_dir.iterdir()))

    def test_a_new_run_after_a_legacy_terminal_links_the_legacy_handle(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertRegex(reply["run_id"], CORE)
        self.run_id = reply["run_id"]
        self.assertEqual(self.read_state()["prior_run"], "direct-41-000001")
        self.assertEqual(self.store().load(reply["run_id"]).subject["sequence"], 2)
        legacy = json.loads((self.workflows_dir / "direct-41-000001" / "state.json")
                            .read_text())
        self.assertEqual(legacy["schema_version"], 8)  # bound and committed (D14)
        self.assertEqual(self.store().lookup(ai.direct_key(41, 1)),
                         legacy["transaction_id"])

    def test_a_reserved_slot_without_a_ledger_is_reused(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        plan = ai.minted_plan(identity=ai.RunIdentity("direct", 41, 2),
                              prior_run="direct-41-000001", caller_key=None)
        self.store_root.mkdir(parents=True, exist_ok=True)
        reserved = self.store().create(plan.creation_key, plan.subject_json(),
                                       **ai.creation_arguments(plan)).transaction_id
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertEqual(reply["run_id"], reserved)
        self.assertIsNone(self.store().lookup(ai.direct_key(41, 3)))

    def test_a_refused_legacy_ledger_refuses_the_call_and_mints_nothing(self):
        self.init_run()
        state = {**self.read_state(), "prior_run": "direct-42-000001"}
        self.install_legacy(state, "direct-41-000002")
        ledger = self.workflows_dir / "direct-41-000002" / "state.json"
        before = ledger.read_bytes()
        refused = self.direct_owner_raw(issue=41, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("ambiguous_lineage", refused.stderr)
        self.assertEqual(ledger.read_bytes(), before)
        for sequence in (1, 2, 3):
            self.assertIsNone(self.store().lookup(ai.direct_key(41, sequence)))

    def test_a_valid_ledger_before_a_refused_one_stays_unbound(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        first = self.workflows_dir / "direct-41-000001" / "state.json"
        self.install_legacy({**json.loads(first.read_text()), "prior_run": "direct-42-000001"},
                            "direct-41-000002")
        second = self.workflows_dir / "direct-41-000002" / "state.json"
        before = (first.read_bytes(), second.read_bytes())
        refused = self.direct_owner_raw(issue=41, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("ambiguous_lineage", refused.stderr)
        self.assertEqual((first.read_bytes(), second.read_bytes()), before)  # D23
        for sequence in (1, 2, 3):
            self.assertIsNone(self.store().lookup(ai.direct_key(41, sequence)))

    def test_control_and_rebootstrap_refuse_a_minted_direct_run_by_identity(self):
        run_id = self.first_direct_run()
        self.run_id = run_id
        before = self.tree_snapshot()
        control = self.control_raw(now="2026-08-20T10:30:00Z", issues=[41],
                                   tracker=[self.tracker_fact(41)], worktrees=[], ok=False)
        self.assertEqual(control.returncode, 2)
        self.assertIn("reserved for direct-owner", control.stderr)
        rebootstrap = self.run_cli("init-run", "--repo-root", self.root, "--run-id", run_id,
                                   ok=False)
        self.assertEqual(rebootstrap.returncode, 2)
        self.assertIn("reserved for direct-owner", rebootstrap.stderr)
        self.assertEqual(self.tree_snapshot(), before)
