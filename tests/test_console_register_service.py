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

from agent_tools.console import checkout_remote, event_log, folder_trust, register, register_check
from agent_tools.project_contract import agent_platform

from . import accounts_sandbox
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)

PATH = "/api/register-project"
ANSWER = "/api/plan-answer"
CONFIRM = "/api/register-confirm"
CANCEL = "/api/register-cancel"
PID_A = "sha256:" + "a" * 64
PID_B = "sha256:" + "b" * 64
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
A1 = {"id": "candidate-class", "subject": ".claude/odd.md", "value": "archive-history"}
DRAFT = {**PLANNED,
         "plan": {"state": "draft", "outcome": "reconcile", "project_id": "o/r", "blockers": [],
                  "plan_id": PID_A},
         "decisions": {"open": [{"id": "candidate-class", "subject": ".claude/odd.md",
                                 "value": "archive-history"}], "recommended": [], "answered": []}}
READY = {**DRAFT, "plan": {**DRAFT["plan"], "state": "ready", "plan_id": PID_B},
         "decisions": {"open": [], "recommended": [], "answered": [A1]}}


def git(path, *arguments):
    done = subprocess.run(
        ["git", "-C", str(path), *arguments], env=GIT_ENV, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    return done.stdout


def git_repo(path: Path, *, contract: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "t")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("# x\n")
    if contract:
        (path / ".agents").mkdir()
        (path / ".agents/project.json").write_text("{}\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "one")
    return path.resolve()


def reconcile_repository(parent: Path, *, contract: bool = False) -> Path:
    root = git_repo(parent / "reconcile", contract=contract)
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


def answer_repository(parent: Path) -> Path:
    root = register_check.adopted_repository(
        parent, "fixture/console-answer", ROOT / register_check.CONTRACT_SOURCE)
    for name, text in ((".claude/odd.md", "# odd\n"), (".claude/specs/a.md", "# a\n"),
                       ("tools/show.sh", "cat .claude/specs/a.md\n")):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "legacy")
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
    def __init__(self, plan=None, report=None, block=None, raises=None, raises_on=None,
                 register_raises=None, apply_result=None, apply_block=None, apply_raises=None,
                 discard_result=None):
        self.document = plan
        self.report = report
        self.block = block
        self.raises = raises
        self.raises_on = raises_on
        self.register_raises = register_raises
        self.apply_result = apply_result
        self.apply_block = apply_block
        self.apply_raises = apply_raises
        self.discard_result = discard_result
        self.calls = []
        self.register_operands = []
        self.answers = []
        self.contracts = []
        self.applied = []
        self.discards = []
        self.order = []

    def _run(self, verb, root, cancel):
        self.calls.append((verb, root))
        if self.block is not None:
            self.block.wait(30)
        if self.raises is not None:
            raise self.raises

    def plan(self, root, cancel=None, answers=(), contract=None):
        self.contracts.append((
            contract, contract is not None and os.path.exists(contract),
            contract is None or not Path(contract).resolve().is_relative_to(Path(root).resolve())))
        self.answers.append(list(answers))
        self.order.append(("plan", root))
        self._run("plan", root, cancel)
        if self.raises_on:
            error = self.raises_on.pop(0)
            if error is not None:
                raise error
        if isinstance(self.document, list):
            return self.document.pop(0)
        return self.document

    def register(self, root, cancel=None, **operands):
        self.register_operands.append(operands)
        self._run("register", root, cancel)
        if self.register_raises is not None:
            raise self.register_raises
        return self.report

    def apply(self, plan_id, cancel=None, acknowledge_deletions=False, discard_retained=False):
        self.applied.append((plan_id, acknowledge_deletions))
        self.discards.append(discard_retained)
        if self.apply_block is not None:
            self.apply_block.wait(30)
        if self.apply_raises is not None:
            raise self.apply_raises
        return self.apply_result

    def discard(self, plan_id, cancel=None):
        self.order.append(("discard", plan_id))
        if self.discard_result is not None:
            return self.discard_result
        return {"plan_id": plan_id, "discarded": True}


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
        allowed = os.environ.get("GIT_ALLOW_PROTOCOL")
        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        if allowed is None:
            self.addCleanup(os.environ.pop, "GIT_ALLOW_PROTOCOL", None)
        else:
            self.addCleanup(os.environ.__setitem__, "GIT_ALLOW_PROTOCOL", allowed)

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

    def answer(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, ANSWER, sent, payload)

    def confirm(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, CONFIRM, sent, payload)

    def registered(self, root):
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        return self.wait_done(root)

    def wait_for(self, predicate, bound=120):
        end = time.monotonic() + bound
        while time.monotonic() < end:
            found = self.view()["registration"]
            if found is not None and predicate(found):
                return found
            time.sleep(0.1)
        self.fail("the registration never reached the expected state")

    def rows(self, kind):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == kind]

    def view(self):
        return json.loads(self.svc.view_bytes)

    def confirm_cards(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_confirm"]

    def settled_row(self, root, bound=120):
        """The stored payload of the root's last ended registration, once the run has finished.

        It observes completion through the log and the service's run mark, not through the view,
        which a card or a registered project reduces or drops (ADR-console-035).
        """
        end = time.monotonic() + bound
        while time.monotonic() < end:
            found = [payload for _, payload in self.rows(event_log.REGISTRATION_ENDED)
                     if payload.get("root") == str(root)]
            if self.svc._registering is None and found:
                return found[-1]
            time.sleep(0.05)
        self.fail("no registration result")

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
                         f"The adoption plan for {repo.name} failed: it took too long and was stopped.")
        self.assertEqual(row["note"], register.unknown_step(repo.name, "plan"))
        self.assertEqual(self.view()["registration"]["status"], "done")

    def test_a_registration_that_raised_names_the_register_command(self):
        fake = Fake(plan=NO_CHANGE, register_raises=register.RunFailed("unreadable"))
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(self.settled_row(repo)["note"], register.CONFIRM_NOTE)
        self.assertEqual(len(self.confirm_cards()), 1)
        self.assertEqual(self.confirm({"root": str(repo), "choice": "register"})[0], 204)
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["result"], "failed")
        self.assertEqual(row["note"], register.unknown_step(repo.name, "register"))
        self.assertNotIn("plan the adoption", row["note"])

    def test_a_no_change_plan_runs_the_register_check(self):
        report = {"registered": True, "project_id": "o/r", "result": "adopted"}
        fake = Fake(plan=NO_CHANGE, report=report)
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(fake.calls, [("plan", str(repo))])
        (_, row), = self.rows("registration.ended")
        self.assertEqual(row["note"], register.CONFIRM_NOTE)
        self.assertEqual(self.confirm({"root": str(repo), "choice": "register"})[0], 204)
        self.assertEqual(fake.calls, [("plan", str(repo)), ("plan", str(repo)),
                                      ("register", str(repo))])
        (_, row), = self.rows("registration.ended")[-1:]
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

    def test_an_unadopted_repository_shows_its_draft_and_the_real_home_is_untouched(self):
        before = real_home_state()
        repo = reconcile_repository(self.parent)
        head = git(repo, "rev-parse", "HEAD")
        self.begin(register.Adopter(), dispatch=None)
        status, _, body = self.post({"path": str(repo)})
        self.assertEqual((status, body), (204, b""))
        reg = self.wait_done(repo)
        self.assertEqual((reg["result"], reg["outcome"]), ("drafting", None))
        self.assertEqual(
            reg["headline"], f"What the console read from {repo.name}: it has no project contract yet")
        self.assertEqual([q["subject"] for q in reg["questions"]],
                         ["project-id", "tracker", "build-command", "test-command"])
        self.assertTrue(reg["questions"][0]["ask"].endswith(
            "Its remote does not name a project: type its id, as owner/name."))
        self.assertIn("default branch: main (read from its remote)",
                      [d["line"] for d in reg["draft"]])
        self.assertEqual(reg["note"], "The draft has 4 open questions.")
        self.assertFalse((self.home / ".agents/state/adopt/plans").exists()
                         and list((self.home / ".agents/state/adopt/plans").iterdir()))
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(real_home_state(), before)

    def test_an_adopted_repository_is_registered_and_listed(self):
        before = real_home_state()
        root = register_check.adopted_repository(
            self.parent, "fixture/console-register", ROOT / register_check.CONTRACT_SOURCE)
        work = self.parent / "accounts" / "profiles" / "work"
        work.mkdir(parents=True)
        (work / ".claude.json").write_text(json.dumps({"oauthAccount": {"a": 1}}), "utf-8")
        self.begin(register.Adopter(), dispatch=None, profile_dirs=[work], trust_home=self.home)
        status, _, body = self.post({"path": str(root)})
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.settled_row(root)["note"], register.CONFIRM_NOTE)
        self.assertEqual(len(self.confirm_cards()), 1)
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        status, _, body = self.confirm({"root": str(root), "choice": "register"})
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.settled_row(root)["result"], "registered")
        self.assertIsNone(self.view()["registration"])
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
        (_, grant), = self.rows("trust.granted")
        self.assertEqual((grant["cause"], [p["profile"] for p in grant["profiles"]]),
                         ("register", ["default", "work"]))
        for path in (self.home / ".claude.json", work / ".claude.json"):
            document = json.loads(path.read_text("utf-8"))
            self.assertIs(document["projects"][os.path.realpath(root)]["hasTrustDialogAccepted"],
                          True)
        self.assertEqual(json.loads((work / ".claude.json").read_text("utf-8"))["oauthAccount"],
                         {"a": 1})
        self.assertEqual(real_home_state(), before)


