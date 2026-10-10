"""Attempt run identity on workflow-state ledgers (#337), driven through the CLI from source.

Run: just agent-workflow-tests
"""

import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import sys
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
        self.edit_ledger("orchestrate-90", schema_version=9)
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
        self.assert_owner_bound()  # finish ran on the schema-8 ledger and kept its binding (D25)
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
