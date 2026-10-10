"""Attempt run identity on workflow-state ledgers (#337), driven through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import re
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
