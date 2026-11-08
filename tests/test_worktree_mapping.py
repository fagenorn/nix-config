"""`agent_tools.worktree_mapping`: the #130 checklist C7 rule as code (issue 585)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import verify_exec, worktree_mapping
from agent_tools.worktree_mapping import (
    ForgeFacts, MappingError, classify, classify_root, ledger_matches)

ROOT = Path(__file__).resolve().parents[1]
CHECK = "home/common/verify-pending/checks/worktree-mapping"
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(*argv, cwd):
    subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


class Fleet:
    """One repository with linked worktrees and hand-written ledgers."""

    def __init__(self, case):
        self._tmp = tempfile.TemporaryDirectory()
        case.addCleanup(self._tmp.cleanup)
        self.base = Path(os.path.realpath(self._tmp.name))
        self.root = self.base / "repo"
        self.root.mkdir()
        git("init", "-q", "-b", "main", cwd=self.root)
        git("commit", "-q", "--allow-empty", "-m", "a", cwd=self.root)

    def worktree(self, name, *, detach=False, at=None):
        path = Path(at) if at else self.base / name
        if detach:
            git("worktree", "add", "-q", "--detach", str(path), cwd=self.root)
        else:
            git("worktree", "add", "-q", "-b", name, str(path), cwd=self.root)
        return str(path)

    def ledger(self, name, *paths):
        d = self.root / ".superpowers" / "workflows" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({"worktrees": list(paths)}), encoding="utf-8")


def report(**verdicts):
    return {"counts": {}, "ledgers": [{"ledger": k, "verdict": v} for k, v in verdicts.items()]}


def printing(rep):
    """A fake `workflow-state` body that prints `rep` as its dry-run report."""
    return "printf '%s\\n' '" + json.dumps(rep) + "'\n"


def fake_home(case, body):
    """A HOME whose `.agents/bin/workflow-state` runs `body`."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    bin_dir = Path(tmp.name) / ".agents" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "workflow-state"
    fake.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return tmp.name


class ClassifyTest(unittest.TestCase):
    def test_the_c7_precedence(self):
        v = {"a": "current", "b": "migrate", "c": "refused", "d": "migrated"}
        self.assertEqual(classify([], v), "unmapped")
        self.assertEqual(classify(["b", "a"], v), "current")
        self.assertEqual(classify(["d"], v), "current")
        self.assertEqual(classify(["c", "b"], v), "migrate")
        self.assertEqual(classify(["c"], v), "refused-only")
        self.assertEqual(classify(["absent"], v), "refused-only")


