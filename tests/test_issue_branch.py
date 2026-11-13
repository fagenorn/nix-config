"""Contract tests for `issue-branch` (`agent_tools.delivery.issue_branch`, issue 748).

The policy functions are imported; the command runs as `python -m agent_tools.delivery.issue_branch`
against a git copy of the eval fixture project with a bare origin, a temporary HOME holding
the committed platform manifest, and a stub `gh` first on PATH (agent-helpers rule 5).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import issue_branch

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
SLUG = "fixture/tinytask"
TWENTY_WORDS = ("Chat and invoke agent run events may never be emitted in production "
                "because the telemetry source name does not match")
SHORT = "chat-and-invoke-agent-run-events"
LONG_SLUG = "-".join(TWENTY_WORDS.lower().split())
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
FAKE_GH = '''import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
argv = sys.argv[1:]
issues = "repos/%s/issues/" % state["slug"]
pulls = "repos/%s/pulls?" % state["slug"]
if len(argv) == 2 and argv[0] == "api" and argv[1].startswith(issues):
    print(json.dumps({"number": int(argv[1][len(issues):]), "title": state["title"]}))
elif argv[:3] == ["api", "--paginate", "--slurp"] and len(argv) == 4 and argv[3].startswith(pulls):
    print(json.dumps([state["pulls"]]))
else:
    sys.stderr.write("gh: Not Found (HTTP 404): unexpected call %r\\n" % (argv,))
    sys.exit(1)
'''


def pull(number, branch):
    """One open same-repository pull request as the REST listing returns it."""
    return {"number": number, "updated_at": "2026-11-01T00:00:00Z",
            "head": {"ref": branch, "repo": {"full_name": SLUG}},
            "base": {"repo": {"full_name": SLUG}}}


PROGRAMS = REPO_ROOT / "home/common/claude-code/skills/deliver-standard"
HARNESSES = REPO_ROOT / "home/common/agent-skills/tests"
# The command a program prompt orders: "exactly <argv>" up to the colon or the " and return" that ends it.
SENT_COMMAND = re.compile(r"\bexactly (issue-branch[^\n]*?)(?::\s| and return)")


def sent_argv(text):
    """The complete argv (program name included) the prompt `text` orders its agent to run."""
    found = SENT_COMMAND.findall(text)
    if len(found) != 1:
        raise AssertionError(f"expected one issue-branch command in the prompt, found {found}")
    return shlex.split(found[0])


def program_prompt(program, harness, args, label):
    """The last prompt labelled `label` that `program` sends under its stub-agent harness."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the program scenarios need it")
    scenario = {"args": args, "replies": {}, "patch": {}, "children": {}}
    done = subprocess.run([node, str(HARNESSES / harness), str(PROGRAMS / program)],
                          input=json.dumps(scenario), capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(f"harness failed: {done.stderr}")
    found = [c["prompt"] for c in json.loads(done.stdout)["calls"]
             if c["label"] == label and c.get("kind", "agent") == "agent"]
    if not found:
        raise AssertionError(f"{program} sent no {label} prompt")
    return found[-1]


class TitleSlugTest(unittest.TestCase):
    def test_a_twenty_word_title_keeps_six_words_within_forty_characters(self):
        self.assertEqual(len(TWENTY_WORDS.split()), 20)
        slug = issue_branch.title_slug(TWENTY_WORDS)
        self.assertEqual(slug, SHORT)
        self.assertLessEqual(len(slug), 40)

    def test_the_slug_is_cut_at_a_word_boundary(self):
        word = "Pneumonoultramicroscopicsilicovolcanoconiosisxyz"
        cases = {
            "Reconciliation orchestrator misclassifies a b": "reconciliation-orchestrator",
            f"{word} is long": word.lower()[:40],
            "Fix: the `cd <path> &&` habit (issue 12)!": "fix-the-cd-path-habit-issue",
            "Café über naïve": "cafe-uber-naive",
            "!!! ---": "untitled",
        }
        for title, want in cases.items():
            with self.subTest(title=title):
                got = issue_branch.title_slug(title)
                self.assertEqual(got, want)
                self.assertLessEqual(len(got), 40)


class SelectTest(unittest.TestCase):
    def pick(self, pattern, refs, pulls=None, issue=9, excluded=("main",)):
        derived = issue_branch.render(pattern, issue, SHORT)
        return issue_branch.select(derived, refs, pulls or {}, issue_branch.matcher(pattern, issue), excluded)

    def test_an_earlier_long_slug_branch_of_the_issue_is_adopted(self):
        refs = {"main": 300, "issue-9-" + LONG_SLUG: 100, "issue-94-other": 200, "issue-9": 250}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs), "issue-9-" + LONG_SLUG)

    def test_the_derived_branch_outranks_an_open_pr_and_a_newer_branch(self):
        derived = "issue-9-" + SHORT
        refs = {derived: 100, "issue-9-old": 200, "issue-9-older": 50}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs, {"issue-9-older": 4}), derived)

    def test_the_lowest_open_pr_outranks_a_newer_branch(self):
        refs = {"issue-9-newer": 200, "issue-9-older": 50, "issue-9-oldest": 10}
        pulls = {"issue-9-older": 7, "issue-9-oldest": 5, "issue-8-x": 1}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs, pulls), "issue-9-oldest")

    def test_equal_dates_pick_the_smallest_name(self):
        self.assertEqual(self.pick("issue-<num>-<slug>", {"issue-9-b": 5, "issue-9-a": 5}), "issue-9-a")

    def test_with_no_candidate_the_derived_branch_is_new(self):
        self.assertEqual(self.pick("issue-<num>-<slug>", {"main": 900, "issue-94-x": 800}), "issue-9-" + SHORT)

    def test_a_slug_first_pattern_adopts_only_branches_of_its_issue(self):
        refs = {"main": 900, "other-12": 800, "x-19": 700, "fix-x-9": 100}
        self.assertEqual(self.pick("<slug>-<num>", refs), "fix-x-9")
        self.assertEqual(self.pick("<slug>-<num>", {"main": 900, "other-12": 800}), f"{SHORT}-9")

    def test_a_pattern_without_the_issue_number_adopts_no_other_branch(self):
        self.assertIsNone(issue_branch.matcher("feat/<slug>", 9))
        self.assertEqual(self.pick("feat/<slug>", {"main": 900, "feat/other": 800}), f"feat/{SHORT}")

    def test_an_adjacent_number_and_slug_adopt_no_other_branch(self):
        self.assertIsNone(issue_branch.matcher("fix-<slug><num>", 4))
        self.assertEqual(self.pick("fix-<slug><num>", {"fix-abc14": 9}, issue=4), f"fix-{SHORT}4")

    def test_the_integration_and_default_branches_are_never_adopted(self):
        refs = {"release-9": 900, "trunk-9": 800, "HEAD": 950}
        self.assertEqual(self.pick("<slug>-<num>", refs, excluded=("release-9", "trunk-9")), f"{SHORT}-9")