class RegisterTrustTest(Case):
    """An adopted repository waits for its Register card; only its approval grants and registers (#1078)."""

    def setUp(self):
        super().setUp()
        self.files = {"default": self.home / ".claude.json"}
        profiles = []
        for name in ("work", "solo"):
            directory = self.parent / "accounts" / "profiles" / name
            directory.mkdir(parents=True)
            profiles.append(directory)
            self.files[name] = directory / ".claude.json"
        for path in self.files.values():
            path.write_text(json.dumps({"oauthAccount": {"a": 1}}), "utf-8")
        self.profiles = profiles
        self.fake = Fake(plan=NO_CHANGE, report={"registered": True, "project_id": "o/r"})
        self.repo = git_repo(self.parent / "r")
        self.begin(self.fake)

    def begin(self, adopter, **kwargs):
        return super().begin(adopter, profile_dirs=self.profiles, trust_home=self.home, **kwargs)

    def contents(self):
        return {name: path.read_bytes() for name, path in self.files.items()}

    def waiting(self):
        self.assertEqual(self.post({"path": str(self.repo)})[0], 204)
        return self.wait_done(self.repo)

    def card(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_confirm"]

    def test_no_trust_is_written_before_the_register_card_is_answered(self):
        before = self.contents()
        self.waiting()
        row = self.settled_row(self.repo)
        self.assertEqual((row["result"], row["note"]), ("not_registered", register.CONFIRM_NOTE))
        self.assertEqual(self.fake.calls, [("plan", str(self.repo))])
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.rows("trust.granted"), [])
        self.assertEqual(len(self.card()), 1)

    def test_register_it_grants_then_registers(self):
        self.waiting()
        self.assertEqual(self.confirm({"root": str(self.repo), "choice": "register"})[0], 204)
        (_, grant), = self.rows("trust.granted")
        self.assertEqual(grant["cause"], "register")
        key = os.path.realpath(self.repo)
        for name, path in self.files.items():
            with self.subTest(file=name):
                document = json.loads(path.read_text("utf-8"))
                self.assertIs(document["projects"][key]["hasTrustDialogAccepted"], True)
        self.assertEqual([c for c in self.fake.calls if c[0] == "register"],
                         [("register", str(self.repo))])
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["result"], "registered")

    def test_register_it_after_an_answer_run_plans_with_the_answers_and_registers(self):
        nothing = {**NO_CHANGE, "decisions": {"open": [], "recommended": [], "answered": [A1]}}

        class Answered(Fake):
            def plan(self, root, cancel=None, answers=(), contract=None):
                super().plan(root, cancel, answers, contract)
                return nothing if answers else DRAFT

        self.svc.close()
        fake = Answered(report={"registered": True, "project_id": "o/r"})
        self.begin(fake)
        self.assertEqual(self.post({"path": str(self.repo)})[0], 204)
        self.wait_done(self.repo)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        self.wait_for(lambda r: r["status"] == "done" and r["outcome"] == "no_change")
        self.assertEqual(self.settled_row(self.repo)["note"], register.CONFIRM_NOTE)
        self.assertEqual(len(self.card()), 1)
        self.assertEqual(self.confirm({"root": str(self.repo), "choice": "register"})[0], 204)
        self.assertEqual(fake.answers, [[], [A1], [A1]])
        self.assertEqual([c for c in fake.calls if c[0] == "register"],
                         [("register", str(self.repo))])
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["result"], "registered")

    def test_not_now_writes_no_trust_and_removes_the_card(self):
        self.waiting()
        before = self.contents()
        counted = self.view()["statement"]["inbox_items"]
        self.assertEqual(len(self.card()), 1)
        self.assertEqual(self.confirm({"root": str(self.repo), "choice": "not_now"})[0], 204)
        self.assertEqual(self.card(), [])
        self.assertEqual(self.view()["statement"]["inbox_items"], counted - 1)
        (_, row), = self.rows("registration.ended")[-1:]
        self.assertEqual(row["note"], "Not registered. Press Register again to register it.")
        self.assertEqual([c for c in self.fake.calls if c[0] == "register"], [])
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.rows("trust.granted"), [])
        self.svc.close()
        self.begin(Fake())
        self.assertEqual(self.card(), [])

    def test_a_confirm_for_another_root_or_a_row_not_waiting_is_refused(self):
        self.waiting()
        before, rows = self.contents(), len(support.log_rows(self.store))
        status, _, body = self.confirm({"root": str(self.parent / "other"), "choice": "register"})
        self.assertEqual((status, body), (409, b"that project is not waiting to be registered\n"))
        self.assertEqual((self.contents(), len(support.log_rows(self.store))), (before, rows))
        self.assertEqual(self.confirm({"root": str(self.repo), "choice": "not_now"})[0], 204)
        rows = len(support.log_rows(self.store))
        status, _, body = self.confirm({"root": str(self.repo), "choice": "register"})
        self.assertEqual((status, body), (409, b"that project is not waiting to be registered\n"))
        self.assertEqual((self.contents(), len(support.log_rows(self.store))), (before, rows))
        self.assertEqual([c for c in self.fake.calls if c[0] == "register"], [])
        for bad in ({"root": "/r"}, {"root": "/r", "choice": "maybe"}):
            status, _, body = self.confirm(bad)
            self.assertEqual((status, body), (400, b"bad registration approval\n"))
        status, _, body = self.confirm(
            {"root": str(self.repo), "choice": "register"},
            headers={"Origin": self.own()["Origin"], "Content-Type": "application/json"})
        self.assertEqual((status, body), (403, b"token refused\n"))


def answer_of(plan_id, given):
    return {"plan_id": plan_id, **given}


def timed_out():
    try:
        raise register.RunFailed("timed_out") from TimeoutError("child ran 300 s")
    except register.RunFailed as error:
        return error


REFUSED = {"code": "adopt_failure", "repair_id": "adopt.decisions.invalid_answer",
           "violations": [{"pointer": "/decisions/answered",
                           "message": "the answer is not the one this candidate's open question "
                                      "offers"}]}
REFUSED_TEXT = ("The plan refused that answer: the answer is not the one this candidate's open "
                "question offers")