class ClassifyRootTest(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet(self)

    def test_a_root_without_linked_worktrees_is_green(self):
        got = classify_root(self.fleet.root, report())
        self.assertEqual((got["worktrees"], got["verdict"]), (0, "green"))

    def test_each_class_and_the_row_verdict(self):
        f = self.fleet
        cur, mig, ref, un = (f.worktree(n) for n in ("cur", "mig", "ref", "un"))
        f.ledger("L1", cur)
        f.ledger("L2", mig)
        f.ledger("L3", ref)
        got = classify_root(f.root, report(L1="current", L2="migrate", L3="refused"))
        self.assertEqual(got["counts"], {"current": 1, "migrate": 1, "refused-only": 1, "unmapped": 1})
        self.assertEqual(got["verdict"], "red")
        self.assertEqual([p["path"] for p in got["paths"]], [cur, mig, ref, un])
        self.assertEqual(got["paths"][2], {"class": "refused-only", "path": ref, "ledgers": ["L3"]})

    def test_refused_only_is_red(self):
        f = self.fleet
        f.ledger("L3", f.worktree("ref"))
        self.assertEqual(classify_root(f.root, report(L3="refused"))["verdict"], "red")

    def test_migrate_only_is_human_pending(self):
        f = self.fleet
        f.ledger("L2", f.worktree("mig"))
        self.assertEqual(classify_root(f.root, report(L2="migrate"))["verdict"], "human-pending")

    def test_a_prefix_path_does_not_map(self):
        f = self.fleet
        short = f.worktree("x")
        f.ledger("L1", short + "-y")
        self.assertEqual(ledger_matches(f.root, short), [])

    def test_a_non_ascii_path_maps_whatever_the_quote_path_setting(self):
        f = self.fleet
        wt = f.worktree("caf\u00e9")
        f.ledger("L1", wt)  # json.dumps escapes the accented letter
        for quote in ("true", "false"):
            with self.subTest(quote_path=quote), mock.patch.dict(os.environ, {
                    **GIT_ENV, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.quotePath",
                    "GIT_CONFIG_VALUE_0": quote}):
                got = classify_root(f.root, report(L1="current"))
                self.assertEqual([(p["path"], p["class"]) for p in got["paths"]], [(wt, "current")])
                self.assertEqual(ledger_matches(f.root, wt), ["L1"])

    def test_a_raw_utf8_ledger_still_maps(self):
        f = self.fleet
        wt = f.worktree("caf\u00e9")
        d = f.root / ".superpowers" / "workflows" / "L1"
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({"worktrees": [wt]}, ensure_ascii=False),
                                      encoding="utf-8")
        self.assertEqual(ledger_matches(f.root, wt), ["L1"])

    def test_the_realpath_maps(self):
        f = self.fleet
        real = f.worktree("real")
        link = f.base / "alias"
        link.symlink_to(real)
        f.ledger("L1", real)
        self.assertEqual(ledger_matches(f.root, str(link)), ["L1"])

    def test_lookalikes_of_a_runner_workspace_are_not_excluded(self):
        f = self.fleet
        (f.base / "verify-pending-short").mkdir()
        (f.base / "verify-pending-abcdefgh").mkdir()
        wrong_parent = f.worktree("a", detach=True, at=f.base / "verify-pending-short" / "wt")
        on_branch = f.worktree("b", at=f.base / "verify-pending-abcdefgh" / "wt")
        got = classify_root(f.root, report())
        self.assertEqual(got["excluded"], [])
        # Porcelain order: git lists linked worktrees sorted by path, so
        # ".../verify-pending-abcdefgh/wt" comes before ".../verify-pending-short/wt".
        self.assertEqual([p["path"] for p in got["paths"]], [on_branch, wrong_parent])
        self.assertEqual(got["verdict"], "red")

    def test_a_report_without_ledgers_is_refused(self):
        with self.assertRaises(MappingError):
            classify_root(self.fleet.root, {"counts": {}})

    def test_a_git_failure_is_refused(self):
        with self.assertRaises(MappingError):
            classify_root(self.fleet.base / "missing", report())


