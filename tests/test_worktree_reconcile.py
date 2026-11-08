"""`agent_tools.worktree_reconcile`: archive-before-remove for unmapped worktrees (issue 585)."""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools import verify_exec, worktree_reconcile
from agent_tools.worktree_reconcile import ReconcileError, apply_plan, build_plan, restore_entry

from .test_worktree_mapping import GIT_ENV, ROOT, Fleet, report

NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)


def none_live():
    return set()


def no_prs(root):
    return {}


def out(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


def bump(path, text):
    """Rewrite `path` with same-size `text` and a later mtime, as an editor would."""
    path.write_text(text)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet(self)
        self.archive = self.fleet.base / "archive"
        self.archive.mkdir()
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plan(self, migrate_report=None, **kw):
        args = dict(fleet_roots=[self.fleet.root], archive_root=self.archive, live_cwds=none_live,
                    open_prs=no_prs, now=NOW, refused_pending=False)
        args.update(kw)
        return build_plan(self.fleet.root, migrate_report or report(), **args)

    def apply(self, plan, migrate_report=None, live_cwds=none_live, open_prs=no_prs,
              migrate_dry_run=None, **kw):
        dry = migrate_dry_run or (lambda: migrate_report or report())
        return apply_plan(plan, migrate_dry_run=dry, live_cwds=live_cwds, open_prs=open_prs,
                          archive_root=self.archive, acknowledge_cleanup=True, **kw)

    def entry(self, plan, path):
        return next(e for e in plan["entries"] if e["path"] == path)

    # --- plan ------------------------------------------------------------------

    def test_mapped_worktrees_are_never_candidates(self):
        f = self.fleet
        cur, mig = f.worktree("cur"), f.worktree("mig")
        f.ledger("L1", cur)
        f.ledger("L2", mig)
        p = self.plan(migrate_report=report(L1="current", L2="migrate"))
        self.assertEqual([e["action"] for e in p["entries"]], ["none", "none"])

    def test_a_runner_workspace_is_never_an_entry(self):
        f = self.fleet
        head = out("rev-parse", "HEAD", cwd=f.root).strip()
        with verify_exec.workspace(f.root, head) as wt:
            p = self.plan()
        self.assertEqual([os.path.realpath(x) for x in p["excluded"]], [os.path.realpath(wt)])
        self.assertEqual(p["entries"], [])

    def test_keep_reasons(self):
        f = self.fleet
        live, other, pr, locked, merging = (
            f.worktree(n) for n in ("live", "other", "pr", "locked", "merging"))
        out("worktree", "lock", locked, cwd=f.root)
        admin = Path(out("rev-parse", "--absolute-git-dir", cwd=merging).strip())
        (admin / "MERGE_HEAD").write_text(out("rev-parse", "HEAD", cwd=merging))
        second = Fleet(self)
        second.ledger("X", other)
        prs = {"pr": {"number": 7, "updated_at": (NOW - timedelta(days=2)).isoformat()}}
        p = self.plan(fleet_roots=[f.root, second.root], live_cwds=lambda: {live + "/sub"},
                      open_prs=lambda root: prs)
        self.assertEqual(self.entry(p, live)["keep"], ["live_process"])
        self.assertEqual(self.entry(p, other)["keep"], ["fleet_ledger"])
        self.assertEqual(self.entry(p, pr)["keep"], ["open_pr"])
        self.assertEqual(self.entry(p, locked)["keep"], ["locked"])
        self.assertEqual(self.entry(p, merging)["keep"], ["git_operation"])
        self.assertEqual(p["fleet_roots"], [str(f.root), str(second.root)])

    def test_a_per_worktree_ref_to_a_non_commit_keeps_the_worktree(self):
        wt = self.fleet.worktree("blobref")
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=wt, input="x\n",
                              capture_output=True, text=True, check=True).stdout.strip()
        out("update-ref", "refs/worktree/odd", blob, cwd=wt)
        e = self.entry(self.plan(), wt)
        self.assertEqual(e["keep"], ["git_operation"])
        self.assertEqual(e["pins"]["non_commit"][0]["sha"], blob)

    def test_an_open_pr_keeps_whatever_its_age(self):
        held = self.fleet.worktree("held")
        prs = {"held": {"number": 8, "updated_at": (NOW - timedelta(days=300)).isoformat()}}
        e = self.entry(self.plan(open_prs=lambda root: prs), held)
        self.assertEqual((e["action"], e["keep"]), ("keep", ["open_pr"]))

    def test_refused_only_is_kept_while_its_ledgers_are_pending(self):
        f = self.fleet
        ref = f.worktree("ref")
        f.ledger("L3", ref)
        p = self.plan(migrate_report=report(L3="refused"), refused_pending=True)
        self.assertEqual(self.entry(p, ref)["keep"], ["refused_ledger_pending"])

    def test_an_operator_keep_is_honoured(self):
        held = self.fleet.worktree("held")
        p = self.plan(operator_keep=frozenset({held}))
        self.assertEqual(self.entry(p, held)["keep"], ["operator"])

    def test_an_operator_keep_is_normalized_before_it_is_compared(self):
        held = self.fleet.worktree("held")
        for spelling in (held + "/", held + "/../held", os.path.relpath(held)):
            with self.subTest(spelling=spelling):
                p = self.plan(operator_keep=frozenset({spelling}))
                self.assertEqual(self.entry(p, held)["keep"], ["operator"])
                self.assertEqual(p["operator_keep"], [os.path.realpath(held)])

    def test_a_tilde_operator_keep_is_expanded(self):
        held = self.fleet.worktree("held")
        with mock.patch.dict(os.environ, {"HOME": str(self.fleet.base)}):
            p = self.plan(operator_keep=frozenset({"~/held"}))
        self.assertEqual(self.entry(p, held)["keep"], ["operator"])

    def test_an_operator_keep_matching_no_worktree_is_refused(self):
        self.fleet.worktree("held")
        with self.assertRaises(ReconcileError) as caught:
            self.plan(operator_keep=frozenset({str(self.fleet.base / "typo")}))
        self.assertEqual(caught.exception.code, "unknown_keep")

    def test_a_worktree_holding_another_worktree_is_kept_and_the_inner_one_survives(self):
        f = self.fleet
        outer = f.worktree("outer")
        inner = f.worktree("inner", at=Path(outer) / ".worktrees" / "inner")
        f.ledger("L1", inner)
        p = self.plan(migrate_report=report(L1="current"))
        self.assertEqual(self.entry(p, outer)["keep"], ["nested_worktree"])
        self.assertEqual(self.entry(p, outer)["action"], "keep")
        self.assertEqual(self.entry(p, inner)["action"], "none")
        result = self.apply(p, migrate_report=report(L1="current"))
        self.assertEqual({r["path"]: r["outcome"] for r in result["results"]},
                         {outer: "kept", inner: "kept"})
        self.assertTrue(os.path.isdir(inner))
        self.assertTrue(os.path.isdir(outer))
        self.assertNotIn("prunable", out("worktree", "list", "--porcelain", cwd=f.root))

    def test_reftable_storage_is_refused(self):
        other = self.fleet.base / "reftable"
        other.mkdir()
        out("init", "-q", "-b", "main", "--ref-format=reftable", cwd=other)
        out("commit", "-q", "--allow-empty", "-m", "a", cwd=other)
        with self.assertRaises(ReconcileError) as caught:
            build_plan(other, report(), fleet_roots=[other], archive_root=self.archive,
                       live_cwds=none_live, open_prs=no_prs, now=NOW, refused_pending=False)
        self.assertEqual(caught.exception.code, "unsupported_ref_storage")

    def test_a_cross_device_worktree_is_kept_in_the_plan(self):
        far = self.fleet.worktree("far")
        here = os.stat(self.archive).st_dev
        dev = lambda p: here + 1 if os.path.realpath(p) == os.path.realpath(far) else here
        p = self.plan(device_of=dev)
        self.assertEqual((self.entry(p, far)["action"], self.entry(p, far)["keep"]),
                         ("keep", ["cross_device"]))
        self.assertEqual(p["archive_root"], str(self.archive))

    # --- apply refusals and re-derivation --------------------------------------

    def test_apply_refuses_without_acknowledgement(self):
        with self.assertRaises(ReconcileError):
            apply_plan(self.plan(), migrate_dry_run=report, live_cwds=none_live, open_prs=no_prs,
                       archive_root=self.archive, acknowledge_cleanup=False)

    def test_apply_refuses_an_archive_root_other_than_the_plans(self):
        self.fleet.worktree("elsewhere")
        other = self.fleet.base / "other-archive"
        other.mkdir()
        with self.assertRaises(ReconcileError) as caught:
            apply_plan(self.plan(), migrate_dry_run=report, live_cwds=none_live, open_prs=no_prs,
                       archive_root=other, acknowledge_cleanup=True)
        self.assertEqual(caught.exception.code, "bad_plan")
        self.assertEqual(list(other.iterdir()), [])

    def test_two_candidates_are_removed_in_one_apply_though_positions_shift(self):
        f = self.fleet
        b1, b2 = Path(f.worktree("b1")), Path(f.worktree("b2"))
        p = self.plan()
        planned = {e["path"]: e["n"] for e in p["entries"]}
        early = Path(f.worktree("a0"))  # sorts before b1 and b2: their positions shift by one
        results = self.apply(p)["results"]
        self.assertEqual([(r["path"], r["outcome"]) for r in results],
                         [(str(b1), "removed"), (str(b2), "removed")])
        self.assertEqual({r["path"]: r["n"] for r in results}, planned)
        self.assertTrue(early.exists())
        self.assertFalse(b1.exists() or b2.exists())

    def test_the_dry_run_is_refreshed_for_each_candidate(self):
        f = self.fleet
        first, revived = Path(f.worktree("a-first")), Path(f.worktree("b-revived"))
        f.ledger("L3", str(revived))
        p = self.plan(migrate_report=report(L3="refused"))
        self.assertEqual([e["action"] for e in p["entries"]], ["archive_remove", "archive_remove"])
        answers = iter([report(L3="refused"), report(L3="migrate")])
        calls = []
        def dry():
            calls.append(1)
            return next(answers)  # the ledger is repaired while a-first is archived
        results = self.apply(p, migrate_dry_run=dry)["results"]
        self.assertEqual([r["outcome"] for r in results], ["removed", "changed"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(revived.exists())
        self.assertFalse(first.exists())

    def test_a_worktree_changed_after_planning_is_untouched(self):
        wt = Path(self.fleet.worktree("moving"))
        p = self.plan()
        (wt / "new.txt").write_text("late\n")
        r = self.apply(p)["results"][0]
        self.assertEqual(r["outcome"], "changed")
        self.assertTrue((wt / "new.txt").exists())

    def test_an_edit_to_an_already_dirty_file_is_seen(self):
        wt = Path(self.fleet.worktree("dirty-edit"))
        (wt / "u.txt").write_text("a\n")
        p = self.plan()
        bump(wt / "u.txt", "b\n")
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "changed")

    def test_an_edit_to_an_ignored_file_is_seen(self):
        f = self.fleet
        wt = Path(f.worktree("ignored-edit"))
        (f.root / ".git" / "info" / "exclude").write_text(".env\n")
        (wt / ".env").write_text("A=1\n")
        p = self.plan()
        bump(wt / ".env", "A=2\n")
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "changed")

    def test_a_new_reflog_line_after_planning_is_seen(self):
        wt = self.fleet.worktree("logged")
        p = self.plan()
        out("commit", "-q", "--allow-empty", "-m", "late", cwd=wt)
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "changed")

    def test_a_ledger_added_in_another_root_after_planning_is_untouched(self):
        f, second = self.fleet, Fleet(self)
        wt = f.worktree("adopted")
        p = self.plan(fleet_roots=[f.root, second.root])
        second.ledger("X", wt)
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "changed")
        self.assertTrue(Path(wt).exists())

    def test_a_refused_ledger_that_became_resumable_is_untouched(self):
        f = self.fleet
        wt = f.worktree("revived")
        f.ledger("L3", wt)
        p = self.plan(migrate_report=report(L3="refused"))
        self.assertEqual(self.entry(p, wt)["action"], "archive_remove")
        r = self.apply(p, migrate_report=report(L3="migrate"))["results"][0]
        self.assertEqual(r["outcome"], "changed")
        self.assertTrue(Path(wt).exists())

    def test_a_pr_opened_after_planning_is_untouched(self):
        wt = self.fleet.worktree("late-pr")
        p = self.plan()
        prs = {"late-pr": {"number": 9, "updated_at": NOW.isoformat()}}
        self.assertEqual(self.apply(p, open_prs=lambda root: prs)["results"][0]["outcome"], "changed")
        self.assertTrue(Path(wt).exists())

    def test_a_worktree_live_at_apply_is_untouched(self):
        wt = self.fleet.worktree("late-live")
        r = self.apply(self.plan(), live_cwds=lambda: {wt})["results"][0]
        self.assertEqual(r["outcome"], "changed")
        self.assertTrue(Path(wt).exists())

    def test_a_change_in_the_admin_directory_alone_is_seen(self):
        wt = self.fleet.worktree("admin-edit")
        p = self.plan()
        admin = Path(self.entry(p, wt)["admin"])
        (admin / "note").write_text("late\n")
        self.assertEqual(self.apply(p)["results"][0]["outcome"], "changed")

    def test_restore_names_why_it_refuses(self):
        wt = Path(self.fleet.worktree("restorable"))
        kept = Path(self.fleet.worktree("kept"))
        p = self.plan(operator_keep=frozenset({str(kept)}))
        result = self.apply(p)
        manifest = Path(result["manifest"])
        by_path = {r["path"]: r for r in result["results"]}
        with self.assertRaises(ReconcileError) as caught:
            restore_entry(manifest, by_path[str(kept)]["n"])
        self.assertEqual(caught.exception.code, "not_removed")
        wt.mkdir()
        with self.assertRaises(ReconcileError) as caught:
            restore_entry(manifest, by_path[str(wt)]["n"])
        self.assertEqual(caught.exception.code, "path_exists")

    # --- archive, removal and restore -----------------------------------------

    def rich(self):
        """A worktree whose git state is all at risk on removal: a commit reachable only from its
        reflog, a per-worktree ref to another dangling commit, an unpushed commit, a staged file
        edited again after staging, an unstaged tracked deletion, untracked and ignored files."""
        f = self.fleet
        wt = Path(f.worktree("rich"))
        out("commit", "-q", "--allow-empty", "-m", "lost", cwd=wt)
        lost = out("rev-parse", "HEAD", cwd=wt).strip()
        out("reset", "-q", "--hard", "HEAD~1", cwd=wt)
        tree = out("rev-parse", "HEAD^{tree}", cwd=wt).strip()
        kept = out("commit-tree", tree, "-m", "per-worktree", cwd=wt).strip()
        out("update-ref", "refs/worktree/keep", kept, cwd=wt)
        (wt / "a.txt").write_text("a\n")
        (wt / "del.txt").write_text("d\n")
        out("add", "a.txt", "del.txt", cwd=wt)
        out("commit", "-q", "-m", "unpushed", cwd=wt)
        (wt / "del.txt").unlink()
        (wt / "staged.txt").write_text("v1\n")
        out("add", "staged.txt", cwd=wt)
        (wt / "staged.txt").write_text("v2\n")
        (wt / "untracked.txt").write_text("u\n")
        (f.root / ".git" / "info" / "exclude").write_text(".env\n")
        (wt / ".env").write_text("SECRET=1\n")
        return wt, out("rev-parse", "HEAD", cwd=wt).strip(), lost, kept

    def test_a_rich_worktree_is_archived_then_removed_and_survives_gc(self):
        f = self.fleet
        wt, head, lost, kept = self.rich()
        result = self.apply(self.plan())
        self.assertEqual(result["schema"], worktree_reconcile.APPLY_SCHEMA)
        r = result["results"][0]
        self.assertEqual(r["outcome"], "removed", r["detail"])
        self.assertNotIn(str(wt), out("worktree", "list", "--porcelain", cwd=f.root))
        self.assertFalse(wt.exists())
        out("reflog", "expire", "--expire=now", "--all", cwd=f.root)
        out("gc", "-q", "--prune=now", cwd=f.root)
        pin = r["archive_ref"]
        self.assertEqual(out("rev-parse", pin + "^1", cwd=f.root).strip(), head)
        self.assertEqual(out("show", pin + ":staged.txt", cwd=f.root), "v1\n")
        parents = out("rev-list", "--parents", "-n", "1", pin, cwd=f.root).split()[1:]
        self.assertIn(lost, parents)
        self.assertIn(kept, parents)
        tree = Path(r["directory"])
        self.assertEqual((tree / ".env").read_text(), "SECRET=1\n")
        self.assertEqual((tree / "staged.txt").read_text(), "v2\n")
        admin = Path(r["admin"])
        self.assertTrue((admin / "index").is_file())
        self.assertEqual((admin / "refs" / "worktree" / "keep").read_text().strip(), kept)
        self.assertIn(lost, (admin / "logs" / "HEAD").read_text())
        out("bundle", "verify", r["bundle"], cwd=f.root)
        self.assertIn(pin, out("bundle", "list-heads", r["bundle"], cwd=f.root))
        self.assertEqual(out("rev-parse", "refs/heads/rich", cwd=f.root).strip(), head)
        manifest = json.loads(Path(result["manifest"]).read_text())
        self.assertEqual(manifest["results"][0]["n"], r["n"])
        self.assertEqual(os.stat(result["manifest"]).st_mode & 0o777, 0o600)
        d = worktree_reconcile.archive_dir(self.archive, result["run_id"], f.root, r["n"], str(wt))
        record = json.loads((d / "record.json").read_text())
        self.assertEqual((record["schema"], record["state"]),
                         (worktree_reconcile.ARCHIVE_SCHEMA, "removed"))
        self.assertEqual(record["pin"], out("rev-parse", pin, cwd=f.root).strip())
        self.assertIn("refs/worktree/keep", record["admin_files"])
        self.assertIn("logs/HEAD", record["admin_files"])
        self.assertEqual(record["admin_files"], worktree_reconcile.admin_digests(admin))
        self.assertEqual(record["bundle_heads"], [[record["pin"], pin]])
        self.assertFalse((d / ".bundle-check").exists())

    def test_restore_reproduces_head_branch_index_refs_reflog_files_and_deletions(self):
        wt, head, lost, kept = self.rich()
        result = self.apply(self.plan())
        out("reflog", "expire", "--expire=now", "--all", cwd=self.fleet.root)
        out("gc", "-q", "--prune=now", cwd=self.fleet.root)
        got = restore_entry(Path(result["manifest"]), result["results"][0]["n"])
        self.assertEqual((got["head"], got["branch"]), (head, "refs/heads/rich"))
        self.assertEqual(out("rev-parse", "HEAD", cwd=wt).strip(), head)
        self.assertEqual(out("symbolic-ref", "HEAD", cwd=wt).strip(), "refs/heads/rich")
        self.assertEqual(out("rev-parse", "refs/worktree/keep", cwd=wt).strip(), kept)
        self.assertIn(lost, out("reflog", "--format=%H", "HEAD", cwd=wt))
        self.assertEqual(out("show", ":staged.txt", cwd=wt), "v1\n")
        self.assertEqual((wt / "staged.txt").read_text(), "v2\n")
        self.assertFalse((wt / "del.txt").exists())
        status = out("status", "--porcelain=v1", cwd=wt).splitlines()
        self.assertIn(" D del.txt", status)
        self.assertIn("AM staged.txt", status)
        self.assertEqual((wt / ".env").read_text(), "SECRET=1\n")
        self.assertEqual((wt / "untracked.txt").read_text(), "u\n")
        with self.assertRaises(ReconcileError):
            restore_entry(Path(result["manifest"]), result["results"][0]["n"])

    def test_a_missing_directory_keeps_its_commit_and_drops_the_registration(self):
        f = self.fleet
        wt = Path(f.worktree("gone"))
        head = out("rev-parse", "HEAD", cwd=wt).strip()
        subprocess.run(["rm", "-rf", str(wt)], check=True)
        r = self.apply(self.plan())["results"][0]
        self.assertEqual((r["outcome"], r["directory"]), ("removed", None), r["detail"])
        self.assertEqual(out("rev-parse", r["archive_ref"] + "^1", cwd=f.root).strip(), head)
        self.assertNotIn(str(wt), out("worktree", "list", "--porcelain", cwd=f.root))


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, "-m", "agent_tools.worktree_reconcile", *argv],
                              cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "python")})

    def test_help_names_the_command(self):
        done = self.run_cli("--help")
        self.assertEqual(done.returncode, 0)
        self.assertTrue(done.stdout.startswith("usage: worktree-reconcile"))

    def test_apply_without_acknowledgement_refuses_before_any_probe(self):
        done = self.run_cli("apply", "--plan", os.devnull, "--archive-root", os.devnull)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.startswith("worktree-reconcile: not_acknowledged: "))


if __name__ == "__main__":
    unittest.main()
