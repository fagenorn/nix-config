"""The desk page's static invariants: one self-contained file, no other origin."""

import gzip
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console import digest as console_digest
from agent_tools.console.event_log import Event
from agent_tools.console.sprints import MAX_REPORT_ISSUES

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"
HARNESS = REPO_ROOT / "tests/fixtures/console/page-harness.js"

INBOX_HARNESS = r"""
const ids = new Set(JSON.parse(process.argv[3]));
class Node {
  constructor(tag) {
    this.tagName = tag; this.className = ""; this.id = ""; this.href = "";
    this.rel = ""; this.open = false; this.children = []; this.dataset = {}; this.style = {};
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
    if (id.endsWith("-icon")) {
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
function setTimeout() { return 0; }
function clearTimeout() {}
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
            env={**os.environ, "TZ": "UTC"},
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
        "url": "/" + key.lower(), "reason": "decision", "headline": f"Question {key}?",
        "more_questions": 0, "answered_at": None,
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

    def test_the_page_has_a_narrow_rule_for_480_wide(self) -> None:
        style = self.text[self.text.index("<style>"):self.text.index("</style>")]
        blocks = []
        for found in re.finditer(r"@media \(max-width: (\d+)px\) \{", style):
            depth, at = 1, found.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(style[at], 0)
                at += 1
            blocks.append((int(found.group(1)), style[found.end():at - 1]))
        (narrow,) = [body for width, body in blocks if 480 <= width < 900]
        (top,) = re.findall(r"\.top-in \{([^}]*)\}", narrow)
        self.assertIn("flex-wrap: wrap", top)
        (statement,) = re.findall(r"\.statement h1 \{([^}]*)\}", narrow)
        (size,) = re.findall(r"font-size: ([\d.]+)rem", statement)
        self.assertLess(float(size), 2.375)

    def test_the_open_chooser_stays_inside_the_viewport_and_the_panel(self) -> None:
        # A long unbroken project id must wrap inside the 480px panel, and a long project list
        # must scroll inside a panel bounded to the viewport so Send and Cancel stay reachable.
        style = self.text[self.text.index("<style>"):self.text.index("</style>")]
        base = style_rules(style[:style.index("@media")])

        def rule(selector: str) -> dict:
            found = {}
            for s, d in base:
                if s == selector:
                    found.update(d)
            return found

        box = rule(".goal-box")
        self.assertRegex(box.get("max-height", ""), r"^calc\(100d?vh - [\d.]+rem\)$")
        self.assertEqual(box.get("overflow-y"), "auto")
        projects = rule(".goal-projects")
        self.assertEqual(projects.get("min-width"), "0")
        self.assertEqual(projects.get("max-width"), "100%")
        self.assertEqual(projects.get("overflow-y"), "auto")
        self.assertEqual(projects.get("flex"), "0 1 auto")
        self.assertEqual(projects.get("min-height"), "0")
        self.assertEqual(rule(".goal-projects li").get("min-width"), "0")
        self.assertEqual(rule(".goal-projects li").get("max-width"), "100%")
        for name in ("min-width", "max-width", "overflow-wrap"):
            with self.subTest(name=name):
                self.assertEqual(
                    rule(".goal-project").get(name), {"min-width": "0", "max-width": "100%", "overflow-wrap": "anywhere"}[name]
                )
        self.assertEqual(rule(".goal-filter").get("min-width"), "0")
        self.assertEqual(rule(".goal-act").get("flex"), "none")

    def test_the_top_bar_fits_480_wide(self) -> None:
        style = self.text[self.text.index("<style>"):self.text.index("</style>")]
        base, at = "", 0
        for found in re.finditer(r"@media [^{]+\{", style):
            if found.start() < at:
                continue
            base += style[at:found.start()]
            depth, at = 1, found.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(style[at], 0)
                at += 1
        base += style[at:]
        phone = style_rules(media_block(style, "(max-width: 480px)"))
        narrow = style_rules(media_block(style, "(max-width: 900px)")) + phone
        rules = style_rules(base) + narrow
        self.assertTrue(any(s == ".top-in" and d.get("flex-wrap") == "wrap" for s, d in phone))
        self.assertTrue(any(s == ".goal-bar" and d.get("flex") == "1 0 100%" for s, d in narrow))
        self.assertTrue(any(
            s == ".goal-box" and d.get("width") == "min(600px, calc(100vw - 32px))"
            for s, d in style_rules(base)
        ))

        def fits(value: str) -> bool:
            if value in ("auto", "0") or value.endswith("%") or "100vw" in value:
                return True
            found = re.fullmatch(r"([\d.]+)(px|rem)", value)
            return bool(found) and float(found.group(1)) * (16 if found.group(2) == "rem" else 1) <= 448

        for selector, decls in rules:
            if not selector.split()[0].startswith((".top", ".brand", ".conn", ".goal-", "#goal", ".cap", ".meter")):
                continue
            values = [decls[n] for n in ("width", "min-width", "flex-basis") if n in decls]
            parts = decls.get("flex", "").split()
            if len(parts) == 3:
                values.append(parts[2])
            for value in values:
                self.assertTrue(fits(value), selector + " sets " + value)

        name = [d for s, d in style_rules(base) if s == ".cap-acct b"]
        self.assertEqual(len(name), 1)
        self.assertEqual(name[0].get("overflow"), "hidden")
        self.assertEqual(name[0].get("text-overflow"), "ellipsis")
        self.assertEqual(name[0].get("white-space"), "nowrap")
        cut = re.fullmatch(r"([\d.]+)(px|rem)", name[0].get("max-width", ""))
        self.assertTrue(cut)
        self.assertLessEqual(float(cut.group(1)) * (16 if cut.group(2) == "rem" else 1), 160)
        (cap,) = [d for s, d in style_rules(base) if s == ".cap"]
        self.assertEqual(cap.get("min-width"), "0")
        self.assertEqual(cap.get("max-width"), "100%")
        (acct,) = [d for s, d in style_rules(base) if s == ".cap-acct"]
        self.assertEqual(acct.get("max-width"), "100%")
        unwrapped = {
            selector for selector, decls in style_rules(base)
            if selector.split()[0].startswith((".top", ".brand", ".conn", ".goal-", "#goal", ".cap", ".meter"))
            and decls.get("white-space") == "nowrap"
        }
        self.assertEqual(unwrapped, {".brand", ".cap-acct", ".cap-acct b"})
        (long_name,) = render([
            START,
            {"frame": {**view([]), "capacity": capacity([profile("a" * 60, "ok", week_left=50)])}},
            {"snapshot": True},
        ])
        (label,) = [n for n in nodes(long_name["capacity"]) if n["tag"] == "b"]
        self.assertEqual(label["title"], "a" * 60)

    def test_the_page_formats_no_time_with_the_locale(self) -> None:
        self.assertNotIn("toLocale", self.text)

    def test_the_page_requests_only_the_console_endpoints(self) -> None:
        literals = re.findall(
            r"\b(?:fetch|EventSource)\(\s*([\"'])([^\"']*)\1", self.text
        )
        self.assertEqual(
            {p for _, p in literals},
            {"/api/stream", "/api/looked", "/api/answer", "/api/check-answer", "/api/goal",
             "/api/withdraw", "/api/retry-manager", "/api/approve", "/api/reply",
             "/api/message"},
        )
        self.assertEqual(
            len(re.findall(r"\b(?:fetch|EventSource)\(", self.text)), len(literals)
        )

    def test_the_page_takes_its_view_only_from_the_stream(self) -> None:
        # A separate snapshot request can answer after a newer streamed frame
        # and render over it; the stream's first frame is already the snapshot.
        self.assertEqual(len(re.findall(r"\bfetch\(", self.text)), 9)
        self.assertIsNotNone(
            re.search(r'fetch\("/api/looked",\s*\{\s*method:\s*"POST"', self.text)
        )
        self.assertIsNotNone(
            re.search(r'fetch\("/api/answer",\s*\{\s*method:\s*"POST"', self.text)
        )
        self.assertIsNotNone(
            re.search(r'fetch\("/api/check-answer",\s*\{\s*method:\s*"POST"', self.text)
        )
        for route in ("/api/goal", "/api/withdraw", "/api/retry-manager", "/api/approve",
                      "/api/reply", "/api/message"):
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
                    item("Y", reason="conflict", headline="The branch conflicts",
                         items=["Merge conflict in flake.lock"], held_work=1, stale=True,
                         read_at="2026-11-10T09:00:00+00:00"),
                ],
                "answered": [item("Z", answered=True, headline="Already answered?")],
            },
        }
        result = render_page(view)
        self.assertIsNotNone(result["inbox"])
        h1 = next(n for n in walk(result["statement"]) if n["tag"] == "h1")
        self.assertEqual((h1["text"], h1["cls"]), ("2 things need you", "needs"))
        text = result["inbox"]["text"]
        for expected in ("Question X?", "Which database?", "Which port?",
                         "chosen: postgres", "holds 3 issues", "waiting ",
                         "The branch conflicts", "Merge conflict in flake.lock",
                         "Already answered?", "waiting for the agent"):
            self.assertIn(expected, text)
        self.assertEqual(len([n for n in walk(result["inbox"]) if n["cls"] == "read-at"]), 1)
        links = [(n["text"], n["href"], n["rel"])
                 for n in walk(result["inbox"]) if n["tag"] == "a"]
        self.assertEqual(links, [("Answer on the tracker", f"/{k}", "noreferrer")
                                 for k in "xyz"])

    def test_later_rows_keep_their_questions_and_project(self) -> None:
        view = {
            "project_count": 0, "entries": [], "unmanaged": [],
            "statement": {"inbox_items": 3, "headline": "3 things need you",
                          "sentence": "s", "stale": False},
            "inbox": {
                "open": [
                    item("A", issue=11, headline="Decisions are needed."),
                    item("B", issue=22, headline="Which cache?", questions=[
                        {"question": "Which cache?", "options": ["redis", "memcached"],
                         "chosen": "redis"}]),
                    item("C", issue=33, headline="Which queue?", questions=[
                        {"question": "Which queue?", "options": ["sqs", "nats"],
                         "chosen": None}]),
                ],
                "answered": [],
            },
        }
        rows = next(n for n in walk(render_page(view)["inbox"]) if n["cls"] == "rest")
        first, second = rows["children"]
        self.assertIn("owner/p00", first["text"])
        self.assertIn("Which cache?", first["text"])
        self.assertIn("chosen: redis", first["text"])
        self.assertIn("owner/p00", second["text"])
        self.assertIn("Which queue?", second["text"])
        self.assertIn("nats", second["text"])
        for row in (first, second):
            self.assertNotIn("#22", row["text"])
            self.assertNotIn("#33", row["text"])

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
        self.assertEqual([n["cls"] for n in walk(stale) if n["cls"] == "read-at"], ["read-at"])
        self.assertEqual([n for n in walk(fresh) if n["cls"] == "read-at"], [])

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
        self.assertNotIn("waiting for the agent", result["inbox"]["text"])
        h1 = next(n for n in walk(result["statement"]) if n["tag"] == "h1")
        self.assertEqual(h1["cls"], "")

    def test_only_a_note_and_a_typed_confirmation_are_typed(self) -> None:
        self.assertEqual(self.text.count('createElement("input")'), 1)
        self.assertEqual(self.text.count('createElement("textarea")'), 1)
        for needle in ("<textarea", "contenteditable"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)
        (snap,) = render([START, {"frame": frame([ANSWERABLE])}, {"snapshot": True}])
        self.assertEqual(
            [n for n in nodes(snap["inbox"]) if n["tag"] in ("input", "textarea")], [])

    def test_the_lead_headline_is_the_largest_type_after_the_statement(self) -> None:
        sizes = {}
        for body in re.findall(r"(?s)<style>(.*?)</style>", self.text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            for selectors, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                selector = " ".join(selectors.split())
                for decl in rule.split(";"):
                    name, _, value = decl.partition(":")
                    name, value = name.strip(), value.strip()
                    if name == "font-size":
                        size = re.fullmatch(r"([\d.]+)rem", value)
                    elif name == "font":
                        size = re.search(r"(?:^|\s)([\d.]+)rem(?:/|\s)", value)
                    else:
                        continue
                    if size:
                        sizes.setdefault(selector, []).append(float(size.group(1)))
        self.assertEqual(sizes.get(".card .q"), [1.5])
        for selector, found in sizes.items():
            if ".statement h1" in selector or selector == ".card .q":
                continue
            for size in found:
                self.assertLess(size, 1.5, selector)

    def test_the_tracker_links_are_the_only_hrefs(self) -> None:
        self.assertEqual(len(re.findall(r"\.href\s*=", self.text)), 2)
        self.assertEqual(self.text.count("a.href = item.url;"), 1)
        self.assertEqual(self.text.count("link.href = sprint.tracker_url;"), 1)
        self.assertIn('sprint.tracker_url.startsWith("https:")', self.text)


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
        env={**os.environ, "TZ": "UTC"},
    )
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def nodes(tree: dict) -> list:
    flat = [tree]
    for child in tree["children"]:
        flat += nodes(child)
    return flat


BOILER = "Delivery waits for the owner's choice: tick exactly one box under each question."


def visible(tree: dict) -> list:
    """The node and its descendants, skipping the body of a closed `details` (its `summary` stays)."""
    flat = [tree]
    for child in tree["children"]:
        if tree["tag"] == "details" and not tree["open"] and child["tag"] != "summary":
            continue
        flat += visible(child)
    return flat


def visible_text(tree: dict) -> str:
    return " ".join(n["text"] for n in visible(tree))


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
    "summary": "2 issues in delivery: 1 building, 1 plan review, moved 3 min ago",
    "moved_at": "2026-11-11T11:57:00+00:00",
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
        (snap,) = render([{"frame": frame}, {"open": "line:owner/p00"},
                          {"open": "line:/srv/elsewhere"}, {"snapshot": True}])
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
        (snap,) = render([{"start": {"focused": False, "clock": NOW_MS}},
                          {"frame": view([entry])}, {"open": "line:owner/p00"},
                          {"snapshot": True}])
        (runs,) = [n for n in nodes(snap["projects"]) if "runs" in n["cls"].split()]
        (run,) = [n for n in nodes(snap["projects"]) if "run" in n["cls"].split()]
        self.assertEqual(
            [full(c) for c in run["children"]],
            ["#856", "building task 3 of 5", "#857", "plan review", "moved 3 min ago"],
        )
        (moved,) = [n for n in nodes(run) if "moved" in n["cls"].split()]
        self.assertNotIn("quiet", moved["cls"].split())
        self.assertEqual([c["cls"] for c in run["children"]][:2], ["issue", "stage"])
        self.assertEqual([c["children"] for c in runs["children"]][0], run["children"])

    def test_a_quiet_run_says_quiet_and_never_stalled(self) -> None:
        quiet = dict(RUN, quiet=True, moved_text="quiet for 22 min",
                     moved_at="2026-11-11T11:38:00+00:00")
        entry = project(0, [session("s1", "working", "working", deliveries=[quiet])])
        (snap,) = render([{"start": {"focused": False, "clock": NOW_MS}},
                          {"frame": view([entry])}, {"open": "line:owner/p00"},
                          {"snapshot": True}])
        (moved,) = [
            n
            for n in nodes(snap["projects"])
            if {"moved", "quiet"} <= set(n["cls"].split())
        ]
        self.assertEqual(full(moved), "quiet for 22 min")
        self.assertNotIn("stalled", text(snap["projects"]).lower())

    def test_a_session_without_deliveries_renders_no_runs(self) -> None:
        entry = project(0, [session("e1", "idle", "idle", deliveries=[]),
                            session("m1", "working", "working")])
        (snap,) = render([{"frame": view([entry])}, {"open": "line:owner/p00"},
                          {"snapshot": True}])
        self.assertEqual(
            [n for n in nodes(snap["projects"]) if "runs" in n["cls"].split()], []
        )
        shown = text(snap["projects"])
        for wanted in ("e1", "idle", "m1", "working"):
            self.assertIn(wanted, shown)

    def test_a_project_without_sessions_still_opens_to_its_root(self) -> None:
        closed, opened = render([{"frame": view([project(0, [])])}, {"snapshot": True},
                                 {"open": "line:owner/p00"}, {"snapshot": True}])
        (fold,) = [n for n in nodes(closed["projects"]) if n["key"] == "line:owner/p00"]
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual([n["text"] for n in visible(summary) if n["text"]], ["owner/p00"])
        self.assertNotIn("/srv/p00", visible_text(closed["projects"]))
        self.assertIn("/srv/p00", visible_text(opened["projects"]))
        self.assertEqual(closed["unmanaged"]["children"], [])

    def test_an_empty_fleet_still_shows_unmanaged_repositories(self) -> None:
        frame = view([], [unmanaged_entry([session("i1", "idle", "idle")])], count=0)
        (snap,) = render([{"frame": frame}, {"open": "line:/srv/elsewhere"}, {"snapshot": True}])
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
            {"open": "line:owner/p00"},
            {"open": "quiet"},
            {"frame": frame("idle")},
            {"snapshot": True},
        ])
        by_key = {n["key"]: n for n in nodes(snap["projects"]) if n["key"]}
        self.assertTrue(by_key["line:owner/p00"]["open"])
        self.assertTrue(by_key["quiet"]["open"])
        self.assertFalse(by_key["line:owner/p01"]["open"])
        self.assertIn("idle", text(by_key["line:owner/p00"]))

    def test_a_quiet_line_says_how_long_it_is_untouched(self) -> None:
        ages = [timedelta(days=3, hours=1), timedelta(days=1, hours=1), timedelta(hours=2)]
        entries = [project(n, [], quiet=True, ago=age) for n, age in enumerate(ages)]
        (snap,) = render([{"frame": view(entries)}, {"snapshot": True}])
        lines = {}
        for n in nodes(snap["projects"]):
            if "line" in n["cls"].split():
                lines[full(n)] = n
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


def strip(snap: dict) -> list:
    return snap["capacity"]["children"]


def bars(n: dict) -> list:
    return [m for m in nodes(n) if m["tag"] == "i"]


def bar(n: dict) -> str:
    (i,) = bars(n)
    return i["width"]


def capacity_snap(cap: dict) -> dict:
    (snap,) = render([START, {"frame": {**view([]), "capacity": cap}}, {"snapshot": True}])
    return snap


def accounts(snap: dict) -> list:
    return [n for n in strip(snap) if has_class(n, "cap-acct")]


def part(snap: dict, name: str) -> dict:
    (found,) = [n for n in strip(snap) if has_class(n, name)]
    return found


class CapacityPageTest(unittest.TestCase):
    def test_fine_reads_one_word_then_each_account_with_a_bar_and_the_next_reset(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "ok", week_left=65, five_hour_left=40, next_reset="2026-11-16T05:00:00+00:00"),
            profile("b", "unknown"),
            profile("c", "ok", week_left=30, next_reset="2026-11-17T05:00:00+00:00"),
        ], no_reading="1 with no reading yet"))
        self.assertEqual(
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-fine", "cap-acct", "cap-acct", "cap-when", "cap-none"])
        state = strip(snap)[0]
        self.assertEqual(full(state), "fine")
        self.assertIn("svg", [c["tag"] for c in state["children"]])
        a, c = accounts(snap)
        labels = [n for n in nodes(snap["capacity"]) if n["tag"] == "b"]
        self.assertEqual([n["text"] for n in labels], ["a", "c"])
        for n in labels:
            self.assertEqual(n["title"], n["text"])
        self.assertEqual(bar(a), "65%")
        self.assertEqual(bar(c), "30%")
        (pc,) = [n for n in nodes(a) if has_class(n, "cap-pc")]
        self.assertEqual(full(pc), "65%")
        self.assertEqual(a["title"], "65% of the week left, 40% of 5 hours")
        self.assertEqual(c["title"], "30% of the week left")
        self.assertEqual(full(part(snap, "cap-when")), "resets Mon 05:00")
        self.assertEqual(full(part(snap, "cap-none")), "1 with no reading yet")

    def test_tight_reads_tight_and_an_out_account_reads_out_until(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "ok", week_left=12, next_reset="2026-11-16T05:00:00+00:00"),
            profile("b", "out", week_left=55, five_hour_left=0,
                    out_until="2026-11-13T09:30:00+00:00", next_reset="2026-11-13T08:00:00+00:00"),
        ], tight=True))
        self.assertEqual(
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-tight", "cap-acct", "cap-acct cap-out", "cap-when"])
        state = strip(snap)[0]
        self.assertEqual(full(state), "tight")
        self.assertIn("svg", [c["tag"] for c in state["children"]])
        a, b = accounts(snap)
        self.assertEqual(bar(a), "12%")
        self.assertEqual(bar(b), "55%")
        self.assertEqual(b["title"], "55% of the week left, 0% of 5 hours")
        self.assertIn("out until Fri 09:30", full(b))
        self.assertEqual([n for n in nodes(b) if has_class(n, "cap-pc")], [])
        self.assertEqual(full(part(snap, "cap-when")), "resets Mon 05:00")

    def test_every_account_out_reads_out_in_red_and_when_work_resumes(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "out", week_left=0, out_until="2026-11-13T09:30:00+00:00"),
            profile("b", "out", out_until="2026-11-13T10:00:00+00:00"),
        ], all_out=True, resumes_at="2026-11-13T09:30:00+00:00"))
        self.assertEqual(
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-out", "cap-acct cap-out", "cap-acct cap-out", "cap-when"])
        state = strip(snap)[0]
        self.assertEqual(full(state), "out")
        self.assertIn("svg", [c["tag"] for c in state["children"]])
        a, b = accounts(snap)
        self.assertEqual(bar(a), "0%")
        self.assertEqual(bars(b), [])
        self.assertEqual(full(part(snap, "cap-when")), "resumes Fri 09:30")
        self.assertNotIn("resets", full(snap["capacity"]))
        for n in nodes(snap["capacity"]):
            self.assertNotIn("needs", n["cls"])
        text = PAGE.read_text(encoding="utf-8")
        style = text[text.index("<style>"):text.index("</style>")]
        base, at = "", 0
        for found in re.finditer(r"@media [^{]+\{", style):
            if found.start() < at:
                continue
            base += style[at:found.start()]
            depth, at = 1, found.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(style[at], 0)
                at += 1
        base += style[at:]
        rules = style_rules(base)
        (out,) = [d for s, d in rules if s == ".cap-out"]
        self.assertEqual(out.get("color"), "var(--red)")
        for selector, decls in rules:
            if ".cap" in selector:
                self.assertNotIn("var(--peach)", " ".join(decls.values()), selector)

    def test_no_reading_at_all_shows_only_the_note(self) -> None:
        snap = capacity_snap(capacity(
            [profile("b", "unknown"), profile("c", "unknown")], no_reading="2 with no reading yet"))
        self.assertEqual([n["cls"] for n in strip(snap)], ["cap-none"])

    def test_a_reset_account_reads_reset_not_yet_used(self) -> None:
        snap = capacity_snap(capacity([
            profile("c", "reset"),
            profile("d", "reset", week_left=100, five_hour_left=100),
        ]))
        self.assertEqual(
            [n["cls"] for n in strip(snap)], ["cap-state cap-fine", "cap-acct", "cap-acct"])
        c, d = accounts(snap)
        self.assertIn("reset, not yet used", full(c))
        self.assertIn("reset, not yet used", full(d))
        self.assertEqual(bars(c), [])
        self.assertEqual(bar(d), "100%")
        self.assertNotIn("week unknown", full(c))
        self.assertEqual(d["title"], "100% of the week left, 100% of 5 hours")

    def test_profiles_without_a_reading_show_as_one_note(self) -> None:
        frame = {**view([]), "capacity": capacity(
            [profile("a", "ok", week_left=62), profile("b", "unknown"), profile("c", "unknown")],
            no_reading="2 with no reading yet")}
        (snap,) = render([START, {"frame": frame}, {"snapshot": True}])
        strip = snap["capacity"]
        self.assertEqual(full(strip).count("no reading yet"), 1)
        self.assertIn("2 with no reading yet", full(strip))
        self.assertEqual([n["text"] for n in nodes(strip) if n["tag"] == "b"], ["a"])

    def test_every_profile_out_is_promoted_above_the_inbox(self) -> None:
        out = [profile("a", "out", out_until="2026-11-12T09:00:00+00:00"),
               profile("b", "out", out_until="2026-11-12T10:00:00+00:00")]
        full = {**view([]), "capacity": capacity(
            out, all_out=True, resumes_at="2026-11-12T09:00:00+00:00")}
        result = render_page(full)
        self.assertIn("Capacity", result["promoted"]["text"])
        self.assertEqual(result["promoted"]["text"].count("out until"), 2)
        self.assertIn("Resumes ", result["statement"]["text"])
        html = PAGE.read_text(encoding="utf-8")
        self.assertLess(html.index('id="promoted"'), html.index('id="inbox"'))
        partial = {**view([]), "capacity": capacity(
            out, all_out=False, resumes_at="2026-11-12T09:00:00+00:00")}
        shown = render_page(partial)
        self.assertEqual(shown["promoted"]["children"], [])
        self.assertNotIn("Resumes ", shown["statement"]["text"])

    def test_unknown_values_read_as_words_not_null_or_1970(self) -> None:
        snap = capacity_snap(capacity([profile("a", "ok", five_hour_left=40), profile("b", "out")]))
        a, b = accounts(snap)
        self.assertEqual(bars(a), [])
        self.assertIn("week unknown", full(a))
        self.assertEqual(a["title"], "week unknown, 40% of 5 hours")
        self.assertIn("out, reset unknown", full(b))
        self.assertEqual(bars(b), [])
        self.assertEqual([n for n in strip(snap) if has_class(n, "cap-when")], [])
        text = full(snap["capacity"])
        for banned in ("null", "1970", "resets "):
            self.assertNotIn(banned, text)
        out = [profile("a", "out"), profile("b", "out")]
        both = capacity_snap(capacity(out, all_out=True))
        self.assertEqual([n for n in strip(both) if has_class(n, "cap-when")], [])
        self.assertEqual(full(both["promoted"]).count("out, reset unknown"), 2)
        self.assertNotIn("Resumes ", full(both["statement"]))

    def test_a_view_without_capacity_still_renders(self) -> None:
        result = render_page(view([]))
        self.assertEqual(result["capacity"]["children"], [])
        self.assertEqual(result["promoted"]["children"], [])


NOW_MS = 1794398400000
RAW_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}:\d{2}|\d{1,2}/\d{1,2}/\d{4}")


def utc(offset_ms: int) -> str:
    return datetime.fromtimestamp((NOW_MS - offset_ms) / 1000, timezone.utc).isoformat()


def times(tree: dict) -> dict:
    return {n["text"]: n["title"] for n in nodes(tree) if n["tag"] == "time"}


class PageTimeTest(unittest.TestCase):
    begin = {"start": {"focused": False, "clock": NOW_MS}}

    def test_times_read_relative_and_resets_read_a_weekday_with_the_exact_time_in_the_title(self) -> None:
        sprinted = {**project(0, []), "sprints": [{**SPRINT, "stated_at": "2026-11-11T11:57:00+00:00"}]}
        quiet = {**project(1, [], quiet=True), "last_activity": "2026-11-08T11:00:00+00:00"}
        first = view([sprinted, quiet])
        first["inbox"]["open"] = [item(
            "A", waiting_since="2026-11-11T09:00:00+00:00", stale=True,
            read_at="2026-11-10T10:00:00+00:00")]
        first["statement"]["inbox_items"] = 1
        first["digest"] = {
            "since": "2026-11-11T10:30:00+00:00", "first_visit": False,
            "recent": [moment("2026-11-11T11:55:00+00:00", "Newest.")],
            "earlier": [], "omitted": 0,
        }
        first["capacity"] = capacity([
            profile("a", "ok", week_left=62, next_reset="2026-11-16T05:00:00+00:00"),
            profile("b", "out", out_until="2026-11-13T09:30:00+00:00"),
        ])
        second = {**first, "capacity": capacity([
            profile("a", "out", out_until="2026-11-13T09:30:00+00:00"),
            profile("b", "out", out_until="2026-11-13T10:00:00+00:00"),
        ], all_out=True, resumes_at="2026-11-13T09:30:00+00:00")}
        one, two = render([
            self.begin, {"frame": first}, {"snapshot": True},
            {"frame": second}, {"snapshot": True},
        ])
        self.assertIn("waiting 3 h", full(one["inbox"]))
        self.assertIn("read yesterday", full(one["inbox"]))
        self.assertIn("Since you last looked, 1 h ago", full(one["digest"]))
        self.assertIn("5 min ago", full(one["digest"]))
        self.assertIn("resets Mon 05:00", full(one["capacity"]))
        self.assertIn("out until Fri 09:30", full(one["capacity"]))
        self.assertIn("stated 3 min ago", full(one["projects"]))
        self.assertIn("untouched for 3 days", full(one["projects"]))
        self.assertIn("Resumes Fri 09:30", full(two["statement"]))
        self.assertIn("out until Fri 09:30", full(two["promoted"]))
        seen = {}
        for snap in (one, two):
            for tree in snap.values():
                if isinstance(tree, dict) and "children" in tree:
                    seen.update(times(tree))
                    for n in nodes(tree):
                        self.assertIsNone(RAW_TIMESTAMP.search(n["text"]), n["text"])
        expected = {
            "3 h": "2026-11-11 09:00", "yesterday": "2026-11-10 10:00",
            "1 h ago": "2026-11-11 10:30", "5 min ago": "2026-11-11 11:55",
            "Mon 05:00": "2026-11-16 05:00", "Fri 09:30": "2026-11-13 09:30",
            "3 min ago": "2026-11-11 11:57", "3 days": "2026-11-08 11:00",
        }
        for words, title in expected.items():
            self.assertEqual(seen.get(words), title, words)

    def test_a_delivery_age_reads_from_its_movement_time_and_moves_with_the_clock(self) -> None:
        moving = {**RUN, "moved_at": "2026-11-11T11:57:00+00:00"}
        quiet = {**RUN, "run_id": "wf_q", "quiet": True, "moved_text": "quiet for 22 min",
                 "summary": "No issue in delivery yet, quiet for 22 min", "issues": [],
                 "moved_at": "2026-11-11T11:38:00+00:00"}
        entry = project(0, [session("s1", "working", "working", deliveries=[moving, quiet])])
        entry["outside_sprints"]["summary"] = "1 working"
        before, after = render([
            self.begin, {"frame": view([entry])}, {"open": "line:owner/p00"}, {"snapshot": True},
            {"clock": NOW_MS + 3 * 3600 * 1000}, {"snapshot": True},
        ])
        sums = [n for n in nodes(before["projects"]) if has_class(n, "run-sum")]
        self.assertEqual(
            [full(n) for n in sums],
            ["2 issues in delivery: 1 building, 1 plan review, moved 3 min ago",
             "No issue in delivery yet, quiet for 22 min"])
        self.assertEqual([[(t["text"], t["title"]) for t in nodes(n) if t["tag"] == "time"]
                          for n in sums],
                         [[("3 min ago", "2026-11-11 11:57")], [("22 min", "2026-11-11 11:38")]])
        moved = [n for n in nodes(before["projects"]) if has_class(n, "moved")]
        self.assertEqual([[(t["text"], t["title"]) for t in nodes(n) if t["tag"] == "time"]
                          for n in moved],
                         [[("3 min ago", "2026-11-11 11:57")], [("22 min", "2026-11-11 11:38")]])
        sums = [n for n in nodes(after["projects"]) if has_class(n, "run-sum")]
        self.assertEqual(
            [full(n) for n in sums],
            ["2 issues in delivery: 1 building, 1 plan review, moved 3 h ago",
             "No issue in delivery yet, quiet for 3 h"])

    def test_ages_follow_the_thresholds(self) -> None:
        second, minute, hour = 1000, 60000, 3600000
        offsets = [-10 * second, 59 * second, 60 * second, 59 * minute, 60 * minute,
                   23 * hour + 59 * minute, 24 * hour, 47 * hour + 59 * minute, 48 * hour, 72 * hour]
        moments = [moment(utc(offset), f"M{n}.") for n, offset in enumerate(offsets)]
        frame = view([])
        frame["digest"] = {
            "since": utc(hour), "first_visit": False,
            "recent": moments[:5], "earlier": moments[5:], "omitted": 0,
        }
        (snap,) = render([self.begin, {"frame": frame}, {"snapshot": True}])
        lines = [n for n in nodes(snap["digest"]) if n["tag"] == "li"]
        words = [next(c["text"] for c in nodes(n) if c["tag"] == "time") for n in lines]
        self.assertEqual(words, ["just now", "just now", "1 min ago", "59 min ago", "1 h ago",
                                 "23 h ago", "yesterday", "yesterday", "2 days ago", "3 days ago"])

    def test_ages_move_with_the_clock_without_a_new_frame(self) -> None:
        frame = view([])
        frame["inbox"]["open"] = [check_item(
            "A", "manual-check", waiting_since="2026-11-11T11:50:00+00:00")]
        frame["statement"]["inbox_items"] = 1
        frame["digest"] = {
            "since": "2026-11-11T11:00:00+00:00", "first_visit": False,
            "recent": [moment("2026-11-11T11:59:30+00:00", "Newest.")],
            "earlier": [moment("2026-11-11T10:00:00+00:00", "Older.")], "omitted": 0,
        }
        before, after = render([
            self.begin, {"frame": frame}, {"open": "earlier"},
            {"type": {"class": "note-text", "text": "half a note"}}, {"snapshot": True},
            {"clock": NOW_MS + 3 * 3600 * 1000}, {"snapshot": True},
        ])

        def newest(snap: dict) -> dict:
            (line,) = [n for n in nodes(snap["digest"]) if n["tag"] == "ul" and n["cls"] == "digest"]
            return next(n for n in nodes(line) if n["tag"] == "time")

        self.assertEqual((newest(before)["text"], newest(before)["title"]),
                         ("just now", "2026-11-11 11:59"))
        self.assertIn("waiting 10 min", full(before["inbox"]))
        self.assertIn("Since you last looked, 1 h ago", full(before["digest"]))
        self.assertEqual((newest(after)["text"], newest(after)["title"]),
                         ("3 h ago", "2026-11-11 11:59"))
        self.assertIn("waiting 3 h", full(after["inbox"]))
        self.assertIn("Since you last looked, 4 h ago", full(after["digest"]))
        (fold,) = [n for n in nodes(after["digest"]) if n["tag"] == "details"]
        self.assertTrue(fold["open"])
        (note,) = [n for n in nodes(after["inbox"]) if has_class(n, "note-text")]
        self.assertEqual(note["value"], "half a note")
        self.assertEqual(after["active"], "note-text")
        self.assertEqual(after["posts"], before["posts"])


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

ANSWERABLE = item("A", headline="Which host?", questions=[
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
    """The option words of every `.picked` node: its `span.ot` child when it has one, else the node."""
    found = []
    for n in nodes(snap["inbox"]):
        if has_class(n, "picked"):
            words = [c for c in n["children"] if has_class(c, "ot")]
            found.append(full(words[0]) if words else full(n))
    return found


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
        (row,) = [n for n in nodes(moved["inbox"]) if n["tag"] == "details" and has_class(n, "done-item")]
        (summary,) = [c for c in row["children"] if c["tag"] == "summary"]
        self.assertIn("waiting for the agent", full(summary))

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


def checks(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/check-answer"]


def field(snap: dict, cls: str) -> dict:
    return next(n for n in nodes(snap["inbox"]) if has_class(n, cls))


def ans_buttons(snap: dict) -> dict:
    out = {}
    for n in nodes(snap["inbox"]):
        for name in n["cls"].split():
            if name.startswith("ans-"):
                out[name] = n["text"]
    return out


REASONS = {"manual-check": "verify-ask", "verdict": "verify-decision",
           "approval": "verify-approve", "paid-approval": "verify-approve",
           "stale-check": "verify-stale-check", "act": "verify-act"}
ANSWERS = {"manual-check": ["passed", "failed", "note"], "verdict": ["passed", "failed"],
           "approval": ["approve"], "paid-approval": ["approve"],
           "stale-check": ["keep", "drop"], "act": []}


def check_item(key: str, kind: str, **fields) -> dict:
    base = {"reason": REASONS[kind], "kind": kind, "answers": ANSWERS[kind],
            "detail": "", "paid": kind == "paid-approval", "confirm": "", "version": "v1-" + key}
    if kind in ("approval", "paid-approval"):
        base["confirm"] = "octo/widgets#12"
    base.update(fields)
    return item(key, **base)


def checked(snap: dict) -> list:
    return [posted(p) for p in checks(snap)]


class PageCheckAnswerTest(unittest.TestCase):
    def test_a_manual_check_is_marked_passed_after_the_undo(self) -> None:
        early, late = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"click": "ans-passed"}, {"clock": 4999}, {"snapshot": True},
            {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(checks(early), [])
        self.assertIn(WAIT_TEXT, full(early["inbox"]))
        self.assertIn("Undo", full(early["inbox"]))
        (post,) = checks(late)
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"],
                         {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
        self.assertEqual(posted(post),
                         {"project_id": "owner/p00", "key": "A", "answer": "passed",
                          "version": "v1-A"})
        self.assertEqual(answers(late), [])
        self.assertIn(SENT_TEXT, full(late["inbox"]))

    def test_an_answer_carries_the_version_seen_when_it_was_chosen(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"click": "ans-passed"},
            {"frame": frame([check_item("A", "manual-check", version="v2-A")])},
            {"clock": 5000}, {"snapshot": True},
        ])
        (post,) = checks(snap)
        self.assertEqual(posted(post)["version"], "v1-A")

    def test_undo_withdraws_a_check_answer(self) -> None:
        for name, undo in (("escape", {"key": "Escape"}), ("button", {"click": "undo"})):
            with self.subTest(name):
                (snap,) = render([
                    START, {"frame": frame([check_item("A", "manual-check")])},
                    {"click": "ans-failed"}, {"clock": 3000}, undo, {"clock": 20000},
                    {"snapshot": True},
                ])
                self.assertEqual(checks(snap), [])
                self.assertNotIn(WAIT_TEXT, full(snap["inbox"]))
                self.assertEqual(count(snap, "ans-failed"), 1)

    def test_a_note_is_sent_verbatim(self) -> None:
        note = "Loads, but slowly.\nna\u00efve"
        typed, sent = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"type": {"class": "note-text", "text": note}}, {"snapshot": True},
            {"click": "ans-note"}, {"clock": 5000}, {"snapshot": True},
        ])
        area = field(typed, "note-text")
        self.assertEqual((area["tag"], area["value"]), ("textarea", note))
        (post,) = checks(sent)
        self.assertEqual(posted(post), {"project_id": "owner/p00", "key": "A",
                                        "answer": "note", "version": "v1-A", "note": note})
        self.assertEqual(field(sent, "note-text")["value"], "")
        self.assertIn("Note sent.", full(sent["inbox"]))
        self.assertNotIn(SENT_TEXT, full(sent["inbox"]))

    def test_an_empty_note_cannot_be_sent(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"click": "ans-note"}, {"clock": 20000}, {"snapshot": True},
        ])
        self.assertTrue(field(snap, "ans-note")["disabled"])
        self.assertEqual(checks(snap), [])
        self.assertNotIn(WAIT_TEXT, full(snap["inbox"]))

    def test_each_kind_renders_its_answers(self) -> None:
        cases = {
            "manual-check": {"ans-passed": "Passed", "ans-failed": "Failed", "ans-note": "Send note"},
            "verdict": {"ans-passed": "Accept as passed", "ans-failed": "Close as not verified"},
            "approval": {"ans-approve": "Approve"},
            "paid-approval": {"ans-approve": "Approve"},
            "stale-check": {"ans-keep": "Keep waiting", "ans-drop": "Accept without the host"},
            "act": {},
        }
        for kind, labels in cases.items():
            with self.subTest(kind):
                (snap,) = render([
                    START,
                    {"frame": frame([check_item("A", kind, detail="Run the thing.")])},
                    {"snapshot": True},
                ])
                self.assertEqual(ans_buttons(snap), labels)
                self.assertIn("Run the thing.", full(snap["inbox"]))
                self.assertEqual(
                    [n["tag"] for n in nodes(snap["inbox"]) if has_class(n, "detail")], ["pre"])

    def test_a_paid_approval_needs_its_typed_confirmation(self) -> None:
        paid = check_item("P", "paid-approval", confirm="octo/widgets#10",
                          detail='Command: ["just", "smoke"]')
        shown, short, exact, sent = render([
            START, {"frame": frame([paid])}, {"snapshot": True},
            {"type": {"class": "confirm-text", "text": "octo/widgets#1"}}, {"snapshot": True},
            {"type": {"class": "confirm-text", "text": "octo/widgets#10"}}, {"snapshot": True},
            {"click": "ans-approve"}, {"clock": 5000}, {"snapshot": True},
        ])
        text = full(shown["inbox"])
        for expected in ('Command: ["just", "smoke"]', "This check costs money.",
                         "Type octo/widgets#10 to approve."):
            self.assertIn(expected, text)
        self.assertLess(text.index("This check costs money."), text.index("Command:"))
        self.assertLess(text.index("Command:"), text.index("Type octo/widgets#10"))
        self.assertEqual(field(shown, "confirm-text")["tag"], "input")
        self.assertTrue(field(shown, "ans-approve")["disabled"])
        self.assertTrue(field(short, "ans-approve")["disabled"])
        self.assertFalse(field(exact, "ans-approve")["disabled"])
        (post,) = checks(sent)
        self.assertEqual(posted(post), {"project_id": "owner/p00", "key": "P",
                                        "answer": "approve", "version": "v1-P", "confirm": "octo/widgets#10"})

    def test_a_live_approval_needs_its_typed_confirmation(self) -> None:
        live = check_item("L", "approval", detail='Command: ["just", "check"]')
        shown, short, exact, sent = render([
            START, {"frame": frame([live])}, {"snapshot": True},
            {"type": {"class": "confirm-text", "text": "octo/widgets#1"}}, {"snapshot": True},
            {"type": {"class": "confirm-text", "text": "octo/widgets#12"}}, {"snapshot": True},
            {"click": "ans-approve"}, {"clock": 5000}, {"snapshot": True},
        ])
        text = full(shown["inbox"])
        self.assertIn('Command: ["just", "check"]', text)
        self.assertIn("Type octo/widgets#12 to approve.", text)
        self.assertNotIn("This check costs money.", text)
        self.assertTrue(field(shown, "ans-approve")["disabled"])
        self.assertTrue(field(short, "ans-approve")["disabled"])
        self.assertFalse(field(exact, "ans-approve")["disabled"])
        (post,) = checks(sent)
        self.assertEqual(posted(post), {"project_id": "owner/p00", "key": "L",
                                        "answer": "approve", "version": "v1-L", "confirm": "octo/widgets#12"})

    def test_a_disabled_approve_sends_nothing(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("L", "approval")])},
            {"click": "ans-approve"}, {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(checks(snap), [])

    def test_a_draft_and_its_focus_survive_a_new_frame(self) -> None:
        a = check_item("A", "manual-check")
        live = check_item("L", "approval", confirm="octo/widgets#12")
        b = check_item("B", "manual-check")
        one, two, three, four = render([
            START, {"frame": frame([a, live])},
            {"append": {"class": "note-text", "text": "Loads"}},
            {"frame": frame([a, live, b])}, {"snapshot": True},
            {"append": {"class": "note-text", "text": ", but slowly"}},
            {"click": "ans-note"}, {"clock": 5000}, {"snapshot": True},
            {"type": {"class": "confirm-text", "text": "octo/widgets"}},
            {"frame": frame([a, live, b, OTHER])}, {"snapshot": True},
            {"append": {"class": "confirm-text", "text": "#12"}}, {"snapshot": True},
        ])
        area = field(one, "note-text")
        self.assertEqual((area["value"], area["focused"], area["selection"]),
                         ("Loads", True, [5, 5]))
        (post,) = checks(two)
        self.assertEqual(posted(post)["note"], "Loads, but slowly")
        box = field(three, "confirm-text")
        self.assertEqual((box["value"], box["focused"]), ("octo/widgets", True))
        self.assertTrue(field(three, "ans-approve")["disabled"])
        self.assertFalse(field(four, "ans-approve")["disabled"])

    def test_a_restored_note_is_sendable_at_once_after_a_redraw(self) -> None:
        a = check_item("A", "manual-check")
        b = check_item("B", "manual-check")
        frame_then, undone, sent = render([
            START, {"frame": frame([a])},
            {"type": {"class": "note-text", "text": "Loads"}},
            {"frame": frame([a, b])}, {"snapshot": True},
            {"click": "ans-note"}, {"key": "Escape"}, {"snapshot": True},
            {"click": "ans-note"}, {"clock": 5000}, {"snapshot": True},
        ])
        for snap in (frame_then, undone):
            self.assertEqual(field(snap, "note-text")["value"], "Loads")
            self.assertFalse(field(snap, "ans-note")["disabled"])
        (post,) = checks(sent)
        self.assertEqual(posted(post)["note"], "Loads")

    def test_a_failed_note_can_be_retried_without_typing(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"respond": {"status": 502, "text": "gh_failed\n"}},
            {"type": {"class": "note-text", "text": "Loads"}},
            {"click": "ans-note"}, {"clock": 5000},
            {"click": "ans-note"}, {"clock": 10000}, {"snapshot": True},
        ])
        self.assertEqual([posted(p)["note"] for p in checks(snap)], ["Loads", "Loads"])

    def test_a_draft_is_dropped_when_its_item_is_gone(self) -> None:
        a = check_item("A", "manual-check")
        again, = render([
            START, {"frame": frame([a])},
            {"type": {"class": "note-text", "text": "stale"}},
            {"frame": frame([])}, {"frame": frame([a])}, {"snapshot": True},
        ])
        self.assertEqual(field(again, "note-text")["value"], "")

    def test_a_refused_check_answer_reads_could_not_send(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"respond": {"status": 409, "text": "this item does not take that answer\n"}},
            {"click": "ans-passed"}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertIn("Could not send: this item does not take that answer",
                      full(snap["inbox"]))
        self.assertEqual(count(snap, "ans-passed"), 1)

    def test_keys_never_answer_a_verification_item(self) -> None:
        (snap,) = render([
            START, {"frame": frame([check_item("A", "manual-check")])},
            {"key": "1"}, {"key": "Enter"}, {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(snap["posts"], [])

    def test_typing_in_a_field_never_drives_a_decision(self) -> None:
        (snap,) = render([
            START,
            {"frame": frame([ANSWERABLE, check_item("M", "manual-check"),
                             check_item("L", "approval")])},
            {"key": "2", "target": "TEXTAREA"}, {"key": "Enter", "target": "TEXTAREA"},
            {"key": "1", "target": "INPUT"}, {"key": "Enter", "target": "INPUT"},
            {"key": "Enter", "target": "DIV", "editable": True},
            {"clock": 20000}, {"snapshot": True},
        ])
        self.assertEqual(answers(snap), [])
        self.assertEqual(checks(snap), [])
        self.assertEqual(len(picked(snap)), 1)
        self.assertTrue(picked(snap)[0].endswith("two"))


def moment(at: str, sentence: str) -> dict:
    return {"at": at, "kind": "session.hook", "sentence": sentence}


def with_digest(digest: dict | None) -> dict:
    frame = view([])
    if digest is not None:
        frame["digest"] = digest
    return frame


def q(question: str, options: list) -> dict:
    return {"question": question, "options": options, "chosen": None, "recommended": None}


class PageInboxGlanceTest(unittest.TestCase):
    def test_an_item_is_headed_by_its_first_question_with_a_count(self) -> None:
        first = item("M", issue=7, headline="Which database?", more_questions=2, question=BOILER,
                     questions=[q("Which database?", ["sqlite", "postgres"]),
                                q("Which port?", ["80", "8080"]), q("Which host?", ["one", "two"])])
        second = item("N", issue=22, headline="Which cache?",
                      questions=[q("Which cache?", ["redis", "memcached"])])
        (snap,) = render([START, {"frame": frame([first, second])}, {"snapshot": True}])
        inbox = snap["inbox"]
        (head,) = [n for n in nodes(inbox) if n["tag"] == "h2" and has_class(n, "q")]
        self.assertEqual(head["text"], "Which database?")
        self.assertEqual(full(inbox).count("and 2 more questions"), 1)
        (rest,) = [n for n in nodes(inbox) if has_class(n, "rest")]
        self.assertNotIn("more question", full(rest))
        self.assertEqual(full(inbox).count("Which cache?"), 1)
        self.assertNotIn(BOILER, full(inbox))
        self.assertIsNone(re.search(r"#\d", full(inbox)))
        lead = inbox["children"][0]
        (meta,) = [n for n in nodes(lead) if has_class(n, "meta") and "waiting" in full(n)]
        self.assertIn("owner/p00", full(meta))
        self.assertIsNone(re.search(r"item\.question(?!s)", PAGE.read_text(encoding="utf-8")))

    def test_a_single_question_is_its_headline_and_has_no_label_above_its_options(self) -> None:
        only = item("S", headline="Which cache?", questions=[q("Which cache?", ["redis", "memcached"])])
        (snap,) = render([START, {"frame": frame([only])}, {"snapshot": True}])
        self.assertEqual(full(snap["inbox"]).count("Which cache?"), 1)

    def test_an_answered_item_is_one_closed_line_until_opened(self) -> None:
        done = item("Z", answered=True, headline="Which database?",
                    answered_at="2026-11-11T10:00:00+00:00",
                    questions=[{"question": "Which database?", "options": ["sqlite", "postgres"],
                                "chosen": "postgres", "recommended": None}])
        closed, opened = render([
            {"start": {"focused": False, "clock": NOW_MS}}, {"frame": frame([], answered=[done])},
            {"snapshot": True}, {"open": "answered:owner/p00#Z"}, {"snapshot": True},
        ])
        (ul,) = [n for n in nodes(closed["inbox"]) if n["tag"] == "ul" and has_class(n, "done")]
        (row,) = ul["children"]
        self.assertEqual(row["tag"], "li")
        (fold,) = row["children"]
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual([(c["tag"], c["cls"]) for c in summary["children"]],
                         [("b", ""), ("span", "when")])
        self.assertEqual(summary["children"][0]["text"], "Which database?")
        self.assertEqual(full(summary["children"][1]), "answered 2 h ago, waiting for the agent")
        inside = {id(n) for n in nodes(summary)} | {id(row), id(fold)}
        self.assertTrue(all(id(n) in inside for n in visible(row)))
        self.assertNotIn("postgres", visible_text(row))
        self.assertNotIn("Answer on the tracker", visible_text(row))
        (fold,) = [n for n in nodes(opened["inbox"]) if n["tag"] == "details" and has_class(n, "done-item")]
        self.assertTrue(fold["open"])
        self.assertIn("chosen: postgres", full(fold))
        self.assertIn("Answer on the tracker", full(fold))

    def test_an_answered_multi_question_item_keeps_its_count_in_the_closed_line(self) -> None:
        done = item("Z", answered=True, headline="Which database?", more_questions=2,
                    answered_at="2026-11-11T10:00:00+00:00",
                    questions=[q("Which database?", ["sqlite", "postgres"]),
                               q("Which port?", ["80", "8080"]), q("Which host?", ["one", "two"])])
        one = item("Y", answered=True, headline="Which cache?", more_questions=1,
                   answered_at="2026-11-11T10:00:00+00:00",
                   questions=[q("Which cache?", ["redis", "memcached"]),
                              q("Which size?", ["s", "m"])])
        (snap,) = render([
            {"start": {"focused": False, "clock": NOW_MS}},
            {"frame": frame([], answered=[done, one])}, {"snapshot": True},
        ])
        rows = [n for n in nodes(snap["inbox"]) if n["tag"] == "summary"]
        self.assertEqual(
            [[full(c) for c in r["children"]] for r in rows],
            [["Which database?", "and 2 more questions", "answered 2 h ago, waiting for the agent"],
             ["Which cache?", "and 1 more question", "answered 2 h ago, waiting for the agent"]])

    def test_a_conflict_or_needs_label_item_shows_no_issue_number_until_opened(self) -> None:
        conflict = item(
            "C", issue=9, reason="conflict", headline="Landing stopped on a merge conflict.",
            items=["PR #14 of issue #9 conflicts with main a second time in one landing, so the "
                   "merge was aborted. Resolve the conflict on the branch, then relaunch the batch."])
        label = item(
            "L", issue=11, reason="needs-label", headline="A check needs a label.",
            items=["PR #15 of issue #11 needs the label deploy, which only the owner applies; "
                   "the failing checks: build."])
        closed, opened = render([
            START, {"frame": frame([conflict, label])}, {"snapshot": True},
            {"open": "items:owner/p00#C"}, {"open": "items:owner/p00#L"}, {"snapshot": True},
        ])
        self.assertIsNone(re.search(r"#\d", visible_text(closed["inbox"])))
        self.assertIn("Landing stopped on a merge conflict.", visible_text(closed["inbox"]))
        shown = visible_text(opened["inbox"])
        self.assertIn("PR #14 of issue #9 conflicts", shown)
        self.assertIn("PR #15 of issue #11 needs the label", shown)

    def test_an_open_answered_line_survives_a_key_redraw(self) -> None:
        done = item("Z", answered=True, headline="Which database?")
        (snap,) = render([
            START, {"frame": frame([ANSWERABLE], answered=[done])},
            {"open": "answered:owner/p00#Z"}, {"key": "2"}, {"snapshot": True},
        ])
        (fold,) = [n for n in nodes(snap["inbox"]) if n["key"] == "answered:owner/p00#Z"]
        self.assertTrue(fold["open"])

    def test_a_checks_detail_and_confirmation_show_only_when_opened(self) -> None:
        live = check_item("P", "approval", issue=12, headline="Approve the live check?",
                          detail="nix-build /srv/p00/checks/live.nix")
        manual = check_item("M", "manual-check", detail="Open /srv/p00/README.md and read it.")
        closed, opened = render([
            START, {"frame": frame([live, manual])}, {"snapshot": True},
            {"open": "check:owner/p00#P"},
            {"type": {"class": "confirm-text", "text": "octo/widgets#12"}}, {"snapshot": True},
        ])
        shown = visible_text(closed["inbox"])
        for expected in ("Review and approve", "Show the check", "Approve the live check?"):
            self.assertIn(expected, shown)
        for hidden in ("octo/widgets#12", "to approve.", "/srv"):
            self.assertNotIn(hidden, shown)
        self.assertIsNone(re.search(r"#\d", shown))
        self.assertTrue(field(closed, "ans-approve")["disabled"])
        (fold,) = [n for n in nodes(opened["inbox"]) if n["key"] == "check:owner/p00#P"]
        self.assertTrue(fold["open"])
        shown = visible_text(opened["inbox"])
        self.assertIn("Type octo/widgets#12 to approve.", shown)
        self.assertIn("nix-build /srv/p00/checks/live.nix", shown)
        self.assertNotIn("/srv/p00/README.md", shown)
        self.assertFalse(field(opened, "ans-approve")["disabled"])

    def test_an_act_prompts_detail_shows_only_when_its_fold_is_opened(self) -> None:
        act = check_item("A", "act", answers=[], detail="Run /srv/p00/deploy.sh on the host.")
        closed, opened = render([
            START, {"frame": frame([act])}, {"snapshot": True},
            {"open": "check:owner/p00#A"}, {"snapshot": True},
        ])
        self.assertNotIn("/srv/p00/deploy.sh", visible_text(closed["inbox"]))
        (fold,) = [n for n in nodes(closed["inbox"]) if n["key"] == "check:owner/p00#A"]
        self.assertFalse(fold["open"])
        self.assertIn("Show the check", visible_text(closed["inbox"]))
        self.assertIn("/srv/p00/deploy.sh", visible_text(opened["inbox"]))


class PageCardTest(unittest.TestCase):
    def test_the_first_open_item_is_one_card_for_each_kind(self) -> None:
        cases = [
            ([ANSWERABLE], "Decision", "owner/p00", "Which host?", "Send answer", True),
            ([BRIEF], "Brief", "owner/p01", "owner/p01 brief, version 2", "Approve", True),
            ([check_item("M", "manual-check")], "Check", "owner/p00", "Question M?", "Passed", False),
            ([check_item("L", "approval")], "Approval", "owner/p00", "Question L?", "Approve", False),
        ]
        for open_items, word, project, heading, label, enter in cases:
            with self.subTest(kind=word):
                (snap,) = render([START, {"frame": frame(open_items)}, {"snapshot": True}])
                card = snap["inbox"]["children"][0]
                self.assertEqual(card["tag"], "article")
                self.assertTrue(has_class(card, "card") and has_class(card, "lead"))
                self.assertEqual([n for n in nodes(snap["inbox"]) if has_class(n, "lead")], [card])
                (head,) = [n for n in nodes(card) if n["tag"] == "h2" and has_class(n, "q")]
                self.assertEqual(full(head), heading)
                (top,) = [n for n in nodes(card) if n["tag"] == "p" and has_class(n, "head")]
                (kind,) = [n for n in nodes(top) if has_class(n, "kind")]
                self.assertEqual(full(kind), word)
                self.assertIn("svg", [c["tag"] for c in kind["children"]])
                self.assertIn(project, full(top))
                self.assertIn("waiting ", full(top))
                primaries = [n for n in nodes(card) if has_class(n, "primary")]
                self.assertEqual(len(primaries), 1)
                self.assertEqual(primaries[0]["tag"], "button")
                self.assertEqual(primaries[0]["text"], label)
                self.assertEqual([full(c) for c in primaries[0]["children"] if c["tag"] == "kbd"],
                                 ["Enter"] if enter else [])

    def test_the_lead_card_holds_its_held_work_under_the_options_and_its_link_under_detail(self) -> None:
        lead = item("A", held_work=3, headline="Which host?", questions=ANSWERABLE["questions"])
        (snap,) = render([START, {"frame": frame([lead])}, {"snapshot": True}])
        card = snap["inbox"]["children"][0]
        flat = nodes(card)
        opts = next(i for i, n in enumerate(flat) if has_class(n, "opts"))
        held = next(i for i, n in enumerate(flat) if has_class(n, "held"))
        primary = next(i for i, n in enumerate(flat) if has_class(n, "primary"))
        self.assertLess(opts, held)
        self.assertLess(held, primary)
        self.assertEqual(full(flat[held]), "holds 3 issues")
        (link,) = [n for n in flat if n["tag"] == "a"]
        self.assertTrue(has_class(link, "answer"))
        (fold,) = [n for n in flat if n["tag"] == "details"]
        self.assertEqual(fold["key"], "detail:owner/p00#A")
        self.assertIn(id(link), {id(n) for n in nodes(fold)})
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "Detail")
        self.assertNotIn("Answer on the tracker", visible_text(card))

    def test_a_card_without_a_page_answer_makes_its_tracker_link_primary(self) -> None:
        conflict = item("K", reason="conflict", items=["Rebase onto main."],
                        waiting_since="2026-11-10T07:00:00+00:00")
        (snap,) = render([START, {"frame": frame([conflict, ANSWERABLE])}, {"snapshot": True}])
        card = snap["inbox"]["children"][0]
        (kind,) = [n for n in nodes(card) if has_class(n, "kind")]
        self.assertEqual(full(kind), "Conflict")
        (primary,) = [n for n in nodes(card) if has_class(n, "primary")]
        self.assertEqual(primary["tag"], "a")
        self.assertTrue(has_class(primary, "answer"))
        self.assertEqual(primary["text"], "Answer on the tracker")
        self.assertEqual([n for n in nodes(card) if n["key"] == "detail:owner/p00#K"], [])
        entered = [n for n in nodes(snap["inbox"]) if n["tag"] == "button"
                   and any(c["tag"] == "kbd" and full(c) == "Enter" for c in n["children"])]
        self.assertEqual([n["text"] for n in entered], ["Send answer"])
        self.assertFalse(has_class(entered[0], "primary"))

    def test_with_a_brief_waiting_the_brief_is_the_one_raised_card(self) -> None:
        (snap,) = render([START, {"frame": frame([BRIEF, ANSWERABLE])}, {"snapshot": True}])
        leads = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertEqual(len(leads), 1)
        self.assertTrue(has_class(leads[0], "brief"))
        articles = [n for n in nodes(snap["inbox"]) if n["tag"] == "article"]
        self.assertTrue(articles)
        self.assertTrue(all(has_class(n, "brief") for n in articles))

    def test_the_primary_style_outranks_the_button_base_rules(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        rules = []
        for body in re.findall(r"(?s)<style>(.*?)</style>", text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            for selectors, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                names = [d.partition(":")[0].strip() for d in rule.split(";") if d.strip()]
                for selector in selectors.split(","):
                    rules.append((" ".join(selector.split()), names))

        def spec(selector: str) -> tuple:
            selector = re.sub(r"::[\w-]+", "", selector)
            b = len(re.findall(r"\[[^\]]*\]", selector))
            rest = re.sub(r"\[[^\]]*\]", "", selector)
            a = len(re.findall(r"#[\w-]+", rest))
            rest = re.sub(r"#[\w-]+", "", rest)
            b += len(re.findall(r"\.[\w-]+", rest)) + len(re.findall(r":[\w-]+", rest))
            c = sum(1 for t in re.split(r"[\s>+~]+", rest) if t[:1].isalpha())
            return (a, b, c)

        self.assertEqual(spec('.abox button[class^="ans-"]'), (0, 2, 1))
        self.assertEqual(spec(".act .primary.needs:hover:enabled"), (0, 5, 0))
        for state in ("", ":hover:enabled", ":disabled"):
            with self.subTest(state=state):
                mine = [s for s, names in rules if s.endswith(".primary.needs" + state) and "background" in names]
                bases = (".send", ".approve", ".answer", 'button[class^="ans-"]')
                rivals = [s for s, _ in rules if any(s.endswith(base + state) for base in bases)]
                self.assertTrue(mine)
                self.assertTrue(rivals)
                self.assertGreater(min(spec(s) for s in mine), max(spec(s) for s in rivals))
                if state == "":
                    declared = [names for s, names in rules if s in mine]
                    for prop in ("background", "color", "border", "padding", "border-radius"):
                        self.assertTrue(any(prop in names for names in declared), prop)


class PageRowTest(unittest.TestCase):
    @staticmethod
    def rows() -> tuple:
        rest_items = [
            ANSWERABLE,
            item("C", issue=9, reason="conflict", headline="Landing stopped.", items=["PR #14 conflicts."]),
            item("N", issue=11, reason="needs-label", headline="A check needs a label.", items=["PR #15 needs a label."]),
            check_item("M", "manual-check"),
            check_item("P", "approval", held_work=2),
        ]
        (snap,) = render([START, {"frame": frame(rest_items)}, {"snapshot": True}])
        (rest,) = [n for n in nodes(snap["inbox"]) if has_class(n, "rest")]
        return rest, rest["children"]

    def test_every_other_open_item_is_one_row_with_its_kind_headline_project_and_wait(self) -> None:
        _, rows = self.rows()
        self.assertEqual([(r["tag"], has_class(r, "row")) for r in rows], [("li", True)] * 4)
        heads = [r["children"][0] for r in rows]
        for head in heads:
            self.assertEqual(head["tag"], "p")
            self.assertTrue(has_class(head, "row-head"))
            self.assertEqual([(c["tag"], c["cls"].split()[0] if c["cls"] else "") for c in head["children"]],
                             [("span", "kind"), ("b", ""), ("span", "lm"), ("span", "lw")])
            self.assertIsNone(re.search(r"#\d", full(head)))
            self.assertTrue(full(head["children"][3]).startswith("waiting "))
            self.assertIn("owner/p00", full(head["children"][2]))
        kinds = [head["children"][0] for head in heads]
        self.assertEqual([full(k) for k in kinds], ["Conflict", "Label", "Check", "Approval"])
        for kind in kinds:
            self.assertIn("svg", [c["tag"] for c in kind["children"]])
        self.assertEqual([full(h["children"][1]) for h in heads],
                         ["Landing stopped.", "A check needs a label.", "Question M?", "Question P?"])
        self.assertIn("holds 2 issues", full(heads[3]["children"][2]))

    def test_a_row_is_never_raised_and_takes_no_primary_action(self) -> None:
        rest, rows = self.rows()
        self.assertTrue(all(has_class(r, "row") for r in rest["children"]))
        for n in nodes(rest):
            for name in ("card", "lead", "primary"):
                self.assertFalse(has_class(n, name), name)
        self.assertTrue([n for n in nodes(rows[2]) if has_class(n, "ans-passed")])


class PageOptionTest(unittest.TestCase):
    @staticmethod
    def three(chosen=None) -> dict:
        return item("D", headline="Which database?", questions=[
            {"question": "Which database?", "options": ["sqlite", "postgres", "mysql"],
             "chosen": chosen, "recommended": "postgres"}])

    @staticmethod
    def options(snap: dict) -> list:
        return [n for n in nodes(snap["inbox"]) if has_class(n, "opt")]

    def test_each_option_is_a_button_with_its_key_badge_and_words(self) -> None:
        (snap,) = render([START, {"frame": frame([self.three()])}, {"snapshot": True}])
        opts = self.options(snap)
        self.assertEqual(len(opts), 3)
        for i, (opt, words) in enumerate(zip(opts, ["sqlite", "postgres", "mysql"])):
            self.assertEqual(opt["tag"], "button")
            self.assertEqual(opt["children"][0]["tag"], "kbd")
            self.assertEqual(opt["children"][0]["text"], str(i + 1))
            (ot,) = [c for c in opt["children"] if has_class(c, "ot")]
            self.assertEqual(full(ot), words)
            recs = [c for c in opt["children"] if has_class(c, "rec")]
            if i == 1:
                self.assertEqual([full(c) for c in recs], ["Recommended"])
            else:
                self.assertEqual(recs, [])
        self.assertEqual([o["pressed"] for o in opts], ["false", "true", "false"])
        self.assertEqual(picked(snap), ["postgres"])

    def test_a_number_key_moves_the_pressed_option(self) -> None:
        (snap,) = render([START, {"frame": frame([ANSWERABLE])}, {"key": "1"}, {"snapshot": True}])
        opts = self.options(snap)
        self.assertEqual([o["pressed"] for o in opts], ["true", "false"])
        self.assertEqual(picked(snap), ["one"])
        self.assertEqual([any(has_class(c, "rec") for c in o["children"]) for o in opts],
                         [False, True])

    def test_a_tracker_chosen_option_is_pressed_and_keeps_its_words(self) -> None:
        (snap,) = render([START, {"frame": frame([self.three("sqlite")])}, {"snapshot": True}])
        opts = self.options(snap)
        self.assertEqual([o["pressed"] for o in opts], ["true", "false", "false"])
        (ot,) = [c for c in opts[0]["children"] if has_class(c, "ot")]
        self.assertEqual(full(ot), "chosen: sqlite")
        self.assertEqual([any(has_class(c, "rec") for c in o["children"]) for o in opts],
                         [False, True, False])

    def test_option_rows_fill_the_width_and_mark_the_pick_beyond_colour(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        rules = []
        for body in re.findall(r"(?s)<style>(.*?)</style>", text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            rules += [(" ".join(sel.split()), rule)
                      for sel, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]
        def declares(selector_test, declaration):
            return any(selector_test(sel) and declaration in rule for sel, rule in rules)
        self.assertTrue(declares(
            lambda sel: any(t.endswith(".opt") for t in re.split(r"[\s,]+", sel)), "width: 100%"))
        self.assertTrue(declares(lambda sel: ".opt.picked kbd" in sel, "background:"))
        for sel, rule in rules:
            if ".opt" in sel:
                self.assertNotIn("var(--peach)", rule, sel)


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
        head = next(n for n in nodes(digest) if has_class(n, "digest-head"))
        self.assertTrue(full(head).startswith("Since you last looked, "))
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
        head = next(n for n in nodes(snap["digest"]) if has_class(n, "digest-head"))
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

    @staticmethod
    def base_rules() -> list:
        text = PAGE.read_text(encoding="utf-8")
        style = text[text.index("<style>"):text.index("</style>")]
        base, at = "", 0
        for found in re.finditer(r"@media [^{]+\{", style):
            if found.start() < at:
                continue
            base += style[at:found.start()]
            depth, at = 1, found.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(style[at], 0)
                at += 1
        base += style[at:]
        return style_rules(base)

    def test_each_digest_line_is_its_age_then_its_sentence(self) -> None:
        frame = with_digest({
            "since": "2026-11-11T08:00:00+00:00", "first_visit": False,
            "recent": [moment("2026-11-11T09:30:00+00:00", "Newest."),
                       moment("2026-11-11T09:00:00+00:00", "Second.")],
            "earlier": [moment("2026-11-11T08:30:00+00:00", "Third.")],
            "omitted": 2,
        })
        (snap,) = render([{"frame": frame}, {"open": "earlier"}, {"snapshot": True}])
        lines = [
            li for ul in nodes(snap["digest"])
            if ul["tag"] == "ul" and ul["cls"] in ("digest", "earlier-list")
            for li in ul["children"]
        ]
        rows = [li for li in lines if not has_class(li, "more-n")]
        for line in rows:
            self.assertEqual([(c["tag"], c["cls"]) for c in line["children"]],
                             [("time", "at"), ("span", "said")])
        said = [c["text"] for li in rows for c in li["children"] if c["cls"] == "said"]
        self.assertEqual(said, ["Newest.", "Second.", "Third."])
        (more,) = [li for li in lines if has_class(li, "more-n")]
        self.assertEqual(text(more).strip(), "and 2 more")
        self.assertEqual(more["children"], [])
        rules = self.base_rules()
        for selector in (".digest li", ".earlier-list li"):
            with self.subTest(selector=selector):
                decls = {}
                for s, d in rules:
                    if s == selector:
                        decls.update(d)
                self.assertEqual(decls.get("display"), "grid")
                self.assertEqual(decls.get("grid-template-columns"), "5.5rem minmax(0, 1fr)")
                self.assertNotIn("flex-wrap", decls)
        (tail,) = [d for s, d in rules if s == ".earlier-list .more-n"]
        self.assertEqual(tail.get("display"), "block")
        self.assertNotIn("grid-column", tail)

    def test_section_headings_share_one_style(self) -> None:
        frame = {
            **view([project(0, [])]),
            "digest": {"since": None, "first_visit": True,
                       "recent": [moment("2026-11-11T09:30:00+00:00", "Newest.")],
                       "earlier": [], "omitted": 0},
            "capacity": capacity([profile("a", "out", out_until="2026-11-13T09:30:00+00:00")],
                                 all_out=True, resumes_at="2026-11-13T09:30:00+00:00"),
        }
        (snap,) = render([START, {"frame": frame}, {"snapshot": True}])
        for section in ("digest", "promoted", "projects"):
            with self.subTest(section=section):
                (head,) = [n for n in nodes(snap[section]) if n["tag"] == "h2"]
                self.assertTrue(has_class(head, "sec-h"))
        rules = self.base_rules()
        (shared,) = [d for s, d in rules if s == ".sec-h"]
        self.assertEqual(shared.get("font"), "600 .9375rem/1.4 var(--ui)")
        self.assertEqual(shared.get("color"), "var(--text)")
        for selector, decls in rules:
            if selector in (".digest-head", ".side h2", "#promoted h2"):
                for name in ("font", "font-size", "font-weight", "color"):
                    self.assertNotIn(name, decls, selector)


GOAL_FRAME = {**view([]), "recent_projects": ["owner/zeta", "owner/alpha", "owner/beta"]}
GOAL_TEXT = "make the importer resumable"
GOAL_HEADERS = {"X-Console-Token": TOKEN, "Content-Type": "application/json"}
SPRINT = {
    "type": "sprint", "sprint_id": "a" * 16, "goal": GOAL_TEXT, "state": "drafting",
    "state_text": "drafting the brief", "stated_at": "2026-11-12T10:00:00+00:00",
    "age_text": "stated 3 min ago", "manager_text": "no manager has picked this up",
    "manager_state": "none", "manager_until": None, "retry": False, "sessions": [],
}


REPORTED = {
    **SPRINT, "state": "on_track", "state_text": "on track", "manager_text": None,
    "progress": {"landed": 3, "in_delivery": 2, "queued": 2, "held": 0, "total": 7},
    "progress_text": "3 of 7 landed, 2 in delivery, 2 queued",
    "status": "two slices are building", "status_at": utc(4 * 60000),
    "next": "start the resume slice", "milestone": "Importer resumes",
    "tracker_url": "https://github.com/owner/p00/milestone/3",
    "issues": [
        {"issue": 12, "stage": "building", "stage_text": "building task 2 of 4"},
        {"issue": 13, "stage": "landed", "stage_text": "landed"},
    ],
    "waiting": 0,
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
    def test_the_goal_field_sits_in_the_top_bar(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        header = html[html.index('<header class="top">'):html.index("</header>")]
        main = html[html.index("<main>"):html.index("</main>")]
        (snap,) = render([START, {"frame": GOAL_FRAME}, {"snapshot": True}])
        self.assertIn('id="goal"', header)
        self.assertNotIn('id="goal"', main)
        self.assertNotIn("goal-open", html)
        self.assertNotIn("State a goal", html)
        (field,) = goal_named(snap, "goal-text")
        self.assertEqual(field["tag"], "textarea")
        self.assertEqual(field["placeholder"], "Tell a manager what you want next\u2026")
        self.assertEqual([full(n) for n in nodes(snap["goal"]) if n["tag"] == "kbd"], ["g"])
        self.assertFalse(box_open(snap))

    def test_g_opens_the_goal_field_and_filters_projects_most_recent_first(self) -> None:
        closed, opened, upper, one = render([
            START, {"frame": GOAL_FRAME}, {"snapshot": True}, {"key": "g"}, {"snapshot": True},
            {"input": {"cls": "goal-filter", "value": "TA"}}, {"snapshot": True},
            {"input": {"cls": "goal-filter", "value": "alpha"}}, {"snapshot": True},
        ])
        self.assertFalse(box_open(closed))
        self.assertEqual(len(goal_named(closed, "goal-text")), 1)
        self.assertTrue(box_open(opened))
        self.assertEqual(goal_names(opened), ["owner/zeta", "owner/alpha", "owner/beta"])
        self.assertEqual(goal_picked(opened), ["owner/zeta"])
        self.assertEqual(opened["active"], "goal-text")
        self.assertIs(opened["key_prevented"], True)
        (filter_node,) = goal_named(opened, "goal-filter")
        self.assertIn(filter_node["value"], ("", None))
        self.assertEqual(goal_names(upper), ["owner/zeta", "owner/beta"])
        self.assertEqual(goal_names(one), ["owner/alpha"])
        self.assertEqual(goal_picked(one), ["owner/alpha"])

    def test_focusing_the_goal_field_opens_the_project_choice(self) -> None:
        opened, closed = render([
            START, {"frame": GOAL_FRAME}, {"focus_on": "goal-text"}, {"snapshot": True},
            {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertTrue(box_open(opened))
        self.assertEqual(goal_names(opened), ["owner/zeta", "owner/alpha", "owner/beta"])
        self.assertEqual(opened["active"], "goal-text")
        self.assertFalse(box_open(closed))
        self.assertIsNone(closed["active"])
        self.assertEqual(len(goal_named(closed, "goal-text")), 1)

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
        (field,) = goal_named(snap, "goal-text")
        self.assertEqual(field["value"], "")

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

    def test_editing_after_a_refused_goal_removes_the_refusal(self) -> None:
        refused_reply = {"respond": {"status": 409, "text": "write the goal first\n"}}
        refused_steps = [
            START, {"frame": GOAL_FRAME}, {"key": "g"}, refused_reply,
            {"click": "goal-send"}, {"snapshot": True},
        ]
        for edit in (
            {"input": {"cls": "goal-text", "value": GOAL_TEXT}},
            {"input": {"cls": "goal-filter", "value": "a"}},
        ):
            with self.subTest(edit=edit):
                refused, edited = render([*refused_steps, edit, {"snapshot": True}])
                self.assertEqual(goal_fail(refused), ["Could not send: write the goal first"])
                self.assertEqual(goal_fail(edited), [])
                self.assertTrue(box_open(edited))
                self.assertEqual(len(goals(edited)), 1)
        with self.subTest(edit="project"):
            alpha_refused_steps = [
                START, {"frame": GOAL_FRAME}, {"key": "g"},
                {"input": {"cls": "goal-filter", "value": "alpha"}},
                {"click": "goal-project"},
                {"input": {"cls": "goal-filter", "value": ""}},
                refused_reply, {"click": "goal-send"}, {"snapshot": True},
            ]
            refused, edited = render([*alpha_refused_steps, {"click": "goal-project"}, {"snapshot": True}])
            self.assertEqual(goal_names(refused), ["owner/zeta", "owner/alpha", "owner/beta"])
            self.assertEqual(goal_picked(refused), ["owner/alpha"])
            self.assertEqual(goal_fail(refused), ["Could not send: write the goal first"])
            self.assertEqual(json.loads(goals(refused)[0]["body"])["project_id"], "owner/alpha")
            self.assertEqual(goal_picked(edited), ["owner/zeta"])
            self.assertEqual(goal_fail(edited), [])
            self.assertTrue(box_open(edited))
            self.assertEqual(len(goals(edited)), 1)
        with self.subTest(edit="a frame"):
            _, framed = render([*refused_steps, {"frame": GOAL_FRAME}, {"snapshot": True}])
            self.assertEqual(goal_fail(framed), ["Could not send: write the goal first"])
        with self.subTest(edit="a local refusal"):
            first, second = render([
                START, {"frame": GOAL_FRAME}, {"key": "g"},
                {"input": {"cls": "goal-filter", "value": "nomatch"}},
                {"click": "goal-send"}, {"snapshot": True},
                {"input": {"cls": "goal-filter", "value": ""}}, {"snapshot": True},
            ])
            self.assertEqual(goal_fail(first), ["Could not send: choose a project"])
            self.assertEqual(goal_fail(second), [])
            self.assertEqual(goals(first), [])
            self.assertEqual(goals(second), [])
        with self.subTest(edit="refused again"):
            (*_, last) = render([
                *refused_steps, {"input": {"cls": "goal-text", "value": "  "}},
                refused_reply, {"click": "goal-send"}, {"snapshot": True},
            ])
            self.assertEqual(goal_fail(last), ["Could not send: write the goal first"])
            self.assertEqual(len(goals(last)), 2)

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
        self.assertIsNone(closed["active"])
        self.assertEqual(len(goal_named(closed, "goal-text")), 1)
        (text_node,) = goal_named(reopened, "goal-text")
        self.assertEqual(text_node["value"], "draft")

    def test_a_sprint_line_reads_its_goal_state_age_and_the_honest_line(self) -> None:
        (snap, bare) = render([
            {"start": {"focused": False, "clock": 1794477780000}},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
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


TELL_TEXT = "leave the importer's schema alone"
REPLY_TEXT = "kept the schema; moved the change to the reader"


def message_entry(mid: int, kind: str, state: str, **extra: object) -> dict:
    return {
        "id": mid, "kind": kind, "version": 2 if kind != "text" else None,
        "text": TELL_TEXT if kind == "text" else None, "at": "2026-11-12T10:05:00+00:00",
        "state": state, "state_text": state, "read_at": None, "reply": None, "reply_at": None,
        **extra,
    }


def tell_field(snap: dict) -> dict:
    (found,) = [n for n in nodes(snap["projects"]) if has_class(n, "tell")]
    return found


class PageMessageTest(unittest.TestCase):
    def messages(self) -> list:
        return [
            message_entry(3, "text", "sent"),
            message_entry(4, "approved", "delivered"),
            message_entry(5, "text", "read", text="a third note", reply=REPLY_TEXT,
                          reply_at="2026-11-12T10:07:00+00:00"),
        ]

    def test_a_sprint_line_shows_each_message_with_its_state_and_the_reply_under_it(self) -> None:
        (snap,) = render([
            START,
            {"frame": with_sprints([{**SPRINT, "messages": self.messages(), "reach_text": None}])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        shown = full(line)
        for expected in (TELL_TEXT, "Approved version 2", "a third note", "sent", "delivered",
                         "read", "Manager: " + REPLY_TEXT):
            self.assertIn(expected, shown)
        states = [n for n in nodes(line) if has_class(n, "message-state")]
        self.assertEqual([full(n) for n in states], ["sent", "delivered", "read"])
        (reply,) = [n for n in nodes(line) if has_class(n, "message-reply")]
        self.assertEqual(full(reply), "Manager: " + REPLY_TEXT)
        third = [n for n in nodes(line) if n["tag"] == "li" and "a third note" in full(n)][-1]
        self.assertIn("Manager: " + REPLY_TEXT, full(third))
        self.assertEqual(
            [n for n in nodes(line) if has_class(n, "unreachable")], [])

    def test_a_change_request_reads_its_version_and_text(self) -> None:
        asked = message_entry(3, "changes", "sent", version=1, text="smaller slices")
        (snap,) = render([
            START, {"frame": with_sprints([{**SPRINT, "messages": [asked], "reach_text": None}])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertIn("Asked for changes to version 1: smaller slices", full(line))

    def test_two_failed_nudges_read_manager_not_reachable(self) -> None:
        (snap,) = render([
            START,
            {"frame": with_sprints([{
                **SPRINT, "messages": self.messages(), "reach_text": "manager not reachable",
                "retry": False}])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        (reach,) = [n for n in nodes(line) if has_class(n, "unreachable")]
        self.assertEqual(full(reach), "manager not reachable")
        self.assertIn(TELL_TEXT, full(line))
        self.assertEqual([n for n in nodes(line) if has_class(n, "retry")], [])

    def test_tell_the_manager_posts_the_text_with_the_token_and_keeps_it_on_refusal(self) -> None:
        refused, after = render([
            START, {"frame": with_sprints([SPRINT])},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"respond": {"status": 409, "text": "this sprint is not open\n"}},
            {"click": "tell-send"}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(refused)
        self.assertIn("Tell the manager", full(line))
        (post,) = [p for p in refused["posts"] if p["url"] == "/api/message"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]), {
            "project_id": "owner/p00", "sprint_id": "a" * 16, "text": TELL_TEXT})
        self.assertEqual([full(n) for n in nodes(line) if has_class(n, "fail")],
                         ["Could not send: this sprint is not open"])
        self.assertEqual(tell_field(refused)["value"], TELL_TEXT)
        self.assertEqual(tell_field(after)["value"], TELL_TEXT)

    def test_an_unanswered_send_keeps_the_text(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([SPRINT])},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"fail_fetch": True}, {"click": "tell-send"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual([full(n) for n in nodes(line) if has_class(n, "fail")],
                         ["Could not send: the console did not answer"])
        self.assertEqual(tell_field(snap)["value"], TELL_TEXT)

    def test_a_sent_message_clears_the_field(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([SPRINT])},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"click": "tell-send"}, {"snapshot": True},
        ])
        self.assertEqual(tell_field(snap)["value"], "")
        (line,) = sprint_lines(snap)
        self.assertEqual([n for n in nodes(line) if has_class(n, "fail")], [])

    def test_a_typed_message_keeps_its_focus_and_selection_across_frames(self) -> None:
        sent = message_entry(3, "text", "delivered")
        before, after, more = render([
            START, {"frame": with_sprints([SPRINT])},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"select": {"cls": "tell", "start": 6, "end": 9}}, {"snapshot": True},
            {"frame": with_sprints([{**SPRINT, "messages": [sent], "reach_text": None}])},
            {"snapshot": True},
            {"append": {"class": "tell", "text": "!"}}, {"snapshot": True},
        ])
        self.assertTrue(tell_field(before)["focused"])
        field = tell_field(after)
        self.assertEqual(field["value"], TELL_TEXT)
        self.assertTrue(field["focused"])
        self.assertEqual(field["selection"], [6, 9])
        self.assertEqual(after["active"], "tell")
        self.assertTrue(tell_field(more)["value"].endswith("!"))

    def test_a_sprint_no_longer_listed_restores_no_focus(self) -> None:
        (gone,) = render([
            START, {"frame": with_sprints([SPRINT])},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"frame": with_sprints([])}, {"snapshot": True},
        ])
        self.assertIsNone(gone["active"])


class PageManagerTest(unittest.TestCase):
    def test_a_failed_manager_shows_its_reason_and_retry_posts(self) -> None:
        reason = "could not start a manager: the directory is not trusted"
        (snap,) = render([
            START,
            {"frame": with_sprints([
                {**SPRINT, "manager_state": "failed", "manager_text": reason, "retry": True}
            ])},
            {"respond": {"status": 409, "text": "this sprint has a manager\n"}},
            {"click": "retry"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertIn(reason, full(line))
        self.assertEqual(
            len([n for n in nodes(line) if n["tag"] == "button" and has_class(n, "retry")]), 1
        )
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/retry-manager"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(
            json.loads(post["body"]), {"project_id": "owner/p00", "sprint_id": "a" * 16}
        )
        self.assertEqual(
            [full(n) for n in nodes(line) if has_class(n, "fail")],
            ["Could not retry: this sprint has a manager"],
        )

    def test_a_refused_retry_message_goes_once_the_manager_has_started(self) -> None:
        failed, started, missing_again, gone, back = render([
            START,
            {"frame": with_sprints([{
                **SPRINT, "manager_state": "missing",
                "manager_text": "the manager is not running", "retry": True,
            }])},
            {"respond": {"status": 409, "text": "this sprint has a manager\n"}},
            {"click": "retry"}, {"snapshot": True},
            {"frame": with_sprints([
                {**SPRINT, "manager_state": "started", "manager_text": None, "retry": False}
            ])},
            {"snapshot": True},
            {"frame": with_sprints([{
                **SPRINT, "manager_state": "missing",
                "manager_text": "the manager is not running", "retry": True,
            }])},
            {"snapshot": True},
            {"frame": with_sprints([])},
            {"snapshot": True},
            {"frame": with_sprints([{
                **SPRINT, "manager_state": "missing",
                "manager_text": "the manager is not running", "retry": True,
            }])},
            {"snapshot": True},
        ])

        def fails(snap: dict) -> list:
            (line,) = sprint_lines(snap)
            return [full(n) for n in nodes(line) if has_class(n, "fail")]

        self.assertEqual(fails(failed), ["Could not retry: this sprint has a manager"])
        self.assertEqual(fails(started), [])
        self.assertEqual(fails(missing_again), [])
        self.assertEqual(sprint_lines(gone), [])
        self.assertEqual(fails(back), [])

    def test_a_sprint_without_retry_has_no_retry_button(self) -> None:
        started, unavailable = render([
            START,
            {"frame": with_sprints([{**SPRINT, "manager_state": "started", "manager_text": None}])},
            {"snapshot": True},
            {"frame": with_sprints([{
                **SPRINT, "manager_state": "unavailable", "retry": False,
                "manager_text": "managers are not available on this host yet",
            }])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(started)
        self.assertEqual([n for n in nodes(line) if has_class(n, "retry")], [])
        self.assertEqual([n for n in nodes(line) if has_class(n, "manager")], [])
        (line,) = sprint_lines(unavailable)
        self.assertIn("managers are not available on this host yet", full(line))
        self.assertEqual([n for n in nodes(line) if has_class(n, "retry")], [])

    def test_waiting_on_quota_shows_when(self) -> None:
        (snap,) = render([
            START,
            {"frame": with_sprints([{
                **SPRINT, "manager_state": "waiting", "manager_text": "waiting on quota until",
                "manager_until": "2026-11-13T00:00:00+00:00", "retry": True,
            }])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertIn("waiting on quota until", full(line))
        (until,) = [n for n in nodes(line) if has_class(n, "until")]
        self.assertNotEqual(full(until), "")
        self.assertNotIn("Invalid Date", full(until))

    def test_a_manager_session_renders_inside_its_sprint(self) -> None:
        name = "owner/p00 sprint " + "a" * 16
        (snap,) = render([
            START,
            {"frame": with_sprints([{**SPRINT, "sessions": [{
                "session_id": "s1", "name": name, "state": "working", "state_text": "working",
                "cwd": "/srv/p00", "deliveries": [],
            }]}])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        (row,) = [n for n in nodes(line) if n["tag"] == "li" and has_class(n, "sprint-session")]
        self.assertIn(name, full(row))
        self.assertEqual(
            [full(n) for n in nodes(row) if has_class(n, "s-working")], ["working"]
        )


def top(line: dict) -> list:
    """The line's nodes outside the sprint-detail subtree, skipped by position, not by value."""
    flat = [line]
    for child in line["children"]:
        if not (child["tag"] == "details" and has_class(child, "sprint-detail")):
            flat += top(child)
    return flat


