"""The console service's tracker poll and the command's use of it (#859).

Run: just agent-workflow-tests
"""
import contextlib
import functools
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console, inbox, service, view
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support

SLUGS = {"/srv/p00": "octo/p00", "/srv/p01": "octo/p01"}
DAY = 86400


def item(issue=7, comment_id=6803141410, project="owner/p00", slug="octo/p00"):
    return {"key": f"{slug}#{issue}/{comment_id}", "project_id": project, "repo": slug, "issue": issue,
            "comment_id": comment_id, "url": f"https://github.com/{slug}/issues/{issue}#issuecomment-{comment_id}",
            "reason": "conflict", "question": "This pull request conflicts with its base.", "questions": [],
            "items": ["Merge conflict in flake.lock"], "answered": False, "held_work": 1}


A = item()


def page(more=False, cursor=None):
    return {"data": {"search": {"issueCount": 0, "pageInfo": {"hasNextPage": more, "endCursor": cursor},
                                "nodes": []}}}


class Scripted:
    """A tracker answering each call from a script: a list is returned, an exception is raised."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, project_id, slug, *, cancelled):
        self.calls.append((project_id, slug))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "console" / "events.sqlite3"
        self.registry = Path(tmp.name) / "fleet" / "registry.json"

    def open(self, tracker, n=1, **kwargs):
        support.write_registry(self.registry, support.entries(n))
        kwargs.setdefault("activity", lambda root: time.time())
        svc = service.ConsoleService(self.store, self.registry, port=0, tracker=tracker,
                                     slug_of=SLUGS.get, **kwargs)
        self.addCleanup(svc.close)
        return svc

    def kinds(self):
        return [row[2] for row in support.log_rows(self.store)]


def view_of(svc):
    return json.loads(svc.view_bytes)


def open_keys(svc):
    return [i["key"] for i in view_of(svc)["inbox"]["open"]]


class RestartTest(Case):
    def test_first_seen_time_survives_a_restart(self):
        first = self.open(Scripted([A]))
        first.poll_tracker()
        waiting = view_of(first)["inbox"]["open"][0]["waiting_since"]
        first.close()
        self.assertEqual(self.kinds()[-2:], ["inbox.seen", "inbox.health"])
        rows = support.log_rows(self.store)
        second = self.open(Scripted([A]))
        self.assertEqual(view_of(second)["inbox"]["open"][0]["waiting_since"], waiting)
        before = view_of(second)["inbox"]["open"][0]["read_at"]
        second.poll_tracker()
        self.assertGreater(view_of(second)["inbox"]["open"][0]["read_at"], before)
        self.assertEqual(view_of(second)["inbox"]["open"][0]["waiting_since"], waiting)
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_failed_read_stays_stale_after_a_restart(self):
        for name, steps in (("nothing known", [ForgeError("gh_failed", "down")]),
                            ("items known", [[A], ForgeError("gh_failed", "down")])):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.store = Path(tmp) / "console" / "events.sqlite3"
                self.registry = Path(tmp) / "fleet" / "registry.json"
                first = self.open(Scripted(*steps))
                read_at = None
                with contextlib.redirect_stderr(io.StringIO()):
                    for _ in steps:
                        first.poll_tracker()
                        read_at = read_at or (view_of(first)["inbox"]["open"] or [{}])[0].get("read_at")
                first.close()
                tracker = Scripted([])
                second = self.open(tracker, clock=lambda: time.time() + 2 * DAY,
                                   activity=lambda root: None)
                for _ in range(2):
                    shown = view_of(second)
                    self.assertTrue(shown["statement"]["stale"])
                    if len(steps) == 1:
                        self.assertEqual(shown["statement"]["headline"], view.STALE_HEADLINE)
                    else:
                        self.assertEqual(open_keys(second), [A["key"]])
                        self.assertTrue(shown["inbox"]["open"][0]["stale"])
                        self.assertEqual(shown["inbox"]["open"][0]["read_at"], read_at)
                        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
                    second.poll_tracker()
                self.assertEqual(tracker.calls, [])
                second.close()


class StaleTest(Case):
    def test_a_tracker_failure_keeps_the_last_items_and_marks_them_stale(self):
        svc = self.open(Scripted([A], ForgeError("gh_failed", "down")))
        svc.poll_tracker()
        shown = view_of(svc)["inbox"]["open"][0]
        read_at = shown["read_at"]
        self.assertFalse(shown["stale"])
        rows = support.log_rows(self.store)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            svc.poll_tracker()
        shown = view_of(svc)
        self.assertEqual(open_keys(svc), [A["key"]])
        self.assertTrue(shown["inbox"]["open"][0]["stale"])
        self.assertEqual(shown["inbox"]["open"][0]["read_at"], read_at)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertTrue(shown["statement"]["stale"])
        self.assertEqual(errors.getvalue(), "console: tracker_failed owner/p00 ForgeError: gh_failed: down\n")
        after = support.log_rows(self.store)
        self.assertEqual(len(after), len(rows) + 1)
        self.assertEqual(after[-1][2], "inbox.health")
        self.assertEqual(json.loads(after[-1][4]), {"ok": False, "read_at": read_at})
        with contextlib.redirect_stderr(io.StringIO()):
            svc.poll_tracker()
        self.assertEqual(support.log_rows(self.store), after)

    def test_a_failure_with_nothing_known_never_says_nothing_needs_you(self):
        svc = self.open(Scripted(ForgeError("gh_timeout")))
        with contextlib.redirect_stderr(io.StringIO()):
            svc.poll_tracker()
        statement = view_of(svc)["statement"]
        self.assertEqual(statement["headline"], view.STALE_HEADLINE)
        self.assertNotEqual(statement["headline"], "Nothing needs you")

    def test_a_recovered_read_clears_stale_and_a_complete_read_drops_gone_items(self):
        svc = self.open(Scripted([A], ForgeError("gh_failed", "down"), []))
        with contextlib.redirect_stderr(io.StringIO()):
            for _ in range(3):
                svc.poll_tracker()
        rows = support.log_rows(self.store)
        self.assertEqual([r[2] for r in rows[-2:]], ["inbox.gone", "inbox.health"])
        self.assertEqual(json.loads(rows[-1][4]), {"ok": True})
        statement = view_of(svc)["statement"]
        self.assertEqual(open_keys(svc), [])
        self.assertFalse(statement["stale"])
        self.assertEqual(statement["headline"], "Nothing needs you")

    def test_a_read_of_an_unregistered_project_appends_nothing(self):
        def tracker(project_id, slug, *, cancelled):
            support.write_registry(self.registry, [])
            svc.refresh()
            return [A]

        svc = self.open(tracker)
        svc.poll_tracker()
        self.assertFalse([k for k in self.kinds() if k.startswith("inbox.")])
        self.assertEqual(view_of(svc)["inbox"], {"open": [], "answered": []})


class CallBudgetTest(Case):
    def test_one_refresh_calls_at_most_four_times_per_active_project_and_none_for_an_idle_one(self):
        calls = []
        answer = {"more": True}

        def stub(argv):
            calls.append(argv)
            return page(answer["more"], f"c{len(calls)}")

        clock = lambda: time.time() + 2 * DAY
        recent = {"/srv/p00": clock() - 60, "/srv/p02": clock() - 60}
        svc = self.open(functools.partial(inbox.read_items, call=stub), n=3, clock=clock,
                        activity=lambda root: recent.get(root))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            svc.poll_tracker()
        self.assertEqual(len(calls), 4)
        for argv in calls:
            self.assertIn("search=repo:octo/p00 is:open label:owner-action,owner-answered", argv)
            self.assertNotIn("octo/p01", " ".join(argv))
        lines = errors.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("console: tracker_failed owner/p00 ForgeError: payload_incomplete"))
        answer["more"] = False
        svc.poll_tracker()
        self.assertEqual(len(calls), 5)


class PollThreadTest(Case):
    def test_the_poll_thread_reads_on_start(self):
        svc = self.open(Scripted([A]), tracker_seconds=0.05)
        svc.start()
        seen = svc.version
        deadline = time.monotonic() + 1
        while A["key"] not in open_keys(svc) and time.monotonic() < deadline:
            change = svc.wait_for_change(seen, 0.1)
            seen = change[0] if change else seen
        self.assertEqual(open_keys(svc), [A["key"]])
        threads = [t for t in threading.enumerate() if t.name == service.TRACKER_THREAD]
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].is_alive())
        svc.close()
        self.assertFalse(threads[0].is_alive())

    def test_close_stops_a_refresh_in_progress(self):
        argvs = []
        entered, release = threading.Event(), threading.Event()

        def stub(argv):
            argvs.append(argv)
            if len(argvs) == 1:
                entered.set()
                release.wait(5)
            return page(True, f"c{len(argvs)}")

        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            svc = self.open(functools.partial(inbox.read_items, call=stub), n=2)
            svc.start()
            self.assertTrue(entered.wait(1))
            closer = threading.Thread(target=svc.close)
            closer.start()
            closer.join(1.0)
            self.assertTrue(closer.is_alive(), "close returned while a read was still running")
            self.assertIsNone(svc.wait_for_change(svc.version, 1))
            self.assertTrue(svc.closing)
            release.set()
            closer.join(2)
        self.assertFalse(closer.is_alive())
        self.assertEqual(len(argvs), 1)
        self.assertFalse([t for t in threading.enumerate() if t.name == service.TRACKER_THREAD])
        self.assertEqual(errors.getvalue(), "")
        self.assertFalse([k for k in self.kinds() if k.startswith("inbox.")])

    def test_close_sets_the_stop_flag_before_closing(self):
        svc = self.open(Scripted([]))
        seen = []

        class Probe(threading.Condition):
            def notify_all(self):
                seen.append(svc.closing and svc._stop.is_set())
                super().notify_all()

        svc._published = Probe()
        svc.close()
        self.assertEqual(seen, [True])

    def test_without_a_tracker_no_poll_thread_starts(self):
        svc = self.open(None)
        svc.start()
        self.assertFalse([t for t in threading.enumerate() if t.name == "console-tracker-poll"])
        rows = support.log_rows(self.store)
        self.assertIsNone(svc.poll_tracker())
        self.assertEqual(support.log_rows(self.store), rows)


class CommandTest(unittest.TestCase):
    def test_the_command_reads_the_tracker(self):
        recorded = {}

        def refuse(*args, **kwargs):
            recorded.update(kwargs)
            raise OSError("taken")

        with mock.patch.object(service, "ConsoleService", side_effect=refuse), \
                mock.patch.object(service, "default_store", return_value=Path("/nonexistent/store")), \
                mock.patch.object(service, "default_registry", return_value=Path("/nonexistent/registry")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["tracker"], inbox.read_items)


if __name__ == "__main__":
    unittest.main()
