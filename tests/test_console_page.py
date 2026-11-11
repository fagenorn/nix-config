"""The desk page's static invariants: one self-contained file, no other origin."""

import gzip
import json
import re
import shutil
import subprocess
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"
HARNESS = REPO_ROOT / "tests/fixtures/console/page-harness.js"


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

    def test_session_states_use_the_state_colours(self) -> None:
        declared = dict(
            re.findall(r"(--(?:green|yellow|red)):\s*(#[0-9a-f]{6})", self.text)
        )
        self.assertEqual(
            declared, {"--green": "#a6da95", "--yellow": "#eed49f", "--red": "#ed8796"}
        )
        wanted = {
            ".s-working": "var(--green)",
            ".s-waiting_answer": "var(--yellow)",
            ".s-waiting_permission": "var(--yellow)",
            ".s-limit": "var(--red)",
        }
        rules = []
        for body in re.findall(r"(?s)<style>(.*?)</style>", self.text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            rules += re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        for selector, colour in wanted.items():
            with self.subTest(selector=selector):
                self.assertTrue(
                    any(
                        selector in sel and f"color: {colour}" in rule
                        for sel, rule in rules
                    ),
                    f"no rule colours {selector} with {colour}",
                )

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


def render(steps: list) -> list:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the page scenarios need it")
    done = subprocess.run(
        [node, str(HARNESS), str(PAGE)],
        input=json.dumps(steps),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def nodes(tree: dict) -> list:
    flat = [tree]
    for child in tree["children"]:
        flat += nodes(child)
    return flat


def text(tree: dict) -> str:
    return " ".join(n["text"] for n in nodes(tree))


def stamp(ago: timedelta) -> str:
    return (datetime.now(timezone.utc) - ago).isoformat(timespec="microseconds")


def session(session_id: str, state: str, state_text: str) -> dict:
    return {
        "session_id": session_id,
        "name": session_id,
        "state": state,
        "state_text": state_text,
        "cwd": "/srv/p00",
    }


def line(sessions: list, summary: str = "No sessions") -> dict:
    return {
        "label": "Outside sprints",
        "working": 0,
        "waiting": 0,
        "summary": summary,
        "sessions": sessions,
    }


def project(number: int, sessions: list, quiet: bool = False, ago=None) -> dict:
    return {
        "type": "project",
        "project_id": f"owner/p{number:02d}",
        "root": f"/srv/p{number:02d}",
        "quiet": quiet,
        "open_work": 0,
        "last_activity": stamp(ago or timedelta(minutes=1)),
        "outside_sprints": line(sessions),
    }


def view(entries: list, unmanaged: list | None = None, count: int | None = None) -> dict:
    return {
        "statement": {"inbox_items": 0, "headline": "Nothing needs you", "sentence": "ok"},
        "project_count": len(entries) if count is None else count,
        "entries": entries,
        "unmanaged": unmanaged or [],
    }


def unmanaged_entry(sessions: list) -> dict:
    return {
        "type": "unmanaged",
        "root": "/srv/elsewhere",
        "label": "Not yet managed",
        "outside_sprints": line(sessions, "1 idle"),
    }


WAITING = "waiting for an answer in its terminal"


class PageRenderTest(unittest.TestCase):
    def test_a_projects_sessions_render_under_outside_sprints(self) -> None:
        entry = project(0, [session("n2", "waiting_answer", WAITING),
                            session("s1", "working", "working")])
        entry["outside_sprints"]["summary"] = "1 working, 1 waiting"
        frame = view([entry], [unmanaged_entry([session("i1", "idle", "idle")])])
        (snap,) = render([{"frame": frame}, {"snapshot": True}])
        shown = text(snap["projects"])
        for wanted in ("Outside sprints", "1 working, 1 waiting", "n2", WAITING, "working"):
            self.assertIn(wanted, shown)
        (word,) = [n for n in nodes(snap["projects"]) if n["text"] == WAITING]
        self.assertIn("s-waiting_answer", word["cls"])
        elsewhere = text(snap["unmanaged"])
        for wanted in ("/srv/elsewhere", "Not yet managed", "idle"):
            self.assertIn(wanted, elsewhere)

    def test_a_project_without_sessions_has_no_fold(self) -> None:
        (snap,) = render([{"frame": view([project(0, [])])}, {"snapshot": True}])
        self.assertNotIn("outside:owner/p00", [n["key"] for n in nodes(snap["projects"])])
        self.assertEqual(snap["unmanaged"]["children"], [])

    def test_an_empty_fleet_still_shows_unmanaged_repositories(self) -> None:
        frame = view([], [unmanaged_entry([session("i1", "idle", "idle")])], count=0)
        (snap,) = render([{"frame": frame}, {"snapshot": True}])
        self.assertIn("No project is registered yet.", text(snap["projects"]))
        shown = text(snap["unmanaged"])
        self.assertIn("/srv/elsewhere", shown)
        self.assertIn("Not yet managed", shown)

    def test_open_folds_survive_a_new_frame(self) -> None:
        def frame(state: str) -> dict:
            group = {
                "type": "quiet_group",
                "label": "4 quiet projects",
                "count": 4,
                "projects": [project(n, [], quiet=True) for n in range(2, 6)],
            }
            return view([
                project(0, [session("a1", state, state)]),
                project(1, [session("b1", "working", "working")]),
                group,
            ], count=6)

        (snap,) = render([
            {"frame": frame("working")},
            {"open": "outside:owner/p00"},
            {"open": "quiet"},
            {"frame": frame("idle")},
            {"snapshot": True},
        ])
        by_key = {n["key"]: n for n in nodes(snap["projects"]) if n["key"]}
        self.assertTrue(by_key["outside:owner/p00"]["open"])
        self.assertTrue(by_key["quiet"]["open"])
        self.assertFalse(by_key["outside:owner/p01"]["open"])
        self.assertIn("idle", text(by_key["outside:owner/p00"]))

    def test_a_quiet_line_says_how_long_it_is_untouched(self) -> None:
        ages = [timedelta(days=3, hours=1), timedelta(days=1, hours=1), timedelta(hours=2)]
        entries = [project(n, [], quiet=True, ago=age) for n, age in enumerate(ages)]
        (snap,) = render([{"frame": view(entries)}, {"snapshot": True}])
        lines = {}
        for n in nodes(snap["projects"]):
            if "line" in n["cls"].split():
                lines[text(n)] = n
        by_project = {
            pid: next(t for t in lines if pid in t)
            for pid in ("owner/p00", "owner/p01", "owner/p02")
        }
        self.assertIn("untouched for 3 days", by_project["owner/p00"])
        self.assertIn("untouched for 1 day", by_project["owner/p01"])
        self.assertNotIn("1 days", by_project["owner/p01"])
        self.assertNotIn("untouched", by_project["owner/p02"])


if __name__ == "__main__":
    unittest.main()
