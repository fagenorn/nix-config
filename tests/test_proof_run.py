"""The `proof-run` command of `agent_tools.delivery.proof_run`.

Runs the real engine, as a child process, on the stubbed fixture project of
`tests/engine_stubbed_world.py` for the proving cases, and answers the forge from a recording fake
tracker or from patched `forge_api` reads for the adapter cases. The checks of the reset, the
attempt and proven records, the lock and the command line are pinned against what the run leaves.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import bound_issues, cleanup_issue, proof_run
from agent_tools.system import forge_api
from tests.engine_fixture import AdoptedFixtures
from tests.engine_stubbed_world import IMPLEMENTED, StubbedRun
from tests.guard_policy_world import REAL_GIT, REPO_ROOT, install_platform_manifest_in_environ

TIER = "integration"  # builds the fixture project and runs the engine as a child process

FIXTURES = AdoptedFixtures()
ENGINE = [sys.executable, "-m", "agent_tools.delivery.engine"]
SHA_A = "a" * 40
SHA_B = "b" * 40
EARLIER = {"proof-runs.log": "issue 7\n", "test_proof_runs.py": "# an earlier run's test\n"}
LOGGED = "issue 7\nissue 41\n"
OVER_THE_RULE = "Add greet().\n\n## Acceptance criteria\n\n" + "".join(f"- [ ] c{i}\n" for i in range(4))
FLAGS = ["--platform-repo", "o/n", "--branch", "main", "--fixture", "example/fixture",
         "--fixture-branch", "main"]


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


class FakeFixture:
    """A `FixtureTracker` that records every call and answers from its constructor."""

    def __init__(self, *, open_issues=(), pulls=(), created: int = 1, on_pulls=None) -> None:
        self.open_issues = list(open_issues)
        self.pulls = list(pulls)
        self.created = created
        self.on_pulls = on_pulls
        self.calls: list[tuple[str, tuple]] = []

    def open_proof_issues(self) -> list[int]:
        self.calls.append(("open_proof_issues", ()))
        return list(self.open_issues)

    def pulls_closing(self, issues) -> list[int]:
        self.calls.append(("pulls_closing", (tuple(issues),)))
        if self.on_pulls is not None:
            self.on_pulls()
        return list(self.pulls)

    def closed_by_merged_pull(self, issue: int) -> bool:
        self.calls.append(("closed_by_merged_pull", (issue,)))
        return False

    def close_pull(self, number: int) -> None:
        self.calls.append(("close_pull", (number,)))

    def close_issue(self, number: int) -> None:
        self.calls.append(("close_issue", (number,)))

    def create(self, title: str, body: str) -> int:
        self.calls.append(("create", (title, body)))
        return self.created


def records_of(run: StubbedRun) -> dict[str, Path]:
    state = run.world.home / ".agents/state/engine"
    return {"proven": state / "proven.jsonl", "attempts": state / "proof-runs.jsonl",
            "lock": state / "proof-run.lock"}


def proves(run: StubbedRun, fake, revision: str, mode: str, engine=ENGINE, env=None, tip=None,
           root=None):
    return proof_run.prove(tip or (lambda: revision), mode=mode,
                           root=root or (lambda: run.fixture.root),
                           slug=run.fixture.slug, branch="main", tracker=fake,
                           engine=lambda _revision: engine, env=run.env if env is None else env,
                           **records_of(run))


def another_checkout(run: StubbedRun) -> Path:
    """A second checkout of the fixture's repository on main, holding a local commit and a stray file."""
    other = run.world.tmp / "other-checkout"
    subprocess.run([REAL_GIT, "clone", "--quiet", run.bare, str(other)], check=True)
    run.world.git(other, "commit", "--quiet", "--allow-empty", "-m", "work not on origin")
    (other / "stray.txt").write_text("keep me", "utf-8")
    return other


def lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def read(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def seed_proven(run: StubbedRun, revision: str) -> None:
    path = records_of(run)["proven"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": 1, "issue": 3, "project": run.fixture.slug,
                                "proven": "2026-01-01T00:00:00Z", "revision": revision,
                                "run": "r"}) + "\n", "utf-8")


