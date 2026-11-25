"""The picture run's desk with one card and seven running sprints (#1807).

Run: just agent-workflow-tests
"""
import json
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import console_screenshot_desk as desk
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_screenshots import all_sprints, entries_of

TIER = "integration"  # every case builds a seeded console; the layout cases drive Chromium


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
