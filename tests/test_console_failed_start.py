"""A manager that fails to start is shown in plain words, never as the raw reason (#1182)."""

import dataclasses
import unittest

from agent_tools.console import manager, view
from agent_tools.console.sprints import APPROVED, Manager
from agent_tools.console.view import derive_view, encode_view

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_view import T0, T0_MS, briefed, sprint, state

SID = "a" * 16
RAW = ("Workspace not trusted. Run `claude` in /home/anis/Projects/jarbird once and accept "
       "the trust prompt, then retry.")

UNTRUSTED_TEXT = "this account does not trust the project's folder"
NOT_INSTALLED_TEXT = "a program the manager needs is missing on this host"
SLOW_TEXT = "the launch did not answer in time"
NO_FOLDER_TEXT = "the project's folder is missing"
SETTINGS_TEXT = "the console could not write the manager's settings"
SECRET_TEXT = "the sprint's secret is missing"
REFUSED_TEXT = "the client refused to start the manager"

LAUNCH_FAILURES = (
    ("the project root /srv/p00 is not a directory", NO_FOLDER_TEXT),
    ("cannot write the manager's settings: Permission denied", SETTINGS_TEXT),
    ("systemd-run is not installed", NOT_INSTALLED_TEXT),
    ("the launch did not return within 30 s", SLOW_TEXT),
    ("the sprint's secret is missing", SECRET_TEXT),
    (manager.UNAVAILABLE_TEXT, manager.UNAVAILABLE_TEXT),
    ("error: the directory is not trusted", UNTRUSTED_TEXT),
    ("the launch exited 3", REFUSED_TEXT),
    ("OSError: [Errno 2] No such file: '/tmp/x'", REFUSED_TEXT),
    ("", REFUSED_TEXT),
    (None, REFUSED_TEXT),
    ("systemd-run is not installed; the directory is not trusted", UNTRUSTED_TEXT),
)


class PlainReasonTest(unittest.TestCase):
    def test_the_16_nov_refusal_reads_as_an_untrusted_folder(self):
        said = manager.plain_reason(RAW)
        self.assertEqual(said, UNTRUSTED_TEXT)
        for leak in ("/", "Workspace not trusted", "claude"):
            self.assertNotIn(leak, said)

    def test_each_launch_failure_has_its_plain_words(self):
        for raw, expected in LAUNCH_FAILURES:
            with self.subTest(raw=raw):
                self.assertEqual(manager.plain_reason(raw), expected)

    def test_no_plain_reason_names_a_path_or_echoes_its_input(self):
        for raw in (RAW, *(raw for raw, _ in LAUNCH_FAILURES)):
            with self.subTest(raw=raw):
                said = manager.plain_reason(raw)
                self.assertIn(said, manager.PLAIN_TEXTS)
                self.assertNotIn("/", said)
                self.assertTrue(said != raw or raw in manager.PLAIN_TEXTS)
        self.assertEqual(len(set(manager.PLAIN_TEXTS)), len(manager.PLAIN_TEXTS))
        for text in manager.PLAIN_TEXTS:
            with self.subTest(text=text):
                self.assertNotIn("/", text)
                self.assertNotIn("stalled", text)

    def test_the_raw_reason_reaches_no_member_of_the_view(self):
        plain = ("failed", "could not start a manager: " + UNTRUSTED_TEXT, True)
        first = dataclasses.replace(sprint(SID), manager=Manager("failed", T0, reason=RAW))
        takeover = dataclasses.replace(
            briefed(sprint(SID), decision=APPROVED, at=T0),
            manager=Manager("failed", T0, reason=RAW, takeover=True))
        for name, row in (("a first launch", first), ("a takeover", takeover)):
            with self.subTest(name):
                shown = derive_view([state("p00", 1)], sprints={SID: row},
                                    now_ms=T0_MS + 60_000)
                text = encode_view(shown).decode()
                entry = shown["entries"][0]["sprints"][0]
                self.assertEqual(
                    (entry["manager_state"], entry["manager_text"], entry["retry"]), plain)
                self.assertNotIn("/home/anis/Projects/jarbird", text)
                self.assertNotIn("Workspace not trusted", text)


if __name__ == "__main__":
    unittest.main()
