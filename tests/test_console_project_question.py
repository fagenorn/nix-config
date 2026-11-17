"""The console's project question session (#1176): hook, launch, service and route.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import (
    account_remove, event_log, project_question, project_question_hook as hook, service, signin, sprints)
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_account_service import Listing
from .test_console_writes import Case

DECLARED = (("just", "build"),)
ROUTES = (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),)
ENVIRON = {"HOME": "/home/u", "PATH": "/bin"}
SESSION_ID = "0b5c8f9e-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
SUCCESS = (
    b'{"type":"result","subtype":"success","is_error":false,'
    b'"result":" Answer: it builds the hosts. "}'
)


def SNAPSHOT(read_only, cwd_of=lambda id: "/srv/p01", root="/srv/p01"):  # noqa: N802 -- a fixture
    return {
        "project": {"root": root, "id": "owner/p01", "name": "p01"},
        "production": {
            "status": "declared",
            "changes": {"commands": ["nix-activate"], "key_files": [], "mcp_tools": []},
            "read_only": {"commands": read_only, "mcp_tools": []},
            "release_profile": "github-release",
        },
        "bindings": {"commands": {
            "nix-build": {"argv": ["just", "build"], "cwd": cwd_of("nix-build"), "env": []},
            "nix-activate": {"argv": ["just", "switch"], "cwd": "/srv/p01", "env": []},
            "sub-check": {"argv": ["./check"], "cwd": "/srv/p01/sub", "env": []},
            "piped": {"argv": ["sh", "-c", "a|b"], "cwd": "/srv/p01", "env": []},
        }},
    }


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def tool(name, tool_input=None):
    return {"tool_name": name, "tool_input": tool_input or {}}


class HookTableTest(unittest.TestCase):
    def test_the_hook_admits_reads_and_bare_declared_commands_and_denies_the_rest(self):
        allow = ("allow", hook.ALLOWED)
        lifecycle = ("deny", hook.LIFECYCLE_DENIED)
        undeclared = ("deny", hook.COMMAND_DENIED.format(commands="just build"))
        rows = [
            (tool("Read", {"file_path": "/srv/p01/README.md"}), DECLARED, allow),
            (tool("Grep", {"pattern": "x"}), DECLARED, allow),
            (tool("Glob", {"pattern": "**/*.nix"}), DECLARED, allow),
            (bash("just build"), DECLARED, allow),
            (bash("  just   build  "), DECLARED, allow),
        ]
        for name in ("Edit", "Write", "NotebookEdit"):
            rows.append((tool(name), DECLARED, ("deny", hook.WRITE_DENIED.format(tool=name))))
        for command in (
            "git push origin main",
            "gh pr create --title t --body b",
            "gh pr merge 7 --merge",
            "git branch -d topic",
            "gh release create v1.0.0",
            "just build && git push",
            "git -C . push origin main",
            "/usr/bin/git push origin main",
            "git -c core.x=y push",
            "git --git-dir=.git push",
            "git --git-dir .git push",
            "/usr/local/bin/gh pr create --title t",
            "gh pr -R owner/repo merge 7",
            "gh --repo owner/repo release create v1",
            "git -C . branch -d topic",
        ):
            rows.append((bash(command), DECLARED, lifecycle))
        rows.append((bash("git push"), (("git", "push"),), lifecycle))
        rows.append((bash("git -C . push origin main"), (("git", "-C", ".", "push", "origin", "main"),),
                     lifecycle))
        rows.append((bash("/usr/bin/git push origin main"),
                     (("/usr/bin/git", "push", "origin", "main"),), lifecycle))
        for command in ("just switch", "just", "just build extra", "cat README.md", "FOO=1 just build"):
            rows.append((bash(command), DECLARED, undeclared))
        for command in (
            "just build | cat",
            "just build > out.txt",
            "just build 2>&1",
            "just build < in.txt",
            "just build; rm -rf x",
            "just build && echo ok",
            "just build || true",
            "just build &",
            "(just build)",
            "$(just build)",
            "`just build`",
            "just build\nrm x",
            "'just' build",
            "just\nbuild",
            "just\tbuild",
            "just\rbuild",
            "just build\n",
        ):
            rows.append((bash(command), DECLARED, undeclared))
        for name in ("WebFetch", "Task", "Agent", "mcp__github__create_issue"):
            rows.append((tool(name), DECLARED, ("deny", hook.TOOL_DENIED.format(tool=name))))
        for document, allowed, expected in rows:
            with self.subTest(document):
                self.assertEqual(hook.decide(document, allowed), expected)

    def test_with_no_declared_command_every_shell_command_is_denied(self):
        denied = ("deny", hook.NO_COMMANDS)
        self.assertEqual(hook.decide(bash("just build"), ()), denied)
        self.assertEqual(hook.decide(bash("ls"), ()), denied)
        self.assertEqual(hook.decide(tool("Read"), ()), ("allow", hook.ALLOWED))

    def test_a_malformed_call_is_denied(self):
        for document in (
            None,
            [],
            {},
            {"tool_name": ""},
            {"tool_name": "Bash"},
            {"tool_name": "Bash", "tool_input": {"command": 3}},
        ):
            with self.subTest(document):
                self.assertEqual(hook.decide(document, DECLARED), ("deny", hook.MALFORMED))

    def test_parse_allowed_accepts_only_lists_of_word_lists(self):
        self.assertEqual(hook.parse_allowed('[["just","build"]]'), (("just", "build"),))
        self.assertEqual(hook.parse_allowed("[]"), ())
        for text in ("{}", "[[]]", '[["just",""]]', "[[1]]", "nope"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    hook.parse_allowed(text)


class HookProcessTest(unittest.TestCase):
    def run_hook(self, args, stdin_text):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.console.project_question_hook", *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def wire(self, decision, reason):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }

    def test_the_module_prints_the_decision_in_the_client_format(self):
        args = ['[["just","build"]]']
        done = self.run_hook(args, json.dumps(bash("just build")))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout), self.wire("allow", hook.ALLOWED))
        done = self.run_hook(args, json.dumps({"tool_name": "Write", "tool_input": {}}))
        self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.WRITE_DENIED.format(tool="Write")))
        done = self.run_hook(args, json.dumps(bash("just\nbuild")))
        self.assertEqual(
            json.loads(done.stdout),
            self.wire("deny", hook.COMMAND_DENIED.format(commands="just build")),
        )

    def test_a_bad_argument_denies_everything(self):
        read = json.dumps(tool("Read", {"file_path": "/x"}))
        deep = "[" * 100000  # under the 128 KiB limit of one argv word
        for args, stdin_text in (
            ([], read),
            (["not json"], read),
            (['[["just","build"]]'], "{"),
            (['[["just","build"]]'], deep),
            ([deep], read),
        ):
            with self.subTest(args=args, stdin=stdin_text):
                done = self.run_hook(args, stdin_text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.MALFORMED))
                self.assertEqual(len(done.stdout.splitlines()), 1)


class LaunchTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "root"
        self.root.mkdir()
        self.settings_dir = Path(directory.name) / "state" / project_question.SETTINGS_DIR
        self.routes = (project_question.Route("nix-build", ("just", "build"), str(self.root)),)
        self.ask = self.make_ask(self.routes)
        self.calls = []
        self.settings = {}

    def make_ask(self, routes, root=None):
        return project_question.new_ask(
            "a" * 16, "owner/p01", str(root or self.root), "what does the build check?", "work",
            routes, self.settings_dir, session_id=SESSION_ID)

    def fake(self, stdout=SUCCESS, code=0, error=None, stderr=b"", act=None):
        def run(argv, *, timeout, cancel=None, **kwargs):
            self.calls.append((argv, timeout, cancel, kwargs))
            path = self.ask.settings
            if path.exists():
                self.settings = {
                    "text": path.read_text(),
                    "mode": path.stat().st_mode & 0o777,
                    "parent_mode": path.parent.stat().st_mode & 0o777,
                }
            if act is not None:
                act(kwargs)
            if error is not None:
                raise error
            if stderr:
                kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=None)
        return run

    def start(self, run, ask=None, cancel=None, platform="linux"):
        return project_question.run_question(
            ask or self.ask, cancel, platform=platform, run=run, environ=ENVIRON)

    def test_the_launch_runs_sonnet_headless_in_the_root_under_the_chosen_profile(self):
        outcome = self.start(self.fake())

        argv, timeout, _cancel, kwargs = self.calls[0]
        self.assertEqual(argv, [
            "claude-account", "run", "-p", "--model", "sonnet", "--session-id", SESSION_ID,
            "--permission-mode", "dontAsk", "--setting-sources", "", "--strict-mcp-config", "--tools", "Read,Grep,Glob,Bash",
            "--output-format", "json", "--settings", str(self.ask.settings),
            project_question.prompt(self.ask.question, self.routes)])
        self.assertEqual(timeout, 300)
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertTrue(kwargs["env"]["PATH"].startswith("/home/u/.agents/bin"))
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(outcome, project_question.Outcome("answered", answer="Answer: it builds the hosts."))

    def test_each_question_gets_its_own_uuid_session_id(self):
        a, b = project_question.new_session_id(), project_question.new_session_id()
        self.assertNotEqual(a, b)
        self.assertEqual(uuid.UUID(a).version, 4)
        self.assertEqual(str(uuid.UUID(a)), a)

    def test_the_settings_file_denies_writes_and_lifecycle_verbs_and_blocks_on_hook_failure(self):
        self.start(self.fake())

        document = json.loads(self.settings["text"])
        self.assertEqual(document["permissions"], {
            "defaultMode": "dontAsk",
            "allow": ["Read", "Grep", "Glob", "Bash(just build)"],
            "deny": ["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
                     "Bash(git push:*)", "Bash(gh pr create:*)", "Bash(gh pr merge:*)",
                     "Bash(git branch -d:*)", "Bash(gh release create:*)"],
        })
        hooks = document["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(document["hooks"], {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": hooks["command"], "timeout": 10, "onFailure": "block"}]}]})
        self.assertEqual(shlex.split(hooks["command"]), [
            *siblings.sibling_argv("console.project_question_hook"), '[["just","build"]]'])
        self.assertEqual(self.settings["mode"], 0o600)
        self.assertEqual(self.settings["parent_mode"], 0o700)
        self.assertFalse(self.ask.settings.exists())

    def test_a_session_past_the_time_cap_is_timed_out(self):
        outcome = self.start(self.fake(error=subprocess.TimeoutExpired(["claude-account"], 300)))

        self.assertEqual(outcome, project_question.Outcome(
            "timed_out", reason="the session did not answer within 300 s"))
        self.assertFalse(self.ask.settings.exists())

    def test_each_failure_is_a_failed_outcome_with_its_reason(self):
        cancel = threading.Event()
        cases = [
            ("darwin", {"platform": "darwin", "run": self.fake()}, project_question.UNAVAILABLE_TEXT),
            ("root", {"run": self.fake(), "ask": self.make_ask(self.routes, self.root / "missing")},
             f"the project root {self.root / 'missing'} is not a directory"),
            ("missing binary", {"run": self.fake(error=FileNotFoundError())},
             "claude-account is not installed"),
            ("stderr", {"run": self.fake(code=1, stderr=b"first\n\nboom\n")}, "boom"),
            ("exit", {"run": self.fake(code=2)}, "the session exited 2"),
            ("not json", {"run": self.fake(stdout=b"not json")}, project_question.UNREADABLE_TEXT),
            ("is_error", {"run": self.fake(stdout=b'{"is_error":true,"result":"Credit balance is too low"}')},
             "Credit balance is too low"),
            ("cancel", {"run": self.fake(code=-9, act=lambda kwargs: cancel.set()), "cancel": cancel},
             project_question.STOPPED_TEXT),
        ]
        for name, kwargs, reason in cases:
            with self.subTest(name):
                self.calls.clear()
                outcome = self.start(**kwargs)
                self.assertEqual(outcome, project_question.Outcome("failed", reason=reason))
                self.assertFalse(self.ask.settings.exists())
                if name in ("darwin", "root"):
                    self.assertEqual(self.calls, [])


class NoProductionTest(unittest.TestCase):
    def test_read_only_routes_resolve_ids_to_argv(self):
        expected = (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),)
        self.assertEqual(project_question.read_only_routes(SNAPSHOT(["nix-build", "ghost"])), expected)
        self.assertEqual(
            project_question.read_only_routes(SNAPSHOT(["nix-build", "ghost"], root="/srv/p01/")), expected)

    def test_a_route_declared_for_another_directory_or_with_a_composed_argv_is_not_offered(self):
        self.assertEqual(
            project_question.read_only_routes(SNAPSHOT(["sub-check", "piped", "nix-build"])),
            (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),))
        self.assertEqual(
            project_question.read_only_routes(
                SNAPSHOT(["nix-build"], cwd_of=lambda id: "/srv/p01/sub")), ())

    def test_an_unresolvable_contract_raises_instead_of_answering_no_routes(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(resolve_project.ContractError):
                project_question.routes_of(path)

    def test_a_contract_with_no_read_only_command_gets_the_production_line(self):
        for snapshot in (SNAPSHOT([]), {**SNAPSHOT([]), "production": {"status": "none"}},
                         {**SNAPSHOT([]), "production": {"status": "not_declared"}}):
            self.assertEqual(project_question.read_only_routes(snapshot), ())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            ask = project_question.new_ask(
                "b" * 16, "owner/p01", str(root), "why?", "work", (), Path(directory) / "settings",
                session_id=SESSION_ID)
            seen = {}

            def run(argv, *, timeout, cancel=None, **kwargs):
                seen["argv"] = argv
                seen["settings"] = json.loads(ask.settings.read_text())
                return subprocess.CompletedProcess(argv, 0, stdout=SUCCESS, stderr=None)

            outcome = project_question.run_question(
                ask, None, platform="linux", run=run, environ=ENVIRON)
        self.assertEqual(
            outcome.answer, "Answer: it builds the hosts.\n" + project_question.NO_PRODUCTION_LINE)
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertIn("This project declares no read-only command, so production cannot be read", argv[-1])
        hook_command = seen["settings"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(hook_command)[-1], "[]")
        self.assertEqual(seen["settings"]["permissions"]["allow"], ["Read", "Grep", "Glob"])

    def test_declared_routes_get_no_production_line(self):
        self.assertNotIn(project_question.NO_PRODUCTION_LINE, project_question.answer_text("Answer: x", ROUTES))
        self.assertIn(
            "Commands you may run, each exactly as written and alone: just build.",
            project_question.prompt("why?", ROUTES))

    def test_a_question_is_checked_and_parsed(self):
        self.assertEqual(project_question.checked_question("  why?  "), "why?")
        for text, reason in (("", project_question.EMPTY), ("   ", project_question.EMPTY),
                             ("x" * 2001, project_question.TOO_LONG)):
            with self.assertRaises(project_question.Refused) as caught:
                project_question.checked_question(text)
            self.assertEqual(str(caught.exception), reason)
        self.assertEqual(
            project_question.parse_request(b'{"project_id":"owner/p01","question":"why?"}'),
            ("owner/p01", "why?"))
        for body in (b'{"project_id":"owner/p01"}', b'{"project_id":"","question":"q"}',
                     b'{"project_id":"p","question":1}',
                     b'{"project_id":"p","project_id":"q","question":"q"}', b"[1]"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                project_question.parse_request(body)

    def test_routes_compare_each_cwd_with_the_resolved_root_not_the_given_path(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            os.symlink(real, link)
            seen = []

            def resolve(path):
                seen.append(path)
                return SNAPSHOT(["nix-build"], cwd_of=lambda id: str(real), root=str(real))

            routes = project_question.routes_of(str(link), resolve=resolve)
        self.assertEqual(seen, [str(link)])
        self.assertEqual(routes, (project_question.Route("nix-build", ("just", "build"), str(real)),))


if __name__ == "__main__":
    unittest.main()


ASKED = "project_question.asked"
ANSWERED_KIND = "project_question.answered"
QUESTION_ROUTE = "/api/project-question"
JSON = {"Content-Type": "application/json"}
WHY = "owner/p01"


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "the condition did not become true within 5 s"


class QuestionCase(Case):
    """A service whose question session is a stub: the asker records each call and returns an outcome."""

    def setUp(self):
        super().setUp()
        self.outcome = project_question.Outcome("answered", answer="Answer: it builds.")
        self.raises = None
        self.asked = []
        self.queued = []
        self.calls = []
        self.profiles = self.store.parent.parent / "accounts" / "profiles"
        patcher = mock.patch.object(
            project_question, "new_session_id", create=True, return_value=SESSION_ID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def asker(self, ask, cancel):
        self.asked.append((ask, cancel))
        if self.raises is not None:
            raise self.raises
        return self.outcome

    def start(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        support.sign_in(self.store, "work")
        defaults = {
            "profile_dirs": [support.profile_dir(self.store, "work")],
            "session_poll_seconds": 3600, "project_asker": self.asker,
            "project_routes": lambda root: ROUTES,
            "project_question_dispatch": lambda job: job()}
        for name, value in defaults.items():
            kwargs.setdefault(name, value)
        return super().start(**kwargs)

    def start_removal(self, **kwargs):
        support.profile_dir(self.store, "work")
        kwargs.setdefault("profile_dirs", Listing(self.profiles))
        kwargs.setdefault("signin_reader", lambda one: signin.Status("signed_in", None))
        kwargs.setdefault("signer_out", lambda one: self.calls.append(("signout", one.profile)))
        kwargs.setdefault("account_remover", self.remover)
        kwargs.setdefault("choice_file", self.profiles.parent / "chosen-profile")
        return self.start(**kwargs)

    def remover(self, name):
        self.calls.append(("rm", name))
        shutil.rmtree(self.profiles / name)

    def question_rows(self):
        return [(row[2], row[3], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2].startswith("project_question.")]


class QuestionServiceTest(QuestionCase):
    def test_asking_appends_a_question_row_then_exactly_one_answer_row_per_outcome(self):
        svc = self.start()
        cases = (
            (project_question.Outcome("answered", answer="Answer: x"), None,
             {"outcome": "answered", "answer": "Answer: x"}),
            (project_question.Outcome("failed", reason="boom"), None,
             {"outcome": "failed", "reason": "boom"}),
            (project_question.Outcome("timed_out", reason="the session did not answer within 300 s"),
             None, {"outcome": "timed_out",
                    "reason": "the session did not answer within 300 s"}),
            (None, RuntimeError("down"), {"outcome": "failed", "reason": "RuntimeError: down"}))
        for outcome, raises, tail in cases:
            with self.subTest(tail=tail):
                self.outcome, self.raises = outcome, raises
                before = len(self.question_rows())
                qid = svc.ask_project_question(WHY, " why? ")
                self.assertEqual(self.question_rows()[before:], [
                    (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
                    (ANSWERED_KIND, WHY, {"question_id": qid, **tail})])
                self.assertEqual(svc._project_questions_open, 0)

    def test_the_session_gets_the_chosen_profile_the_root_and_the_routes(self):
        svc = self.start()
        svc.ask_project_question(WHY, "why?")
        (ask, cancel), = self.asked
        self.assertEqual((ask.profile, ask.root, ask.routes, ask.question),
                         ("work", "/srv/p01", ROUTES, "why?"))
        self.assertEqual(ask.settings.parent, self.store.with_name("project-question-settings"))
        self.assertIs(cancel, svc._stop)
        self.assertEqual(ask.session_id, SESSION_ID)
        self.assertEqual(self.question_rows()[0][2]["session_id"], ask.session_id)

    def test_a_questions_transcript_is_spent_under_its_project_and_the_questions_aspect(self):
        now = 1_800_000_000.0
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        sessions = self.store.parent.parent / "sessions"
        svc = self.start(session_dirs=[sessions], clock=lambda: now)
        svc.ask_project_question(WHY, "why?")
        path = sessions.parent / "projects" / "-srv-p01" / f"{SESSION_ID}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"type": "assistant", "sessionId": SESSION_ID, "cwd": "/srv/p01",
                "timestamp": f"{today}T10:00:00.000Z",
                "message": {"id": "msg_q1", "model": "claude-sonnet-4-6",
                            "usage": {"input_tokens": 40}}}
        path.write_text(json.dumps(line) + "\n")
        os.utime(path, (now, now))
        svc.poll_spend()
        day = json.loads(svc.view_bytes)["spend"]["days"][-1]
        self.assertEqual({k: t["input"] for k, t in day["aspect"].items()}, {"questions": 40})
        self.assertEqual(day["project"][WHY]["input"], 40)
        self.assertEqual(set(day["account"]), {"work"})

    def test_nothing_reaches_the_tracker(self):
        def refuse(name):
            def double(*args, **kwargs):
                self.calls.append(name)
                raise AssertionError(name)
            return double
        svc = self.start(tracker=refuse("tracker"), tick=refuse("tick"),
                         owner_path=refuse("owner_path"), criterion_path=refuse("criterion_path"),
                         slug_of=lambda root: None)
        for outcome, raises in ((project_question.Outcome("answered", answer="Answer: x"), None),
                                (project_question.Outcome("failed", reason="boom"), None),
                                (project_question.Outcome("timed_out", reason="late"), None),
                                (None, RuntimeError("down"))):
            self.outcome, self.raises = outcome, raises
            svc.ask_project_question(WHY, "why?")
        self.assertEqual(self.calls, [])

    def test_refusals_append_nothing(self):
        cases = (
            ({}, "owner/p99", "why?", "this project is not registered"),
            ({}, WHY, "   ", "write the question first"),
            ({}, WHY, "x" * 2001, "a question is at most 2000 characters"),
            ({"project_asker": None}, WHY, "why?", "questions are not available on this host yet"),
            ({"profile_dirs": []}, WHY, "why?", "no account can take a question now"))
        for kwargs, project, text, reason in cases:
            with self.subTest(reason=reason):
                svc = self.start(**kwargs)
                before = self.question_rows()
                with self.assertRaises(project_question.Refused) as caught:
                    svc.ask_project_question(project, text)
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(self.question_rows(), before)
                self.assertEqual(self.asked, [])
                self.assertEqual(svc._project_questions_open, 0)
                svc.close()

    def test_a_dispatch_that_fails_still_answers_the_question_once(self):
        def dispatch(job):
            raise RuntimeError("no thread")
        svc = self.start(project_question_dispatch=dispatch)
        with self.assertRaises(RuntimeError):
            svc.ask_project_question(WHY, "why?")
        (asked, project, payload), (answered, _, tail) = self.question_rows()
        self.assertEqual((asked, project, answered), (ASKED, WHY, ANSWERED_KIND))
        self.assertEqual(tail, {"question_id": payload["question_id"], "outcome": "failed",
                                "reason": "RuntimeError: no thread"})
        self.assertEqual(self.asked, [])
        self.assertEqual(svc._project_questions_open, 0)

    def test_a_default_dispatch_that_cannot_start_a_thread_leaves_close_working(self):
        svc = self.start(project_question_dispatch=None)
        with mock.patch.object(threading.Thread, "start",
                               side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(RuntimeError):
                svc.ask_project_question(WHY, "why?")
        self.assertEqual(svc._project_question_workers, [])
        self.assertEqual(svc._project_questions_open, 0)
        svc.close()
        self.assertEqual([row[0] for row in self.question_rows()][-1:], [ANSWERED_KIND])

    def test_an_unresolvable_contract_is_a_failed_answer_and_starts_no_session(self):
        error = resolve_project.ContractError(
            "resolver_failure", "resolver.internal",
            [{"pointer": "", "message": "the resolver failed unexpectedly"}])

        def routes(root):
            raise error
        svc = self.start(project_routes=routes)
        qid = svc.ask_project_question(WHY, "why?")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows()[-1], (ANSWERED_KIND, WHY, {
            "question_id": qid, "outcome": "failed",
            "reason": project_question.CONTRACT_UNREADABLE.format(
                detail="ContractError: " + str(error))}))

    def test_the_question_kinds_are_not_kept(self):
        self.assertEqual(event_log.PROJECT_QUESTION_ASKED, ASKED)
        self.assertEqual(event_log.PROJECT_QUESTION_ANSWERED, ANSWERED_KIND)
        self.assertNotIn(ASKED, event_log.KEPT_KINDS)
        self.assertNotIn(ANSWERED_KIND, event_log.KEPT_KINDS)
        self.assertEqual(event_log.SCHEMA_VERSION, 10)


def question_threads():
    return [t for t in threading.enumerate() if t.name == service.PROJECT_QUESTION_THREAD]


class QuestionLifecycleTest(QuestionCase):
    def test_an_orderly_stop_records_the_running_questions_answer_once(self):
        entered = threading.Event()

        def asker(ask, cancel):
            entered.set()
            cancel.wait(10)
            time.sleep(0.2)
            return project_question.Outcome("failed", reason=project_question.STOPPED_TEXT)
        svc = self.start(project_question_dispatch=None, project_asker=asker)
        record = svc._record_project_answer

        def record_then_linger(*args):
            record(*args)
            time.sleep(0.3)  # the worker outlives its answer: only a join waits for it
        svc._record_project_answer = record_then_linger
        qid = svc.ask_project_question(WHY, "why?")
        self.assertTrue(entered.wait(10))
        svc.close()
        self.assertEqual(self.question_rows(), [
            (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
            (ANSWERED_KIND, WHY, {"question_id": qid, "outcome": "failed",
                                  "reason": project_question.STOPPED_TEXT})])
        self.assertEqual(question_threads(), [])

    def test_a_question_accepted_before_a_stop_and_not_yet_dispatched_is_answered_before_the_log_closes(self):
        svc = self.start(project_question_dispatch=self.queued.append)
        qid = svc.ask_project_question(WHY, "why?")
        closer = threading.Thread(target=svc.close)
        closer.start()
        try:
            wait_until(svc._stop.is_set)
            closer.join(2)  # past the server's 0.5 s shutdown poll: only the drain still holds it
            self.assertTrue(closer.is_alive())
        finally:
            self.queued[0]()
        closer.join(10)
        self.assertFalse(closer.is_alive())
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows(), [
            (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
            (ANSWERED_KIND, WHY, {"question_id": qid, "outcome": "failed",
                                  "reason": project_question.STOPPED_TEXT})])

    def test_a_question_asked_while_the_console_stops_is_refused_and_appends_nothing(self):
        svc = self.start(project_question_dispatch=self.queued.append)
        svc.ask_project_question(WHY, "why?")
        closer = threading.Thread(target=svc.close)
        closer.start()
        try:
            wait_until(svc._stop.is_set)
            with self.assertRaises(project_question.Refused) as caught:
                svc.ask_project_question(WHY, "again?")
            self.assertEqual(str(caught.exception), "the console is stopping")
            self.assertEqual([kind for kind, _, _ in self.question_rows()], [ASKED])
        finally:
            for job in list(self.queued):
                job()
        closer.join(10)
        self.assertFalse(closer.is_alive())
        self.assertEqual(len(self.queued), 1)

    def test_concurrent_questions_are_each_answered_once_on_stop(self):
        entered = []
        barrier = threading.Barrier(2, timeout=10)

        def asker(ask, cancel):
            entered.append(ask.question_id)
            barrier.wait()
            cancel.wait(10)
            return project_question.Outcome("failed", reason=project_question.STOPPED_TEXT)
        svc = self.start(project_question_dispatch=None, project_asker=asker)
        ids = []
        askers = [threading.Thread(target=lambda text=text: ids.append(
            svc.ask_project_question(WHY, text))) for text in ("one?", "two?")]
        for each in askers:
            each.start()
        for each in askers:
            each.join(10)
        wait_until(lambda: len(entered) == 2 and barrier.n_waiting == 0)
        svc.close()
        rows = self.question_rows()
        self.assertEqual(len(ids), 2)
        self.assertEqual(sorted(p["question_id"] for k, _, p in rows if k == ASKED), sorted(ids))
        self.assertEqual(sorted(p["question_id"] for k, _, p in rows if k == ANSWERED_KIND),
                         sorted(ids))
        self.assertEqual(len(rows), 4)
        self.assertEqual(question_threads(), [])

    def test_a_removal_waits_for_a_running_question_and_is_refused_while_it_runs(self):
        entered, gate = threading.Event(), threading.Event()

        def asker(ask, cancel):
            entered.set()
            gate.wait(10)
            return project_question.Outcome("answered", answer="Answer: x")
        self.addCleanup(gate.set)
        svc = self.start_removal(
            project_asker=asker,
            project_question_dispatch=lambda job: threading.Thread(target=job).start())
        qid = svc.ask_project_question(WHY, "why?")
        self.assertTrue(entered.wait(10))
        with mock.patch.object(account_remove, "DRAIN_TIMEOUT", 0.2):
            with self.assertRaises(sprints.Refused) as caught:
                svc.remove_account("work", "work")
        self.assertEqual(str(caught.exception), account_remove.busy("work"))
        self.assertEqual(self.calls, [])
        gate.set()
        wait_until(lambda: [k for k, _, _ in self.question_rows()] == [ASKED, ANSWERED_KIND])
        self.assertEqual(self.question_rows()[-1][2],
                         {"question_id": qid, "outcome": "answered", "answer": "Answer: x"})

    def test_a_queued_question_whose_profile_is_removed_fails_without_a_session(self):
        for name, reason in (
                ("marked", "work is being removed"),
                ("gone", "the account work was removed before the session started")):
            with self.subTest(name):
                self.calls.clear()
                self.queued.clear()
                self.asked.clear()
                support.profile_dir(self.store, "work")
                if name == "marked":
                    def signer_out(one):
                        self.calls.append(("signout", one.profile))
                        self.queued[0]()
                    svc = self.start_removal(project_question_dispatch=self.queued.append,
                                             signer_out=signer_out)
                else:
                    svc = self.start_removal(project_question_dispatch=self.queued.append)
                qid = svc.ask_project_question(WHY, "why?")
                svc.remove_account("work", "work")
                if name == "gone":
                    self.assertFalse((self.profiles / "work").exists())
                    self.queued[0]()
                self.assertEqual(self.asked, [])
                answered = [p for k, _, p in self.question_rows()
                            if k == ANSWERED_KIND and p["question_id"] == qid]
                self.assertEqual(answered, [{"question_id": qid, "outcome": "failed",
                                             "reason": reason}])
                svc.close()


class QuestionRouteTest(QuestionCase):
    def post(self, svc, body, headers):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        return support.post_page(svc.address, QUESTION_ROUTE, headers, payload)

    def test_the_route_refuses_without_the_token_or_origin_and_appends_nothing(self):
        svc = self.start()
        body = {"project_id": WHY, "question": "why?"}
        origin = f"http://127.0.0.1:{svc.address[1]}"
        cases = (
            ({"Origin": origin, **JSON}, b"token refused\n"),
            (self.own(svc, Origin="http://example.test", **JSON), b"origin refused\n"),
            ({"X-Console-Token": self.token(), **JSON}, b"origin refused\n"))
        for headers, text in cases:
            with self.subTest(text=text):
                got = self.assert_unchanged(svc, lambda: self.post(svc, body, headers))
                self.assertEqual((got[0], got[2]), (403, text))
        self.assertEqual(self.asked, [])

    def test_the_route_refuses_an_unregistered_project_and_appends_nothing(self):
        svc = self.start()
        cases = (
            ({"project_id": "owner/p99", "question": "why?"}, 409,
             b"this project is not registered\n"),
            (b'{"project_id":"owner/p01"}', 400, b"bad question\n"),
            ({"project_id": WHY, "question": ""}, 409, b"write the question first\n"))
        for body, status, text in cases:
            with self.subTest(text=text):
                got = self.assert_unchanged(
                    svc, lambda: self.post(svc, body, self.own(svc, **JSON)))
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual(self.asked, [])

    def test_a_question_from_the_page_is_answered_into_the_log(self):
        svc = self.start()
        status, _, body = self.post(
            svc, {"project_id": WHY, "question": "what does the build check?"},
            self.own(svc, **JSON))
        self.assertEqual((status, body), (204, b""))
        asked, answered = self.question_rows()[-2:]
        self.assertEqual((asked[0], asked[1], answered[0], answered[1]),
                         (ASKED, WHY, ANSWERED_KIND, WHY))

    def test_the_route_is_a_page_write_that_takes_only_post(self):
        svc = self.start()
        self.assertIn(QUESTION_ROUTE, service.PAGE_WRITES)
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, QUESTION_ROUTE)
                self.assertEqual((status, headers["Allow"]), (405, "POST"))
