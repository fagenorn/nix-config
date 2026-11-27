"""The `host-alerts-panel` console screenshot (tests/console_screenshot_host_alerts.py).

Runs the screenshot's helper against a fake page, a loopback stand-in for Telegram and one fixture tree: the
panel is opened, its chats found and a test sent only where the page has the button, the helper imports
nothing the base commit lacks, and a base console starts bare while a head console gets the seeded panel.
Run: just agent-workflow-tests
"""
import ast
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import service
from agent_tools.hosts.host_alerts_panel import Panel
from agent_tools.hosts import host_alerts
from agent_tools.hosts.host_alerts import Chat, Settings

from . import console_screenshot_host_alerts as alert_shot
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_screenshots import shot_calls

TIER = "fast"  # a fake page, a loopback stand-in and one fixture tree

TESTS = Path(__file__).resolve().parent
OPENED = [("click", ("#host-alerts-open",)),
          ("wait_for_selector", ("#host-alerts:not([hidden])",)),
          ("click", ("button.alerts-find",)),
          ("wait_for_selector", ("button.alerts-chat",)),
          ("click", ("button.alerts-chat",)),
          ("click", ("button.alerts-test",)),
          ("wait_for_selector", (".alerts-result:not(:empty)",))]


def top_level_imports(path: Path) -> list[ast.stmt]:
    return [node for node in ast.parse(path.read_text()).body if isinstance(node, (ast.Import, ast.ImportFrom))]


class HostAlertsShotTest(unittest.TestCase):
    def test_the_host_alerts_shot_opens_the_panel_finds_chats_and_sends_a_test_only_where_the_page_has_one(self) -> None:
        calls = shot_calls("host-alerts-panel", {"#host-alerts-open"})
        steps = [call for call in calls if call in OPENED]
        self.assertEqual(steps, OPENED)
        for without in (shot_calls("host-alerts-panel", set()),
                        shot_calls("sharing-panel", {"#host-alerts-open"})):
            self.assertEqual([call for call in without if call in OPENED], [])

    def test_the_set_ends_with_the_host_alerts_state_and_the_recipe_counts_it(self) -> None:
        self.assertEqual(shots.STATES[-1], "host-alerts-panel")
        self.assertEqual(len(shots.STATES), 61)
        self.assertIn("122 PNGs into out", (TESTS.parent / "justfile").read_text())

    def test_the_helper_imports_nothing_the_base_commit_lacks(self) -> None:
        for node in top_level_imports(TESTS / "console_screenshot_host_alerts.py"):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            self.assertEqual(getattr(node, "level", 0), 0, ast.dump(node))
            for name in names:
                self.assertFalse(name.startswith("agent_tools") or name.startswith("tests"), name)
        screenshots = TESTS / "console_screenshots.py"
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None
                            and "console_screenshot_host_alerts" in [a.name for a in node.names]
                            for node in top_level_imports(screenshots)))
        self.assertNotIn("host_alerts_panel", [
            part for node in top_level_imports(screenshots)
            for part in (getattr(node, "module", None) or "").split(".") + [a.name for a in node.names]])

    def test_the_seed_starts_a_base_console_bare_and_a_head_console_with_the_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = alert_shot.service_kwargs(lambda store, registry, *, port=0: None, root, "http://127.0.0.1:9")
            self.assertEqual(base, {})
            self.assertEqual(list(root.iterdir()), [])
            api = "http://127.0.0.1:9"
            self.assertEqual(alert_shot.service_kwargs(service.ConsoleService, root, api),
                             {"host_alerts": Panel(root / "host-alerts" / "telegram.json", api=api)})
            seeded = root / "host-alerts" / "telegram.json"
            self.assertEqual(host_alerts.read_settings(seeded), Settings(True, alert_shot.TOKEN, alert_shot.CHAT))
            self.assertEqual(stat.S_IMODE(seeded.stat().st_mode), 0o600)
        with mock.patch.dict(os.environ, {"https_proxy": "http://proxy.invalid:3128", "ALL_PROXY": "x"}):
            before = {name: os.environ.get(name) for name in alert_shot.PROXY_VARIABLES}
            telegram = alert_shot.Telegram()
            try:
                self.assertEqual([name for name in alert_shot.PROXY_VARIABLES if name in os.environ], [])
                self.assertEqual(host_alerts.list_chats(alert_shot.TOKEN, api=telegram.api),
                                 ((Chat("-1001234", "Owner alerts"),), ""))
            finally:
                telegram.close()
            self.assertEqual({name: os.environ.get(name) for name in alert_shot.PROXY_VARIABLES}, before)

    def test_the_fixture_for_the_state_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = shots.build_fixture(Path(tmp), "host-alerts-panel", time.time())
        self.assertIsInstance(fixture, shots.Fixture)


if __name__ == "__main__":
    unittest.main()
