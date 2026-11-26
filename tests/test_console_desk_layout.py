"""The picture run's desk with one card and seven running sprints (#1807).

Run: just agent-workflow-tests
"""
import json
import os
import shutil
import subprocess
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

ROOT = Path(__file__).resolve().parents[1]
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


class DeskLayoutTest(unittest.TestCase):
    """The Work column's full-width layout, read in Chromium."""

    READ = """() => {
        const grid = document.querySelector(".desk-grid");
        const style = getComputedStyle(grid);
        const box = grid.getBoundingClientRect();
        const mid = (box.left + parseFloat(style.paddingLeft) + box.right - parseFloat(style.paddingRight)) / 2;
        const rect = (node) => node.getBoundingClientRect();
        const blocks = [...document.querySelectorAll("#projects li.sprint")].map((node) => {
            const r = rect(node);
            return {top: r.top, bottom: r.bottom, left: r.left, width: r.width};
        });
        const lefts = [...document.querySelectorAll(".desk-grid > main > *, #projects li.sprint")]
            .map(rect).filter((r) => r.width > 0 && r.height > 0 && r.left < mid);
        let gap = 0;
        if (blocks.length) {
            const top = Math.min(...blocks.map((b) => b.top));
            const bottom = Math.max(...blocks.map((b) => b.bottom));
            const clipped = lefts.map((r) => [Math.max(r.top, top), Math.min(r.bottom, bottom)])
                .filter((r) => r[1] > r[0]).sort((a, b) => a[0] - b[0]);
            let cursor = top;
            for (const [from, to] of clipped) {
                if (from - cursor > gap) gap = from - cursor;
                cursor = Math.max(cursor, to);
            }
            if (bottom - cursor > gap) gap = bottom - cursor;
        }
        const wide = grid.classList.contains("work-wide");
        const height = document.documentElement.scrollHeight;
        grid.classList.remove("work-wide");
        const baseHeight = document.documentElement.scrollHeight;
        const bottomOf = (selector) => rect(grid.querySelector(selector)).bottom;
        const overhang = bottomOf(":scope > .side") - bottomOf(":scope > main");
        if (wide) grid.classList.add("work-wide");
        return {mid, blocks, gap, wide, height, baseHeight, overhang};
    }"""
    IS_WIDE = "document.querySelector('.desk-grid').classList.contains('work-wide')"

    def chromium(self):
        return controls.ControlTargetTest.chromium(self)

    def desk(self, browser, state, width):
        return open_desk(self, browser, state, width)

    def test_one_card_and_seven_sprints_leave_no_tall_empty_left_and_a_shorter_page_at_1440(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        got = page.evaluate(self.READ)
        self.assertEqual(len(got["blocks"]), 7)
        self.assertLessEqual(got["gap"], 900, f"the gap in {got['gap']}")
        self.assertLess(got["height"], got["baseHeight"])

    def test_the_wide_rule_turns_at_900_px(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        self.assertEqual(page.evaluate(
            "[EMPTY_LEFT_PX, deskWide(0, 900), deskWide(0, 901), deskWide(100, 1001), deskWide(100, 1000)]"),
            [900, False, True, True, False])

    def test_the_desk_goes_wide_exactly_when_its_work_would_run_over_900_px_below_the_cards(self) -> None:
        browser = self.chromium()
        wides = []
        for state in ("seven-sprints", "live-several", "inbox-card", "nothing-running"):
            with self.subTest(state=state):
                got = self.desk(browser, state, 1440).evaluate(self.READ)
                wides.append(got["wide"])
                self.assertEqual(got["wide"], got["overhang"] > 900, f"overhang {got['overhang']}")
                if state == "seven-sprints":
                    lefts = sorted({round(b["left"]) for b in got["blocks"]})
                    self.assertEqual(len(lefts), 2, lefts)
                    self.assertLess(lefts[0], got["mid"])
        self.assertIn(True, wides)
        self.assertIn(False, wides)

    def test_the_phone_width_keeps_one_column(self) -> None:
        browser = self.chromium()
        for width in (390, 480):
            with self.subTest(width=width):
                got = self.desk(browser, "seven-sprints", width).evaluate(self.READ)
                self.assertEqual(len({round(b["left"]) for b in got["blocks"]}), 1)
                self.assertLessEqual(abs(got["height"] - got["baseHeight"]), 1)
                for block in got["blocks"]:
                    self.assertAlmostEqual(block["width"], got["blocks"][0]["width"], delta=1)

    def test_a_resize_lays_the_desk_out_again(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        self.assertTrue(page.evaluate(self.IS_WIDE))
        page.evaluate("document.querySelector('.desk-grid > main').appendChild(Object.assign("
                      "document.createElement('div'), {className: 'test-tall'})).style.height = '40000px'")
        page.set_viewport_size({"width": 1441, "height": shots.HEIGHT})
        page.wait_for_function(
            "() => !document.querySelector('.desk-grid').classList.contains('work-wide')", timeout=5000)

    def test_an_overlap_line_spans_both_block_columns(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        page.evaluate("document.querySelector('#projects li.sprint').after(Object.assign("
                      "document.createElement('li'), {className: 'overlap', textContent: 'x'}))")
        self.assertTrue(page.evaluate(self.IS_WIDE))
        overlap = page.evaluate("document.querySelector('#projects li.overlap').getBoundingClientRect().width")
        blocks = page.evaluate("document.querySelector('.sprint-blocks').getBoundingClientRect().width")
        self.assertLessEqual(abs(overlap - blocks), 1)

    def test_the_work_columns_other_parts_keep_a_reading_width(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        self.assertTrue(page.evaluate(self.IS_WIDE))
        widths = page.evaluate("""[...document.querySelectorAll(
            "#projects > :not(.sprint-blocks), .desk-grid > .side > :not(#projects)")]
            .map((node) => node.getBoundingClientRect().width).filter((width) => width > 0)""")
        self.assertTrue(widths)
        self.assertLessEqual(max(widths), 704.5, widths)

    def test_closing_a_tall_reading_panel_lays_the_desk_out_wide_again(self) -> None:
        page = self.desk(self.chromium(), "seven-sprints", 1440)
        self.assertTrue(page.evaluate(self.IS_WIDE))
        page.evaluate("""() => {
            const panel = document.getElementById("reading");
            panel.hidden = false;
            panel.appendChild(Object.assign(document.createElement("div"), {className: "test-tall"})).style.height = "40000px";
            layDesk();
        }""")
        self.assertFalse(page.evaluate(self.IS_WIDE))
        page.evaluate("closeReading()")
        self.assertTrue(page.evaluate(self.IS_WIDE))


class ScreenshotRecipeTest(unittest.TestCase):
    """The `console-screenshots` recipe hands its words to the shooter as the words they were typed as."""

    def run_recipe(self, *words: str) -> list[str]:
        self.assertIsNotNone(shutil.which("just"), "just is not on PATH")
        tmp = Path(tempfile.mkdtemp(prefix="console-screenshots-recipe-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "bin").mkdir()
        log = tmp / "argv.log"
        stubs = {
            tmp / "bin" / "nix": f"#!/bin/sh\nprintf '%s\\n' '{tmp}'\n",
            tmp / "bin" / "python3": f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> '{log}'\n",
        }
        for path, text in stubs.items():
            path.write_text(text)
            path.chmod(0o755)
        env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp)}
        done = subprocess.run(["just", "--justfile", str(ROOT / "justfile"), "console-screenshots", *words],
                              capture_output=True, text=True, env=env, cwd=tmp, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return log.read_text().splitlines()

    def test_a_quoted_question_stays_one_argument_and_its_shell_syntax_does_not_run(self) -> None:
        marker = Path(tempfile.mkdtemp(prefix="console-screenshots-marker-")) / "ran"
        self.addCleanup(shutil.rmtree, marker.parent, True)
        question = f"a b; touch {marker}"
        got = self.run_recipe("my out", "--question", question)
        self.assertEqual(got[-4:], ["--out", "my out", "--question", question])
        self.assertFalse(marker.exists())

    def test_an_empty_out_shoots_into_the_default_directory(self) -> None:
        got = self.run_recipe("", "--states", "seven-sprints")
        self.assertEqual(got[-4], "--out")
        self.assertTrue(got[-3].endswith("/tmp/clarity-screenshots"), got)
        self.assertEqual(got[-2:], ["--states", "seven-sprints"])


if __name__ == "__main__":
    unittest.main()
