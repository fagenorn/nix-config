"""The shipped `direct` and `verify` procedures: their shape, their prompts and their review bounds."""

from __future__ import annotations

import json
import re
import unittest

from agent_tools.delivery import engine_core, engine_reply, engine_session, issue_setup
from agent_tools.delivery.engine_core import RunGroup, Stop
from agent_tools.delivery.engine_graders import GRADERS, dropped
from tests.test_engine_check import PROCEDURES, SHIPPED_INPUTS, UNNAMED, load, step

TIER = "fast"

SHA = "a" * 40
NAMED = [{"severity": "important", "file": "a.py:1", "failing_input": "f('')", "summary": "s", "kind": "other"}]
GRADING = [{"id": "AC1", "met": True, "evidence": "test_x"}]
PREFLIGHT = {"branch": "b", "worktree_path": "/w", "integration_branch": "main", "issue_text": "t", "plan": ""}
IMPLEMENTED = {"status": "done", "start_head": SHA, "commit": SHA, "notes": "n", "tests": [],
               "acceptance": [{"id": "AC1", "text": "t", "kind": "code", "result": "r"}],
               "sensitive": False, "ineligible": False}
INDEPENDENT = {"verdict": "pass", "findings": []}


def reported(name: str, outcome: str, result: dict) -> list[dict]:
    return [{"type": "entered", "step": name},
            {"type": "outcome", "step": name, "outcome": outcome, "result": result}]


def lite_review(verdict: str, findings: list[dict]) -> dict:
    return {"verdict": verdict, "findings": findings, "acceptance": GRADING, "escalate": False}


