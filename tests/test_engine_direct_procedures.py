"""The shipped `direct` and `verify` procedures: their shape, their prompts and their review bounds."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import engine_core, engine_session
from agent_tools.delivery.engine_core import RunGroup, Stop
from tests.test_engine_check import PROCEDURES, REPO_ROOT, SHIPPED_INPUTS, UNNAMED, load, step
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
ROUTED = {"routed_files": ["/s/the-bar.md"], "diff": f"{SHA}..{SHA}", "head": SHA, "merge_base": SHA}


STANDARDS_DIRECTORIES = (REPO_ROOT / "home/common/agent-skills/standards", REPO_ROOT / "docs/standards")
SHARD_WORD = re.compile(r"\bshards?\b|\bglobs?\b[^.]*\b(match\w*|govern\w*)\b|\b(match\w*|govern\w*)\b[^.]*\bglobs?\b"
                        r"|\bintersect\w*|the-bar|stacks/", re.IGNORECASE)
CHOICE_WORD = re.compile(r"\b(choose|chooses|choosing|pick|picks|picking|select|selects|selecting|applicable)\b"
                         r"|\bwhich(ever)?\b[^.]*\b(apply|applies|match|matches)\b", re.IGNORECASE)
STANDARDS_WORD = re.compile(r"\b(standards?|shards?|stacks?|rules? files?)\b", re.IGNORECASE)
MARKERS = "#-*>| "
# A long sentence may be any part of a rule, but a short one counts only when it is a whole rule sentence.
MINIMUM_PASTE = 40


def collapsed(text: str) -> str:
    return " ".join(text.split())


def blocks(text: str) -> list[str]:
    found, paragraph = [], []
    for line in text.splitlines():
        if line.strip() and line.lstrip()[0] not in "#-*>|":
            paragraph.append(line)
            continue
        if paragraph:
            found.append(collapsed(" ".join(paragraph)))
            paragraph = []
        if line.strip():
            found.append(collapsed(line.lstrip(MARKERS)))
    if paragraph:
        found.append(collapsed(" ".join(paragraph)))
    return [block for block in found if block]


def sentences(text: str) -> list[str]:
    return [part for block in blocks(text) for part in re.split(r"(?<=[.!?]) ", block)]


def rule_sentence(sentence: str) -> bool:
    return len(sentence.split()) >= 2 and sentence[-1] in ".!?"


def standards_sentences() -> set[str]:
    texts = (path.read_text(encoding="utf-8") for directory in STANDARDS_DIRECTORIES
             for path in sorted(directory.rglob("*.md")))
    return {sentence.lower() for text in texts for sentence in sentences(text)
            if len(sentence) >= MINIMUM_PASTE or rule_sentence(sentence)}


def prompt_defects(directory: Path) -> list[tuple[str, str]]:
    pasted, found = standards_sentences(), set()
    for path in sorted(Path(directory).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        flat = collapsed(text).lower()
        if SHARD_WORD.search(flat):
            found.add((path.name, "shard-word"))
        if any(CHOICE_WORD.search(sentence) and STANDARDS_WORD.search(sentence) for sentence in sentences(text)):
            found.add((path.name, "standards-choice"))
        if any(sentence in flat for sentence in pasted):
            found.add((path.name, "pasted-standards"))
    return sorted(found)


def with_appended(text: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="engine-prompts-"))
    unittest.addModuleCleanup(shutil.rmtree, directory, ignore_errors=True)
    copy = directory / "procedures"
    shutil.copytree(PROCEDURES, copy)
    with (copy / "direct-review.md").open("a", encoding="utf-8") as prompt:
        prompt.write("\n\n" + text)
    return copy


def reported(name: str, outcome: str, result: dict) -> list[dict]:
    return [{"type": "entered", "step": name},
            {"type": "outcome", "step": name, "outcome": outcome, "result": result}]


def lite_review(verdict: str, findings: list[dict]) -> dict:
    return {"verdict": verdict, "findings": findings, "acceptance": GRADING, "escalate": False}


def to_the_lite_group() -> list[dict]:
    return (reported("preflight", "clear", PREFLIGHT) + reported("route", "ok", ROUTED)
            + reported("implement", "done", IMPLEMENTED) + reported("route-lite", "ok", ROUTED))


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
            "route-failed": {"need": "owner-decision", "reenter": "preflight"},
            "direct-review": {"need": "owner-decision", "reenter": "implemented"},
            "direct-fix": {"need": "owner-decision", "reenter": "implemented"},
            "codex-unavailable": {"need": "retry", "reenter": "implemented"}})
        self.assertEqual(load(PROCEDURES, "verify")["stops"], {
            "setup": {"need": "owner-decision", "reenter": "preflight"},
            "claim-lost": {"need": "owner-decision", "reenter": "preflight"},
            "verify": {"need": "owner-decision", "reenter": "checks"},
            "verify-route-failed": {"need": "owner-decision", "reenter": "checks"},
            "verify-unrelated": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix": {"need": "owner-decision", "reenter": "checks"},
            "verify-fix-review": {"need": "owner-decision", "reenter": "checks"}})

    def test_the_route_prompts_differ_only_by_their_producers(self):
        producers = {"lite": ("lite-review", "lite-independent", "lite-fix", "route-lite", "route-lite-fixed"),
                     "escalated": ("escalated", "lite-independent", "escalated-fix", "route-lite",
                                   "route-escalated-fixed"),
                     "full": ("full-review", "full-independent", "full-fix", "route-full", "route-full-fixed")}
        for kind in ("fix", "rereview"):
            texts = set()
            for route, (review, independent, fix, routed, fixed) in producers.items():
                text = (PROCEDURES / f"direct-{kind}-{route}.md").read_text(encoding="utf-8")
                text = text.replace(fixed, "ROUTE") if kind == "rereview" else text.replace(routed, "ROUTE")
                texts.add(text.replace(fix, "FIX").replace(independent, "INDEPENDENT").replace(review, "REVIEW"))
            self.assertEqual(len(texts), 1, kind)

    def test_the_escalated_and_full_review_prompts_differ_only_by_their_route(self):
        escalated = (PROCEDURES / "direct-review-escalated.md").read_text(encoding="utf-8")
        full = (PROCEDURES / "direct-review.md").read_text(encoding="utf-8")
        self.assertEqual(escalated.replace("route-lite", "ROUTE"), full.replace("route-full", "ROUTE"))

    def test_the_independent_reviews_read_their_reviewers_route(self):
        direct = load(PROCEDURES, "direct")
        self.assertIn("route-lite.routed_files", step(direct, "lite-independent")["in"])
        self.assertIn("route-full.routed_files", step(direct, "full-independent")["in"])
        for name, route in (("lite-independent", "route-lite"), ("full-independent", "route-full")):
            for member in ("merge_base", "head"):
                self.assertIn(f"{route}.{member}", step(direct, name)["in"], name)

    def test_the_reviewers_read_the_diff_their_route_names_and_the_independent_reviews_its_head(self):
        direct = load(PROCEDURES, "direct")
        for name, route in (("lite-review", "route-lite"), ("escalated", "route-lite"),
                            ("full-review", "route-full")):
            item = step(direct, name)
            prompt = (PROCEDURES / item["prompt"]).read_text(encoding="utf-8")
            self.assertIn("git diff {{" + route + ".diff}}", prompt, name)
            self.assertNotIn("git diff origin/", prompt, name)
            self.assertIn(f"{route}.diff", item["in"], name)
        for name, route in (("lite-independent", "route-lite"), ("full-independent", "route-full")):
            self.assertIn(f"{route}.head", step(direct, name)["in"], name)

    def test_every_route_step_holds_for_its_checkouts_merge_base_with_the_integration_branch(self):
        routers = [item for name in ("direct", "verify") for item in load(PROCEDURES, name)["steps"]
                   if item["kind"] == "command" and item["command"] == "router"]
        self.assertGreaterEqual(len(routers), 8)
        for item in routers:
            self.assertEqual(item["base"], "preflight.integration_branch", item["id"])
            self.assertIn("preflight.integration_branch", item["in"], item["id"])

    def test_a_route_that_does_not_end_ok_stops_route_failed(self):
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": [], "declines": []}
        before = {
            "route": reported("preflight", "clear", PREFLIGHT),
            "route-lite": (reported("preflight", "clear", PREFLIGHT) + reported("route", "ok", ROUTED)
                           + reported("implement", "done", IMPLEMENTED)),
            "route-lite-fixed": (to_the_lite_group() + lite_round(lite_review("findings", NAMED))
                                 + reported("lite-fix", "done", fix)),
        }
        for name, events in before.items():
            for outcome in ("failed", "refused", "out-of-bounds"):
                with self.subTest(step=name, outcome=outcome):
                    done = replayed(events + reported(name, outcome, {}))
                    self.assertIsInstance(done.action, Stop)
                    self.assertEqual(done.action.name, "route-failed")

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
            + reported("lite-fix", "done", fix) + reported("route-lite-fixed", "ok", ROUTED)
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

    def test_a_fix_with_no_commit_stops_direct_fix(self):
        fix = {"status": "done", "start_head": SHA, "commit": "", "notes": "n", "tests": [], "declines": []}
        done = replayed(to_the_lite_group() + lite_round(lite_review("findings", NAMED))
                        + reported("lite-fix", "done", fix))
        self.assertIsInstance(done.action, Stop)
        self.assertEqual(done.action.name, "direct-fix")
        steps = [(t.step, t.outcome) for t in done.transitions]
        self.assertIn(("lite-fixed", "not-done"), steps)
        self.assertNotIn("lite-rereview", [name for name, _ in steps])


ROUTE_SUBCOMMANDS = {"building": "building", "final review": "final-review", "verifying": "final-review"}
PREFLIGHT_PATHS = {"preflight.worktree_path", "preflight.integration_branch", "preflight.branch"}
UNROUTED = {("setup", "applies"), ("close-out", "hold-draft"), ("close-out", "regrade")}
PLACEHOLDER = re.compile(r"\{\{([\w-]+)\.routed_files\}\}")


def reachable_agent_steps() -> list[tuple[str, dict, dict]]:
    pending, seen, found = ["deliver"], set(), []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        doc = load(PROCEDURES, name)
        for item in doc["steps"]:
            if item["kind"] == "call":
                pending.append(item["procedure"])
            elif item["kind"] == "agent":
                found.append((name, doc, item))
    return found


class RoutedPromptTest(unittest.TestCase):
    def test_every_briefed_step_but_the_owners_exceptions_reads_a_route_at_its_stage(self):
        agents = reachable_agent_steps()
        routed = {}
        for name, doc, item in agents:
            prompt = (PROCEDURES / item["prompt"]).read_text(encoding="utf-8")
            routed[(name, item["id"])] = (doc, item, PLACEHOLDER.findall(prompt))
        unrouted = {key for key, (_, _, producers) in routed.items() if not producers}
        land_attempt = {(name, item["id"]) for name, _, item in agents if name == "land-attempt"}
        self.assertEqual(unrouted, UNROUTED | land_attempt)
        for key, (doc, item, producers) in routed.items():
            if not producers:
                continue
            with self.subTest(step=key):
                self.assertEqual(len(producers), 1)
                self.assertIn(f"{producers[0]}.routed_files", item["in"])
                producer = step(doc, producers[0])
                self.assertEqual((producer["command"], producer["holds"], producer["repository"]),
                                 ("router", "head", "preflight.worktree_path"))
                self.assertTrue(PREFLIGHT_PATHS <= set(producer["in"]))
                self.assertEqual(producer["subcommand"], ROUTE_SUBCOMMANDS[item["stage"]])

    def test_each_fix_prompt_names_the_stored_review_range_never_the_moving_base(self):
        direct = load(PROCEDURES, "direct")
        for fix, route in (("lite-fix", "route-lite"), ("escalated-fix", "route-lite"),
                           ("full-fix", "route-full")):
            with self.subTest(step=fix):
                item = step(direct, fix)
                prompt = (PROCEDURES / item["prompt"]).read_text(encoding="utf-8")
                self.assertIn("{{" + route + ".diff}}", prompt)
                self.assertNotIn("integration_branch", prompt)
                self.assertIn(route + ".diff", item["in"])

    def test_no_shipped_prompt_holds_standards_text_or_asks_for_shards(self):
        self.assertEqual(prompt_defects(PROCEDURES), [])

    def test_the_prompt_check_names_pasted_standards_text_however_it_is_wrapped(self):
        bar = (REPO_ROOT / "home/common/agent-skills/standards/the-bar.md").read_text(encoding="utf-8").splitlines()
        heading = next(index for index, line in enumerate(bar) if line.startswith("### B1."))
        body = next(line for line in bar[heading + 1:] if line.strip())
        cut = body.index(" ", 60)
        rule = next(index for index, line in enumerate(bar) if line.startswith("### B8."))
        short = sentences(next(line for line in bar[rule + 1:] if line.strip()))[0]
        for label, text in (("whole", body), ("wrapped", body[:cut] + "\n" + body[cut + 1:]),
                            ("first sentence", "Every trust boundary is checked on both sides."),
                            ("short rule", short)):
            with self.subTest(copy=label):
                self.assertEqual(prompt_defects(with_appended(text)), [("direct-review.md", "pasted-standards")])

    def test_the_prompt_check_names_an_instruction_to_choose_standards(self):
        both = [("direct-review.md", "shard-word"), ("direct-review.md", "standards-choice")]
        only = [("direct-review.md", "standards-choice")]
        for text, expected in (("Choose the shards that apply to this change.", both),
                               ("Choose the applicable standards files for this diff.", only),
                               ("Pick which rules files apply\nhere.", only),
                               ("Read whichever standards match the changed files.", only),
                               ("Read the standards whose globs match the changed files.",
                                [("direct-review.md", "shard-word")])):
            with self.subTest(text=text):
                self.assertEqual(prompt_defects(with_appended(text)), expected)

    def test_the_prompt_check_passes_ordinary_words(self):
        for text in ("Keep the global settings as they are; select the test files you changed.",
                     "Give the rule's id, as B8.",
                     "Run the glob tests.",
                     "Keep defense in depth in mind."):
            with self.subTest(text=text):
                self.assertEqual(prompt_defects(with_appended(text)), [])


class VerifyProcedureTest(unittest.TestCase):
    def test_a_verify_route_that_does_not_end_ok_stops_verify_route_failed(self):
        results = [{"id": "test", "status": "fail", "named": ["a.json"]}]
        round_read = {"head": SHA, "clean": True, "results": results, "start_head": "", "guards": [],
                      "problems": [{"id": "test", "status": "fail", "summary": "s", "reran": False}]}
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": ["t"],
               "outside_diff": [], "unrelated": {"test": "", "evidence": ""}}
        unread = {"start_head": SHA, "commit": "", "whitespace_only": False, "changed_paths": []}
        to_checks = reported("preflight", "clear", PREFLIGHT) + reported("checks", "failed", round_read)
        before = {
            "route-checks": to_checks,
            "route-review": (to_checks + reported("route-checks", "ok", ROUTED) + reported("round", "fix", round_read)
                             + reported("fix", "done", fix) + reported("ws-check", "unread", unread)),
        }
        for name, events in before.items():
            for outcome in ("failed", "refused", "out-of-bounds"):
                with self.subTest(step=name, outcome=outcome):
                    done = engine_core.replay(load(PROCEDURES, "verify"), SHIPPED_INPUTS,
                                              events + reported(name, outcome, {}))
                    self.assertIsInstance(done.action, Stop)
                    self.assertEqual(done.action.name, "verify-route-failed")

    def test_the_verify_routes_are_bounded_and_on_every_edge_into_round_and_fix_review(self):
        verify = load(PROCEDURES, "verify")
        self.assertEqual((step(verify, "route-checks")["max_visits"], step(verify, "route-review")["max_visits"]),
                         (3, 2))
        for name in ("route-checks", "route-review"):
            self.assertEqual(step(verify, name)["on"]["exhausted"], "verify", name)
        for name in ("checks", "rerun"):
            on = step(verify, name)["on"]
            self.assertEqual({on[o] for o in ("passed", "failed", "dirty")}, {"route-checks"}, name)
        on = step(verify, "ws-check")["on"]
        self.assertEqual({on["read"], on["unread"]}, {"route-review"})
        self.assertEqual(step(verify, "route-checks")["on"]["ok"], "round")
        self.assertEqual(step(verify, "route-review")["on"]["ok"], "fix-review")

    def test_a_fix_range_that_could_not_be_read_still_reaches_the_full_review_and_reruns_every_id(self):
        results = [{"id": "lint", "status": "pass"}, {"id": "test", "status": "fail", "named": ["a.json"]}]
        round_read = {"head": SHA, "clean": True, "results": results, "start_head": "", "guards": [],
                      "problems": [{"id": "test", "status": "fail", "summary": "s", "reran": False}]}
        fix = {"status": "done", "start_head": SHA, "commit": "b" * 40, "notes": "n", "tests": ["t"],
               "outside_diff": [], "unrelated": {"test": "", "evidence": ""}}
        unread = {"start_head": SHA, "commit": "", "whitespace_only": False, "changed_paths": []}
        events = (reported("preflight", "clear", PREFLIGHT) + reported("checks", "failed", round_read)
                  + reported("route-checks", "ok", ROUTED)
                  + reported("round", "fix", round_read) + reported("fix", "done", fix)
                  + reported("ws-check", "unread", unread) + reported("route-review", "ok", ROUTED))

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