class RegisterFailureCardTest(Case):
    """A failed registration is one Try again card the service answers (#1085, ADR-console-035)."""

    FAILED = {"error": {"code": "x", "repair_id": "adopt.manifest.missing", "violations": [
        {"pointer": "", "message": "the installed platform manifest was not found"}]}}

    def failed(self):
        self.fake = Fake(plan=self.FAILED)
        self.begin(self.fake)
        repo = git_repo(self.parent / "fail-app")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        return repo, self.settled_row(repo)

    def failure_cards(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_failed"]

    def test_a_failed_plan_is_one_card_and_the_work_line_says_needs_you(self):
        repo, row = self.failed()
        self.assertEqual(row["result"], "failed")
        view = self.view()
        self.assertEqual(view["statement"]["inbox_items"], 1)
        (card,) = self.failure_cards()
        self.assertEqual([o["label"] if isinstance(o, dict) else o
                          for o in card["questions"][0]["options"]], ["Try again", "Not now"])
        self.assertEqual(view["registration"]["line"], "Register fail-app: needs you")

    def test_a_failed_plan_keeps_its_original_error_in_the_log_and_off_the_page(self):
        message = "the contract at /srv/secret/.agents/project.json hashes to sha256:" + "a" * 64
        error = {"code": "x", "repair_id": "adopt.contract.invalid",
                 "violations": [{"pointer": "", "message": message}]}
        self.fake = Fake(plan={"error": error})
        self.begin(self.fake)
        repo = git_repo(self.parent / "log-app")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.post({"path": str(repo)})[0], 204)
            row = self.settled_row(repo)
        prefix = "console: registration_error "
        found = [json.loads(line[len(prefix):]) for line in errors.getvalue().splitlines()
                 if line.startswith(prefix)]
        self.assertEqual(found, [{"root": str(repo), "verb": "plan", "error": error}])
        self.assertNotIn("/srv/secret", row["headline"])
        self.assertNotIn("sha256:", row["headline"])

    def test_try_again_plans_again_and_not_now_removes_the_card(self):
        repo, _ = self.failed()
        before = len(self.rows(event_log.REGISTRATION_ENDED))
        self.assertEqual(self.confirm({"root": str(repo), "choice": "try_again"})[0], 204)
        self.settled_row(repo)
        self.assertEqual([c[0] for c in self.fake.calls], ["plan", "plan"])
        self.assertEqual(len(self.rows(event_log.REGISTRATION_ENDED)), before + 1)
        self.assertEqual(self.confirm({"root": str(repo), "choice": "not_now"})[0], 204)
        self.assertEqual(self.failure_cards(), [])
        self.assertEqual(self.view()["inbox"]["open"], [])
        self.assertEqual(self.rows(event_log.REGISTRATION_ENDED)[-1][1]["note"],
                         register.LATER_NOTE)
        self.assertEqual([c[0] for c in self.fake.calls], ["plan", "plan"])

    def test_a_try_again_for_a_row_that_did_not_fail_is_refused(self):
        self.fake = Fake(plan=NO_CHANGE, report={"registered": True, "project_id": "o/r"})
        self.begin(self.fake)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(self.settled_row(repo)["note"], register.CONFIRM_NOTE)
        calls = list(self.fake.calls)
        status, _, body = self.confirm({"root": str(repo), "choice": "try_again"})
        self.assertEqual((status, body), (409, (register.NOT_WAITING + "\n").encode()))
        self.assertEqual(self.fake.calls, calls)


class CancelChecks:
    """What every Cancel registration test checks (#1088); mixed into a `Case`."""

    def arrange_profiles(self):
        """Sandboxed profile files, as `TrustGrantTest` arranges them, and the service's trust kwargs."""
        self.key = str(self.parent / "reconcile")
        arranged = {"oauthAccount": {"emailAddress": "o@example.test"}, "keep": [1, 2],
                    "projects": {self.key: {"allowedTools": ["Bash"]}}}
        self.files = {"default": self.home / ".claude.json"}
        for name in ("work", "solo"):
            directory = self.parent / "accounts" / "profiles" / name
            directory.mkdir(parents=True)
            self.files[name] = directory / ".claude.json"
        for path in self.files.values():
            path.write_text(json.dumps(arranged), "utf-8")
        self.trust = {"profile_dirs": [self.files[n].parent for n in ("work", "solo")],
                      "trust_home": self.home}

    def cancel(self, body=None, headers=None, raw=None):
        payload = json.dumps(body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, CANCEL, sent, payload)

    def refused_cancel(self, body, text):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, answer = self.cancel(body)
        self.assertEqual((status, answer), (409, text.encode() + b"\n"))
        self.assertIn(f"console: register_cancel_refused {text}", errors.getvalue())

    def inbox_of(self, root):
        return [i for i in self.view()["inbox"]["open"] if i.get("root") == str(root)]

    def captured(self, repo):
        files = {str(path.relative_to(repo)): digest(path) for path in sorted(repo.rglob("*"))
                 if path.is_file() and ".git" not in path.relative_to(repo).parts}
        return {
            "status": git(repo, "status", "--porcelain"), "files": files,
            "refs": git(repo, "for-each-ref"), "worktrees": git(repo, "worktree", "list"),
            "home": home_state(self.home), "real": real_home_state(),
            "calls": list(self.fake.calls),
            "order": [step for step in self.fake.order if step[0] != "discard"],
            "trust_rows": len(self.rows("trust.granted")),
            "profiles": {name: (path.read_bytes(), path.stat().st_mtime_ns)
                         for name, path in self.files.items()}}

    def assert_cancelled(self, repo):
        plan_id = self.view()["registration"]["plan_id"]
        before = self.captured(repo)
        self.assertEqual(self.cancel({"root": str(repo)})[::2], (204, b""))
        self.assertIsNone(self.view()["registration"])
        self.assertEqual(self.inbox_of(repo), [])
        (found,) = self.rows("registration.cancelled")
        self.assertEqual(found[1], {"by": "owner", "root": str(repo), "plan_id": plan_id})
        self.assertEqual(found[0], support.log_rows(self.store)[-1][0])
        self.assertEqual(self.captured(repo), before)


class RegisterCancelTest(CancelChecks, Case):
    """Cancel registration of a plan or a failure that was never applied (#1088, ADR-console-037)."""

    FAILED = RegisterFailureCardTest.FAILED

    def setUp(self):
        super().setUp()
        self.arrange_profiles()
        self.fake = None

    def start(self, fake, **kwargs):
        self.fake = fake
        self.kwargs = {**self.trust, **kwargs}
        return self.begin(fake, **self.kwargs)

    def test_cancel_with_plan_questions_open(self):
        self.start(Fake(plan=DRAFT))
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.assertEqual(len(self.inbox_of(repo)), 1)
        self.assert_cancelled(repo)

    def test_cancel_with_contract_questions_open(self):
        self.start(Fake(plan=READY), draft_reader=lambda root: READ_NO_BUILD)
        repo = git_repo(self.parent / "r", contract=False)
        shown = self.registered(repo)
        self.assertEqual(shown["result"], "drafting")
        self.assertTrue(self.inbox_of(repo))
        self.assert_cancelled(repo)

    def test_cancel_a_failed_plan(self):
        self.start(Fake(plan=self.FAILED))
        repo = git_repo(self.parent / "fail-app")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.assertEqual(self.settled_row(repo)["result"], "failed")
        self.assertTrue(self.view()["registration"]["cancel"])
        self.assert_cancelled(repo)

    def test_cancel_after_not_now_on_a_failed_plan(self):
        self.start(Fake(plan=self.FAILED))
        repo = git_repo(self.parent / "fail-app")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.settled_row(repo)
        self.assertEqual(self.confirm({"root": str(repo), "choice": "not_now"})[0], 204)
        self.assertEqual(self.inbox_of(repo), [])
        self.assert_cancelled(repo)

    def test_cancel_survives_a_restart(self):
        self.start(Fake(plan=DRAFT))
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.assert_cancelled(repo)
        self.svc.close()
        self.begin(self.fake, **self.kwargs)
        self.assertIsNone(self.view()["registration"])
        self.assertEqual(self.inbox_of(repo), [])
        self.assertEqual(len(self.rows("registration.cancelled")), 1)

    def test_cancel_is_refused_while_a_run_is_under_way(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = Fake(plan=[DRAFT, READY])
        self.start(fake, dispatch=None)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        fake.block = gate
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        before = support.log_rows(self.store)
        self.refused_cancel({"root": str(repo)}, register.running(repo.name))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.rows("registration.cancelled"), [])
        gate.set()
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)

    def test_cancel_for_another_root_is_refused(self):
        self.start(Fake(plan=DRAFT))
        repo = git_repo(self.parent / "r")
        self.refused_cancel({"root": str(repo)}, register.NOT_WAITING)
        self.registered(repo)
        before = support.log_rows(self.store)
        self.refused_cancel({"root": str(self.parent / "other")}, register.NOT_WAITING)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertIsNotNone(self.view()["registration"])

    def test_cancel_clears_the_refusal_of_the_last_answer(self):
        fake = Fake(plan=[DRAFT, {"error": REFUSED}, DRAFT])
        self.start(fake)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
            self.wait_for(lambda r: r["refusal"] is not None)
        self.assert_cancelled(repo)
        self.assertIsNone(self.registered(repo)["refusal"])

    def test_a_bad_cancel_body_is_400(self):
        self.start(Fake(plan=DRAFT))
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        before = support.log_rows(self.store)
        for raw in (b"[]", b"{}", b'{"root": ""}', b'{"root": 3}', b'{"root": "/x\\ny"}',
                    json.dumps({"root": str(repo), "choice": "x"}).encode()):
            with self.subTest(raw=raw):
                status, _, body = self.cancel(raw=raw)
                self.assertEqual((status, body), (400, b"bad registration cancel\n"))
        self.assertEqual(support.log_rows(self.store), before)


