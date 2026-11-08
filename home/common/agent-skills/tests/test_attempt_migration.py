"""Attempt run identity on workflow-state ledgers (#337), driven through the CLI from source.

Run: just agent-workflow-tests
"""

import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_identity as ai
from agent_tools.transaction_core import TransactionStore

from .test_delivered_control import DeliveredControlHarness
from .test_workflow_state import DEFAULT_NOW, SCRIPT, LifecycleHarness

BASE_COMMIT = "eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7"
REPO = Path(__file__).resolve().parents[4]
CORE = re.compile(
    r"^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
# The issue-207 ledger text per concrete test class (issue 500 D4, D9).
_DELIVERED_207: dict[type, str] = {}


class MigrationFixtures(LifecycleHarness):
    """Legacy-dialect ledgers shaped like the retained ones (D21, D24).

    The fixtures run on `LifecycleHarness` (its root, `run_cli`, `read_state`,
    `control`). The issue-207 ledger comes from the #220 driver run in its own
    root and HOME; only its parsed state crosses into this test's root.
    """

    def store(self):
        return TransactionStore(self.store_root)

    def delivered_207(self):
        """The issue-207 ledger's parsed state, a fresh parse on every call (issue 500 D4).

        The first call in a concrete test class runs the #220 driver and keeps the
        ledger's text for that class; the driver's root and HOME are removed before
        this method returns, and a failed run keeps nothing.
        """
        owner = type(self)
        text = _DELIVERED_207.get(owner)
        if text is None:
            class Driver(DeliveredControlHarness, unittest.TestCase):
                def runTest(self):
                    pass

            Driver.setUpClass()
            driver = Driver()
            try:
                driver.deliver_through_remainder()
                text = driver.ledger.read_text(encoding="utf-8")
            finally:
                driver.doCleanups()
            _DELIVERED_207[owner] = text
            owner.addClassCleanup(_DELIVERED_207.pop, owner, None)
        return json.loads(text)

    def install_orchestrated(self, handle):
        source = self.delivered_207()
        self.install_legacy(source, handle)
        return source

    def new_run_fields(self, issue):
        return {"issue": issue, "new_run": True, "now": "2026-08-20T10:10:00Z",
                "tracker": self.tracker_fact(issue),
                "worktree": self.worktree_fact(issue, recorded={
                    "path": self.terminal_worktree, "state": "matching_issue_branch"})}

    def install_direct_pair(self):
        """Issue 41 as two retained legacy ledgers, `direct-41-000001` (terminal) and
        `direct-41-000002` (its `new_run` successor), with their minted runs and index
        entries removed so only the legacy ledgers name the issue (D21)."""
        owner = self.acquire_direct(issue=41)
        first_id = owner["run_id"]
        self.run_id = first_id
        self.finish(1, {**self.merged_result(41), "state": "stopped", "pr_url": None,
                        "merge_sha": None, "issue_closed": False, "notes": "semantic stop"},
                    issue=41, now="2026-08-20T10:05:00Z")
        self.terminal_worktree = owner["worktree"]
        first = self.read_state()
        second_id = self.direct_owner(**self.new_run_fields(41))["run_id"]
        self.run_id = second_id
        second = self.read_state()
        self.install_legacy(first, "direct-41-000001")
        self.install_legacy({**second, "prior_run": "direct-41-000001"}, "direct-41-000002")
        for minted in (first_id, second_id):
            shutil.rmtree(self.workflows_dir / minted)
        for sequence in (1, 2):
            key = ai.direct_key(41, sequence)
            (self.store_root / "creation-keys" /
             f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json").unlink()
            self.assertIsNone(self.store().lookup(key))

    def edit_ledger(self, handle, **fields):
        path = self.workflows_dir / handle / "state.json"
        state = {**json.loads(path.read_text(encoding="utf-8")), **fields}
        path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")

    def install_refusal_fixtures(self):
        """Ledgers each refused for a different reason; returns `{handle: reason}`."""
        source = self.delivered_207()
        self.install_legacy(source, "issue-14-test")
        self.install_legacy(source, "orchestrate-90")
        self.edit_ledger("orchestrate-90", schema_version=12)
        self.install_legacy({**source, "prior_run": "orchestrate-90"}, "orchestrate-91")
        self.install_direct_pair()
        shutil.rmtree(self.workflows_dir / "direct-41-000001")
        self.edit_ledger("direct-41-000002", prior_run="direct-42-000001")
        extra = {**source, "issues": {key: {**issue, "extra": 1}
                                      for key, issue in source["issues"].items()}}
        self.install_legacy(extra, "orchestrate-92", version=1)
        return {"issue-14-test": "unknown_dialect", "orchestrate-90": "unknown_schema",
                "orchestrate-91": "ambiguous_lineage", "direct-41-000002": "ambiguous_lineage",
                "orchestrate-92": "invalid_state"}

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
        self.assertEqual((state["schema_version"], state["transaction_id"]), (11, first["run_id"]))
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
        self.assertEqual((state["schema_version"], state["run_id"]), (11, "orchestrate-21-24-r2"))
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

    def test_each_delivered_207_call_is_the_callers_own_copy(self):
        """Issue 500 D4, D6: a mutation of one call's state never reaches the next call's."""
        first = self.delivered_207()
        self.assertTrue(first["issues"]["207"]["attempts"])
        expected = json.dumps(first, sort_keys=True)
        second = self.delivered_207()
        second["mutated"] = True
        second["issues"]["207"]["attempts"][0]["mutated"] = True
        second["issues"]["207"]["attempts"].append({"mutated": True})
        second["issues"]["207"]["delivery_remainders"].clear()
        self.assertEqual(json.dumps(self.delivered_207(), sort_keys=True), expected)

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
        self.run_cli("migrate", "--repo-root", self.root, "--apply")
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertRegex(reply["run_id"], CORE)
        self.run_id = reply["run_id"]
        self.assertEqual(self.read_state()["prior_run"], "direct-41-000001")
        self.assertEqual(self.store().load(reply["run_id"]).subject["sequence"], 2)
        legacy = json.loads((self.workflows_dir / "direct-41-000001" / "state.json")
                            .read_text())
        self.assertEqual(legacy["schema_version"], 11)  # bound and committed (D14)
        self.assertEqual(self.store().lookup(ai.direct_key(41, 1)),
                         legacy["transaction_id"])

    def test_a_reserved_slot_without_a_ledger_is_reused(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        plan = ai.minted_plan(identity=ai.RunIdentity("direct", 41, 2),
                              prior_run="direct-41-000001", caller_key=None)
        self.store_root.mkdir(parents=True, exist_ok=True)
        reserved = self.store().create(plan.creation_key, plan.subject_json(),
                                       **ai.creation_arguments(plan)).transaction_id
        self.run_cli("migrate", "--repo-root", self.root, "--apply")
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertEqual(reply["run_id"], reserved)
        self.assertIsNone(self.store().lookup(ai.direct_key(41, 3)))

    def test_a_legacy_ledger_the_index_never_reaches_is_not_read(self):
        self.init_run()
        state = {**self.read_state(), "prior_run": "direct-42-000001"}
        self.install_legacy(state, "direct-41-000002")
        ledger = self.workflows_dir / "direct-41-000002" / "state.json"
        before = ledger.read_bytes()
        reply = self.direct_owner(issue=41, tracker=self.tracker_fact(41))
        self.assertRegex(reply["run_id"], CORE)
        self.assertEqual(self.store().lookup(ai.direct_key(41, 1)), reply["run_id"])
        self.assertEqual(ledger.read_bytes(), before)

    def test_a_valid_ledger_before_a_refused_one_stays_unbound(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        first = self.workflows_dir / "direct-41-000001" / "state.json"
        self.install_legacy({**json.loads(first.read_text()), "prior_run": "direct-42-000001"},
                            "direct-41-000002")
        second = self.workflows_dir / "direct-41-000002" / "state.json"
        before = (first.read_bytes(), second.read_bytes())
        refused = self.direct_owner_raw(issue=41, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("unmigrated direct run", refused.stderr)
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


class MigrationAcceptanceTest(MigrationFixtures, unittest.TestCase):
    LEGACY = ("orchestrate-21-24-r2", "issues-29-30-20260817-r2")

    def migrate(self, *flags, ok=True):
        completed = self.run_cli("migrate", "--repo-root", self.root, *flags, ok=ok)
        return completed, (json.loads(completed.stdout) if ok else None)

    def rows(self, report):
        return {row["ledger"]: row for row in report["ledgers"]}

    def install_all(self):
        source = self.delivered_207()       # built in the driver's own root (D24)
        for handle in self.LEGACY:
            self.install_legacy(source, handle)
        self.init_run(creation_key="fixture-337")
        self.spawn(issue=337, worktree=str(self.root / "wt-337"))
        self.install_legacy(self.read_state(), "run-20261009-337-338-339")
        self.install_direct_pair()          # direct-41-000001 (terminal) and -000002 (D21)
        return source

    def launch_bytes(self, handle):
        return [self.run_cli(command, "--repo-root", self.root, "--run-id", handle,
                             "--action-id", action).stdout
                for command in ("check-launch", "current-launch")
                for action in ("207:1:4", "207:r1:1")]

    def test_ac1_minted_runs_and_legacy_rows_with_lineage(self):
        self.install_all()
        before = {handle: self.launch_bytes(handle) for handle in self.LEGACY}
        _, report = self.migrate("--apply")
        rows = self.rows(report)
        for handle in (*self.LEGACY, "run-20261009-337-338-339", "direct-41-000001",
                       "direct-41-000002"):
            with self.subTest(handle=handle):
                self.assertEqual(rows[handle]["verdict"], "migrated")
                key = (ai.direct_key(41, int(handle[-6:])) if handle.startswith("direct-")
                       else ai.legacy_key(handle))
                self.assertEqual(self.store().lookup(key), rows[handle]["transaction_id"])
        self.assertEqual(rows["direct-41-000002"]["prior_transaction_id"],
                         rows["direct-41-000001"]["transaction_id"])
        _, again = self.migrate()
        again_rows = self.rows(again)
        self.assertEqual(set(again_rows), set(rows))
        self.assertEqual({handle: row["verdict"] for handle, row in again_rows.items()},
                         {handle: "current" for handle in rows})
        self.assertEqual({handle: self.launch_bytes(handle) for handle in self.LEGACY}, before)

    def test_ac2_identity_never_comes_from_names(self):
        self.install_all()
        _, report = self.migrate()
        grouped = self.rows(report)["run-20261009-337-338-339"]
        self.assertEqual((grouped["alias"]["issues"], grouped["issues"]),
                         ([337, 338, 339], [337]))
        retried = self.rows(report)["orchestrate-21-24-r2"]
        self.assertEqual((retried["alias"]["retry"], retried["prior_run"],
                          retried["prior_transaction_id"]), (2, None, None))
        self.migrate("--apply")
        subject = self.store().load(self.store().lookup(
            ai.legacy_key("run-20261009-337-338-339"))).subject
        self.assertNotIn("issues", subject)
        moved = self.workflows_dir / "orchestrate-99"
        (self.workflows_dir / "issues-29-30-20260817-r2").rename(moved)
        snapshot = self.tree_snapshot()
        _, report = self.migrate()
        self.assertEqual((self.rows(report)["orchestrate-99"]["verdict"],
                          self.rows(report)["orchestrate-99"]["reason"]),
                         ("refused", "location_mismatch"))
        refused = self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                               "orchestrate-99", "--action-id", "207:1:4", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), snapshot)

    def test_ac3_dry_run_then_idempotent_apply(self):
        self.install_all()
        snapshot = self.tree_snapshot()
        first, _ = self.migrate()
        second, _ = self.migrate()
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(self.tree_snapshot(), snapshot)
        self.migrate("--apply")
        applied = self.tree_snapshot()
        _, again = self.migrate("--apply")
        self.assertEqual(again["counts"]["migrated"], 0)
        self.assertEqual(self.tree_snapshot(), applied)

    def test_ac3_dry_run_before_any_store_creates_nothing(self):
        source = self.install_orchestrated("orchestrate-21-24-r2")
        self.install_legacy(source, "issues-29-30-20260817-r2")
        self.assertFalse(self.store_root.exists())
        snapshot = self.tree_snapshot()
        first, report = self.migrate()
        second, _ = self.migrate()
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual({row["verdict"] for row in report["ledgers"]}, {"migrate"})
        self.assertEqual({row["transaction_id"] for row in report["ledgers"]}, {None})
        self.assertEqual(self.tree_snapshot(), snapshot)
        self.assertFalse(self.store_root.exists())

    def test_ac3_ledger_refusal_is_data_and_a_store_fault_exits_2(self):
        self.init_run(creation_key="fixture-unknown")
        unknown = self.run_id
        shutil.rmtree(self.store_root / unknown)      # the ledger names a missing transaction
        _, report = self.migrate()
        self.assertEqual((self.rows(report)[unknown]["verdict"],
                          self.rows(report)[unknown]["reason"]), ("refused", "invalid_state"))
        self.init_run(creation_key="fixture-fault")
        (self.store_root / self.run_id / "state.json").write_bytes(b"{")  # unreadable record
        snapshot = self.tree_snapshot()
        for flags in ((), ("--apply",)):
            with self.subTest(flags=flags):
                completed, _ = self.migrate(*flags, ok=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
                self.assertTrue(completed.stderr.startswith("workflow-state: "),
                                completed.stderr)
                self.assertEqual(self.tree_snapshot(), snapshot)

    def test_ac3_a_prior_run_that_differs_from_its_run_transaction_is_refused(self):
        owner = self.acquire_direct(issue=41)
        self.run_id = owner["run_id"]
        self.finish(1, {**self.merged_result(41), "state": "stopped", "pr_url": None,
                        "merge_sha": None, "issue_closed": False, "notes": "semantic stop"},
                    issue=41, now="2026-08-20T10:05:00Z")
        self.terminal_worktree = owner["worktree"]
        second = self.direct_owner(**self.new_run_fields(41))["run_id"]
        self.assertEqual(self.store().load(second).subject["prior_run"], owner["run_id"])
        self.edit_ledger(second, prior_run=None)
        snapshot = self.tree_snapshot()
        _, report = self.migrate()
        self.assertEqual((self.rows(report)[second]["verdict"],
                          self.rows(report)[second]["reason"]), ("refused", "invalid_state"))
        refused = self.run_cli("check-launch", "--repo-root", self.root, "--run-id", second,
                               "--action-id", "41:1:1", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("prior_run does not match its run transaction", refused.stderr)
        self.assertEqual(self.tree_snapshot(), snapshot)

    def test_ac3_refusals_are_byte_identical(self):
        fixtures = self.install_refusal_fixtures()
        snapshot = self.tree_snapshot()
        index = sorted((self.store_root / "creation-keys").iterdir())
        _, report = self.migrate("--apply")
        rows = self.rows(report)
        after = self.tree_snapshot()
        for handle, reason in fixtures.items():
            with self.subTest(handle=handle):
                self.assertEqual((rows[handle]["verdict"], rows[handle]["reason"]),
                                 ("refused", reason))
                prefix = f"workflows/{handle}/"
                self.assertEqual({k: v for k, v in after.items() if k.startswith(prefix)},
                                 {k: v for k, v in snapshot.items() if k.startswith(prefix)})
        self.assertEqual(sorted((self.store_root / "creation-keys").iterdir()), index)

    def test_ac3_precreated_transaction_is_bound(self):
        self.install_all()
        plan = ai.plan_migration(json.loads(
            (self.workflows_dir / "orchestrate-21-24-r2" / "state.json").read_text()))
        reserved = self.store().create(plan.creation_key, plan.subject_json(),
                                       **ai.creation_arguments(plan)).transaction_id
        _, report = self.migrate("--apply")
        self.assertEqual(self.rows(report)["orchestrate-21-24-r2"]["transaction_id"], reserved)

    def test_ac3_held_mint_lock_makes_apply_wait(self):
        self.install_all()
        ledger = self.workflows_dir / "orchestrate-21-24-r2" / "state.json"
        before = ledger.read_bytes()
        with open(self.store_root / "attempt-runs.lock", "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            child = subprocess.Popen(
                [sys.executable, str(SCRIPT), "migrate", "--repo-root", str(self.root),
                 "--apply"], env=self.cli_env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            with self.assertRaises(subprocess.TimeoutExpired):
                child.wait(timeout=3)
            self.assertEqual(ledger.read_bytes(), before)
        stdout, stderr = child.communicate(timeout=120)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(self.rows(json.loads(stdout))["orchestrate-21-24-r2"]["verdict"],
                         "migrated")


class LegacyOwnerCompatibilityTest(MigrationFixtures, unittest.TestCase):
    def live_legacy_owner(self):
        """A schema-7 `orchestrate-14` ledger with an active owner on 14:1:1."""
        self.init_run(creation_key="fixture-14")
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.install_legacy(self.read_state(), "orchestrate-14")
        self.assertEqual(json.loads(self.state_path.read_text())["schema_version"], 7)

    def owner_lifecycle(self):
        """progress, register-worker, release-worker, suspend, then finish: legacy ids only."""
        worktree = self.root / "wt-14"
        self.progress(issue=14, phase=1, now="2026-08-13T20:01:00Z")
        self.register_worker(action_id="14:1:1", now="2026-08-13T20:02:00Z")
        self.release_worker(worker_id="14:1:1:w1", event="returned",
                            now="2026-08-13T20:03:00Z")
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:04:00Z")
        self.resume(issue=14, worktree=worktree, now="2026-08-13T20:05:00Z")
        bound = self.read_state()["transaction_id"]
        self.finish(1, self.merged_result(), now="2026-08-13T20:30:00Z")
        self.assertEqual(self.read_state()["issues"]["14"]["attempts"][-1]["state"], "merged")
        self.assert_owner_bound()  # finish ran on the schema-11 ledger and kept its binding (D25)
        self.assertEqual(self.read_state()["transaction_id"], bound)

    def assert_owner_bound(self):
        state = self.read_state()
        self.assertEqual(state["run_id"], "orchestrate-14")
        self.assert_bound(state)

    def test_control_migrates_under_a_live_owner(self):
        self.live_legacy_owner()
        worktree = str(self.root / "wt-14")
        self.control(now="2026-08-13T20:00:30Z", issues=[14],
                     tracker=[self.tracker_fact(14)], max_parallel=100,
                     worktrees=[self.worktree_fact(14, recorded={
                         "path": worktree, "state": "matching_issue_branch"})])
        self.assert_owner_bound()
        self.owner_lifecycle()

    def test_owner_write_is_the_migrating_write(self):
        self.live_legacy_owner()
        self.progress(issue=14, phase=1, now="2026-08-13T20:00:30Z")
        self.assert_owner_bound()
        self.owner_lifecycle()

    def base_helper(self, scratch):
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            self.fail(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D13)")
        archive = subprocess.run(["git", "-C", str(REPO), "archive", BASE_COMMIT,
                                  "home/common/agent-skills/scripts",
                                  "home/common/agent-skills/artifact-budget-policy.json"],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(scratch)], input=archive.stdout, check=True)
        return scratch / "home/common/agent-skills/scripts/workflow-state.py"

    def test_base_helper_refuses_schema_8_without_writing(self):
        self.live_legacy_owner()
        with tempfile.TemporaryDirectory() as scratch:
            script = self.base_helper(Path(scratch))
            env = {**self.cli_env, "PYTHONPATH": str(REPO / "python")}

            def base(command, *rest):
                return subprocess.run(
                    [sys.executable, str(script), command, "--repo-root", str(self.root),
                     "--run-id", "orchestrate-14", *rest],
                    env=env, cwd=scratch, capture_output=True, text=True, timeout=120)

            # Positive control (D26): the extracted helper reads the schema-7 ledger.
            control = base("check-launch", "--action-id", "14:1:1")
            self.assertEqual(control.returncode, 0, control.stderr)
            self.progress(issue=14, phase=1, now="2026-08-13T20:00:30Z")
            self.assert_owner_bound()
            snapshot = self.tree_snapshot()
            for args in (("check-launch", "--action-id", "14:1:1"),
                         ("progress", "--issue", "14", "--attempt", "1", "--phase", "2",
                          "--next-needs-context", "true", "--artifacts-sufficient", "false",
                          "--remainder-self-contained", "false")):
                with self.subTest(command=args[0]):
                    completed = base(*args)
                    # Exit 2 with a schema refusal: check-launch rejects the unknown
                    # `transaction_id` field, progress the chain's version 8 (D26).
                    self.assertEqual(completed.returncode, 2, completed.stdout)
                    self.assertTrue(completed.stderr.startswith("workflow-state: "),
                                    completed.stderr)
                    self.assertIn("workflow state schema", completed.stderr)
                    self.assertEqual(self.tree_snapshot(), snapshot)


_SHIM = """#!@PYTHON@
import json, os, shutil, subprocess, sys
from pathlib import Path

plan_path = Path(os.environ["LEDGER_ARCHIVE_SHIM_PLAN"])
counter = plan_path.with_suffix(".calls")
call = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
counter.write_text(str(call + 1), encoding="utf-8")
plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
step = plan.get(str(call), {})


def act(actions):
    for kind, source, target in actions:
        if kind == "copytree":
            shutil.copytree(source, target)
        elif kind == "move":
            shutil.move(source, target)
        elif kind == "symlink":
            os.symlink(source, target)  # source is the link's target, target the link
        else:
            shutil.copyfile(source, target)


act(step.get("before", []))
if "exit" in step or "stdout" in step:
    sys.stdout.write(step.get("stdout", ""))
    sys.stderr.write(step.get("stderr", ""))
    sys.exit(step.get("exit", 0))
done = subprocess.run([sys.executable, @SCRIPT@, *sys.argv[1:]], capture_output=True,
                      text=True, check=False)
act(step.get("after", []))
sys.stdout.write(done.stdout)
sys.stderr.write(done.stderr)
sys.exit(done.returncode)
"""


class LedgerArchiveTest(MigrationFixtures, unittest.TestCase):
    """`ledger-archive` (#584): refused ledgers leave `migrate`'s inventory, nothing else moves."""

    def setUp(self):
        super().setUp()
        self.refused = self.install_refusal_fixtures()
        self.install_orchestrated("orchestrate-17")
        shims = tempfile.TemporaryDirectory()
        self.addCleanup(shims.cleanup)
        shim = Path(shims.name) / "workflow-state"
        shim.write_text(_SHIM.replace("@PYTHON@", sys.executable)
                        .replace("@SCRIPT@", repr(str(SCRIPT))), encoding="utf-8")
        shim.chmod(0o755)
        self.plan_path = Path(shims.name) / "plan.json"
        self.archive_env = {**self.cli_env, "PYTHONPATH": str(REPO / "python"),
                            "LEDGER_ARCHIVE_SHIM_PLAN": str(self.plan_path),
                            "PATH": f"{shims.name}{os.pathsep}{os.environ['PATH']}"}
        self.archive_dir = self.root / ".superpowers" / "archive" / "workflows"
        self.labels_path = Path(shims.name) / "labels.json"  # outside the tree
        self.write_labels()

    def write_labels(self, labels=None):
        if labels is None:
            labels = {handle: {"disposition": "archived", "redeliver": []}
                      for handle in self.refused}
        self.labels_path.write_text(json.dumps(labels), encoding="utf-8")

    def shim_plan(self, plan):
        """Set the shim's call plan and reset its call counter."""
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.plan_path.with_suffix(".calls").unlink(missing_ok=True)

    def shim_calls(self):
        counter = self.plan_path.with_suffix(".calls")
        return int(counter.read_text(encoding="utf-8")) if counter.exists() else 0

    def archive(self, *args, code=0, labels=True):
        extra = ["--labels", str(self.labels_path)] if labels and "--apply" in args else []
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.ledger_archive", "--repo-root",
             str(self.root), *args, *extra], env=self.archive_env, capture_output=True, text=True,
            check=False)
        self.assertEqual(completed.returncode, code, completed.stderr)
        if code == 2:
            self.assertEqual(completed.stdout, "")
            self.assertRegex(completed.stderr, r"^ledger-archive: ")
        return json.loads(completed.stdout) if completed.stdout else None

    def migrate_counts(self):
        _, report = self.run_cli_json("migrate", "--repo-root", self.root)
        return report["counts"], {row["ledger"]: row["verdict"] for row in report["ledgers"]}

    def ledger_bytes(self, base, handle):
        return {str(p.relative_to(base / handle)): p.read_bytes()
                for p in sorted((base / handle).rglob("*")) if p.is_file()}

    def assert_nothing_moved(self, before):
        self.assertEqual(self.tree_snapshot(), before)
        self.assertFalse((self.root / ".superpowers" / "archive").exists())
        for handle in self.refused:
            with open(self.workflows_dir / handle / "state.lock", "r+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # released

    def test_dry_run_lists_every_refused_ledger_and_writes_nothing(self):
        counts, verdicts = self.migrate_counts()
        self.assertEqual(verdicts["orchestrate-17"], "migrate")
        self.assertEqual(counts["refused"], len(self.refused))
        before = self.tree_snapshot()
        report = self.archive()
        self.assertEqual(report["schema"], "ledger-archive-report/v1")
        self.assertEqual(report["mode"], "dry_run")
        self.assertIsNone(report["post_check"])
        self.assertEqual({row["ledger"]: row["reason"] for row in report["ledgers"]},
                         self.refused)
        self.assertEqual({row["verdict"] for row in report["ledgers"]}, {"would_archive"})
        self.assertEqual(report["counts"], {"would_archive": len(self.refused),
                                            "archived": 0, "skipped": 0})
        self.assertEqual(set(report["ledgers"][0]), {
            "ledger", "run_id", "schema_version", "dialect", "issues", "reason",
            "disposition", "redeliver", "destination", "verdict", "skip_reason"})
        self.assertEqual({row["disposition"] for row in report["ledgers"]}, {None})
        self.assertEqual(self.tree_snapshot(), before)
        self.assertFalse((self.root / ".superpowers" / "archive").exists())
        self.assertEqual(self.shim_calls(), 1)

    def test_apply_moves_refused_ledgers_byte_for_byte_and_leaves_the_rest(self):
        workflows = self.workflows_dir
        moved = {handle: self.ledger_bytes(workflows, handle) for handle in self.refused}
        kept = self.ledger_bytes(workflows, "orchestrate-17")
        report = self.archive("--apply")
        self.assertEqual(report["mode"], "apply")
        self.assertEqual(report["counts"], {"would_archive": 0,
                                            "archived": len(self.refused), "skipped": 0})
        self.assertEqual(report["post_check"],
                         {"passed": True, "refused_after": 0, "unexpected": []})
        self.assertEqual(self.shim_calls(), 3)  # inventory, re-read under the locks, post-check
        for handle, files in moved.items():
            with self.subTest(handle=handle):
                self.assertFalse((workflows / handle).exists())
                self.assertEqual(self.ledger_bytes(self.archive_dir, handle), files)
                record = json.loads((self.archive_dir / f"{handle}.archived.json")
                                    .read_text(encoding="utf-8"))
                self.assertEqual(record["schema"], "ledger-archive-record/v1")
                self.assertEqual(record["ledger"], handle)
                self.assertEqual(record["reason"], self.refused[handle])
                self.assertEqual(record["source"], str(workflows.resolve() / handle))
                self.assertEqual((record["disposition"], record["redeliver"]), ("archived", []))
                self.assertEqual(record["state_sha256"], "sha256:" + hashlib.sha256(
                    files["state.json"]).hexdigest())
                self.assertRegex(record["archived_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(self.ledger_bytes(workflows, "orchestrate-17"), kept)
        counts, verdicts = self.migrate_counts()
        self.assertEqual(counts["refused"], 0)
        self.assertEqual(verdicts, {"orchestrate-17": "migrate"})

    def test_apply_again_archives_nothing(self):
        self.archive("--apply")
        before = self.tree_snapshot()
        report = self.archive("--apply")
        self.assertEqual(report["ledgers"], [])
        self.assertEqual(report["counts"], {"would_archive": 0, "archived": 0, "skipped": 0})
        self.assertTrue(report["post_check"]["passed"])
        self.assertEqual(self.tree_snapshot(), before)

    def test_a_held_lock_skips_that_ledger_only(self):
        with open(self.workflows_dir / "orchestrate-92" / "state.lock", "r+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual((rows["orchestrate-92"]["verdict"],
                          rows["orchestrate-92"]["skip_reason"]), ("skipped", "locked"))
        self.assertTrue((self.workflows_dir / "orchestrate-92" / "state.json").is_file())
        self.assertEqual(report["counts"]["archived"], len(self.refused) - 1)
        self.assertEqual(report["post_check"],
                         {"passed": True, "refused_after": 1, "unexpected": []})

    def test_a_candidate_changed_before_its_lock_is_skipped_as_changed(self):
        changed = self.workflows_dir / "issue-14-test" / "state.json"
        replacement = self.workflows_dir / "orchestrate-17" / "state.json"
        # After the unlocked inventory, before the locks: the row turns location_mismatch.
        self.shim_plan({"0": {"after": [["copyfile", str(replacement), str(changed)]]}})
        report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual((rows["issue-14-test"]["verdict"],
                          rows["issue-14-test"]["skip_reason"]), ("skipped", "changed"))
        self.assertEqual(changed.read_bytes(), replacement.read_bytes())
        self.assertFalse((self.archive_dir / "issue-14-test").exists())
        self.assertFalse((self.archive_dir / "issue-14-test.archived.json").exists())
        self.assertEqual(report["counts"]["archived"], len(self.refused) - 1)
        self.assertEqual(report["post_check"],
                         {"passed": True, "refused_after": 1, "unexpected": []})

    def test_a_candidate_removed_after_the_inventory_is_skipped_as_missing(self):
        gone = tempfile.TemporaryDirectory()
        self.addCleanup(gone.cleanup)
        source = self.workflows_dir / "issue-14-test"
        # After the unlocked inventory, before its lock: the candidate disappears.
        self.shim_plan({"0": {"after": [["move", str(source), str(Path(gone.name) / "away")]]}})
        report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual((rows["issue-14-test"]["verdict"],
                          rows["issue-14-test"]["skip_reason"]), ("skipped", "ledger_missing"))
        self.assertFalse(os.path.lexists(source))  # no lock file or directory was recreated
        self.assertFalse(os.path.lexists(self.archive_dir / "issue-14-test"))
        self.assertFalse(os.path.lexists(self.archive_dir / "issue-14-test.archived.json"))
        self.assertEqual(report["counts"]["archived"], len(self.refused) - 1)
        self.assertEqual(report["post_check"],
                         {"passed": True, "refused_after": 0, "unexpected": []})

    def test_a_candidate_replaced_by_a_symlink_gets_no_lock_outside_the_tree(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        bait = Path(outside.name) / "bait"
        bait.mkdir()
        source = self.workflows_dir / "issue-14-test"
        # After the inventory: the directory moves away and a symlink to an empty
        # directory outside the tree takes its name.
        self.shim_plan({"0": {"after": [["move", str(source), str(Path(outside.name) / "away")],
                                        ["symlink", str(bait), str(source)]]}})
        report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual((rows["issue-14-test"]["verdict"],
                          rows["issue-14-test"]["skip_reason"]), ("skipped", "ledger_missing"))
        self.assertEqual(list(bait.iterdir()), [])  # no state.lock created through the link
        self.assertTrue(source.is_symlink())
        self.assertFalse(os.path.lexists(self.archive_dir / "issue-14-test"))
        self.assertEqual(report["counts"]["archived"], len(self.refused) - 1)
        self.assertTrue(report["post_check"]["passed"])

    def test_an_existing_destination_is_skipped_and_kept(self):
        (self.archive_dir / "issue-14-test").mkdir(parents=True)
        report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual(rows["issue-14-test"]["skip_reason"], "destination_exists")
        self.assertTrue((self.workflows_dir / "issue-14-test" / "state.json").is_file())
        self.assertEqual(list((self.archive_dir / "issue-14-test").iterdir()), [])

    def test_a_symlinked_archive_home_refuses_before_any_move(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        (self.root / ".superpowers" / "archive").symlink_to(elsewhere.name)
        before = self.tree_snapshot()
        self.assertIsNone(self.archive("--apply", code=2))
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(list(Path(elsewhere.name).iterdir()), [])

    def test_a_missing_workflows_directory_exits_2_before_workflow_state_runs(self):
        shutil.rmtree(self.workflows_dir)
        self.assertIsNone(self.archive("--apply", code=2))
        self.assertFalse((self.root / ".superpowers" / "archive").exists())
        self.assertEqual(self.shim_calls(), 0)

    def test_a_bad_inventory_exits_2_with_nothing_moved(self):
        _, real = self.run_cli_json("migrate", "--repo-root", self.root)
        text = json.dumps(real)
        variants = {
            "nonzero_exit": {"exit": 3, "stderr": "workflow-state: boom\n"},
            "apply_mode": {"stdout": json.dumps({**real, "mode": "apply"})},
            "duplicate_key": {"stdout": '{"mode": "dry_run", ' + text[1:]},
            "wrong_schema": {"stdout": json.dumps({**real, "schema": "other/v1"})},
            "not_json": {"stdout": "not json\n"},
        }
        for name, step in variants.items():
            with self.subTest(variant=name):
                self.shim_plan({"0": step})
                before = self.tree_snapshot()
                self.assertIsNone(self.archive("--apply", code=2))
                self.assertEqual(self.shim_calls(), 1)  # the shim ran; the check is not local
                self.assert_nothing_moved(before)

    def test_a_failing_re_read_under_the_locks_exits_2_with_nothing_moved(self):
        for name, step in {"nonzero_exit": {"exit": 3, "stderr": "boom\n"},
                           "not_json": {"stdout": "{\n"}}.items():
            with self.subTest(variant=name):
                self.shim_plan({"1": step})
                before = self.tree_snapshot()
                self.assertIsNone(self.archive("--apply", code=2))
                self.assertEqual(self.shim_calls(), 2)
                self.assert_nothing_moved(before)

    def test_an_archived_ledger_reappearing_fails_the_post_check(self):
        self.shim_plan({"2": {"before": [[
            "copytree", str(self.archive_dir / "issue-14-test"),
            str(self.workflows_dir / "issue-14-test")]]}})
        report = self.archive("--apply", code=1)
        self.assertEqual(report["counts"]["archived"], len(self.refused))
        self.assertEqual(report["post_check"],
                         {"passed": False, "refused_after": 1, "unexpected": ["issue-14-test"]})

    def test_a_new_refused_ledger_fails_the_post_check(self):
        self.shim_plan({"1": {"after": [[
            "copytree", str(self.workflows_dir / "orchestrate-92"),
            str(self.workflows_dir / "orchestrate-93")]]}})
        report = self.archive("--apply", code=1)
        self.assertNotIn("orchestrate-93", {row["ledger"] for row in report["ledgers"]})
        self.assertEqual(report["counts"]["archived"], len(self.refused))
        self.assertEqual(report["post_check"],
                         {"passed": False, "refused_after": 1, "unexpected": ["orchestrate-93"]})
        self.assertTrue((self.workflows_dir / "orchestrate-93" / "state.json").is_file())

    def test_apply_without_labels_exits_2_before_workflow_state_runs(self):
        before = self.tree_snapshot()
        self.assertIsNone(self.archive("--apply", code=2, labels=False))
        self.assertEqual(self.shim_calls(), 0)
        self.assert_nothing_moved(before)

    def test_an_unlabelled_candidate_is_skipped_and_kept(self):
        self.write_labels({handle: {"disposition": "archived", "redeliver": []}
                           for handle in self.refused if handle != "orchestrate-92"})
        report = self.archive("--apply")
        rows = {row["ledger"]: row for row in report["ledgers"]}
        self.assertEqual((rows["orchestrate-92"]["verdict"],
                          rows["orchestrate-92"]["skip_reason"]), ("skipped", "unlabelled"))
        self.assertTrue((self.workflows_dir / "orchestrate-92" / "state.json").is_file())
        self.assertFalse((self.archive_dir / "orchestrate-92.archived.json").exists())
        self.assertEqual(report["counts"]["archived"], len(self.refused) - 1)
        self.assertEqual(report["post_check"],
                         {"passed": True, "refused_after": 1, "unexpected": []})

    def test_each_record_carries_its_label(self):
        labels = {handle: {"disposition": "archived", "redeliver": []}
                  for handle in self.refused}
        labels["orchestrate-91"] = {"disposition": "abandoned", "redeliver": [207]}
        labels["orchestrate-92"] = {"disposition": "unresolved", "redeliver": [92]}
        labels["issue-14-test"] = {"disposition": "unresolved", "redeliver": []}
        labels["not-a-candidate"] = {"disposition": "archived", "redeliver": []}
        self.write_labels(labels)
        report = self.archive("--apply")
        self.assertEqual(report["counts"]["archived"], len(self.refused))
        rows = {row["ledger"]: row for row in report["ledgers"]}
        for handle in self.refused:
            with self.subTest(handle=handle):
                record = json.loads((self.archive_dir / f"{handle}.archived.json")
                                    .read_text(encoding="utf-8"))
                want = (labels[handle]["disposition"], labels[handle]["redeliver"])
                self.assertEqual((record["disposition"], record["redeliver"]), want)
                self.assertEqual((rows[handle]["disposition"], rows[handle]["redeliver"]), want)
        self.assertNotIn("not-a-candidate", rows)

    def test_an_invalid_labels_file_exits_2_with_nothing_moved(self):
        good = {"disposition": "archived", "redeliver": []}
        variants = {
            "not_json": "not json",
            "duplicate_key": '{"issue-14-test": %s, "issue-14-test": %s}' % (
                json.dumps(good), json.dumps(good)),
            "not_an_object": "[]",
            "unknown_disposition": json.dumps({"issue-14-test": {
                "disposition": "dropped", "redeliver": []}}),
            "archived_with_issues": json.dumps({"issue-14-test": {
                "disposition": "archived", "redeliver": [14]}}),
            "abandoned_without_issues": json.dumps({"issue-14-test": {
                "disposition": "abandoned", "redeliver": []}}),
            "unsorted": json.dumps({"issue-14-test": {
                "disposition": "unresolved", "redeliver": [3, 2]}}),
            "bool_issue": json.dumps({"issue-14-test": {
                "disposition": "abandoned", "redeliver": [True]}}),
            "zero_issue": json.dumps({"issue-14-test": {
                "disposition": "abandoned", "redeliver": [0]}}),
            "extra_field": json.dumps({"issue-14-test": {**good, "note": "x"}}),
            "bad_ledger_name": json.dumps({"../issue-14-test": good}),
        }
        for name, text in variants.items():
            with self.subTest(variant=name):
                self.labels_path.write_text(text, encoding="utf-8")
                self.shim_plan({})
                before = self.tree_snapshot()
                self.assertIsNone(self.archive("--apply", code=2))
                self.assertEqual(self.shim_calls(), 0)
                self.assert_nothing_moved(before)


class LedgerSnapshotTest(MigrationFixtures, unittest.TestCase):
    """`ledger-snapshot` (#584 D7, D9): one consistent, restorable cut of both stores."""

    def setUp(self):
        super().setUp()
        self.install_orchestrated("orchestrate-17")
        self.run_cli("migrate", "--repo-root", self.root, "--apply")  # fills attempt-transactions
        self.assertTrue((self.store_root / "attempt-runs.lock").is_file())
        # Not `self.home`: the harness keeps HOME there.
        self.archive_home = self.root / ".superpowers" / "archive"
        self.out = self.archive_home / "pre-test.tar.gz"
        self.env = {**self.cli_env, "PYTHONPATH": str(REPO / "python")}

    def cli(self, *args, code=0):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.ledger_snapshot", *args], env=self.env,
            capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, code, completed.stderr)
        if code == 2:
            self.assertEqual(completed.stdout, "")
            self.assertRegex(completed.stderr, r"^ledger-snapshot: ")
            return completed.stderr
        return json.loads(completed.stdout)

    def take(self, code=0):
        return self.cli("take", "--repo-root", str(self.root), "--out", str(self.out), code=code)

    def restore(self, *extra, code=0, snapshot=None):
        return self.cli("restore", "--repo-root", str(self.root), "--snapshot",
                        str(snapshot or self.out), *extra, code=code)

    def stores(self):
        return {key: value for key, value in self.tree_snapshot().items()
                if key.split("/")[0] in ("workflows", "attempt-transactions")}

    def lock_paths(self):
        ledgers = [self.workflows_dir / name / "state.lock"
                   for name in sorted(os.listdir(self.workflows_dir))
                   if (self.workflows_dir / name / "state.lock").is_file()]
        return ledgers + [self.store_root / name for name in
                          ("attempt-runs.lock", "creation.lock", "leases.lock")
                          if (self.store_root / name).is_file()]

    def assert_all_locks_free(self):
        for path in self.lock_paths():
            with open(path, "r+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_take_writes_one_tarball_of_both_stores_and_releases_every_lock(self):
        report = self.take()
        stores = self.stores()
        self.assertEqual(report["schema"], "ledger-snapshot-report/v1")
        self.assertEqual(report["mode"], "take")
        self.assertEqual(report["snapshot"], str(self.out.resolve()))
        self.assertTrue(report["transactions"])
        self.assertGreaterEqual(report["ledgers"], 1)
        self.assertRegex(report["taken_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(report["sha256"],
                         "sha256:" + hashlib.sha256(self.out.read_bytes()).hexdigest())
        with tarfile.open(self.out, "r:gz") as tar:
            members = tar.getmembers()
            self.assertEqual({m.name for m in members}, set(stores))
            self.assertTrue(all(m.isdir() or m.isreg() for m in members))
            for member in members:
                if member.isreg():
                    self.assertEqual(tar.extractfile(member).read(), stores[member.name])
        self.assertEqual(report["members"], len(stores))
        self.assertEqual(sorted(p.name for p in self.archive_home.iterdir()), ["pre-test.tar.gz"])
        self.assert_all_locks_free()

    def test_a_held_lock_refuses_take_with_nothing_written(self):
        (self.workflows_dir / ".direct-5.lock").write_bytes(b"")
        for held in (self.workflows_dir / "orchestrate-17" / "state.lock",
                     self.workflows_dir / ".direct-5.lock",
                     self.store_root / "attempt-runs.lock"):
            with self.subTest(held=held.name):
                before = self.tree_snapshot()
                with open(held, "r+b") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    self.assertRegex(self.take(code=2), r"^ledger-snapshot: busy: ")
                self.assertEqual(self.tree_snapshot(), before)
                self.assertFalse(self.archive_home.exists())
                self.assert_all_locks_free()

    def test_a_ledger_or_store_appearing_while_fenced_refuses_and_leaves_no_snapshot(self):
        from agent_tools import ledger_snapshot

        def late_ledger():
            (self.workflows_dir / "late-1").mkdir()
            (self.workflows_dir / "late-1" / "state.json").write_text("{}", encoding="utf-8")

        def store_vanishes():
            os.rename(self.store_root, self.root / "store-away")

        for name, appear in (("ledger", late_ledger), ("store", store_vanishes)):
            with self.subTest(change=name):
                with self.assertRaises(ledger_snapshot.SnapshotRefused) as caught:
                    ledger_snapshot.take(self.root, self.out, on_written=appear,
                                         now=lambda: "2026-11-08T00:00:00Z")
                self.assertEqual(caught.exception.code, "changed")
                self.assertEqual(list(self.archive_home.iterdir()), [])  # no snapshot, no partial
                if name == "ledger":
                    shutil.move(str(self.workflows_dir / "late-1"), str(self.root / "late-away"))

    def test_take_refuses_an_existing_or_misplaced_out(self):
        self.archive_home.mkdir(mode=0o700)
        self.out.write_bytes(b"kept")
        before = self.tree_snapshot()
        self.assertRegex(self.take(code=2), r"^ledger-snapshot: exists: ")
        self.assertEqual(self.tree_snapshot(), before)
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        for out in (Path(elsewhere.name) / "pre.tar.gz", self.archive_home / "pre.tar",
                    self.archive_home / "sub" / "pre.tar.gz"):
            with self.subTest(out=str(out)):
                self.cli("take", "--repo-root", str(self.root), "--out", str(out), code=2)
                self.assertEqual(self.tree_snapshot(), before)
                self.assertEqual(list(Path(elsewhere.name).iterdir()), [])

    def test_a_symlinked_archive_home_or_a_symlink_in_a_store_refuses_take(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.archive_home.symlink_to(elsewhere.name)
        self.assertRegex(self.take(code=2), r"^ledger-snapshot: invalid_store: ")
        self.assertEqual(list(Path(elsewhere.name).iterdir()), [])
        self.archive_home.unlink()
        (self.workflows_dir / "orchestrate-17" / "link").symlink_to(elsewhere.name)
        self.assertRegex(self.take(code=2), r"^ledger-snapshot: invalid_store: ")
        self.assertEqual(list(self.archive_home.iterdir()), [])
        self.assert_all_locks_free()

    def test_restore_returns_both_stores_to_the_snapshot_and_keeps_every_later_file(self):
        self.take()
        before = self.stores()
        (self.archive_home / "workflows").mkdir()
        os.rename(self.workflows_dir / "orchestrate-17", self.archive_home / "workflows" / "orchestrate-17")
        (self.workflows_dir / "late").mkdir()
        (self.workflows_dir / "late" / "state.json").write_text("{}", encoding="utf-8")
        (self.store_root / "late.json").write_text("{}", encoding="utf-8")
        later = self.tree_snapshot()
        dry = self.restore()
        self.assertEqual(dry["mode"], "restore_dry_run")
        self.assertIsNone(dry["aside"])
        self.assertEqual(dry["moved"], ["workflows", "attempt-transactions", "archive/workflows"])
        self.assertEqual(dry["restored"], ["workflows", "attempt-transactions"])
        self.assertIn("workflows/late/state.json", dry["newer"])
        self.assertIn("attempt-transactions/late.json", dry["newer"])
        self.assertEqual(self.tree_snapshot(), later)  # the dry run wrote nothing
        report = self.restore("--apply")
        self.assertEqual(report["mode"], "restore")
        self.assertEqual(self.stores(), before)
        self.assertFalse(os.path.lexists(self.archive_home / "workflows"))
        aside = Path(report["aside"])
        self.assertEqual(aside.parent, self.archive_home.resolve())
        prefix = {"workflows": "workflows", "attempt-transactions": "attempt-transactions",
                  "archive-workflows": "archive/workflows"}
        kept = {f"{prefix[p.relative_to(aside).parts[0]]}/"
                f"{'/'.join(p.relative_to(aside).parts[1:])}": p.read_bytes()
                for p in aside.rglob("*") if p.is_file() and len(p.relative_to(aside).parts) > 1}
        for key, value in later.items():
            if value != "<dir>" and key.split("/")[0] in ("workflows", "attempt-transactions",
                                                          "archive"):
                if key.startswith("archive/") and not key.startswith("archive/workflows/"):
                    continue
                with self.subTest(kept=key):
                    self.assertEqual(kept.get(key), value)
        self.assert_all_locks_free()

    def test_a_store_absent_at_snapshot_time_stays_absent_after_restore(self):
        shutil.move(str(self.store_root), str(self.root / "store-away"))
        report = self.take()
        self.assertFalse(report["transactions"])
        before = self.stores()
        self.store_root.mkdir()
        (self.store_root / "late.json").write_text("{}", encoding="utf-8")
        report = self.restore("--apply")
        self.assertFalse(report["transactions"])
        self.assertEqual(report["restored"], ["workflows"])
        self.assertFalse(os.path.lexists(self.store_root))
        self.assertEqual(self.stores(), before)
        self.assertEqual((Path(report["aside"]) / "attempt-transactions" / "late.json")
                         .read_text(encoding="utf-8"), "{}")

    def test_a_held_lock_refuses_restore_with_nothing_moved(self):
        self.take()
        before = self.tree_snapshot()
        with open(self.workflows_dir / "orchestrate-17" / "state.lock", "r+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            self.assertRegex(self.restore("--apply", code=2), r"^ledger-snapshot: busy: ")
        self.assertEqual(self.tree_snapshot(), before)

    def test_an_invalid_snapshot_refuses_restore_with_nothing_moved(self):
        self.archive_home.mkdir(mode=0o700)

        def build(path, entries):
            with tarfile.open(path, "w:gz") as tar:
                for name, kind in entries:
                    info = tarfile.TarInfo(name)
                    if kind == "dir":
                        info.type = tarfile.DIRTYPE
                        tar.addfile(info)
                    elif kind == "link":
                        info.type, info.linkname = tarfile.SYMTYPE, "/etc"
                        tar.addfile(info)
                    else:
                        info.size = 2
                        tar.addfile(info, io.BytesIO(b"{}"))

        variants = {
            "dotdot": [("workflows", "dir"), ("workflows/../escape", "file")],
            "absolute": [("workflows", "dir"), ("/workflows/x", "file")],
            "symlink": [("workflows", "dir"), ("workflows/link", "link")],
            "outside_stores": [("workflows", "dir"), ("other/file", "file")],
            "no_workflows": [("attempt-transactions", "dir")],
        }
        for name, entries in variants.items():
            with self.subTest(variant=name):
                bad = self.archive_home / f"bad-{name}.tar.gz"
                build(bad, entries)
                before = self.tree_snapshot()
                self.restore("--apply", code=2, snapshot=bad)
                self.assertEqual(self.tree_snapshot(), before)
        not_gzip = self.archive_home / "not-gzip.tar.gz"
        not_gzip.write_bytes(b"not a tarball")
        before = self.tree_snapshot()
        self.restore("--apply", code=2, snapshot=not_gzip)
        self.assertEqual(self.tree_snapshot(), before)
