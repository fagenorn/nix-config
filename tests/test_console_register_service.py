"""The console's register-project write (#1052): the guard, the refusals, the run, the view.

Each case has its own HOME, so no case shares an event log, a plan store or a registry with another.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.console import register, register_check
from agent_tools.project_contract import agent_platform

from . import accounts_sandbox
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

PATH = "/api/register-project"
ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
PLANNED = {
    "plan": {"state": "draft", "outcome": "reconcile", "project_id": None, "blockers": []},
    "decisions": {"open": [{"id": "project-id"}], "recommended": [], "answered": []},
    "changes": [{"op": "git-mv", "sources": [".claude/specs/a.md"], "targets": [".agents/x"]}],
    "link_rewrites": {"inbound": {"links": 0, "files": []}, "outbound": {"links": 0, "files": []},
                      "unrewritable": [], "already_broken": 0},
    "path_references": [],
    "handoff": {"next_command": None},
}
NO_CHANGE = {**PLANNED, "plan": {"state": "ready", "outcome": "no_change", "project_id": "o/r",
                                 "blockers": []}, "changes": [], "decisions": {"open": []}}


def git(path, *arguments):
    done = subprocess.run(
        ["git", "-C", str(path), *arguments], env=GIT_ENV, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    return done.stdout


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "t")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("# x\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "one")
    return path.resolve()


def reconcile_repository(parent: Path) -> Path:
    root = git_repo(parent / "reconcile")
    for name, text in ((".claude/specs/a.md", "# spec a\n"), (".claude/plans/b.md", "# plan b\n")):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "legacy")
    bare = parent / "origin.git"
    git(parent, "init", "-q", "--bare", "-b", "main", str(bare))
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "main")
    return root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def home_state(home: Path) -> tuple:
    registry = home / ".agents/state/fleet/registry.json"
    adopt = home / ".agents/state/adopt"
    files = None
    if adopt.is_dir():
        files = sorted((str(path.relative_to(adopt)), digest(path))
                       for path in adopt.rglob("*") if path.is_file())
    return (digest(registry) if registry.is_file() else None, files)


def real_home_state() -> tuple:
    return home_state(Path(pwd.getpwuid(os.getuid()).pw_dir))


class Fake:
    def __init__(self, plan=None, report=None, block=None, raises=None):
        self.document = plan
        self.report = report
        self.block = block
        self.raises = raises
        self.calls = []

    def _run(self, verb, root, cancel):
        self.calls.append((verb, root))
        if self.block is not None:
            self.block.wait(30)
        if self.raises is not None:
            raise self.raises

    def plan(self, root, cancel=None):
        self._run("plan", root, cancel)
        return self.document

    def register(self, root, cancel=None):
        self._run("register", root, cancel)
        return self.report


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
        self.store = self.home / ".agents/state/console/events.sqlite3"
        self.token_file = self.store.with_name("page-token")
        self.registry = agent_platform.registry_path()
        support.write_registry(self.registry, [])
        self.parent = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.parent, True)

    def begin(self, adopter, **kwargs):
        self.svc = support.service(self, self.store, self.registry, adopter=adopter, **kwargs)
        return self.svc

    def own(self, **headers):
        return {"Origin": f"http://127.0.0.1:{self.svc.address[1]}",
                "X-Console-Token": self.token_file.read_text().strip(), **headers}

    def post(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, PATH, sent, payload)

    def rows(self, kind):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == kind]

    def view(self):
        return json.loads(self.svc.view_bytes)

    def wait_done(self, root, bound=120):
        end = time.monotonic() + bound
        while time.monotonic() < end:
            found = self.view()["registration"]
            if found is not None and found["root"] == str(root) and found["status"] == "done":
                return found
            time.sleep(0.1)
        self.fail("no registration result")


class RegisterGuardTest(Case):
    def test_the_write_is_refused_without_the_token_or_from_another_origin_and_runs_nothing(self):
        fake = Fake(plan=PLANNED)
        svc = self.begin(fake)
        repo = git_repo(self.parent / "r")
        json_type = {"Content-Type": "application/json"}
        own = f"http://127.0.0.1:{svc.address[1]}"
        token = self.token_file.read_text().strip()
        before = support.log_rows(self.store)
        version = svc.version
        for headers, text in (
                ({"Origin": own, **json_type}, b"token refused\n"),
                ({"Origin": "http://evil.test", "X-Console-Token": token, **json_type},
                 b"origin refused\n"),
                ({"X-Console-Token": token, **json_type}, b"origin refused\n")):
            with self.subTest(text=text):
                status, _, body = self.post({"path": str(repo)}, headers=headers)
                self.assertEqual((status, body), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(svc.version, version)
        self.assertEqual(fake.calls, [])

    def test_bodies_are_refused_as_bad_registration(self):
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        before = support.log_rows(self.store)
        for raw in (b"[]", b'{"path": 1}', b'{"path": "/a", "x": 1}'):
            with self.subTest(raw=raw):
                status, _, body = self.post(raw=raw)
                self.assertEqual((status, body), (400, b"bad registration\n"))
        status, _, body = self.post(raw=b'{"path": "' + b"a" * 4090 + b'"}')
        self.assertEqual((status, body), (413, b"too large\n"))
        status, _, body = self.post(raw=b'{"path": "/a"}',
                                    headers=self.own(**{"Content-Type": "text/plain"}))
        self.assertEqual((status, body), (415, b"json only\n"))
        self.assertEqual(fake.calls, [])
        self.assertEqual(support.log_rows(self.store), before)


class RegisterRefusalTest(Case):
    def refused(self, path):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, body = self.post({"path": path})
        return status, body.decode(), errors.getvalue()

    def test_a_path_that_is_not_the_top_of_a_checkout_is_refused_and_runs_nothing(self):
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        plain = self.parent / "plain"
        plain.mkdir()
        sub = git_repo(self.parent / "r") / "sub"
        sub.mkdir()
        before = support.log_rows(self.store)
        cases = [(str(plain), register.not_toplevel(str(plain))),
                 (str(sub), register.not_toplevel(str(sub))),
                 ("rel/x", register.RELATIVE),
                 (str(self.parent / "missing"), register.not_directory(str(self.parent / "missing")))]
        for path, reason in cases:
            with self.subTest(path=path):
                status, body, errors = self.refused(path)
                self.assertEqual((status, body), (409, reason + "\n"))
                self.assertIn(f"console: registration_refused {reason}", errors)
        self.assertEqual(fake.calls, [])
        self.assertEqual(support.log_rows(self.store), before)

    def test_a_registered_path_is_refused_and_runs_nothing(self):
        repo = git_repo(self.parent / "r")
        support.write_registry(self.registry, [{"project_id": "o/r", "root": str(repo)}])
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        status, _, body = self.post({"path": str(repo)})
        self.assertEqual((status, body), (409, f"{repo} is already registered as o/r\n".encode()))
        self.assertEqual(fake.calls, [])

    def test_an_unreadable_registry_refuses_and_an_absent_one_is_an_empty_fleet(self):
        repo = git_repo(self.parent / "r")
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        self.registry.write_text("{not json")
        status, _, body = self.post({"path": str(repo)})
        self.assertEqual((status, body), (409, (register.registry_unreadable() + "\n").encode()))
        self.assertEqual(fake.calls, [])
        self.registry.unlink()
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.wait_done(repo)
        self.assertEqual(fake.calls, [("plan", str(repo.resolve()))])

    def test_without_an_adopter_the_host_refuses(self):
        self.begin(None)
        status, _, body = self.post({"path": "rel"})
        self.assertEqual(
            (status, body), (409, b"registering a project is not available on this host\n"))


class RegisterRunTest(Case):
    def test_the_write_answers_while_the_plan_runs_and_the_view_says_running(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = Fake(plan=PLANNED, block=gate)
        svc = self.begin(fake, dispatch=None)
        repo = git_repo(self.parent / "r")
        status, _, body = self.post({"path": str(repo)})
        self.assertEqual((status, body), (204, b""))
        status, _, body = support.request(svc.address, "GET", "/api/state")
        self.assertEqual(status, 200)
        shown = json.loads(body)["registration"]
        self.assertEqual(shown["status"], "running")
        self.assertEqual(shown["headline"], f"Planning the adoption of {repo.name}…")
        gate.set()
        end = time.monotonic() + 5
        while time.monotonic() < end and self.view()["registration"]["status"] != "done":
            time.sleep(0.05)
        done = self.view()["registration"]
        self.assertEqual((done["status"], done["result"]), ("done", "planned"))

    def test_a_second_registration_while_one_runs_is_refused(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = Fake(plan=PLANNED, block=gate)
        self.begin(fake, dispatch=None)
        first = git_repo(self.parent / "r")
        second = git_repo(self.parent / "r2")
        self.assertEqual(self.post({"path": str(first)})[0], 204)
        status, _, body = self.post({"path": str(second)})
        self.assertEqual(
            (status, body), (409, f"a registration is already running for {first.name}\n".encode()))
        deadline = time.monotonic() + 5
        while not fake.calls and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(fake.calls, [("plan", str(first.resolve()))])

    def test_a_dispatch_that_fails_frees_the_reservation(self):
        calls = []

        def dispatch(job):
            calls.append(job)
            if len(calls) == 1:
                raise RuntimeError("cannot start a thread")
            job()

        fake = Fake(plan=PLANNED)
        self.begin(fake, dispatch=dispatch)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 500)
        self.assertIsNone(self.view()["registration"])
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(self.wait_done(repo)["result"], "planned")

    def test_a_failed_child_is_shown_as_failed(self):
        fake = Fake(raises=register.RunFailed("timed_out"))
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        (_, row), = self.rows("registration.ended")
        self.assertEqual(row["result"], "failed")
        self.assertEqual(row["headline"],
                         f"The adoption plan for {repo.name} failed: it took too long and was stopped")
        self.assertEqual(self.view()["registration"]["status"], "done")

    def test_a_no_change_plan_runs_the_register_check(self):
        report = {"registered": True, "project_id": "o/r", "result": "adopted"}
        fake = Fake(plan=NO_CHANGE, report=report)
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(fake.calls, [("plan", str(repo)), ("register", str(repo))])
        (_, row), = self.rows("registration.ended")
        self.assertEqual(row["result"], "registered")

    def test_the_result_survives_a_restart(self):
        self.begin(Fake(plan=PLANNED))
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        first = self.view()["registration"]
        self.assertEqual(first["status"], "done")
        self.svc.close()
        again = self.begin(Fake())
        self.assertEqual(json.loads(again.view_bytes)["registration"], first)

    def test_an_unadopted_repository_shows_its_plan_and_the_real_home_is_untouched(self):
        before = real_home_state()
        repo = reconcile_repository(self.parent)
        head = git(repo, "rev-parse", "HEAD")
        self.begin(register.Adopter(), dispatch=None)
        status, _, body = self.post({"path": str(repo)})
        self.assertEqual((status, body), (204, b""))
        reg = self.wait_done(repo)
        self.assertEqual((reg["result"], reg["outcome"]), ("planned", "reconcile"))
        self.assertEqual(
            reg["headline"],
            f"What adopting {repo.name} would change: it has agent files or a contract to bring up to date")
        stored = list((self.home / ".agents/state/adopt/plans").iterdir())
        self.assertEqual(len(stored), 1)
        document = json.loads(stored[0].read_text())
        self.assertEqual(reg["lines"], register.plan_lines(document))
        self.assertTrue(reg["lines"][0].startswith("moves 2 agent file"))
        n = len(document["decisions"]["open"])
        self.assertGreaterEqual(n, 1)
        self.assertEqual(reg["note"], f"The plan has {n} open question{'s' if n != 1 else ''}.")
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(real_home_state(), before)

    def test_an_adopted_repository_is_registered_and_listed(self):
        before = real_home_state()
        root = register_check.adopted_repository(
            self.parent, "fixture/console-register", ROOT / register_check.CONTRACT_SOURCE)
        self.begin(register.Adopter(), dispatch=None)
        status, _, body = self.post({"path": str(root)})
        self.assertEqual((status, body), (204, b""))
        self.wait_done(root)
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["result"], "registered")
        self.assertEqual(row["headline"], f"{root.name} is registered as fixture/console-register.")
        self.assertEqual(json.loads(self.registry.read_text())["projects"],
                         [{"project_id": "fixture/console-register", "root": str(root)}])
        end = time.monotonic() + 10
        listed = False
        while time.monotonic() < end and not listed:
            entries = []
            for entry in self.view()["entries"]:
                entries.extend(entry["projects"] if entry["type"] == "quiet_group" else [entry])
            listed = any(entry["project_id"] == "fixture/console-register" for entry in entries)
            if not listed:
                time.sleep(0.1)
        self.assertTrue(listed)
        self.assertEqual(real_home_state(), before)


class SnapshotTest(unittest.TestCase):
    def test_the_home_snapshot_sees_a_changed_plan_and_registry(self):
        with tempfile.TemporaryDirectory() as name:
            h = Path(name)
            registry = h / ".agents/state/fleet/registry.json"
            plan = h / ".agents/state/adopt/plans/p.json"
            for path, text in ((registry, '{"projects": []}'), (plan, '{"a": 1}')):
                path.parent.mkdir(parents=True)
                path.write_text(text)
            snapshots = [home_state(h)]
            plan.write_text('{"a": 2}')
            snapshots.append(home_state(h))
            registry.write_text('{"projects": [1]}')
            snapshots.append(home_state(h))
            (plan.parent / "q.json").write_text("{}")
            snapshots.append(home_state(h))
            for before, after in zip(snapshots, snapshots[1:]):
                self.assertNotEqual(before, after)
            self.assertEqual(home_state(h), snapshots[-1])
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(home_state(Path(empty)), (None, None))


if __name__ == "__main__":
    unittest.main()