class PlanAnswerGuardTest(Case):
    def test_the_write_is_refused_without_the_token_or_from_another_origin_and_runs_nothing(self):
        fake = Fake(plan=DRAFT)
        svc = self.begin(fake)
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
                status, _, body = self.answer(answer_of(PID_A, A1), headers=headers)
                self.assertEqual((status, body), (403, text))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(svc.version, version)
        self.assertEqual(fake.calls, [])

    def test_bodies_are_refused_as_bad_plan_answer(self):
        fake = Fake(plan=DRAFT)
        self.begin(fake)
        before = support.log_rows(self.store)
        good = answer_of(PID_A, A1)
        bodies = [[], {k: v for k, v in good.items() if k != "value"}, {**good, "extra": "x"},
                  {**good, "value": 1}, {**good, "subject": ""}, {**good, "subject": "a\u0007b"}]
        for body in bodies:
            with self.subTest(body=body):
                status, _, text = self.answer(body)
                self.assertEqual((status, text), (400, b"bad plan answer\n"))
        status, _, text = self.answer({**good, "value": "a" * 4100})
        self.assertEqual((status, text), (413, b"too large\n"))
        status, _, text = self.answer(
            good, headers=self.own(**{"Content-Type": "text/plain"}))
        self.assertEqual((status, text), (415, b"json only\n"))
        self.assertEqual(fake.calls, [])
        self.assertEqual(support.log_rows(self.store), before)


class PlanAnswerRefusalTest(Case):
    def refused(self, body, reason):
        before = support.log_rows(self.store)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, text = self.answer(body)
        self.assertEqual((status, text), (409, reason.encode() + b"\n"))
        self.assertIn(f"console: plan_answer_refused {reason}", errors.getvalue())
        self.assertEqual(support.log_rows(self.store), before)

    def test_without_an_adopter_the_host_refuses(self):
        fake = Fake(plan=DRAFT)
        self.begin(None)
        self.refused(answer_of(PID_A, A1),
                     "answering the adoption's questions is not available on this host")
        self.assertEqual(fake.calls, [])

    def test_with_no_plan_shown_the_answer_is_stale(self):
        fake = Fake(plan=DRAFT)
        self.begin(fake)
        self.refused(answer_of(PID_A, A1),
                     "that plan is no longer the one shown; answer the plan shown now")
        self.assertEqual(fake.calls, [])

    def test_an_answer_for_another_plan_id_is_stale(self):
        fake = Fake(plan=DRAFT)
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.refused(answer_of(PID_B, A1),
                     "that plan is no longer the one shown; answer the plan shown now")
        self.assertEqual(fake.answers, [[]])
        self.assertEqual(fake.calls, [("plan", str(repo))])

    def test_a_row_with_no_plan_id_is_stale(self):
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.refused(answer_of(PID_A, A1),
                     "that plan is no longer the one shown; answer the plan shown now")
        self.assertEqual(fake.calls, [("plan", str(repo))])

    def test_an_answer_while_a_run_is_under_way_is_refused(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = Fake(plan=DRAFT, block=gate)
        self.begin(fake, dispatch=None)
        repo = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(repo)})[0], 204)
        self.refused(answer_of(PID_A, A1), f"a registration is already running for {repo.name}")


class PlanAnswerRunTest(Case):
    def test_an_answer_reruns_the_plan_and_the_view_shows_the_new_one(self):
        fake = Fake(plan=[DRAFT, READY])
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[::2], (204, b""))
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        self.assertEqual(fake.answers, [[], [A1]])
        self.assertEqual(fake.calls, [("plan", str(repo)), ("plan", str(repo))])
        shown = self.view()["registration"]
        self.assertEqual((shown["state"], shown["questions"]), ("ready", []))
        self.assertEqual(shown["note"], "The plan is ready.")
        rows = self.rows("registration.ended")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1][1]["answered"], [A1])

    def test_answering_an_item_reruns_the_plan_and_removes_that_item(self):
        first = {"id": "candidate-class", "subject": ".claude/odd.md",
                 "value": "archive-history"}
        second = {"id": "path-reference", "subject": "tools/show.sh:1:5",
                  "answers": ["rewrite", "retain"]}
        two = {**DRAFT, "decisions": {"open": [first, second], "recommended": [],
                                      "answered": []}}
        one = {**DRAFT, "plan": {**DRAFT["plan"], "plan_id": PID_B},
               "decisions": {"open": [second], "recommended": [], "answered": [A1]}}
        fake = Fake(plan=[two, one])
        self.begin(fake)
        self.registered(git_repo(self.parent / "r"))
        shown = self.view()
        self.assertEqual([i["key"] for i in shown["inbox"]["open"]],
                         [f"register/{PID_A}/0", f"register/{PID_A}/1"])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        shown = self.view()
        self.assertEqual([i["key"] for i in shown["inbox"]["open"]], [f"register/{PID_B}/0"])
        self.assertEqual(shown["inbox"]["open"][0]["subject"], "tools/show.sh:1:5")
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(fake.answers[-1], [A1])

    def test_a_refused_answer_keeps_the_item_with_its_plain_reason(self):
        self.refused_run(Fake(plan=[DRAFT, {"error": REFUSED}]), git_repo(self.parent / "r"))
        shown = self.view()
        (entry,) = shown["inbox"]["open"]
        self.assertEqual((entry["key"], entry["refusal"]), (f"register/{PID_A}/0", REFUSED_TEXT))
        self.assertEqual(shown["statement"]["inbox_items"], 1)

    def test_every_answer_given_so_far_is_sent_again(self):
        a2 = {"id": "path-reference", "subject": "tools/show.sh:1:5", "value": "rewrite"}
        second = {**DRAFT, "plan": {**DRAFT["plan"], "plan_id": PID_B},
                  "decisions": {"open": [{"id": "path-reference", "subject": "tools/show.sh:1:5",
                                          "answers": ["rewrite", "retain"]}],
                                "recommended": [], "answered": [A1]}}
        fake = Fake(plan=[DRAFT, second, READY])
        self.begin(fake)
        repo = git_repo(self.parent / "r")
        self.registered(repo)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)
        self.assertEqual(self.answer(answer_of(PID_B, a2))[0], 204)
        self.assertEqual(fake.answers[-1], [A1, a2])

    def test_the_answer_run_shows_its_own_running_headline(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        fake = Fake(plan=[DRAFT, READY])
        self.begin(fake, dispatch=None)
        repo = git_repo(self.parent / "r")
        other = git_repo(self.parent / "r2")
        self.registered(repo)
        fake.block = gate
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        shown = self.view()["registration"]
        self.assertEqual(shown["status"], "running")
        self.assertEqual(shown["headline"],
                         f"Planning the adoption of {repo.name} again with your answer…")
        status, _, body = self.post({"path": str(other)})
        self.assertEqual(
            (status, body), (409, f"a registration is already running for {repo.name}\n".encode()))
        gate.set()
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] == PID_B)

    def refused_run(self, fake, repo):
        """Register, answer under a held stderr, and return the shown view and its stderr."""
        self.begin(fake)
        self.registered(repo)
        before = self.view()["registration"]
        count = len(self.rows("registration.ended"))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
            self.wait_for(lambda r: r["refusal"] is not None)
        self.assertEqual(len(self.rows("registration.ended")), count)
        return before, errors.getvalue()

    @staticmethod
    def records(errors):
        lines = [line for line in errors.splitlines()
                 if line.startswith("console: plan_answer_error ")]
        return [json.loads(line.partition("console: plan_answer_error ")[2]) for line in lines]

    def test_a_refused_answer_appends_nothing_and_shows_why(self):
        repo = git_repo(self.parent / "r")
        before, errors = self.refused_run(Fake(plan=[DRAFT, {"error": REFUSED}]), repo)
        self.assertEqual(self.view()["registration"], {
            **before, "refusal": REFUSED_TEXT,
            "refused": {"id": A1["id"], "subject": A1["subject"]}})
        self.assertEqual(self.records(errors), [{"root": str(repo), "error": REFUSED}])

    def test_a_refused_answer_names_its_question(self):
        repo = git_repo(self.parent / "r")
        self.refused_run(Fake(plan=[DRAFT, {"error": REFUSED}]), repo)
        shown = self.view()["registration"]
        self.assertEqual(shown["refused"], {"id": A1["id"], "subject": A1["subject"]})
        self.assertEqual(shown["refusal"], REFUSED_TEXT)

    def test_a_failed_rerun_keeps_the_plan(self):
        repo = git_repo(self.parent / "r")
        _, errors = self.refused_run(
            Fake(plan=[DRAFT, READY], raises_on=[None, timed_out()]), repo)
        self.assertEqual(self.view()["registration"]["refusal"],
                         "The plan was not made again: it took too long and was stopped")
        (record,) = self.records(errors)
        self.assertEqual((record["root"], record["failure"]), (str(repo), "timed_out"))
        self.assertIn("child ran 300 s", record["cause"])

    def test_an_error_that_is_not_a_refused_answer_shows_its_message_not_its_code(self):
        repo = git_repo(self.parent / "r")
        other = {"code": "adopt_failure", "repair_id": "adopt.some.repair",
                 "violations": [{"pointer": "/x", "message": "the store is unreadable"}]}
        self.refused_run(Fake(plan=[DRAFT, {"error": other}]), repo)
        self.assertEqual(self.view()["registration"]["refusal"],
                         "The plan was not made again: the store is unreadable")

    def test_the_next_answer_clears_the_refusal(self):
        repo = git_repo(self.parent / "r")
        unchanged = {**READY, "plan": {**READY["plan"], "plan_id": PID_A}}
        self.refused_run(Fake(plan=[DRAFT, {"error": REFUSED}, unchanged]), repo)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        shown = self.wait_for(lambda r: r["status"] == "done" and r["refusal"] is None)
        self.assertEqual((shown["plan_id"], shown["state"]), (PID_A, "ready"))
        self.assertEqual(len(self.rows("registration.ended")), 2)

    def test_an_unexpected_failure_is_logged_before_it_is_shortened(self):
        repo = git_repo(self.parent / "r")
        _, errors = self.refused_run(
            Fake(plan=[DRAFT, READY],
                 raises_on=[None, RuntimeError("store unreadable at /x")]), repo)
        self.assertEqual(self.view()["registration"]["refusal"],
                         "The plan was not made again: it stopped unexpectedly")
        self.assertEqual(self.records(errors), [
            {"root": str(repo), "exception": "RuntimeError", "detail": "store unreadable at /x"}])
        self.assertIn("Traceback (most recent call last)", errors)

    def test_an_answer_that_leaves_nothing_to_adopt_shows_the_terminal_handoff_and_registers_nothing(
            self):
        repo = git_repo(self.parent / "r")
        nothing = {**NO_CHANGE, "handoff": {
            "next_command": f"adopt-project verify --register --repo-root {repo}"}}
        fake = Fake(plan=[DRAFT, nothing], report={"registered": True, "project_id": "o/r"})
        self.begin(fake)
        self.registered(repo)
        state = home_state(self.home)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[::2], (204, b""))
        self.wait_for(lambda r: r["status"] == "done" and r["outcome"] == "no_change")
        shown = self.settled_row(repo)
        self.assertEqual((shown["result"], shown["plan_id"], shown["questions"]),
                         ("not_registered", None, []))
        self.assertEqual(shown["headline"],
                         f"{repo.name} is already adopted and is not registered yet.")
        self.assertEqual(shown["note"], "Choose Register it to register it.")
        self.assertEqual(len(self.confirm_cards()), 1)
        self.assertEqual(fake.calls, [("plan", str(repo)), ("plan", str(repo))])
        self.assertEqual(len(self.rows("registration.ended")), 2)
        self.assertEqual(home_state(self.home), state)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, _, body = self.answer(answer_of(PID_A, A1))
        self.assertEqual((status, body), (
            409, b"that plan is no longer the one shown; answer the plan shown now\n"))


