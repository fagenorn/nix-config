"""The Spend page's static invariants and render (#1135)."""

import gzip
import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEND = REPO_ROOT / "python/agent_tools/console/spend.html"
DESK = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"
SERVICE = REPO_ROOT / "python/agent_tools/console/service.py"
ADR_DIR = REPO_ROOT / "docs/areas/console/adr"


class SpendStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = SPEND.read_bytes()
        cls.text = cls.data.decode("utf-8")

    def test_the_package_ships_the_spend_page(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertIn(
            "spend.html", data["tool"]["setuptools"]["package-data"]["agent_tools.console"])

    def test_the_spend_page_names_no_other_origin(self) -> None:
        patterns = (
            rb"[A-Za-z][A-Za-z0-9+.-]*://",
            rb"(?i)\b(?:src|href|action|poster|srcset)\s*=\s*[\"']?\s*//",
            rb"(?i)url\(\s*[\"']?\s*//",
            rb"(?i)@import",
            rb"(?i)<base\b",
        )
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertEqual(re.findall(pattern, self.data), [])

    def test_the_spend_page_names_no_write_api(self) -> None:
        for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "<form",
                     "console-token", "__CONSOLE_TOKEN__", "X-Console-Token", "method:"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.text)
        self.assertEqual(
            re.findall(r"\b(?:fetch|EventSource)\(\s*([\"'])([^\"']*)\1", self.text),
            [('"', "/api/stream")])
        self.assertEqual(self.text.count('addEventListener("view",'), 1)

    def test_the_spend_page_links_back_to_the_desk(self) -> None:
        header = self.text[self.text.index('<header class="top">'):self.text.index("</header>")]
        self.assertEqual(header.count('<a class="nav" href="/">Desk</a>'), 1)
        self.assertEqual(re.findall(r'\shref="([^"]*)"', header), ["/"])
        self.assertEqual(
            re.findall(r'\shref="([^"]*)"', self.text[:self.text.index("<script>")]),
            ["data:,", "/"])

    def test_the_spend_page_never_parses_view_text_as_html(self) -> None:
        for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                     "toLocale"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.text)

    def test_the_spend_page_is_small(self) -> None:
        self.assertLess(len(gzip.compress(self.data, 9)), 20480)


class SpendDecisionCitationTest(unittest.TestCase):
    def test_the_service_cites_the_spend_page_decision_under_the_number_main_left_free(
            self) -> None:
        # origin/main took 050 for the wait-signals decision (#1110); the Spend page
        # decision is the next free number, and a file under the cited number, once it
        # exists, must be the decision made in #1135.
        cited = re.findall(
            r"GET /spend. serves the Spend page.*?\(#1135, ADR-console-(\d+)\)",
            SERVICE.read_text(encoding="utf-8"), re.S)
        self.assertEqual(cited, ["051"])
        for path in ADR_DIR.glob("%s-*.md" % cited[0]):
            self.assertIn("- **Decided in:** #1135", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
