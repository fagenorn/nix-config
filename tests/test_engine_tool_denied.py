"""Contract tests for a session denied a tool call: `engine deliver` ends the run at the engine's own stop
`tool-denied`, never a fault and never a graded reply, and a blocked reply ends at its own stop.

The helpers, fixtures and the stand-in launcher are the ones tests/test_engine_session.py defines; the group
and call cases run in process as tests/test_engine_fanout.py does.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_session, engine_shell, engine_stop
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_deliver import EngineProject
from tests.test_engine_fanout import FAN, REVIEWS, child, children_of, roots, with_session_files
from tests.test_engine_session import (
    REPO_ROOT, RESULT_LIMIT, RESULT_MISSING, after, agent_step, canned_result, copy_roles, install_answers,
    install_stub, one_step, write_procedures, REVIEW_REPLY, DRAFT_REPLY,
)
from tests.test_engine_stubbed_run import SHA, Scenario

TIER = "integration"  # every case runs the engine as a child process or in process on a built project

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())
RESULT_DENIED = REPO_ROOT / "tests/fixtures/engine-session/result-denied-1639.json"
RESULT_DENIED_1740 = REPO_ROOT / "tests/fixtures/engine-session/result-denied-1740.json"


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


def bash(command: str, ident: str = "toolu_01") -> dict:
    return {"tool_name": "Bash", "tool_use_id": ident, "tool_input": {"command": command}}


class DeniedRun:
    """The project, the run's ledger and the tool-denied stop check both denied-run classes use."""

    def setUp(self) -> None:
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, "implementer", "reviewer")

    def run_dir(self) -> Path:
        (run,) = self.project.runs()
        return run

    def events(self) -> list[dict]:
        return self.project.events(self.run_dir())

    def kinds(self) -> list[str]:
        return [event["event"] for event in self.events()]

    def stopped(self, done, issue: int) -> dict:
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual((line["end"], line["need"]), ("tool-denied", "owner-decision"), line)
        stop = self.events()[-1]
        self.assertEqual((stop["event"], stop["stop"], stop["need"]),
                         ("stop_reached", "tool-denied", "owner-decision"))
        return line


