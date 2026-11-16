"""The sprint screenshot set against a fixture console (#1086).

Run: just agent-workflow-tests
"""
import dataclasses
import json
import os
import pwd
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import accounts_sandbox
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def fixture_paths(fixture):
    paths = [value for field in dataclasses.fields(fixture)
             for value in ([getattr(fixture, field.name)] if field.name != "projects"
                           else list(fixture.projects))]
    return paths


def entries_of(view):
    for entry in view["entries"]:
        yield from (entry["projects"] if entry["type"] == "quiet_group" else [entry])


def all_sprints(view):
    found = []
    for project in entries_of(view):
        found.extend(project.get("sprints") or [])
        found.extend((project.get("finished_sprints") or {"sprints": []})["sprints"])
    return found


class ScreenshotFixtureTest(unittest.TestCase):
    def test_the_set_is_ten_states_at_two_widths(self) -> None:
        self.assertEqual(len(shots.STATES), 10)
        self.assertEqual(shots.STATES.index("tell-box-open"), shots.STATES.index("stuck") + 1)
        self.assertEqual(shots.WIDTHS, (1440, 480))

    def test_a_shot_with_jargon_or_a_clamped_sentence_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 0, 1))
        self.assertEqual(code, 1)
        self.assertIn("jargon label", text)
        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 1, 0))
        self.assertEqual(code, 1)
        self.assertIn("squeezes the now sentence", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 (False, None, None)))
        self.assertEqual(code, 1)
        self.assertIn("does not show the open Tell box", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 shots.OPEN_TELL))
        self.assertEqual(code, 0)

    def test_every_fixture_path_is_temporary_and_never_a_real_one(self) -> None:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        real_registry = real_home / ".agents" / "state" / "fleet" / "registry.json"
        protected = [*accounts_sandbox.real_accounts_dirs(), real_home / ".agents" / "state"]
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = shots.build_fixture(root, state, time.time())
                paths = fixture_paths(fixture)
                for path in paths:
                    self.assertTrue(path.resolve().is_relative_to(root), path)
                self.assertFalse(accounts_sandbox.overlaps(paths, protected))
                self.assertNotEqual(fixture.registry.resolve(), real_registry.resolve())
                for value in shots.sandbox_environ(root).values():
                    self.assertTrue(Path(value).resolve().is_relative_to(root), value)
                self.assertEqual(
                    sorted(shots.sandbox_environ(root)),
                    ["CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR", "HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME"])
                svc = shots.start_service(fixture, time.time())
                try:
                    self.assertEqual(svc.registry, fixture.registry)
                finally:
                    svc.close()

    def test_each_fixture_view_shows_its_state(self) -> None:
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                launches: list = []
                svc = shots.start_service(fixture, now_s, launches)
                try:
                    view = json.loads(svc.view_bytes)
                finally:
                    svc.close()
                sprints = all_sprints(view)
                running = [s for s in sprints if s["ended_at"] is None]
                ended = [s for s in sprints if s["ended_at"] is not None]
                self.assertEqual(launches, [])
                for sprint in running:
                    self.assertEqual(sprint["manager_state"], "started", sprint["title"])
                    self.assertIsNone(sprint["manager_text"], sprint["title"])
                    self.assertFalse(sprint["now_text"].startswith("Working on"), sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["status"])
                    self.assertEqual(
                        [m for m in sprint["messages"]
                         if m["kind"] == "approved" and m["state"] == "picked_up"], [])
                latest = [s["messages"][-1] for s in running if s["messages"]]
                if state == "live-several":
                    self.assertEqual(len(running), 3)
                    self.assertEqual(
                        len({p["project_id"] for p in entries_of(view) if p.get("sprints")}), 2)
                    self.assertEqual({s["ball"] for s in running},
                                     {"manager", "owner", "nobody"})
                elif state == "waiting-on-you":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "waiting for your answer: Which store should the checkpoint use?")
                elif state == "stuck":
                    self.assertEqual([s["ball"] for s in running], ["nobody"])
                    self.assertEqual(running[0]["now_text"],
                                     "last seen building 1 of 2: the upload form")
                elif state == "tell-box-open":
                    self.assertEqual(len(running), 1)
                    self.assertEqual(running[0]["messages"], [])
                    self.assertIsInstance(running[0]["tell_text"], str)
                elif state == "message-sent":
                    self.assertEqual(len(running[0]["messages"]), 1)
                    self.assertEqual(latest[-1]["state"], "sent")
                elif state == "message-picked-up":
                    self.assertEqual(latest[-1]["state"], "picked_up")
                elif state == "message-replied":
                    self.assertEqual(latest[-1]["state"], "replied")
                    self.assertTrue(latest[-1]["new"])
                    self.assertIsInstance(view["new_replies_text"], str)
                elif state == "message-not-picked-up":
                    self.assertEqual(latest[-1]["state"], "not_picked_up")
                    self.assertTrue(latest[-1]["action_text"])
                elif state == "finished-list":
                    self.assertGreaterEqual(len(ended), 2)
                    self.assertTrue(any(s["closing"] for s in ended))
                elif state == "nothing-running":
                    self.assertEqual(running, [])


class ScreenshotCaptureTest(unittest.TestCase):
    def test_the_command_writes_twenty_pngs_and_nothing_scrolls_sideways(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            taken = shots.capture(out)
            self.assertEqual([s for s in taken if s.width == 480 and s.scroll_width > 480], [])
            self.assertEqual([s for s in taken if s.squeezed], [])
            self.assertEqual([s for s in taken if s.jargon], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "tell-box-open" and s.tell == shots.OPEN_TELL],
                list(shots.WIDTHS))
            self.assertEqual(
                [s for s in taken if s.state != "tell-box-open" and s.tell is not None], [])
            self.assertEqual(shots.main(["--out", str(out)]), 0)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(
                names, sorted(f"{s}-{w}.png" for s in shots.STATES for w in shots.WIDTHS))
            self.assertEqual(len(names), 20)
            for path in out.iterdir():
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