class PlanAnswerRealTest(Case):
    def setUp(self):
        super().setUp()
        self.before = real_home_state()
        self.repo = answer_repository(self.parent)
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.begin(register.Adopter(), dispatch=None)
        self.addCleanup(self.untouched)

    def untouched(self):
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(real_home_state(), self.before)

    def answered(self, plan_id, question, subject, value):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(
                self.answer(answer_of(plan_id, {"id": question, "subject": subject,
                                                "value": value}))[0], 204)
            return self.wait_for(
                lambda r: r["status"] == "done"
                and (r["plan_id"] != plan_id or r["refusal"] is not None))

    def test_a_throwaway_repository_shows_one_plain_question_per_subject(self):
        reg = self.registered(self.repo)
        self.assertEqual(reg["questions"], [
            {"id": "candidate-class", "subject": ".claude/odd.md",
             "ask": "What should happen to .claude/odd.md? No rule covers this agent file.",
             "options": [{"value": "archive-history",
                          "label": "Archive it under .agents/knowledge/archive/adopted/"}],
             "recommended": None, "why": None},
            {"id": "path-reference", "subject": "tools/show.sh:1:5",
             "ask": "tools/show.sh line 1 names .claude/specs/a.md, which this plan moves. "
                    "Should it follow the move?",
             "options": [{"value": "rewrite", "label": "Change it to .agents/artifacts/specs/a.md"},
                         {"value": "retain", "label": "Leave it as it is"}],
             "recommended": None, "why": None}])
        self.assertEqual(reg["state"], "draft")
        self.assertTrue(reg["plan_id"].startswith("sha256:"))

    def test_a_throwaway_repository_asks_two_counted_register_items(self):
        self.registered(self.repo)
        shown = self.view()
        items = [i for i in shown["inbox"]["open"] if i["reason"] == "register"]
        self.assertEqual(len(items), 2)
        for entry in items:
            self.assertEqual(entry["title"], f"Register {self.repo.name}")
        self.assertEqual(
            [i["headline"] for i in items],
            ["What should happen to .claude/odd.md? No rule covers this agent file.",
             "tools/show.sh line 1 names .claude/specs/a.md, which this plan moves. "
             "Should it follow the move?"])
        self.assertEqual(items[1]["questions"][0]["options"],
                         ["Change it to .agents/artifacts/specs/a.md", "Leave it as it is"])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["headline"], "2 things need you")

    def test_answering_both_questions_on_a_throwaway_repository_makes_the_plan_ready(self):
        first = self.registered(self.repo)
        second = self.answered(first["plan_id"], "candidate-class", ".claude/odd.md",
                               "archive-history")
        self.assertEqual([q["subject"] for q in second["questions"]], ["tools/show.sh:1:5"])
        reg = self.answered(second["plan_id"], "path-reference", "tools/show.sh:1:5", "rewrite")
        self.assertEqual((reg["state"], reg["questions"]), ("ready", []))
        self.assertEqual(reg["note"], "The plan is ready.")
        stored = (self.home / ".agents/state/adopt/plans"
                  / (reg["plan_id"].partition(":")[2] + ".json"))
        document = json.loads(stored.read_text())
        self.assertEqual(document["plan"]["state"], "ready")
        self.assertEqual(
            {(a["id"], a["subject"], a["value"]) for a in document["decisions"]["answered"]},
            {("candidate-class", ".claude/odd.md", "archive-history"),
             ("path-reference", "tools/show.sh:1:5", "rewrite")})

    def test_a_refused_answer_leaves_the_stored_plan_unchanged(self):
        reg = self.registered(self.repo)
        snapshot = home_state(self.home)
        rows = self.rows("registration.ended")
        shown = self.answered(reg["plan_id"], "candidate-class", ".claude/odd.md",
                              "retain-product")
        self.assertEqual(shown["refusal"], REFUSED_TEXT)
        self.assertEqual(home_state(self.home), snapshot)
        self.assertEqual(self.rows("registration.ended"), rows)
        self.assertEqual((shown["plan_id"], shown["questions"]),
                         (reg["plan_id"], reg["questions"]))
        shown = self.answered(reg["plan_id"], "candidate-class", ".claude/none.md",
                              "archive-history")
        self.assertEqual(
            shown["refusal"],
            "The plan refused that answer: the answered subject is not an undecided candidate of "
            "this inspection")
        self.assertEqual(home_state(self.home), snapshot)


