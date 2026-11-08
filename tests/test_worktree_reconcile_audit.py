"""`worktree-reconcile audit`: the pre-merge check that every red path is resolved (issue 585, AC2)."""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools import verify_exec, worktree_reconcile
from agent_tools.worktree_reconcile import (ReconcileError, apply_plan, archive_dir, audit_root,
                                            build_plan, load_run_dir)

from .test_worktree_mapping import GIT_ENV, ROOT, Fleet, fake_home, printing, report

NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)


def out(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet(self)
        self.archive = self.fleet.base / "archive"
        self.archive.mkdir()
        self.run_dir = self.fleet.base / "run"
        self.run_dir.mkdir()
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plan(self, k=1, **kw):
        args = dict(fleet_roots=[self.fleet.root], archive_root=self.archive,
                    live_cwds=lambda: set(), open_prs=lambda root: {},
                    now=NOW + timedelta(minutes=k), refused_pending=False)
        args.update(kw)
        p = build_plan(self.fleet.root, report(), **args)
        (self.run_dir / f"repo-plan-{k}.json").write_text(json.dumps(p))
        return p

    def apply(self, p, k=1, record=True, **kw):
        args = dict(migrate_dry_run=report, live_cwds=lambda: set(), open_prs=lambda root: {},
                    archive_root=self.archive, acknowledge_cleanup=True)
        args.update(kw)
        a = apply_plan(p, **args)
        if record:
            (self.run_dir / f"repo-apply-{k}.json").write_text(json.dumps(a))
        return a

    def audit(self):
        plans, applies = load_run_dir(self.run_dir)
        root = str(self.fleet.root)
        return audit_root(self.fleet.root, report(), plans.get(root, []), applies.get(root, []),
                          archive_root=self.archive)

    def removed_one(self, name="gone"):
        """Plan and apply one candidate; return (plan, its result, its archive dir)."""
        self.fleet.worktree(name)
        p = self.plan()
        r = self.apply(p)["results"][0]
        self.assertEqual(r["outcome"], "removed", r["detail"])
        return p, r, archive_dir(self.archive, p["run_id"], self.fleet.root, r["n"], r["path"])

    def whys(self):
        return [u["why"] for u in self.audit()["unresolved"]]

    # --- dispositions of red paths ---------------------------------------------

    def test_nothing_red_and_no_plan_is_met(self):
        got = self.audit()
        self.assertEqual((got["red"], got["unresolved"]), (0, []))

    def test_red_with_no_plan_is_unresolved(self):
        wt = self.fleet.worktree("stray")
        self.assertEqual(self.audit()["unresolved"],
                         [{"path": wt, "why": "no_plan", "action": None, "outcome": None}])

    def test_removed_kept_and_new_since_plan_resolve(self):
        f = self.fleet
        gone, held = f.worktree("gone"), f.worktree("held")
        p = self.plan(operator_keep=frozenset({held}))
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "removed")
        late = f.worktree("late")
        got = self.audit()
        self.assertEqual(got["unresolved"], [])
        self.assertEqual([(r["path"], r["state"]) for r in got["removed"]], [(gone, "removed")])
        self.assertEqual(got["kept"], {held: ["operator"]})
        self.assertEqual(got["new_since_plan"], [late])

    def test_a_cross_device_keep_passes_the_audit(self):
        far = self.fleet.worktree("far")
        here = os.stat(self.archive).st_dev
        dev = lambda p: here + 1 if os.path.realpath(p) == os.path.realpath(far) else here
        p = self.plan(device_of=dev)
        self.assertEqual(self.apply(p, device_of=dev)["results"][0]["outcome"], "kept")
        got = self.audit()
        self.assertEqual((got["kept"], got["unresolved"]), ({far: ["cross_device"]}, []))

    def test_a_changed_candidate_is_unresolved_with_its_outcome(self):
        wt = Path(self.fleet.worktree("moving"))
        p = self.plan()
        (wt / "late.txt").write_text("x\n")
        self.apply(p)
        self.assertEqual(self.audit()["unresolved"],
                         [{"path": str(wt), "why": "planned_archive_remove", "action": "archive_remove",
                           "outcome": "changed"}])

    def test_the_latest_plan_decides(self):
        f = self.fleet
        wt = f.worktree("twice")
        self.plan(k=1, operator_keep=frozenset({wt}))
        self.plan(k=2)
        self.assertEqual(self.whys(), ["planned_archive_remove"])

    def test_a_runner_workspace_is_never_red(self):
        f = self.fleet
        head = out("rev-parse", "HEAD", cwd=f.root).strip()
        with verify_exec.workspace(f.root, head) as wt:
            got = self.audit()
        self.assertEqual((got["red"], got["unresolved"]), (0, []))
        self.assertEqual([os.path.realpath(x) for x in got["excluded"]], [os.path.realpath(wt)])

    # --- removal evidence survives a lost apply result (P9) --------------------

    def test_removal_evidence_does_not_need_the_apply_result(self):
        self.fleet.worktree("gone")
        self.apply(self.plan(), record=False)
        got = self.audit()
        self.assertEqual((got["unresolved"], [r["state"] for r in got["removed"]]), ([], ["removed"]))

    def test_an_apply_interrupted_after_the_removal_still_audits(self):
        self.fleet.worktree("gone")
        p = self.plan()
        real = worktree_reconcile.write_record

        def stop_before_removed(dir, record):
            if record["state"] == "removed":
                raise KeyboardInterrupt  # killed after `worktree remove`, before any output
            real(dir, record)

        with mock.patch.object(worktree_reconcile, "write_record", side_effect=stop_before_removed):
            with self.assertRaises(KeyboardInterrupt):
                self.apply(p, record=False)
        got = self.audit()
        self.assertEqual(got["unresolved"], [])
        self.assertEqual([r["state"] for r in got["removed"]], ["renamed"])

    def test_an_apply_interrupted_before_the_rename_is_recorded_is_unresolved(self):
        wt = self.fleet.worktree("half")
        p = self.plan()
        real = worktree_reconcile.write_record

        def stop_at_renamed(dir, record):
            if record["state"] == "renamed":
                raise KeyboardInterrupt
            real(dir, record)

        with mock.patch.object(worktree_reconcile, "write_record", side_effect=stop_at_renamed):
            with self.assertRaises(KeyboardInterrupt):
                self.apply(p, record=False)
        self.assertEqual(self.audit()["unresolved"],
                         [{"path": wt, "why": "planned_archive_remove", "action": "archive_remove",
                           "outcome": None}])

    def test_a_removal_whose_record_is_gone_is_unresolved(self):
        _, _, d = self.removed_one()
        (d / "record.json").unlink()
        self.assertEqual(self.whys(), ["record_missing"])

    def test_a_record_that_never_reached_renamed_is_unresolved(self):
        _, _, d = self.removed_one()
        rec = json.loads((d / "record.json").read_text())
        worktree_reconcile.write_record(d, {**rec, "state": "archived"})
        self.assertEqual(self.whys(), ["removal_unconfirmed"])

    def test_a_worktree_removed_by_someone_else_is_gone_elsewhere(self):
        wt = self.fleet.worktree("theirs")
        self.plan()
        out("worktree", "remove", "--force", wt, cwd=self.fleet.root)
        got = self.audit()
        self.assertEqual(got["unresolved"], [])
        self.assertEqual([g["path"] for g in got["gone_elsewhere"]], [wt])

    # --- archive integrity (P10) -----------------------------------------------

    def test_a_missing_bundle_is_unresolved(self):
        _, r, _ = self.removed_one()
        Path(r["bundle"]).unlink()
        got = self.audit()["unresolved"]
        self.assertEqual([(u["why"], u["outcome"]) for u in got], [("bundle_damaged", "removed")])

    def test_a_bundle_with_a_damaged_payload_is_unresolved(self):
        _, r, _ = self.removed_one()
        b = Path(r["bundle"])
        data = bytearray(b.read_bytes())
        data[-40] ^= 0xFF  # inside the packed objects, before the pack trailer
        b.write_bytes(bytes(data))
        self.assertEqual(self.whys(), ["bundle_damaged"])

    def test_archived_refs_and_reflogs_must_all_be_present(self):
        f = self.fleet
        wt = f.worktree("refs")
        tree = out("rev-parse", "HEAD^{tree}", cwd=wt).strip()
        out("update-ref", "refs/worktree/keep", out("commit-tree", tree, "-m", "k", cwd=wt).strip(),
            cwd=wt)
        p = self.plan()
        r = self.apply(p)["results"][0]
        admin = archive_dir(self.archive, p["run_id"], f.root, r["n"], wt) / "admin"
        for rel in ("refs/worktree/keep", "logs/HEAD"):
            with self.subTest(rel=rel):
                kept = (admin / rel).read_bytes()
                (admin / rel).unlink()
                self.assertEqual(self.whys(), ["admin_mismatch"])
                (admin / rel).write_bytes(kept)
                self.assertEqual(self.whys(), [])

    def test_a_repointed_pin_ref_is_unresolved(self):
        _, r, _ = self.removed_one()
        out("update-ref", r["archive_ref"], "refs/heads/main", cwd=self.fleet.root)
        self.assertEqual(self.whys(), ["pin_mismatch"])

    def test_a_removal_whose_pin_ref_is_gone_is_unresolved(self):
        _, r, _ = self.removed_one()
        out("update-ref", "-d", r["archive_ref"], cwd=self.fleet.root)
        self.assertEqual(self.whys(), ["archive_ref_missing"])

    # --- the root's spelling ---------------------------------------------------

    def audit_spelled_by_symlink(self):
        link = self.fleet.base / "link"
        os.symlink(self.fleet.base, link)
        plans, applies = load_run_dir(self.run_dir)
        root = str(self.fleet.root)
        return audit_root(link / self.fleet.root.name, report(), plans[root], applies[root],
                          archive_root=self.archive)

    def test_a_root_spelled_differently_from_the_plan_still_finds_its_archive(self):
        self.removed_one()
        got = self.audit_spelled_by_symlink()
        self.assertEqual(got["unresolved"], [])
        self.assertEqual([r["path"] for r in got["removed"]], [str(self.fleet.base / "gone")])

    def test_a_lost_pin_is_not_gone_elsewhere_under_another_spelling_of_the_root(self):
        _, r, _ = self.removed_one()
        out("update-ref", "-d", r["archive_ref"], cwd=self.fleet.root)
        got = self.audit_spelled_by_symlink()
        self.assertEqual([u["why"] for u in got["unresolved"]], ["archive_ref_missing"])
        self.assertEqual(got["gone_elsewhere"], [])

    # --- run directory ---------------------------------------------------------

    def test_unrelated_json_is_ignored_and_a_broken_plan_is_refused(self):
        (self.run_dir / "c7.json").write_text(json.dumps({"met": False, "roots": []}))
        (self.run_dir / "repo-apply-9.json").write_text("")  # an interrupted apply's empty stdout
        self.assertEqual(load_run_dir(self.run_dir), ({}, {}))
        (self.run_dir / "bad-plan.json").write_text('{"schema": "worktree-reconcile-plan/v2", "root": ')
        with self.assertRaises(ReconcileError):
            load_run_dir(self.run_dir)


class AuditCliTest(unittest.TestCase):
    def test_exit_1_lists_the_unresolved_path_and_exit_0_when_resolved(self):
        f = Fleet(self)
        run_dir, archive = f.base / "run", f.base / "archive"
        run_dir.mkdir()
        archive.mkdir()
        f.worktree("stray")
        env = {**os.environ, **GIT_ENV, "HOME": fake_home(self, printing(report())),
               "PYTHONPATH": str(ROOT / "python")}
        env["PATH"] = str(Path(env["HOME"]) / ".agents" / "bin") + os.pathsep + env["PATH"]
        argv = [sys.executable, "-m", "agent_tools.worktree_reconcile", "audit",
                "--run-dir", str(run_dir), "--archive-root", str(archive), "--repo-root", str(f.root)]
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(done.returncode, 1, done.stderr)
        doc = json.loads(done.stdout)
        self.assertFalse(doc["met"])
        self.assertEqual(doc["roots"][0]["unresolved"][0]["why"], "no_plan")
        out("worktree", "remove", "--force", str(f.base / "stray"), cwd=f.root)
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