FAKE_GIT = '''import os, sys
argv = sys.argv[1:]
left = os.environ.get("FAKE_GIT_FETCH_FAILURES")
if left and "fetch" in argv:
    count = int(open(left).read())
    if count > 0:
        open(left, "w").write(str(count - 1))
        sys.stderr.write(os.environ["FAKE_GIT_FETCH_STDERR"])
        sys.exit(128)
os.execv(os.environ["REAL_GIT"], ["git", *argv])
'''
UNREACHABLE = ("ssh: connect to host ssh.github.com port 443: Network is unreachable\n"
               "fatal: Could not read from remote repository.\n")


class IssueBranchCase(unittest.TestCase):
    """A git copy of the fixture project with a bare origin, a manifest HOME and a stub gh."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.home = base / "home"
        (self.home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents" / "share" / "platform-manifest.json")
        self.bin = base / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
        gh.chmod(0o755)
        self.state = base / "gh-state.json"
        self.set_forge(TWENTY_WORDS, [])
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root)
        self.edit_contract(lambda c: c["bindings"]["tracker"].update({"kind": "github", "repo_slug": SLUG}))
        self.origin = base / "origin.git"
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "init", "-q", "-b", "main")
        self.git(self.root, "remote", "add", "origin", str(self.origin))
        self.commit("main", "2026-01-01T00:00:00Z")

    def set_forge(self, title, pulls, slug=SLUG):
        self.state.write_text(json.dumps({"slug": slug, "title": title, "pulls": pulls}), encoding="utf-8")

    def edit_contract(self, change):
        path = self.root / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        change(contract)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, cwd, *args, env=None):
        done = subprocess.run([*GIT, "-C", str(cwd), *args], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(self.home), **(env or {})}, check=False)
        if done.returncode != 0:
            raise AssertionError(f"git {args} failed: {done.stderr}")
        return done.stdout

    def commit(self, branch, date, *, local=False, remote=True):
        """One commit on `branch` (made from main) at `date`; origin fetches it when `remote`,
        and the local branch stays only when `local`."""
        dated = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
        if branch != "main":
            self.git(self.root, "checkout", "-q", "-b", branch, "main")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", branch, env=dated)
        if remote:
            self.git(self.origin, "fetch", "-q", str(self.root), f"{branch}:{branch}")
        if branch != "main":
            self.git(self.root, "checkout", "-q", "main")
            if not local:
                self.git(self.root, "update-ref", "-d", f"refs/heads/{branch}")

    def issue_branch(self, issue=9, argv=None, env=None):
        """Run the command; `argv` (a program's sent argv) replaces the default one, with only the
        launcher and the --repo-root value swapped for this fixture."""
        args = ["--repo-root", str(self.root), "--issue", str(issue)] if argv is None else self.fixture_args(argv)
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.issue_branch", *args],
            capture_output=True, text=True, timeout=120, cwd=str(self.home),
            env={**os.environ, "HOME": str(self.home), "FAKE_GH_STATE": str(self.state),
                 "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", **(env or {})})
        return proc.returncode, proc.stdout, proc.stderr

    def fail_fetches(self, count, stderr=UNREACHABLE):
        """The next `count` `git fetch` runs of the command fail with `stderr`; returns the env to run under."""
        git = self.bin / "git"
        git.write_text(f"#!{sys.executable}\n{FAKE_GIT}", encoding="utf-8")
        git.chmod(0o755)
        left = self.bin.parent / "fetch-failures"
        left.write_text(str(count), encoding="utf-8")
        return {"REAL_GIT": shutil.which("git"), "FAKE_GIT_FETCH_FAILURES": str(left),
                "FAKE_GIT_FETCH_STDERR": stderr}

    def fixture_args(self, argv):
        """`argv` without its program name, the value after --repo-root pointing at the fixture project."""
        args = list(argv[1:])
        if "--repo-root" in args[:-1]:
            args[args.index("--repo-root") + 1] = str(self.root)
        return args

    def derived(self, issue=9, argv=None):
        code, out, err = self.issue_branch(issue, argv)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out.count("\n"), 1)
        return json.loads(out)

    def refused(self, exit_code):
        code, out, err = self.issue_branch()
        self.assertEqual((code, out), (exit_code, ""), err)
        return json.loads(err)["error"]["code"]


class IssueBranchCommandTest(IssueBranchCase):
    def test_a_fresh_run_readopts_an_existing_long_slug_branch(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z")
        self.assertEqual(self.derived(), {
            "adopted": True, "branch": long, "derived": "issue-9-" + SHORT,
            "worktree_path": str(self.root / ".worktrees" / f"worktree-{long}")})

    def test_a_local_only_branch_is_readopted_too(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z", local=True, remote=False)
        self.assertEqual(self.derived()["branch"], long)

    def test_an_open_pr_head_outranks_a_newer_branch_of_the_issue(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z")
        self.commit("issue-9-newer", "2026-03-01T00:00:00Z")
        self.set_forge(TWENTY_WORDS, [pull(41, long)])
        self.assertEqual(self.derived()["branch"], long)

    def test_with_no_earlier_branch_the_short_branch_is_derived(self):
        self.commit("issue-94-other", "2026-03-01T00:00:00Z")
        out = self.derived()
        self.assertEqual((out["branch"], out["adopted"]), ("issue-9-" + SHORT, False))
        self.assertEqual(out["worktree_path"], str(self.root / ".worktrees" / f"worktree-issue-9-{SHORT}"))

    def test_a_slug_first_pattern_never_adopts_the_newest_branch(self):
        self.edit_contract(lambda c: c["bindings"]["vcs"].update({"branch_pattern": "<slug>-<num>"}))
        self.commit("main", "2026-04-01T00:00:00Z")
        self.commit("other-12", "2026-03-01T00:00:00Z")
        self.assertEqual(self.derived()["branch"], f"{SHORT}-9")

    def test_a_tracker_other_than_github_is_refused(self):
        self.edit_contract(lambda c: c["bindings"]["tracker"].update({"kind": "none"}))
        self.assertEqual(self.refused(2), "tracker_unsupported")

    def test_a_project_without_a_contract_is_resolver_refused(self):
        (self.root / ".agents" / "project.json").unlink()
        self.assertEqual(self.refused(2), "resolver_refused")

    def test_a_forge_failure_exits_one(self):
        self.set_forge(TWENTY_WORDS, [], slug="someone/else")
        self.assertEqual(self.refused(1), "forge_failed")


class FetchRetryTest(IssueBranchCase):
    """Issue 999: a network failure of the fetch is retried once, then reported transient."""

    def failed(self, env):
        code, out, err = self.issue_branch(env=env)
        self.assertEqual((code, out), (1, ""), err)
        return json.loads(err)["error"]

    def left(self, env):
        return int(Path(env["FAKE_GIT_FETCH_FAILURES"]).read_text(encoding="utf-8"))

    def test_a_fetch_that_fails_once_on_the_network_then_succeeds_derives_the_branch(self):
        env = self.fail_fetches(1)
        code, out, err = self.issue_branch(env=env)
        self.assertEqual((code, err), (0, ""), err)
        self.assertEqual(json.loads(out)["branch"], "issue-9-" + SHORT)
        self.assertEqual(self.left(env), 0)

    def test_two_network_failures_exit_one_marked_transient(self):
        env = self.fail_fetches(5)
        self.assertEqual(self.failed(env), {"code": "git_failed", "detail": UNREACHABLE.strip(), "transient": True})
        self.assertEqual(self.left(env), 3, "the fetch ran exactly twice")

    def test_a_failure_that_is_not_the_network_is_neither_retried_nor_transient(self):
        stderr = "fatal: 'origin' does not appear to be a git repository\n"
        env = self.fail_fetches(5, stderr)
        self.assertEqual(self.failed(env), {"code": "git_failed", "detail": stderr.strip()})
        self.assertEqual(self.left(env), 4, "the fetch ran once")

    def test_every_network_failure_git_and_ssh_report_is_recognised(self):
        for text in ("ssh: connect to host ssh.github.com port 443: Network is unreachable",
                     "ssh: connect to host github.com port 22: Connection timed out",
                     "fatal: unable to access 'https://x/': Recv failure: Connection reset by peer",
                     "kex_exchange_identification: read: Connection reset by peer",
                     "fatal: unable to access 'https://x/': Could not resolve host: github.com",
                     "ssh: Could not resolve hostname github.com: Temporary failure in name resolution",
                     "fatal: early EOF",
                     "fatal: the remote end hung up unexpectedly"):
            with self.subTest(text=text):
                self.assertTrue(issue_branch.network_failure(text))
        for text in ("fatal: 'origin' does not appear to be a git repository",
                     "fatal: couldn't find remote ref main", "Permission denied (publickey).", "timeout", ""):
            with self.subTest(text=text):
                self.assertFalse(issue_branch.network_failure(text))


class ProgramsDeriveAlikeTest(IssueBranchCase):
    """#748 AC1: both programs run issue-branch for the issue, so a 20-word title gives one short branch."""

    def test_a_twenty_word_title_derives_one_short_branch_in_both_programs(self):
        prompts = {
            "deliver-standard": program_prompt("deliver-standard.js", "deliver_standard_harness.mjs",
                                               {"repo_root": "/r", "issue": 1, "session_id": "s1"}, "setup"),
            "deliver-batch": program_prompt("deliver-batch.js", "deliver_batch_harness.mjs",
                                            {"repo_root": "/r", "batch_id": "b1",
                                             "child_script": "/s/deliver-standard.js", "issues": [1]}, "facts-1"),
        }
        outputs = {}
        for name, text in prompts.items():
            argv = sent_argv(text)
            self.assertEqual(argv, ["issue-branch", "--repo-root", "/r", "--issue", "1"], name)
            outputs[name] = self.derived(argv=argv)
        self.assertEqual(outputs["deliver-standard"], outputs["deliver-batch"])
        self.assertEqual(outputs["deliver-standard"]["branch"], "issue-1-" + SHORT)
        self.assertLessEqual(len(outputs["deliver-standard"]["branch"].removeprefix("issue-1-")), 40)


class SentArgvTest(unittest.TestCase):
    def test_every_sent_argument_is_kept(self):
        cases = {
            "run alone and exactly issue-branch --repo-root /r --issue 1: it prints": ["--repo-root", "/r", "--issue", "1"],
            "alone and exactly issue-branch --repo-root /r --issue 1 --issue 2 and return it":
                ["--repo-root", "/r", "--issue", "1", "--issue", "2"],
            "exactly issue-branch --repo-root /r --issue 1 --unsupported and return it":
                ["--repo-root", "/r", "--issue", "1", "--unsupported"],
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sent_argv(text), ["issue-branch", *want])


if __name__ == "__main__":
    unittest.main()
