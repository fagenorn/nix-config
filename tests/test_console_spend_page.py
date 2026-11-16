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


if __name__ == "__main__":
    unittest.main()
