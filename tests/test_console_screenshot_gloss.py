"""The screenshot state that shows a tapped gloss on a sprint's status line (#1797).

Run: just agent-workflow-tests
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import owner_words

from . import console_screenshot_gloss as gloss
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_screenshots import fake_browser

TIER = "fast"
URL = "http://console.test/"


def shoot(state, present, head):
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(shots, "style_applies", return_value=head):
        browser, page = fake_browser(present)
        shots._shoot(browser, URL, state, 480, Path(tmp))
    return page


class GlossShotTest(unittest.TestCase):
    def test_the_gloss_state_reports_a_status_with_a_glossary_word(self) -> None:
        calls = []

        class StandIn:
            now_s = 1_800_000_000.0

            def sprint(self, *args, **kwargs):
                calls.append(kwargs)
                return "0" * 16, "Add resumable uploads."

        shots._seed_state(StandIn(), "jargon-gloss")
        self.assertEqual([c.get("report_extra") for c in calls], [{"status": gloss.GLOSS_STATUS}])
        self.assertEqual(calls[0]["report"], 45 * shots.MINUTE)
        self.assertNotEqual(owner_words.unglossed(gloss.GLOSS_STATUS), [])

    def test_the_head_shot_opens_the_report_and_taps_its_mark(self) -> None:
        page = shoot("jargon-gloss", {gloss.GLOSS_MARK}, True)
        self.assertEqual(page.clicks, [gloss.GLOSS_FOLD + " > summary", gloss.GLOSS_MARK])
        self.assertIn(gloss.GLOSS_FOLD + "[open] p.report-status", page.waits)
        self.assertIn(gloss.GLOSS_FOLD + " p.report-status .gloss-text", page.waits)

    def test_the_head_shot_fails_when_the_report_has_no_mark(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "gloss mark"):
            shoot("jargon-gloss", set(), True)

    def test_the_base_shot_opens_the_same_report_with_its_plain_status(self) -> None:
        page = shoot("jargon-gloss", set(), False)
        self.assertEqual(page.clicks, [gloss.GLOSS_FOLD + " > summary"])
        self.assertIn(gloss.GLOSS_FOLD + "[open] p.report-status", page.waits)
        self.assertFalse([w for w in page.waits if ".gloss-text" in w])

    def test_another_state_taps_no_gloss(self) -> None:
        page = shoot("paused", {gloss.GLOSS_MARK}, True)
        self.assertFalse([c for c in page.clicks if "gloss" in c])


if __name__ == "__main__":
    unittest.main()
