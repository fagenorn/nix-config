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
    this.rel = ""; this.open = false; this.children = []; this.dataset = {};
  }
  addEventListener() {}
  setAttribute() {}
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
const window = {addEventListener() {}};
document.addEventListener = () => {};
document.hasFocus = () => false;
document.visibilityState = "visible";
const fetch = () => Promise.resolve({});
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

    def test_the_page_carries_one_token_slot(self) -> None:
        meta = '<meta name="console-token" id="console-token" content="__CONSOLE_TOKEN__">'
        self.assertEqual(self.text.count(meta), 1)
        self.assertEqual(self.text.count("__CONSOLE_TOKEN__"), 1)

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
        self.assertEqual(
            {p for _, p in literals},
            {"/api/stream", "/api/looked", "/api/answer", "/api/goal", "/api/withdraw",
             "/api/approve", "/api/reply"},
        )
        self.assertEqual(
            len(re.findall(r"\b(?:fetch|EventSource)\(", self.text)), len(literals)
        )

    def test_the_page_takes_its_view_only_from_the_stream(self) -> None:
        # A separate snapshot request can answer after a newer streamed frame
        # and render over it; the stream's first frame is already the snapshot.
        self.assertEqual(len(re.findall(r"\bfetch\(", self.text)), 6)
        self.assertIsNotNone(
            re.search(r'fetch\("/api/looked",\s*\{\s*method:\s*"POST"', self.text)
        )
        self.assertIsNotNone(
            re.search(r'fetch\("/api/answer",\s*\{\s*method:\s*"POST"', self.text)
        )
        for route in ("/api/goal", "/api/withdraw", "/api/approve", "/api/reply"):
            self.assertIsNotNone(
                re.search(rf'fetch\("{route}",\s*\{{\s*method:\s*"POST"', self.text)
            )
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

    def test_runs_are_never_peach_or_red_and_never_stalled(self) -> None:
        rules = []
        for body in re.findall(r"(?s)<style>(.*?)</style>", self.text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            rules += re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        runs = [
            (sel, rule)
            for sel, rule in rules
            if any(word in sel for word in (".run", ".runs", ".moved", ".quiet"))
        ]
        self.assertTrue(any(".run" in sel for sel, _ in runs))
        for sel, rule in runs:
            with self.subTest(selector=sel.strip()):
                self.assertNotIn("var(--peach)", rule)
                self.assertNotIn("var(--red)", rule)
        self.assertNotIn("stalled", self.text.lower())

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


def session(
    session_id: str, state: str, state_text: str, deliveries: list | None = None
) -> dict:
    entry = {
        "session_id": session_id,
        "name": session_id,
        "state": state,
        "state_text": state_text,
        "cwd": "/srv/p00",
    }
    if deliveries is not None:
        entry["deliveries"] = deliveries
    return entry


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
RUN = {
    "run_id": "wf_a",
    "quiet": False,
    "moved_text": "moved 3 min ago",
    "issues": [
        {"issue": 856, "stage": "building", "stage_text": "building task 3 of 5"},
        {"issue": 857, "stage": "plan review", "stage_text": "plan review"},
    ],
}


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

    def test_a_sessions_deliveries_render_their_stage_in_plain_words(self) -> None:
        entry = project(0, [session("s1", "working", "working", deliveries=[RUN])])
        (snap,) = render([{"frame": view([entry])}, {"snapshot": True}])
        (runs,) = [n for n in nodes(snap["projects"]) if "runs" in n["cls"].split()]
        (run,) = [n for n in nodes(snap["projects"]) if "run" in n["cls"].split()]
        self.assertEqual(
            [c["text"] for c in run["children"]],
            ["#856", "building task 3 of 5", "#857", "plan review", "moved 3 min ago"],
        )
        (moved,) = [n for n in nodes(run) if "moved" in n["cls"].split()]
        self.assertNotIn("quiet", moved["cls"].split())
        self.assertEqual([c["cls"] for c in run["children"]][:2], ["issue", "stage"])
        self.assertEqual([c["children"] for c in runs["children"]][0], run["children"])

    def test_a_quiet_run_says_quiet_and_never_stalled(self) -> None:
        quiet = dict(RUN, quiet=True, moved_text="quiet for 22 min")
        entry = project(0, [session("s1", "working", "working", deliveries=[quiet])])
        (snap,) = render([{"frame": view([entry])}, {"snapshot": True}])
        (moved,) = [
            n
            for n in nodes(snap["projects"])
            if {"moved", "quiet"} <= set(n["cls"].split())
        ]
        self.assertEqual(moved["text"], "quiet for 22 min")
        self.assertNotIn("stalled", text(snap["projects"]).lower())

    def test_a_session_without_deliveries_renders_no_runs(self) -> None:
        entry = project(0, [session("e1", "idle", "idle", deliveries=[]),
                            session("m1", "working", "working")])
        (snap,) = render([{"frame": view([entry])}, {"snapshot": True}])
        self.assertEqual(
            [n for n in nodes(snap["projects"]) if "runs" in n["cls"].split()], []
        )
        shown = text(snap["projects"])
        for wanted in ("e1", "idle", "m1", "working"):
            self.assertIn(wanted, shown)

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


TOKEN = "__CONSOLE_TOKEN__"
LOOK = {"url": "/api/looked", "method": "POST", "headers": {"X-Console-Token": TOKEN},
        "keepalive": True}


class PageFocusTest(unittest.TestCase):
    def test_a_hold_longer_than_five_seconds_posts_one_look_when_it_ends(self) -> None:
        (snap,) = render([
            {"start": {"focused": False, "clock": 0}}, {"clock": 1000}, {"focus": True},
            {"clock": 7000}, {"blur": True}, {"snapshot": True},
        ])
        self.assertEqual(snap["posts"], [LOOK])

    def test_a_glance_posts_nothing_and_a_later_hold_posts_once(self) -> None:
        (snap,) = render([
            {"start": {"focused": False, "clock": 0}},
            {"clock": 1000}, {"focus": True}, {"clock": 6000}, {"blur": True},
            {"clock": 7000}, {"focus": True}, {"clock": 12001}, {"blur": True},
            {"blur": True}, {"snapshot": True},
        ])
        self.assertEqual(snap["posts"], [LOOK])

    def test_a_page_loaded_with_focus_counts_from_load(self) -> None:
        (snap,) = render([
            {"start": {"focused": True, "clock": 0}}, {"clock": 6000}, {"pagehide": True},
            {"snapshot": True},
        ])
        self.assertEqual(snap["posts"], [LOOK])

    def test_hiding_the_page_ends_a_hold(self) -> None:
        hidden, blurred = render([
            {"start": {"focused": False, "clock": 0}}, {"focus": True}, {"clock": 6000},
            {"hide": True}, {"snapshot": True}, {"blur": True}, {"snapshot": True},
        ])
        self.assertEqual(hidden["posts"], [LOOK])
        self.assertEqual(blurred["posts"], [LOOK])

ANSWERABLE = item("A", questions=[
    {"question": "Which host?", "options": ["one", "two"], "chosen": None,
     "recommended": "two"}])
OTHER = item("B", held_work=5, questions=[
    {"question": "Which port?", "options": ["80", "8080"], "chosen": None,
     "recommended": None}])
START = {"start": {"focused": False, "clock": 0}}
WAIT_TEXT = "Sending in five seconds."
SENT_TEXT = "Answered, waiting for the agent to pick it up"


def frame(open_items: list, answered: list = ()) -> dict:
    return {
        "statement": {"inbox_items": len(open_items), "headline": "h", "sentence": "s",
                      "stale": False},
        "inbox": {"open": list(open_items), "answered": list(answered)},
        "project_count": 0, "entries": [], "unmanaged": [],
    }


def full(n: dict) -> str:
    return "".join([n["text"], *(full(c) for c in n["children"])])


def has_class(n: dict, name: str) -> bool:
    return name in n["cls"].split()


def picked(snap: dict) -> list:
    return [full(n) for n in nodes(snap["inbox"]) if has_class(n, "picked")]


def answers(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/answer"]


def count(snap: dict, name: str) -> int:
    return sum(1 for n in nodes(snap["inbox"]) if has_class(n, name))


def posted(post: dict) -> dict:
    return json.loads(post["body"])


class PageAnswerTest(unittest.TestCase):
    def test_the_lead_item_opens_with_its_recommended_option_selected(self) -> None:
        (snap,) = render([START, {"frame": frame([ANSWERABLE])}, {"snapshot": True}])
        self.assertEqual(len(picked(snap)), 1)
        self.assertTrue(picked(snap)[0].endswith("two"))

    def test_without_a_recommendation_enter_sends_nothing(self) -> None:
        bare = item("A", questions=[{**ANSWERABLE["questions"][0], "recommended": None}])
        (snap,) = render([
            START, {"frame": frame([bare])}, {"key": "Enter"}, {"clock": 20000},
            {"snapshot": True},
        ])
        self.assertEqual(picked(snap), [])
        self.assertEqual(answers(snap), [])

    def test_a_number_key_chooses_and_enter_sends_after_five_seconds(self) -> None:
        early, late = render([
            START, {"frame": frame([ANSWERABLE])}, {"key": "1"}, {"key": "Enter"},
            {"clock": 4999}, {"snapshot": True}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(answers(early), [])
        self.assertIn(WAIT_TEXT, full(early["inbox"]))
        self.assertIn("Undo", full(early["inbox"]))
        (post,) = answers(late)
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"],
                         {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
        self.assertNotIn("keepalive", post)
        self.assertEqual(posted(post),
                         {"project_id": "owner/p00", "key": "A", "choices": [0]})

    def test_undo_within_five_seconds_sends_nothing(self) -> None:
        for name, undo in (("escape", {"key": "Escape"}), ("button", {"click": "undo"})):
            with self.subTest(name):
                (snap,) = render([
                    START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"}, {"clock": 3000},
                    undo, {"clock": 20000}, {"snapshot": True},
                ])
                self.assertEqual(answers(snap), [])
                self.assertTrue(picked(snap)[0].endswith("two"))
                self.assertNotIn(WAIT_TEXT, full(snap["inbox"]))

    def test_a_refused_tick_reads_could_not_send_and_keeps_the_choice(self) -> None:
        refusal = "the tracker refused the tick: gh_failed: gh: Server Error (HTTP 502)"
        for name, reply, reason in (
            ("refused", [{"respond": {"status": 502, "text": refusal + "\n"}}], refusal),
            ("no answer", [{"fail_fetch": True}], "the console did not answer"),
        ):
            with self.subTest(name):
                first, second = render([
                    START, {"frame": frame([ANSWERABLE])}, *reply, {"key": "Enter"},
                    {"clock": 5000}, {"snapshot": True},
                    {"frame": frame([ANSWERABLE])}, {"snapshot": True},
                ])
                for snap in (first, second):
                    self.assertIn("Could not send: " + reason, full(snap["inbox"]))
                    (fail,) = [n for n in nodes(snap["inbox"]) if has_class(n, "fail")]
                    self.assertEqual(fail["text"], "Could not send: " + reason)
                    self.assertTrue(picked(snap)[0].endswith("two"))
                    lead = snap["inbox"]["children"][0]
                    self.assertEqual(lead["tag"], "article")
                    self.assertIn("Which host?", full(lead))

    def test_a_sent_answer_reads_answered_waiting_for_the_agent_to_pick_it_up(self) -> None:
        sent, moved = render([
            START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"}, {"clock": 5000},
            {"snapshot": True},
            {"frame": frame([], answered=[{**ANSWERABLE, "answered": True}])},
            {"snapshot": True},
        ])
        self.assertIn(SENT_TEXT, full(sent["inbox"]))
        head = next(n for n in nodes(moved["inbox"]) if has_class(n, "done-head"))
        self.assertEqual(head["text"], SENT_TEXT)

    def test_an_item_the_tracker_shows_open_again_after_a_send_is_answerable_again(self) -> None:
        reopened = {**ANSWERABLE, "questions": [{**ANSWERABLE["questions"][0], "recommended": None}]}
        sent, again, resent = render([
            START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"}, {"clock": 5000},
            {"snapshot": True}, {"frame": frame([reopened])}, {"snapshot": True},
            {"key": "1"}, {"key": "Enter"}, {"clock": 10000}, {"snapshot": True},
        ])
        self.assertIn(SENT_TEXT, full(sent["inbox"]))
        self.assertNotIn(SENT_TEXT, full(again["inbox"]))
        self.assertEqual(picked(again), [])
        self.assertEqual(count(again, "send"), 1)
        self.assertEqual([posted(p)["choices"] for p in answers(resent)], [[1], [0]])

    def test_an_item_that_leaves_while_waiting_is_never_sent(self) -> None:
        (snap,) = render([
            START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"}, {"clock": 2000},
            {"frame": frame([])}, {"clock": 10000}, {"snapshot": True},
        ])
        self.assertEqual(answers(snap), [])

    def test_keys_with_a_modifier_or_on_an_item_without_boxes_do_nothing(self) -> None:
        bare = item("A", questions=[{**ANSWERABLE["questions"][0], "recommended": None}])
        (snap,) = render([
            START, {"frame": frame([bare])}, {"key": "1", "ctrlKey": True},
            {"key": "1", "altKey": True}, {"key": "1", "metaKey": True}, {"snapshot": True},
        ])
        self.assertEqual(picked(snap), [])
        conflict = item("K", reason="conflict", items=["Rebase onto main."])
        (snap,) = render([
            START, {"frame": frame([conflict])}, {"key": "1"}, {"key": "Enter"},
            {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(answers(snap), [])
        self.assertEqual(count(snap, "opt"), 0)

    def test_number_keys_move_through_the_questions(self) -> None:
        two = item("A", questions=[
            {"question": "Which database?", "options": ["sqlite", "postgres"],
             "chosen": None, "recommended": None},
            {"question": "Which port?", "options": ["80", "8080"],
             "chosen": None, "recommended": None}])
        (snap,) = render([
            START, {"frame": frame([two])}, {"key": "2"}, {"key": "1"}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True},
        ])
        (post,) = answers(snap)
        self.assertEqual(posted(post)["choices"], [1, 0])

    def test_a_decision_behind_a_conflict_takes_the_keys(self) -> None:
        conflict = item("K", reason="conflict", items=["Rebase onto main."],
                        waiting_since="2026-11-10T07:00:00+00:00")
        first, last = render([
            START, {"frame": frame([conflict, ANSWERABLE])}, {"snapshot": True},
            {"key": "1"}, {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(count(first, "opt"), 2)
        self.assertEqual(len(picked(first)), 1)
        self.assertTrue(picked(first)[0].endswith("two"))
        (post,) = answers(last)
        self.assertEqual(posted(post),
                         {"project_id": "owner/p00", "key": "A", "choices": [0]})

    def test_undo_stays_reachable_when_another_item_takes_the_lead(self) -> None:
        for name, undo in (("button", {"click": "undo"}), ("escape", {"key": "Escape"})):
            with self.subTest(name):
                moved, last = render([
                    START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"}, {"clock": 1000},
                    {"frame": frame([OTHER, ANSWERABLE])}, {"snapshot": True},
                    undo, {"clock": 20000}, {"snapshot": True},
                ])
                self.assertIn(WAIT_TEXT, full(moved["inbox"]))
                self.assertIn("Undo", full(moved["inbox"]))
                self.assertEqual(answers(last), [])
                self.assertTrue(picked(last)[0].endswith("two"))

    def test_a_failure_stays_visible_when_the_item_stops_leading(self) -> None:
        held = item("B", held_work=5, questions=[
            {"question": "Which port?", "options": ["80"], "chosen": None,
             "recommended": None}])
        first, last = render([
            START, {"frame": frame([ANSWERABLE])},
            {"respond": {"status": 502, "text": "boom"}}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True},
            {"frame": frame([held, ANSWERABLE])}, {"snapshot": True},
        ])
        for snap in (first, last):
            self.assertIn("Could not send: boom", full(snap["inbox"]))
            self.assertEqual(count(snap, "fail"), 1)
        self.assertEqual(count(last, "send"), 2)

    def test_enter_and_digits_stay_with_a_focused_link_button_or_summary(self) -> None:
        for tag in ("A", "BUTTON", "SUMMARY"):
            with self.subTest(tag):
                (snap,) = render([
                    START, {"frame": frame([ANSWERABLE])}, {"key": "Enter", "target": tag},
                    {"key": "1", "target": tag}, {"clock": 5000}, {"snapshot": True},
                ])
                self.assertEqual(answers(snap), [])
                self.assertTrue(picked(snap)[0].endswith("two"))
                self.assertNotIn(WAIT_TEXT, full(snap["inbox"]))

    def test_while_one_answer_waits_the_keys_choose_for_the_next(self) -> None:
        first = item("A", questions=[{**ANSWERABLE["questions"][0], "recommended": None}])
        (snap,) = render([
            START, {"frame": frame([first, OTHER])}, {"key": "1"}, {"key": "Enter"},
            {"key": "2"}, {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
        ])
        one, two = answers(snap)
        self.assertEqual(posted(one),
                         {"project_id": "owner/p00", "key": "A", "choices": [0]})
        self.assertEqual(posted(two),
                         {"project_id": "owner/p00", "key": "B", "choices": [1]})


def moment(at: str, sentence: str) -> dict:
    return {"at": at, "kind": "session.hook", "sentence": sentence}


def with_digest(digest: dict | None) -> dict:
    frame = view([])
    if digest is not None:
        frame["digest"] = digest
    return frame


class PageDigestTest(unittest.TestCase):
    def test_the_digest_lists_newest_first_with_earlier_folded(self) -> None:
        frame = with_digest({
            "since": "2026-11-11T08:00:00+00:00", "first_visit": False,
            "recent": [moment("2026-11-11T09:30:00+00:00", "Newest."),
                       moment("2026-11-11T09:00:00+00:00", "Second.")],
            "earlier": [moment("2026-11-11T08:30:00+00:00", "Third.")],
            "omitted": 2,
        })
        (snap,) = render([{"frame": frame}, {"snapshot": True}])
        digest = snap["digest"]
        head = next(n for n in nodes(digest) if n["cls"] == "digest-head")
        self.assertTrue(head["text"].startswith("Since you last looked, "))
        (lines,) = [n for n in nodes(digest) if n["tag"] == "ul" and n["cls"] == "digest"]
        shown = [text(n) for n in lines["children"]]
        self.assertEqual(len(shown), 2)
        self.assertIn("Newest.", shown[0])
        self.assertIn("Second.", shown[1])
        (fold,) = [n for n in nodes(digest) if n["tag"] == "details"]
        self.assertEqual(fold["key"], "earlier")
        self.assertFalse(fold["open"])
        summary = next(n for n in nodes(fold) if n["tag"] == "summary")
        self.assertIn("Earlier", text(summary))
        self.assertIn("3", text(summary))
        self.assertIn("Third.", text(fold))
        self.assertIn("and 2 more", text(fold))

    def test_a_first_visit_says_the_last_eight_hours(self) -> None:
        frame = with_digest({
            "since": None, "first_visit": True,
            "recent": [moment("2026-11-11T09:30:00+00:00", "Newest.")],
            "earlier": [], "omitted": 0,
        })
        (snap,) = render([{"frame": frame}, {"snapshot": True}])
        head = next(n for n in nodes(snap["digest"]) if n["cls"] == "digest-head")
        self.assertEqual(text(head).strip(), "In the last eight hours")

    def test_an_empty_digest_says_nothing_changed(self) -> None:
        frame = with_digest({
            "since": "2026-11-11T08:00:00+00:00", "first_visit": False,
            "recent": [], "earlier": [], "omitted": 0,
        })
        (snap,) = render([{"frame": frame}, {"snapshot": True}])
        self.assertIn("Nothing changed.", text(snap["digest"]))

    def test_a_view_without_a_digest_leaves_the_section_empty(self) -> None:
        for frame in (with_digest(None), {**with_digest(None), "digest": None}):
            with self.subTest(null="digest" in frame):
                (snap,) = render([{"frame": frame}, {"snapshot": True}])
                self.assertEqual(snap["digest"]["children"], [])

    def test_an_open_earlier_fold_survives_a_new_frame(self) -> None:
        frame = with_digest({
            "since": "2026-11-11T08:00:00+00:00", "first_visit": False,
            "recent": [moment("2026-11-11T09:30:00+00:00", "Newest.")],
            "earlier": [moment("2026-11-11T08:30:00+00:00", "Third.")], "omitted": 0,
        })
        (snap,) = render([
            {"frame": frame}, {"open": "earlier"}, {"frame": frame}, {"snapshot": True},
        ])
        (fold,) = [n for n in nodes(snap["digest"]) if n["tag"] == "details"]
        self.assertTrue(fold["open"])


GOAL_FRAME = {**view([]), "recent_projects": ["owner/zeta", "owner/alpha", "owner/beta"]}
GOAL_TEXT = "make the importer resumable"
GOAL_HEADERS = {"X-Console-Token": TOKEN, "Content-Type": "application/json"}
SPRINT = {
    "type": "sprint", "sprint_id": "a" * 16, "goal": GOAL_TEXT, "state": "drafting",
    "state_text": "drafting the brief", "stated_at": "2026-11-12T10:00:00+00:00",
    "age_text": "stated 3 min ago", "manager_text": "no manager has picked this up",
}


def goal_named(snap: dict, cls: str) -> list:
    return [n for n in nodes(snap["goal"]) if has_class(n, cls)]


def goal_names(snap: dict) -> list:
    return [full(n) for n in goal_named(snap, "goal-project")]


def goal_picked(snap: dict) -> list:
    return [full(n) for n in goal_named(snap, "goal-project") if has_class(n, "picked")]


def box_open(snap: dict) -> bool:
    return goal_named(snap, "goal-box") != []


def goals(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/goal"]


def goal_fail(snap: dict) -> list:
    return [full(n) for n in goal_named(snap, "fail")]


def with_sprints(sprints: list) -> dict:
    return view([{**project(0, []), "sprints": sprints}])


def sprint_lines(snap: dict) -> list:
    return [n for n in nodes(snap["projects"]) if n["tag"] == "li" and has_class(n, "sprint")]


class PageGoalTest(unittest.TestCase):
    def test_g_opens_the_goal_field_and_filters_projects_most_recent_first(self) -> None:
        closed, opened, upper, one = render([
            START, {"frame": GOAL_FRAME}, {"snapshot": True}, {"key": "g"}, {"snapshot": True},
            {"input": {"cls": "goal-filter", "value": "TA"}}, {"snapshot": True},
            {"input": {"cls": "goal-filter", "value": "alpha"}}, {"snapshot": True},
        ])
        self.assertFalse(box_open(closed))
        self.assertEqual([full(n) for n in goal_named(closed, "goal-open")], ["State a goal"])
        self.assertTrue(box_open(opened))
        self.assertEqual(goal_named(opened, "goal-open"), [])
        self.assertEqual(goal_names(opened), ["owner/zeta", "owner/alpha", "owner/beta"])
        self.assertEqual(goal_picked(opened), ["owner/zeta"])
        self.assertEqual(opened["active"], "goal-filter")
        self.assertIs(opened["key_prevented"], True)
        (filter_node,) = goal_named(opened, "goal-filter")
        self.assertIn(filter_node["value"], ("", None))
        self.assertEqual(goal_names(upper), ["owner/zeta", "owner/beta"])
        self.assertEqual(goal_names(one), ["owner/alpha"])
        self.assertEqual(goal_picked(one), ["owner/alpha"])

    def test_the_goal_field_opens_from_a_visible_button(self) -> None:
        opened, closed = render([
            START, {"frame": GOAL_FRAME}, {"click": "goal-open"}, {"snapshot": True},
            {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertTrue(box_open(opened))
        self.assertEqual(goal_names(opened), ["owner/zeta", "owner/alpha", "owner/beta"])
        self.assertEqual(opened["active"], "goal-filter")
        self.assertEqual(goal_named(opened, "goal-open"), [])
        self.assertFalse(box_open(closed))
        self.assertEqual(len(goal_named(closed, "goal-open")), 1)

    def test_a_sent_goal_posts_the_project_and_text_and_closes(self) -> None:
        (snap,) = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-filter", "value": "alpha"}},
            {"input": {"cls": "goal-text", "value": GOAL_TEXT}},
            {"click": "goal-send"}, {"snapshot": True},
        ])
        (post,) = goals(snap)
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]), {"project_id": "owner/alpha", "goal": GOAL_TEXT})
        self.assertFalse(box_open(snap))
        self.assertEqual(len(goal_named(snap, "goal-open")), 1)

    def test_a_refused_goal_keeps_its_text_and_says_why(self) -> None:
        for reply, reason in (
            ({"respond": {"status": 409, "text": "this project is not registered\n"}},
             "Could not send: this project is not registered"),
            ({"fail_fetch": True}, "Could not send: the console did not answer"),
        ):
            with self.subTest(reason=reason):
                (snap,) = render([
                    START, {"frame": GOAL_FRAME}, {"key": "g"},
                    {"input": {"cls": "goal-filter", "value": "alpha"}},
                    {"input": {"cls": "goal-text", "value": GOAL_TEXT}},
                    reply, {"click": "goal-send"}, {"snapshot": True},
                ])
                self.assertEqual(goal_fail(snap), [reason])
                (text_node,) = goal_named(snap, "goal-text")
                self.assertEqual(text_node["value"], GOAL_TEXT)
                self.assertEqual(goal_picked(snap), ["owner/alpha"])
                self.assertTrue(box_open(snap))

    def test_local_refusals_send_nothing(self) -> None:
        nothing, long = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-filter", "value": "nomatch"}},
            {"click": "goal-send"}, {"snapshot": True},
            {"input": {"cls": "goal-filter", "value": ""}},
            {"input": {"cls": "goal-text", "value": "x" * 2001}},
            {"click": "goal-send"}, {"snapshot": True},
        ])
        self.assertEqual(goal_fail(nothing), ["Could not send: choose a project"])
        self.assertEqual(
            goal_fail(long), ["Could not send: a goal is at most 2000 characters"]
        )
        self.assertEqual(goals(nothing), [])
        self.assertEqual(goals(long), [])

    def test_a_frame_keeps_the_typed_goal_and_its_focus(self) -> None:
        before, after = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"}, {"focus_on": "goal-text"},
            {"input": {"cls": "goal-text", "value": "half a thought"}}, {"snapshot": True},
            {"frame": {**GOAL_FRAME, "recent_projects": ["owner/new", "owner/zeta"]}},
            {"snapshot": True},
        ])
        self.assertEqual(before["active"], "goal-text")
        self.assertEqual(after["active"], "goal-text")
        self.assertEqual(after["focus_count"], before["focus_count"])
        (text_node,) = goal_named(after, "goal-text")
        self.assertEqual(text_node["value"], "half a thought")
        self.assertEqual(goal_names(after), ["owner/new", "owner/zeta"])

    def test_keys_typed_in_the_goal_field_stay_there(self) -> None:
        stay, snap = render([
            START, {"frame": {**frame([ANSWERABLE]), "recent_projects": ["owner/alpha"]}},
            {"key": "g", "target": "INPUT"}, {"snapshot": True},
            {"key": "g"}, {"key": "1", "target": "TEXTAREA"},
            {"key": "Enter", "target": "TEXTAREA"}, {"clock": 6000}, {"snapshot": True},
        ])
        self.assertFalse(box_open(stay))
        self.assertIs(stay["key_prevented"], False)
        self.assertEqual(answers(snap), [])
        self.assertTrue(picked(snap)[-1].endswith("two"))

    def test_escape_closes_the_goal_field_and_keeps_the_draft(self) -> None:
        closed, reopened = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "draft"}}, {"key": "Escape"},
            {"snapshot": True}, {"key": "g"}, {"snapshot": True},
        ])
        self.assertFalse(box_open(closed))
        (text_node,) = goal_named(reopened, "goal-text")
        self.assertEqual(text_node["value"], "draft")

    def test_a_sprint_line_reads_its_goal_state_age_and_the_honest_line(self) -> None:
        (snap, bare) = render([
            START, {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"frame": with_sprints([{**SPRINT, "manager_text": None}])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        for expected in (GOAL_TEXT, "drafting the brief", "stated 3 min ago",
                         "no manager has picked this up"):
            self.assertIn(expected, full(line))
        self.assertEqual(
            len([n for n in nodes(line) if n["tag"] == "button" and has_class(n, "withdraw")]), 1
        )
        (bare_line,) = sprint_lines(bare)
        self.assertEqual([n for n in nodes(bare_line) if has_class(n, "manager")], [])

    def test_withdraw_posts_the_sprint_and_a_refusal_says_why(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([SPRINT])},
            {"respond": {"status": 409, "text": "this sprint is not open\n"}},
            {"click": "withdraw"}, {"snapshot": True},
        ])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/withdraw"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(
            json.loads(post["body"]), {"project_id": "owner/p00", "sprint_id": "a" * 16}
        )
        (line,) = sprint_lines(snap)
        self.assertEqual(
            [full(n) for n in nodes(line) if has_class(n, "fail")],
            ["Could not withdraw: this sprint is not open"],
        )


class PageInFlightTest(unittest.TestCase):
    def test_a_goal_edited_while_sending_survives_the_answer(self) -> None:
        (snap,) = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-filter", "value": "alpha"}},
            {"input": {"cls": "goal-text", "value": GOAL_TEXT}},
            {"hold": True}, {"click": "goal-send"},
            {"input": {"cls": "goal-text", "value": GOAL_TEXT + " and then verifiable"}},
            {"release": {"status": 204}}, {"snapshot": True},
        ])
        self.assertTrue(box_open(snap))
        (text_node,) = goal_named(snap, "goal-text")
        self.assertEqual(text_node["value"], GOAL_TEXT + " and then verifiable")
        self.assertEqual(goal_fail(snap), [])

    def test_a_goal_reopened_and_edited_while_sending_survives_the_answer(self) -> None:
        closed, snap = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": GOAL_TEXT}},
            {"hold": True}, {"click": "goal-send"}, {"key": "Escape"}, {"snapshot": True},
            {"key": "g"}, {"input": {"cls": "goal-text", "value": "a second thought"}},
            {"release": {"status": 204}}, {"snapshot": True},
        ])
        self.assertFalse(box_open(closed))
        self.assertTrue(box_open(snap))
        (text_node,) = goal_named(snap, "goal-text")
        self.assertEqual(text_node["value"], "a second thought")

    def test_a_withdrawal_failing_after_a_new_view_shows_on_the_visible_row(self) -> None:
        sending, failed = render([
            START, {"frame": with_sprints([SPRINT])}, {"hold": True}, {"click": "withdraw"},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"release": {"status": 409, "text": "this sprint is not open\n"}},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(sending)
        (button,) = [n for n in nodes(line) if has_class(n, "withdraw")]
        self.assertTrue(button["disabled"])
        (line,) = sprint_lines(failed)
        (button,) = [n for n in nodes(line) if has_class(n, "withdraw")]
        self.assertFalse(button["disabled"])
        self.assertEqual(
            [full(n) for n in nodes(line) if has_class(n, "fail")],
            ["Could not withdraw: this sprint is not open"],
        )


BRIEF = {
    "type": "inbox_item", "reason": "brief", "key": "brief/" + "a" * 16,
    "project_id": "owner/p01", "sprint_id": "a" * 16, "goal": GOAL_TEXT, "version": 2,
    "brief": {
        "done": "the importer resumes", "excluded": ["no new formats"],
        "slices": ["checkpoint", "resume"], "risks": ["partial writes"],
        "asks": ["which store?"],
    },
    "answered": False, "waiting_since": stamp(timedelta(minutes=3)),
}
BRIEF_V1 = {**BRIEF, "version": 1, "waiting_since": stamp(timedelta(minutes=9))}
BRIEF_B = {
    **BRIEF, "key": "brief/" + "b" * 16, "sprint_id": "b" * 16, "version": 1,
    "waiting_since": stamp(timedelta(minutes=8)),
}
APPROVING_TEXT = "Approving in five seconds."
APPROVED_TEXT = "Approved, the sprint is starting"
REPLIED_TEXT = "Reply sent, waiting for a new brief"
LABELS = ("What done looks like", "Excluded", "Slices", "Risks", "What I expect to ask")


def approvals(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/approve"]


def replies(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/reply"]


def brief_cards(snap: dict) -> list:
    return [n for n in nodes(snap["inbox"]) if has_class(n, "brief")]


def fails(snap: dict) -> list:
    return [full(n) for n in nodes(snap["inbox"]) if has_class(n, "fail")]


def reply_fields(snap: dict) -> list:
    return [n["value"] for n in nodes(snap["inbox"]) if has_class(n, "reply-text")]


class PageBriefTest(unittest.TestCase):
    def test_a_brief_opens_in_place_with_its_goal_above_and_its_version(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF, ANSWERABLE])}, {"snapshot": True},
        ])
        first = snap["inbox"]["children"][0]
        self.assertEqual(first["tag"], "article")
        self.assertTrue(has_class(first, "brief"))
        words = full(first)
        self.assertIn("owner/p01 brief, version 2", words)
        at = 0
        for needle in (GOAL_TEXT, LABELS[0], "the importer resumes", LABELS[1], "no new formats",
                       LABELS[2], "checkpoint", "resume", LABELS[3], "partial writes",
                       LABELS[4], "which store?"):
            found = words.find(needle, at)
            self.assertGreaterEqual(found, 0, needle)
            at = found + len(needle)
        self.assertIn("Which host?", full(snap["inbox"]))

    def test_enter_approves_after_five_seconds(self) -> None:
        early, late = render([
            START, {"frame": frame([BRIEF, ANSWERABLE])}, {"key": "Enter"}, {"clock": 4999},
            {"snapshot": True}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(approvals(early), [])
        self.assertIn(APPROVING_TEXT, full(early["inbox"]))
        (post,) = approvals(late)
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(posted(post), {
            "project_id": "owner/p01", "sprint_id": "a" * 16, "version": 2,
        })
        self.assertIn(APPROVED_TEXT, full(late["inbox"]))
        self.assertEqual(answers(late), [])

    def test_escape_or_undo_cancels_an_approval(self) -> None:
        for cancel in ({"key": "Escape"}, {"click": "undo"}):
            with self.subTest(cancel=cancel):
                (snap,) = render([
                    START, {"frame": frame([BRIEF])}, {"key": "Enter"}, {"clock": 3000},
                    cancel, {"clock": 20000}, {"snapshot": True},
                ])
                self.assertEqual(approvals(snap), [])

    def test_a_refused_approval_says_why_and_stays_approvable(self) -> None:
        refused, again = render([
            START, {"frame": frame([BRIEF])},
            {"respond": {"status": 409, "text": "a newer brief replaced this one\n"}},
            {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
            {"key": "Enter"}, {"clock": 10000}, {"snapshot": True},
        ])
        self.assertEqual(fails(refused), ["Could not send: a newer brief replaced this one"])
        self.assertEqual(len(approvals(refused)), 1)
        self.assertEqual(len(approvals(again)), 2)

    def test_a_newer_brief_during_the_undo_cancels_the_approval(self) -> None:
        mid, later, last = render([
            START, {"frame": frame([BRIEF_V1])}, {"key": "Enter"}, {"clock": 2000},
            {"frame": frame([BRIEF])}, {"clock": 5000}, {"snapshot": True},
            {"clock": 20000}, {"snapshot": True},
            {"key": "Enter"}, {"clock": 25000}, {"snapshot": True},
        ])
        note = "A newer brief replaced version 1; nothing was approved."
        for snap in (mid, later):
            self.assertEqual(approvals(snap), [])
            words = full(snap["inbox"])
            self.assertIn("owner/p01 brief, version 2", words)
            self.assertIn(note, words)
            self.assertEqual(count(snap, "approve"), 1)
        (post,) = approvals(last)
        self.assertEqual(posted(post), {
            "project_id": "owner/p01", "sprint_id": "a" * 16, "version": 2,
        })
        self.assertNotIn(note, full(last["inbox"]))

    def test_a_response_for_an_older_brief_never_marks_the_newer_one(self) -> None:
        for release in ({"status": 409, "text": "a newer brief replaced this one\n"},
                        {"status": 204}):
            with self.subTest(approve=release["status"]):
                held, done = render([
                    START, {"frame": frame([BRIEF_V1])}, {"key": "Enter"}, {"hold": True},
                    {"clock": 5000}, {"frame": frame([BRIEF])}, {"release": release},
                    {"snapshot": True}, {"key": "Enter"}, {"clock": 10000}, {"snapshot": True},
                ])
                (post,) = approvals(held)
                self.assertEqual(posted(post)["version"], 1)
                words = full(held["inbox"])
                for text in ("Could not send", APPROVED_TEXT, "Approving"):
                    self.assertNotIn(text, words)
                self.assertEqual(count(held, "approve"), 1)
                self.assertEqual([posted(p)["version"] for p in approvals(done)], [1, 2])
        (snap,) = render([
            START, {"frame": frame([BRIEF_V1])},
            {"input": {"cls": "reply-text", "value": "redo"}}, {"hold": True},
            {"click": "reply-send"}, {"frame": frame([BRIEF])},
            {"release": {"status": 204}}, {"snapshot": True},
        ])
        (post,) = replies(snap)
        self.assertEqual(posted(post)["version"], 1)
        self.assertNotIn(REPLIED_TEXT, full(snap["inbox"]))
        self.assertEqual(reply_fields(snap), ["redo"])

    def test_a_reply_cancels_a_pending_approval(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])}, {"key": "Enter"}, {"clock": 2000},
            {"input": {"cls": "reply-text", "value": "Drop slice 2"}}, {"hold": True},
            {"click": "reply-send"}, {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(approvals(snap), [])
        self.assertEqual(len(replies(snap)), 1)
        self.assertNotIn(APPROVING_TEXT, full(snap["inbox"]))

    def test_no_approval_starts_while_a_reply_is_sending(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])},
            {"input": {"cls": "reply-text", "value": "Drop slice 2"}}, {"hold": True},
            {"click": "reply-send"}, {"key": "Enter"}, {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(approvals(snap), [])
        self.assertEqual(len(replies(snap)), 1)
        self.assertNotIn(APPROVING_TEXT, full(snap["inbox"]))

    def test_no_reply_goes_out_while_an_approval_is_sending(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])}, {"key": "Enter"}, {"hold": True},
            {"clock": 5000},
            {"input": {"cls": "reply-text", "value": "Drop slice 2"}},
            {"click": "reply-send"}, {"snapshot": True},
        ])
        self.assertEqual(len(approvals(snap)), 1)
        self.assertEqual(replies(snap), [])
        self.assertEqual(reply_fields(snap), ["Drop slice 2"])

    def test_a_reply_posts_the_owners_exact_words(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])},
            {"input": {"cls": "reply-text", "value": "Drop slice 2.\nKeep the rest. "}},
            {"click": "reply-send"}, {"snapshot": True},
        ])
        (post,) = replies(snap)
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(posted(post), {
            "project_id": "owner/p01", "sprint_id": "a" * 16, "version": 2,
            "reply": "Drop slice 2.\nKeep the rest. ",
        })
        self.assertIn(REPLIED_TEXT, full(snap["inbox"]))

    def test_an_empty_reply_sends_nothing_and_says_why(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])},
            {"input": {"cls": "reply-text", "value": "  \n"}}, {"click": "reply-send"},
            {"snapshot": True},
        ])
        self.assertEqual(replies(snap), [])
        self.assertIn("Could not send: write the reply first", fails(snap))

    def test_a_typed_reply_keeps_its_focus_across_frames(self) -> None:
        before, after = render([
            START, {"frame": frame([BRIEF])}, {"focus_on": "reply-text"},
            {"input": {"cls": "reply-text", "value": "keep slice 1"}}, {"snapshot": True},
            {"frame": frame([BRIEF])}, {"frame": frame([BRIEF, ANSWERABLE])},
            {"frame": frame([{**BRIEF, "version": 3}])}, {"snapshot": True},
        ])
        for snap in (before, after):
            self.assertEqual(snap["active"], "reply-text")
            self.assertEqual(snap["field"], {
                "cls": "reply-text", "value": "keep slice 1", "start": 12, "end": 12,
            })
        self.assertEqual(after["focus_count"], before["focus_count"])

    def test_a_reply_field_keeps_focus_and_selection_when_its_card_moves(self) -> None:
        moved = {**BRIEF_B, "version": 2, "waiting_since": stamp(timedelta(minutes=1))}
        (snap,) = render([
            START, {"frame": frame([BRIEF_B, BRIEF])}, {"focus_on": "reply-text"},
            {"input": {"cls": "reply-text", "value": "abcdef"}},
            {"select": {"cls": "reply-text", "start": 2, "end": 4}},
            {"frame": frame([BRIEF, moved])}, {"snapshot": True},
        ])
        self.assertEqual(snap["active"], "reply-text")
        self.assertEqual(snap["field"], {
            "cls": "reply-text", "value": "abcdef", "start": 2, "end": 4,
        })
        first, second = brief_cards(snap)
        self.assertIn("owner/p01 brief, version 2", full(first))
        self.assertIn("owner/p01 brief, version 2", full(second))
        self.assertEqual(
            [n["value"] for n in nodes(second) if has_class(n, "reply-text")], ["abcdef"]
        )
        self.assertNotIn(
            "abcdef", [n["value"] for n in nodes(first) if has_class(n, "reply-text")]
        )

    def test_enter_in_the_reply_field_does_not_approve(self) -> None:
        (snap,) = render([
            START, {"frame": frame([BRIEF])}, {"key": "Enter", "target": "TEXTAREA"},
            {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(approvals(snap), [])

    def test_only_a_brief_offers_a_reply_field(self) -> None:
        plain, brief = render([
            START, {"frame": frame([ANSWERABLE])}, {"snapshot": True},
            {"frame": frame([BRIEF])}, {"snapshot": True},
        ])
        self.assertEqual([n for n in nodes(plain["inbox"]) if n["tag"] == "textarea"], [])
        (field,) = [n for n in nodes(brief["inbox"]) if n["tag"] == "textarea"]
        self.assertEqual(field["cls"], "reply-text")