def stubbed(test: unittest.TestCase, **members) -> StubbedRun:
    return StubbedRun(test, fixtures=FIXTURES, title=members.pop("title", proof_run.TITLE),
                      body=members.pop("body", proof_run.BODY), **members)


class ProveTest(unittest.TestCase):
    def test_a_run_ending_done_merges_the_logged_line_and_records_the_revision_as_proven(self):
        reply = {**IMPLEMENTED, "commit": {"path": "proof-runs.log", "text": LOGGED}}
        run = stubbed(self, replies={"implement": reply}, extra_files=EARLIER)
        fake = FakeFixture(created=run.issue)
        seed_proven(run, SHA_A)

        outcome = proves(run, fake, SHA_B, "daily")

        self.assertEqual((outcome.action, outcome.end, outcome.issue, outcome.run, outcome.code),
                         ("proven", "done", run.issue, run.runs()[0].name, 0), outcome)
        self.assertEqual(proof_run.latest_proven(records_of(run)["proven"]), SHA_B)
        proven = lines(records_of(run)["proven"])[-1]
        self.assertEqual(sorted(proven), ["format", "issue", "project", "proven", "revision", "run"])
        self.assertEqual((proven["format"], proven["issue"], proven["project"], proven["revision"],
                          proven["run"]), (1, run.issue, run.fixture.slug, SHA_B, run.runs()[0].name))
        merged = [REAL_GIT, "-C", run.bare, "show"]
        self.assertEqual(subprocess.run([*merged, "main:proof-runs.log"], capture_output=True,
                                        text=True, check=True).stdout, LOGGED)
        self.assertEqual(subprocess.run([*merged, "main:test_proof_runs.py"], capture_output=True,
                                        text=True, check=True).stdout, EARLIER["test_proof_runs.py"])
        started, ended = lines(records_of(run)["attempts"])
        self.assertEqual((started["event"], started["mode"], started["project"], started["revision"]),
                         ("started", "daily", run.fixture.slug, SHA_B))
        self.assertNotIn("issue", started)
        self.assertEqual((ended["event"], ended["attempt"], ended["code"], ended["end"], ended["run"],
                          ended["issue"]),
                         ("ended", started["attempt"], 0, "done", run.runs()[0].name, 41))
        self.assertEqual(fake.calls[-1], ("create", (proof_run.TITLE, proof_run.BODY)))

    def test_an_unmoved_main_starts_no_run(self):
        run = stubbed(self)
        fake = FakeFixture(created=run.issue)
        seed_proven(run, SHA_A)
        before = {name: read(path) for name, path in records_of(run).items() if name != "lock"}

        outcome = proves(run, fake, SHA_A, "daily")

        self.assertEqual(outcome.action, "unmoved")
        self.assertEqual(fake.calls, [])
        self.assertEqual((run.runs(), run.launches()), ([], []))
        self.assertEqual({name: read(path) for name, path in records_of(run).items()
                          if name != "lock"}, before)

    def test_a_run_ending_in_a_stop_records_nothing(self):
        run = stubbed(self, body=OVER_THE_RULE)
        fake = FakeFixture(created=run.issue)
        seed_proven(run, SHA_A)
        before = read(records_of(run)["proven"])

        outcome = proves(run, fake, SHA_B, "daily")

        self.assertEqual((outcome.action, outcome.code, outcome.end),
                         ("unproven", 3, "standard-not-on-engine"))
        self.assertEqual(read(records_of(run)["proven"]), before)
        self.assertEqual(lines(records_of(run)["attempts"])[-1]["code"], 3)

    def test_an_engine_fault_records_nothing(self):
        run = stubbed(self)
        fake = FakeFixture(created=run.issue)
        seed_proven(run, SHA_A)
        before = read(records_of(run)["proven"])

        outcome = proves(run, fake, SHA_B, "daily",
                         engine=[sys.executable, "-c", "import sys; sys.exit(1)"])

        self.assertEqual((outcome.action, outcome.code, outcome.end), ("unproven", 1, None))
        self.assertEqual(read(records_of(run)["proven"]), before)

    def test_a_second_caller_is_busy_while_the_first_holds_the_operation(self):
        run = stubbed(self)
        inside, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold() -> None:
            inside.set()
            release.wait(60)

        first = FakeFixture(created=run.issue, on_pulls=hold)
        done: list = []
        thread = threading.Thread(target=lambda: done.append(proves(run, first, SHA_B, "daily")))
        thread.start()
        self.addCleanup(thread.join, 600)
        self.assertTrue(inside.wait(60))
        second = FakeFixture(created=run.issue)

        outcome = proves(run, second, SHA_B, "now")

        self.assertEqual(outcome.action, "busy")
        self.assertEqual(second.calls, [])
        self.assertEqual(run.runs(), [])
        release.set()

    def test_the_branch_tip_is_read_only_while_the_operation_is_held(self):
        run = stubbed(self)
        reads = []

        def tip() -> str:
            probe = os.open(records_of(run)["lock"], os.O_RDWR)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                reads.append("held")
            else:
                reads.append("free")
            finally:
                os.close(probe)
            return SHA_A

        seed_proven(run, SHA_A)
        proves(run, FakeFixture(created=run.issue), SHA_A, "daily", tip=tip)

        self.assertEqual(reads, ["held"])

    def test_a_busy_caller_never_reads_the_tip(self):
        run = stubbed(self)
        lock = records_of(run)["lock"]
        lock.parent.mkdir(parents=True, exist_ok=True)
        held = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX)
        reads = []

        outcome = proves(run, FakeFixture(), SHA_A, "now", tip=lambda: reads.append(1) or SHA_A)

        self.assertEqual((outcome.action, outcome.revision, reads), ("busy", None, []))

    def test_a_setup_failure_is_recorded_as_an_ended_attempt(self):
        run = stubbed(self)
        failure = forge_api.ForgeError("gh_failed", "no issue")

        class Failing(FakeFixture):
            def create(self, title: str, body: str) -> int:
                raise failure

        with self.assertRaises(forge_api.ForgeError):
            proves(run, Failing(), SHA_B, "daily")

        started, ended = lines(records_of(run)["attempts"])
        self.assertEqual((started["event"], ended["event"], ended["attempt"]),
                         ("started", "ended", started["attempt"]))
        self.assertEqual((ended["code"], ended["end"], ended["run"], ended["issue"]), (2, None, None, None))
        self.assertIsNone(read(records_of(run)["proven"]))

    def test_a_tip_that_cannot_be_read_is_recorded_as_a_failed_attempt(self):
        run = stubbed(self)
        failure = forge_api.ForgeError("gh_failed", "no tip")

        def tip() -> str:
            raise failure

        fake = FakeFixture()
        with self.assertRaises(forge_api.ForgeError):
            proves(run, fake, SHA_B, "daily", tip=tip)

        started, ended = lines(records_of(run)["attempts"])
        self.assertEqual((started["event"], started["mode"], started["project"], started["revision"]),
                         ("started", "daily", run.fixture.slug, None))
        self.assertEqual((ended["event"], ended["attempt"], ended["code"], ended["end"], ended["run"],
                          ended["issue"]), ("ended", started["attempt"], 2, None, None, None))
        self.assertEqual(fake.calls, [])
        self.assertIsNone(read(records_of(run)["proven"]))

    def test_a_registered_checkout_that_cannot_be_resolved_is_recorded_as_a_failed_attempt(self):
        run = stubbed(self)

        def root() -> Path:
            raise cleanup_issue.Refusal("no registered checkout")

        fake = FakeFixture()
        with self.assertRaises(cleanup_issue.Refusal):
            proves(run, fake, SHA_B, "daily", root=root)

        started, ended = lines(records_of(run)["attempts"])
        self.assertEqual((started["revision"], ended["attempt"], ended["code"], ended["issue"]),
                         (SHA_B, started["attempt"], 2, None))
        self.assertEqual(fake.calls, [])

    def test_inherited_repository_selectors_never_reach_the_engine(self):
        run = stubbed(self)
        other = another_checkout(run)
        seen = run.world.tmp / "engine-env.json"
        probe = ("import json, os; json.dump(sorted(k for k in os.environ if k in "
                 f"('GIT_DIR', 'GIT_WORK_TREE')), open({str(seen)!r}, 'w')); "
                 "print(json.dumps({'end': 'stopped', 'run': 'r'}))")
        env = {**run.env, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}

        proves(run, FakeFixture(created=run.issue), SHA_B, "now", env=env,
               engine=[sys.executable, "-c", probe])

        self.assertEqual(json.loads(seen.read_text("utf-8")), [])


