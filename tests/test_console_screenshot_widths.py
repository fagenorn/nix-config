"""The screenshot command's --widths flag reaches the capture.

Run: just agent-workflow-tests
"""
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"  # the capture is mocked: only the command line is read


class ScreenshotWidthsTest(unittest.TestCase):
    def test_main_passes_the_widths_to_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(shots, "capture", return_value=[]) as capture, \
                    redirect_stdout(StringIO()):
                self.assertEqual(shots.main(["--out", tmp, "--sheets", "--states",
                                             "owner-actors,owner-accounts,accounts-panel",
                                             "--widths", "1440,390"]), 0)
                self.assertEqual(capture.call_args.kwargs["widths"], (1440, 390))
                self.assertEqual(capture.call_args.kwargs["states"],
                                 ("owner-actors", "owner-accounts", "accounts-panel"))
                self.assertEqual(shots.main(["--out", tmp]), 0)
                self.assertEqual(capture.call_args.kwargs["widths"], shots.WIDTHS)
                answer = Path(tmp) / "answer.txt"
                answer.write_text("Answer: plain", encoding="utf-8")
                self.assertEqual(shots.main(["--out", tmp, "--question", "Q?", "--answer-file",
                                             str(answer), "--widths", "390"]), 0)
                self.assertEqual(capture.call_args.kwargs["widths"], (390,))
            for value in ("", "1440,", "wide", "0", "-390", "1440,1440"):
                with self.subTest(value=value), mock.patch.object(shots, "capture") as capture, \
                        redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        shots.main(["--out", tmp, "--widths", value])
                    self.assertEqual(raised.exception.code, 2)
                    capture.assert_not_called()
