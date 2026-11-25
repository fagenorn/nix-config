"""`agent_tools.verification.verify_checks`: the committed verify checks of issue 638."""
import contextlib
import dataclasses
import http.server
import io
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log
from agent_tools.console import manager as console_manager
from agent_tools.console import sprints as console_sprints
from agent_tools.console import view as console_view
from agent_tools.console.sprints import Manager, SprintState
from agent_tools.console.view import ProjectState
from agent_tools.claims import forge_markers
from agent_tools.verification import verify_checks
from agent_tools.system import forge_api

from . import console_test_support as support

ROOT = Path(__file__).resolve().parents[1]
CHECKS = "home/common/verify-pending/checks"


def run_from_root(argv, env_extra=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **(env_extra or {})}
    return subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def committed_mode(path):
    return subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", path],
                          capture_output=True, text=True, check=True).stdout.split(" ")[0]


KEPT_CHECKS = ("console-failed-start", "console-manager-merge", "console-notice-lists",
               "devenv-shell", "host-mentions", "host-prompts", "owner-services")
DELETED_CHECKS = ("required-checks", "managed-pre-push-hook", "cutover-manifest",
                  "cutover-preflight", "self-hosted-runner", "deprecations-retired",
                  "guard-policy-fleet", "registry-agreement", "darwin-shell-path",
                  "railway-project-read", "console-state", "console-no-card",
                  "console-first-screen", "issue-closed", "suite-regressions",
                  "suite-wall-time", "fleet-preflight")


class VerifyChecksSubcommandsTest(unittest.TestCase):
    def test_the_parser_offers_only_the_kept_checks(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit) as raised:
            verify_checks.main(["--help"])
        choices = re.search(r"\{([a-z0-9,-]+)\}", buffer.getvalue()).group(1).split(",")
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(sorted(choices), sorted(KEPT_CHECKS))

    def test_a_deleted_check_is_refused(self):
        for name in DELETED_CHECKS:
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                verify_checks.main([name, "--help"])
            self.assertEqual(raised.exception.code, 2)


def forge(gets, pages):
    """Patch both forge reads; any read not listed fails the test."""
    def api_get(path, allow=()):
        if path not in gets:
            raise AssertionError(f"unexpected read {path}")
        return gets[path]

    def api_pages(path):
        if path not in pages:
            raise AssertionError(f"unexpected paginated read {path}")
        return pages[path]
    return (mock.patch.object(forge_api, "api_get", side_effect=api_get),
            mock.patch.object(forge_api, "api_pages", side_effect=api_pages))