class ForgeClassifyTest(unittest.TestCase):
    """Issue 710: forge facts map an otherwise unmapped worktree, with the reason (D2, D8)."""

    def setUp(self):
        self.fleet = Fleet(self)
        self.calls = []

    def reader(self, facts):
        def read(root):
            self.calls.append(root)
            return facts
        return read

    def test_a_claim_an_open_pr_and_a_declared_branch_each_map_with_their_reason(self):
        f = self.fleet
        claimed, pr, declared = (f.worktree(n) for n in ("c-br", "p-br", "d-br"))
        facts = ForgeFacts(
            claims={"c-br": [{"issue": 7, "comment_id": 70, "holder": "h/s"}]},
            open_prs={"p-br": 9}, declared={"d-br": 130})
        got = classify_root(f.root, report(), forge=self.reader(facts))
        self.assertEqual(got["verdict"], "green")
        self.assertEqual(got["counts"], {"current": 0, "migrate": 0, "refused-only": 0,
                                         "unmapped": 0, "forge": 3})
        # Porcelain order: git lists linked worktrees sorted by path (as in
        # test_lookalikes_of_a_runner_workspace_are_not_excluded), so c-br, d-br, p-br.
        self.assertEqual(got["paths"], [
            {"class": "forge", "path": claimed, "ledgers": [], "branch": "c-br",
             "forge": [{"reason": "claim", "issue": 7, "comment_id": 70, "holder": "h/s"}]},
            {"class": "forge", "path": declared, "ledgers": [], "branch": "d-br",
             "forge": [{"reason": "declared", "issue": 130}]},
            {"class": "forge", "path": pr, "ledgers": [], "branch": "p-br",
             "forge": [{"reason": "open_pr", "pr": 9}]}])
        self.assertEqual(self.calls, [f.root])

    def test_every_reason_is_listed_in_order(self):
        f = self.fleet
        f.worktree("all")
        facts = ForgeFacts(claims={"all": [{"issue": 1, "comment_id": 2, "holder": None}]},
                           open_prs={"all": 3}, declared={"all": 4})
        row = classify_root(f.root, report(), forge=self.reader(facts))["paths"][0]
        self.assertEqual([r["reason"] for r in row["forge"]], ["claim", "open_pr", "declared"])

    def test_an_unclaimed_stale_worktree_stays_red(self):
        f = self.fleet
        stale = f.worktree("stale")
        f.worktree("c-br")
        facts = ForgeFacts(claims={"c-br": [{"issue": 7, "comment_id": 70, "holder": "h/s"}]})
        got = classify_root(f.root, report(), forge=self.reader(facts))
        self.assertEqual(got["verdict"], "red")
        self.assertEqual((got["counts"]["unmapped"], got["counts"]["forge"]), (1, 1))
        self.assertIn({"class": "unmapped", "path": stale, "ledgers": []}, got["paths"])

    def test_refused_only_and_migrate_keep_their_ledger_class(self):
        f = self.fleet
        f.ledger("L3", f.worktree("ref"))
        f.ledger("L2", f.worktree("mig"))
        facts = ForgeFacts(open_prs={"ref": 1, "mig": 2})
        got = classify_root(f.root, report(L3="refused", L2="migrate"), forge=self.reader(facts))
        self.assertEqual(sorted(p["class"] for p in got["paths"]), ["migrate", "refused-only"])
        self.assertEqual(got["verdict"], "red")
        self.assertEqual(self.calls, [])  # no unmapped path, no forge read

    def test_a_detached_worktree_never_maps(self):
        f = self.fleet
        f.worktree("x", detach=True)
        got = classify_root(f.root, report(), forge=self.reader(ForgeFacts(open_prs={"x": 1})))
        self.assertEqual(got["paths"][0]["class"], "unmapped")
        self.assertEqual(self.calls, [])

    def test_short_branch_keeps_the_reconcile_semantics(self):
        self.assertEqual([worktree_mapping.short_branch(b) for b in
                          (None, "refs/heads/a/b", "refs/heads/", "odd")], [None, "a/b", "", "odd"])

    def test_without_a_reader_the_document_is_unchanged(self):
        f = self.fleet
        un = f.worktree("un")
        got = classify_root(f.root, report())
        self.assertEqual(set(got["counts"]), set(worktree_mapping.CLASSES))
        self.assertEqual(got["paths"], [{"class": "unmapped", "path": un, "ledgers": []}])


class WrapperTest(unittest.TestCase):
    def run_check(self, fake_body, *roots, flags=()):
        argv = [str(ROOT / CHECK), *flags]
        for r in roots:
            argv += ["--repo-root", str(r)]
        return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, **GIT_ENV, "HOME": fake_home(self, fake_body)})

    def test_green_root_exits_0(self):
        f = Fleet(self)
        f.ledger("L1", f.worktree("cur"))
        done = self.run_check(printing(report(L1="current")), f.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["met"])

    def test_red_root_exits_1_and_human_pending_exits_75(self):
        red, pending = Fleet(self), Fleet(self)
        red.worktree("un")
        pending.ledger("L2", pending.worktree("mig"))
        body = printing(report(L2="migrate"))
        self.assertEqual(self.run_check(body, pending.root).returncode, 75)
        done = self.run_check(body, pending.root, red.root)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual([r["verdict"] for r in json.loads(done.stdout)["roots"]], ["human-pending", "red"])

    def test_red_pending_reads_red_as_not_yet(self):
        red = Fleet(self)
        red.worktree("un")
        done = self.run_check(printing(report()), red.root, flags=("--red-pending",))
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(json.loads(done.stdout)["roots"][0]["verdict"], "red")

    def test_a_failing_dry_run_is_exit_2_with_its_diagnostic(self):
        f = Fleet(self)
        done = self.run_check("echo boom >&2\nexit 4\n", f.root)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("workflow-state exit 4: boom", done.stderr)

    def test_wrapper_is_committed_executable(self):
        mode = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", CHECK],
                              capture_output=True, text=True, check=True).stdout.split(" ")[0]
        self.assertEqual(mode, "100755")


