"""The picture run's control target floors and its sprint fold shot.

Run: just agent-workflow-tests
"""
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import console_screenshot_controls as targets
from . import console_screenshots as shots
from . import test_console_screenshots as screenshot_tests
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # the real picture-run capture serves a console per state


class PhoneTargetTest(unittest.TestCase):
    def test_at_390_px_no_desk_or_spend_control_is_under_24_px_and_answers_and_tell_are_44_tall(self) -> None:
        taken = screenshot_tests.ScreenshotStyleTest.sandboxed_capture(
            self, states=shots._EVERY_STATE, widths=(targets.PHONE_WIDTH,))
        self.assertEqual(sorted(s.state for s in taken), sorted(shots._EVERY_STATE))
        self.assertEqual({s.width for s in taken}, {390})
        self.assertEqual({s.path.name: s.small for s in taken if s.small}, {})

    def test_the_target_reading_flags_a_small_control_and_a_short_phone_answer(self) -> None:
        bodies = [
            '<div style="display:flex"><a class="nav" href="/spend" '
            'style="width:39px;height:20px">Spend</a></div>',
            '<p>see <a href="/x">here</a> now</p>',
            '<button style="width:20px;height:32px;padding:0;border:0">x</button>',
            '<details><summary style="width:100px;height:20px">Show</summary></details>',
            '<button style="display:none;width:10px;height:10px">h</button>',
            '<button style="width:24px;height:24px;padding:0;border:0">o</button>',
            '<div id="inbox"><article class="card"><div class="act">'
            '<button class="send btn-primary" '
            'style="width:120px;height:40px;padding:0;border:0">Send</button></div></article></div>',
            '<div class="sprint-acts"><button class="tell-open btn-quiet" '
            'style="width:135px;height:32px;padding:0;border:0">Tell</button></div>',
            '<div id="inbox"><article class="card"><button class="pic-thumb btn-quiet btn-bare" '
            'style="width:30px;height:30px;padding:0;border:0"></button></article></div>',
        ]
        pages = [f"<body>{body}</body>" for body in bodies]
        read = screenshot_tests.ScreenshotReadingTest.read_pages
        phone = [["a.nav 39x20px"], [], ["button.- 20x32px"], ["summary.- 100x20px"], [], [],
                 ["button.send 40px under 44"], ["button.tell-open 32px under 44"], []]
        self.assertEqual(read(self, pages, targets.SMALL_TARGETS, width=390), phone)
        wide = phone[:6] + [[], [], []]
        self.assertEqual(read(self, pages, targets.SMALL_TARGETS, width=1440), wide)

    def test_a_shot_with_a_small_target_fails_the_command(self) -> None:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", return_value=[
                    shots.Shot("live-several", 1440, Path(tmp) / "p.png", 1440,
                               small=("a.nav 39x20px", "button.tell-open 32px under 44"))]), \
                redirect_stdout(out):
            code = shots.main(["--out", tmp])
        self.assertEqual(code, 1)
        self.assertIn("console-screenshots: p.png has a control under 24 by 24 px or a phone "
                      "answer under 44 px (a.nav 39x20px, button.tell-open 32px under 44)",
                      out.getvalue())


class SprintFoldShotTest(unittest.TestCase):
    def test_the_sprint_fold_shot_opens_the_sprints_fold_then_end_the_sprint(self) -> None:
        fake = screenshot_tests.fake_browser
        for state in ("sprint-fold-open", "tell-box-open", "live-several"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake(set())
                read = page.evaluate
                page.evaluate = lambda e, arg=None: [] if e == shots.TELL_READING else read(e, arg)
                shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                folds = [c for c in page.clicks if c in (targets.SPRINT_FOLD, targets.END_FOLD)]
                if state == "sprint-fold-open":
                    self.assertEqual(folds, [targets.SPRINT_FOLD, targets.END_FOLD])
                    self.assertIn(targets.END_OPEN, page.waits)
                else:
                    self.assertEqual(folds, [])
                    self.assertNotIn(targets.END_OPEN, page.waits)

    def test_the_sprint_fold_state_follows_the_tell_box_state(self) -> None:
        self.assertEqual(shots.STATES.index("sprint-fold-open"),
                         shots.STATES.index("tell-box-open") + 1)
