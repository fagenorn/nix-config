"""The desk page's static invariants: one self-contained file, no other origin."""

import gzip
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"
HARNESS = REPO_ROOT / "tests/fixtures/console/page-harness.js"

INBOX_HARNESS = r"""
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
  querySelectorAll: () => [],
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
  capacity: tree(ELEMENTS.capacity || null),
  promoted: tree(ELEMENTS.promoted || null),
}));
"""


def render_page(view: dict) -> dict:
    """The `#statement`, `#inbox`, `#capacity` and `#promoted` trees the page draws for `view`, run under node."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the page render tests need it")
    html = PAGE.read_text(encoding="utf-8")
    script = re.search(r"(?s)<script>(.*?)</script>", html).group(1)
    ids = re.findall(r'id="([^"]+)"', html)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.js"
        path.write_text(INBOX_HARNESS + script + TAIL, encoding="utf-8")
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

    def test_the_page_renders_the_inbox(self) -> None:
        view = {
            "project_count": 0, "entries": [], "unmanaged": [],
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

    def test_later_rows_keep_their_questions_and_issue(self) -> None:
        view = {
            "project_count": 0, "entries": [], "unmanaged": [],
            "statement": {"inbox_items": 3, "headline": "3 things need you",
                          "sentence": "s", "stale": False},
            "inbox": {
                "open": [
                    item("A", issue=11, question="Decisions are needed."),
                    item("B", issue=22, question="Decisions are needed.", questions=[
                        {"question": "Which cache?", "options": ["redis", "memcached"],
                         "chosen": "redis"}]),
                    item("C", issue=33, question="Decisions are needed.", questions=[
                        {"question": "Which queue?", "options": ["sqs", "nats"],
                         "chosen": None}]),
                ],
                "answered": [],
            },
        }
        rows = next(n for n in walk(render_page(view)["inbox"]) if n["cls"] == "rest")
        first, second = rows["children"]
        self.assertIn("owner/p00 #22", first["text"])
        self.assertIn("Which cache?", first["text"])
        self.assertIn("chosen: redis", first["text"])
        self.assertIn("owner/p00 #33", second["text"])
        self.assertIn("Which queue?", second["text"])
        self.assertIn("nats", second["text"])

    def test_an_answered_stale_item_shows_when_it_was_last_read(self) -> None:
        view = {
            "project_count": 0, "entries": [], "unmanaged": [],
            "statement": {"inbox_items": 0, "headline": "h", "sentence": "s", "stale": True},
            "inbox": {"open": [], "answered": [
                item("Z", answered=True, stale=True, read_at="2026-11-10T09:15:00+00:00"),
                item("W", answered=True),
            ]},
        }
        done = next(n for n in walk(render_page(view)["inbox"]) if n["cls"] == "done")
        stale, fresh = done["children"]
        self.assertIn("read at ", stale["text"])
        self.assertNotIn("read at ", fresh["text"])

    def test_an_empty_inbox_renders_no_item(self) -> None:
        view = {
            "project_count": 0, "entries": [], "unmanaged": [],
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
        "statement": {"inbox_items": 0, "headline": "Nothing needs you", "sentence": "ok",
                      "stale": False},
        "inbox": {"open": [], "answered": []},
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


def profile(name: str, state: str, **fields) -> dict:
    base = {"profile": name, "state": state, "week_left": None, "five_hour_left": None,
            "next_reset": None, "out_until": None, "read_at": "2026-11-10T08:30:00+00:00"}
    base.update(fields)
    return base


def capacity(profiles: list, **fields) -> dict:
    base = {"tight": False, "all_out": False, "resumes_at": None, "profiles": profiles}
    base.update(fields)
    return base


class CapacityPageTest(unittest.TestCase):
    def strip_view(self, **fields) -> dict:
        profiles = [
            profile("a", "ok", week_left=62, five_hour_left=40,
                    next_reset="2026-11-12T09:00:00+00:00"),
            profile("b", "unknown"),
            profile("c", "reset"),
        ]
        return {**view([]), "capacity": capacity(profiles, **fields)}

    def test_the_strip_shows_each_profile(self) -> None:
        result = render_page(self.strip_view())
        text = result["capacity"]["text"]
        for expected in ("a", "62% of the week left", "40% of 5 hours", "resets ", "b",
                         "no reading yet", "c", "reset, not yet used"):
            self.assertIn(expected, text)
        self.assertNotIn("tight", text)

    def test_tight_is_shown_only_when_the_view_says_so(self) -> None:
        result = render_page(self.strip_view(tight=True))
        self.assertTrue(result["capacity"]["text"].endswith("tight"))

    def test_every_profile_out_is_promoted_above_the_inbox(self) -> None:
        out = [profile("a", "out", out_until="2026-11-12T09:00:00+00:00"),
               profile("b", "out", out_until="2026-11-12T10:00:00+00:00")]
        full = {**view([]), "capacity": capacity(
            out, all_out=True, resumes_at="2026-11-12T09:00:00+00:00")}
        result = render_page(full)
        self.assertIn("Capacity", result["promoted"]["text"])
        self.assertEqual(result["promoted"]["text"].count("out until"), 2)
        self.assertIn("Resumes at", result["statement"]["text"])
        html = PAGE.read_text(encoding="utf-8")
        self.assertLess(html.index('id="promoted"'), html.index('id="inbox"'))
        partial = {**view([]), "capacity": capacity(
            out, all_out=False, resumes_at="2026-11-12T09:00:00+00:00")}
        shown = render_page(partial)
        self.assertEqual(shown["promoted"]["children"], [])
        self.assertNotIn("Resumes at", shown["statement"]["text"])

    def test_unknown_values_read_as_words_not_null_or_1970(self) -> None:
        profiles = [profile("a", "ok", five_hour_left=40), profile("b", "out")]
        text = render_page({**view([]), "capacity": capacity(profiles)})["capacity"]["text"]
        for expected in ("week unknown", "40% of 5 hours", "out, reset unknown"):
            self.assertIn(expected, text)
        for banned in ("null", "1970", "resets "):
            self.assertNotIn(banned, text)
        out = [profile("a", "out"), profile("b", "out")]
        result = render_page({**view([]), "capacity": capacity(out, all_out=True)})
        promoted = result["promoted"]["text"]
        self.assertEqual(promoted.count("out, reset unknown"), 2)
        for banned in ("null", "1970"):
            self.assertNotIn(banned, promoted)
        self.assertNotIn("Resumes at", result["statement"]["text"])

    def test_a_view_without_capacity_still_renders(self) -> None:
        result = render_page(view([]))
        self.assertEqual(result["capacity"]["children"], [])
        self.assertEqual(result["promoted"]["children"], [])


if __name__ == "__main__":
    unittest.main()