class RunnerSeamTest(unittest.TestCase):
    """The check as verify-pending runs it: the committed script inside a detached worktree that
    `verify_exec.workspace` adds to the very root it inspects, with a second runner workspace
    open on the same root at the same time (O2, P7)."""

    def setUp(self):
        f = self.fleet = Fleet(self)
        shutil.copytree(ROOT / "python" / "agent_tools", f.root / "python" / "agent_tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (f.root / CHECK).parent.mkdir(parents=True)
        shutil.copy2(ROOT / CHECK, f.root / CHECK)
        git("add", "python", CHECK, cwd=f.root)
        git("commit", "-q", "-m", "check", cwd=f.root)
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=f.root, check=True,
                                     capture_output=True, text=True).stdout.strip()

    def run_in_runner(self, rep, *flags):
        """({realpaths of both runner worktrees}, Result) of one run through the real seam."""
        home = fake_home(self, printing(rep))
        with mock.patch.dict(os.environ, {**GIT_ENV, "HOME": home}):
            with verify_exec.workspace(self.fleet.root, self.commit) as other, \
                    verify_exec.workspace(self.fleet.root, self.commit) as wt:
                argv, cwd = verify_exec.run_argv(
                    {"script": CHECK, "args": [*flags, "--repo-root", str(self.fleet.root)]},
                    {}, self.fleet.root, wt)
                return ({os.path.realpath(other), os.path.realpath(wt)},
                        verify_exec.execute(argv, cwd))

    def test_runner_worktrees_never_turn_their_root_red(self):
        f = self.fleet
        f.ledger("L1", f.worktree("cur"))
        runners, result = self.run_in_runner(report(L1="current"), "--red-pending")
        self.assertEqual(verify_exec.classify(result, None), "met", result.stderr)
        got = json.loads(result.stdout)["roots"][0]
        self.assertEqual({os.path.realpath(p) for p in got["excluded"]}, runners)
        self.assertEqual((got["worktrees"], got["verdict"]), (1, "green"))

    def test_only_runner_worktrees_are_left_out(self):
        self.fleet.worktree("stray")
        _, result = self.run_in_runner(report(), "--red-pending")
        self.assertEqual(verify_exec.classify(result, None), "not_yet", result.stderr)
        got = json.loads(result.stdout)["roots"][0]
        self.assertEqual((got["counts"]["unmapped"], len(got["excluded"])), (1, 2))
        _, result = self.run_in_runner(report())
        self.assertEqual(verify_exec.classify(result, None), "not_met", result.stderr)


def write_fake_gh(bin_dir, home):
    """A fake `gh` in `bin_dir` answering `gh api [--paginate --slurp] <path>` from
    `home/responses.json` (path -> JSON) and logging every argv to `home/gh.log`."""
    gh = Path(bin_dir) / "gh"
    gh.write_text(f"#!{sys.executable}\n" + f"HOME_DIR = {str(home)!r}\n" + """
import json, os, sys
with open(os.path.join(HOME_DIR, "gh.log"), "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
responses = json.load(open(os.path.join(HOME_DIR, "responses.json")))
path = sys.argv[-1]
if sys.argv[1] != "api" or path not in responses:
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
print(json.dumps(responses[path]))
""", encoding="utf-8")
    gh.chmod(0o755)


def fake_forge_home(case, rep, responses):
    """A HOME whose `.agents/bin` holds a fake `workflow-state` printing `rep` and the fake `gh`."""
    home = Path(fake_home(case, printing(rep)))
    (home / "responses.json").write_text(json.dumps(responses), encoding="utf-8")
    write_fake_gh(home / ".agents" / "bin", home)
    return str(home)


def comment(cid, body, assoc="OWNER"):
    return {"id": cid, "body": body, "author_association": assoc,
            "updated_at": "2026-11-08T00:00:00Z"}


ISSUES = "repos/o/r/issues?labels=in-progress&state=open&per_page=100"
PULLS = "repos/o/r/pulls?state=open&per_page=100"


def pull(number, ref, repo="o/r", base="o/r"):
    return {"number": number, "updated_at": "2026-11-08T00:00:00Z",
            "head": {"ref": ref, "repo": {"full_name": repo} if repo else None},
            "base": {"repo": {"full_name": base}}}


