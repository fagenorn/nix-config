"""The console service's tracker poll and the command's use of it (#859).

Run: just agent-workflow-tests
"""
import contextlib
import functools
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console, inbox, movement, pictures, service, view
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support
from .console_test_support import JPEG, PIXEL, WIDE
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

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
        kwargs.setdefault("slug_of", SLUGS.get)
        # No session poll of the host: these tests assert on the log's rows, and a live session would add some.
        kwargs.setdefault("session_dirs", lambda: [])
        kwargs.setdefault("repo_of", lambda cwd: cwd)
        svc = service.ConsoleService(self.store, self.registry, port=0, tracker=tracker, **kwargs)
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


class SharedSlugTest(Case):
    def test_two_projects_on_one_repository_each_keep_their_own_item(self):
        def tracker(project_id, slug, *, cancelled):
            return [item(project=project_id, slug="octo/same")]

        svc = self.open(tracker, n=2, slug_of=lambda root: "octo/same", activity=lambda root: None)
        svc.poll_tracker()
        rows = support.log_rows(self.store)
        self.assertEqual(self.kinds().count("inbox.seen"), 2)
        for _ in range(2):
            svc.poll_tracker()
            self.assertEqual(support.log_rows(self.store), rows)
        shown = view_of(svc)["inbox"]["open"]
        self.assertEqual(sorted(i["project_id"] for i in shown), ["owner/p00", "owner/p01"])
        self.assertEqual(view_of(svc)["statement"]["headline"], "2 things need you")


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


class WaitingLineReadTest(Case):
    WAITING = {**A, "key": "octo/p00#7/wait/1/0", "reason": "verify-wait", "kind": "waiting", "answers": [],
               "wait": {"reason": "not_before", "until": None, "what": "Read the hourly rows."}}

    def test_a_project_with_a_waiting_line_is_read_after_a_day_without_activity(self):
        first = self.open(Scripted([self.WAITING]))
        first.poll_tracker()
        first.close()
        tracker = Scripted([A])
        second = self.open(tracker, clock=lambda: time.time() + 2 * DAY, activity=lambda root: None)
        second.poll_tracker()
        self.assertEqual(len(tracker.calls), 1)
        self.assertEqual(open_keys(second), [A["key"]])
        second.poll_tracker()
        self.assertEqual(len(tracker.calls), 1)


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
        self.assertEqual(len(calls), 6)


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


