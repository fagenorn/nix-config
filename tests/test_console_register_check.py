"""The host check that registers a throwaway project from the page and restores the registry (#1052).

Each case has its own HOME, so no case shares a registry, a plan store or an event log with another.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from agent_tools.console import register, register_check
from agent_tools.project_contract import agent_platform

from . import accounts_sandbox
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = str(ROOT / register_check.CONTRACT_SOURCE)
WRAPPER = ROOT / "home/common/verify-pending/checks/console-register"


def view(registration):
    return 200, json.dumps({"registration": registration, "entries": []}).encode()


def seeded(entries) -> bytes:
    agent_platform.write_registry(entries)
    return agent_platform.registry_path().read_bytes()


class Case(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(self.home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, self.home, True)
        share = self.home / ".agents/share"
        share.mkdir(parents=True)
        shutil.copy(ROOT / "home/common/agent-skills/platform-manifest.json",
                    share / "platform-manifest.json")
        self.tmp_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_root, True)

    def token(self):
        path = agent_platform.state_root() / "console" / "page-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("t" * 43 + "\n")

    def run_check(self, argv, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = register_check.main(argv, tmp_root=self.tmp_root, **kwargs)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])


class RealConsoleTest(Case):
    def test_the_check_registers_then_restores_the_registry(self):
        keep = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keep, True)
        seeded([{"project_id": "owner/keep", "root": str(keep)}])
        store = agent_platform.state_root() / "console" / "events.sqlite3"
        svc = support.service(self, store, agent_platform.registry_path(),
                              adopter=register.Adopter(), dispatch=None)
        code, out = self.run_check(
            ["--url", f"http://127.0.0.1:{svc.address[1]}", "--contract", CONTRACT,
             "--wait", "120"])
        self.assertEqual((code, out["status"], out["restored"]), (0, "met", True))
        registry = json.loads(agent_platform.registry_path().read_text())
        self.assertEqual(registry["projects"], [{"project_id": "owner/keep", "root": str(keep)}])
        self.assertFalse(Path(out["root"]).exists())
        self.assertEqual(list(self.tmp_root.iterdir()), [])
        for plan in (agent_platform.state_root() / "adopt/plans").glob("*.json"):
            handoff = json.loads(plan.read_text()).get("handoff", {})
            self.assertNotEqual(handoff.get("repo_root"), out["root"])
        results = [json.loads(row[4])["result"] for row in support.log_rows(store)
                   if row[2] == "registration.ended"]
        self.assertIn("registered", results)


class SettleTest(Case):
    PID = "console-check/register-test"

    def late_writer(self, root_box, written):
        def late():
            with agent_platform.registry_transaction() as entries:
                agent_platform.write_registry(
                    [*entries, {"project_id": self.PID, "root": root_box[0]}])
            plans = agent_platform.state_root() / "adopt/plans"
            plans.mkdir(parents=True, exist_ok=True)
            (plans / "late.json").write_text(json.dumps({"handoff": {"repo_root": root_box[0]}}))
            written.set()
        return late

    def late_run(self, status):
        keep = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keep, True)
        before = seeded([{"project_id": "owner/keep", "root": str(keep)}])
        self.token()
        root_box, written, timers = [None], threading.Event(), []

        def post(url, headers, body):
            root_box[0] = json.loads(body)["path"]
            timer = threading.Timer(1.0, self.late_writer(root_box, written))
            timers.append(timer)
            timer.start()
            return status, b""

        def fetch(url):
            if root_box[0] is None:
                return view(None)
            if not written.is_set():
                return view({"root": root_box[0], "status": "running", "result": None,
                             "headline": "Planning…"})
            return view({"root": root_box[0], "status": "done", "result": "not_registered",
                         "headline": "r was not registered: x"})

        code, out = self.run_check(["--wait", "0.2", "--contract", CONTRACT], fetch=fetch,
                                   post=post, project_id=self.PID, poll=0.05, settle=30)
        for timer in timers:
            timer.join()
        self.assertEqual((code, out["status"], out["reason"]), (1, "not_met", "no result"))
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)
        self.assertFalse((agent_platform.state_root() / "adopt/plans/late.json").exists())
        self.assertEqual(list(self.tmp_root.iterdir()), [])

    def test_a_late_write_is_restored_because_the_check_waits_for_the_run(self):
        self.late_run(204)

    def test_an_unanswered_post_still_waits_for_the_run(self):
        self.late_run(None)

    def test_a_run_that_never_settles_is_left_and_named(self):
        before = seeded([])
        self.token()
        root_box = [None]

        def post(url, headers, body):
            root_box[0] = json.loads(body)["path"]
            return 204, b""

        def fetch(url):
            if root_box[0] is None:
                return view(None)
            return view({"root": root_box[0], "status": "running", "result": None,
                         "headline": "Planning…"})

        code, out = self.run_check(["--wait", "0.1", "--contract", CONTRACT], fetch=fetch,
                                   post=post, project_id=self.PID, poll=0.05, settle=0.3)
        self.assertEqual(code, 1)
        self.assertEqual(out, {"project_id": self.PID, "root": root_box[0],
                               "status": "unsettled"})
        self.assertTrue(Path(root_box[0]).exists())
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)

    def test_the_default_wait_covers_the_console_run(self):
        self.assertEqual(register_check.SETTLE_SECONDS,
                         2 * register.RUN_TIMEOUT + register.GIT_TIMEOUT + 60)
        self.assertEqual(register_check.parser().parse_args([]).wait,
                         register_check.SETTLE_SECONDS)
        self.assertGreater(register_check.POST_TIMEOUT, register.GIT_TIMEOUT)


class RestoreTest(Case):
    PID = "console-check/register-leftover"

    def registered_run(self):
        """A stubbed console that registers, leaving one stored plan behind; the output."""
        seeded([])
        self.token()
        box = [None]
        plans = agent_platform.state_root() / "adopt/plans"
        self.plan = plans / "leftover.json"

        def post(url, headers, body):
            box[0] = json.loads(body)["path"]
            plans.mkdir(parents=True, exist_ok=True)
            self.plan.write_text(json.dumps({"handoff": {"repo_root": box[0]}}))
            return 204, b""

        def fetch(url):
            if box[0] is None:
                return view(None)
            return 200, json.dumps({
                "registration": {"root": box[0], "status": "done", "result": "registered",
                                 "headline": "registered"},
                "entries": [{"project_id": self.PID}]}).encode()

        return self.run_check(["--wait", "1", "--contract", CONTRACT], fetch=fetch, post=post,
                              project_id=self.PID, poll=0.05, settle=5)

    def test_a_plan_that_cannot_be_deleted_is_not_restored_and_is_named(self):
        real = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "leftover.json":
                raise PermissionError("held")
            return real(path, *args, **kwargs)

        with unittest.mock.patch.object(Path, "unlink", unlink):
            code, out = self.registered_run()
        self.assertEqual(
            (code, out), (1, {"status": "not_restored", "leftovers": [str(self.plan)]}))

    def test_a_directory_that_cannot_be_removed_is_not_restored_and_is_named(self):
        with unittest.mock.patch.object(register_check.shutil, "rmtree"):
            code, out = self.registered_run()
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "not_restored")
        self.assertEqual(len(out["leftovers"]), 1)
        self.assertTrue(Path(out["leftovers"][0]).is_dir())
        shutil.rmtree(out["leftovers"][0])

    def test_a_clean_restore_is_met(self):
        code, out = self.registered_run()
        self.assertEqual((code, out["status"], out["restored"]), (0, "met", True))
        self.assertFalse(self.plan.exists())


class StubTest(Case):
    def test_a_console_that_does_not_answer_is_not_running(self):
        code, out = self.run_check([], fetch=lambda url: (None, b""))
        self.assertEqual((code, out), (75, {"status": "not_running"}))

    def test_a_console_without_the_member_is_not_deployed(self):
        code, out = self.run_check([], fetch=lambda url: (200, b'{"capacity": {}}'))
        self.assertEqual((code, out), (75, {"status": "not_deployed"}))

    def test_a_busy_console_is_not_yet_and_restores(self):
        before = seeded([{"project_id": "owner/keep", "root": "/somewhere"}])
        self.token()
        code, out = self.run_check(
            ["--contract", CONTRACT], fetch=lambda url: view(None),
            post=lambda url, headers, body: (409, b"a registration is already running for x\n"))
        self.assertEqual((code, out), (75, {"status": "busy"}))
        self.assertEqual(agent_platform.registry_path().read_bytes(), before)
        self.assertEqual(list(self.tmp_root.iterdir()), [])

    def test_another_refusal_is_not_met(self):
        seeded([])
        self.token()
        code, out = self.run_check(
            ["--contract", CONTRACT], fetch=lambda url: view(None),
            post=lambda url, headers, body: (409, b"... is not the top of a git checkout\n"))
        self.assertEqual((code, out["status"]), (1, "not_met"))
        self.assertTrue(out["reason"].startswith("refused 409 "))

    def test_a_foreign_url_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            register_check.main(["--url", "http://example.com:1"])
        self.assertEqual(raised.exception.code, 2)


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_runs_the_module(self):
        done = subprocess.run([str(WRAPPER), "--url", "http://127.0.0.1:1"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 75)
        self.assertEqual(json.loads(done.stdout), {"status": "not_running"})
        self.assertTrue(os.access(WRAPPER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