class ForgeWrapperTest(unittest.TestCase):
    """Issue 710 AC1 through the committed wrapper: forge facts map a worktree, fail-closed."""

    def run_check(self, fleet, responses, *flags, slug="o/r"):
        git("remote", "add", "origin", f"https://github.com/{slug}.git", cwd=fleet.root)
        self.home = fake_forge_home(self, report(), responses)
        return subprocess.run(
            [str(ROOT / CHECK), *flags, "--repo-root", str(fleet.root)], cwd=ROOT,
            capture_output=True, text=True, timeout=60,
            env={**os.environ, **GIT_ENV, "HOME": self.home})

    def row(self, done):
        return json.loads(done.stdout)["roots"][0]

    def gh_calls(self):
        log = Path(self.home) / "gh.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_a_claimed_worktree_maps(self):
        f = Fleet(self)
        f.worktree("issue-12-x")
        claim = "<!-- agent:claim v1 issue=12 holder=h/s branch=issue-12-x renewed=1 -->\nClaimed."
        done = self.run_check(f, {ISSUES: [[{"number": 12}]], PULLS: [[]],
                                  "repos/o/r/issues/12/comments?per_page=100": [[comment(55, claim)]]})
        self.assertEqual(done.returncode, 0, done.stderr)
        got = self.row(done)
        self.assertEqual((got["verdict"], got["counts"]["forge"]), ("green", 1))
        self.assertEqual(got["paths"][0]["forge"],
                         [{"reason": "claim", "issue": 12, "comment_id": 55, "holder": "h/s"}])
        self.assertTrue(all("-X" not in argv for argv in self.gh_calls()))

    def test_an_organization_member_claim_maps(self):
        f = Fleet(self)
        f.worktree("issue-12-x")
        claim = "<!-- agent:claim v1 issue=12 holder=h/s branch=issue-12-x renewed=1 -->\nClaimed."
        done = self.run_check(f, {ISSUES: [[{"number": 12}]], PULLS: [[]],
                                  "repos/o/r/issues/12/comments?per_page=100":
                                      [[comment(55, claim, "MEMBER")]]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["class"], "forge")

    def test_an_open_pr_worktree_maps(self):
        f = Fleet(self)
        f.worktree("feature")
        done = self.run_check(f, {ISSUES: [[]], PULLS: [[pull(9, "feature")], [pull(8, "feature")]]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["forge"], [{"reason": "open_pr", "pr": 8}])

    def test_an_open_pr_maps_when_the_repository_was_renamed_behind_origin(self):
        f = Fleet(self)
        f.worktree("feature")
        done = self.run_check(f, {ISSUES: [[]], PULLS: [[pull(5, "feature", repo="new/r", base="new/r")]]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["forge"], [{"reason": "open_pr", "pr": 5}])

    def test_a_fork_pr_into_a_renamed_repository_maps_nothing(self):
        f = Fleet(self)
        f.worktree("feature")
        done = self.run_check(f, {ISSUES: [[]], PULLS: [[pull(5, "feature", repo="fork/r", base="new/r")]]})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["class"], "unmapped")

    def test_the_declared_candidate_maps_while_its_issue_is_open(self):
        for state, code in (("open", 0), ("closed", 1)):
            with self.subTest(state=state):
                f = Fleet(self)
                f.worktree("cutover-130-candidate")
                done = self.run_check(f, {
                    "repos/fagenorn/nix-config/issues?labels=in-progress&state=open&per_page=100": [[]],
                    "repos/fagenorn/nix-config/pulls?state=open&per_page=100": [[]],
                    "repos/fagenorn/nix-config/issues/130": {"number": 130, "state": state}},
                    slug="fagenorn/nix-config")
                self.assertEqual(done.returncode, code, done.stderr)
                path = self.row(done)["paths"][0]
                if state == "open":
                    self.assertEqual(path["forge"], [{"reason": "declared", "issue": 130}])
                else:
                    self.assertEqual(path["class"], "unmapped")

    def test_a_root_without_a_github_origin_reads_no_forge(self):
        f = Fleet(self)
        f.worktree("any")
        self.home = fake_forge_home(self, report(), {})
        done = subprocess.run([str(ROOT / CHECK), "--repo-root", str(f.root)], cwd=ROOT,
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, **GIT_ENV, "HOME": self.home})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["class"], "unmapped")
        self.assertEqual(self.gh_calls(), [])

    def test_a_declared_issue_that_is_a_pull_request_maps_nothing(self):
        f = Fleet(self)
        f.worktree("cutover-130-candidate")
        done = self.run_check(f, {
            "repos/fagenorn/nix-config/issues?labels=in-progress&state=open&per_page=100": [[]],
            "repos/fagenorn/nix-config/pulls?state=open&per_page=100": [[]],
            "repos/fagenorn/nix-config/issues/130": {"number": 130, "state": "open",
                                                    "pull_request": {}}},
            slug="fagenorn/nix-config")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.row(done)["paths"][0]["class"], "unmapped")

    def test_an_unclaimed_stale_worktree_stays_red(self):
        f = Fleet(self)
        f.worktree("stale")
        released = ("<!-- agent:claim v1 issue=12 holder=h/s branch=stale renewed=1 released=done -->"
                    "\nClaimed.")
        untrusted = "<!-- agent:claim v1 issue=13 holder=h/s branch=stale renewed=1 -->\nClaimed."
        done = self.run_check(f, {
            ISSUES: [[{"number": 12}, {"number": 13}]],
            "repos/o/r/issues/12/comments?per_page=100": [[comment(55, released)]],
            "repos/o/r/issues/13/comments?per_page=100": [[comment(56, untrusted, "NONE")]],
            PULLS: [[pull(8, "stale", repo="fork/r"), pull(7, "stale", repo=None)]]})
        self.assertEqual(done.returncode, 1, done.stderr)
        got = self.row(done)
        self.assertEqual((got["verdict"], got["paths"][0]["class"]), ("red", "unmapped"))
        done = subprocess.run([str(ROOT / CHECK), "--red-pending", "--repo-root", str(f.root)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={**os.environ, **GIT_ENV, "HOME": self.home})
        self.assertEqual(done.returncode, 75, done.stderr)

    def test_a_forge_failure_is_exit_2(self):
        f = Fleet(self)
        f.worktree("any")
        done = self.run_check(f, {})
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("verify-checks: forge_error:", done.stderr)

    def test_a_malformed_forge_payload_is_exit_2(self):
        bad_pull = {"number": "8", "updated_at": "t", "head": {"ref": "any", "repo": None}}
        no_repo_name = {"number": 8, "updated_at": "t", "head": {"ref": "any", "repo": {}},
                        "base": {"repo": {"full_name": "o/r"}}}
        head = {"ref": "any", "repo": {"full_name": "o/r"}}
        no_base = {"number": 8, "updated_at": "t", "head": head}
        omitted_head_repo = {"number": 8, "updated_at": "t", "head": {"ref": "any"},
                             "base": {"repo": {"full_name": "o/r"}}}
        null_base_repo = {"number": 8, "updated_at": "t", "head": head, "base": {"repo": None}}
        no_base_name = {"number": 8, "updated_at": "t", "head": head, "base": {"repo": {}}}
        cases = {
            "issue number": ({ISSUES: [[{"number": "12"}]], PULLS: [[]]}, "o/r"),
            "pull number": ({ISSUES: [[]], PULLS: [[bad_pull]]}, "o/r"),
            "pull repo name": ({ISSUES: [[]], PULLS: [[no_repo_name]]}, "o/r"),
            "pull head repo omitted": ({ISSUES: [[]], PULLS: [[omitted_head_repo]]}, "o/r"),
            "pull base": ({ISSUES: [[]], PULLS: [[no_base]]}, "o/r"),
            "pull base repo": ({ISSUES: [[]], PULLS: [[null_base_repo]]}, "o/r"),
            "pull base repo name": ({ISSUES: [[]], PULLS: [[no_base_name]]}, "o/r"),
            "pull page": ({ISSUES: [[]], PULLS: [{"number": 8}]}, "o/r"),
            "declared document": ({
                "repos/fagenorn/nix-config/issues?labels=in-progress&state=open&per_page=100": [[]],
                "repos/fagenorn/nix-config/pulls?state=open&per_page=100": [[]],
                "repos/fagenorn/nix-config/issues/130": [{"state": "open"}]}, "fagenorn/nix-config"),
        }
        for name, (responses, slug) in cases.items():
            with self.subTest(case=name):
                f = Fleet(self)
                f.worktree("cutover-130-candidate" if slug != "o/r" else "any")
                done = self.run_check(f, responses, slug=slug)
                self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
                self.assertIn("verify-checks: forge_error:", done.stderr)

    def test_the_declared_branch_is_the_cutover_candidate(self):
        from agent_tools import verify_checks, worktree_forge
        self.assertEqual(worktree_forge.DECLARED_BRANCHES,
                         {"fagenorn/nix-config": {verify_checks.CANDIDATE_BRANCH: 130}})


if __name__ == "__main__":
    unittest.main()
