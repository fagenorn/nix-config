"""The desk page's static invariants: one self-contained file, no other origin."""

import gzip
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"

HARNESS = r"""
const ids = new Set(JSON.parse(process.argv[3]));
class Node {
  constructor(tag) {
    this.tagName = tag; this.className = ""; this.id = ""; this.href = "";
    this.rel = ""; this.open = false; this.children = [];
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...nodes) { this.children = nodes; }
  set textContent(text) { this.children = [{text: String(text)}]; }
  get textContent() {
    return this.children.map((c) => c.text !== undefined ? c.text : c.textContent).join("");
  }
}
const ELEMENTS = {};
const document = {
  createElement: (tag) => new Node(tag),
  getElementById(id) {
    if (!ids.has(id)) return null;
    if (id === "quiet-icon") {
      return {content: {firstElementChild: {cloneNode: () => new Node("svg")}}};
    }
    if (!(id in ELEMENTS)) ELEMENTS[id] = new Node("div");
    return ELEMENTS[id];
  },
  querySelector: () => null,
};
const kept = {};
class EventSource {
  addEventListener(name, fn) { kept[name] = fn; }
}
"""
TAIL = r"""
const tree = (n) => n === null ? null : {
  tag: n.tagName, cls: n.className, text: n.textContent, href: n.href, rel: n.rel,
  children: n.children.filter((c) => c.tagName !== undefined).map(tree),
};
kept.view({data: JSON.stringify(JSON.parse(process.argv[4]))});
console.log(JSON.stringify({
  statement: tree(ELEMENTS.statement || null),
  inbox: tree(ELEMENTS.inbox || null),
}));
"""


def render_page(view: dict) -> dict:
    """The `#statement` and `#inbox` trees the page draws for `view`, run under node."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the page render tests need it")
    html = PAGE.read_text(encoding="utf-8")
    script = re.search(r"(?s)<script>(.*?)</script>", html).group(1)
    ids = re.findall(r'id="([^"]+)"', html)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.js"
        path.write_text(HARNESS + script + TAIL, encoding="utf-8")
        done = subprocess.run(
            [node, str(path), "-", json.dumps(ids), json.dumps(view)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    if done.returncode != 0:
        raise AssertionError(f"the page failed under node: {done.stderr}")
    return json.loads(done.stdout)


def walk(tree: dict):
    yield tree
    for child in tree["children"]:
        yield from walk(child)


def item(key: str, **fields) -> dict:
    base = {
        "type": "inbox_item", "key": key, "project_id": "owner/p00", "issue": 7,
        "url": "/" + key.lower(), "reason": "decision", "question": f"Question {key}?",
        "questions": [], "items": [], "answered": False, "held_work": 1,
        "waiting_since": "2026-11-10T08:00:00+00:00", "stale": False,
        "read_at": "2026-11-10T08:30:00+00:00",
    }
    base.update(fields)
    return base


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

    def test_the_page_renders_the_inbox(self) -> None:
        view = {
            "project_count": 0, "entries": [],
            "statement": {"inbox_items": 2, "headline": "2 things need you",
                          "sentence": "s", "stale": True},
            "inbox": {
                "open": [
                    item("X", held_work=3, questions=[
                        {"question": "Which database?", "options": ["sqlite", "postgres"],
                         "chosen": "postgres"},
                        {"question": "Which port?", "options": ["80", "8080"],
                         "chosen": None},
                    ]),
                    item("Y", reason="conflict", question="The branch conflicts",
                         items=["Merge conflict in flake.lock"], held_work=1, stale=True,
                         read_at="2026-11-10T09:00:00+00:00"),
                ],
                "answered": [item("Z", answered=True, question="Already answered?")],
            },
        }
        result = render_page(view)
        self.assertIsNotNone(result["inbox"])
        h1 = next(n for n in walk(result["statement"]) if n["tag"] == "h1")
        self.assertEqual((h1["text"], h1["cls"]), ("2 things need you", "needs"))
        text = result["inbox"]["text"]
        for expected in ("Question X?", "Which database?", "Which port?",
                         "chosen: postgres", "holds 3 issues", "waiting since ",
                         "The branch conflicts", "Merge conflict in flake.lock",
                         "Answered, waiting for the agent"):
            self.assertIn(expected, text)
        self.assertEqual(text.count("read at "), 1)
        links = [(n["text"], n["href"], n["rel"])
                 for n in walk(result["inbox"]) if n["tag"] == "a"]
        self.assertEqual(links, [("Answer on the tracker", f"/{k}", "noreferrer")
                                 for k in "xyz"])

    def test_an_empty_inbox_renders_no_item(self) -> None:
        view = {
            "project_count": 0, "entries": [],
            "statement": {"inbox_items": 0, "headline": "Nothing needs you",
                          "sentence": "s", "stale": False},
            "inbox": {"open": [], "answered": []},
        }
        result = render_page(view)
        self.assertIsNotNone(result["inbox"])
        self.assertEqual([n for n in walk(result["inbox"]) if n["tag"] == "a"], [])
        self.assertNotIn("Answered, waiting for the agent", result["inbox"]["text"])
        h1 = next(n for n in walk(result["statement"]) if n["tag"] == "h1")
        self.assertEqual(h1["cls"], "")

    def test_the_tracker_link_is_the_only_href(self) -> None:
        self.assertEqual(len(re.findall(r"\.href\s*=", self.text)), 1)
        self.assertIsNotNone(re.search(r"\.href = item\.url;", self.text))


if __name__ == "__main__":
    unittest.main()