CHECK = {"key": "octo/p00#7/6803141410", "project_id": "owner/p00", "repo": "octo/p00", "issue": 7,
         "comment_id": 6803141410, "url": "https://github.com/octo/p00/issues/7#issuecomment-6803141410",
         "reason": "verify-ask", "kind": "manual-check", "check_id": "AC5", "reading": "",
         "answers": ["passed", "failed", "note"], "version": "sha256:" + "0" * 64,
         "question": "Do the two screenshots read well?", "detail": "", "questions": [], "items": [],
         "paid": False, "confirm": "", "answered": False, "held_work": 1}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class OwnerCheckPictureTest(Case):
    def setUp(self):
        super().setUp()
        base = self.store.parent.parent
        self.project = base / "project"
        (self.project / "shots").mkdir(parents=True)
        (self.project / "shots" / "before.png").write_bytes(PIXEL)
        (self.project / "shots" / "after.png").write_bytes(WIDE)
        (self.project / "fake.png").write_bytes(JPEG)
        self.outside = base / "outside" / "x.png"
        self.outside.parent.mkdir()
        self.other = PIXEL[:33] + b"other"
        self.outside.write_bytes(self.other)
        self.screens = base / "screens"
        self.screens.mkdir()
        (self.screens / "s.png").write_bytes(PIXEL[:33] + b"screen")
        self.check = dict(CHECK, detail=f"In shots/: before.png and after.png. Also fake.png and {self.outside}.")

    def opened(self, tracker, **kwargs):
        support.write_registry(self.registry, [{"project_id": "owner/p00", "root": str(self.project)}])
        kwargs.setdefault("activity", lambda root: time.time())
        kwargs.setdefault("slug_of", lambda root: "octo/p00")
        kwargs.setdefault("session_dirs", lambda: [])
        kwargs.setdefault("repo_of", lambda cwd: cwd)
        svc = service.ConsoleService(self.store, self.registry, port=0, tracker=tracker, **kwargs)
        self.addCleanup(svc.close)
        return svc

    def served(self, tracker, **kwargs):
        svc = self.opened(tracker, **kwargs)
        svc.start()
        seen = svc.version
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if "pictures" in (self.the_check(svc) or {}):
                return svc
            change = svc.wait_for_change(seen, 0.1)
            seen = change[0] if change else seen
        self.fail("condition not reached: the check carries no pictures")

    def the_check(self, svc):
        return next((i for i in view_of(svc)["inbox"]["open"] if i["key"] == CHECK["key"]), None)

    def fetch(self, svc, picture_id):
        token = (self.store.parent / "page-token").read_text().strip()
        return support.get_page(svc.address, "/api/picture/" + picture_id, {"X-Console-Token": token})

    def test_a_polled_check_lists_its_pictures_and_the_page_reads_them(self):
        svc = self.served(Scripted([self.check]))
        card = self.the_check(svc)
        self.assertEqual([p["line"] for p in card["pictures"]], ["before.png", "after.png"])
        self.assertEqual(card["missing_pictures"], [])
        status, _, body = self.fetch(svc, sha256(PIXEL))
        self.assertEqual((status, body), (200, PIXEL))

    def test_a_review_item_carries_the_pictures_its_criterion_names(self):
        node = {"__typename": "Issue", "number": 5, "issueDependenciesSummary": {"blocking": 0},
                "blocking": {"totalCount": 0, "nodes": []},
                "authorAssociation": "OWNER", "labels": {"nodes": [{"name": "needs-verification"}]},
                "comments": {"totalCount": 0, "nodes": []},
                "body": "## Acceptance criteria\n\n- [ ] [human] The card looks right in shots/before.png and shots/after.png\n"}
        items = inbox.items_from_node("owner/p00", "octo/p00", node)
        self.assertEqual(len(items), 1)
        svc = self.opened(Scripted(items))
        svc.poll_tracker()
        card = next((i for i in view_of(svc)["inbox"]["open"] if i["key"] == "octo/p00#5/ac1"), None)
        self.assertIsNotNone(card)
        self.assertEqual([p["line"] for p in card["pictures"]], ["before.png", "after.png"])
        self.assertEqual(card["missing_pictures"], [])

    def test_a_non_png_or_outside_path_is_neither_listed_nor_served(self):
        svc = self.served(Scripted([self.check]))
        lines = [p["line"] for p in self.the_check(svc)["pictures"]]
        self.assertNotIn("fake.png", lines)
        self.assertNotIn("x.png", lines)
        self.assertEqual(self.fetch(svc, sha256(JPEG))[0], 404)
        self.assertEqual(self.fetch(svc, sha256(self.other))[0], 404)
        self.assertIsNone(pictures.read(svc.pictures_dir, sha256(self.other)))

    def test_a_configured_screenshot_location_is_served(self):
        check = dict(CHECK, detail=f"{self.screens}/s.png")
        svc = self.opened(Scripted([check]), screenshot_dirs=[self.screens])
        svc.poll_tracker()
        self.assertEqual([p["line"] for p in self.the_check(svc)["pictures"]], ["s.png"])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "console" / "events.sqlite3"
        fresh = self.opened(Scripted([check]))
        fresh.poll_tracker()
        self.assertEqual(self.the_check(fresh)["pictures"], [])

    def test_a_second_poll_with_unchanged_files_appends_no_row(self):
        svc = self.opened(Scripted([self.check]))
        svc.poll_tracker()
        rows = support.log_rows(self.store)
        svc.poll_tracker()
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_checks_picture_outlives_the_sweep(self):
        now = [time.time()]
        svc = self.opened(Scripted([self.check]), clock=lambda: now[0])
        svc.poll_tracker()
        old = now[0] - 2 * DAY
        os.utime(svc.pictures_dir / sha256(PIXEL), (old, old))
        svc.retain()
        self.assertEqual(pictures.read(svc.pictures_dir, sha256(PIXEL)), PIXEL)

    def test_a_sweep_waits_while_a_check_picture_is_being_stored(self):
        now = [time.time()]
        svc = self.opened(Scripted([self.check]), clock=lambda: now[0])
        svc.poll_tracker()
        old = now[0] - 2 * DAY
        stored = svc.pictures_dir / sha256(PIXEL)
        os.utime(stored, (old, old))
        swept = threading.Event()
        real_sweep, real_store = pictures.sweep, pictures.store
        sweeper = threading.Thread(target=svc.retain)
        raced = []

        def sweep(*args):
            try:
                return real_sweep(*args)
            finally:
                swept.set()

        def store(directory, data):
            if data == PIXEL and not sweeper.is_alive() and not swept.is_set():
                sweeper.start()
                raced.append(swept.wait(0.3))
            return real_store(directory, data)

        with mock.patch.object(pictures, "sweep", sweep), mock.patch.object(pictures, "store", store):
            svc.poll_tracker()
            sweeper.join(5)
        self.assertEqual(raced, [False], "the sweep ran while a picture was being stored")
        self.assertTrue(swept.is_set())
        self.assertEqual(pictures.read(svc.pictures_dir, sha256(PIXEL)), PIXEL)

    def test_other_items_gain_no_picture_members(self):
        svc = self.opened(Scripted([A]))
        svc.poll_tracker()
        card = next(i for i in view_of(svc)["inbox"]["open"] if i["key"] == A["key"])
        self.assertNotIn("pictures", card)
        self.assertNotIn("missing_pictures", card)

    def test_a_failed_attach_is_one_line_and_keeps_the_item(self):
        svc = self.opened(Scripted([self.check]))
        errors = io.StringIO()
        with mock.patch.object(inbox, "attach_pictures", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(errors):
            svc.poll_tracker()
        self.assertEqual(errors.getvalue(), "console: picture_attach_failed owner/p00 RuntimeError: boom\n")
        card = self.the_check(svc)
        self.assertIsNotNone(card)
        self.assertNotIn("pictures", card)

    def test_a_stop_during_the_attach_appends_nothing(self):
        svc = self.opened(Scripted([self.check]))
        rows = support.log_rows(self.store)
        with mock.patch.object(inbox, "attach_pictures",
                               side_effect=lambda item, *a, **k: (svc._stop.set(), item)[1]):
            svc.poll_tracker()
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

    def test_the_command_reads_the_pull_requests(self):
        recorded = {}

        def refuse(*args, **kwargs):
            recorded.update(kwargs)
            raise OSError("taken")

        with mock.patch.object(service, "ConsoleService", side_effect=refuse), \
                mock.patch.object(service, "default_store", return_value=Path("/nonexistent/store")), \
                mock.patch.object(service, "default_registry", return_value=Path("/nonexistent/registry")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["pull_reader"], movement.read_pulls)


    def test_the_command_passes_the_screenshot_locations(self):
        for argv, expected in ((["--port", "0", "--screenshots", "/a", "--screenshots", "/b"],
                                [Path("/a"), Path("/b")]), (["--port", "0"], [])):
            recorded = {}

            def refuse(*args, **kwargs):
                recorded.update(kwargs)
                raise OSError("taken")

            with mock.patch.object(service, "ConsoleService", side_effect=refuse), \
                    mock.patch.object(service, "default_store", return_value=Path("/nonexistent/store")), \
                    mock.patch.object(service, "default_registry", return_value=Path("/nonexistent/registry")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(console.main(argv), 1)
            self.assertEqual(recorded["screenshot_dirs"], expected)


if __name__ == "__main__":
    unittest.main()
