"""The picture run's held permission prompts.

Run: just agent-workflow-tests
"""
import http.client
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from . import console_screenshot_permissions as perms
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # the real picture-run capture serves a console per width


class PermissionShotTest(unittest.TestCase):
    def test_the_long_permission_shot_finds_the_held_prompt_with_its_summary_at_each_width(self) -> None:
        with mock.patch.object(shots, "keep_permission", wraps=shots.keep_permission) as kept:
            views = self.permission_views("permission-long")
        self.assertEqual(kept.call_count, len(shots.WIDTHS))
        self.assertEqual([width for width, _ in views], list(shots.WIDTHS))
        summary = {"read": True, "runs": ["python3", "cat", "git"],
                   "writes": ["/tmp/uploads-notes.md", "review/diff.txt"], "outside": ["/tmp/uploads-notes.md"],
                   "scripts": [{"program": "python3", "lines": 28, "paths": ["tests/test_uploads.py"]}]}
        for width, view in views:
            with self.subTest(width=width):
                held = [i for i in view["inbox"]["open"] if i["reason"] == "permission"]
                self.assertEqual([(i["command"], i["words"]) for i in held],
                                 [(perms.PERMISSION_LONG_COMMAND, perms.PERMISSION_LONG_WORDS)])
                self.assertEqual([i["summary"] for i in held], [summary])
                self.assertEqual(view["statement"]["inbox_items"], 1)

    def permission_views(self, state: str) -> list:
        """What a shot of `state` finds on the console at each width: `(width, /api/state)`, from the real `capture`."""
        class Browser:
            def close(self):
                pass

        class Playwright:
            chromium = types.SimpleNamespace(launch=lambda args=None: Browser())

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        api = types.ModuleType("playwright.sync_api")
        api.Error = type("Error", (Exception,), {})
        api.sync_playwright = Playwright
        views = []

        def fake(browser, url, state, width, out, **kwargs):
            host, port = url.split("//")[1].split("/")[0].split(":")
            connection = http.client.HTTPConnection(host, int(port))
            try:
                connection.request("GET", "/api/state")
                views.append((width, json.loads(connection.getresponse().read())))
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                              "playwright.sync_api": api}), \
                mock.patch.object(shots, "_shoot", side_effect=fake):
            shots.capture(Path(tmp), states=(state,), home=Path(tmp) / "home")
        return views

    def test_the_permission_card_shot_finds_the_held_prompt_at_each_width(self) -> None:
        # Without `hold_permission` in `capture` the PNGs are still named right, so the view is read at the shot.
        views = self.permission_views("permission-card")
        self.assertEqual([width for width, _ in views], list(shots.WIDTHS))
        for width, view in views:
            with self.subTest(width=width):
                held = [i for i in view["inbox"]["open"] if i["reason"] == "permission"]
                self.assertEqual([(i["command"], i["words"]) for i in held],
                                 [(perms.PERMISSION_COMMAND, perms.PERMISSION_WORDS)])
                self.assertEqual(view["statement"]["inbox_items"], 1)

    def test_the_permission_stale_shot_finds_nothing_that_needs_the_owner(self) -> None:
        views = self.permission_views("permission-stale")
        self.assertEqual([width for width, _ in views], list(shots.WIDTHS))
        for width, view in views:
            with self.subTest(width=width):
                self.assertEqual(view["statement"]["inbox_items"], 0)
                self.assertEqual(view["inbox"]["open"], [])
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "permission-stale", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                svc.poll_sessions()
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        self.assertEqual(view["statement"]["inbox_items"], 0)

    def test_the_held_prompt_is_a_card_in_the_fixture_view_once_posted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "permission-card", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                before = json.loads(svc.view_bytes)
                held = perms.hold_permission(svc, fixture)
                perms.keep_permission(svc, fixture, held)
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        self.assertEqual(before["statement"]["inbox_items"], 0)
        self.assertIsInstance(held, int)
        self.assertEqual([i["command"] for i in view["inbox"]["open"]], [perms.PERMISSION_COMMAND])
        self.assertEqual(view["statement"]["inbox_items"], 1)


if __name__ == "__main__":
    unittest.main()