class ResetTest(unittest.TestCase):
    def reset(self, run: StubbedRun, fake) -> int:
        return proof_run.reset_fixture(run.fixture.root, slug=run.fixture.slug, branch="main",
                                       tracker=fake, env=run.env)

    def test_the_reset_closes_leftover_pulls_then_issues_then_files_the_fixed_issue(self):
        run = stubbed(self)
        root, git = run.fixture.root, run.world.git
        (root / "junk.txt").write_text("x", "utf-8")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "not on origin")
        fake = FakeFixture(open_issues=[7], pulls=[9], created=12)

        self.assertEqual(self.reset(run, fake), 12)

        self.assertEqual([name for name, _ in fake.calls],
                         ["open_proof_issues", "pulls_closing", "close_pull", "close_issue", "create"])
        self.assertEqual(git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "origin/main"))
        self.assertFalse((root / "junk.txt").exists())

    def test_inherited_repository_selectors_cannot_aim_the_reset_at_another_checkout(self):
        run = stubbed(self)
        other = another_checkout(run)
        other_head = run.world.git(other, "rev-parse", "HEAD")
        (run.fixture.root / "junk.txt").write_text("x", "utf-8")
        env = {**run.env, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}

        self.assertEqual(proof_run.reset_fixture(run.fixture.root, slug=run.fixture.slug, branch="main",
                                                 tracker=FakeFixture(created=12), env=env), 12)

        self.assertEqual(run.world.git(other, "rev-parse", "HEAD"), other_head)
        self.assertTrue((other / "stray.txt").exists())
        self.assertFalse((run.fixture.root / "junk.txt").exists())

    def test_a_stale_registry_path_is_refused_before_anything_changes(self):
        run = stubbed(self)
        root, git = run.fixture.root, run.world.git
        run.world.identity(root, "git@github.com:o/other.git")
        (root / "junk.txt").write_text("x", "utf-8")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "local")
        head, refs = git(root, "rev-parse", "HEAD"), git(root, "for-each-ref")
        fake = FakeFixture(open_issues=[7], created=12)

        with self.assertRaises(cleanup_issue.Refusal):
            self.reset(run, fake)

        self.assertEqual(fake.calls, [])
        self.assertTrue((root / "junk.txt").exists())
        self.assertEqual((git(root, "rev-parse", "HEAD"), git(root, "for-each-ref")), (head, refs))

    def test_a_checkout_on_another_branch_is_refused_before_anything_changes(self):
        run = stubbed(self)
        root, git = run.fixture.root, run.world.git
        git(root, "checkout", "--quiet", "-b", "topic")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "on topic")
        (root / "junk.txt").write_text("x", "utf-8")
        head = git(root, "rev-parse", "topic")
        fake = FakeFixture(open_issues=[7], created=12)

        with self.assertRaises(cleanup_issue.Refusal):
            self.reset(run, fake)

        self.assertEqual(fake.calls, [])
        self.assertEqual(git(root, "rev-parse", "topic"), head)
        self.assertTrue((root / "junk.txt").exists())


