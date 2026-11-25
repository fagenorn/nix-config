"""The short id a manager's background launch prints, and how `run_launch` returns it.

Run: just agent-workflow-tests
"""
import subprocess

from agent_tools.console import manager

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_manager import Case

TIER = "fast"

LINE = "backgrounded · 7c5dcf5d · n"
PRINTED = (
    "cat <<'EOF'\n"
    "Starting background service…\n"
    "backgrounded · 7c5dcf5d · owner/p01 sprint bbbbbbbbbbbbbbbb\n"
    "  claude agents             list sessions\n"
    "  claude attach 7c5dcf5d    open in this terminal\n"
    "EOF\n")
ENVIRON = {"PATH": "/p", "HOME": "/h"}


class LaunchShortIdTest(Case):
    def test_run_launch_returns_the_short_id_the_launch_printed(self):
        environ = self.fake_client(PRINTED)
        launch = self.launch(root=str(self.root))
        found = manager.run_launch(launch, platform="darwin", environ=environ)
        self.assertEqual(found, "7c5dcf5d")

    def test_printed_short_id_reads_exactly_one_backgrounded_line(self):
        rows = [
            ("backgrounded · 7c5dcf5d · flaky-test-fix\n", "7c5dcf5d"),
            ("backgrounded · 7c5dcf5d\n", "7c5dcf5d"),
            ("\x1b[1mbackgrounded · 7c5dcf5d · n\x1b[0m\r\n", "7c5dcf5d"),
            ("Starting background service…\nbackgrounded · 7c5dcf5d · n\n"
             "  claude stop 7c5dcf5d    stop this session\n", "7c5dcf5d"),
            (LINE + "\n" + LINE + "\n", "7c5dcf5d"),
            ("  " + LINE + "  \n", "7c5dcf5d"),
            ("", None),
            ("backgrounded · 7C5DCF5D · n", None),
            ("backgrounded · 7c5dcf5 · n", None),
            ("backgrounded · 7c5dcf5d0 · n", None),
            ("note: backgrounded · 7c5dcf5d", None),
            ("backgrounded - 7c5dcf5d", None),
            (LINE + "\nbackgrounded · 0657a088 · n\n", None),
        ]
        for text, expected in rows:
            with self.subTest(text=text):
                self.assertEqual(manager.printed_short_id(text), expected)

    def test_a_failed_launch_ignores_what_it_printed(self):
        environ = self.fake_client("echo 'backgrounded · 7c5dcf5d · n'\necho boom >&2\nexit 3\n")
        with self.assertRaises(manager.LaunchFailed) as raised:
            manager.run_launch(self.launch(root=str(self.root)), platform="darwin", environ=environ)
        self.assertEqual(str(raised.exception), "boom")

    def test_a_launch_that_printed_nothing_returns_none(self):
        found = manager.run_launch(self.launch(root=str(self.root)), platform="linux",
                                   run=self.fake(), environ=ENVIRON)
        self.assertIsNone(found)

    def test_the_launch_keeps_stdout_in_its_own_temporary_file(self):
        run = self.fake()
        manager.run_launch(self.launch(root=str(self.root)), platform="linux", run=run,
                           environ=ENVIRON)
        argv, kwargs = run.calls[0]
        self.assertNotIn(kwargs["stdout"], (subprocess.PIPE, subprocess.DEVNULL, None))
        self.assertTrue(hasattr(kwargs["stdout"], "fileno"))
        self.assertIsNot(kwargs["stdout"], kwargs["stderr"])
        self.assertNotIn("capture_output", kwargs)
