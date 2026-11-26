"""The picture run's desk with one card and seven running sprints (#1807).

Run: just agent-workflow-tests
"""
import json
import tempfile
import time
import unittest
from datetime import datetime
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import console_screenshot_desk as desk
from . import console_screenshots as shots
from . import test_console_controls as controls
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_screenshots import all_sprints, entries_of

TIER = "integration"  # every case builds a seeded console; the layout cases drive Chromium


def open_desk(test, browser, state, width):
    """The desk page of `state`'s seeded console, loaded in `browser` at `width` px; every cleanup is registered."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    now_s = time.time()
    fixture = shots.build_fixture(Path(tmp.name).resolve(), state, now_s)
    service = shots.start_service(fixture, now_s)
    test.addCleanup(service.close)
    page = browser.new_page(viewport={"width": width, "height": shots.HEIGHT})
    test.addCleanup(page.close)
    host, port = service.address
    page.goto(f"http://{host}:{port}/")
    page.wait_for_selector("#projects h2")
    if state == desk.SEVEN_SPRINTS:
        page.wait_for_function("document.querySelectorAll('#projects li.sprint').length === 7", timeout=10000)
    page.evaluate("document.fonts.ready.then(() => true)")
    return page


class SevenSprintsSeedTest(unittest.TestCase):
    def test_the_seven_sprints_seed_holds_seven_running_sprints_and_one_card(self) -> None:
        now_s = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = shots.build_fixture(Path(tmp), "seven-sprints", now_s)
            launches: list = []
            svc = shots.start_service(fixture, now_s, launches)
            try:
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        sprints = all_sprints(view)
        running = [s for s in sprints if s["ended_at"] is None]
        self.assertEqual(len(running), 7)
        self.assertEqual(len(sprints), 7)
        self.assertEqual({p["project_id"] for p in entries_of(view) if p.get("sprints")}, set(shots.PROJECTS))
        self.assertEqual(view["statement"]["inbox_items"], 1)
        self.assertEqual(sorted(s["ball"] for s in running), ["manager"] * 6 + ["owner"])
        self.assertEqual(launches, [])

    def test_the_seven_sprints_desk_leaves_the_left_empty_far_below_the_cards_at_1440(self) -> None:
        page = open_desk(self, controls.ControlTargetTest.chromium(self), "seven-sprints", 1440)
        got = page.evaluate("""() => {
            const grid = document.querySelector(".desk-grid");
            const wide = grid.classList.contains("work-wide");
            grid.classList.remove("work-wide");
            const bottom = (selector) => document.querySelector(selector).getBoundingClientRect().bottom;
            const last = Math.max(...[...document.querySelectorAll("#projects li.sprint")]
                .map((block) => block.getBoundingClientRect().bottom));
            const read = {main: bottom(".desk-grid > main"), side: bottom(".desk-grid > .side"), last};
            if (wide) grid.classList.add("work-wide");
            return read;
        }""")
        self.assertGreater(got["side"] - got["main"], 2700, f"side - main in {got}")
        self.assertGreater(got["last"] - got["main"], 2700, f"last - main in {got}")

    def test_the_seven_sprints_carry_the_live_desks_reports_exchanges_and_faults(self) -> None:
        now_s = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = shots.build_fixture(Path(tmp), "seven-sprints", now_s)
            svc = shots.start_service(fixture, now_s, [])
            try:
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        running = [s for s in all_sprints(view) if s["ended_at"] is None]
        for s in running:
            with self.subTest(sprint=s["title"]):
                self.assertEqual(len(s["issues"]), 20)
                self.assertTrue(s["messages"])
                last = s["messages"][-1]
                self.assertTrue(270 <= len(last["reply"].split()) <= 330, len(last["reply"].split()))
                self.assertTrue(270 <= len(last["text"].split()) <= 330, len(last["text"].split()))
                self.assertLess(datetime.fromisoformat(s["stated_at"]).timestamp(), now_s - 10 * 3600)
        self.assertEqual(sorted(len(s["live_faults"]) for s in running), [0] * 5 + [2, 2])
        for s in running:
            for fault in s["live_faults"]:
                self.assertTrue(380 <= len(fault["text"]) <= 420, len(fault["text"]))

    def test_the_seven_sprints_state_follows_failed_start(self) -> None:
        self.assertEqual(shots.STATES[shots.STATES.index("failed-start") + 1], desk.SEVEN_SPRINTS)
        self.assertEqual(desk.SEVEN_SPRINTS, "seven-sprints")

    def test_main_passes_the_widths_to_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(shots, "capture", return_value=[]) as capture, redirect_stdout(StringIO()):
                self.assertEqual(shots.main(["--out", tmp, "--states", "seven-sprints", "--widths", "1440,390"]), 0)
                self.assertEqual(capture.call_args.kwargs["widths"], (1440, 390))
                self.assertEqual(shots.main(["--out", tmp]), 0)
                self.assertEqual(capture.call_args.kwargs["widths"], shots.WIDTHS)
            for bad in ("", "1440,x", "0", "1440,"):
                with self.subTest(widths=bad):
                    with (mock.patch.object(shots, "capture") as capture, redirect_stderr(StringIO()),
                          self.assertRaises(SystemExit) as raised):
                        shots.main(["--out", tmp, "--widths", bad])
                    self.assertEqual(raised.exception.code, 2)
                    capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