def sample_repository(parent: Path, *, remote: bool) -> Path:
    root = parent / "sample-app"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "trunk")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# sample\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    if remote:
        bare = parent / "origin.git"
        git(parent, "clone", "-q", "--bare", str(root), str(bare))
        url = "https://github.com/sample-owner/sample-app.git"
        git(root, "remote", "add", "origin", url)
        git(root, "config", f"url.{bare}.insteadOf", url)
    return root.resolve()


def checkout_state(root: Path) -> tuple:
    files = sorted(
        (str(path.relative_to(root)), digest(path)) for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts)
    return (git(root, "status", "--porcelain"), git(root, "rev-parse", "HEAD^{tree}"), files)


READ_ALL = {
    "remotes": [("origin", "https://github.com/sample-owner/sample-app.git")],
    "default_branch": "trunk", "branches": ["trunk"], "files": ["README.md", "justfile"],
    "texts": {"justfile": "build:\n\techo b\ntest:\n\techo t\n"}}
READ_NO_BUILD = {**READ_ALL, "files": ["README.md"], "texts": {}}
NO_REMOTE_ASK = ("Which project is this repository?\n"
                 "It has no remote that names it: type its id, as owner/name.")


def taken_entry(project_id, parent):
    other = Path(tempfile.mkdtemp(dir=parent)).resolve()
    return {"project_id": project_id, "root": str(other)}


class DraftCase(Case):
    def draft_answer(self, plan_id, field, value):
        status, _, body = self.answer(answer_of(
            plan_id, {"id": "contract-draft", "subject": field, "value": value}))
        return status, body.decode().strip()

    def answered_draft(self, plan_id, field, value):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.draft_answer(plan_id, field, value)[0], 204)
            return self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] != plan_id)

    def register_items(self):
        return [i for i in self.view()["inbox"]["open"] if i["reason"] == "register"]

    def refusal_of(self, plan_id, field, value):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status, text = self.draft_answer(plan_id, field, value)
        self.assertEqual(status, 409)
        return text


class DraftRealTest(DraftCase):
    def setUp(self):
        super().setUp()
        self.before = real_home_state()
        self.repo = sample_repository(self.parent, remote=True)
        self.begin(register.Adopter(), dispatch=None)
        self.addCleanup(self.untouched)

    def untouched(self):
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
        self.assertEqual(real_home_state(), self.before)

    def ready(self):
        first = self.registered(self.repo)
        second = self.answered_draft(first["plan_id"], "build-command", "none")
        return self.answered_draft(second["plan_id"], "test-command", "none")

    def test_a_repository_with_no_contract_is_drafted_from_its_remote(self):
        reg = self.registered(self.repo)
        self.assertEqual(reg["result"], "drafting")
        for line in ("project id: sample-owner/sample-app (read from its remote)",
                     "project name: sample-app (read from its remote)",
                     "default branch: trunk (read from its remote)",
                     "issue tracker: GitHub, as sample-owner/sample-app (read from its remote)"):
            self.assertIn(line, [d["line"] for d in reg["draft"]])
        items = self.register_items()
        self.assertEqual([i["subject"] for i in items], ["build-command", "test-command"])
        self.assertEqual({i["title"] for i in items}, {"Register sample-app"})
        self.assertEqual(self.view()["statement"]["inbox_items"], 2)

    def test_answering_the_cards_makes_the_plan_ready_with_the_contract_line(self):
        reg = self.ready()
        self.assertEqual((reg["state"], reg["note"]), ("ready", "The plan is ready."))
        self.assertIn("writes the project contract", reg["lines"])
        self.assertEqual(reg["questions"], [])
        self.assertEqual(reg["line"], "Register sample-app: ready to apply")
        stored = (self.home / ".agents/state/adopt/plans"
                  / (reg["plan_id"].partition(":")[2] + ".json"))
        document = json.loads(stored.read_text())
        draft = document["plan"]["contract_draft"]
        self.assertEqual(draft["project"], {"id": "sample-owner/sample-app", "name": "sample-app"})
        self.assertEqual(draft["bindings"]["vcs"]["default_branch"], "trunk")
        self.assertEqual(draft["bindings"]["tracker"]["kind"], "github")
        self.assertEqual(draft["bindings"]["tracker"]["repo_slug"], "sample-owner/sample-app")

    def test_the_checkout_is_unchanged_before_approval(self):
        before = checkout_state(self.repo)
        self.ready()
        self.assertEqual(checkout_state(self.repo), before)
        self.assertFalse((self.repo / ".agents").exists())
        drafts = self.home / ".agents/state/console/drafts"
        self.assertEqual(list(drafts.iterdir()) if drafts.is_dir() else [], [])

    def test_a_drafted_value_the_resolver_refuses_is_a_card_with_its_plain_reason(self):
        reg = self.ready()
        shown = self.answered_draft(reg["plan_id"], "docs-paths", "../outside")
        self.assertEqual(shown["result"], "drafting")
        (question,) = shown["questions"]
        self.assertEqual(question["subject"], "docs-paths")
        self.assertEqual(
            question["why"],
            "The plan refused the documentation: must be a non-empty repository-relative "
            "path with no '..' segment")
        self.assertIs(question["text"], True)
        text = json.dumps(self.view())
        for word in ("adopt.draft", "contract.paths", "unsafe_path", "/bindings"):
            self.assertNotIn(word, text)


class DraftNoRemoteTest(DraftCase):
    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, [taken_entry("someone/taken", self.parent)])
        self.repo = sample_repository(self.parent, remote=False)
        self.begin(register.Adopter(), dispatch=None)

    def test_the_project_id_card_has_a_text_field(self):
        self.registered(self.repo)
        (item,) = [i for i in self.register_items() if i["subject"] == "project-id"]
        self.assertIs(item["text"], True)
        self.assertEqual(item["questions"], [])
        self.assertEqual(item["headline"], NO_REMOTE_ASK)

    def test_a_typed_id_that_breaks_the_id_rule_is_refused_in_plain_words(self):
        reg = self.registered(self.repo)
        rows = self.rows("registration.ended")
        self.assertEqual(
            self.refusal_of(reg["plan_id"], "project-id", "not an id"),
            "a project id is two names joined by one slash, like owner/name, with no spaces")
        self.assertEqual(self.rows("registration.ended"), rows)

    def test_a_typed_id_registered_for_another_checkout_is_refused(self):
        reg = self.registered(self.repo)
        self.assertEqual(self.refusal_of(reg["plan_id"], "project-id", "someone/taken"),
                         "someone/taken is already registered for another checkout")
        shown = self.answered_draft(reg["plan_id"], "project-id", "sample-owner/sample-app")
        self.assertIn("project id: sample-owner/sample-app (set by you)",
                      [d["line"] for d in shown["draft"]])
        self.assertNotIn("project-id", [i["subject"] for i in self.register_items()])

    def test_the_id_card_keeps_its_no_remote_sentence_after_another_answer(self):
        reg = self.registered(self.repo)
        shown = self.answered_draft(reg["plan_id"], "tracker", "none")
        self.assertEqual(shown["result"], "drafting")
        (item,) = [i for i in self.register_items() if i["subject"] == "project-id"]
        self.assertEqual(item["headline"], NO_REMOTE_ASK)

    def test_an_unreadable_command_is_refused_in_plain_words(self):
        reg = self.registered(self.repo)
        rows = self.rows("registration.ended")
        for value in ('echo "unterminated', "echo trailing\\"):
            self.assertEqual(
                self.refusal_of(reg["plan_id"], "build-command", value),
                "the command could not be read: close every quote and do not end it with a "
                "backslash")
        self.assertEqual(self.rows("registration.ended"), rows)
        self.assertIn("build-command", [i["subject"] for i in self.register_items()])