def to_the_lite_group() -> list[dict]:
    return reported("preflight", "clear", PREFLIGHT) + reported("implement", "done", IMPLEMENTED)


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

    def test_the_direct_implementer_prompts_show_commands_in_the_worktree(self):
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

    def test_the_implementer_builds_an_approved_plan_and_applies_the_eligibility_check_to_no_planned_issue(self):
        text = (PROCEDURES / "direct-implement.md").read_text(encoding="utf-8")
        planned = text.split("\nBEGIN APPROVED PLAN\n", 1)[0]
        self.assertIn("approved plan", planned)
        self.assertIn("every task", planned)
        self.assertIn("not eligibility", planned)

    def test_the_implementer_is_given_the_plan_the_engine_verified_not_a_comment_it_picks_by_marker(self):
        direct = load(PROCEDURES, "direct")["steps"]
        implement = next(s for s in direct if s["id"] == "implement")
        self.assertIn("run.holder", next(s for s in direct if s["id"] == "preflight")["in"])
        self.assertIn("preflight.plan", implement["in"])
        self.assertNotIn("run.holder", implement["in"])
        template = (PROCEDURES / implement["prompt"]).read_text(encoding="utf-8")
        for plan, block in (("THE PLAN", "BEGIN APPROVED PLAN\nTHE PLAN\nEND APPROVED PLAN"),
                            ("", "BEGIN APPROVED PLAN\n\nEND APPROVED PLAN")):
            text = engine_session.render_prompt(
                template, tuple((path, plan if path == "preflight.plan" else f"<{path}>") for path in implement["in"]))
            self.assertIn(block, text)
        self.assertNotIn(issue_setup.PLAN_MARKER, template)

    def test_the_planner_prompts_ask_for_a_read_only_shell_and_read_the_worktree_by_path(self):
        steps = {s["id"]: s for s in load(PROCEDURES, "deliver")["steps"]}
        for name in ("plan", "plan-revise"):
            with self.subTest(name):
                text = engine_session.render_prompt(
                    (PROCEDURES / steps[name]["prompt"]).read_text(encoding="utf-8"),
                    tuple((path, "/srv/p/wt" if path == "plan-preflight.worktree_path" else f"<{path}>")
                          for path in steps[name]["in"]))
                self.assertIn("shell only to read", text)
                self.assertNotIn("Bash or Read", text)
                self.assertIn("project root", text)  # the session's directory is not the worktree
                self.assertIn("by their absolute path under /srv/p/wt", text)
                self.assertIn(f"at most {issue_setup.PLAN_LIMIT} characters", text)
                self.assertIn("task_numbers", text)
                self.assertIn("evidence an empty string", text)  # a blocked reply fills every required member
        plan = (PROCEDURES / steps["plan"]["prompt"]).read_text(encoding="utf-8")
        gate = next(line for line in plan.splitlines() if "grep or deny gate" in line)
        self.assertIn("Grep tool", gate)

    def test_the_plan_reply_schema_takes_a_blocked_reply_with_empty_members_and_requires_the_task_numbers(self):
        schema = json.loads((PROCEDURES / "plan.reply.json").read_text(encoding="utf-8"))
        blocked = {"status": "blocked", "evidence": "", "tasks": [], "task_numbers": [], "declines": [],
                   "notes": "Which option?"}
        self.assertIsNone(engine_reply.reply_problem(schema, blocked))
        self.assertIsNotNone(engine_reply.reply_problem(schema, {k: v for k, v in blocked.items()
                                                                 if k != "task_numbers"}))
        self.assertIsNotNone(engine_reply.reply_problem(schema, dict(blocked, task_numbers=["1"])))

    def test_the_plan_review_reply_names_only_important_and_critical_findings(self):
        schema = json.loads((PROCEDURES / "plan-review.reply.json").read_text(encoding="utf-8"))
        finding = {"severity": "important", "file": "plan.md", "failing_input": "x", "summary": "s", "kind": "other"}
        for severity, admitted in (("important", True), ("critical", True), ("minor", False)):
            with self.subTest(severity):
                reply = {"verdict": "findings", "findings": [dict(finding, severity=severity)]}
                self.assertEqual(engine_reply.reply_problem(schema, reply) is None, admitted)

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
            "codex-unavailable": {"need": "retry", "reenter": "implemented"}})
        self.assertEqual(load(PROCEDURES, "verify")["stops"], {
            "setup": {"need": "owner-decision", "reenter": "preflight"},
            "claim-lost": {"need": "owner-decision", "reenter": "preflight"},
            "verify": {"need": "owner-decision", "reenter": "checks"},
            "verify-unrelated": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix-review": {"need": "owner-decision", "reenter": "checks"}})

    def test_the_route_prompts_differ_only_by_their_producers(self):
        producers = {"lite": ("lite-review", "lite-independent", "lite-fix"),
                     "escalated": ("escalated", "lite-independent", "escalated-fix"),
                     "full": ("full-review", "full-independent", "full-fix")}
        for kind in ("fix", "rereview"):
            texts = set()
            for route, (review, independent, fix) in producers.items():
                text = (PROCEDURES / f"direct-{kind}-{route}.md").read_text(encoding="utf-8")
                texts.add(text.replace(fix, "FIX").replace(independent, "INDEPENDENT").replace(review, "REVIEW"))
            self.assertEqual(len(texts), 1, kind)

    def test_every_re_review_prompt_carries_the_sentence_that_other_criteria_are_graded_never_findings(self):
        sentence = ("A code criterion that is not met, or has no evidence, is an Important finding; "
                    "criteria of other kinds are graded (give what you observed), never findings.")
        self.assertIn(sentence, (PROCEDURES / "direct-review.md").read_text(encoding="utf-8"))
        for name in ("direct-rereview-full.md", "direct-rereview-lite.md", "direct-rereview-escalated.md"):
            with self.subTest(name=name):
                self.assertIn(sentence, (PROCEDURES / name).read_text(encoding="utf-8"))

    def test_every_fix_and_re_review_prompt_leaves_the_findings_the_engine_dropped_alone(self):
        fix = ("A finding that names only criteria of other kinds than code (evidence, human or note) in its "
               "restates or summary is dropped by the engine: leave it alone, neither fixing nor declining it.")
        rereview = ("A finding of the review that names only criteria of other kinds than code (evidence, human "
                    "or note) in its restates or summary was dropped by the engine: do not report it again.")
        for route in ("full", "lite", "escalated"):
            for name, sentence in ((f"direct-fix-{route}.md", fix), (f"direct-rereview-{route}.md", rereview)):
                with self.subTest(name=name):
                    self.assertIn(sentence, (PROCEDURES / name).read_text(encoding="utf-8"))

    def test_a_re_review_finding_naming_only_an_evidence_criterion_settles_clean_and_rides_on_its_transition(self):
        evidence = {"id": "AC2", "text": "t", "kind": "evidence", "result": "r"}
        implemented = {**IMPLEMENTED, "acceptance": [*IMPLEMENTED["acceptance"], evidence]}
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": [], "declines": []}
        finding = {**NAMED[0], "summary": "AC2 has no evidence", "kind": "other", "restates": "AC2"}
        events = (reported("preflight", "clear", PREFLIGHT) + reported("implement", "done", implemented)
                  + lite_round(lite_review("findings", NAMED)) + reported("lite-fix", "done", fix)
                  + reported("lite-rereview", "findings", {"verdict": "findings", "findings": [finding]}))

        replay = replayed(events)

        self.assertIsInstance(replay.action, engine_core.Done)
        self.assertIn(engine_core.Transition("lite-settled", "clean", "done"), replay.transitions)
        settled = [t for t in replay.transitions if t.step == "lite-settled"][0]
        self.assertEqual(settled.dropped, ({"finding": "lite-rereview:1", "criteria": ["AC2"]},))

    def test_every_step_whose_grader_drops_findings_reads_the_acceptance(self):
        steps = [s for s in load(PROCEDURES, "direct")["steps"]
                 if s["kind"] == "decide" and GRADERS[s["grader"]].drops is dropped]
        self.assertEqual({s["id"] for s in steps}, {"lite-tally", "escalated-tally", "full-tally",
                                                    "lite-settled", "escalated-settled", "full-settled"})
        for one in steps:
            with self.subTest(step=one["id"]):
                self.assertIn("implement.acceptance", one["in"])

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
            + reported("lite-fix", "done", fix) + reported("lite-rereview", "pass", unusable),
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
