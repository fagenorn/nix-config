"""Contract tests for the keep-alive of `engine deliver` (#1518): the claim is renewed before each
`mutates` command step, and a claim that is not renewed ends the run at `claim-lost`.

The keep-alive and every step run the stand-in project command
(tests/fixtures/engine-deliver/standin.py): its `answers` mode plays one scripted answer per call.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from agent_tools.delivery import engine_shell
from tests.engine_guards import standin_guard
from tests.test_engine_deliver import ANY_SENTENCE, EngineProject, step
from tests.test_engine_fanout import GROUP, stamps
from tests.test_engine_session import DRAFT_REPLY, RESULT_NORMAL, agent_step, copy_roles, install_stub

TIER = "integration"  # every case runs `engine deliver` against the stand-in command

KEEP_ALIVE = {"command": "standin-keep-alive", "in": ["run.issue"]}
RENEWED = {"stdout": '{"verdict":"renewed"}', "exit": 0}


def guarded(events: list[dict]) -> list[tuple]:
    return [(e["event"], e["step"], e["visit"]) for e in events
            if e["event"] in ("keep_alive_ran", "step_entered")]


class KeepAliveTest(unittest.TestCase):
    def stopped(self, project: EngineProject, procedures, *, calls: int = 1) -> tuple[dict, list]:
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "claim-lost")
        ANY_SENTENCE(self, line["detail"])
        self.assertEqual(len(project.renewal_calls()), calls)
        return line, project.events(project.runs()[0])

    def test_the_keep_alive_runs_once_before_each_visit_of_each_mutating_step_and_no_other(self):
        project = EngineProject(self)
        project.answer(RENEWED)
        procedures = project.procedures([
            step("a", "standin-record", "b"),
            step("b", "standin-record", None, mutates=True, max_visits=2,
                 on={"ok": "c", "failed": "needs-owner", "refused": "needs-owner", "exhausted": "d"}),
            step("c", "standin-record", None, max_visits=2,
                 on={"ok": "b", "failed": "needs-owner", "refused": "needs-owner", "exhausted": "d"}),
            step("d", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE)
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual(guarded(events), [
            ("step_entered", "a", 1), ("keep_alive_ran", "b", 1), ("step_entered", "b", 1),
            ("step_entered", "c", 1), ("keep_alive_ran", "b", 2), ("step_entered", "b", 2),
            ("step_entered", "c", 2), ("keep_alive_ran", "d", 1), ("step_entered", "d", 1)])
        kept = [e for e in events if e["event"] == "keep_alive_ran"]
        self.assertEqual({(e["attempt"], e["verdict"]) for e in kept}, {(1, "renewed")})
        self.assertEqual(project.renewal_calls(), [{"argv": ["1512"]}] * 3)

    def test_a_procedure_with_no_keep_alive_runs_none(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(
            [step("a", "standin-record", "done", mutates=True)]))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual([e for e in events if e["event"] == "keep_alive_ran"], [])
        self.assertEqual(project.renewal_calls(), [])
        self.assertEqual(guarded(events), [("step_entered", "a", 1)])

    def test_a_keep_alive_that_stops_renewing_ends_the_run_in_claim_lost_before_the_second_step(self):
        project = EngineProject(self)
        project.answer(RENEWED, {"stdout": '{"by":"other/holder","verdict":"not_held"}', "exit": 0},
                       RENEWED)
        procedures = project.procedures([
            step("a", "standin-record", "b", mutates=True),
            step("b", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE)
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        run = project.runs()[0]
        line = json.loads(done.stdout)
        detail = line.pop("detail")
        self.assertEqual(line, {"end": "claim-lost", "need": "owner-decision", "run": run.name})
        ANY_SENTENCE(self, detail)
        for word in ("not_held", "other/holder", "b"):
            self.assertIn(word, detail)
        events = project.events(run)
        self.assertEqual(guarded(events), [("keep_alive_ran", "a", 1), ("step_entered", "a", 1),
                                           ("keep_alive_ran", "b", 1)])
        self.assertEqual([e["verdict"] for e in events if e["event"] == "keep_alive_ran"],
                         ["renewed", "not_held"])
        last = events[-1]
        self.assertEqual((last["event"], last["step"], last["stop"], last["need"]),
                         ("stop_reached", "b", "claim-lost", "owner-decision"))
        self.assertEqual(len(project.record.read_text(encoding="utf-8").splitlines()), 1)
        state = json.loads(project.status(1512).stdout)
        self.assertEqual(state["stop"], {"name": "claim-lost", "need": "owner-decision"})

    def test_each_failure_of_the_keep_alive_ends_in_claim_lost_before_the_step_starts(self):
        cases = {
            "another verdict": (
                {"stdout": '{"detail":"marker-verdict","verdict":"not_held"}', "exit": 0},
                "not_held", "marker-verdict"),
            "a non-zero exit": (
                {"stdout": '{"detail":"marker-exit","verdict":"renewed"}', "exit": 1},
                "failed", "marker-exit"),
            "output that is not JSON": (
                {"stdout": "renewed marker-text", "exit": 0}, "ok", "marker-text"),
            "no output": ({"stdout": "", "exit": 0}, "ok", "no output"),
            "a diagnostic on stderr only": (
                {"stdout": "", "stderr": "marker-stderr\n", "exit": 1}, "failed", "marker-stderr"),
            "a non-transient error": (
                {"stdout": '{"detail":"marker-error","transient":false,"verdict":"error"}',
                 "exit": 1}, "error", "marker-error"),
        }
        for name, (answer, verdict, marker) in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.answer(answer, RENEWED)
                line, events = self.stopped(project, project.procedures(
                    [step("a", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE))
                self.assertIn(verdict, line["detail"])
                self.assertIn(marker, line["detail"])
                if name == "a diagnostic on stderr only":
                    self.assertNotIn("no output", line["detail"])
                kept = [e for e in events if e["event"] == "keep_alive_ran"]
                self.assertEqual([(e["attempt"], e["verdict"]) for e in kept], [(1, verdict)])
                self.assertEqual([e for e in events if e["event"] == "step_entered"], [])
                self.assertFalse(project.record.exists())

    def test_a_keep_alive_past_its_timeout_ends_in_claim_lost(self):
        project = EngineProject(self)
        project.answer({"stdout": '{"detail":"marker-timeout","verdict":"renewed"}',
                        "sleep": 60, "exit": 0})
        procedures = project.procedures([step("a", "standin-record", "done", mutates=True)],
                                        keep_alive=KEEP_ALIVE)
        started = time.monotonic()
        with project.inside(), mock.patch.object(engine_shell, "KEEP_ALIVE_SECONDS", 2):
            code, line = engine_shell.deliver(1512, procedures)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, engine_shell.EXIT_STOP)
        self.assertEqual(line["end"], "claim-lost")
        self.assertIn("timeout", line["detail"])
        self.assertIn("marker-timeout", line["detail"])
        events = project.events(project.runs()[0])
        self.assertEqual([e["verdict"] for e in events if e["event"] == "keep_alive_ran"],
                         ["timeout"])
        self.assertEqual([e for e in events if e["event"] == "step_entered"], [])
        self.assertFalse(project.record.exists())

    def test_a_transient_error_is_called_exactly_once_more(self):
        transient = {"stdout": '{"detail":"marker-transient","transient":true,"verdict":"error"}',
                     "exit": 1}
        steps = lambda: [step("a", "standin-record", "done", mutates=True)]  # noqa: E731
        with self.subTest("renewed on the second call"):
            project = EngineProject(self)
            project.answer(transient, RENEWED)
            done = project.deliver(project.procedures(steps(), keep_alive=KEEP_ALIVE))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            events = project.events(project.runs()[0])
            kept = [e for e in events if e["event"] == "keep_alive_ran"]
            self.assertEqual([(e["attempt"], e["verdict"]) for e in kept],
                             [(1, "error"), (2, "renewed")])
            self.assertEqual({(e["step"], e["visit"]) for e in kept}, {("a", 1)})
            self.assertEqual([e for e in events if e["event"] == "step_entered"][0]["step"], "a")
            self.assertEqual(len([e for e in events if e["event"] == "step_entered"]), 1)
        with self.subTest("a second transient error stands"):
            project = EngineProject(self)
            project.answer(transient, transient, RENEWED)
            line, events = self.stopped(
                project, project.procedures(steps(), keep_alive=KEEP_ALIVE), calls=2)
            kept = [e for e in events if e["event"] == "keep_alive_ran"]
            self.assertEqual([e["attempt"] for e in kept], [1, 2])
            self.assertIn("marker-transient", line["detail"])
            self.assertEqual([e for e in events if e["event"] == "step_entered"], [])
        not_transient = {
            "a string flag": '{"detail":"marker-string","transient":"true","verdict":"error"}',
            "transient on another verdict":
                '{"detail":"marker-not-held","transient":true,"verdict":"not_held"}',
        }
        for name, stdout in not_transient.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.answer({"stdout": stdout, "exit": 1 if "string" in name else 0}, RENEWED)
                line, events = self.stopped(
                    project, project.procedures(steps(), keep_alive=KEEP_ALIVE))
                kept = [e for e in events if e["event"] == "keep_alive_ran"]
                self.assertEqual(len(kept), 1)
                self.assertEqual(kept[0]["verdict"], "error" if "string" in name else "not_held")

    def test_a_refused_renewal_stops_at_claim_lost_with_the_guard_reason_and_the_step_never_starts(self):
        project = EngineProject(self)
        project.answer(RENEWED)
        log = project.tmp / "refuse.log"
        project.use_guard(standin_guard(project.tmp, "g", "only", str(project.answers), "refuse",
                                        str(log), "lifecycle guard: refused by the stand-in."))
        procedures = project.procedures(
            [step("a", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE)
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "claim-lost")
        ANY_SENTENCE(self, line["detail"])
        self.assertIn("lifecycle guard: refused by the stand-in.", line["detail"])
        self.assertEqual(project.renewal_calls(), [])
        self.assertFalse(project.record.exists())
        events = project.events(project.runs()[0])
        self.assertEqual([e for e in events if e["event"] in
                          ("step_entered", "process_started", "result_stored")], [])

    def test_a_renewal_that_itself_answers_refused_stops_at_claim_lost_with_its_output(self):
        project = EngineProject(self)
        project.answer({"stdout": '{"verdict":"refused"}', "exit": 0})
        line, events = self.stopped(project, project.procedures(
            [step("a", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE))
        self.assertIn('{"verdict":"refused"}', line["detail"])
        kept = [e for e in events if e["event"] == "keep_alive_ran"]
        self.assertEqual([e["verdict"] for e in kept], ["refused"])
        self.assertFalse(project.record.exists())
        self.assertEqual([e for e in events if e["event"] == "step_entered"], [])


class GroupKeepAliveTest(unittest.TestCase):
    """A group with a `mutates` member renews the claim once before its members start."""

    def group(self, *, mutating: bool) -> list[dict]:
        steps = GROUP("standin-stamp")
        if mutating:
            steps[1]["mutates"] = True
            steps[1]["check"] = {"command": "standin-stamp"}
        return steps

    def test_a_group_with_a_mutating_member_renews_once_before_either_member_starts(self):
        project = EngineProject(self)
        project.answer(RENEWED)
        done = project.deliver(project.procedures(self.group(mutating=True), keep_alive=KEEP_ALIVE),
                               issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        events = project.events(project.runs()[0])
        self.assertEqual(guarded(events)[:2], [("keep_alive_ran", "checks", 1),
                                               ("step_entered", "checks", 1)])
        self.assertEqual(sorted(guarded(events)[2:]), [("step_entered", "a", 1),
                                                       ("step_entered", "b", 1)])
        self.assertEqual([e["event"] for e in events].index("keep_alive_ran"), 0)
        self.assertEqual(len(project.renewal_calls()), 1)
        self.assertEqual(len(stamps(project)), 2)

    def test_a_group_with_a_mutating_member_ends_in_claim_lost_when_the_claim_is_not_renewed(self):
        project = EngineProject(self)
        project.answer({"stdout": '{"by":"other/holder","verdict":"not_held"}', "exit": 0}, RENEWED)
        done = project.deliver(project.procedures(self.group(mutating=True), keep_alive=KEEP_ALIVE),
                               issue=1517)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "claim-lost")
        self.assertIn("not_held", line["detail"])
        self.assertIn("checks", line["detail"])
        events = project.events(project.runs()[0])
        self.assertEqual(guarded(events), [("keep_alive_ran", "checks", 1)])
        self.assertEqual(events[-1]["event"], "stop_reached")
        self.assertEqual(len(project.renewal_calls()), 1)
        self.assertFalse(project.stamps.exists())

    def test_a_group_with_no_mutating_member_renews_nothing(self):
        project = EngineProject(self)
        done = project.deliver(project.procedures(self.group(mutating=False), keep_alive=KEEP_ALIVE),
                               issue=1517)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(guarded(project.events(project.runs()[0]))[0], ("step_entered", "checks", 1))
        self.assertEqual(project.renewal_calls(), [])


class ShapeTest(unittest.TestCase):
    def test_the_keep_alive_timeout_is_twenty_minutes(self):
        self.assertEqual(engine_shell.KEEP_ALIVE_SECONDS, 1200)


class MutatingAgentStepTest(unittest.TestCase):
    """A `mutates` agent step renews the claim before its session starts, once per visit."""

    def run_draft(self, answer: dict) -> tuple[EngineProject, object, list]:
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        log = install_stub(project, RESULT_NORMAL)
        project.answer(answer)
        draft = agent_step("draft", "implementer", {"drafted": "done", "stuck": "needs-owner"},
                           mutates=True)
        directory = project.procedures(
            [draft], keep_alive=KEEP_ALIVE,
            stops={"needs-owner": {"need": "owner-decision", "reenter": "draft"},
                   "step-failed": {"need": "retry", "reenter": "draft"},
                   "claim-lost": {"need": "owner-decision", "reenter": "draft"}})
        (directory / "draft.md").write_text("Draft issue {{run.issue}}.\n", encoding="utf-8")
        (directory / "draft.reply.json").write_text(json.dumps(DRAFT_REPLY), encoding="utf-8")
        done = project.deliver(directory)
        return project, done, log

    def test_a_mutating_agent_step_renews_the_claim_before_its_session(self):
        project, done, _ = self.run_draft(RENEWED)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        events = project.events(project.runs()[0])
        (kept,) = [e for e in events if e["event"] == "keep_alive_ran"]
        self.assertEqual((kept["step"], kept["visit"], kept["verdict"]), ("draft", 1, "renewed"))
        starting = [e for e in events if e["event"] == "session_starting" and e["step"] == "draft"]
        self.assertEqual(len(starting), 1)
        self.assertLess(events.index(kept), events.index(starting[0]))

    def test_a_mutating_agent_step_whose_claim_is_not_renewed_ends_at_claim_lost_without_a_session(self):
        project, done, log = self.run_draft({"stdout": '{"verdict":"not_held"}', "exit": 0})
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "claim-lost")
        events = project.events(project.runs()[0])
        self.assertEqual([e for e in events if e["event"] == "session_starting"], [])
        self.assertTrue(not log.exists() or log.read_text(encoding="utf-8") == "")