class SuiteWorld:
    """A forge for the suite checks: before runs 1..N, the merge run 100 and after runs 100..119."""
    REPO, WORKFLOW, JOB, BRANCH = "fagenorn/nix-config", "ci.yaml", "Agent Workflow Tests", "main"
    MERGE = "c" * 40
    STAMP = "2026-11-18T00:00:00Z"
    LISTING = "repos/fagenorn/nix-config/actions/workflows/ci.yaml/runs?branch=main&event=push"
    PAGE = 100

    def __init__(self, before=20, after=21, after_base=100):
        self.after_base = after_base
        self.before_ids = list(range(1, before + 1))
        self.after_ids = list(range(after_base, after_base + after))
        self.attempts = {}
        self.jobs = {}
        self.logs = {}

    @staticmethod
    def log(rows=(("tests/a.py", True), ("tests/b.py", True)), summary=None, prefix="\ufeff"):
        stamp = "2026-11-18T00:00:01.1234567Z "
        lines = []
        for member, passed in rows:
            state = "passed" if passed else "failed"
            lines += [f"suite-runner: begin {member}", f"{member} output", "end noise",
                      f"suite-runner: end {member} {state} exit={0 if passed else 1} 1.0s"]
        for member, passed in rows:
            lines.append(f"suite-runner:     1.0s wall     1.0s cpu {'passed' if passed else 'failed'} {member}")
        if summary is None:
            ok = sum(1 for _, passed in rows if passed)
            summary = (len(rows), ok, len(rows) - ok)
        lines.append("suite-runner: summary members=%d passed=%d failed=%d jobs=4 wall=2.0s cpu=2.0s" % summary)
        return prefix + "\n".join(stamp + line for line in lines) + "\n"

    def run(self, run_id, created):
        return {"id": run_id, "created_at": created, "run_attempt": self.attempts.get(run_id, 1)}

    def before_created(self, run_id):
        return (datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(minutes=run_id)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def after_created(self, run_id):
        return (datetime(2026, 11, 18, tzinfo=timezone.utc)
                + timedelta(minutes=run_id - self.after_base)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def set_job(self, run_id, status="completed", conclusion="success", attempt=1):
        self.jobs[(run_id, attempt)] = (status, conclusion)

    def fail(self, run_id, rows=(("tests/a.py", True), ("tests/b.py", False)), attempt=1, log=None):
        self.set_job(run_id, conclusion="failure", attempt=attempt)
        self.logs[1000 * attempt + run_id] = self.log(rows) if log is None else log

    def gets(self):
        gets = {f"{self.LISTING}&head_sha={self.MERGE}&per_page=100":
                {"workflow_runs": [self.run(100, self.STAMP)]},
                }
        for run_id in self.before_ids + self.after_ids:
            for attempt in range(1, self.attempts.get(run_id, 1) + 1):
                status, conclusion = self.jobs.get((run_id, attempt), ("completed", "success"))
                gets[f"repos/{self.REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"] = {
                    "jobs": [{"id": 5, "name": "Nix Eval", "status": "completed", "conclusion": "failure"},
                             {"id": 1000 * attempt + run_id, "name": self.JOB,
                              "status": status, "conclusion": conclusion}]}
        return gets

    def pages(self):
        runs = [self.run(i, self.after_created(i)) for i in reversed(self.after_ids)]
        earlier = [self.run(i, self.before_created(i)) for i in reversed(self.before_ids)]
        return {f"{self.LISTING}&created=>={self.STAMP}&per_page=100":
                [{"total_count": len(runs), "workflow_runs": runs}],
                f"{self.LISTING}&created=<{self.STAMP}&per_page=100":
                [{"total_count": len(earlier), "workflow_runs": earlier[at:at + self.PAGE]}
                 for at in range(0, len(earlier), self.PAGE)]}


class HostMentionsTest(unittest.TestCase):
    PATH = "repos/o/r/issues?state=open&per_page=100"

    def read(self, pages, phrases=("anis-desktop", "Linux host"), gone="anis-desktop is gone", exempt=()):
        def api_pages(path):
            self.assertEqual(path, self.PATH)
            return pages
        with mock.patch.object(forge_api, "api_pages", side_effect=api_pages):
            return verify_checks.host_mentions("o/r", list(phrases), gone, list(exempt))

    def test_an_issue_that_names_the_host_without_the_gone_line_is_an_offender(self):
        pages = [[{"number": 6, "title": "On the Linux host", "body": "anis-desktop is gone: moved to eleven-m5"},
                  {"number": 7, "title": "y", "body": "nothing"}],
                 [{"number": 5, "title": "x", "body": "run it on anis-desktop"},
                  {"number": 8, "title": "pr", "body": "anis-desktop", "pull_request": {}}]]
        self.assertEqual(self.read(pages), (1, {"mentioning": [5, 6], "offenders": [5]}))

    def test_matching_ignores_case_and_honours_the_exemption(self):
        pages = [[{"number": 9, "title": "t", "body": "the LINUX HOST"},
                  {"number": 1291, "title": "t", "body": "anis-desktop"},
                  {"number": 10, "title": "t", "body": "Anis-Desktop Is Gone. anis-desktop"},
                  {"number": 11, "title": "anis-desktop", "body": None}]]
        self.assertEqual(self.read(pages, exempt=[1291]),
                         (1, {"mentioning": [9, 10, 11, 1291], "offenders": [9, 11]}))
        self.assertEqual(self.read([[]]), (0, {"mentioning": [], "offenders": []}))

    def test_an_open_criterion_that_still_names_the_host_is_not_answered_by_a_gone_paragraph(self):
        gone = "anis-desktop is gone: nothing runs there now."
        pages = [[{"number": 5, "title": "t", "body": f"- [ ] [evidence] run it on anis-desktop\n\n{gone}"},
                  {"number": 6, "title": "t", "body": f"- [ ] [evidence] run it on eleven-m5\n- [x] was on the Linux host\n\n{gone}"},
                  {"number": 7, "title": "t", "body": f"Run on the Linux host.\n\n{gone}"},
                  {"number": 8, "title": "t", "body": f"1. [ ] run on the LINUX HOST\n\n{gone}"},
                  {"number": 9, "title": "t", "body": f"- [ ] {gone}"}]]
        self.assertEqual(self.read(pages), (1, {"mentioning": [5, 6, 7, 8, 9], "offenders": [5, 8]}))

    def test_a_malformed_listing_is_a_forge_error(self):
        for pages in (["x"], [["x"]], [[{"number": "5", "body": ""}]], [[{"number": True, "body": ""}]]):
            with self.subTest(pages=pages):
                with self.assertRaises(forge_api.ForgeError) as raised:
                    self.read(pages)
                self.assertEqual(raised.exception.code, "payload_invalid")
        err = io.StringIO()
        with mock.patch.object(forge_api, "api_pages",
                               side_effect=forge_api.ForgeError("transport", "x")):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = verify_checks.main(["host-mentions", "--repo", "o/r", "--phrase", "a", "--gone", "b"])
        self.assertEqual(code, 2)
        self.assertIn("verify-checks: forge_error: transport", err.getvalue())


class HostPromptsTest(unittest.TestCase):
    HOST = "anis-desktop"
    STALE = {"reason": "verify-stale-check", "block": "1.0000000000000000", "check": "0",
             "host": "anis-desktop", "cause": "silent", "last": "never"}

    @staticmethod
    def comment(cid, body, association="OWNER"):
        return {"id": cid, "author_association": association, "body": body,
                "updated_at": "2026-11-06T10:00:00Z"}

    def prompt(self, cid, fields, association="OWNER"):
        return self.comment(cid, forge_markers.render("owner-action", fields, "Asking."), association)

    def end(self, cid, of, association="OWNER"):
        return self.comment(cid, forge_markers.end_body(of, "decision"), association)

    def run_check(self, listings, comments, repos=("o/r",)):
        """`listings` maps a repo to its pages; `comments` maps (repo, issue) to REST comments."""
        self.reads = []

        def api_pages(path):
            for repo, pages in listings.items():
                if path == f"repos/{repo}/issues?state=open&per_page=100":
                    return pages
            raise AssertionError(path)

        def list_comments(slug, issue):
            self.reads.append((slug, issue))
            return comments.get((slug, issue), [])
        with mock.patch.object(forge_api, "api_pages", side_effect=api_pages), \
                mock.patch.object(forge_markers, "list_comments", side_effect=list_comments):
            return verify_checks.host_prompts(list(repos), self.HOST)

    def test_a_live_prompt_naming_the_host_is_reported_whatever_the_labels(self):
        listings = {"o/r": [[{"number": 3, "title": "t", "body": "", "labels": []},
                             {"number": 4, "title": "t", "body": "", "labels": []}]]}
        comments = {("o/r", 3): [self.prompt(30, self.STALE)],
                    ("o/r", 4): [self.prompt(40, {**self.STALE, "host": "eleven-m5"})]}
        self.assertEqual(self.run_check(listings, comments),
                         (1, {"host": self.HOST, "live": [
                             {"repo": "o/r", "issue": 3, "comment": 30, "reason": "verify-stale-check"}]}))

    def test_trust_and_liveness_follow_the_marker_type(self):
        listings = {"o/r": [[{"number": 5}, {"number": 4}, {"number": 3}]]}
        approve = {**self.STALE, "reason": "verify-approve", "host": "mbp+anis-desktop"}
        forge = {"issue": "5", "reason": "decision", "holder": "h", "host": self.HOST}
        comments = {
            ("o/r", 3): [self.prompt(30, self.STALE), self.end(31, 30)],
            ("o/r", 4): [self.prompt(41, approve), self.end(42, 41, "COLLABORATOR"),
                         self.prompt(43, self.STALE, "COLLABORATOR")],
            ("o/r", 5): [self.prompt(50, forge, "COLLABORATOR"), self.prompt(51, forge, "NONE")]}
        code, report = self.run_check(listings, comments)
        self.assertEqual(code, 1)
        self.assertEqual(report["live"], [
            {"repo": "o/r", "issue": 4, "comment": 41, "reason": "verify-approve"},
            {"repo": "o/r", "issue": 5, "comment": 50, "reason": "decision"}])

    def test_every_open_issue_is_read_once_and_none_is_met(self):
        listings = {"o/r": [[{"number": 3}, {"number": 4}], [{"number": 5}]],
                    "o/s": [[]]}
        self.assertEqual(self.run_check(listings, {}, repos=("o/r", "o/s")),
                         (0, {"host": self.HOST, "live": []}))
        self.assertEqual(sorted(self.reads), [("o/r", 3), ("o/r", 4), ("o/r", 5)])

    def test_a_live_prompt_on_an_open_pull_request_is_reported(self):
        listings = {"o/r": [[{"number": 3, "title": "t", "body": "", "pull_request": {}},
                             {"number": 4, "title": "t", "body": ""}]]}
        comments = {("o/r", 3): [self.prompt(30, self.STALE)]}
        self.assertEqual(self.run_check(listings, comments),
                         (1, {"host": self.HOST, "live": [
                             {"repo": "o/r", "issue": 3, "comment": 30, "reason": "verify-stale-check"}]}))
        self.assertEqual(sorted(self.reads), [("o/r", 3), ("o/r", 4)])


class HostCheckWrappersTest(unittest.TestCase):
    def test_the_wrappers_are_committed_executable(self):
        for name in ("host-mentions", "host-prompts"):
            with self.subTest(name=name):
                self.assertEqual(committed_mode(f"{CHECKS}/{name}"), "100755")
                self.assertEqual(run_from_root([str(ROOT / CHECKS / name)]).returncode, 2)


class PlatformStatusWrapperTest(unittest.TestCase):
    def test_runs_the_installed_platform_status_and_passes_it_through(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".agents" / "bin"
            bin_dir.mkdir(parents=True)
            fake = bin_dir / "resolve-project"
            fake.write_text('#!/bin/sh\nprintf \'{"argv": "%s", "platform": {"deprecations": [1]}}\\n\' "$*"\n'
                            "exit 3\n")
            fake.chmod(0o755)
            done = run_from_root([str(ROOT / CHECKS / "platform-status")], {"HOME": home})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(json.loads(done.stdout)["argv"], "platform-status")

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/platform-status"), "100755")


if __name__ == "__main__":
    unittest.main()


class ConsoleStateTest(unittest.TestCase):
    """`console_state` (issue 856): the console's state endpoint answers 200 on loopback."""

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)

    def console(self):
        support.write_registry(self.tmp / "registry.json", [])
        svc = support.service(self, self.tmp / "events.sqlite3", self.tmp / "registry.json")
        return svc.address[1]

    def stub(self, routes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(routes.get(self.path.split("?", 1)[0], 404))
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def closed_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_a_running_console_is_met(self):
        port = self.console()
        self.assertEqual(verify_checks.console_state(port), (0, {"port": port, "status": 200}))

    def test_another_status_on_the_state_endpoint_is_not_met(self):
        port = self.stub({"/": 200, "/api/state": 503})
        self.assertEqual(verify_checks.console_state(port), (1, {"port": port, "status": 503}))

    def test_no_answer_is_not_met_with_the_error(self):
        port = self.closed_port()
        code, report = verify_checks.console_state(port)
        self.assertEqual(code, 1)
        self.assertIsNone(report["status"])
        self.assertTrue(report["error"].startswith("ConnectionRefusedError: "), report["error"])
        self.assertEqual(report["port"], port)


class ConsoleFailedStartTest(unittest.TestCase):
    """`console-failed-start` (issue 1182): an open failed-start card's sprint line reads the failed start."""

    SID = "a" * 16
    T0 = "2026-11-12T10:00:00.000000+00:00"
    REASON = ("Workspace not trusted. Run `claude` in /home/x/p once and accept the trust prompt, "
              "then retry.")

    def real_view(self):
        t0_ms = int(datetime.fromisoformat(self.T0).timestamp() * 1000)
        sprint = dataclasses.replace(
            SprintState(self.SID, "p00", "make the importer resumable", 5, self.T0),
            manager=Manager("failed", self.T0, reason=self.REASON))
        view = console_view.derive_view([ProjectState("p00", "/srv/p00", 1, "t1")],
                                        sprints={self.SID: sprint}, now_ms=t0_ms + 60_000)
        return json.loads(console_view.encode_view(view))

    def stub(self, routes):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = routes.get(self.path.split("?", 1)[0], (404, b""))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def closed_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_no_open_card_is_not_yet(self):
        self.assertEqual(verify_checks.failed_start_state({"inbox": {"open": []}, "entries": []}),
                         (75, {"verdict": "not_yet", "cards": 0}))

    def test_a_card_whose_line_reads_the_failed_start_is_met(self):
        self.assertEqual(verify_checks.failed_start_state(self.real_view()),
                         (0, {"verdict": "met", "cards": 1}))

    def test_a_wrong_line_ball_retry_or_reason_is_not_met(self):
        def sprint_of(view):
            return verify_checks._sprint_entries(view)[0]

        def card_of(view):
            return view["inbox"]["open"][0]

        def drop(view):
            for project in view["entries"]:
                project["sprints"] = []

        cases = (
            ("line", lambda v: sprint_of(v).update(now_text="drafting the brief")),
            ("ball", lambda v: sprint_of(v).update(ball="nobody")),
            ("retry", lambda v: sprint_of(v).update(retry=False)),
            ("reason", lambda v: card_of(v).update(last_reason="Run claude in /home/x/p")),
            ("reason", lambda v: card_of(v).update(last_reason="Workspace not trusted")),
            ("reason", lambda v: card_of(v).update(last_reason="   ")),
            ("reason", lambda v: card_of(v).update(last_reason="")),
            ("reason", lambda v: card_of(v).update(last_reason=None)),
            ("line", drop))
        for index, (problem, mutate) in enumerate(cases):
            with self.subTest(index=index, problem=problem):
                view = self.real_view()
                mutate(view)
                self.assertEqual(verify_checks.failed_start_state(view),
                                 (1, {"verdict": "not_met", "cards": 1, "problems": [problem]}))

    def test_a_card_and_sprint_without_a_string_sprint_id_are_not_met(self):
        def strip(view):
            del view["inbox"]["open"][0]["sprint_id"]
            del verify_checks._sprint_entries(view)[0]["sprint_id"]

        def as_list(view):
            view["inbox"]["open"][0]["sprint_id"] = ["a"]
            verify_checks._sprint_entries(view)[0]["sprint_id"] = ["a"]

        def card_only(view):
            view["inbox"]["open"][0]["sprint_id"] = 7

        for name, mutate in (("both absent", strip), ("list valued", as_list), ("card not a string", card_only)):
            with self.subTest(name):
                view = self.real_view()
                mutate(view)
                self.assertEqual(verify_checks.failed_start_state(view),
                                 (1, {"verdict": "not_met", "cards": 1, "problems": ["line"]}))

    def test_the_wire_names_match_the_console(self):
        self.assertEqual(verify_checks.FAILED_START_REASON, "failed_start")
        self.assertEqual(verify_checks.FAILED_START_NOW, console_sprints.NOW_FAILED_START_TEXT)
        self.assertEqual(verify_checks.FAILED_START_REASONS, console_manager.PLAIN_TEXTS)

    def test_an_unreachable_console_is_not_yet(self):
        unreachable = (75, {"verdict": "unreachable", "cards": 0})
        self.assertEqual(verify_checks.console_failed_start(self.closed_port()), unreachable)
        self.assertEqual(verify_checks.console_failed_start(
            self.stub({"/api/state": (503, b"{}")})), unreachable)
        self.assertEqual(verify_checks.console_failed_start(
            self.stub({"/api/state": (200, b"[]")})), unreachable)

    def test_the_command_and_its_wrapper_print_one_json_line(self):
        port = self.stub({"/api/state": (200, console_view.encode_view(self.real_view()))})
        expected = json.dumps({"verdict": "met", "cards": 1}, sort_keys=True) + "\n"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-failed-start", "--port", str(port)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), expected)
        result = run_from_root([str(ROOT / CHECKS / "console-failed-start"), "--port", str(port)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        for argv in (["console-failed-start"], ["console-failed-start", "--port", "0"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-failed-start"), "100755")


class ConsoleManagerMergeTest(unittest.TestCase):
    """`console-manager-merge` (issue 1377): a manager merged its own pull request after activation."""

    SPRINT = "a" * 16
    OTHER_SPRINT = "b" * 16
    SESSION = "manager-session"
    REPO = "octo/widgets"
    HEAD = "b" * 40
    T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = self.dir / "repo"
        self.root.mkdir()
        self.shas = {}
        self.git("init", "-q")
        for name in ("P", "S", "C"):
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                     "commit", "-q", "--allow-empty", "-m", name)
            self.shas[name] = self.git("rev-parse", "HEAD").strip()
        self.at = self.T0
        self.log_path = self.dir / "events.sqlite3"
        self.log = event_log.EventLog(self.log_path, clock=lambda: self.at.isoformat(timespec="microseconds"))
        self.addCleanup(self.log._connection.close)
        self.pulls = {}
        self.calls = []
        self.reported(self.SPRINT, 1377)

    def reported(self, sprint, *issues):
        self.append("sprint.reported", {"sprint_id": sprint, "goal": "g", "report": {
            "issues": [{"issue": number, "stage": "building"} for number in issues]}}, timedelta(0))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              check=True).stdout

    def append(self, kind, payload, when):
        self.at = self.T0 + when
        self.log.append([(kind, None, payload)])

    def activated(self, commit="C", ok=True, when=timedelta(0)):
        self.append("activation.finished", {"root": "/r", "commit": self.shas[commit], "ok": ok,
                                            "reason": None, "next_step": None}, when)

    def seen(self, session=None, sprint=None, when=timedelta(0)):
        self.append("session.seen", {"session_id": session or self.SESSION, "cwd": "/r", "repo": None,
                                     "state": "idle", "name": f"p00 sprint {sprint or self.SPRINT}"}, when)

    def permit(self, kind, when, repo=None, session=None, pr=7, head=None, sprint=None, call="call-1"):
        payload = {"sprint_id": sprint or self.SPRINT, "session_id": session or self.SESSION,
                   "tool_use_id": call, "repo": repo or self.REPO, "verb": "merge",
                   "target": {"pr": pr, "head": head or self.HEAD}}
        if kind == "permit.judged":
            payload.update(decision="allow", reason="allowed")
        self.append(kind, payload, when)

    def pull(self, merged_at, head=None, pr=7, merged=True):
        self.pulls[pr] = {"merged": merged, "head": {"sha": head or self.HEAD},
                          "merged_at": None if merged_at is None else
                          (self.T0 + merged_at).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def landed_merge(self, day=1, **extra):
        """A judged allow at 10:00, its landing at 10:01 and the pull merged at 10:00:30 of the day."""
        start = timedelta(days=day, hours=10)
        self.permit("permit.judged", start, **extra)
        self.permit("permit.landed", start + timedelta(minutes=1), **extra)
        self.pull(start + timedelta(seconds=30), head=extra.get("head"))

    def run_check(self, now, *argv):
        def api_get(path, allow=()):
            self.calls.append(path)
            prefix = f"repos/{self.REPO}/pulls/"
            self.assertTrue(path.startswith(prefix), path)
            return self.pulls[int(path[len(prefix):])]

        out = io.StringIO()
        args = ["console-manager-merge", "--repo", self.REPO, "--since", self.shas["S"],
                "--log", str(self.log_path), "--repo-root", str(self.root), *argv]
        with mock.patch.object(verify_checks.forge_api, "api_get", api_get), \
                mock.patch.object(verify_checks, "_utcnow", lambda: self.T0 + now), \
                contextlib.redirect_stdout(out):
            code = verify_checks.main(args)
        return code, json.loads(out.getvalue())

    def qualifying(self, day=1):
        self.activated()
        self.seen()
        self.landed_merge(day)

    def test_a_landed_manager_merge_after_activation_is_met(self):
        self.qualifying()
        code, report = self.run_check(timedelta(days=2))
        self.assertEqual(code, 0)
        self.assertEqual(report["pr"], 7)
        self.assertEqual((report["met"], report["verdict"], report["head"]), (True, "met", self.HEAD))
        self.assertEqual(report["activated_at"], self.T0.isoformat())
        self.assertEqual(report["judged_at"], (self.T0 + timedelta(days=1, hours=10)).isoformat())
        self.assertEqual(report["merged_at"], (self.T0 + timedelta(days=1, hours=10, seconds=30)).isoformat())
        self.assertEqual(set(report), {"met", "verdict", "pr", "head", "judged_at", "landed_at",
                                       "merged_at", "activated_at"})

    def test_a_delayed_verifier_still_counts_a_merge_inside_the_window(self):
        self.qualifying()
        self.assertEqual(self.run_check(timedelta(days=10))[0], 0)

    def test_a_merge_after_the_window_is_not_met(self):
        self.qualifying(day=8)
        code, report = self.run_check(timedelta(days=10))
        self.assertEqual((code, report["verdict"], report["pr"]), (1, "not_met", None))
        self.assertEqual(self.run_check(timedelta(days=8))[0], 1)

    def test_a_merge_before_activation_is_not_counted(self):
        self.activated()
        self.seen()
        self.landed_merge(day=-1)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_no_qualifying_activation_is_not_yet(self):
        self.seen()
        self.landed_merge()
        self.activated(ok=False)
        self.activated(commit="P", when=timedelta(hours=1))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_refused_manager_call_then_a_lead_merge_stays_pending(self):
        self.activated()
        self.seen()
        self.permit("permit.judged", timedelta(days=1, hours=10))
        self.pull(timedelta(days=1, hours=12))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_merge_outside_the_calls_span_is_not_counted(self):
        for merged_at in (timedelta(days=1, hours=9), timedelta(days=1, hours=11)):
            with self.subTest(merged_at=merged_at):
                self.setUp()
                self.activated()
                self.seen()
                self.permit("permit.judged", timedelta(days=1, hours=10))
                self.permit("permit.landed", timedelta(days=1, hours=10, minutes=1))
                self.pull(merged_at)
                self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_sprint_that_reported_no_issue_before_the_judgement_is_not_counted(self):
        self.activated()
        self.seen(sprint=self.OTHER_SPRINT)
        self.landed_merge(sprint=self.OTHER_SPRINT)
        self.append("sprint.reported", {"sprint_id": self.OTHER_SPRINT, "goal": "g", "report": {
            "issues": []}}, timedelta(days=0))
        self.append("sprint.reported", {"sprint_id": self.OTHER_SPRINT, "goal": "g", "report": {
            "issues": [{"issue": 5, "stage": "building"}]}}, timedelta(days=3))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)
        self.assertEqual(self.run_check(timedelta(days=10))[0], 1)

    def test_any_sprints_manager_merge_counts_whichever_issue_it_delivered(self):
        """Issue 1377 itself may have been delivered outside a sprint or as a sprint's last issue."""
        self.activated()
        self.seen(sprint=self.OTHER_SPRINT)
        self.reported(self.OTHER_SPRINT, 999)
        self.landed_merge(sprint=self.OTHER_SPRINT)
        code, report = self.run_check(timedelta(days=2))
        self.assertEqual((code, report["verdict"], report["pr"]), (0, "met", 7))

    def test_a_landing_of_another_tool_call_does_not_complete_the_allowed_one(self):
        self.activated()
        self.seen()
        start = timedelta(days=1, hours=10)
        self.permit("permit.judged", start, call="call-1")
        self.permit("permit.landed", start + timedelta(minutes=1), call="call-2")
        self.pull(start + timedelta(seconds=30))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_rows_that_name_no_tool_call_are_not_counted(self):
        self.activated()
        self.seen()
        start = timedelta(days=1, hours=10)
        for call in ("", None):
            self.permit("permit.judged", start, call=call)
            self.permit("permit.landed", start + timedelta(minutes=1), call=call)
        self.pull(start + timedelta(seconds=30))
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_git_that_cannot_answer_the_ancestry_is_an_error_not_pending(self):
        self.append("activation.finished", {"root": "/r", "commit": "d" * 40, "ok": True,
                                            "reason": None, "next_step": None}, timedelta(0))
        self.activated(when=timedelta(hours=1))
        stderr = io.StringIO()
        with mock.patch.object(verify_checks.forge_api, "api_get") as api_get, \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = verify_checks.main(["console-manager-merge", "--repo", self.REPO, "--since",
                                       self.shas["S"], "--log", str(self.log_path),
                                       "--repo-root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("git", stderr.getvalue())
        api_get.assert_not_called()

    def test_a_permit_of_another_repository_or_session_is_not_counted(self):
        self.activated()
        self.seen()
        self.landed_merge(repo="x/y")
        self.landed_merge(session="other-session")
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_a_merge_at_another_head_or_unmerged_is_skipped(self):
        self.qualifying()
        self.pull(timedelta(days=1, hours=10, seconds=30), head="c" * 40)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)
        self.pull(None, merged=False)
        self.assertEqual(self.run_check(timedelta(days=2))[0], 75)

    def test_bad_arguments_are_a_usage_error(self):
        for argv in (["--repo", "bad", "--since", self.shas["S"]],
                     ["--repo", self.REPO, "--since", "abc"],
                     ["--repo", self.REPO]):
            with self.subTest(argv=argv):
                with mock.patch.object(verify_checks.forge_api, "api_get") as api_get, \
                        contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(["console-manager-merge", *argv, "--log", str(self.log_path)])
                self.assertEqual(raised.exception.code, 2)
                api_get.assert_not_called()

    def test_the_script_is_committed_executable_and_runs_the_check(self):
        script = f"{CHECKS}/console-manager-merge"
        self.assertEqual(committed_mode(script), "100755")
        result = run_from_root([str(ROOT / script), "--repo", "bad", "--since", "x"])
        self.assertEqual(result.returncode, 2, result.stderr)


class ConsoleNoticeListsTest(unittest.TestCase):
    """`console-notice-lists` (issue 1291): the owner's notices name every issue of a project."""

    def serve(self, status, body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = loopback_server(Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def serve_view(self, entries):
        return self.serve(200, json.dumps({"entries": entries}).encode())

    @staticmethod
    def project(project_id, *notices):
        return {"type": "project", "project_id": project_id, "notices": list(notices)}

    @staticmethod
    def notice(number, text, owner=True):
        return {"id": number, "owner": owner, "kind": "heads-up", "text": text}

    def test_one_owner_notice_naming_every_issue_covers_a_project(self):
        port = self.serve_view([
            self.project("jarbird", self.notice(4, "anis-desktop is gone: #611 #711 #712")),
            {"type": "quiet_group", "label": "1 quiet projects", "count": 1,
             "projects": [self.project("nodocom", self.notice(9, "anis-desktop is gone: #2600 #2990"))]}])
        self.assertEqual(
            verify_checks.console_notice_lists(port, {"jarbird": [611, 711, 712], "nodocom": [2600, 2990]}),
            (0, {"verdict": "covered", "projects": {"jarbird": {"notice": 4}, "nodocom": {"notice": 9}}}))

    def test_a_split_list_a_manager_notice_or_a_prefix_does_not_cover(self):
        cases = {
            "split": [self.notice(1, "gone: #611"), self.notice(2, "gone: #711 #712")],
            "manager": [self.notice(3, "gone: #611 #711 #712", owner=False)],
            "prefix": [self.notice(5, "gone: #6110 #711 #712")],
        }
        for name, notices in cases.items():
            with self.subTest(name=name):
                port = self.serve_view([self.project("jarbird", *notices)])
                code, report = verify_checks.console_notice_lists(port, {"jarbird": [611, 711, 712]})
                self.assertEqual(code, 75)
                self.assertEqual(report["verdict"], "missing")
                self.assertIsNone(report["projects"]["jarbird"]["notice"])

    def test_an_entry_of_another_type_is_skipped_and_an_absent_project_is_missing(self):
        port = self.serve_view([
            {"type": "other", "project_id": "jarbird", "notices": [self.notice(1, "#611")]}])
        self.assertEqual(verify_checks.console_notice_lists(port, {"jarbird": [611]}),
                         (75, {"verdict": "missing", "projects": {"jarbird": {"notice": None}}}))

    def test_an_unreachable_console_is_not_yet(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            closed = sock.getsockname()[1]
        unreachable = (75, {"verdict": "unreachable"})
        wanted = {"jarbird": [611]}
        self.assertEqual(verify_checks.console_notice_lists(closed, wanted), unreachable)
        self.assertEqual(verify_checks.console_notice_lists(self.serve(500, b"{}"), wanted), unreachable)
        self.assertEqual(verify_checks.console_notice_lists(self.serve(200, b"[]"), wanted), unreachable)

    def test_the_command_prints_one_json_line(self):
        port = self.serve_view([self.project("jarbird", self.notice(4, "#611 #711"))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_checks.main(["console-notice-lists", "--port", str(port),
                                       "--notice", "jarbird=611,711"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), json.dumps(
            {"projects": {"jarbird": {"notice": 4}}, "verdict": "covered"}, sort_keys=True) + "\n")

    def test_a_bad_notice_argument_is_a_usage_error(self):
        bad = (["jarbird"], ["jarbird=a"], ["jarbird=611,"], ["jarbird=0"],
               ["jarbird=1", "jarbird=1"])
        for values in bad:
            with self.subTest(values=values):
                argv = ["console-notice-lists", "--port", "1"]
                for value in values:
                    argv += ["--notice", value]
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verify_checks.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_the_wrapper_is_committed_executable_and_exits_2_without_arguments(self):
        self.assertEqual(committed_mode(f"{CHECKS}/console-notice-lists"), "100755")
        self.assertEqual(run_from_root([str(ROOT / CHECKS / "console-notice-lists")]).returncode, 2)


# --- railway-project-read (issue 1124) ----------------------------------------------------


CONSOLE_LABEL = "org.nixos.agent-console"
PROXY_LABEL = "org.nixos.claude-cache-proxy"
SOPS_LABEL = "org.nixos.sops-nix"
VERIFY_LABEL = "org.nixos.verify-pending"
NO_SESSION = "ownerServices: the owner has no login session"
SESSION = "ownerServices: the owner has a login session"
DOMAIN = "Domain does not support specified action"


def loopback_server(handler):
    """A loopback `ThreadingHTTPServer` on port 0 serving `handler`, in a daemon thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/state" else 404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    body = b'{"service":"cache-proxy"}'

    def do_GET(self):
        ok = self.path == "/_proxy/health"
        body = self.body if ok else b""
        self.send_response(200 if ok else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class OwnerServicesWorld(unittest.TestCase):
    """A temp HOME with the forge key and the activation record, and the two loopback servers."""
    commit = "b" * 40

    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)
        self.home = self.tmp / "home"
        (self.home / ".ssh").mkdir(parents=True)
        (self.home / "secret").write_text("key\n", encoding="utf-8")
        self.key = self.home / ".ssh" / "id_ed25519"
        self.key.symlink_to(self.home / "secret")
        self.state = self.home / ".agents" / "state" / "console"
        self.state.mkdir(parents=True)
        self.result = self.state / "activation.result"
        self.log = self.state / "activation.log"
        self.write_activation({"commit": self.commit, "exit": 0},
                              f"building\n{NO_SESSION}\ndone\n")
        self.store = self.state / "events.sqlite3"
        self.finish(self.commit, ok=True)
        self.proxy_handler = type("Proxy", (ProxyHandler,), {})
        self.console_server = loopback_server(ConsoleHandler)
        self.proxy_server = loopback_server(self.proxy_handler)
        self.addCleanup(self.stop, self.console_server)
        self.addCleanup(self.stop, self.proxy_server)
        self.console_port = self.console_server.server_address[1]
        self.proxy_port = self.proxy_server.server_address[1]

    @staticmethod
    def stop(server):
        server.shutdown()
        server.server_close()

    def finish(self, commit, *, ok):
        """Append one `activation.finished` row, as the console does when it settles a run."""
        connection = sqlite3.connect(self.store)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                               " at TEXT NOT NULL, kind TEXT NOT NULL, project TEXT, payload TEXT NOT NULL)")
            connection.execute("INSERT INTO events (at, kind, project, payload) VALUES (?, ?, NULL, ?)",
                               ("2026-11-18T00:00:00Z", "activation.finished",
                                json.dumps({"root": "r", "commit": commit, "ok": ok})))
            connection.commit()
        finally:
            connection.close()

    def write_activation(self, result, log):
        if result is not None:
            self.result.write_text(json.dumps(result), encoding="utf-8")
        self.log.write_text(log, encoding="utf-8")
        self.age_log(10)

    def age_log(self, seconds):
        """Set the log's mtime `seconds` before the result's (negative: after)."""
        stamp = self.result.stat().st_mtime_ns if self.result.exists() else time.time_ns()
        shifted = stamp - seconds * 1_000_000_000
        os.utime(self.log, ns=(shifted, shifted))


class OwnerServicesTest(OwnerServicesWorld):
    """`owner-services` (issue 1290): the owner's services run at boot with nobody logged in."""

    def setUp(self):
        super().setUp()
        merge_base = ("-C", ".", "merge-base", "--is-ancestor", "a" * 40, self.commit)
        self.table = {
            ("print", "gui/502"): (113, ""),
            ("print", f"system/{CONSOLE_LABEL}"): (0, "\tstate = running\n\tpid = 4001\n"),
            ("print", f"system/{PROXY_LABEL}"): (0, "\tstate = running\n\tpid = 4002\n"),
            ("print", f"system/{SOPS_LABEL}"): (0, ""),
            ("print", f"system/{VERIFY_LABEL}"): (0, ""),
            ("-nP", "-a", f"-iTCP:{self.console_port}", "-sTCP:LISTEN", "-Fp"): (0, "p4001\nf3\n"),
            ("-nP", "-a", f"-iTCP:{self.proxy_port}", "-sTCP:LISTEN", "-Fp"): (0, "p4002\nf5\n"),
            merge_base: (0, ""),
        }
        self.merge_base = merge_base

    def fake(self, argv, **kw):
        answer = self.table[tuple(argv[1:])]
        if callable(answer):
            answer = answer()
        if isinstance(answer, BaseException):
            raise answer
        code, stdout = answer
        return subprocess.CompletedProcess(argv, code, stdout, "")

    def check(self):
        return verify_checks.owner_services(
            console_port=self.console_port, proxy_port=self.proxy_port, merge="a" * 40,
            home=self.home, uid=502, repo_root=Path("."), launchctl="/bin/launchctl",
            lsof="/usr/sbin/lsof", run=self.fake)

    def test_every_service_up_and_a_clean_page_activation_is_met(self):
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (0, "met"))
        self.assertEqual(report["activation"], "clean")
        self.assertTrue(report["met"])
        self.assertTrue(all(report["daemons"].values()))
        self.assertEqual(set(report["daemons"]), set(verify_checks.OWNER_SERVICE_LABELS))
        self.assertEqual(report["console"], {"answers": True, "owned": True})
        self.assertEqual(report["proxy"], {"answers": True, "owned": True})
        self.assertTrue(report["ssh_key"])

    def test_an_owner_gui_session_is_not_yet(self):
        self.table[("print", "gui/502")] = (0, "")
        self.assertEqual(self.check()[0], 75)
        self.assertEqual(self.check()[1]["verdict"], "logged_in")

    def test_a_gui_session_wins_over_a_failed_reading(self):
        self.table[("print", "gui/502")] = (0, "")
        self.table[("print", f"system/{SOPS_LABEL}")] = (113, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (75, "logged_in"))

    def test_a_daemon_not_loaded_is_not_met(self):
        self.table[("print", f"system/{SOPS_LABEL}")] = (113, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["daemons"][SOPS_LABEL], False)

    def test_a_dangling_forge_key_is_not_met(self):
        (self.home / "secret").unlink()
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["ssh_key"], False)

    def test_a_proxy_that_is_not_the_cache_proxy_is_not_met(self):
        self.proxy_handler.body = b'{"service":"other"}'
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["proxy"]["answers"], False)

    def test_no_console_is_not_met(self):
        self.console_server.shutdown()
        self.console_server.server_close()
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["console"]["answers"], False)

    def test_a_console_served_by_another_process_is_not_met(self):
        lsof = ("-nP", "-a", f"-iTCP:{self.console_port}", "-sTCP:LISTEN", "-Fp")
        self.table[("print", f"system/{CONSOLE_LABEL}")] = (0, "\tstate = spawn scheduled\n")
        self.table[lsof] = (0, "p5000\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertEqual(report["console"], {"answers": True, "owned": False})
        self.assertIs(report["daemons"][CONSOLE_LABEL], True)
        with self.subTest("the job has a pid, another process listens"):
            self.table[("print", f"system/{CONSOLE_LABEL}")] = (0, "\tpid = 4001\n")
            self.assertIs(self.check()[1]["console"]["owned"], False)

    def test_a_domain_line_in_the_page_activation_is_not_met(self):
        self.write_activation({"commit": self.commit, "exit": 0},
                              f"building\n{NO_SESSION}\nBoot-out failed: 125: {DOMAIN}\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (1, "not_met", "domain_lines"))

    def test_an_activation_without_the_session_line_is_not_met(self):
        self.write_activation({"commit": self.commit, "exit": 0}, "building\ndone\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (1, "not_met", "unmarked"))

    def test_an_activation_in_an_owner_session_is_not_yet(self):
        self.write_activation({"commit": self.commit, "exit": 0}, f"building\n{SESSION}\n")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "logged_in"))

    def test_an_activation_of_an_older_commit_is_not_yet(self):
        self.table[self.merge_base] = (1, "")
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_an_unread_activation_is_not_yet(self):
        self.result.unlink()
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_failed_activation_is_not_yet(self):
        records = [({"commit": self.commit, "exit": 1}, "building\n"),
                   ({"commit": self.commit, "exit": True}, "building\n"),
                   ({"commit": self.commit, "exit": False}, "building\n"),
                   ({"commit": self.commit, "error": "FileNotFoundError: x"}, "")]
        for record, log in records:
            with self.subTest(record=record):
                self.write_activation(record, log)
                code, report = self.check()
                self.assertEqual((code, report["verdict"], report["activation"]),
                                 (75, "not_yet", "unread"))

    def test_an_activation_the_console_did_not_record_as_succeeded_is_not_yet(self):
        """The result's exit 0 is the command's; the console may then find the host on another revision."""
        for name, rows in (("no row", []), ("failed", [("b" * 40, False)]),
                           ("another commit", [("c" * 40, True)]),
                           ("a failure after a success", [("b" * 40, True), ("b" * 40, False)])):
            with self.subTest(name):
                self.store.unlink()
                if not rows:
                    sqlite3.connect(self.store).close()
                for commit, ok in rows:
                    self.finish(commit, ok=ok)
                code, report = self.check()
                self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))
        with self.subTest("no store"):
            self.store.unlink()
            code, report = self.check()
            self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_success_after_a_failure_of_the_same_commit_is_met(self):
        self.finish(self.commit, ok=False)
        self.finish(self.commit, ok=True)
        self.assertEqual(self.check()[0], 0)

    def test_a_gui_domain_that_cannot_be_read_is_not_a_logout(self):
        for name, answer in (("exit 1", (1, "")), ("exit 64", (64, "")),
                             ("timeout", subprocess.TimeoutExpired(["launchctl"], 5)),
                             ("no tool", FileNotFoundError("launchctl"))):
            with self.subTest(name):
                self.table[("print", "gui/502")] = answer
                code, report = self.check()
                self.assertEqual((code, report["verdict"]), (1, "gui_unread"))
                self.assertFalse(report["met"])

    def test_every_missing_domain_answer_reads_as_no_session(self):
        for status in (112, 113, 125):
            with self.subTest(status=status):
                self.table[("print", "gui/502")] = (status, "")
                self.assertEqual(self.check()[1]["verdict"], "met")

    def test_a_log_newer_than_its_result_is_not_yet(self):
        self.age_log(-10)
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_a_result_replaced_while_reading_is_not_yet(self):
        def replaced():
            self.result.unlink()
            return 0, ""
        self.table[self.merge_base] = replaced
        code, report = self.check()
        self.assertEqual((code, report["verdict"], report["activation"]), (75, "not_yet", "unread"))

    def test_an_unread_activation_is_not_yet_even_with_a_service_down(self):
        self.result.unlink()
        self.proxy_server.shutdown()
        self.proxy_server.server_close()
        self.assertEqual(self.check()[0], 75)

    def test_a_missing_tool_is_a_failed_reading(self):
        for key in list(self.table):
            if key[0] == "-nP":
                self.table[key] = FileNotFoundError("lsof")
        code, report = self.check()
        self.assertEqual((code, report["verdict"]), (1, "not_met"))
        self.assertIs(report["console"]["owned"], False)


class OwnerServicesCommandTest(OwnerServicesWorld):
    def setUp(self):
        self.commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                     capture_output=True, text=True, check=True).stdout.strip()
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        pid = os.getpid()
        self.launchctl = self.script("launchctl", f"""#!/bin/sh
echo "noise {self.home}" >&2
case "$*" in
  "print gui/"*) exit 113 ;;
  "print system/{CONSOLE_LABEL}"|"print system/{PROXY_LABEL}") echo "pid = {pid}"; exit 0 ;;
  *) exit 0 ;;
esac
""")
        self.lsof = self.script("lsof", f"""#!/bin/sh
echo "noise {self.home}" >&2
echo "p{pid}"
exit 0
""")
        self.arguments = ["owner-services", "--console-port", str(self.console_port),
                          "--proxy-port", str(self.proxy_port), "--merge", self.commit,
                          "--launchctl", str(self.launchctl), "--lsof", str(self.lsof)]

    def script(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
        return path

    def command(self, arguments=None):
        return run_from_root([sys.executable, "-m", "agent_tools.verification.verify_checks",
                              *(arguments or self.arguments)], env_extra={"HOME": str(self.home)})

    def test_the_command_prints_one_json_line_and_exits_with_the_verdict(self):
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")
        self.assertEqual(result.stderr, "")
        self.assertNotIn(str(self.home), result.stdout + result.stderr)
        self.assertNotIn("noise", result.stdout + result.stderr)

    def test_the_committed_script_runs_the_owner_services_check(self):
        (self.home / ".agents" / "bin").mkdir(parents=True)
        (self.home / ".agents" / "bin" / "verify-pending").write_text(
            "#!/bin/sh\nunset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
            f'exec {sys.executable} -I -m agent_tools.verification.verify_pending "$@"\n',
            encoding="utf-8")
        result = subprocess.run(["/bin/sh", str(ROOT / CHECKS / "owner-services"), *self.arguments[1:]],
                                cwd=ROOT, env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")

    def test_a_bad_merge_sha_is_a_usage_error(self):
        arguments = list(self.arguments)
        arguments[arguments.index("--merge") + 1] = "xyz"
        result = self.command(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--merge", result.stderr)
        self.assertNotIn("invalid choice", result.stderr)

    def test_the_session_lines_match_the_activation_cleanup(self):
        text = (ROOT / "hosts/common/darwin-owner-services.nix").read_text(encoding="utf-8")
        self.assertIn(verify_checks.NO_SESSION_LINE, text)
        self.assertIn(verify_checks.SESSION_LINE, text)

    def test_the_check_script_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/owner-services"), "100755")


FAKE_DEVENV = f"""#!{sys.executable}
import json, os, subprocess, sys, time
from pathlib import Path

state = Path(os.environ["DEVENV_SHELL_FIXTURE"])
with open(state / "devenv.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{
        "argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(),
        "home": os.environ.get("HOME"),
        "git_config_global": os.environ.get("GIT_CONFIG_GLOBAL"),
        "git_dir": os.environ.get("GIT_DIR"),
        "git_index_file": os.environ.get("GIT_INDEX_FILE")}}) + "\\n")
if sys.argv[1:3] != ["shell", "--"]:
    sys.exit(64)
(Path.cwd() / ".devenv").mkdir(exist_ok=True)
(Path.cwd() / ".devenv" / "state").write_text("x", encoding="utf-8")
if (state / "stray").exists():
    (Path.cwd() / "stray.txt").write_text("x", encoding="utf-8")
if (state / "fail").exists():
    print("shell broke")
    sys.exit(3)
if (state / "nocommit").exists():
    sys.exit(0)
if (state / "sleep").exists():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (state / "grandchild.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
env = dict(os.environ)
command = sys.argv[3:]
if (state / "locked").exists():
    locked = Path.cwd() / ".devenv" / "locked"
    locked.mkdir(exist_ok=True)
    (locked / "f").write_text("x", encoding="utf-8")
    locked.chmod(0o500)
if (state / "localconfig").exists():
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], check=True)
if (state / "message").exists():
    command = ["other" if word == "probe" else word for word in command]
if (state / "rewind").exists():
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="commit.gpgsign",
               GIT_CONFIG_VALUE_0="false")
    subprocess.run(command, env=env, check=True)
    subprocess.run(["git", "reset", "-q", "--hard", (state / "rewind").read_text()], check=True)
    sys.exit(0)
if (state / "hooks").exists():
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath",
               GIT_CONFIG_VALUE_0="/dev/null")
sys.exit(subprocess.run(command, env=env).returncode)
"""
FAKE_KEYGEN = f"""#!{sys.executable}
import sys

if "-Y" in sys.argv and "sign" in sys.argv:
    with open(sys.argv[-1] + ".sig", "w", encoding="utf-8") as sig:
        sig.write("-----BEGIN SSH SIGNATURE-----\\nZmFrZQ==\\n-----END SSH SIGNATURE-----\\n")
"""


class DevenvShellWorld:
    """A repository, a fake `devenv` and a fake ssh signer under one private environment."""

    def __init__(self, test_case):
        scratch = tempfile.TemporaryDirectory()
        test_case.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()
        for name in ("bin", "state", "home"):
            (self.tmp / name).mkdir()
        self.state = self.tmp / "state"
        for name, text in (("devenv", FAKE_DEVENV), ("fake-ssh-keygen", FAKE_KEYGEN)):
            script = self.tmp / "bin" / name
            script.write_text(text, encoding="utf-8")
            script.chmod(0o755)
        (self.tmp / "key").write_text("dummy", encoding="utf-8")
        self.gitconfig = self.tmp / "gitconfig"
        self.set_signing(True)
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "HOME": str(self.tmp / "home"), "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1", "DEVENV_SHELL_FIXTURE": str(self.state),
            "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
            "PYTHONPATH": str(ROOT / "python")}
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], env=self.env, check=True)
        (self.repo / ".gitignore").write_text(".devenv/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def set_signing(self, enabled):
        self.gitconfig.write_text(
            f"[user]\n\tname = Probe\n\temail = probe@example.invalid\n"
            f"\tsigningkey = {self.tmp / 'key'}\n[gpg]\n\tformat = ssh\n"
            f"[gpg \"ssh\"]\n\tprogram = {self.tmp / 'bin' / 'fake-ssh-keygen'}\n"
            f"[commit]\n\tgpgsign = {'true' if enabled else 'false'}\n", encoding="utf-8")

    def run(self, argv, env=None):
        return subprocess.run(argv, cwd=ROOT, env=env or self.env, capture_output=True,
                              text=True, timeout=60)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              capture_output=True, text=True, check=True).stdout

    def check(self, probe, *extra, env=None):
        return self.run([str(ROOT / CHECKS / "devenv-shell"), "--probe", probe,
                         "--repo-root", str(self.repo), *extra], env)

    @staticmethod
    def report(result):
        return json.loads(result.stdout)

    def calls(self):
        log = self.state / "devenv.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def flag(self, name):
        (self.state / name).write_text("", encoding="utf-8")

    def worktrees(self):
        return [line for line in self.git("worktree", "list", "--porcelain").splitlines()
                if line.startswith("worktree ")]


def process_is_gone(pid, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


class DevenvShellCheckTest(unittest.TestCase):
    def setUp(self):
        self.world = DevenvShellWorld(self)

    def test_a_signed_commit_through_the_shell_is_met(self):
        world = self.world
        result = world.check("commit")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = world.report(result)
        self.assertEqual(sorted(report), [
            "elapsed_seconds", "exit", "hooks_path", "met", "new_commit", "output_tail",
            "probe", "reason", "signed", "status"])
        self.assertEqual(report["probe"], "commit")
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], [])
        self.assertEqual(report["hooks_path"], {"outside": None, "inside": None})
        self.assertIsNone(report["reason"])
        self.assertIs(report["met"], True)
        self.assertIsInstance(report["elapsed_seconds"], float)
        self.assertIsInstance(report["output_tail"], list)
        calls = world.calls()
        self.assertEqual([call["argv"] for call in calls], [
            ["shell", "--", "git", "commit", "--allow-empty", "-m", "probe"],
            ["shell", "--", "git", "config", "--get", "core.hooksPath"]])
        self.assertEqual(calls[0]["cwd"], calls[1]["cwd"])
        self.assertNotEqual(calls[0]["cwd"], str(world.repo))
        for call in calls:
            self.assertEqual(call["home"], world.env["HOME"])
            self.assertEqual(call["git_config_global"], world.env["GIT_CONFIG_GLOBAL"])
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("rev-parse", "HEAD").strip(), world.base)
        self.assertEqual(world.git("status", "--porcelain"), "")
        self.assertFalse(Path(calls[0]["cwd"]).exists())

    def test_an_unsigned_commit_through_the_shell_is_not_met(self):
        self.world.set_signing(False)
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], False)
        self.assertEqual(report["reason"], "unsigned")
        self.assertIs(report["met"], False)

    def test_a_shell_that_makes_no_commit_is_not_met(self):
        self.world.flag("nocommit")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], False)
        self.assertIs(report["signed"], False)
        self.assertEqual(report["reason"], "no_commit")

    def test_a_head_moved_to_an_older_signed_commit_is_not_a_probe_commit(self):
        world = self.world
        world.set_signing(False)
        world.git("commit", "--allow-empty", "-m", "tip")
        (world.state / "rewind").write_text(world.base, encoding="utf-8")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["exit"], 0)
        self.assertIs(report["new_commit"], False)
        self.assertEqual(report["reason"], "no_commit")
        self.assertIs(report["met"], False)

    def test_a_commit_with_another_message_is_not_the_probe_commit(self):
        world = self.world
        world.flag("message")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIs(report["new_commit"], False)
        self.assertEqual(report["reason"], "no_commit")

    def test_a_shell_that_writes_the_repository_config_leaves_the_callers_untouched(self):
        world = self.world
        world.flag("localconfig")
        before = (world.repo / ".git" / "config").read_text(encoding="utf-8")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(world.report(result)["reason"], "hooks_changed")
        self.assertEqual((world.repo / ".git" / "config").read_text(encoding="utf-8"), before)
        configured = subprocess.run(
            ["git", "-C", str(world.repo), "config", "--get", "core.hooksPath"],
            env=world.env, capture_output=True, text=True)
        self.assertEqual(configured.returncode, 1)
        self.assertEqual(len(world.worktrees()), 1)

    @unittest.skipIf(os.geteuid() == 0, "root can remove a read-only directory")
    def test_a_scratch_clone_that_cannot_be_removed_is_a_fixture_error(self):
        world = self.world
        world.flag("locked")
        result = world.check("clean")
        scratch = Path(world.calls()[0]["cwd"]).parent
        try:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("fixture_error", result.stderr)
            self.assertIn("not removed", result.stderr)
            self.assertEqual(result.stdout, "")
        finally:
            for locked in scratch.rglob("locked"):
                locked.chmod(0o700)
            shutil.rmtree(scratch, ignore_errors=True)

    def test_a_failing_shell_is_not_met(self):
        self.world.flag("fail")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertEqual(report["exit"], 3)
        self.assertEqual(report["reason"], "shell_failed")
        self.assertIn("shell broke", report["output_tail"])
        self.assertEqual(len(self.world.calls()), 1)

    def test_a_signed_commit_that_leaves_a_file_behind_is_not_met(self):
        world = self.world
        world.flag("stray")
        result = world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIs(report["new_commit"], True)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], ["?? stray.txt"])
        self.assertEqual(report["reason"], "dirty")
        self.assertIs(report["met"], False)
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("status", "--porcelain"), "")

    def test_a_shell_that_overrides_the_hooks_path_is_not_met(self):
        self.world.flag("hooks")
        result = self.world.check("commit")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = self.world.report(result)
        self.assertIs(report["signed"], True)
        self.assertEqual(report["status"], [])
        self.assertEqual(report["hooks_path"], {"outside": None, "inside": "/dev/null"})
        self.assertEqual(report["reason"], "hooks_changed")

    def test_an_inherited_repository_redirect_cannot_reach_the_callers_branch(self):
        world = self.world
        staged = world.git("ls-files", "-s")
        redirect = {**world.env, "GIT_DIR": str(world.repo / ".git"),
                    "GIT_WORK_TREE": str(world.repo),
                    "GIT_INDEX_FILE": str(world.repo / ".git" / "index")}
        result = world.check("commit", env=redirect)
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in world.calls():
            self.assertIsNone(call["git_dir"])
            self.assertIsNone(call["git_index_file"])
        self.assertEqual(world.git("rev-parse", "HEAD").strip(), world.base)
        self.assertEqual(world.git("rev-list", "--count", "HEAD").strip(), "1")
        self.assertEqual(world.git("ls-files", "-s"), staged)
        self.assertEqual(world.git("status", "--porcelain"), "")
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_shell_past_the_bound_is_not_met_and_its_processes_end(self):
        world = self.world
        world.flag("sleep")
        started = time.monotonic()
        result = world.check("commit", "--timeout-seconds", "1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertIsNone(report["exit"])
        self.assertEqual(report["reason"], "timeout")
        grandchild = int((world.state / "grandchild.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_is_gone(grandchild))
        self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_terminated_check_ends_its_shell_and_removes_its_worktree(self):
        world = self.world
        world.flag("sleep")
        proc = subprocess.Popen(
            [str(ROOT / CHECKS / "devenv-shell"), "--probe", "commit",
             "--repo-root", str(world.repo)],
            cwd=ROOT, env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            pid_file = world.state / "grandchild.pid"
            deadline = time.monotonic() + 20
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(pid_file.exists())
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode, 128 + signal.SIGTERM)
            self.assertTrue(process_is_gone(int(pid_file.read_text(encoding="utf-8"))))
            self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
            self.assertEqual(len(world.worktrees()), 1)
            self.assertFalse(Path(world.calls()[0]["cwd"]).exists())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_a_killed_check_still_ends_its_shell(self):
        world = self.world
        world.flag("sleep")
        proc = subprocess.Popen(
            [str(ROOT / CHECKS / "devenv-shell"), "--probe", "commit",
             "--repo-root", str(world.repo)],
            cwd=ROOT, env=world.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            pid_file = world.state / "grandchild.pid"
            deadline = time.monotonic() + 20
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(pid_file.exists())
            scratch = Path(world.calls()[0]["cwd"]).parent
            self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
            proc.kill()
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode, -signal.SIGKILL)
            self.assertTrue(process_is_gone(int(pid_file.read_text(encoding="utf-8"))))
            self.assertTrue(process_is_gone(world.calls()[0]["pid"]))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_a_timeout_past_the_bound_is_refused(self):
        for value in ("301", "0"):
            with self.subTest(value=value):
                result = self.world.check("commit", "--timeout-seconds", value)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--timeout-seconds", result.stderr)
                self.assertEqual(self.world.calls(), [])
                self.assertEqual(len(self.world.worktrees()), 1)

    def test_no_devenv_on_path_is_not_met(self):
        world = self.world
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is not installed")
        system = world.tmp / "sys"
        system.mkdir()
        (system / "git").symlink_to(git)
        (system / "python3").symlink_to(sys.executable)
        result = world.check("commit", env={**world.env, "PATH": str(system)})
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["reason"], "devenv_missing")
        self.assertIsNone(report["exit"])
        self.assertIs(report["met"], False)
        self.assertEqual(world.calls(), [])
        self.assertEqual(len(world.worktrees()), 1)

    def test_a_shell_that_leaves_the_checkout_clean_is_met(self):
        world = self.world
        result = world.check("clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = world.report(result)
        self.assertEqual(report["probe"], "clean")
        self.assertEqual(report["exit"], 0)
        self.assertEqual(report["status"], [])
        self.assertIsNone(report["reason"])
        self.assertIs(report["met"], True)
        self.assertEqual(sorted(report), [
            "elapsed_seconds", "exit", "met", "output_tail", "probe", "reason", "status"])
        self.assertEqual([call["argv"] for call in world.calls()], [["shell", "--", "true"]])

    def test_a_shell_that_dirties_the_checkout_is_not_met(self):
        world = self.world
        world.flag("stray")
        result = world.check("clean")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = world.report(result)
        self.assertEqual(report["status"], ["?? stray.txt"])
        self.assertEqual(report["reason"], "dirty")
        self.assertEqual(len(world.worktrees()), 1)
        self.assertEqual(world.git("status", "--porcelain"), "")

    def test_an_unrelated_worktree_registration_survives(self):
        world = self.world
        other = world.tmp / "other"
        world.git("worktree", "add", "--detach", str(other))
        shutil.rmtree(other)
        result = world.check("clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"worktree {other}", world.worktrees())

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(f"{CHECKS}/devenv-shell"), "100755")
        result = self.world.run([str(ROOT / CHECKS / "devenv-shell")])
        self.assertEqual(result.returncode, 2)
