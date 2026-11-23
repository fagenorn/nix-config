"""The host check that a drafted registration ends on schema 3 and resolves.

Each case has its own HOME, so no case shares a registry, a plan store or an installed revision
with another. The console and the resolver are injected; the fixture is built for real.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from agent_tools.console import contract_draft as cd
from agent_tools.console import draft_register_check, register
from agent_tools.project_contract import agent_platform, derived_values, resolve_project

from . import accounts_sandbox
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # one case builds a real git repository and resolves it
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "home" / "common" / "agent-skills" / "platform-manifest.json"
T = "2026-11-19T17:00:00+00:00"
REVISION = {"type": "github", "owner": "fixture", "repo": "platform", "rev": "0f" * 20,
            "narHash": "sha256-" + "A" * 43 + "=", "lastModified": 1700000000}
PLAN_ID = "sha256:" + "c" * 64
DRAFT = {"schema_version": 3,
         "bindings": {"vcs": {"integration_branch": "main"},
                      "commands": {"lint": {"argv": ["just", "lint"]},
                                   "test": {"argv": ["just", "test"]}}},
         "capabilities": {"tracker": {"support": "supported"}},
         "projections": [], "release": "unsupported"}
ENTRY = {"id": "conformance.workflow", "kind": "conformance_workflow",
         "target": ".github/workflows/conformance.yaml"}
OWNER_ROW = {"root": "/elsewhere/r", "status": "done", "result": "failed",
             "note": register.LATER_NOTE, "at": T}


def written(draft: dict) -> bytes:
    """The bytes adoption writes for a drafted contract: the conformance entry appended."""
    document = {**draft, "projections": [*draft["projections"], ENTRY]}
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def view(registration) -> tuple:
    return 200, json.dumps({"registration": registration, "entries": []}).encode()


class Case(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(dir=accounts_sandbox.root())).resolve()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(self.home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)
        self.addCleanup(shutil.rmtree, self.home, True)
        share = self.home / ".agents" / "share"
        share.mkdir(parents=True)
        shutil.copy(MANIFEST, share / "platform-manifest.json")
        self.tmp_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_root, True)
        self.store = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.store, True)
        patched = unittest.mock.patch.object(derived_values, "STORE_DIR", str(self.store))
        patched.start()
        self.addCleanup(patched.stop)
        self.install_revision()
        self.token()

    def install_revision(self, record: dict | None = REVISION, *, source: bool = True) -> None:
        target = self.home / ".agents" / "share" / "platform-revision.json"
        target.unlink(missing_ok=True)
        if record is None:
            return
        target.write_text(json.dumps({"schema_version": 1, **record}), encoding="utf-8")
        tree = Path(derived_values.store_path(record["narHash"], str(self.store)))
        shutil.rmtree(tree, ignore_errors=True)
        if source:
            manifest = tree / derived_values.TREE_MANIFEST
            manifest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(MANIFEST, manifest)

    def token(self) -> None:
        path = agent_platform.state_root() / "console" / "page-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("t" * 43 + "\n")

    def run_check(self, argv=(), **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = draft_register_check.main(list(argv), tmp_root=self.tmp_root, **kwargs)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])


class Console:
    """A fake console: the owner's row, then the posted root's done row, then the owner's row again."""

    def __init__(self, case: Case, row: dict, *, plan: dict | None = None,
                 owner_returns: bool = True):
        self.case, self.row, self.plan, self.owner_returns = case, row, plan, owner_returns
        self.phase = "before"
        self.root = None
        self.posts: list[tuple[str, dict]] = []

    def fetch(self, url):
        if self.phase == "before":
            return view(OWNER_ROW)
        if self.phase == "posted":
            return view({"root": self.root, "status": "done", "cancel": True, "at": T, **self.row})
        return view(OWNER_ROW if self.owner_returns else None)

    def post(self, url, headers, body):
        document = json.loads(body)
        self.posts.append((url.rsplit("/", 1)[1], document))
        if url.endswith("/api/register-project"):
            self.root = document["path"]
            self.phase = "posted"
            if self.plan is not None:
                path = agent_platform.state_root() / "adopt" / "plans" / (PLAN_ID.split(":")[1] + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({**self.plan, "handoff": {"repo_root": self.root}}))
        elif url.endswith("/api/register-cancel"):
            self.phase = "cancelled"
        return 204, b""


def stored(draft: dict, *, after: bytes | None = None) -> dict:
    after = written(draft) if after is None else after
    return {"plan": {"contract_draft": draft},
            "changes": [{"op": "write-file", "sources": [".agents/project.json"],
                         "targets": [".agents/project.json"], "before": None,
                         "after": "sha256:" + hashlib.sha256(after).hexdigest()}]}


QUICK = {"poll": 0.02, "settle": 1, "shown": 1}  # a removed check fails fast instead of waiting out the defaults
READY = {"state": "ready", "plan_id": PLAN_ID, "headline": "What adopting r would change."}


