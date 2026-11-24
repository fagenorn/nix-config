"""The console grants every registered project's folder trust at start (#1183, ADR-console-034).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console as console_module
from agent_tools.console import folder_trust, service
from agent_tools.console.write_guard import TokenError

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures


class Case(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        self.dirs = [support.profile_dir(self.store, name) for name in ("solo", "work")]
        self.files = {"default": self.home / ".claude.json",
                      "solo": self.dirs[0] / ".claude.json",
                      "work": self.dirs[1] / ".claude.json"}
        repos = {}
        for name in ("alpha", "beta"):
            repo = self.root / name
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                           stdin=subprocess.DEVNULL)
            repos[name] = repo
        self.keys = {name: os.path.realpath(repo) for name, repo in repos.items()}
        support.write_registry(self.registry, [
            {"project_id": "alpha", "root": str(repos["alpha"])},
            {"project_id": "beta", "root": str(repos["beta"])}])

    def begin(self, **kwargs):
        kwargs.setdefault("trust_at_start", True)
        self.svc = support.service(self, self.store, self.registry, profile_dirs=self.dirs,
                                   trust_home=self.home, session_poll_seconds=3600, **kwargs)
        return self.svc

    def rows(self):
        return [json.loads(payload) for _, _, kind, _, payload in support.log_rows(self.store)
                if kind == "trust.granted"]

    def wait_for(self, predicate, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("timed out waiting")

    def write(self, name, document):
        self.files[name].write_text(json.dumps(document))

    def load(self, name):
        return json.loads(self.files[name].read_text())

    def blocking_granter(self, calls):
        entered, release = threading.Event(), threading.Event()

        def granter(path, key):
            calls.append(key)
            if len(calls) == 1:
                entered.set()
                release.wait(10)
            return folder_trust.grant(path, key)

        return granter, entered, release


class StartTrustTest(Case):
    def seed(self):
        alpha, beta = self.keys["alpha"], self.keys["beta"]
        self.write("default", {"oauthAccount": {"a": 1},
                               "projects": {"/elsewhere": {"allowedTools": ["x"]}}})
        self.write("work", {"oauthAccount": {"b": 2},
                            "projects": {alpha: {"hasTrustDialogAccepted": True, "x": 1}}})
        self.write("solo", {"oauthAccount": {"c": 3}})
        return alpha, beta

    def test_start_grants_every_registered_project_in_every_profile_and_keeps_the_rest(self):
        alpha, beta = self.seed()
        self.begin()
        self.wait_for(lambda: len(self.rows()) == 2)
        trusted = {"hasTrustDialogAccepted": True}
        self.assertEqual(self.load("default"), {
            "oauthAccount": {"a": 1},
            "projects": {"/elsewhere": {"allowedTools": ["x"]},
                         alpha: dict(trusted), beta: dict(trusted)}})
        self.assertEqual(self.load("work"), {
            "oauthAccount": {"b": 2},
            "projects": {alpha: {"hasTrustDialogAccepted": True, "x": 1}, beta: dict(trusted)}})
        self.assertEqual(self.load("solo"), {
            "oauthAccount": {"c": 3}, "projects": {alpha: dict(trusted), beta: dict(trusted)}})
        self.assertEqual(self.rows(), [
            {"by": "owner", "cause": "console-start", "project": "alpha", "root": alpha,
             "profiles": [{"profile": "default", "result": "granted"},
                          {"profile": "solo", "result": "granted"},
                          {"profile": "work", "result": "already"}]},
            {"by": "owner", "cause": "console-start", "project": "beta", "root": beta,
             "profiles": [{"profile": "default", "result": "granted"},
                          {"profile": "solo", "result": "granted"},
                          {"profile": "work", "result": "granted"}]}])

    def test_a_project_trusted_everywhere_reads_already_and_is_not_rewritten(self):
        trusted = {self.keys["alpha"]: {"hasTrustDialogAccepted": True},
                   self.keys["beta"]: {"hasTrustDialogAccepted": True}}
        for name in self.files:
            self.write(name, {"oauthAccount": {"n": name}, "projects": trusted})
        before = {}
        for name, path in self.files.items():
            info = os.stat(path)
            before[name] = (info.st_ino, info.st_mtime_ns, path.read_bytes())
        self.begin()
        self.wait_for(lambda: len(self.rows()) == 2)
        for row in self.rows():
            self.assertEqual(row["profiles"], [{"profile": p, "result": "already"}
                                               for p in ("default", "solo", "work")])
        for name, path in self.files.items():
            info = os.stat(path)
            self.assertEqual((info.st_ino, info.st_mtime_ns, path.read_bytes()), before[name])
            self.assertEqual([p.name for p in path.parent.iterdir()
                              if p.name.startswith(".claude.json.trust-")], [])

    def test_a_failed_read_back_raises_the_check_again_card(self):
        alpha, beta = self.seed()
        real = folder_trust.swap

        def wrapper(a, b):
            real(a, b)
            if Path(b) == self.files["solo"]:
                handle, temporary = tempfile.mkstemp(dir=self.files["solo"].parent)
                with os.fdopen(handle, "w") as stream:
                    json.dump({"projects": {}}, stream)
                os.replace(temporary, self.files["solo"])

        def open_failures():
            items = json.loads(self.svc.view_bytes)["inbox"]["open"]
            return [item for item in items if item.get("reason") == "trust_failed"]

        with mock.patch.object(folder_trust, "swap", new=wrapper):
            self.begin()
            self.wait_for(lambda: len(self.rows()) == 2 and len(open_failures()) == 2)
        for row in self.rows():
            results = {entry["profile"]: entry["result"] for entry in row["profiles"]}
            self.assertEqual(results["solo"], "failed")
            self.assertEqual(results["default"], "granted")
        items = open_failures()
        self.assertEqual(sorted((item["root"], item["profile"]) for item in items),
                         sorted([(alpha, "solo"), (beta, "solo")]))
        self.assertEqual({item["root"]: item["title"] for item in items},
                         {alpha: "Trust alpha", beta: "Trust beta"})
        for item in items:
            self.assertEqual(item["questions"][0]["options"], ["Check again"])

    def test_the_sweep_runs_off_the_ingest_lock_and_the_page_answers(self):
        self.seed()
        granter, entered, release = self.blocking_granter([])
        self.begin(trust_granter=granter)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(5))
        status, _, _ = support.get_page(self.svc.address, "/")
        self.assertEqual(status, 200)
        status, _, _ = support.post_hook(self.svc.address, support.hook_body("session start"))
        self.assertEqual(status, 204)
        self.assertEqual(self.rows(), [])
        release.set()
        self.wait_for(lambda: len(self.rows()) == 2)

    def test_close_stops_the_sweep_between_projects(self):
        self.seed()
        calls = []
        granter, entered, release = self.blocking_granter(calls)
        self.addCleanup(release.set)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.begin(trust_granter=granter)
            self.assertTrue(entered.wait(5))
            closer = threading.Thread(target=self.svc.close)
            closer.start()
            self.wait_for(self.svc._stop.is_set)
            release.set()
            closer.join(10)
            self.assertFalse(closer.is_alive())
        self.assertNotIn(self.keys["beta"], calls)
        rows = self.rows()
        self.assertEqual([(row["project"], row["cause"]) for row in rows],
                         [("alpha", "console-start")])
        self.assertNotIn("console: trust_grant_skipped closing", errors.getvalue())

    def test_without_trust_at_start_nothing_is_granted(self):
        self.seed()
        before = {name: path.read_bytes() for name, path in self.files.items()}
        self.begin(trust_at_start=False)
        self.svc.poll_sessions()
        self.assertEqual([t.name for t in threading.enumerate()
                          if t.name == service.TRUST_START_THREAD], [])
        self.assertEqual(self.rows(), [])
        self.assertEqual({name: path.read_bytes() for name, path in self.files.items()}, before)

    def test_an_unreadable_registry_grants_nothing_and_says_so(self):
        self.seed()
        self.registry.write_text("{")
        before = {name: path.read_bytes() for name, path in self.files.items()}
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.begin()
            self.wait_for(lambda: "console: trust_start_registry_unreadable" in errors.getvalue())
        self.assertEqual(self.rows(), [])
        self.assertEqual({name: path.read_bytes() for name, path in self.files.items()}, before)

    def test_the_console_starts_the_service_with_trust_at_start(self):
        given = {}

        def fake(*args, **kwargs):
            given.update(kwargs)
            raise TokenError("x")

        with mock.patch.object(console_module.service, "ConsoleService", fake), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console_module.main([]), 1)
        self.assertIs(given["trust_at_start"], True)


if __name__ == "__main__":
    unittest.main()