def detail_nodes(line: dict) -> list:
    return [n for n in nodes(line) if n["tag"] == "details" and has_class(n, "sprint-detail")]


def detail(line: dict) -> dict:
    (found,) = detail_nodes(line)
    return found


def top_text(line: dict) -> str:
    return " ".join(n["text"] for n in top(line))


class TopHelperTest(unittest.TestCase):
    def test_a_node_copied_from_the_detail_onto_the_line_still_counts_as_top(self) -> None:
        def node(tag: str, cls: str, text: str, children: list | None = None) -> dict:
            return {"tag": tag, "cls": cls, "text": text, "children": children or []}

        issue = node("span", "issue", "#12")
        fold = node("details", "sprint-detail", "", [node("span", "issue", "#12")])
        line = node("li", "sprint", "g", [issue, fold])
        self.assertIsNotNone(re.search(r"#\d", top_text(line)))
        self.assertEqual(top_text(node("li", "sprint", "g", [fold])), "g")


class PageSprintReportTest(unittest.TestCase):
    def test_the_sprint_line_carries_no_issue_number_branch_or_session_until_opened(self) -> None:
        outside = session("feature-s1", "working", "working", [{**RUN, "issues": [
            {"issue": 12, "stage": "building", "stage_text": "building task 2 of 4"}]}])
        frame = view([{**project(0, [outside]), "sprints": [REPORTED]}])
        first, second, third = render([
            START, {"frame": frame}, {"snapshot": True},
            {"open": "sprint:" + "a" * 16}, {"snapshot": True},
            {"frame": frame}, {"snapshot": True},
        ])
        (line,) = sprint_lines(first)
        shown = top_text(line)
        self.assertIsNone(re.search(r"#\d", shown))
        for hidden in ("feature-s1", "wf_a", "issue-12"):
            self.assertNotIn(hidden, shown)
        self.assertFalse(detail(line)["open"])
        for snap in (second, third):
            (opened,) = sprint_lines(snap)
            fold = detail(opened)
            self.assertTrue(fold["open"])
            for expected in ("#12", "building task 2 of 4", "#13", "landed",
                             "Next: start the resume slice", "Milestone: Importer resumes"):
                self.assertIn(expected, full(fold))
            last = fold["children"][-1]
            self.assertEqual((last["tag"], last["cls"], full(last)),
                             ("a", "tracker", "Open on the tracker"))
            self.assertEqual(full(fold["children"][0]), "Detail")

    def test_a_reported_sprint_line_reads_state_progress_status_and_age(self) -> None:
        quiet = {**REPORTED, "state": "quiet", "state_text": "quiet for 16 min — may be stuck"}
        snap, stuck = render([
            {"start": {"focused": False, "clock": NOW_MS}},
            {"frame": with_sprints([REPORTED])}, {"snapshot": True},
            {"frame": with_sprints([quiet])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        for expected in ("on track", "3 of 7", "two slices are building", "4 min ago"):
            self.assertIn(expected, top_text(line))
        self.assertIn("3 of 7 landed, 2 in delivery, 2 queued", full(detail(line)))
        (line,) = sprint_lines(stuck)
        self.assertIn("quiet for 16 min — may be stuck", top_text(line))
        self.assertNotIn("stalled", top_text(line).lower())

    def test_the_report_age_is_a_time_element_that_follows_the_page_clock(self) -> None:
        before, after = render([
            {"start": {"focused": False, "clock": NOW_MS}},
            {"frame": with_sprints([REPORTED])}, {"snapshot": True},
            {"clock": NOW_MS + 3 * 3600 * 1000}, {"snapshot": True},
        ])
        (line,) = sprint_lines(before)
        (shown,) = [n for n in nodes(line) if n["tag"] == "time" and n["text"] == "4 min ago"]
        self.assertEqual(shown["title"], "2026-11-11 11:56")
        (line,) = sprint_lines(after)
        self.assertIn("3 h ago", top_text(line))

    def test_a_non_https_tracker_url_draws_no_link(self) -> None:
        bad = {**REPORTED, "tracker_url": "javascript:alert(1)"}
        (snap,) = render([START, {"frame": with_sprints([bad])}, {"snapshot": True}])
        (line,) = sprint_lines(snap)
        self.assertEqual([n for n in nodes(detail(line)) if n["tag"] == "a"], [])

    def test_a_sprint_without_a_report_has_no_detail(self) -> None:
        (snap,) = render([START, {"frame": with_sprints([SPRINT])}, {"snapshot": True}])
        (line,) = sprint_lines(snap)
        self.assertEqual(detail_nodes(line), [])
        for cls in ("sprint-detail", "progress", "status"):
            self.assertEqual([n for n in nodes(line) if has_class(n, cls)], [])


class PageSprintGlanceTest(unittest.TestCase):
    def test_a_reported_sprint_shows_one_pip_per_issue_by_stage_group(self) -> None:
        staged = {**REPORTED,
                  "progress": {"landed": 1, "in_delivery": 2, "queued": 1, "held": 1, "total": 5},
                  "progress_text": "1 of 5 landed, 2 in delivery, 1 queued, 1 held",
                  "issues": [
                      {"issue": 11, "stage": "landed", "stage_text": "landed"},
                      {"issue": 12, "stage": "building", "stage_text": "building task 2 of 4"},
                      {"issue": 13, "stage": "held", "stage_text": "held"},
                      {"issue": 14, "stage": "queued", "stage_text": "queued"},
                      {"issue": 15, "stage": "closed out", "stage_text": "closed out"}]}
        empty = {**REPORTED,
                 "progress": {"landed": 0, "in_delivery": 0, "queued": 0, "held": 0, "total": 0},
                 "progress_text": "0 of 0 landed", "issues": []}
        first, second, third = render([
            START, {"frame": with_sprints([staged])}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"frame": with_sprints([empty])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(first)
        (pips,) = [n for n in top(line) if has_class(n, "pips")]
        self.assertEqual([c["cls"] for c in pips["children"]],
                         ["pip pip-landed", "pip pip-delivery", "pip pip-held", "pip pip-queued",
                          "pip pip-delivery"])
        self.assertEqual(pips["title"], staged["progress_text"])
        self.assertEqual([full(n) for n in top(line) if has_class(n, "pip-count")], ["1 of 5"])
        (mark,) = [n for n in top(line) if has_class(n, "sic")]
        self.assertEqual([c["tag"] for c in mark["children"]], ["svg"])
        self.assertIn("1 of 5 landed, 2 in delivery, 1 queued, 1 held", full(detail(line)))
        for snap in (second, third):
            (line,) = sprint_lines(snap)
            for cls in ("pips", "pip", "pip-count"):
                self.assertEqual([n for n in nodes(line) if has_class(n, cls)], [])
            self.assertEqual(len([n for n in nodes(line) if has_class(n, "sic")]), 1)

    def test_pip_marks_differ_beyond_colour(self) -> None:
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        normalised = []
        for group in ("landed", "delivery", "held", "queued"):
            found = [d for selector, d in rules if selector == ".pip.pip-" + group]
            self.assertEqual(len(found), 1, group)
            normalised.append({k: re.sub(r"var\(--[\w-]+\)|#[0-9a-fA-F]{3,8}", "C", v)
                               for k, v in found[0].items()})
        for i, left in enumerate(normalised):
            for right in normalised[i + 1:]:
                self.assertNotEqual(left, right)
        for selector, decls in rules:
            if ".pip" in selector:
                for value in decls.values():
                    self.assertNotIn("var(--peach)", value)

    def test_only_a_sprint_waiting_on_the_owner_reads_as_needs_you(self) -> None:
        cases = [
            ("drafting", "drafting the brief", "none", "sic-lines", "st-dim"),
            ("starting", "starting", "started", "sic-play", "st-go"),
            ("on_track", "on track", "started", "sic-play", "st-go"),
            ("waiting", "waiting on you (2)", "started", "sic-pause", "needs"),
            ("quiet", "quiet for 16 min — may be stuck", "started", "sic-dashed", "st-wait"),
            ("closing", "closing", "started", "sic-closing", "st-go"),
            ("done", "done", "started", "sic-tick", "st-dim"),
            ("drafting", "drafting the brief", "waiting", "sic-clock", "st-wait"),
        ]
        sprints = [{**REPORTED, "state": s, "state_text": t, "manager_state": m,
                    "manager_text": None if m != "waiting" else "waiting on quota until",
                    "manager_until": None if m != "waiting" else "2026-11-13T00:00:00+00:00"}
                   for s, t, m, _, _ in cases]
        steps = [START]
        for sprint in sprints:
            steps += [{"frame": with_sprints([sprint])}, {"snapshot": True}]
        snaps = render(steps)
        for (s, t, m, icon_class, tone), snap in zip(cases, snaps):
            with self.subTest(state=s, manager=m):
                (line,) = sprint_lines(snap)
                (words,) = [n for n in top(line) if has_class(n, "sprint-state")]
                self.assertEqual(full(words), t)
                self.assertIs(has_class(words, "needs"), s == "waiting")
                self.assertTrue(has_class(words, tone))
                (mark,) = [n for n in top(line) if has_class(n, "sic")]
                self.assertTrue(has_class(mark, icon_class))
                self.assertTrue(has_class(mark, tone))
                self.assertIs(has_class(mark, "needs"), s == "waiting")
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        for marker, colour in ((".sprint-state.needs", "var(--peach)"), (".st-go", "var(--green)"),
                               (".st-wait", "var(--yellow)"), (".st-dim", "var(--ov2)")):
            self.assertTrue(any(marker in selector and decls.get("color") == colour
                                for selector, decls in rules), marker)

    def test_a_manager_session_reads_as_words_until_the_detail_opens(self) -> None:
        name = "owner/p00 sprint " + "a" * 16
        managed = {**SPRINT, "sessions": [{"session_id": "s1", "name": name, "state": "working",
                                            "state_text": "working", "cwd": "/srv/p00",
                                            "deliveries": []}]}
        idle = {**managed, "sessions": [{**managed["sessions"][0], "state": "idle",
                                         "state_text": "idle"}]}
        closed, opened, later = render([
            START, {"frame": with_sprints([managed])}, {"snapshot": True},
            {"open": "sprint:" + "a" * 16}, {"snapshot": True},
            {"frame": with_sprints([idle])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(closed)
        self.assertNotIn(name, visible_text(line))
        self.assertNotIn("/srv", visible_text(line))
        words = [n for n in top(line) if has_class(n, "manager-now")]
        self.assertEqual([full(n) for n in words], ["manager working"])
        self.assertTrue(has_class(words[0], "s-working"))
        self.assertFalse(detail(line)["open"])
        (line,) = sprint_lines(opened)
        self.assertIn(name, visible_text(line))
        (row,) = [n for n in nodes(detail(line)) if has_class(n, "sprint-session")]
        self.assertIn(name, full(row))
        (line,) = sprint_lines(later)
        self.assertTrue(detail(line)["open"])
        self.assertEqual([full(n) for n in top(line) if has_class(n, "manager-now")],
                         ["manager idle"])

    def test_a_full_report_keeps_every_pip_and_wraps_them(self) -> None:
        full_report = {
            **REPORTED,
            "progress": {"landed": 0, "in_delivery": 0, "queued": MAX_REPORT_ISSUES, "held": 0,
                         "total": MAX_REPORT_ISSUES},
            "progress_text": f"0 of {MAX_REPORT_ISSUES} landed, {MAX_REPORT_ISSUES} queued",
            "issues": [{"issue": n, "stage": "queued", "stage_text": "queued"}
                       for n in range(1, MAX_REPORT_ISSUES + 1)]}
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        (snap,) = render([START, {"frame": with_sprints([full_report])}, {"snapshot": True}])
        (line,) = sprint_lines(snap)
        (pips,) = [n for n in top(line) if has_class(n, "pips")]
        self.assertEqual(len([c for c in pips["children"] if has_class(c, "pip")]),
                         MAX_REPORT_ISSUES)
        self.assertEqual([full(n) for n in top(line) if has_class(n, "pip-count")],
                         [f"0 of {MAX_REPORT_ISSUES}"])
        self.assertTrue(any(s == ".pips" and d.get("flex-wrap") == "wrap" for s, d in rules))
        for selector, decls in rules:
            if selector in (".sp-prog", ".pips"):
                self.assertNotEqual(decls.get("white-space"), "nowrap", selector)
        grids = [d["grid-template-columns"] for s, d in rules
                 if s == ".sp-head" and "grid-template-columns" in d]
        self.assertGreaterEqual(len(grids), 1)
        for value in grids:
            found = re.match(r"^16px minmax\(0, 1fr\) fit-content\((\d+)%\)$", value)
            self.assertIsNotNone(found, value)
            self.assertLessEqual(int(found.group(1)), 50)

    def test_an_unknown_sprint_state_fails_loud(self) -> None:
        for state, manager in (("bogus", "started"), ("constructor", "started"),
                               ("bogus", "waiting")):
            sprint = {**REPORTED, "state": state, "state_text": state, "manager_state": manager}
            with self.subTest(state=state, manager=manager):
                with self.assertRaisesRegex(AssertionError, "unknown sprint state"):
                    render([START, {"frame": with_sprints([sprint])}])


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


NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def digest_of(events: list) -> dict:
    return console_digest.digest(console_digest.moments(events, {}, {}), None, NOW)


def glance_events() -> list:
    def at(minute: int) -> str:
        return f"2026-11-11T10:{minute:02d}:00.000000+00:00"

    def asked(text: str) -> dict:
        return {"question": text, "options": ["a", "b"], "chosen": None, "recommended": None}

    def inbox(issue: int, text: str, answered: bool) -> dict:
        return {"key": f"k{issue}", "project_id": "owner/p00", "issue": issue,
                "reason": "decision", "question": BOILER, "questions": [asked(text)],
                "answered": answered}

    def seen(seq: int, project, sid: str, repo: str, name: str) -> Event:
        return Event(seq, at(seq), "session.seen", project,
                     {"session_id": sid, "cwd": repo, "repo": repo, "state": "working",
                      "name": name})

    def stopped(seq: int, project, sid: str, repo: str) -> Event:
        return Event(seq, at(seq), "session.hook", project,
                     {"event": "StopFailure", "session_id": sid, "cwd": repo, "repo": repo,
                      "error": "rate_limit"})

    return [
        Event(1, at(1), "inbox.seen", "owner/p00", inbox(7, "Which database?", False)),
        Event(2, at(2), "inbox.seen", "owner/p00", inbox(8, "Merge it?", False)),
        Event(3, at(3), "inbox.changed", "owner/p00", inbox(8, "Merge it?", True)),
        seen(4, "owner/p00", "aaaaaaaa-1111", "/srv/p00", "fixer-session"),
        stopped(5, "owner/p00", "aaaaaaaa-1111", "/srv/p00"),
        seen(6, None, "cccccccc-3333", "/srv/elsewhere", "stray-session"),
        stopped(7, None, "cccccccc-3333", "/srv/elsewhere"),
        Event(8, at(8), "session.gone", None, {"session_id": "cccccccc-3333"}),
    ]


def glance_sample() -> dict:
    ran = {**RUN, "summary": "2 issues in delivery: 1 building, 1 plan review, moved 3 min ago"}
    worker = {**session("fixer-session", "working", "working", deliveries=[ran]),
              "cwd": "/srv/p00/.worktrees/fix"}
    entry = project(0, [worker])
    entry["outside_sprints"]["summary"] = "1 working"
    entry["sprints"] = [{**REPORTED, "sessions": [
        {"session_id": "dddddddd-4444", "name": "manager-session", "state": "working",
         "state_text": "working", "cwd": "/srv/p00", "deliveries": []}]}]
    quiet = {"type": "quiet_group", "label": "4 quiet projects", "count": 4,
             "projects": [project(n, [], quiet=True) for n in range(2, 6)]}
    stray = {**unmanaged_entry([session("stray-session", "idle", "idle")]), "name": "elsewhere"}
    asking = item("A", issue=7, headline="Which database?",
                  questions=[q("Which database?", ["sqlite", "postgres"])])
    approval = check_item("P", "approval", issue=12, headline="Approve the live check?",
                          detail="nix-build /srv/p00/checks/live.nix")
    conflict = item("C", issue=9, reason="conflict", headline="Landing stopped on a merge conflict.",
                    items=["the branch conflicts with main"])
    answered = item("Z", issue=8, answered=True, headline="Merge it?",
                    answered_at="2026-11-11T11:00:00+00:00")
    profiles = [profile("a", "ok", week_left=62, next_reset="2026-11-12T09:00:00+00:00"),
                profile("b", "unknown")]
    return {
        **view([entry, quiet], [stray], count=6),
        "inbox": {"open": [asking, approval, conflict], "answered": [answered]},
        "digest": digest_of(glance_events()),
        "capacity": capacity(profiles, no_reading="1 with no reading yet"),
    }


class PageGlanceTest(unittest.TestCase):
    def test_with_every_line_closed_no_path_session_name_or_issue_number_shows(self) -> None:
        sample = glance_sample()
        self.assertEqual(len(sample["digest"]["recent"]) + len(sample["digest"]["earlier"]), 6)
        closed, opened = render([
            START, {"frame": sample}, {"snapshot": True},
            {"open": "line:owner/p00"}, {"open": "sprint:" + "a" * 16}, {"snapshot": True},
        ])
        sections = ("statement", "inbox", "projects", "unmanaged", "digest", "capacity",
                    "promoted", "goal")
        for name in sections:
            shown = visible_text(closed[name])
            with self.subTest(section=name):
                self.assertNotIn("/srv", shown)
                self.assertIsNone(re.search(r"(^|\s)/[\w.-]+/", shown))
                for leaked in ("fixer-session", "stray-session", "aaaaaaaa", "cccccccc", BOILER,
                               "Delivery waits for the owner", "manager-session", "dddddddd"):
                    self.assertNotIn(leaked, shown)
                self.assertIsNone(re.search(r"#\d", shown))
                self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", shown))
        self.assertIn("elsewhere", visible_text(closed["unmanaged"]))
        self.assertIn("Not yet managed", visible_text(closed["unmanaged"]))
        self.assertIn("A session in elsewhere ended.", visible_text(closed["digest"]))
        self.assertIn("Review and approve", visible_text(closed["inbox"]))
        self.assertIn("manager working", visible_text(closed["projects"]))
        shown = visible_text(opened["projects"])
        for wanted in ("/srv/p00", "fixer-session", "#856", "manager-session"):
            self.assertIn(wanted, shown)

    def test_a_project_line_is_its_name_and_its_run_sentences(self) -> None:
        ran = {**RUN, "summary": "2 issues in delivery: 1 building, 1 plan review, moved 3 min ago"}
        entry = project(0, [session("s1", "working", "working", deliveries=[ran])])
        entry["outside_sprints"]["summary"] = "1 working"
        (snap,) = render([{"start": {"focused": False, "clock": NOW_MS}},
                          {"frame": view([entry])}, {"snapshot": True}])
        (fold,) = [n for n in nodes(snap["projects"]) if n["key"] == "line:owner/p00"]
        self.assertFalse(fold["open"])
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(
            [full(c) for c in summary["children"] if full(c)],
            ["owner/p00", "1 working",
             "2 issues in delivery: 1 building, 1 plan review, moved 3 min ago"],
        )
        self.assertEqual(len([n for n in nodes(summary) if has_class(n, "run-sum")]), 1)


class PageSideColumnTest(unittest.TestCase):
    def test_the_work_heading_counts_sprints_and_their_projects(self) -> None:
        none = view([project(0, []), project(1, [], quiet=True, ago=timedelta(days=3))])
        one = with_sprints([SPRINT])
        several = view([
            {**project(0, []), "sprints": [SPRINT, {**REPORTED, "sprint_id": "b" * 16}]},
            {**project(1, []), "sprints": [{**SPRINT, "sprint_id": "c" * 16}]},
            project(2, [], quiet=True, ago=timedelta(days=3)),
        ])
        snaps = render([
            START, {"frame": none}, {"snapshot": True}, {"frame": one}, {"snapshot": True},
            {"frame": several}, {"snapshot": True},
        ])
        counts = []
        for snap in snaps:
            (h2,) = [n for n in nodes(snap["projects"]) if n["tag"] == "h2"]
            self.assertEqual(h2["text"], "Work")
            counts.append([full(c) for c in h2["children"]])
        self.assertEqual(counts, [[], ["1 sprint across 1 project"], ["3 sprints across 2 projects"]])

    def test_give_it_a_goal_opens_the_goal_field_with_that_project_chosen(self) -> None:
        frame = {
            **view([project(1, [], quiet=True, ago=timedelta(days=3)),
                    project(2, [], quiet=True, ago=timedelta(days=5))]),
            "recent_projects": ["owner/p02", "owner/p01"],
        }
        before, opened, sent = render([
            START, {"frame": frame}, {"snapshot": True}, {"click": "give-goal"}, {"snapshot": True},
            {"input": {"cls": "goal-text", "value": GOAL_TEXT}}, {"click": "goal-send"},
            {"snapshot": True},
        ])
        self.assertFalse(box_open(before))
        self.assertEqual(
            [(n["tag"], full(n)) for n in nodes(before["projects"]) if has_class(n, "give-goal")],
            [("button", "Give it a goal")] * 2,
        )
        for n in nodes(before["projects"]):
            if n["tag"] == "summary":
                self.assertEqual([m for m in nodes(n) if has_class(m, "give-goal")], [])
        self.assertTrue(box_open(opened))
        self.assertEqual(goal_picked(opened), ["owner/p01"])
        self.assertEqual(opened["active"], "goal-text")
        (post,) = goals(sent)
        self.assertEqual(json.loads(post["body"]), {"project_id": "owner/p01", "goal": GOAL_TEXT})
        self.assertEqual(post["headers"], GOAL_HEADERS)

    def test_give_it_a_goal_keeps_the_typed_goal_and_clears_the_filter(self) -> None:
        frame = {
            **view([project(1, [], quiet=True, ago=timedelta(days=3)),
                    project(2, [], quiet=True, ago=timedelta(days=5))]),
            "recent_projects": ["owner/p02", "owner/p01"],
        }
        (snap,) = render([
            START, {"frame": frame}, {"key": "g"},
            {"input": {"cls": "goal-filter", "value": "p02"}},
            {"input": {"cls": "goal-text", "value": "draft"}},
            {"click": "give-goal"}, {"snapshot": True},
        ])
        self.assertEqual(goal_picked(snap), ["owner/p01"])
        (f,) = goal_named(snap, "goal-filter")
        self.assertEqual(f["value"], "")
        (t,) = goal_named(snap, "goal-text")
        self.assertEqual(t["value"], "draft")
        self.assertEqual(snap["active"], "goal-text")

    def test_every_quiet_project_offers_a_goal_even_when_folded(self) -> None:
        group = {"type": "quiet_group", "label": "4 quiet projects", "count": 4,
                 "projects": [project(n, [], quiet=True) for n in range(2, 6)]}
        frame = view([{**project(0, []), "sprints": [SPRINT]}, group], count=5)
        (snap,) = render([START, {"frame": frame}, {"snapshot": True}])
        buttons = [n for n in nodes(snap["projects"]) if has_class(n, "give-goal")]
        self.assertEqual(len(buttons), 4)
        (folded,) = [n for n in nodes(snap["projects"]) if n["key"] == "quiet"]
        self.assertEqual([n for n in nodes(folded) if has_class(n, "give-goal")], buttons)
        (busy,) = [n for n in nodes(snap["projects"])
                   if n["tag"] == "li" and any(m["key"] == "line:owner/p00" for m in nodes(n))]
        self.assertEqual([n for n in nodes(busy) if has_class(n, "give-goal")], [])

    def test_a_project_is_a_block_headed_by_its_name(self) -> None:
        (snap,) = render([START, {"frame": view([project(0, []), project(1, [])])},
                          {"snapshot": True}])
        (fold,) = [n for n in nodes(snap["projects"]) if n["key"] == "line:owner/p00"]
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        name = summary["children"][0]
        self.assertEqual((name["tag"], name["cls"], name["text"]), ("h3", "pname", "owner/p00"))
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        self.assertTrue([d for s, d in rules
                         if s == "#list > li.line + li.line"
                         and "var(--hair)" in d.get("border-top", "")])
        self.assertTrue([d for s, d in rules
                         if s == ".pname" and d.get("font-weight") == "600"])


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
KEY_B = "brief:" + "b" * 16
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

    def test_an_empty_list_part_reads_its_label_and_none(self) -> None:
        empty = {**BRIEF, "brief": {**BRIEF["brief"], "excluded": [], "risks": [], "asks": []}}
        shown, approved = render([
            START, {"frame": frame([empty])}, {"snapshot": True}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True},
        ])
        card = shown["inbox"]["children"][0]
        self.assertTrue(has_class(card, "brief"))

        def after(label: str) -> dict:
            (found,) = [
                (n, i) for n in nodes(card) for i, c in enumerate(n["children"])
                if has_class(c, "meta") and c["text"] == label
            ]
            parent, at = found
            return parent["children"][at + 1]

        for label in ("Excluded", "Risks", "What I expect to ask"):
            with self.subTest(label=label):
                following = after(label)
                self.assertEqual(following["tag"], "p")
                self.assertEqual(full(following), "None")
        slices = after("Slices")
        self.assertEqual(slices["tag"], "ul")
        self.assertEqual([full(li) for li in slices["children"]], ["checkpoint", "resume"])
        self.assertEqual([n for n in nodes(card) if n["tag"] == "ul" and n["children"] == []], [])
        (post,) = approvals(approved)
        self.assertEqual(posted(post), {
            "project_id": "owner/p01", "sprint_id": "a" * 16, "version": 2,
        })

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
        (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "details" and n["key"] == KEY_B]
        self.assertTrue(row["open"])
        self.assertIn(second, nodes(row))
        self.assertEqual(sum(1 for n in nodes(row) if has_class(n, "kind")), 1)
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


def brief_row(snap: dict, key: str = KEY_B) -> dict:
    (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "details" and n["key"] == key]
    return row


def has_any(tree: dict, names: tuple) -> bool:
    return any(has_class(n, name) for n in visible(tree) for name in names)


ROW_BODY = ("parts", "approve", "reply-text", "reply-send")


class PageBriefRowTest(unittest.TestCase):
    def test_the_brief_row_head_keeps_the_shared_flex_layout(self) -> None:
        # The harness applies no CSS: a rule on the summary that is more specific
        # than .row-head must not take its flex row (gap, wait at the right) away.
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        self.assertEqual(
            [d["display"] for s, d in rules if s == ".row-head" and "display" in d], ["flex"])
        for selector, decls in rules:
            if selector == ".brief-row > summary":
                self.assertEqual(decls.get("display", "flex"), "flex", selector)

    def test_a_later_brief_is_one_row_until_opened(self) -> None:
        closed, opened, promoted = render([
            START, {"frame": frame([BRIEF, BRIEF_B, ANSWERABLE])}, {"snapshot": True},
            {"open": KEY_B}, {"snapshot": True},
            {"frame": frame([BRIEF_B])}, {"snapshot": True},
        ])
        kids = closed["inbox"]["children"]
        self.assertEqual(kids[0]["tag"], "article")
        for name in ("card", "brief", "lead"):
            self.assertTrue(has_class(kids[0], name))
        self.assertEqual((kids[1]["tag"], kids[1]["key"]), ("details", KEY_B))
        self.assertTrue(has_class(kids[1], "row") and has_class(kids[1], "brief-row"))
        self.assertFalse(kids[1]["open"])
        self.assertEqual(kids[2]["tag"], "ul")
        self.assertTrue(has_class(kids[2], "rest"))
        row = brief_row(closed)
        self.assertFalse(has_any(row, ROW_BODY))
        summary = row["children"][0]
        self.assertEqual(summary["tag"], "summary")
        self.assertEqual(
            [(c["tag"], c["cls"].split()[0] if c["cls"] else "") for c in summary["children"]],
            [("span", "kind"), ("b", ""), ("span", "lm"), ("span", "lw")])
        texts = [full(c) for c in summary["children"]]
        self.assertEqual(texts[:3], ["Brief", GOAL_TEXT, "owner/p01"])
        self.assertTrue(texts[3].startswith("waiting "))
        self.assertIn("svg", [c["tag"] for c in summary["children"][0]["children"]])

        row = brief_row(opened)
        self.assertTrue(row["open"])
        shown = visible(row)
        self.assertEqual(sum(1 for n in shown if has_class(n, "approve")), 1)
        self.assertEqual(sum(1 for n in shown if has_class(n, "primary")), 0)
        self.assertEqual(sum(1 for n in shown if has_class(n, "reply-text")), 1)
        self.assertEqual(sum(1 for n in shown if has_class(n, "reply-send")), 1)
        text = visible_text(row)
        self.assertIn("owner/p01 brief, version 1", text)
        for label in LABELS:
            self.assertIn(label, text)
        self.assertEqual(sum(1 for n in nodes(row) if has_class(n, "kind")), 1)

        first = promoted["inbox"]["children"][0]
        self.assertEqual(first["tag"], "article")
        self.assertTrue(has_class(first, "lead") and has_class(first, "brief"))
        self.assertIn("owner/p01 brief, version 1", full(first))
        self.assertFalse(any(has_class(n, "brief-row") for n in nodes(promoted["inbox"])))

    def test_a_reply_in_a_later_brief_survives_frames_and_closing(self) -> None:
        both = {"frame": frame([BRIEF, BRIEF_B])}
        typed, closed, reopened = render([
            START, both, {"open": KEY_B},
            {"focus_on": "reply-text", "in": KEY_B},
            {"input": {"cls": "reply-text", "value": "smaller slices"}, "in": KEY_B},
            both, {"snapshot": True},
            {"close": KEY_B}, both, {"snapshot": True},
            {"open": KEY_B}, {"snapshot": True},
        ])
        self.assertEqual(typed["active"], "reply-text")
        self.assertEqual(typed["field"]["value"], "smaller slices")
        for snap in (typed, closed, reopened):
            row = brief_row(snap)
            self.assertEqual(reply_fields(dict(inbox=row)), ["smaller slices"])
            lead = snap["inbox"]["children"][0]
            self.assertEqual(reply_fields(dict(inbox=lead)), [""])
        self.assertFalse(brief_row(closed)["open"])
        self.assertEqual(
            [n["value"] for n in visible(brief_row(reopened)) if has_class(n, "reply-text")],
            ["smaller slices"])
        self.assertEqual(replies(reopened), [])

    def test_a_later_brief_opens_itself_once_per_approval_step(self) -> None:
        both = {"frame": frame([BRIEF, BRIEF_B])}
        waiting, closed, approved, closed_again = render([
            START, both, {"key": "Enter"}, {"key": "Enter"}, {"snapshot": True},
            {"close": KEY_B}, both, {"snapshot": True},
            {"clock": 5000}, {"snapshot": True},
            {"close": KEY_B}, both, {"snapshot": True},
        ])
        row = brief_row(waiting)
        self.assertTrue(row["open"])
        self.assertIn(APPROVING_TEXT, visible_text(row))
        self.assertEqual(approvals(waiting), [])
        row = brief_row(closed)
        self.assertFalse(row["open"])
        self.assertNotIn(APPROVING_TEXT, visible_text(row))
        row = brief_row(approved)
        self.assertTrue(row["open"])
        self.assertIn(APPROVED_TEXT, visible_text(row))
        self.assertFalse(brief_row(closed_again)["open"])

    def test_the_brief_reply_field_carries_a_hint_and_a_name(self) -> None:
        (snap,) = render([START, {"frame": frame([BRIEF])}, {"snapshot": True}])
        (field,) = [n for n in nodes(snap["inbox"]) if has_class(n, "reply-text")]
        self.assertEqual(field["placeholder"], "Or say what to change\u2026")
        self.assertEqual(field["label"], "Or say what to change")

    def test_the_first_row_sits_one_row_gap_below_the_card(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        (body,) = re.findall(r"(?s)<style>(.*?)</style>", text)
        top = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", body)
        rules = style_rules(top)

        def decls(selector: str) -> dict:
            merged: dict = {}
            for sel, found in rules:
                if sel == selector:
                    merged.update(found)
            return merged

        self.assertEqual(decls(".brief-row").get("padding"), decls(".rest > li.row")["padding"])
        self.assertEqual(decls(".brief-row").get("padding"), "12px 0")
        self.assertEqual(decls(".card.lead + .brief-row").get("margin-top"), "12px")
        self.assertEqual(decls(".card.lead + .rest").get("margin-top"), "12px")
        self.assertIn("var(--hair)", decls(".brief-row + .brief-row").get("border-top", ""))

    def test_a_closed_brief_row_stays_closed_after_its_reply_is_sent(self) -> None:
        both = {"frame": frame([BRIEF, BRIEF_B])}
        sent, closed = render([
            START, both, {"open": KEY_B},
            {"input": {"cls": "reply-text", "value": "smaller slices"}, "in": KEY_B},
            {"respond": {"status": 204}},
            {"click": "reply-send", "in": KEY_B}, {"snapshot": True},
            {"close": KEY_B}, both, {"snapshot": True},
        ])
        (post,) = replies(sent)
        self.assertEqual(posted(post), {
            "project_id": "owner/p01", "sprint_id": "b" * 16, "version": 1,
            "reply": "smaller slices"})
        row = brief_row(sent)
        self.assertTrue(row["open"])
        self.assertIn(REPLIED_TEXT, visible_text(row))
        row = brief_row(closed)
        self.assertFalse(row["open"])
        self.assertFalse(has_any(row, ROW_BODY))


def style_rules(block: str) -> list:
    """(selector, {property: value}) for every rule in a block of CSS without nested blocks."""
    css = re.sub(r"(?s)/\*.*?\*/", "", block)
    rules = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for decl in body.split(";"):
            name, _, value = decl.partition(":")
            if name.strip():
                decls[name.strip()] = value.strip()
        for selector in selectors.split(","):
            rules.append((" ".join(selector.split()), decls))
    return rules


def media_block(style: str, query: str) -> str:
    opener = "@media " + query + " {"
    if opener not in style:
        return ""
    start = style.index(opener) + len(opener)
    depth, at = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(style[at], 0)
        at += 1
    return style[start:at - 1]


class PageAnsweredRowTest(unittest.TestCase):
    def test_an_answered_row_clips_its_question_to_one_line(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        (body,) = re.findall(r"(?s)<style>(.*?)</style>", text)
        top = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", body)
        rules = style_rules(top)
        clip = {}
        for selector, decls in rules:
            if selector == ".done-item summary > b":
                clip.update(decls)
        self.assertEqual(
            {k: clip.get(k) for k in ("white-space", "overflow", "text-overflow", "min-width")},
            {"white-space": "nowrap", "overflow": "hidden", "text-overflow": "ellipsis",
             "min-width": "0"})
        summary = {}
        for selector, decls in rules:
            if selector == ".done-item summary":
                summary.update(decls)
        self.assertEqual(summary.get("flex-wrap"), "nowrap")
        # The tail (the "more" words and the "when" phrase) must itself shrink and clip, so a
        # narrow screen never pushes the row (and the page) wider than its column, but only
        # after the question has given up its width: the question's shrink factor outweighs
        # the tail's, so "answered ..., waiting for the agent" keeps its words (state is never
        # colour alone) until the question is gone.
        tail, row_rule = {}, {}
        for selector, decls in rules:
            if selector == ".done-item summary > span":
                tail.update(decls)
            if selector == ".done-item":
                row_rule.update(decls)
        self.assertEqual(
            {k: tail.get(k) for k in ("white-space", "overflow", "text-overflow", "min-width")},
            {"white-space": "nowrap", "overflow": "hidden", "text-overflow": "ellipsis",
             "min-width": "0"})
        tail_flex = tail.get("flex", "").split()
        clip_flex = clip.get("flex", "").split()
        self.assertEqual(tail_flex[:1], ["0"])
        self.assertEqual(clip_flex[:1], ["0"])
        self.assertGreater(float(clip_flex[1]), float(tail_flex[1]))
        self.assertGreater(float(tail_flex[1]), 0)
        self.assertEqual(row_rule.get("min-width"), "0")
        done = item("Z", answered=True, headline="Which database?",
                    answered_at="2026-11-11T10:00:00+00:00",
                    questions=[{"question": "Which database?", "options": ["sqlite", "postgres"],
                                "chosen": "postgres", "recommended": None}])
        closed, opened = render([
            {"start": {"focused": False, "clock": NOW_MS}}, {"frame": frame([], answered=[done])},
            {"snapshot": True}, {"open": "answered:owner/p00#Z"}, {"snapshot": True},
        ])
        (ul,) = [n for n in nodes(closed["inbox"]) if n["tag"] == "ul" and has_class(n, "done")]
        (row,) = ul["children"]
        (summary_node,) = [n for n in nodes(row) if n["tag"] == "summary"]
        first = summary_node["children"][0]
        self.assertEqual((first["tag"], first["text"]), ("b", "Which database?"))
        self.assertNotIn("postgres", visible_text(row))
        self.assertIn("chosen: postgres", visible_text(opened["inbox"]))


class PageKeyStripTest(unittest.TestCase):
    def test_the_key_strip_lists_only_the_keys_that_act_on_the_current_item(self) -> None:
        one = item("O", questions=[{"question": "Go?", "options": ["yes"], "chosen": None,
                                    "recommended": "yes"}])
        rows = [
            ("decision", [START, {"frame": frame([ANSWERABLE])}, {"snapshot": True}],
             ["1", "2", "Enter"], ("choose", "send answer")),
            ("one option", [START, {"frame": frame([one])}, {"snapshot": True}],
             ["1", "Enter"], ("choose", "send answer")),
            ("ten options", [START, {"frame": frame([item("T", questions=[
                {"question": "Which?", "options": [str(i) for i in range(10)],
                 "chosen": None, "recommended": None}])])}, {"snapshot": True}],
             ["1", "9"], ("choose",)),
            ("ten options, one picked", [START, {"frame": frame([item("T", questions=[
                {"question": "Which?", "options": [str(i) for i in range(10)],
                 "chosen": None, "recommended": None}])])}, {"key": "1"}, {"snapshot": True}],
             ["1", "9", "Enter"], ("choose", "send answer")),
            ("two questions, one picked", [START, {"frame": frame([item("U", questions=[
                {"question": "Which?", "options": ["a", "b"], "chosen": None, "recommended": None},
                {"question": "And?", "options": ["c", "d"], "chosen": None, "recommended": None},
            ])])}, {"key": "1"}, {"snapshot": True}], ["1", "2"], ("choose",)),
            ("check", [START, {"frame": frame([check_item("M", "manual-check")])},
                       {"snapshot": True}], None, ()),
            ("empty", [START, {"frame": frame([])}, {"snapshot": True}], None, ()),
            ("answered only", [START, {"frame": frame([], answered=[item("Z", answered=True)])},
                               {"snapshot": True}], None, ()),
            ("waiting", [START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"},
                         {"snapshot": True}], ["Esc"], ("undo",)),
            ("check waiting", [START, {"frame": frame([check_item("M", "manual-check")])},
                               {"click": "ans-passed"}, {"snapshot": True}], ["Esc"], ("undo",)),
            ("gone while waiting", [START, {"frame": frame([ANSWERABLE])}, {"key": "Enter"},
                                    {"clock": 2000}, {"frame": frame([])},
                                    {"snapshot": True}], None, ()),
            ("brief", [START, {"frame": frame([BRIEF])}, {"snapshot": True}],
             ["Enter"], ("approve",)),
            ("brief, reply sending", [
                START, {"frame": frame([BRIEF])},
                {"input": {"cls": "reply-text", "value": "redo"}}, {"hold": True},
                {"click": "reply-send"}, {"snapshot": True}], None, ()),
        ]
        for name, steps, expected, words in rows:
            with self.subTest(row=name):
                snap = render(steps)[-1]
                strips = [n for n in nodes(snap["inbox"]) if has_class(n, "keys")]
                if expected is None:
                    self.assertEqual(strips, [])
                    continue
                (strip,) = strips
                self.assertIs(snap["inbox"]["children"][-1], strip)
                self.assertEqual([n["text"] for n in nodes(strip) if n["tag"] == "kbd"], expected)
                for word in words:
                    self.assertIn(word, full(strip))


class PageStandingRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        (self.style,) = re.findall(r"(?s)<style>(.*?)</style>", text)

    def test_motion_is_off_under_reduced_motion(self) -> None:
        block = media_block(self.style, "(prefers-reduced-motion: reduce)")
        declared = {name for _, decls in style_rules(block) for name in decls}
        self.assertLessEqual({"transition-duration", "animation-duration"}, declared)

    def test_the_lead_card_narrows_under_900(self) -> None:
        horizontal = []
        for selector, decls in style_rules(media_block(self.style, "(max-width: 900px)")):
            if selector != ".card.lead":
                continue
            parts = decls.get("padding", "").split()
            if len(parts) == 4:
                horizontal += [parts[1], parts[3]]
            elif parts:
                horizontal.append(parts[0] if len(parts) == 1 else parts[1])
            for name in ("padding-left", "padding-right", "padding-inline"):
                horizontal += decls.get(name, "").split()
        self.assertTrue(horizontal)
        for value in horizontal:
            self.assertRegex(value, r"^\d+(\.\d+)?px$")
            self.assertLessEqual(float(value[:-2]), 16)