class RegisterDraftCheckTest(Case):
    def exercise(self, console: Console, resolver=None, **kwargs):
        calls: list = []

        def answering(root, *args):
            calls.append((root, args[0], json.loads((root / ".agents/project.json").read_text())))
            return (resolver or (lambda verb: (0, {})))(args[0])

        code, out = self.run_check(
            ["--wait", "5"], fetch=console.fetch, post=console.post, resolver=answering,
            poll=0.02, settle=5, shown=kwargs.pop("shown", 5))
        return code, out, calls

    def test_a_ready_schema_three_plan_that_resolves_is_met(self):
        console = Console(self, READY, plan=stored(DRAFT))
        code, out, calls = self.exercise(console)
        self.assertEqual((code, out), (0, {"schema_version": 3, "status": "met"}))
        (register_post, cancel) = console.posts
        root = register_post[1]["path"]
        self.assertEqual(register_post, ("register-project", {"path": root, "unless_open": True}))
        self.assertEqual(cancel, ("register-cancel", {"restore": True, "root": root}))
        self.assertEqual([(verb, document["schema_version"]) for _, verb, document in calls],
                         [("write-projections", 3), ("resolve", 3)])
        self.assertEqual({str(path) for path, _, _ in calls}, {str(Path(calls[0][0]))})
        self.assertNotEqual(str(calls[0][0]), root)
        self.assertEqual(list(self.tmp_root.iterdir()), [])
        self.assertEqual(list((agent_platform.state_root() / "adopt" / "plans").glob("*.json")), [])

    def test_a_plan_whose_contract_the_resolver_refuses_is_not_met(self):
        console = Console(self, READY, plan=stored(DRAFT))
        refusal = {"error": {"violations": [{"pointer": "/platform", "message": "x"}]}}
        code, out, calls = self.exercise(
            console, lambda verb: (2, refusal) if verb == "resolve" else (0, {}))
        self.assertEqual((code, out), (1, {"reason": "resolve refused: /platform",
                                           "status": "not_met"}))
        self.assertEqual([verb for _, verb, _ in calls], ["write-projections", "resolve"])

    def test_a_drafting_row_is_not_met_with_its_open_questions(self):
        row = {"state": "drafting", "plan_id": "draft:x", "questions": [{"subject": "lint-command"}]}
        code, out, calls = self.exercise(Console(self, row))
        self.assertEqual((code, out), (1, {"reason": "open questions: lint-command",
                                           "status": "not_met"}))
        self.assertEqual(calls, [])

    def test_a_schema_two_plan_is_not_met(self):
        console = Console(self, READY, plan=stored({**DRAFT, "schema_version": 2}))
        code, out, calls = self.exercise(console)
        self.assertEqual((code, out), (1, {"reason": "plan not schema 3", "status": "not_met"}))
        self.assertEqual(calls, [])

    def test_a_plan_whose_write_is_not_its_contract_is_not_met(self):
        console = Console(self, READY, plan=stored(DRAFT, after=b"{}\n"))
        code, out, calls = self.exercise(console)
        self.assertEqual((code, out), (1, {"reason": "contract bytes differ from the plan",
                                           "status": "not_met"}))
        self.assertEqual(calls, [])

    def test_an_owner_row_that_does_not_come_back_is_not_restored(self):
        console = Console(self, READY, plan=stored(DRAFT), owner_returns=False)
        code, out, _ = self.exercise(console, shown=0.3)
        self.assertEqual((code, out), (1, {
            "status": "not_restored", "leftovers": ["registration"],
            "verdict": {"schema_version": 3, "status": "met"}}))

    def test_the_fixture_reads_its_default_branch_and_its_drafted_contract_resolves(self):
        previous = os.environ.get("GIT_ALLOW_PROTOCOL")
        os.environ["GIT_ALLOW_PROTOCOL"] = "file"
        self.addCleanup(os.environ.pop if previous is None else os.environ.__setitem__,
                        "GIT_ALLOW_PROTOCOL", *([] if previous is None else [previous]))
        parent = Path(tempfile.mkdtemp(dir=self.tmp_root))
        root = draft_register_check.fixture(parent, "console-check/draft-0a1b2c3d", REVISION)
        reading = cd.read(str(root))
        self.assertEqual(reading["default_branch"], "main")
        fields = cd.draft(str(root), reading)
        self.assertEqual(cd.questions(fields), [])
        copy = parent / "resolved"
        shutil.copytree(root, copy, symlinks=True)
        (copy / ".agents").mkdir()
        (copy / ".agents" / "project.json").write_bytes(written(cd.contract(fields)))
        for verb in ("write-projections", "resolve"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = resolve_project.main([verb, "--repo-root", str(copy)])
            self.assertEqual(code, 0, out.getvalue())

    def test_no_console_is_not_yet(self):
        posted: list = []

        def post(url, headers, body):
            posted.append(url)
            return 204, b""

        code, out = self.run_check(["--wait", "1"], fetch=lambda url: (None, b""), post=post, **QUICK)
        self.assertEqual((code, out), (75, {"status": "not_running"}))
        with self.subTest(case="no installed revision"):
            self.install_revision(None)
            code, out = self.run_check(["--wait", "1"], fetch=lambda url: view(OWNER_ROW), post=post, **QUICK)
            self.assertEqual((code, out), (75, {"status": "no_platform_revision"}))
        with self.subTest(case="no source of the installed revision"):
            self.install_revision(REVISION, source=False)
            code, out = self.run_check(["--wait", "1"], fetch=lambda url: view(OWNER_ROW), post=post, **QUICK)
            self.assertEqual((code, out), (75, {"status": "no_platform_source"}))
        self.assertEqual(posted, [])
        self.assertEqual(list(self.tmp_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