class DraftRunTest(DraftCase):
    def test_a_checkout_with_a_contract_is_planned_without_a_draft(self):
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        self.registered(git_repo(self.parent / "r"))
        self.assertEqual(fake.contracts, [(None, False, True)])

    def draft_file_after(self, fake):
        self.begin(fake, draft_reader=lambda root: READ_ALL)
        self.registered(git_repo(self.parent / "r", contract=False))
        self.assertEqual(fake.contracts[0][1:], (True, True))
        self.assertFalse(os.path.exists(fake.contracts[0][0]))

    def test_the_draft_file_is_outside_the_checkout_and_removed_after_the_run(self):
        self.draft_file_after(Fake(plan=PLANNED))

    def test_the_draft_file_is_removed_after_a_run_that_raised(self):
        self.draft_file_after(Fake(raises=register.RunFailed("timed_out")))

    def test_an_answer_to_a_plan_with_no_draft_is_refused(self):
        self.begin(Fake(plan=DRAFT))
        self.registered(git_repo(self.parent / "r"))
        self.assertEqual(self.refusal_of(PID_A, "project-id", "a/b"),
                         "that plan has no drafted contract to change")

    def test_a_remote_id_registered_for_another_checkout_reopens_the_id_card(self):
        support.write_registry(
            self.registry, [taken_entry("sample-owner/sample-app", self.parent)])
        fake = Fake(plan=PLANNED)
        self.begin(fake, draft_reader=lambda root: READ_ALL)
        reg = self.registered(git_repo(self.parent / "r", contract=False))
        self.assertEqual(reg["result"], "drafting")
        (question,) = reg["questions"]
        self.assertEqual(question["subject"], "project-id")
        self.assertEqual(question["why"],
                         "sample-owner/sample-app is already registered for another checkout")
        self.assertIs(question["text"], True)
        self.assertEqual(fake.calls, [])

    def test_the_id_is_checked_again_before_the_plan_runs(self):
        fake = Fake(plan=READY)
        self.begin(fake, draft_reader=lambda root: READ_NO_BUILD)
        reg = self.registered(git_repo(self.parent / "r", contract=False))
        self.assertEqual(len(reg["questions"]), 2)
        self.assertEqual(fake.calls, [])
        support.write_registry(
            self.registry, [taken_entry("sample-owner/sample-app", self.parent)])
        reg = self.answered_draft(reg["plan_id"], "build-command", "none")
        reg = self.answered_draft(reg["plan_id"], "test-command", "none")
        self.assertEqual(reg["result"], "drafting")
        (question,) = reg["questions"]
        self.assertEqual(question["subject"], "project-id")
        self.assertEqual(question["why"],
                         "sample-owner/sample-app is already registered for another checkout")
        self.assertEqual(fake.calls, [])


