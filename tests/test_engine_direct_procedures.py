"""The shipped `direct` and `verify` procedures: their shape, their prompts and their review bounds."""

from __future__ import annotations

import json
import re
import unittest

from agent_tools.delivery import engine_core, engine_session
from agent_tools.delivery.engine_core import RunGroup, Stop
from tests.test_engine_check import PROCEDURES, SHIPPED_INPUTS, UNNAMED, load, step
from tests.test_engine_whole_shell import client_admits, whole_shell_argv, words_after

TIER = "fast"

SHA = "a" * 40
NAMED = [{"severity": "important", "file": "a.py:1", "failing_input": "f('')", "summary": "s", "kind": "other"}]
GRADING = [{"id": "AC1", "met": True, "evidence": "test_x"}]
PREFLIGHT = {"branch": "b", "worktree_path": "/w", "integration_branch": "main", "issue_text": "t"}
IMPLEMENTED = {"status": "done", "start_head": SHA, "commit": SHA, "notes": "n", "tests": [],
               "acceptance": [{"id": "AC1", "text": "t", "kind": "code", "result": "r"}],
               "sensitive": False, "ineligible": False}
INDEPENDENT = {"verdict": "pass", "findings": []}
CHECKED = {"verdict": "ok", "base": SHA, "head": SHA, "new_tests": [], "still_passing": [], "reason": ""}


def reported(name: str, outcome: str, result: dict) -> list[dict]:
    return [{"type": "entered", "step": name},
            {"type": "outcome", "step": name, "outcome": outcome, "result": result}]


def lite_review(verdict: str, findings: list[dict]) -> dict:
    return {"verdict": verdict, "findings": findings, "acceptance": GRADING, "escalate": False}


def to_the_lite_group() -> list[dict]:
    return (reported("preflight", "clear", PREFLIGHT) + reported("implement", "done", IMPLEMENTED)
            + reported("revert-check", "ok", CHECKED))


def lite_round(review: dict, independent: bool = True) -> list[dict]:
    events = [{"type": "entered", "step": "lite-group"}] + reported("lite-review", review["verdict"], review)
    return events + (reported("lite-independent", "pass", INDEPENDENT) if independent else [])


def replayed(events: list[dict]) -> engine_core.Replay:
    return engine_core.replay(load(PROCEDURES, "direct"), SHIPPED_INPUTS, events)


