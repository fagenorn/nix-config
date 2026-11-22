"""Contract tests for `engine deliver` against a usage limit and an API error (#1521, #1525).

Split from tests/test_engine_session.py to hold that file under the 1,500-line rule (B17): the
helpers, fixtures and the stand-in launcher are the ones that file defines.
"""

from __future__ import annotations

import json
import socket
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_session, engine_shell
from tests.test_engine_deliver import EngineProject, shape
from tests.test_engine_session import (
    REVIEW_REPLY, RESULT_API_ERROR, RESULT_LIMIT, RESULT_NORMAL, ROLE_NAMES, after, agent_step,
    canned_result, copy_roles, install_answers, install_stub, one_step, write_procedures,
)

TIER = "integration"

QUOTA_RESET = "2030-03-17T17:46:40Z"


class DeliverLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, *ROLE_NAMES)

    def log(self, log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def run_dir(self) -> Path:
        (run,) = self.project.runs()
        return run

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.project.events(self.run_dir()) if e["event"] == kind]

    def canned(self, name: str, data: bytes) -> str:
        path = self.project.tmp / name
        path.write_bytes(data)
        return str(path)

    def limit(self, account: str) -> dict:
        return {"stdout": str(RESULT_LIMIT), "exit": 1, "account": account}

    def normal(self, account: str | None) -> dict:
        return {"stdout": str(RESULT_NORMAL), "exit": 0, "account": account}

    def all_out(self, resumes_at: str | None = QUOTA_RESET) -> dict:
        return {"stdout": self.canned("empty.json", b""), "exit": 75, "account": None,
                "all_out": {"resumes_at": resumes_at}}

    def limit_then_reply(self) -> tuple[Path, Path]:
        log = install_answers(self.project, [self.limit("p1"), self.normal("p2")])
        return log, one_step(self.project)

    def test_a_limit_then_a_reply_resumes_the_same_session_in_one_visit_on_the_answering_account(self):
        log, procedures = self.limit_then_reply()
        done = self.project.deliver(procedures, issue=1521)
        self.assertEqual(done.returncode, 0, done.stderr)
        run = self.run_dir()
        records = self.log(log)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["answer_file"] for record in records))
        first, second = (record["argv"] for record in records)
        session = after(first, "--session-id")
        self.assertNotIn("--resume", first)
        self.assertEqual(after(second, "--resume"), session)
        self.assertNotIn("--session-id", second)
        prompt = (run / "sessions/draft.1.prompt.md").read_text(encoding="utf-8")
        self.assertEqual([record["stdin"] for record in records], [prompt, prompt])
        events = self.project.events(run)
        self.assertEqual(shape(events), [
            ("step_entered", "draft", 1), ("session_starting", "draft", 1),
            ("process_started", "draft", 1), ("session_answered", "draft", 1),
            ("wait_started", None, None), ("session_resuming", "draft", 1),
            ("process_started", "draft", 1), ("session_answered", "draft", 1),
            ("wait_ended", None, None), ("result_stored", "draft", 1),
            ("outcome_graded", "draft", 1), ("transition_taken", "draft", 1),
            ("run_done", None, None)])
        (started,) = [e for e in events if e["event"] == "wait_started"]
        self.assertEqual((started["wait"], started["until"]), ("usage-limit", None))
        (ended,) = [e for e in events if e["event"] == "wait_ended"]
        self.assertEqual(ended["wait"], "usage-limit")
        self.assertIsNone(json.loads(self.project.status(1521).stdout)["wait"])
        answered = [e for e in events if e["event"] == "session_answered"]
        self.assertEqual([e["account"] for e in answered], ["p1", "p2"])
        self.assertEqual([e["attempt"] for e in answered], [1, 2])
        (resuming,) = [e for e in events if e["event"] == "session_resuming"]
        self.assertEqual(resuming["attempt"], 2)
        for event in (*answered, resuming):
            self.assertEqual(event["session"], session)
        record = json.loads((run / "sessions/draft.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["session"], session)
        (graded,) = [e for e in events if e["event"] == "outcome_graded"]
        self.assertEqual(graded["outcome"], "drafted")

    def test_an_all_out_answer_stops_the_run_at_quota_wait_with_the_resume_time(self):
        install_answers(self.project, [self.all_out()])
        done = self.project.deliver(one_step(self.project), issue=1521)
        self.assertEqual(done.returncode, 3, done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual((line["end"], line["need"]), ("quota-wait", "retry"))
        self.assertIn(QUOTA_RESET, line["detail"])
        events = self.project.events(self.run_dir())
        kinds = [e["event"] for e in events]
        self.assertNotIn("session_answered", kinds)
        self.assertNotIn("result_stored", kinds)
        waited, stopped = events[-2:]
        self.assertEqual((waited["event"], waited["wait"], waited["until"]),
                         ("wait_started", "usage-limit", QUOTA_RESET))
        self.assertEqual((stopped["event"], stopped["step"], stopped["stop"], stopped["need"]),
                         ("stop_reached", "draft", "quota-wait", "retry"))
        status = json.loads(self.project.status(1521).stdout)
        self.assertEqual(status["wait"]["until"], QUOTA_RESET)
        self.assertEqual(status["stop"]["name"], "quota-wait")

    def test_an_all_out_answer_needs_both_the_document_and_exit_75(self):
        empty = self.canned("empty.json", b"")
        with self.subTest("document, exit 1"):
            install_answers(self.project, [{"stdout": empty, "exit": 1, "account": None,
                                            "all_out": {"resumes_at": None}}])
            done = self.project.deliver(one_step(self.project), issue=1521)
            self.assertEqual(done.returncode, 1)
            self.assertIn("no structured reply, exit 1", done.stderr)
            self.assertEqual(self.events("stop_reached"), [])
            self.assertEqual([e["account"] for e in self.events("session_answered")],
                             ["unknown"])
        with self.subTest("exit 75, account document"):
            self.project = EngineProject(self)
            self.project.env.pop("CLAUDE_ACCOUNT", None)
            copy_roles(self.project, *ROLE_NAMES)
            install_answers(self.project, [{"stdout": empty, "exit": 75, "account": "p1"}])
            done = self.project.deliver(one_step(self.project), issue=1521)
            self.assertEqual(done.returncode, 1)
            self.assertIn("exit 75", done.stderr)
            self.assertEqual(self.events("stop_reached"), [])

    def test_a_limit_then_all_out_reopens_the_wait_with_the_resume_time(self):
        log = install_answers(self.project, [self.limit("p1"), self.all_out()])
        done = self.project.deliver(one_step(self.project), issue=1521)
        self.assertEqual(done.returncode, 3, done.stderr)
        events = self.project.events(self.run_dir())
        self.assertEqual(
            [(e["event"], e.get("until", "-")) for e in events
             if e["event"] in ("wait_started", "wait_ended", "stop_reached")],
            [("wait_started", None), ("wait_ended", "-"), ("wait_started", QUOTA_RESET),
             ("stop_reached", "-")])
        records = self.log(log)
        self.assertEqual(len(records), 2)
        self.assertEqual(after(records[1]["argv"], "--resume"),
                         after(records[0]["argv"], "--session-id"))

    def test_an_account_that_answers_a_limit_twice_stops_the_run_at_quota_wait(self):
        log = install_answers(self.project, [self.limit("p1"), self.limit("p2"),
                                             self.limit("p1"), self.normal("p3")])
        done = self.project.deliver(one_step(self.project), issue=1521)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(len(self.log(log)), 3)
        self.assertEqual(json.loads(done.stdout)["end"], "quota-wait")
        self.assertEqual(len(self.events("wait_started")), 1)
        self.assertEqual(self.events("wait_ended"), [])
        status = json.loads(self.project.status(1521).stdout)
        self.assertEqual(status["wait"]["wait"], "usage-limit")
        self.assertIsNone(status["wait"]["until"])
        self.assertEqual(status["stop"]["name"], "quota-wait")

    def test_an_inherited_account_override_is_released_after_a_limit(self):
        self.project.env["CLAUDE_ACCOUNT"] = "p1"
        log, procedures = self.limit_then_reply()
        done = self.project.deliver(procedures, issue=1521)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([r["account_env"] for r in self.log(log)], ["p1", None])
        (starting,) = self.events("session_starting")
        self.assertEqual(starting["account"], "p1")
        self.assertEqual([e["account"] for e in self.events("session_answered")], ["p1", "p2"])
        (graded,) = self.events("outcome_graded")
        self.assertEqual(graded["outcome"], "drafted")

    def test_a_denied_shell_command_beside_a_limit_is_a_fault_not_a_relaunch(self):
        denial = {"tool_name": "Bash", "tool_use_id": "toolu_02",
                  "tool_input": {"command": "PYTHONPATH=python python3 -m unittest tests.test_x"}}
        limited = self.canned("denied.json", canned_result(
            is_error=True, api_error_status=429, api_error="usage_limit_reached",
            structured_output=..., permission_denials=[denial]))
        log = install_answers(self.project, [
            {"stdout": limited, "exit": 1, "account": "p1"}, self.normal("p2")])
        steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner"},
                            prompt="review.md", reply="review.reply.json",
                            outcome_from="verdict")]
        procedures = write_procedures(self.project, steps, {
            "review.md": "Review {{run.issue}}.\n",
            "review.reply.json": json.dumps(REVIEW_REPLY)})
        done = self.project.deliver(procedures, issue=1521)
        self.assertEqual(done.returncode, 1)
        self.assertIn("python3 -m unittest tests.test_x", done.stderr)
        self.assertEqual(len(self.log(log)), 1)
        self.assertEqual(self.events("wait_started"), [])
        record = json.loads((self.run_dir() / "sessions/review.1.json").read_text(
            encoding="utf-8"))
        self.assertEqual(record["denials"], [denial])

    def test_a_launch_with_no_answer_file_is_answered_by_unknown(self):
        install_answers(self.project, [self.normal(None)])
        done = self.project.deliver(one_step(self.project), issue=1521)
        self.assertEqual(done.returncode, 0, done.stderr)
        (answered,) = self.events("session_answered")
        self.assertEqual(answered["account"], "unknown")

    def test_a_launcher_that_cannot_start_is_a_fault_with_its_diagnostic_and_no_answer(self):
        install_stub(self.project, RESULT_NORMAL)
        procedures = one_step(self.project)
        with self.project.inside(), mock.patch.object(
                engine_session, "LAUNCHER", ("/nonexistent/claude-account", "run")):
            with self.assertRaises(engine_shell.Fault) as raised:
                engine_shell.deliver(1521, procedures)
        self.assertIn("exit 127", str(raised.exception))
        self.assertIn("/nonexistent/claude-account", str(raised.exception))
        kinds = [e["event"] for e in self.project.events(self.run_dir())]
        self.assertNotIn("process_started", kinds)
        self.assertNotIn("session_answered", kinds)

    def test_handling_a_limit_opens_no_connection(self):
        log, procedures = self.limit_then_reply()
        with self.project.inside(), \
                mock.patch.object(socket.socket, "connect", side_effect=OSError("no socket")) as connect, \
                mock.patch.object(socket.socket, "connect_ex", side_effect=OSError("no socket")) as connect_ex, \
                mock.patch.object(socket, "create_connection", side_effect=OSError("no socket")) as create:
            code, line = engine_shell.deliver(1521, procedures)
        self.assertEqual(code, 0, line)
        self.assertEqual(line["end"], "done")
        self.assertEqual((connect.call_count, connect_ex.call_count, create.call_count), (0, 0, 0))
        self.assertEqual(len(self.log(log)), 2)


class DeliverApiErrorTest(unittest.TestCase):
    NO_REPLY_ON = {"drafted": "done", "stuck": "needs-owner", "no-reply": "needs-owner"}

    def setUp(self) -> None:
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, *ROLE_NAMES)

    def log(self, log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def run_dir(self) -> Path:
        (run,) = self.project.runs()
        return run

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.project.events(self.run_dir()) if e["event"] == kind]

    def api_error(self, account: str = "p1") -> dict:
        return {"stdout": str(RESULT_API_ERROR), "exit": 1, "account": account}

    def limit(self, account: str = "p1") -> dict:
        return {"stdout": str(RESULT_LIMIT), "exit": 1, "account": account}

    def normal(self, account: str = "p1") -> dict:
        return {"stdout": str(RESULT_NORMAL), "exit": 0, "account": account}

    def canned(self, name: str, data: bytes) -> str:
        path = self.project.tmp / name
        path.write_bytes(data)
        return str(path)

    def deliver(self, log: Path, procedures: Path) -> tuple[int, dict, list[tuple[float, int]]]:
        """`engine_shell.deliver` in process, with each sleep recorded as (seconds, invocations so far)."""
        sleeps: list[tuple[float, int]] = []

        def record(seconds: float) -> None:
            sleeps.append((seconds, len(log.read_text(encoding="utf-8").splitlines())))

        # Only the engine's own clock is replaced: patching `time.sleep` itself would also record
        # the polling `subprocess` does while it reaps a launcher that is slow to exit.
        clock = mock.Mock(wraps=time, sleep=record)
        with self.project.inside(), mock.patch.object(engine_shell, "time", clock):
            code, line = engine_shell.deliver(1521, procedures)
        return code, line, sleeps

    def test_an_api_error_is_retried_once_after_thirty_seconds_on_the_same_session(self):
        log = install_answers(self.project, [self.api_error(), self.normal()])
        code, line, sleeps = self.deliver(log, one_step(self.project))
        self.assertEqual(code, 0, line)
        self.assertEqual(sleeps, [(30, 1)])
        records = self.log(log)
        self.assertEqual(len(records), 2)
        first, second = (record["argv"] for record in records)
        session = after(first, "--session-id")
        self.assertNotIn("--resume", first)
        self.assertEqual(after(second, "--resume"), session)
        self.assertEqual(len(self.events("step_entered")), 1)
        self.assertEqual(self.events("wait_started"), [])
        (graded,) = self.events("outcome_graded")
        self.assertEqual(graded["outcome"], "drafted")
        (resuming,) = self.events("session_resuming")
        self.assertEqual(resuming["attempt"], 2)

    def test_a_sleep_outside_the_engine_is_not_one_of_its_waits(self):
        log = install_answers(self.project, [self.api_error(), self.normal()])
        launch = engine_session.launch

        def slow_to_exit(*args, **kwargs):
            launched = launch(*args, **kwargs)
            time.sleep(0.001)  # what `subprocess` does while it reaps a launcher
            return launched

        with mock.patch.object(engine_session, "launch", side_effect=slow_to_exit):
            code, line, sleeps = self.deliver(log, one_step(self.project))
        self.assertEqual(code, 0, line)
        self.assertEqual(sleeps, [(30, 1)])

    def test_a_second_api_error_is_the_outcome_no_reply(self):
        log = install_answers(self.project, [self.api_error(), self.api_error(), self.normal()])
        code, line, sleeps = self.deliver(log, one_step(self.project, on=self.NO_REPLY_ON))
        self.assertEqual(code, 3, line)
        self.assertEqual(line["end"], "needs-owner")
        self.assertEqual(len(self.log(log)), 2)
        self.assertEqual(sleeps, [(30, 1)])
        run = self.run_dir()
        events = self.project.events(run)
        self.assertEqual(
            [e["event"] for e in events if e["event"] in (
                "result_stored", "outcome_graded", "transition_taken")],
            ["result_stored", "outcome_graded", "transition_taken"])
        (stored,) = [e for e in events if e["event"] == "result_stored"]
        self.assertEqual(json.loads((run / "results/draft.1.json").read_text(encoding="utf-8")), {})
        self.assertEqual(stored["wall_seconds"], 1.5)
        (graded,) = [e for e in events if e["event"] == "outcome_graded"]
        self.assertEqual(graded["outcome"], "no-reply")
        (taken,) = [e for e in events if e["event"] == "transition_taken"]
        self.assertEqual((taken["outcome"], taken["to"]), ("no-reply", "needs-owner"))

    def test_a_no_reply_keeps_a_measured_duration_of_zero(self):
        failed = self.canned("zero.json", canned_result(
            is_error=True, api_error_status=529, api_error="overloaded_error",
            structured_output=..., duration_ms=0))
        entry = {"stdout": failed, "exit": 1, "account": "p1"}
        log = install_answers(self.project, [entry, entry])
        code, line, _ = self.deliver(log, one_step(self.project, on=self.NO_REPLY_ON))
        self.assertEqual(code, 3, line)
        (stored,) = self.events("result_stored")
        self.assertEqual(stored["wall_seconds"], 0.0)

    def test_a_limit_after_an_api_error_still_resumes(self):
        log = install_answers(self.project, [self.api_error(), self.limit(), self.normal("p2")])
        code, line, sleeps = self.deliver(log, one_step(self.project))
        self.assertEqual(code, 0, line)
        self.assertEqual(len(self.log(log)), 3)
        self.assertEqual(sleeps, [(30, 1)])
        (graded,) = self.events("outcome_graded")
        self.assertEqual(graded["outcome"], "drafted")
        self.assertEqual(len(self.events("wait_started")), 1)
        self.assertEqual(len(self.events("wait_ended")), 1)

    def test_a_limit_an_api_error_and_a_limit_on_the_same_account_stop_with_the_wait_open(self):
        log = install_answers(self.project, [
            self.limit(), self.api_error(), self.limit(), self.normal()])
        code, line, sleeps = self.deliver(log, one_step(self.project))
        self.assertEqual(code, 3, line)
        self.assertEqual(line["end"], "quota-wait")
        self.assertEqual(len(self.log(log)), 3)
        self.assertEqual(sleeps, [(30, 2)])
        self.assertEqual(len(self.events("wait_started")), 1)
        self.assertEqual(self.events("wait_ended"), [])
        status = json.loads(self.project.status(1521).stdout)
        self.assertEqual(status["wait"]["wait"], "usage-limit")
        self.assertIsNone(status["wait"]["until"])
        self.assertEqual(status["stop"]["name"], "quota-wait")

    def test_a_denied_shell_command_beside_an_api_error_is_a_fault_before_any_retry(self):
        denial = {"tool_name": "Bash", "tool_use_id": "toolu_02",
                  "tool_input": {"command": "PYTHONPATH=python python3 -m unittest tests.test_x"}}
        failed = self.canned("denied.json", canned_result(
            is_error=True, api_error_status=529, api_error="overloaded_error",
            structured_output=..., permission_denials=[denial]))
        log = install_answers(self.project, [
            {"stdout": failed, "exit": 1, "account": "p1"}, self.normal()])
        steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner"},
                            prompt="review.md", reply="review.reply.json",
                            outcome_from="verdict")]
        procedures = write_procedures(self.project, steps, {
            "review.md": "Review {{run.issue}}.\n",
            "review.reply.json": json.dumps(REVIEW_REPLY)})
        with self.assertRaises(engine_shell.Fault) as raised:
            self.deliver(log, procedures)
        self.assertIn("python3 -m unittest tests.test_x", str(raised.exception))
        self.assertEqual(len(self.log(log)), 1)
        record = json.loads((self.run_dir() / "sessions/review.1.json").read_text(
            encoding="utf-8"))
        self.assertEqual(record["denials"], [denial])