def remote_checkout(parent: Path, *, contract: bool, ahead: bool,
                    ahead_contract: bool = False) -> tuple[Path, Path]:
    """A clone of a bare remote, and the seed repository that can push more to it (#1233)."""
    seed = git_repo(parent / "seed", contract=contract)
    bare = parent / "origin.git"
    git(parent, "init", "-q", "--bare", "-b", "main", str(bare))
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "origin", "main")
    checkout = parent / "checkout"
    git(parent, "clone", "-q", str(bare), str(checkout))
    git(checkout, "config", "user.name", "t")
    git(checkout, "config", "user.email", "t@example.invalid")
    git(checkout, "config", "commit.gpgsign", "false")
    if ahead:
        if ahead_contract:
            (seed / ".agents").mkdir(exist_ok=True)
            (seed / ".agents/project.json").write_text("{}\n")
        else:
            (seed / "NOTES.md").write_text("n\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "ahead")
        git(seed, "push", "-q", "origin", "main")
    return checkout.resolve(), seed


def spy(*results):
    """A reader or updater that records `(root, cancel)` and returns the next result (the last repeats)."""
    calls = []
    queue = list(results)

    def reader(root, *, cancel):
        calls.append((root, cancel))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return calls, reader


def logged(errors: io.StringIO) -> list[dict]:
    prefix = "console: registration_error "
    return [json.loads(line[len(prefix):]) for line in errors.getvalue().splitlines()
            if line.startswith(prefix)]


CURRENT_CHECKOUT = checkout_remote.Comparison("current", "main", 0, False, None)


class RegisterRemoteTest(Case):
    def behind_card(self, *, dirty=False, **begin):
        checkout, seed = remote_checkout(self.parent, contract=False, ahead=True, ahead_contract=True)
        fake = Fake(plan=PLANNED)
        reads = []
        self.begin(fake, draft_reader=lambda root: reads.append(root) or READ_ALL, **begin)
        if dirty:
            (checkout / "README.md").write_text("changed\n")
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        self.settled_row(checkout)
        return checkout, seed, fake, reads

    def missing_origin(self, *, contract=True):
        root = git_repo(self.parent / "r", contract=contract)
        git(root, "remote", "add", "origin", str(self.parent / "missing.git"))
        return root

    def test_a_checkout_behind_a_remote_with_a_contract_raises_the_behind_card_and_plans_nothing(self):
        checkout, _ = remote_checkout(self.parent, contract=False, ahead=True, ahead_contract=True)
        fake = Fake(plan=PLANNED)
        reads = []
        self.begin(fake, draft_reader=lambda root: reads.append(root) or READ_ALL)
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        row = self.settled_row(checkout)
        self.assertEqual(row["result"], "behind")
        self.assertEqual(row["headline"],
                         "checkout is 1 commit behind its remote, which already has a project contract.")
        self.assertEqual(fake.calls, [])
        self.assertEqual(reads, [])
        self.assertEqual([p["result"] for _, p in self.rows("registration.ended")], ["behind"])
        (item,) = [i for i in self.view()["inbox"]["open"] if i["reason"] == "register_behind"]
        self.assertEqual(item["values"], ["update", "not_now"])
        self.assertFalse((checkout / ".agents/project.json").exists())

    def test_update_it_moves_the_checkout_and_plans_with_the_remotes_contract(self):
        checkout, seed, fake, reads = self.behind_card()
        status, _, body = self.confirm({"root": str(checkout), "choice": "update"})
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.settled_row(checkout)["result"], "planned")
        self.assertEqual(fake.calls, [("plan", str(checkout))])
        self.assertEqual(fake.contracts, [(None, False, True)])
        self.assertEqual(reads, [])
        self.assertEqual((checkout / ".agents/project.json").read_text(), "{}\n")
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(seed, "rev-parse", "HEAD"))
        self.assertEqual(self.rows("trust.granted"), [])

    def test_not_now_sets_the_behind_card_aside_and_plans_nothing(self):
        checkout, _, fake, _ = self.behind_card()
        self.assertEqual(self.confirm({"root": str(checkout), "choice": "not_now"})[0], 204)
        row = self.rows("registration.ended")[-1][1]
        self.assertEqual((row["result"], row["note"]), ("behind", register.LATER_NOTE))
        self.assertEqual([i for i in self.view()["inbox"]["open"]
                          if i["reason"] == "register_behind"], [])
        self.assertEqual(fake.calls, [])

    def test_a_failed_update_is_a_try_again_card_and_keeps_the_checkout(self):
        checkout, _ = remote_checkout(self.parent, contract=False, ahead=True, ahead_contract=True)
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        (checkout / "README.md").write_text("changed\n")
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        self.settled_row(checkout)
        self.assertEqual(self.confirm({"root": str(checkout), "choice": "update"})[0], 204)
        row = self.settled_row(checkout)
        self.assertEqual(row["result"], "failed")
        self.assertEqual(row["headline"],
                         "checkout could not be updated: it has changes that are not committed.")
        self.assertEqual(row["note"], "Update the checkout in a terminal, then choose Try again.")
        self.assertEqual(len([i for i in self.view()["inbox"]["open"]
                              if i["reason"] == "register_failed"]), 1)
        self.assertEqual(fake.calls, [])
        self.assertEqual((checkout / "README.md").read_text(), "changed\n")

    def test_a_current_checkout_plans_as_today(self):
        checkout, _ = remote_checkout(self.parent, contract=True, ahead=False)
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        row = self.settled_row(checkout)
        self.assertEqual(row["result"], "planned")
        self.assertNotIn("remote", row)
        self.assertEqual(fake.calls, [("plan", str(checkout))])
        self.assertIsNone(self.view()["registration"]["remote"])

    def test_an_unreadable_remote_plans_as_today_and_says_so(self):
        root = self.missing_origin()
        fake = Fake(plan=PLANNED)
        self.begin(fake)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        row = self.settled_row(root)
        self.assertEqual(row["result"], "planned")
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)
        self.assertEqual(row["lines"], register.plan_lines(PLANNED))
        self.assertEqual(fake.calls, [("plan", str(root))])
        self.assertEqual(self.view()["registration"]["remote"], register.REMOTE_UNREAD)

    def test_an_unreadable_remote_on_a_checkout_with_no_contract_drafts_and_says_so(self):
        root = self.missing_origin(contract=False)
        self.begin(Fake(plan=PLANNED), draft_reader=lambda root: READ_NO_BUILD)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        row = self.settled_row(root)
        self.assertEqual(row["result"], "drafting")
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)

    def test_a_plan_answer_keeps_the_unreadable_remote_sentence(self):
        root = self.missing_origin()
        self.begin(Fake(plan=[DRAFT, READY]))
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        first = self.settled_row(root)
        self.assertEqual(first["remote"], register.REMOTE_UNREAD)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        row = self.settled_row(root)
        self.assertEqual((row["result"], row["plan_id"]), ("planned", PID_B))
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)
        self.assertEqual(self.view()["registration"]["remote"], register.REMOTE_UNREAD)

    def test_a_draft_answer_keeps_the_unreadable_remote_sentence(self):
        root = self.missing_origin(contract=False)
        self.begin(Fake(plan=PLANNED), draft_reader=lambda root: READ_NO_BUILD)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        first = self.settled_row(root)
        self.assertEqual(first["remote"], register.REMOTE_UNREAD)
        status, _, _ = self.answer(answer_of(
            first["plan_id"], {"id": "contract-draft", "subject": "build-command", "value": "none"}))
        self.assertEqual(status, 204)
        row = self.settled_row(root)
        self.assertEqual(row["result"], "drafting")
        self.assertNotEqual(row["questions"], first["questions"])
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)
        self.assertEqual(self.view()["registration"]["remote"], register.REMOTE_UNREAD)

    def test_a_confirmed_register_keeps_the_unreadable_remote_sentence(self):
        root = self.missing_origin()
        fake = Fake(plan=NO_CHANGE, report={"registered": True, "project_id": "o/r"})
        self.begin(fake)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        self.assertEqual(self.settled_row(root)["remote"], register.REMOTE_UNREAD)
        self.assertEqual(self.confirm({"root": str(root), "choice": "register"})[0], 204)
        row = self.settled_row(root)
        self.assertEqual(row["result"], "registered")
        self.assertEqual(row["remote"], register.REMOTE_UNREAD)
        self.assertEqual(self.view()["registration"]["remote"], register.REMOTE_UNREAD)

    def test_a_confirmed_register_after_a_readable_remote_carries_no_sentence(self):
        checkout, _ = remote_checkout(self.parent, contract=True, ahead=False)
        fake = Fake(plan=NO_CHANGE, report={"registered": True, "project_id": "o/r"})
        self.begin(fake)
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        self.settled_row(checkout)
        self.assertEqual(self.confirm({"root": str(checkout), "choice": "register"})[0], 204)
        row = self.settled_row(checkout)
        self.assertEqual(row["result"], "registered")
        self.assertNotIn("remote", row)
        self.assertIsNone(self.view()["registration"]["remote"])

    def test_an_answer_after_a_readable_remote_carries_no_sentence(self):
        checkout, _ = remote_checkout(self.parent, contract=True, ahead=False)
        self.begin(Fake(plan=[DRAFT, READY]))
        self.assertEqual(self.post({"path": str(checkout)})[0], 204)
        self.settled_row(checkout)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        row = self.settled_row(checkout)
        self.assertEqual(row["plan_id"], PID_B)
        self.assertNotIn("remote", row)
        self.assertIsNone(self.view()["registration"]["remote"])

    def test_a_confirmed_register_and_an_answer_do_not_compare_again(self):
        calls, reader = spy(CURRENT_CHECKOUT)
        fake = Fake(plan=NO_CHANGE, report={"registered": True, "project_id": "o/r"})
        self.begin(fake, checkout_reader=reader)
        root = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        self.settled_row(root)
        self.assertEqual(self.confirm({"root": str(root), "choice": "register"})[0], 204)
        self.settled_row(root)
        self.assertEqual([called for called, _ in calls], [str(root)])
        self.assertIs(calls[0][1], self.svc._stop)
        self.svc.close()
        self.begin(Fake(plan=[DRAFT, READY]), checkout_reader=reader)
        again = git_repo(self.parent / "again")
        before = len(calls)
        self.assertEqual(self.post({"path": str(again)})[0], 204)
        self.settled_row(again)
        self.assertEqual(self.answer(answer_of(PID_A, A1))[0], 204)
        self.settled_row(again)
        self.assertEqual(len(calls) - before, 1)

    def test_try_again_compares_again(self):
        calls, reader = spy(CURRENT_CHECKOUT)
        error = {"code": "x", "repair_id": "adopt.git.fetch_failed",
                 "violations": [{"pointer": "", "message": "m"}]}
        self.begin(Fake(plan={"error": error}), checkout_reader=reader)
        root = git_repo(self.parent / "r")
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        self.assertEqual(self.settled_row(root)["result"], "failed")
        self.assertEqual(self.confirm({"root": str(root), "choice": "try_again"})[0], 204)
        self.settled_row(root)
        self.assertEqual([called for called, _ in calls], [str(root), str(root)])

    def test_an_unreadable_remote_is_logged_with_gits_words(self):
        root = self.missing_origin()
        self.begin(Fake(plan=PLANNED))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.post({"path": str(root)})[0], 204)
            row = self.settled_row(root)
        (entry,) = logged(errors)
        self.assertEqual((entry["root"], entry["verb"], entry["step"]),
                         (str(root), "compare", "ls-remote"))
        self.assertTrue(entry["detail"].startswith("exit "))
        self.assertIn("missing.git", entry["detail"])
        for member in (row["headline"], row["remote"]):
            self.assertNotIn("missing.git", member)
            self.assertNotIn("/", member)

    def test_a_failed_update_logs_the_step_and_gits_words(self):
        _, reader = spy(checkout_remote.Comparison("behind", "main", 1, True, None))
        failure = checkout_remote.Failure(
            "merge", "exit 128: error: The following untracked working tree files would be "
                     "overwritten by merge")
        _, updater = spy(checkout_remote.Updated(checkout_remote.NOT_MOVED, failure))
        root = git_repo(self.parent / "r", contract=False)
        self.begin(Fake(plan=PLANNED), checkout_reader=reader, checkout_updater=updater)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        self.settled_row(root)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.confirm({"root": str(root), "choice": "update"})[0], 204)
            self.settled_row(root)
        self.assertEqual(logged(errors), [{"root": str(root), "verb": "update", "step": "merge",
                                           "detail": failure.detail}])
        row = self.rows("registration.ended")[-1][1]
        self.assertEqual(row["headline"], "r could not be updated: git could not move it forward.")
        self.assertNotIn("untracked", row["headline"])
        self.assertNotIn("untracked", row["note"])

    def test_a_shutdown_during_the_update_starts_nothing_after_it(self):
        reads, reader = spy(checkout_remote.Comparison("behind", "main", 1, True, None))
        seen = []

        def updater(root, *, cancel):
            seen.append(cancel)
            cancel.set()
            return checkout_remote.Updated(None, None)

        fake = Fake(plan=PLANNED)
        draws = []
        self.begin(fake, checkout_reader=reader, checkout_updater=updater,
                   draft_reader=lambda root: draws.append(root) or READ_ALL)
        root = git_repo(self.parent / "r", contract=False)
        self.assertEqual(self.post({"path": str(root)})[0], 204)
        self.settled_row(root)
        self.assertEqual(self.confirm({"root": str(root), "choice": "update"})[0], 204)
        deadline = time.monotonic() + 30
        while self.svc._registering is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(seen, [self.svc._stop])
        self.assertEqual(len(reads), 1)
        self.assertEqual(fake.calls, [])
        self.assertEqual(draws, [])
        self.assertEqual([p["result"] for _, p in self.rows("registration.ended")
                          if p["result"] in ("planned", "drafting")], [])


class PlanAnswerSecretTest(Case):
    def test_a_secret_shaped_file_says_why_it_cannot_be_answered_here(self):
        before = real_home_state()
        root = register_check.adopted_repository(
            self.parent, "fixture/console-answer", ROOT / register_check.CONTRACT_SOURCE)
        (root / ".claude/secrets").mkdir(parents=True)
        (root / ".claude/secrets/key.md").write_text("# key\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "secret")
        self.begin(register.Adopter(), dispatch=None)
        reg = self.registered(root)
        (question,) = [q for q in reg["questions"] if q["subject"] == ".claude/secrets/key.md"]
        self.assertEqual(question["options"], [])
        self.assertEqual(
            question["why"],
            ".claude/secrets/key.md looks like a secret, so it cannot be answered here: remove it "
            "from the repository in its own commit, then register the repository again.")
        self.assertEqual(reg["state"], "draft")
        self.assertEqual(json.loads(self.registry.read_text())["projects"], [])
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