class AdapterTest(unittest.TestCase):
    def test_a_proof_issue_on_a_later_page_is_found(self):
        marked = {"number": 5, "body": f"text\n{proof_run.MARKER}  \n", "author_association": "OWNER"}
        other = {"number": 4, "body": "no marker", "author_association": "OWNER"}
        pages = [[other], [marked]]

        with mock.patch.object(forge_api, "api_pages", return_value=pages):
            self.assertEqual(proof_run.GitHubFixture("o/f").open_proof_issues(), [5])

    def test_a_pull_of_another_repository_naming_the_same_number_is_not_closed(self):
        nodes = [{"number": 9, "state": "OPEN", "repository": {"nameWithOwner": "o/f"}},
                 {"number": 9, "state": "OPEN", "repository": {"nameWithOwner": "x/y"}}]
        answer = {"data": {"repository": {"issue": {"closedByPullRequestsReferences":
                                                    {"nodes": nodes}}}}}

        with mock.patch.object(forge_api, "graphql", return_value=answer) as graphql:
            self.assertEqual(proof_run.GitHubFixture("o/f").pulls_closing([7]), [9])

        query, variables = graphql.call_args.args
        self.assertIn("issue(number: 7)", query)
        self.assertEqual(variables, {"owner": "o", "name": "f"})

    def test_the_first_page_sends_no_cursor_through_gh_and_the_next_sends_the_returned_one(self):
        first = [{"number": n, "state": "CLOSED", "repository": {"nameWithOwner": "o/f"}}
                 for n in range(1, 51)]
        answers = [json.dumps(self.page(first, "c1")), json.dumps(self.page([], None))]
        with mock.patch.object(forge_api, "run_gh", side_effect=[(0, a) for a in answers]) as gh:
            proof_run.GitHubFixture("o/f").pulls_closing([7])

        sent = [[arg for arg in call.args[0] if arg.startswith(("owner=", "name=", "after="))]
                for call in gh.call_args_list]
        self.assertEqual(sent, [["owner=o", "name=f"], ["owner=o", "name=f", "after=c1"]])

    @staticmethod
    def page(nodes: list, cursor: str | None, *, state: str | None = None) -> dict:
        found = {"closedByPullRequestsReferences": {
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": nodes}}
        if state is not None:
            found["state"] = state
        return {"data": {"repository": {"issue": found}}}

    def test_an_open_pull_on_a_later_page_of_closing_pulls_is_found(self):
        first = [{"number": n, "state": "CLOSED", "repository": {"nameWithOwner": "o/f"}}
                 for n in range(1, 51)]
        last = [{"number": 99, "state": "OPEN", "repository": {"nameWithOwner": "o/f"}}]
        answers = [self.page(first, "c1"), self.page(last, None)]

        with mock.patch.object(forge_api, "graphql", side_effect=answers) as graphql:
            self.assertEqual(proof_run.GitHubFixture("o/f").pulls_closing([7]), [99])

        self.assertEqual([call.args[1].get("after") for call in graphql.call_args_list], [None, "c1"])

    def test_the_merged_pull_on_a_later_page_is_found(self):
        first = [{"number": n, "merged": False, "repository": {"nameWithOwner": "o/f"}}
                 for n in range(1, 51)]
        last = [{"number": 99, "merged": True, "repository": {"nameWithOwner": "o/f"}}]
        answers = [self.page(first, "c1", state="CLOSED"), self.page(last, None, state="CLOSED")]

        with mock.patch.object(forge_api, "graphql", side_effect=answers):
            self.assertIs(proof_run.GitHubFixture("o/f").closed_by_merged_pull(7), True)

    def test_a_cursor_that_does_not_advance_is_an_error_not_a_loop(self):
        answer = self.page([], "same")

        with mock.patch.object(forge_api, "graphql", return_value=answer):
            with self.assertRaises(forge_api.ForgeError):
                proof_run.GitHubFixture("o/f").pulls_closing([7])

    def test_a_merged_pull_of_another_repository_does_not_count(self):
        def answer(repository: str) -> dict:
            nodes = [{"number": 9, "merged": True, "repository": {"nameWithOwner": repository}}]
            return {"data": {"repository": {"issue": {
                "state": "CLOSED", "closedByPullRequestsReferences": {"nodes": nodes}}}}}

        fixture = proof_run.GitHubFixture("o/f")
        with mock.patch.object(forge_api, "graphql", return_value=answer("x/y")):
            self.assertIs(fixture.closed_by_merged_pull(7), False)
        with mock.patch.object(forge_api, "graphql", return_value=answer("o/f")):
            self.assertIs(fixture.closed_by_merged_pull(7), True)


class RecordTest(unittest.TestCase):
    def test_the_latest_proven_revision_skips_a_torn_last_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proven.jsonl"
            good = json.dumps({"format": 1, "revision": SHA_A})
            foreign = json.dumps({"format": 2, "revision": SHA_B})
            path.write_text(f"{good}\n{foreign}\n{json.dumps({'format': 1, 'revision': SHA_B})[:30]}",
                            "utf-8")

            self.assertEqual(proof_run.latest_proven(path), SHA_A)

    def test_no_record_is_no_proven_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(proof_run.latest_proven(Path(directory) / "proven.jsonl"))

    def test_the_engine_is_built_at_the_revision(self):
        self.assertEqual(proof_run.engine_argv("o/n", SHA_A),
                         ["nix", "shell", f"github:o/n/{SHA_A}#agent-platform", "--command", "engine"])

    def test_the_main_revision_is_the_branch_tip(self):
        with mock.patch.object(forge_api, "api_get", return_value={"commit": {"sha": SHA_A}}) as get:
            self.assertEqual(proof_run.main_revision("o/n", "main"), SHA_A)
        get.assert_called_once_with("repos/o/n/branches/main")
        with mock.patch.object(forge_api, "api_get", return_value={"commit": {"sha": "x"}}):
            with self.assertRaises(forge_api.ForgeError):
                proof_run.main_revision("o/n", "main")

    def test_the_fixed_issue_carries_the_marker_and_one_criterion(self):
        self.assertTrue(proof_run.BODY.endswith(proof_run.MARKER + "\n"))
        criteria = [line for line in proof_run.BODY.splitlines() if line.startswith("- [ ] [code]")]
        self.assertEqual(len(criteria), 1)
        self.assertIn("test_proof_runs.py", criteria[0])


class CliTest(unittest.TestCase):
    def call(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = proof_run.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_usage_error_exits_2_with_one_stderr_line(self):
        code, out, err = self.call(["daily"])

        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith("proof-run: "), err)

    def test_an_unregistered_fixture_exits_2(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(proof_run, "main_revision", return_value=SHA_B):
            code, out, err = self.call(["now", *FLAGS])

        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_now_runs_where_daily_finds_main_unmoved(self):
        run = stubbed(self)
        seed_proven(run, SHA_A)
        fake = FakeFixture(created=run.issue)
        with mock.patch.dict(os.environ, run.env, clear=True), \
                mock.patch.object(proof_run, "main_revision", return_value=SHA_A), \
                mock.patch.object(cleanup_issue, "registered_root",
                                  return_value=str(run.fixture.root)), \
                mock.patch.object(proof_run, "engine_argv", return_value=ENGINE), \
                mock.patch.object(proof_run, "GitHubFixture", return_value=fake), \
                mock.patch.object(bound_issues, "file_pass", return_value=[]):
            daily = self.call(["daily", *FLAGS])
            self.assertEqual(json.loads(daily[1])["action"], "unmoved")
            self.assertEqual((daily[0], run.runs()), (0, []))

            now = self.call(["now", *FLAGS])

        line = json.loads(now[1])
        self.assertEqual((now[0], line["action"]), (0, "proven"), now)
        self.assertEqual(sorted(line), ["action", "code", "end", "filed", "issue", "revision", "run"])
        self.assertEqual(len(run.runs()), 1)


    def test_daily_runs_the_filing_pass_and_prints_what_it_filed(self):
        unmoved = proof_run.Outcome("unmoved", SHA_A, None, None, None, None)
        filed = [bound_issues.Filed("out-of-bounds", "direct.implement", 101)]
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(proof_run, "main_revision", return_value=SHA_A), \
                mock.patch.object(proof_run, "prove", return_value=unmoved), \
                mock.patch.object(cleanup_issue, "registered_root", return_value=home), \
                mock.patch.object(bound_issues, "file_pass", return_value=filed) as passed:
            daily = self.call(["daily", *FLAGS])
            only = self.call(["file", "--platform-repo", "o/n"])

        line = json.loads(daily[1])
        self.assertEqual((daily[0], line["filed"], line["action"]), (0, [101], "unmoved"))
        self.assertEqual((only[0], json.loads(only[1])), (0, {"filed": [101]}))
        self.assertEqual(passed.call_count, 2)


class ObservedTest(unittest.TestCase):
    FIXTURE = "example/fixture"
    ACTIVATED = "2026-01-01T06:00:00Z"

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        patched = mock.patch.dict(os.environ, {"HOME": home.name})
        patched.start()
        self.addCleanup(patched.stop)
        self.attempts = proof_run.attempts_path()
        self.history = proof_run.engine_housekeeping.history_path()
        self.attempts.parent.mkdir(parents=True)

    def started(self, attempt, *, mode="daily", at="2026-01-01T06:00:00Z", project=None,
                revision=SHA_A):
        self.append(self.attempts, {"format": 1, "attempt": attempt, "event": "started", "mode": mode,
                                    "project": project or self.FIXTURE, "revision": revision, "at": at})

    def ended(self, attempt, *, code=0, end="done", run="root-run", at="2026-01-01T06:30:00Z",
              issue=41):
        self.append(self.attempts, {"format": 1, "attempt": attempt, "event": "ended", "code": code,
                                    "end": end, "run": run, "issue": issue, "at": at})

    def line(self, run, *, issue=41, end="done"):
        self.append(self.history, {"format": 1, "run": run, "project": self.FIXTURE, "issue": issue,
                                   "end": end})

    @staticmethod
    def append(path, line):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")

    def observe(self, merged=True, activated=ACTIVATED):
        out, err = io.StringIO(), io.StringIO()
        flags = [] if activated is None else ["--activated", activated]
        with mock.patch.object(proof_run.GitHubFixture, "closed_by_merged_pull",
                               return_value=merged) as asked, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = proof_run.main(["observed", "--fixture", self.FIXTURE, *flags])
        self.asked = asked
        return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()

    def test_no_daily_attempt_is_not_yet(self):
        self.started("n1", mode="now")
        self.ended("n1")
        self.line("root-run")

        code, line, _ = self.observe()

        self.assertEqual(code, 75)
        self.assertEqual(line["state"], "not_yet")
        self.assertEqual(sorted(line), ["attempt", "end", "issue", "run", "state"])

    def test_a_running_first_attempt_is_not_yet_even_beside_a_done_child_line(self):
        self.started("d1")
        self.line("child-run")

        code, line, _ = self.observe()

        self.assertEqual((code, line["state"], line["attempt"]), (75, "running", "d1"))

    def test_a_failed_first_attempt_is_not_met_whatever_follows(self):
        self.started("d1")
        self.ended("d1", code=3, end="stopped")
        self.started("d2", at="2026-01-02T06:00:00Z")
        self.ended("d2", run="root-2", at="2026-01-02T06:30:00Z", issue=42)
        self.line("root-2", issue=42)

        code, line, _ = self.observe(merged=True)

        self.assertEqual((code, line["state"], line["attempt"]), (1, "not_met", "d1"))

    def test_a_first_attempt_that_took_over_three_days_is_not_met(self):
        self.started("d1")
        self.ended("d1", at="2026-01-04T06:00:01Z")
        self.line("root-run")

        self.assertEqual(self.observe()[0], 1)

    def test_a_first_attempt_that_started_four_days_after_activation_is_not_met_however_short(self):
        self.started("d1", at="2026-01-05T06:00:00Z")
        self.ended("d1", at="2026-01-05T06:05:00Z")
        self.line("root-run")

        code, line, _ = self.observe(merged=True)

        self.assertEqual((code, line["state"]), (1, "not_met"))

    def test_an_attempt_that_ended_before_activation_is_not_the_first_scheduled_one(self):
        self.started("d0", at="2025-12-30T06:00:00Z")
        self.ended("d0", at="2025-12-30T06:30:00Z")
        self.line("root-run")

        code, line, _ = self.observe(merged=True, activated="2026-01-03T00:00:00Z")

        self.assertEqual((code, line["state"], line["attempt"]), (75, "not_yet", None))

    def test_the_first_attempt_is_the_first_one_at_or_after_activation(self):
        self.started("d0", at="2025-12-31T06:00:00Z")
        self.ended("d0", at="2025-12-31T06:30:00Z")
        self.started("d1", at="2026-01-03T00:00:00Z")
        self.ended("d1", code=3, end="stopped", at="2026-01-03T00:30:00Z")

        code, line, _ = self.observe(merged=True, activated="2026-01-03T00:00:00Z")

        self.assertEqual((code, line["state"], line["attempt"]), (1, "not_met", "d1"))

    def test_a_first_attempt_that_failed_before_a_revision_was_known_is_not_met_whatever_follows(self):
        self.started("d1", revision=None)
        self.ended("d1", code=2, end=None, run=None, issue=None)
        self.started("d2", at="2026-01-02T06:00:00Z")
        self.ended("d2", run="root-2", at="2026-01-02T06:30:00Z", issue=42)
        self.line("root-2", issue=42)

        code, line, _ = self.observe(merged=True)

        self.assertEqual((code, line["state"], line["attempt"]), (1, "not_met", "d1"))

    def test_the_observer_needs_a_valid_activation_time(self):
        self.started("d1")
        self.ended("d1")
        self.line("root-run")

        for activated in (None, "yesterday"):
            with self.subTest(activated=activated):
                code, line, err = self.observe(activated=activated)
                self.assertEqual((code, line), (2, None))
                self.assertTrue(err.startswith("proof-run: "), err)

    def test_a_done_attempt_without_its_root_line_is_not_met(self):
        self.started("d1")
        self.ended("d1")
        self.line("child-run")

        self.assertEqual(self.observe()[0], 1)

    def test_a_done_first_attempt_with_a_merged_pull_closing_its_issue_is_met(self):
        self.started("d1")
        self.ended("d1", at="2026-01-04T06:00:00Z")
        self.line("root-run")

        code, line, _ = self.observe(merged=True)

        self.assertEqual((code, line["state"]), (0, "met"))
        self.assertEqual(line, {"attempt": "d1", "end": "done", "issue": 41, "run": "root-run",
                                "state": "met"})
        self.asked.assert_called_once_with(41)

    def test_a_done_first_attempt_without_a_merged_pull_is_not_met(self):
        self.started("d1")
        self.ended("d1")
        self.line("root-run")

        code, line, _ = self.observe(merged=False)

        self.assertEqual((code, line["state"]), (1, "not_met"))

    def test_a_forge_error_exits_2_with_one_stderr_line(self):
        self.started("d1")
        self.ended("d1")
        self.line("root-run")
        failure = forge_api.ForgeError("payload_invalid", "no closing pull requests")
        err = io.StringIO()
        with mock.patch.object(proof_run.GitHubFixture, "closed_by_merged_pull", side_effect=failure), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = proof_run.main(["observed", "--fixture", self.FIXTURE, "--activated", self.ACTIVATED])

        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("proof-run: "), err.getvalue())

    def test_it_writes_nothing(self):
        self.started("d1")
        self.ended("d1")
        self.line("root-run")
        before = [read(path) for path in (self.attempts, self.history)]

        self.observe()

        self.assertEqual([read(path) for path in (self.attempts, self.history)], before)
        self.assertFalse(proof_run.lock_path().exists())

    def test_the_check_script_runs_observed(self):
        script = "home/common/verify-pending/checks/proof-run-green"
        text = (REPO_ROOT / script).read_text("utf-8")
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertTrue(text.endswith(
            'PYTHONPATH=python exec python3 -m agent_tools.delivery.proof_run observed "$@"\n'))
        staged = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-s", script],
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(staged.startswith("100755 "), staged)


class GlossaryTest(unittest.TestCase):
    def test_the_project_contract_glossary_defines_proven_revision(self):
        text = (REPO_ROOT / "docs/areas/project-contract/CONTEXT.md").read_text("utf-8").splitlines()
        at = text.index("**Proven revision**:")
        for needle in ("`main` revision", "fixture project", "`done`"):
            self.assertIn(needle, text[at + 1])
        self.assertIn("| Proven revision | Project contract |",
                      (REPO_ROOT / "docs/CONTEXT-MAP.md").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