class ToolDeniedStopTest(DeniedRun, unittest.TestCase):
    def test_the_recorded_1639_denial_ends_the_run_at_tool_denied(self):
        fixture = json.loads(RESULT_DENIED.read_text(encoding="utf-8"))
        (denial,) = fixture["permission_denials"]
        install_stub(self.project, RESULT_DENIED)
        procedures = one_step(self.project)

        done = self.project.deliver(procedures, issue=1639)
        status = json.loads(self.project.status(1639).stdout)

        line = self.stopped(done, 1639)
        self.assertIn(repr(denial["tool_input"]["command"]), line["detail"])
        self.assertEqual(self.events()[-1]["step"], "draft")
        kinds = self.kinds()
        for kind in ("result_stored", "outcome_graded", "transition_taken", "run_done"):
            self.assertNotIn(kind, kinds)
        record = json.loads((self.run_dir() / "sessions/draft.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["denials"], fixture["permission_denials"])
        history = (self.project.world.home / ".agents/state/engine/history.jsonl").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(json.loads(history[-1])["end"], "tool-denied")
        self.assertEqual(status["stop"]["name"], "tool-denied")

    def test_a_session_denied_only_a_write_stops_at_tool_denied(self):
        install_stub(self.project, canned_result(permission_denials=[
            {"tool_name": "Write", "tool_use_id": "toolu_01", "tool_input": {"file_path": "/etc/hosts"}}]))

        done = self.project.deliver(one_step(self.project), issue=1919)

        line = self.stopped(done, 1919)
        self.assertIn(repr('Write {"file_path":"/etc/hosts"}'), line["detail"])
        self.assertNotIn("outcome_graded", self.kinds())

    def test_every_denied_tool_call_is_named_whole_and_the_record_keeps_every_denial(self):
        first = "echo " + "a" * 250 + " one"
        second = "echo " + "a" * 250 + " two"
        denials = [bash("make check"),
                   {"tool_name": "Write", "tool_use_id": "toolu_02", "tool_input": {"file_path": "/etc/hosts"}},
                   bash(first, "toolu_03"), bash(second, "toolu_04")]
        install_stub(self.project, canned_result(permission_denials=denials))

        done = self.project.deliver(one_step(self.project), issue=1919)

        line = self.stopped(done, 1919)
        named = [repr("make check"), repr('Write {"file_path":"/etc/hosts"}'), repr(first), repr(second)]
        places = [line["detail"].index(text) for text in named]
        self.assertEqual(places, sorted(set(places)))
        record = json.loads((self.run_dir() / "sessions/draft.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["denials"], denials)

    def test_a_denied_shell_command_on_the_resume_stops_at_tool_denied(self):
        log = install_stub(self.project, RESULT_MISSING,
                           resumed=canned_result(permission_denials=[bash("rm -rf x", "t")]))

        done = self.project.deliver(one_step(self.project), issue=1514)

        self.stopped(done, 1514)
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 3)
        for name in ("draft.1.resume.json", "draft.1.denied.json"):
            self.assertTrue((self.run_dir() / "sessions" / name).exists(), name)
        self.assertNotIn("outcome_graded", self.kinds())

    def test_a_reviewer_denied_a_shell_command_stops_at_tool_denied(self):
        command = "PYTHONPATH=python python3 -m unittest tests.test_x"
        denial = bash(command, "toolu_02")
        install_stub(self.project, canned_result(
            structured_output={"verdict": "approve"}, permission_denials=[denial]))
        steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner"},
                            prompt="review.md", reply="review.reply.json", outcome_from="verdict")]
        procedures = write_procedures(self.project, steps, {
            "review.md": "Review {{run.issue}}.\n",
            "review.reply.json": json.dumps(REVIEW_REPLY)})

        done = self.project.deliver(procedures, issue=1514)

        line = self.stopped(done, 1514)
        self.assertIn(repr(command), line["detail"])
        kinds = self.kinds()
        for kind in ("result_stored", "outcome_graded", "transition_taken", "run_done"):
            self.assertNotIn(kind, kinds)
        record = json.loads((self.run_dir() / "sessions/review.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["denials"], [denial])

    def test_a_denial_after_a_usage_limit_ends_the_wait_before_the_stop(self):
        install_answers(self.project, [
            {"stdout": str(RESULT_LIMIT), "exit": 1, "account": "p1"},
            {"stdout": str(RESULT_DENIED), "exit": 0, "account": "p2"}])

        done = self.project.deliver(one_step(self.project), issue=1919)

        self.stopped(done, 1919)
        kinds = self.kinds()
        self.assertLess(kinds.index("wait_started"), kinds.index("wait_ended"))
        self.assertLess(kinds.index("wait_ended"), len(kinds) - 1)
        (ended,) = [e for e in self.events() if e["event"] == "wait_ended"]
        self.assertEqual(ended["wait"], "usage-limit")
        self.assertIsNone(json.loads(self.project.status(1919).stdout)["wait"])


class DeniedReaskTest(DeniedRun, unittest.TestCase):
    ISSUE = 1514
    USAGE = {"input_tokens": 1, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3,
             "output_tokens": 4}

    def answers(self, *documents: bytes) -> Path:
        entries = []
        for number, data in enumerate(documents, 1):
            path = self.project.tmp / f"answer-{number}.json"
            path.write_bytes(data)
            entries.append({"stdout": str(path), "exit": 0, "account": "p1"})
        return install_answers(self.project, entries)

    def review(self, **on: str) -> Path:
        steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner", **on},
                            prompt="review.md", reply="review.reply.json", outcome_from="verdict")]
        return write_procedures(self.project, steps, {
            "review.md": "Review {{run.issue}}.\n", "review.reply.json": json.dumps(REVIEW_REPLY)})

    @staticmethod
    def verdict(value: str) -> dict:
        return {"verdict": value, "status": "s"}

    @staticmethod
    def launches(log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def sessions(self, name: str) -> Path:
        return self.run_dir() / "sessions" / name

    def test_the_recorded_1740_denial_is_asked_again_once_with_the_call_and_the_sessions_tools(self):
        denial = json.loads(RESULT_DENIED_1740.read_text(encoding="utf-8"))["permission_denials"][0]
        listed = next(line for line in (REPO_ROOT / "home/common/claude-code/agents/reviewer.md")
                      .read_text(encoding="utf-8").splitlines() if line.startswith("tools:"))
        tools = [name.strip() for name in listed.removeprefix("tools:").split(",")]
        log = self.answers(
            canned_result(structured_output=self.verdict("revise"), duration_ms=1000, num_turns=3,
                          total_cost_usd=0.1, usage=self.USAGE, permission_denials=[denial]),
            canned_result(structured_output=self.verdict("approve"), duration_ms=2000, num_turns=4,
                          total_cost_usd=0.2, permission_denials=[], usage={
                              "input_tokens": 10, "cache_creation_input_tokens": 20,
                              "cache_read_input_tokens": 30, "output_tokens": 40}))

        done = self.project.deliver(self.review(), issue=self.ISSUE)

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        first, second = self.launches(log)
        self.assertEqual(after(second["argv"], "--resume"), after(first["argv"], "--session-id"))
        prompt = self.sessions("review.1.denied.prompt.md").read_text(encoding="utf-8")
        self.assertEqual(second["stdin"], prompt)
        self.assertIn(repr(denial["tool_input"]["command"]), prompt)
        for name in tools:
            with self.subTest(tool=name):
                self.assertIn(name, prompt)
        self.assertTrue(prompt.endswith(engine_session.REASK_REQUEST))
        for name, denials in (("review.1.json", [denial]), ("review.1.denied.json", [])):
            record = json.loads(self.sessions(name).read_text(encoding="utf-8"))
            self.assertEqual(record["denials"], denials, name)
        result = json.loads((self.run_dir() / "results/review.1.json").read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "approve")
        events = self.events()
        kinds = [event["event"] for event in events]
        self.assertIn("session_resuming", kinds)
        self.assertEqual([e["outcome"] for e in events
                          if e["event"] == "outcome_graded" and e["step"] == "review"], ["approve"])
        self.assertFalse([e for e in events if e["event"] == "stop_reached"
                          and e["stop"] == "tool-denied"])
        (stored,) = [e for e in events if e["event"] == "result_stored" and e["step"] == "review"]
        self.assertEqual(stored["turns"], 7)
        self.assertEqual(stored["tokens"], {"input": 11, "cache_write": 22, "cache_read": 33,
                                            "output": 44})
        self.assertAlmostEqual(stored["spend_usd"], 0.3)
        self.assertAlmostEqual(stored["wall_seconds"], 3.0)

    def test_a_second_denial_stops_at_tool_denied_naming_both_commands(self):
        first, second = bash("git log | head"), bash("git checkout main", "toolu_02")
        log = self.answers(
            canned_result(structured_output=self.verdict("approve"), permission_denials=[first]),
            canned_result(structured_output=self.verdict("approve"), permission_denials=[second]))

        done = self.project.deliver(self.review(), issue=self.ISSUE)

        line = self.stopped(done, self.ISSUE)
        self.assertEqual(len(self.launches(log)), 2)
        detail = line["detail"]
        self.assertLess(detail.index(repr("git log | head")), detail.index(repr("git checkout main")))
        for name, denial in (("review.1.json", first), ("review.1.denied.json", second)):
            record = json.loads(self.sessions(name).read_text(encoding="utf-8"))
            self.assertEqual(record["denials"], [denial], name)
        self.assertNotIn("outcome_graded", self.kinds())

    def test_a_call_denied_on_both_launches_is_named_once(self):
        first, second = bash("git log | head"), bash("rm x", "toolu_02")
        self.answers(
            canned_result(structured_output=self.verdict("approve"), permission_denials=[first]),
            canned_result(structured_output=self.verdict("approve"),
                          permission_denials=[first, second]))

        done = self.project.deliver(self.review(), issue=self.ISSUE)

        detail = self.stopped(done, self.ISSUE)["detail"]
        self.assertEqual(detail.count(repr("git log | head")), 1)
        self.assertLess(detail.index(repr("git log | head")), detail.index(repr("rm x")))
        self.assertTrue(detail.startswith("Step review was denied 2 tool calls"), detail)

    def test_a_miss_after_the_denial_reask_is_no_reply(self):
        log = self.answers(
            canned_result(structured_output=self.verdict("approve"),
                          permission_denials=[bash("git log | head")]),
            RESULT_MISSING.read_bytes())

        done = self.project.deliver(self.review(**{"no-reply": "step-failed"}), issue=self.ISSUE)

        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "step-failed")
        self.assertEqual(len(self.launches(log)), 2)
        self.assertTrue(self.sessions("review.1.denied.json").exists())
        self.assertEqual([e["outcome"] for e in self.events() if e["event"] == "outcome_graded"],
                         ["no-reply"])


class DenialPromptTest(unittest.TestCase):
    def test_the_prompt_names_each_call_in_order_and_each_tool_a_role_leaves_out(self):
        limited = engine_session.Role("implementer", "opus", "high", None, ("Workflow", "SendFeedback"), "")
        calls = ["git status --short", "rm -rf build"]

        prompt = engine_session.denial_prompt(limited, calls)

        self.assertLess(prompt.index(repr(calls[0])), prompt.index(repr(calls[1])))
        self.assertIn("Workflow", prompt)
        self.assertIn("SendFeedback", prompt)
        self.assertTrue(prompt.endswith(engine_session.REASK_REQUEST))


class FanOutDeniedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, "reviewer", "reviewer-lite")

    @staticmethod
    def answer(env, document: dict) -> None:
        Path(env[engine_session.ANSWER_ENV]).write_text(json.dumps(document))

    def denied(self, command: str) -> engine_session.Launched:
        return engine_session.Launched(
            0, canned_result(permission_denials=[bash(command)]), b"", 0.1)

    def by_session(self, launches):
        """A launch stand-in giving each child its own sequence: a launch with `--session-id` takes the next
        item and waits for the other child, one with `--resume` gets the item remembered under its session."""
        taken, remembered = threading.Lock(), {}
        both = threading.Barrier(2, timeout=60)

        def fake(argv, cwd, prompt, *, on_start, timeout=None, env=None, stop=None):
            resumed = "--resume" in argv
            session = after(argv, "--resume" if resumed else "--session-id")
            if not resumed:
                with taken:
                    remembered[session] = next(launches)
            on_start(os.getpid())
            if not resumed:
                both.wait()
            self.answer(env, {"account": "stub"})
            return remembered[session]
        return fake

    def test_two_group_members_denied_stop_the_run_at_tool_denied_naming_both(self):
        directory = with_session_files(self.project.procedures(REVIEWS()))
        commands = {"ra": "echo first", "rb": "echo second"}

        def fake(argv, cwd, prompt, *, on_start, timeout=None, env=None, stop=None):
            name = "ra" if argv[-1].endswith("ra.1.system.md") else "rb"
            on_start(os.getpid())
            self.answer(env, {"account": "stub"})
            return self.denied(commands[name])

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual((code, line["end"], line["need"]), (3, "tool-denied", "owner-decision"))
        for command in commands.values():
            self.assertIn(repr(command), line["detail"])
        (root,) = roots(self.project)
        events = self.project.events(root)
        self.assertEqual(events[-1]["event"], "stop_reached")
        self.assertEqual(events[-1]["stop"], "tool-denied")
        self.assertIn(events[-1]["step"], commands)
        self.assertEqual([e for e in events if e["event"] == "outcome_graded" and e["step"] == "reviews"], [])

    def test_two_child_runs_denied_stop_the_parent_at_tool_denied_naming_both(self):
        directory = self.project.procedures(FAN("standin-items", 2), children={
            "fan-child": child([
                {"id": "look", "stage": "building", "kind": "agent", "holds": "run", "role": "reviewer",
                 "prompt": "item.md", "reply": "draft.reply.json", "outcome_from": "status",
                 "in": ["run.item"],
                 "on": {"drafted": "done", "stuck": "child-stop", "no-reply": "child-stop",
                        "out-of-bounds": "child-stop"}}])})
        (directory / "item.md").write_text("Review item {{run.item}}.\n", encoding="utf-8")
        (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")
        fake = self.by_session(iter([self.denied("echo first"), self.denied("echo second")]))

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual((code, line["end"], line["need"]), (3, "tool-denied", "owner-decision"))
        for command in ("echo first", "echo second"):
            self.assertIn(repr(command), line["detail"])
        (root,) = roots(self.project)
        self.assertEqual(len(children_of(self.project)), 2)
        events = self.project.events(root)
        self.assertEqual((events[-1]["event"], events[-1]["stop"]), ("stop_reached", "tool-denied"))
        self.assertEqual([e for e in events if e["event"] in ("result_stored", "outcome_graded")
                          and e["step"] == "fan"], [])


    def test_a_call_cut_before_it_recorded_the_stop_walks_its_tool_denied_children_again(self):
        directory = self.project.procedures(FAN("standin-items", 2), children={
            "fan-child": child([
                {"id": "look", "stage": "building", "kind": "agent", "holds": "run", "role": "reviewer",
                 "prompt": "item.md", "reply": "draft.reply.json", "outcome_from": "status",
                 "in": ["run.item"],
                 "on": {"drafted": "done", "stuck": "child-stop", "no-reply": "child-stop",
                        "out-of-bounds": "child-stop"}}])})
        (directory / "item.md").write_text("Review item {{run.item}}.\n", encoding="utf-8")
        (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")
        both = threading.Barrier(2, timeout=60)
        denying = True

        def fake(argv, cwd, prompt, *, on_start, timeout=None, env=None, stop=None):
            on_start(os.getpid())
            self.answer(env, {"account": "stub"})
            if denying:
                both.wait()
                return self.denied("echo first")
            return engine_session.Launched(0, canned_result(), b"", 0.1)

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            code, line = engine_shell.deliver(1919, directory)
            self.assertEqual((code, line["end"]), (3, "tool-denied"))
            (root,) = roots(self.project)
            kids = children_of(self.project)
            self.assertEqual(len(kids), 2)
            # The engine was killed after each child stopped and before the parent recorded its own stop.
            path = root / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            self.assertEqual(json.loads(lines[-1])["event"], "stop_reached")
            path.write_text("".join(lines[:-1]), encoding="utf-8")
            denying = False

            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual((code, line["end"]), (0, "done"), line)
        events = self.project.events(root)
        # The two denied children are the ones the call named; only the third item, never started, is new.
        named = [e["child"] for e in events if e["event"] == "call"]
        self.assertEqual(sorted(named[:2]), sorted(kid.name for kid in kids))
        self.assertEqual(len(children_of(self.project)), 3)
        self.assertEqual(events[-1]["event"], "run_done")
        self.assertEqual([e["event"] for e in events].count("stop_reached"), 0)
        for kid in children_of(self.project):
            self.assertEqual(self.project.events(kid)[-1]["event"], "run_done", kid.name)

    def test_a_group_member_cut_after_its_first_denial_is_entered_again_and_asked_again_once_on_its_new_session(self):
        directory = with_session_files(self.project.procedures(REVIEWS()))
        def approving() -> engine_session.Launched:
            return engine_session.Launched(0, canned_result(), b"", 0.1)

        queues, launches = {}, []

        def fake(argv, cwd, prompt, *, on_start, timeout=None, env=None, stop=None):
            name = Path(argv[-1]).name.split(".")[0]
            launches.append((name, argv, prompt))
            on_start(os.getpid())
            self.answer(env, {"account": "stub"})
            return queues[name].pop(0)

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            queues.update(ra=[self.denied("git log | head"), approving()], rb=[approving()])
            code, line = engine_shell.deliver(1919, directory)
            self.assertEqual(code, 0, line)
            (root,) = roots(self.project)
            path = root / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            cut = next(i for i, text in enumerate(lines) if json.loads(text)["event"] == "session_answered"
                       and json.loads(text)["step"] == "ra") + 1
            path.write_text("".join(lines[:cut]), encoding="utf-8")
            (root / "results/ra.1.json").unlink()
            (root / "sessions/ra.1.denied.json").unlink()
            first = len(launches)
            queues.update(ra=[self.denied("rm x"), approving()], rb=[approving()])

            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual(code, 0, line)
        events = self.project.events(root)
        self.assertEqual(len([e for e in events if e["event"] == "run_continued"]), 1)
        original = after(next(argv for name, argv, _ in launches if name == "ra"), "--session-id")
        fresh, asked = [(argv, prompt) for name, argv, prompt in launches[first:] if name == "ra"]
        self.assertNotEqual(after(fresh[0], "--session-id"), original)
        self.assertEqual(after(asked[0], "--resume"), after(fresh[0], "--session-id"))
        self.assertIn(repr("rm x"), asked[1])
        self.assertNotIn(repr("git log | head"), asked[1])
        self.assertEqual([e for e in events if e["event"] == "stop_reached" and e["stop"] == "tool-denied"], [])

    def faulted(self) -> engine_session.Launched:
        return engine_session.Launched(1, b"", b"the client crashed\n", 0.1)

    def test_a_group_member_denied_beside_a_member_that_faults_still_stops_the_run_at_tool_denied(self):
        directory = with_session_files(self.project.procedures(REVIEWS()))

        def fake(argv, cwd, prompt, *, on_start, timeout=None, env=None, stop=None):
            name = "ra" if argv[-1].endswith("ra.1.system.md") else "rb"
            on_start(os.getpid())
            self.answer(env, {"account": "stub"})
            return self.denied("echo first") if name == "ra" else self.faulted()

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual((code, line["end"], line["need"]), (3, "tool-denied", "owner-decision"))
        self.assertIn(repr("echo first"), line["detail"])
        self.assertIn("the client crashed", line["detail"])
        (root,) = roots(self.project)
        events = self.project.events(root)
        self.assertEqual((events[-1]["event"], events[-1]["stop"]), ("stop_reached", "tool-denied"))

    def test_a_child_run_denied_beside_a_child_that_faults_still_stops_the_parent_at_tool_denied(self):
        directory = self.project.procedures(FAN("standin-items", 2), children={
            "fan-child": child([
                {"id": "look", "stage": "building", "kind": "agent", "holds": "run", "role": "reviewer",
                 "prompt": "item.md", "reply": "draft.reply.json", "outcome_from": "status",
                 "in": ["run.item"],
                 "on": {"drafted": "done", "stuck": "child-stop", "no-reply": "child-stop",
                        "out-of-bounds": "child-stop"}}])})
        (directory / "item.md").write_text("Review item {{run.item}}.\n", encoding="utf-8")
        (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")
        fake = self.by_session(iter([self.denied("echo first"), self.faulted()]))

        with self.project.inside(), mock.patch.object(engine_session, "launch", fake):
            code, line = engine_shell.deliver(1919, directory)

        self.assertEqual((code, line["end"], line["need"]), (3, "tool-denied", "owner-decision"))
        self.assertIn(repr("echo first"), line["detail"])
        self.assertIn("the client crashed", line["detail"])
        (root,) = roots(self.project)
        events = self.project.events(root)
        self.assertEqual((events[-1]["event"], events[-1]["stop"]), ("stop_reached", "tool-denied"))


class JoinedStopTest(unittest.TestCase):
    def test_a_denial_outranks_a_quota_wait_and_the_details_join_in_order(self):
        stop = engine_session.joined([engine_session.EngineStop("quota-wait", "retry", "q", "a"),
                                      engine_session.EngineStop("tool-denied", "owner-decision", "d", "b")])
        self.assertEqual((stop.name, stop.need, stop.step, stop.detail),
                         ("tool-denied", "owner-decision", "b", "q d"))

    def test_two_quota_waits_join_at_the_first(self):
        stop = engine_session.joined([engine_session.EngineStop("quota-wait", "retry", "q", "a"),
                                      engine_session.EngineStop("quota-wait", "retry", "r", "b")])
        self.assertEqual((stop.name, stop.need, stop.step), ("quota-wait", "retry", "a"))

    def test_a_fault_is_raised_before_any_stop(self):
        with self.assertRaises(RuntimeError):
            engine_session.raise_first([None, engine_session.EngineStop("quota-wait", "retry", "q", "a"),
                                        RuntimeError("x")])

    def test_a_denial_outranks_a_fault_and_the_stop_names_the_fault(self):
        with self.assertRaises(engine_session.EngineStop) as caught:
            engine_session.raise_first([RuntimeError("x"),
                                        engine_session.EngineStop("tool-denied", "owner-decision", "d", "a")])
        self.assertEqual((caught.exception.name, caught.exception.step), ("tool-denied", "a"))
        self.assertEqual(caught.exception.detail, "d Another member faulted: x")

    def test_a_stop_request_outranks_a_denial(self):
        with self.assertRaises(engine_stop.Stopped):
            engine_session.raise_first([engine_session.EngineStop("tool-denied", "owner-decision", "d", "a"),
                                        engine_stop.Stopped()])

    def test_no_error_returns(self):
        self.assertIsNone(engine_session.raise_first([None, None]))

    def test_two_stops_raise_one_holding_both(self):
        with self.assertRaises(engine_session.EngineStop) as caught:
            engine_session.raise_first([engine_session.EngineStop("tool-denied", "owner-decision", "d1", "a"),
                                        engine_session.EngineStop("tool-denied", "owner-decision", "d2", "b")])
        self.assertEqual(caught.exception.detail, "d1 d2")


class BlockedReplyTest(Scenario):
    def test_a_blocked_implement_reply_stops_the_delivery_at_task(self):
        blocked = {"status": "blocked", "start_head": SHA, "commit": SHA, "notes": "no shell",
                   "acceptance": [], "sensitive": False, "ineligible": False, "tests": []}
        run = self.stubbed(replies={"implement": blocked})

        done = run.deliver()

        self.stopped(run, done, "task", "owner-decision")
        (root,) = run.runs()
        last = run.events(root)[-1]
        self.assertEqual((last["event"], last["stop"]), ("stop_reached", "task"))
        direct = self.child(run, "direct")
        last = run.events(direct)[-1]
        self.assertEqual((last["event"], last["stop"]), ("stop_reached", "task"))
        status = json.loads(run.status().stdout)
        self.assertEqual(status["stop"]["name"], "task")


if __name__ == "__main__":
    unittest.main()
