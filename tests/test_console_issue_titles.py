"""The console reads the issues' titles of its running sprints from the tracker.

Run: just agent-workflow-tests
"""

import contextlib
import io
import json
import re
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from agent_tools.console import deliveries, guest, movement, service, sprints
from agent_tools.delivery import comment_lint, comment_syntax
from agent_tools.system.forge_api import ForgeError

from . import console_screenshots as shots
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_briefs import PARTS
from .test_console_service import Case, sprint_entry

TIER = "fast"

QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    i3: issueOrPullRequest(number: 3) { ... on Issue { number title } ... on PullRequest { number title } }
    i12: issueOrPullRequest(number: 12) { ... on Issue { number title } ... on PullRequest { number title } }
  }
}"""


class Titles:
    """A title reader answering or raising its steps in order and repeating the last one."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, slug, numbers, *, cancelled):
        self.calls.append((slug, list(numbers)))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step(numbers) if callable(step) else step


class TitlesServiceTest(Case):
    def setUp(self):
        super().setUp()
        self.now = 1_800_000_000.0

    def open(self, title_reader, **kwargs):
        support.write_registry(self.registry, [{"project_id": "owner/p00", "root": "/srv/p00"}])
        svc = service.ConsoleService(
            self.store, self.registry, port=0, session_dirs=lambda: [self.sessions],
            profile_dirs=lambda: [], repo_of=lambda cwd: cwd,
            branch_pattern_of=lambda repo: "issue-<num>-<slug>", dispatch=lambda job: job(),
            clock=lambda: self.now, slug_of=lambda root: "owner/p00", pull_reader=None,
            title_reader=title_reader, write_sleep=lambda seconds: None,
            monotonic=lambda: 0.0, **kwargs)
        self.addCleanup(svc.close)
        return svc

    def report(self, rows, phase="running"):
        return {"status": "one slice is queued", "phase": phase, "milestone": "Importer resumes",
                "tracker_url": "https://github.com/owner/p00/milestone/3",
                "issues": [{"issue": number, "stage": stage} for number, stage in rows],
                "inbox": [], "next": "start the resume slice"}

    def running_sprint(self, svc, issues=((858, "queued"),)):
        sid = svc.state_goal("owner/p00", "make the importer resumable")
        secret = sprints.read_secret(self.store.with_name(sprints.SECRETS_DIR), sid)
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p00", sid, 1)
        svc.send_report(sid, secret, self.report(issues))
        self.settle(svc)
        return sid, secret

    def settle(self, svc):
        """The clock reads the moment of the last event, so the sprint is not quiet."""
        self.now = datetime.fromisoformat(support.log_rows(self.store)[-1][1]).timestamp()

    def poll(self, svc):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            svc.poll_titles()
        return errors.getvalue()

    def test_a_running_sprints_issue_titles_reach_its_line(self):
        titles = Titles({858: "Resume a broken upload"})
        svc = self.open(titles)
        self.running_sprint(svc)
        self.poll(svc)
        self.assertEqual(sprint_entry(svc)["now_text"], "Next: \u201cResume a broken upload\u201d")
        self.assertEqual(titles.calls, [("owner/p00", [858])])

    def test_a_known_title_is_not_read_again(self):
        titles = Titles({858: "Resume a broken upload"})
        svc = self.open(titles)
        self.running_sprint(svc)
        self.poll(svc)
        self.poll(svc)
        self.assertEqual(len(titles.calls), 1)

    def test_a_failed_title_read_says_so_and_keeps_the_line(self):
        titles = Titles(ForgeError("gh_failed", "no such issue"))
        svc = self.open(titles)
        self.running_sprint(svc)
        errors = self.poll(svc)
        self.assertIn("console: titles_read_failed owner/p00 ForgeError: gh_failed", errors)
        self.assertEqual(sprint_entry(svc)["now_text"], deliveries.NOW_IDLE_WORK_TEXT)

    def many(self, svc):
        rows = [(number, "queued") for number in range(1, 150)] + [(150, "building")]
        self.running_sprint(svc, rows)

    def unavailable(self, first):
        titled = {150: "Resume a broken upload"}
        titles = Titles(first, lambda numbers: {n: titled[n] for n in numbers if n in titled}, {})
        svc = self.open(titles)
        self.many(svc)
        self.poll(svc)
        self.assertEqual(titles.calls[-1][1], list(range(1, 101)))
        self.assertEqual(sprint_entry(svc)["now_text"], "Working on 1 issue.")
        self.poll(svc)
        self.assertEqual(titles.calls[-1][1], list(range(101, 151)))
        self.assertEqual(sprint_entry(svc)["now_text"], "Working on: \u201cResume a broken upload\u201d")
        self.poll(svc)
        self.assertEqual(titles.calls[-1][1], list(range(1, 101)))

    def test_unavailable_titles_do_not_block_the_rest(self):
        self.unavailable(lambda numbers: {})

    def test_failed_titles_do_not_block_the_rest(self):
        self.unavailable(ForgeError("gh_failed", "down"))

    def test_a_projects_titles_go_with_its_last_running_sprint(self):
        titles = Titles({858: "Resume a broken upload"})
        svc = self.open(titles)
        sid, secret = self.running_sprint(svc)
        self.poll(svc)
        self.assertEqual(svc._titles, {"owner/p00": {858: "Resume a broken upload"}})
        svc.send_report(sid, secret, self.report([(858, "landed")], phase="done"))
        self.settle(svc)
        self.poll(svc)
        self.assertEqual((svc._titles, svc._titles_asked), ({}, {}))
        self.assertEqual(len(titles.calls), 1)

    def test_the_query_asks_one_alias_per_number_in_order(self):
        argv = movement.titles_argv("owner/p00", [3, 12])
        self.assertIn("owner=owner", argv)
        self.assertIn("name=p00", argv)
        self.assertEqual(argv[argv.index("-f") + 1], "query=" + QUERY)

    def test_an_answer_gives_each_titled_number_one_line(self):
        answer = {"data": {"repository": {"i3": {"number": 3, "title": "  Save a\ncheckpoint "},
                                          "i12": None}}}
        self.assertEqual(movement.titles_from_answer(answer, [3, 12]), {3: "Save a checkpoint"})

    def test_a_malformed_answer_is_payload_invalid(self):
        for answer in ({"data": {}},
                       {"data": {"repository": {"i3": {"number": 3, "title": 5}}}},
                       {"data": {"repository": {"i3": {"number": 4, "title": "x"}}}}):
            with self.subTest(answer=answer), self.assertRaises(ForgeError) as caught:
                movement.titles_from_answer(answer, [3])
            self.assertEqual(caught.exception.code, "payload_invalid")

    def test_a_read_asks_at_most_the_smallest_hundred_numbers_and_honours_cancel(self):
        calls = []

        def recorder(argv):
            calls.append(argv)
            return {"data": {"repository": {}}}

        movement.read_titles("owner/p00", range(150, 0, -1), call=recorder)
        (argv,) = calls
        query = argv[argv.index("-f") + 1]
        self.assertIn("i1:", query)
        self.assertIn("i100:", query)
        self.assertNotIn("i101:", query)
        self.assertEqual(movement.read_titles("owner/p00", [], call=recorder), {})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ForgeError) as caught:
            movement.read_titles("owner/p00", [1], call=recorder, cancelled=lambda: True)
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertEqual(len(calls), 1)
        first, asked = movement.titles_batch(range(1, 151), {}, ())
        self.assertEqual(first, list(range(1, 101)))
        second, asked = movement.titles_batch(range(1, 151), {}, asked)
        self.assertEqual(second, list(range(101, 151)))
        third, asked = movement.titles_batch(range(1, 151), {}, asked)
        self.assertEqual(third, list(range(1, 101)))

    @staticmethod
    def resolving(unresolved):
        """A `gh api graphql` stand-in: a query naming a number in `unresolved` fails whole, as gh does."""
        calls = []

        def call(argv):
            query = argv[argv.index("-f") + 1]
            numbers = [int(n) for n in re.findall(r"\bi(\d+):", query)]
            calls.append(numbers)
            if unresolved & set(numbers):
                raise ForgeError("gh_failed", "Could not resolve to an issue or pull request")
            return {"data": {"repository": {f"i{n}": {"number": n, "title": f"Title {n}"} for n in numbers}}}

        return call, calls

    def test_a_number_that_does_not_resolve_does_not_hide_the_others_titles(self):
        call, calls = self.resolving({9999})
        self.assertEqual(movement.read_titles("owner/p00", [101, 9999], call=call), {101: "Title 101"})
        self.assertEqual(movement.read_titles("owner/p00", [9999], call=call), {})
        crowd = [*range(1, 100), 9999]
        self.assertEqual(movement.read_titles("owner/p00", crowd, call=call),
                         {n: f"Title {n}" for n in range(1, 100)})

    def test_a_failed_read_that_is_not_the_numbers_still_fails(self):
        for error in (ForgeError("gh_timeout", "slow"), ForgeError("gh_failed", "HTTP 502", transient=True),
                      ForgeError("gh_missing", "no gh")):
            calls = []

            def call(argv, error=error):
                calls.append(argv)
                raise error

            with self.subTest(code=error.code), self.assertRaises(ForgeError) as caught:
                movement.read_titles("owner/p00", [1, 2, 3], call=call)
            self.assertEqual((caught.exception.code, len(calls)), (error.code, 1))

    def test_a_failure_that_is_not_an_unresolved_number_raises_after_one_call(self):
        for detail in ("HTTP 401: Bad credentials", "HTTP 403: API rate limit exceeded",
                       "Could not resolve to a Repository with the name 'owner/p00'."):
            calls = []

            def call(argv, detail=detail):
                calls.append(argv)
                raise ForgeError("gh_failed", detail)

            with self.subTest(detail=detail), self.assertRaises(ForgeError) as caught:
                movement.read_titles("owner/p00", range(1, 101), call=call)
            self.assertEqual((caught.exception.code, len(calls)), ("gh_failed", 1))

    def test_a_sprint_with_a_number_that_does_not_resolve_still_shows_the_titles_that_do(self):
        call, calls = self.resolving({9999})
        svc = self.open(lambda slug, numbers, *, cancelled: movement.read_titles(
            slug, numbers, call=call, cancelled=cancelled))
        self.running_sprint(svc, [(101, "building"), (9999, "queued")])
        errors = self.poll(svc)
        self.assertEqual(errors, "")
        self.assertEqual(sprint_entry(svc)["now_text"], "Working on: \u201cTitle 101\u201d")

    def test_a_number_beyond_the_trackers_integer_range_is_never_asked(self):
        big = 2 ** 31
        batch, _ = movement.titles_batch([5, big - 1, big, big + 7], {}, ())
        self.assertEqual(batch, [5, big - 1])
        calls = []

        def recorder(argv):
            calls.append(argv[argv.index("-f") + 1])
            return {"data": {"repository": {}}}

        movement.read_titles("owner/p00", [5, big], call=recorder)
        self.assertIn("i5:", calls[0])
        self.assertNotIn(f"i{big}:", calls[0])
        self.assertEqual(movement.read_titles("owner/p00", [big], call=recorder), {})
        self.assertEqual(len(calls), 1)

    def test_the_polling_thread_reads_titles_without_a_pull_reader(self):
        asked = threading.Event()

        def reader(slug, numbers, *, cancelled):
            asked.set()
            return {858: "Resume a broken upload"}

        svc = self.open(reader, movement_seconds=3600)
        self.running_sprint(svc)
        svc.start()
        self.assertTrue(asked.wait(5))
        svc.close()

    def test_a_guest_sees_only_its_projects_titles(self):
        scoped = guest.scoped({"states": [], "issue_titles": {"acme/app": {1: "a"}, "other/app": {2: "b"}}},
                              frozenset({"acme/app"}))
        self.assertEqual(scoped["issue_titles"], {"acme/app": {1: "a"}})

    def test_the_live_several_console_names_each_running_sprints_work(self):
        now_s = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = shots.build_fixture(Path(tmp), "live-several", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        running = {shown["goal"]: shown for entry in view["entries"]
                   for project in entry.get("projects", [entry]) for shown in project["sprints"]
                   if shown["state"] != "done"}
        settings = running["Fix the settings page."]
        self.assertEqual(settings["now_text"],
                         "Working on: \u201cShow which settings changed\u201d\n"
                         "Just finished: \u201cSave the settings in one click\u201d\n"
                         "Next: \u201cUndo a settings change\u201d")
        self.assertEqual({item["group"]: item["count"] for item in settings["legend"]},
                         {"landed": 1, "delivery": 1, "queued": 1, "held": 1})
        for goal, shown in running.items():
            if goal != "Fix the settings page.":
                words = " ".join(filter(None, (shown["now_text"], shown.get("work_text"))))
                self.assertTrue(any(title in words for title in shots.stand_ins.TITLES.values()), goal)


class CommentsNameNoIssueTest(unittest.TestCase):
    """B18: no comment of the files this work touched names its own issue or pull request."""

    FILES = (
        "python/agent_tools/console/console.py", "python/agent_tools/console/deliveries.py",
        "python/agent_tools/console/movement.py", "python/agent_tools/console/service.py",
        "python/agent_tools/console/sprints.py", "tests/test_console_issue_titles.py",
        "tests/test_console_page.py", "tests/test_console_page_work.py", "tests/test_console_work_sentence.py",
    )

    def test_no_comment_line_cites_issue_1793(self):
        root = Path(__file__).resolve().parents[1]
        cited = []
        for path in self.FILES:
            for block in comment_syntax.blocks(path, (root / path).read_text(encoding="utf-8")):
                cited += [f"{path}:{number}" for number, text in enumerate(block.texts, block.first)
                          if "1793" in text and comment_lint.references(text, "fagenorn/nix-config")]
        self.assertEqual(cited, [])


class ScreenshotsFileSizeTest(unittest.TestCase):
    """The screenshots module, already over the size budget, does not grow past its merge base's 3,684 lines."""

    def test_the_screenshots_module_is_no_longer_than_its_merge_base(self):
        text = (Path(__file__).resolve().parent / "console_screenshots.py").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 3684)


if __name__ == "__main__":
    unittest.main()