class DirectProcedureTest(unittest.TestCase):
    def test_the_direct_steps_that_commit_are_the_only_mutating_ones(self):
        self.assertEqual([s["id"] for s in load(PROCEDURES, "direct")["steps"] if s.get("mutates")],
                         ["implement", "lite-fix", "escalated-fix", "full-fix"])
        self.assertEqual([s["id"] for s in load(PROCEDURES, "verify")["steps"] if s.get("mutates")], ["fix"])

    def test_only_the_direct_implementer_steps_name_a_worktree(self):
        named = {"path": "preflight.worktree_path", "branch": "preflight.branch"}
        direct = {s["id"]: s["worktree"] for s in load(PROCEDURES, "direct")["steps"] if "worktree" in s}
        self.assertEqual(direct, {"implement": named, "lite-fix": named, "escalated-fix": named,
                                  "full-fix": named})
        for path in sorted(PROCEDURES.glob("*.json")):
            if path.name in ("direct.json", "command_verdicts.json"):
                continue
            with self.subTest(path.name):
                steps = json.loads(path.read_text(encoding="utf-8")).get("steps", [])
                self.assertEqual([s["id"] for s in steps if "worktree" in s], [])

    def test_the_direct_implementer_prompts_show_single_commands_in_the_worktree(self):
        _, argv = whole_shell_argv()
        allowed, denied = words_after(argv, "--allowedTools"), words_after(argv, "--disallowedTools")
        steps = {s["id"]: s for s in load(PROCEDURES, "direct")["steps"]}
        for name in ("implement", "lite-fix", "escalated-fix", "full-fix"):
            with self.subTest(name):
                step = steps[name]
                args = tuple((path, "/srv/p/wt" if path == "preflight.worktree_path" else f"<{path}>")
                             for path in step["in"])
                text = engine_session.render_prompt(
                    (PROCEDURES / step["prompt"]).read_text(encoding="utf-8"), args)
                blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
                lines = [line for block in blocks for line in block.splitlines() if line.strip()]
                self.assertTrue(lines)
                self.assertLess(len(text.encode("utf-8")), 8192)
                for line in lines:
                    self.assertIn("/srv/p/wt", line)
                    for word in (";", "&&", "||", "|", "$", "`"):
                        self.assertNotIn(word, line)
                    self.assertTrue(client_admits(line, allowed, denied), line)

    def test_the_direct_review_roles(self):
        direct = load(PROCEDURES, "direct")
        roles = {s["id"]: s["role"] for s in direct["steps"] if s["kind"] == "agent"}
        self.assertEqual(roles, {
            "implement": "implementer", "lite-fix": "implementer", "escalated-fix": "implementer",
            "full-fix": "implementer", "lite-review": "reviewer-lite", "lite-rereview": "reviewer-lite",
            "escalated-rereview": "reviewer-lite", "full-rereview": "reviewer-lite",
            "full-review": "reviewer", "escalated": "reviewer"})

    def test_the_direct_stops_keep_the_programs_names_and_needs(self):
        self.assertEqual(load(PROCEDURES, "direct")["stops"], {
            "setup": {"need": "owner-decision", "reenter": "preflight"},
            "claim-lost": {"need": "owner-decision", "reenter": "preflight"},
            "ineligible": {"need": "owner-decision", "reenter": "preflight"},
            "task": {"need": "owner-decision", "reenter": "implement"},
            "direct-review": {"need": "owner-decision", "reenter": "implemented"},
            "direct-fix": {"need": "owner-decision", "reenter": "implemented"},
            "codex-unavailable": {"need": "retry", "reenter": "implemented"},
            "revert-check-unavailable": {"need": "retry", "reenter": "revert-check"}})
        self.assertEqual(load(PROCEDURES, "verify")["stops"], {
            "setup": {"need": "owner-decision", "reenter": "preflight"},
            "claim-lost": {"need": "owner-decision", "reenter": "preflight"},
            "verify": {"need": "owner-decision", "reenter": "checks"},
            "verify-unrelated": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix-review": {"need": "owner-decision", "reenter": "checks"}})

    def test_the_route_prompts_differ_only_by_their_producers(self):
        producers = {"lite": ("lite-review", "lite-independent", "lite-fix", "lite-revert-check"),
                     "escalated": ("escalated", "lite-independent", "escalated-fix", "escalated-revert-check"),
                     "full": ("full-review", "full-independent", "full-fix", "full-revert-check")}
        for kind in ("fix", "rereview"):
            texts = set()
            for route, (review, independent, fix, check) in producers.items():
                text = (PROCEDURES / f"direct-{kind}-{route}.md").read_text(encoding="utf-8")
                texts.add(text.replace(check, "CHECK").replace(fix, "FIX").replace(independent, "INDEPENDENT").replace(review, "REVIEW"))
            self.assertEqual(len(texts), 1, kind)

    def test_a_blocked_group_reaches_its_tally(self):
        direct = load(PROCEDURES, "direct")
        for route in ("lite", "full"):
            on = step(direct, f"{route}-group")["on"]
            self.assertEqual((on["pass"], on["blocked"], on["exhausted"]),
                             (f"{route}-tally", f"{route}-tally", "direct-review"))

    def test_an_unusable_review_is_asked_once_more_without_the_independent_review(self):
        events = to_the_lite_group() + lite_round(lite_review("pass", UNNAMED["findings"]))
        again = replayed(events)
        self.assertIsInstance(again.action, RunGroup)
        self.assertEqual((again.action.step, tuple(m.step for m in again.action.members)),
                         ("lite-group", ("lite-review",)))
        self.assertIn(("lite-tally", "unusable"), [(t.step, t.outcome) for t in again.transitions])
        second = replayed(events + lite_round(lite_review("pass", UNNAMED["findings"]), independent=False))
        self.assertIsInstance(second.action, Stop)
        self.assertEqual(second.action.name, "direct-review")
        usable = replayed(events + lite_round(lite_review("pass", []), independent=False))
        self.assertIsInstance(usable.action, engine_core.Done)

    def test_an_unusable_escalated_or_re_review_reply_is_asked_once_more(self):
        unnamed = UNNAMED["findings"]
        escalate = {**lite_review("pass", []), "escalate": True}
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": [], "declines": []}
        unusable = lite_review("pass", unnamed)
        routes = {
            "escalated": to_the_lite_group() + lite_round(escalate) + reported("escalated", "pass", unusable),
            "lite-rereview": to_the_lite_group() + lite_round(lite_review("findings", NAMED))
            + reported("lite-fix", "done", fix) + reported("lite-revert-check", "ok", CHECKED)
            + reported("lite-rereview", "pass", unusable),
        }
        for name, events in routes.items():
            with self.subTest(name=name):
                again = replayed(events)
                self.assertEqual((type(again.action), again.action.step), (engine_core.StartSession, name))
                self.assertEqual(again.action.visit, 2)
                usable = replayed(events + reported(name, "pass", lite_review("pass", [])))
                self.assertIsInstance(usable.action, engine_core.Done)
                twice = replayed(events + reported(name, "pass", unusable))
                self.assertEqual((type(twice.action), twice.action.name), (Stop, "direct-review"))

    def test_each_review_reads_the_revert_check_on_its_route(self):
        direct = load(PROCEDURES, "direct")
        for review, check in (("lite-review", "revert-check"), ("full-review", "revert-check"),
                              ("escalated", "revert-check"), ("lite-rereview", "lite-revert-check"),
                              ("escalated-rereview", "escalated-revert-check"),
                              ("full-rereview", "full-revert-check")):
            with self.subTest(review=review):
                prompt = (PROCEDURES / step(direct, review)["prompt"]).read_text(encoding="utf-8")
                for member in ("still_passing", "reason"):
                    self.assertIn(f"{check}.{member}", step(direct, review)["in"])
                    self.assertIn("{{" + f"{check}.{member}" + "}}", prompt)
                self.assertIn("covers only the tests that completed", prompt)
        for check in ("revert-check", "lite-revert-check", "escalated-revert-check", "full-revert-check"):
            with self.subTest(check=check):
                one = step(direct, check)
                self.assertEqual((one["kind"], one["command"], one["holds"]), ("command", "revert-check", "run"))
                self.assertEqual(one["in"], ["preflight.worktree_path", "preflight.integration_branch"])
                self.assertEqual((one["on"]["refused"], one["on"]["out-of-bounds"], one["on"]["failed"]),
                                 ("revert-check-unavailable",) * 3)
        self.assertEqual(step(direct, "revert-check")["on"]["ok"], "implemented")
        self.assertEqual(step(direct, "implement")["on"]["done"], "revert-check")
        self.assertEqual(step(direct, "implement")["on"]["blocked"], "revert-check")
        for route in ("lite", "escalated", "full"):
            self.assertEqual(step(direct, f"{route}-revert-check")["on"]["ok"], f"{route}-rereview")
            self.assertEqual(step(direct, f"{route}-fixed")["on"]["done"], f"{route}-revert-check")

    def test_a_fix_runs_the_revert_check_again_before_its_re_review(self):
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": [], "declines": []}
        events = (to_the_lite_group() + lite_round(lite_review("findings", NAMED))
                  + reported("lite-fix", "done", fix))
        checking = replayed(events)
        self.assertIsInstance(checking.action, engine_core.RunCommand)
        self.assertEqual((checking.action.step, checking.action.command, checking.action.args),
                         ("lite-revert-check", "revert-check",
                          (("preflight.worktree_path", "/w"), ("preflight.integration_branch", "main"))))
        reviewing = replayed(events + reported("lite-revert-check", "ok", CHECKED))
        self.assertEqual((type(reviewing.action), reviewing.action.step, reviewing.action.visit),
                         (engine_core.StartSession, "lite-rereview", 1))

    def test_a_checker_that_crashes_before_its_json_enters_the_retry_stop(self):
        stopped = replayed(reported("preflight", "clear", PREFLIGHT) + reported("implement", "done", IMPLEMENTED)
                           + reported("revert-check", "failed", {}))
        self.assertEqual((type(stopped.action), stopped.action.name, stopped.action.need),
                         (Stop, "revert-check-unavailable", "retry"))

    def test_a_check_stored_at_one_head_is_not_stale_when_the_checkout_of_the_run_moves(self):
        """The engine reads the head of the project's checkout, which a pull moves while a run is cut."""
        events = (to_the_lite_group() + lite_round(lite_review("findings", NAMED))
                  + [{"type": "entered", "step": "lite-fix"}])
        for name in ("revert-check", "lite-revert-check"):
            with self.subTest(check=name):
                stored = [{**event, "head": "a" * 40} if event.get("step") == name and event["type"] == "outcome"
                          else event for event in events]
                if name == "lite-revert-check":
                    fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": [],
                           "declines": []}
                    stored = (events[:-1] + reported("lite-fix", "done", fix)
                              + [{**event, "head": "a" * 40} if event["type"] == "outcome" else event
                                 for event in reported("lite-revert-check", "ok", CHECKED)]
                              + [{"type": "entered", "step": "lite-rereview"}])
                moved = engine_core.reentry(load(PROCEDURES, "direct"), SHIPPED_INPUTS, stored, "b" * 40)
                self.assertNotIn(name, moved.stale)

    def test_a_fix_with_no_commit_stops_direct_fix(self):
        fix = {"status": "done", "start_head": SHA, "commit": "", "notes": "n", "tests": [], "declines": []}
        done = replayed(to_the_lite_group() + lite_round(lite_review("findings", NAMED))
                        + reported("lite-fix", "done", fix))
        self.assertIsInstance(done.action, Stop)
        self.assertEqual(done.action.name, "direct-fix")
        steps = [(t.step, t.outcome) for t in done.transitions]
        self.assertIn(("lite-fixed", "not-done"), steps)
        self.assertNotIn("lite-rereview", [name for name, _ in steps])


class VerifyProcedureTest(unittest.TestCase):
    def test_a_fix_range_that_could_not_be_read_still_reaches_the_full_review_and_reruns_every_id(self):
        results = [{"id": "lint", "status": "pass"}, {"id": "test", "status": "fail", "named": ["a.json"]}]
        round_read = {"head": SHA, "clean": True, "results": results, "start_head": "", "guards": [],
                      "problems": [{"id": "test", "status": "fail", "summary": "s", "reran": False}]}
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": ["t"],
               "outside_diff": [], "unrelated": {"test": "", "evidence": ""}}
        unread = {"start_head": SHA, "commit": "", "whitespace_only": False, "changed_paths": []}
        events = (reported("preflight", "clear", PREFLIGHT) + reported("checks", "failed", round_read)
                  + reported("round", "fix", round_read) + reported("fix", "done", fix)
                  + reported("ws-check", "unread", unread))

        review = engine_core.replay(load(PROCEDURES, "verify"), SHIPPED_INPUTS, events)

        self.assertEqual((type(review.action), review.action.step), (engine_core.StartSession, "fix-review"))
        passed = {"verdict": "pass", "findings": [], "whitespace_insignificant": True, "whitespace_evidence": "e"}
        narrowed = engine_core.replay(load(PROCEDURES, "verify"), SHIPPED_INPUTS,
                                      events + reported("fix-review", "pass", passed))
        self.assertIn(("narrowing", "rerun-all"), [(t.step, t.outcome) for t in narrowed.transitions])
        self.assertEqual((type(narrowed.action), narrowed.action.step, narrowed.action.command),
                         (engine_core.RunCommand, "checks", "verified-tree"))


if __name__ == "__main__":
    unittest.main()
