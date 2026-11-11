"""The desk page's static invariants: one self-contained file, no other origin."""

import gzip
import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = PAGE.read_bytes()
        cls.text = cls.data.decode("utf-8")

    def test_the_page_names_no_other_origin(self) -> None:
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

    def test_the_page_is_under_60_kb_compressed(self) -> None:
        self.assertLess(len(gzip.compress(self.data, 9)), 61440)

    def test_the_page_requests_only_the_console_endpoints(self) -> None:
        literals = re.findall(
            r"\b(?:fetch|EventSource)\(\s*([\"'])([^\"']*)\1", self.text
        )
        self.assertEqual({p for _, p in literals}, {"/api/stream"})
        self.assertEqual(
            len(re.findall(r"\b(?:fetch|EventSource)\(", self.text)), len(literals)
        )

    def test_the_page_takes_its_view_only_from_the_stream(self) -> None:
        # A separate snapshot request can answer after a newer streamed frame
        # and render over it; the stream's first frame is already the snapshot.
        self.assertIsNone(re.search(r"\bfetch\(", self.text))
        self.assertEqual(self.text.count("render(JSON.parse("), 1)

    def test_peach_marks_only_needs_you(self) -> None:
        found = 0
        for body in re.findall(r"(?s)<style>(.*?)</style>", self.text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            for selector, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if "var(--peach)" in rule:
                    found += 1
                    self.assertIn(".needs", selector)
        self.assertGreater(found, 0)

    def test_the_page_never_parses_view_text_as_html(self) -> None:
        for name in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            with self.subTest(name=name):
                self.assertNotIn(name, self.text)

    def test_the_package_ships_the_page(self) -> None:
        config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        shipped = config["tool"]["setuptools"]["package-data"]["agent_tools.console"]
        self.assertIn("page.html", shipped)

    def test_the_page_listens_for_view_events(self) -> None:
        self.assertEqual(self.text.count('addEventListener("view",'), 1)
        self.assertNotIn("onmessage", self.text)
        self.assertIn('<section id="projects"', self.text)


if __name__ == "__main__":
    unittest.main()
