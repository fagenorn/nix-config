"""The desk page's static invariants: one self-contained file, no other origin."""

import dataclasses
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

from agent_tools.console import answer as console_answer
from agent_tools.console import capacity as console_capacity
from agent_tools.console import digest as console_digest
from agent_tools.console import signin as console_signin
from agent_tools.console.event_log import Event
from agent_tools.console import event_log
from agent_tools.console.sprints import MAX_REPORT_ISSUES, Question, sprint_states
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_messages import ANSWER as MESSAGE_ANSWER, AT, PARTS, approval, life, view_with
from .test_console_view import (
    A, MIN, T0_MS, entry as view_entry, iso, line as view_line, message_at, message_row,
    message_rows, reported, started)

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


def render_page(view: dict, clock_ms: int | None = None) -> dict:
    """The `#statement`, `#inbox`, `#capacity` and `#promoted` trees the page draws for `view`, run under node.

    The page reads the real clock unless `clock_ms` freezes it, which a view with a reset time needs (#1045)."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the page render tests need it")
    html = PAGE.read_text(encoding="utf-8")
    script = re.search(r"(?s)<script>(.*?)</script>", html).group(1)
    ids = re.findall(r'id="([^"]+)"', html)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.js"
        frozen = "" if clock_ms is None else f"Date.now = () => {int(clock_ms)};\n"
        path.write_text(INBOX_HARNESS + frozen + script + TAIL, encoding="utf-8")
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
        self.assertEqual(unwrapped, {".brand", ".cap", ".cap-acct", ".cap-acct b",
                                    ".goal-in .goal-text::placeholder"})
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
             "/api/message", "/api/stop", "/api/round-answer", "/api/continue",
             "/api/exclusion", "/api/pin", "/api/signin", "/api/signin-code", "/api/signin-cancel",
             "/api/account-add", "/api/signin-link", "/api/account-remove",
             "/api/register-project", "/api/plan-answer", "/api/plan-approve",
             "/api/adoption-register", "/api/plan-defer", "/api/register-confirm",
             "/api/trust-check", "/api/register-cancel"},
        )
        self.assertEqual(
            len(re.findall(r"\b(?:fetch|EventSource)\(", self.text)), len(literals)
        )

    def test_the_page_takes_its_view_only_from_the_stream(self) -> None:
        # A separate snapshot request can answer after a newer streamed frame
        # and render over it; the stream's first frame is already the snapshot.
        self.assertEqual(len(re.findall(r"\bfetch\(", self.text)), 34)
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
                      "/api/reply", "/api/message", "/api/stop", "/api/round-answer",
                      "/api/pin", "/api/signin", "/api/signin-code", "/api/signin-cancel",
                      "/api/account-add", "/api/signin-link"):
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

    def test_only_a_note_a_typed_confirmation_and_a_sign_in_code_are_typed(self) -> None:
        self.assertEqual(self.text.count('createElement("input")'), 2)
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

    def test_the_tracker_and_sign_in_links_are_the_only_hrefs(self) -> None:
        self.assertEqual(len(re.findall(r"\.href\s*=", self.text)), 4)
        lines = self.text.splitlines()
        (at,) = [i for i, row in enumerate(lines) if "link.href = held.link;" in row]
        self.assertIn("isHttps(", lines[at - 1] + lines[at])
        self.assertIn(r"/^https:\/\//", self.text)
        self.assertEqual(self.text.count("a.href = item.url;"), 1)
        self.assertEqual(self.text.count("link.href = sprint.tracker_url;"), 1)
        self.assertEqual(self.text.count("link.href = item.url;"), 1)
        self.assertNotIn("adoption.url", self.text)
        self.assertEqual(self.text.count("if (isHttps(item.url)) {"), 1)
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
        closed, opened = render([{"frame": view([project(0, [], quiet=True)])}, {"snapshot": True},
                                 {"open": "line:owner/p00"}, {"snapshot": True}])
        (fold,) = [n for n in nodes(closed["projects"]) if n["key"] == "line:owner/p00"]
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual([n["text"] for n in visible(summary) if n["text"]], ["owner/p00", "quiet"])
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


def capacity_snap(cap: dict, clock_ms: int = 0) -> dict:
    (snap,) = render([{"start": {"focused": False, "clock": clock_ms}},
                      {"frame": {**view([]), "capacity": cap}}, {"snapshot": True}])
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
            ["cap-state cap-fine", "cap-acct cap-extra", "cap-acct cap-tightest", "cap-none cap-extra"])
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
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-when")], [])
        self.assertNotIn("resets", full(snap["capacity"]))
        self.assertEqual(full(part(snap, "cap-none")), "1 with no reading yet")

    def test_tight_reads_tight_and_an_out_account_reads_out_until(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "ok", week_left=12, next_reset="2026-11-16T05:00:00+00:00"),
            profile("b", "out", week_left=55, five_hour_left=0,
                    out_until="2026-11-13T09:30:00+00:00", next_reset="2026-11-13T08:00:00+00:00"),
        ], tight=True))
        self.assertEqual(
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-tight", "cap-acct cap-extra", "cap-acct cap-out cap-tightest"])
        state = strip(snap)[0]
        self.assertEqual(full(state), "tight")
        self.assertIn("svg", [c["tag"] for c in state["children"]])
        a, b = accounts(snap)
        self.assertEqual(bar(a), "12%")
        self.assertEqual(bar(b), "55%")
        self.assertEqual(b["title"], "55% of the week left, 0% of 5 hours")
        self.assertIn("out until Fri 09:30", full(b))
        self.assertEqual([n for n in nodes(b) if has_class(n, "cap-pc")], [])
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-when")], [])
        self.assertNotIn("resets", full(snap["capacity"]))

    def test_every_account_out_reads_out_in_red_and_when_work_resumes(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "out", week_left=0, out_until="2026-11-13T09:30:00+00:00"),
            profile("b", "out", out_until="2026-11-13T10:00:00+00:00"),
        ], all_out=True, resumes_at="2026-11-13T09:30:00+00:00"), NOW_MS)
        self.assertEqual(
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-out", "cap-acct cap-out cap-tightest", "cap-acct cap-out cap-extra"])
        state = strip(snap)[0]
        self.assertEqual(full(state), "out")
        self.assertIn("svg", [c["tag"] for c in state["children"]])
        a, b = accounts(snap)
        self.assertEqual(bar(a), "0%")
        self.assertEqual(bars(b), [])
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-when")], [])
        self.assertNotIn("resumes", full(snap["capacity"]))
        self.assertNotIn("resets", full(snap["capacity"]))
        statement = render_page({**view([]), "capacity": capacity([
            profile("a", "out", week_left=0, out_until="2026-11-13T09:30:00+00:00"),
            profile("b", "out", out_until="2026-11-13T10:00:00+00:00"),
        ], all_out=True, resumes_at="2026-11-13T09:30:00+00:00")}, NOW_MS)["statement"]
        self.assertIn("Resumes Fri 09:30", full(statement))
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
            [n["cls"] for n in strip(snap)],
            ["cap-state cap-fine", "cap-acct cap-extra", "cap-acct cap-tightest"])
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
        result = render_page(full, NOW_MS - 86400 * 1000)
        self.assertIn("Capacity", result["promoted"]["text"])
        self.assertEqual(result["promoted"]["text"].count("out until"), 2)
        self.assertIn("Resumes ", result["statement"]["text"])
        html = PAGE.read_text(encoding="utf-8")
        self.assertLess(html.index('id="promoted"'), html.index('id="inbox"'))
        partial = {**view([]), "capacity": capacity(
            out, all_out=False, resumes_at="2026-11-12T09:00:00+00:00")}
        shown = render_page(partial, NOW_MS - 86400 * 1000)
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

    def test_all_out_lists_an_excluded_profile_as_excluded(self) -> None:
        result = render_page({**view([]), "capacity": capacity([
            profile("a", "ok", week_left=65, excluded=True),
            profile("b", "out", out_until="2026-11-20T09:30:00+00:00"),
        ], all_out=True)})
        items = [n["text"] for n in nodes(result["promoted"]) if n["tag"] == "li"]
        self.assertEqual(items, ["a excluded", "b out until Fri 09:30"])

    def test_an_all_excluded_strip_never_reads_fine(self) -> None:
        snap = capacity_snap(capacity([
            profile("a", "ok", week_left=65, next_reset="2026-11-16T05:00:00+00:00", excluded=True),
            profile("b", "ok", week_left=30, next_reset="2026-11-17T05:00:00+00:00", excluded=True),
        ]))
        self.assertEqual(classes(snap),
                         ["cap-acct cap-excluded", "cap-acct cap-excluded", "cap-none"])
        self.assertEqual(full(part(snap, "cap-none")), "every profile excluded")
        self.assertNotIn("resets", full(snap["capacity"]))
        self.assertNotIn("fine", [full(n) for n in strip(snap)])
        mixed = capacity_snap(capacity([
            profile("a", "ok", week_left=65, next_reset="2026-11-16T05:00:00+00:00", excluded=True),
            profile("b", "ok", week_left=30, next_reset="2026-11-17T05:00:00+00:00", excluded=False),
        ]))
        self.assertEqual(classes(mixed)[0], "cap-state cap-fine")
        self.assertEqual([n for n in nodes(mixed["capacity"]) if has_class(n, "cap-when")], [])
        self.assertEqual([n for n in strip(mixed) if has_class(n, "cap-none")], [])

    def test_a_view_without_capacity_still_renders(self) -> None:
        result = render_page(view([]))
        self.assertEqual([(n["cls"], full(n)) for n in result["capacity"]["children"]],
                         [("cap-none", "no accounts")])
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
            self.begin, {"frame": first}, {"click": "cap"}, {"snapshot": True},
            {"frame": second}, {"snapshot": True},
        ])
        self.assertIn("waiting 3 h", full(one["inbox"]))
        self.assertIn("read yesterday", full(one["inbox"]))
        self.assertIn("Since you last looked, 1 h ago", full(one["digest"]))
        self.assertIn("5 min ago", full(one["digest"]))
        self.assertIn("resets Mon 05:00", full(one["accounts_body"]))
        self.assertNotIn("resets", full(one["capacity"]))
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
        refusal = console_answer.NETWORK_DOWN
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

    def test_a_failed_tick_offers_try_again_which_sends_the_same_answer_at_once(self) -> None:
        failed, sending, sent = render([
            START, {"frame": frame([ANSWERABLE])},
            {"respond": {"status": 502, "text": console_answer.NETWORK_DOWN + "\n"}},
            {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
            {"hold": True}, {"click": "answer-again"}, {"snapshot": True},
            {"release": {"status": 204}}, {"snapshot": True},
        ])
        (fail,) = [n for n in nodes(failed["inbox"]) if has_class(n, "fail")]
        self.assertEqual(fail["text"], "Could not send: " + console_answer.NETWORK_DOWN)
        (again,) = [n for n in nodes(failed["inbox"]) if has_class(n, "answer-again")]
        self.assertEqual(again["text"], "Try again")
        self.assertFalse(has_class(again, "primary"))
        self.assertTrue(picked(failed)[0].endswith("two"))
        posts = answers(sending)
        self.assertEqual(len(posts), 2)
        for post in posts:
            self.assertEqual(posted(post),
                             {"project_id": "owner/p00", "key": "A", "choices": [1]})
        self.assertIn("Sending\u2026", full(sending["inbox"]))
        self.assertEqual(count(sending, "fail"), 0)
        self.assertEqual(count(sending, "answer-again"), 0)
        self.assertIn(SENT_TEXT, full(sent["inbox"]))

    def test_try_again_is_offered_only_when_a_repeat_may_succeed(self) -> None:
        refused = "the prompt changed on the tracker"
        for name, steps, expected in (
            ("refused", [{"respond": {"status": 409, "text": refused + "\n"}},
                         {"key": "Enter"}, {"clock": 5000}], 0),
            ("console failed",
             [{"respond": {"status": 500, "text": console_answer.UNEXPECTED_FAILURE + "\n"}},
              {"key": "Enter"}, {"clock": 5000}], 1),
            ("no answer", [{"fail_fetch": True}, {"key": "Enter"}, {"clock": 5000}], 1),
            ("another choice",
             [{"respond": {"status": 502, "text": console_answer.NETWORK_DOWN + "\n"}},
              {"key": "Enter"}, {"clock": 5000}, {"key": "1"}], 0),
        ):
            with self.subTest(name):
                (snap,) = render([START, {"frame": frame([ANSWERABLE])}, *steps,
                                  {"snapshot": True}])
                self.assertEqual(count(snap, "answer-again"), expected)
                if name == "refused":
                    self.assertIn("Could not send: " + refused, full(snap["inbox"]))

    def test_a_failure_with_no_reason_reads_plainly(self) -> None:
        for status, expected in ((502, 1), (409, 0)):
            with self.subTest(status):
                (snap,) = render([
                    START, {"frame": frame([ANSWERABLE])},
                    {"respond": {"status": status, "text": ""}},
                    {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
                ])
                (fail,) = [n for n in nodes(snap["inbox"]) if has_class(n, "fail")]
                self.assertEqual(fail["text"], "Could not send: the console did not say why.")
                self.assertNotIn("HTTP", full(snap["inbox"]))
                self.assertEqual(count(snap, "answer-again"), expected)

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


SID = "a" * 16


def question(index, text, options, recommended, **fields):
    base = {"type": "inbox_item", "reason": "question",
            "key": f"question/{SID}/41/{index}", "project_id": "owner/p00", "sprint_id": SID,
            "title": "make the importer resumable", "round": 41, "index": index,
            "blocker": False, "blocks": "the resume slice", "headline": text,
            "context": None, "more_questions": 0,
            "questions": [{"question": text, "options": options, "chosen": None,
                           "recommended": recommended,
                           "recommended_index": options.index(recommended)}],
            "items": [], "answers": [], "answered": False,
            "waiting_since": "2026-11-10T08:00:00+00:00"}
    base.update(fields)
    return base


Q0 = question(0, "Which store keeps the checkpoints?", ["sqlite", "files", "redis"], "files")
Q1 = question(1, "May the reader change?", ["yes", "no"], "no", blocks="the reader slice")


def round_posts(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/round-answer"]


def rows_of(snap: dict) -> list:
    return [n for n in nodes(snap["inbox"]) if has_class(n, "row")]


def held_texts(node: dict) -> list:
    return [full(n) for n in nodes(node) if has_class(n, "held")]


class PageQuestionTest(unittest.TestCase):
    def test_a_question_opens_with_its_recommendation_and_shows_the_project_and_the_sprint(self) -> None:
        (snap,) = render([START, {"frame": frame([Q0, Q1])}, {"snapshot": True}])
        self.assertTrue(picked(snap)[0].endswith("files"))
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        text = full(lead)
        for word in ("Question", "owner/p00", "make the importer resumable",
                     "Which store keeps the checkpoints?", "Blocks: the resume slice"):
            self.assertIn(word, text)
        self.assertTrue([n for n in nodes(lead) if has_class(n, "sprint-title")])
        tree = render_page(frame([Q0, Q1]))["inbox"]
        self.assertEqual([n["href"] for n in walk(tree) if n.get("href")], [])
        self.assertNotIn("Answer on the tracker", full(tree))

    def test_a_question_leads_with_its_ask_and_sets_its_context_beneath(self) -> None:
        asked = question(0, "Which store keeps the checkpoints?", ["sqlite", "files"], "files",
                         context="A crash loses an hour of work.")
        (snap,) = render([START, {"frame": frame([asked])}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        (title,) = [n for n in nodes(lead) if has_class(n, "sprint-title")]
        self.assertEqual(full(title), "make the importer resumable")
        self.assertEqual([n for n in nodes(lead) if has_class(n, "sprint-goal")], [])
        (ask,) = [n for n in nodes(lead) if n["tag"] == "h2" and has_class(n, "q")]
        self.assertEqual(full(ask), "Which store keeps the checkpoints?")
        kids = lead["children"]
        after = kids[kids.index(ask) + 1]
        self.assertTrue(has_class(after, "context"))
        self.assertFalse(has_class(after, "q"))
        self.assertEqual(full(after), "A crash loses an hour of work.")

    def test_the_blocks_line_stays_one_line(self) -> None:
        (snap,) = render([START, {"frame": frame([Q0])}, {"snapshot": True}])
        (held,) = [n for n in nodes(snap["inbox"]) if has_class(n, "held")]
        self.assertTrue(has_class(held, "blocks"))
        self.assertEqual(full(held), "Blocks: the resume slice")
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        merged: dict = {}
        for selector, decls in style_rules(style):
            if selector == ".held.blocks":
                merged.update(decls)
        self.assertEqual(merged.get("white-space"), "nowrap")
        self.assertEqual(merged.get("overflow"), "hidden")
        self.assertEqual(merged.get("text-overflow"), "ellipsis")

    def test_an_open_question_row_sets_its_context_under_its_ask(self) -> None:
        asked = question(1, "May the reader change?", ["yes", "no"], "no",
                         context="The reader is shared.")
        (snap,) = render([START, {"frame": frame([Q0, asked])}, {"snapshot": True}])
        (row,) = [n for n in rows_of(snap) if "May the reader change?" in full(n)]
        (context,) = [n for n in nodes(row) if has_class(n, "context")]
        self.assertEqual(full(context), "The reader is shared.")
        self.assertFalse(has_class(context, "q"))

    def test_a_collapsed_question_row_reads_the_project_and_the_title(self) -> None:
        (snap,) = render([START, {"frame": frame([Q0, Q1])}, {"snapshot": True}])
        (row,) = [n for n in rows_of(snap) if "May the reader change?" in full(n)]
        self.assertEqual([full(n) for n in nodes(row) if has_class(n, "lm")],
                         ["owner/p00 \u00b7 make the importer resumable"])

    def test_a_recommendation_is_found_by_index_when_shown_options_collide(self) -> None:
        same = "o" * 79 + "\u2026"
        asked = question(0, "Which store keeps the checkpoints?", [same, same], same, questions=[
            {"question": "Which store keeps the checkpoints?", "options": [same, same],
             "chosen": None, "recommended": same, "recommended_index": 1}])
        before, after = render([
            START, {"frame": frame([asked])}, {"snapshot": True}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True}])
        (lead,) = [n for n in nodes(before["inbox"]) if has_class(n, "lead")]
        buttons = [n for n in nodes(lead) if n["tag"] == "button" and has_class(n, "opt")]
        self.assertEqual(len(buttons), 2)
        recs = [n for n in nodes(before["inbox"]) if has_class(n, "rec")]
        self.assertEqual(len(recs), 1)
        self.assertEqual([has_class(b, "picked") for b in buttons], [False, True])
        self.assertEqual([bool([n for n in nodes(b) if has_class(n, "rec")]) for b in buttons],
                         [False, True])
        (sent,) = round_posts(after)
        self.assertEqual(posted(sent)["choice"], 1)

    def test_enter_twice_sends_both_recommendations(self) -> None:
        early, late = render([
            START, {"frame": frame([Q0, Q1])}, {"key": "Enter"}, {"key": "Enter"},
            {"clock": 4999}, {"snapshot": True}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(round_posts(early), [])
        self.assertIn(WAIT_TEXT, full(early["inbox"]))
        sent = round_posts(late)
        self.assertEqual([posted(p) for p in sent], [
            {"project_id": "owner/p00", "sprint_id": SID, "round": 41, "question": 0, "choice": 1},
            {"project_id": "owner/p00", "sprint_id": SID, "round": 41, "question": 1, "choice": 1},
        ])
        for post in sent:
            self.assertEqual(post["method"], "POST")
            self.assertEqual(post["headers"],
                             {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
        self.assertEqual(answers(late), [])

    def test_a_number_key_picks_another_option(self) -> None:
        (snap,) = render([
            START, {"frame": frame([Q0, Q1])}, {"key": "1"}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True},
        ])
        (post,) = round_posts(snap)
        self.assertEqual(posted(post), {
            "project_id": "owner/p00", "sprint_id": SID, "round": 41, "question": 0, "choice": 0,
        })

    def test_own_words_are_sent_verbatim_instead_of_a_choice(self) -> None:
        snap, reopened = render([
            START, {"frame": frame([Q0, Q1])},
            {"type": {"class": "words-text", "text": "use the reader\nnot the writer"}},
            {"click": "ans-words"}, {"clock": 5000}, {"snapshot": True},
            {"frame": frame([Q0, Q1])}, {"snapshot": True},
        ])
        (post,) = round_posts(snap)
        self.assertEqual(posted(post), {
            "project_id": "owner/p00", "sprint_id": SID, "round": 41, "question": 0,
            "text": "use the reader\nnot the writer",
        })
        # A sent answer leaves no draft behind when the item is shown open again (each row has its own field).
        self.assertEqual(
            [n["value"] for n in nodes(reopened["inbox"]) if has_class(n, "words-text")], ["", ""])
        (blank,) = render([
            START, {"frame": frame([Q0, Q1])},
            {"type": {"class": "words-text", "text": "   "}},
            {"click": "ans-words"}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertEqual(round_posts(blank), [])

    def test_a_refused_answer_says_why_and_keeps_the_pick(self) -> None:
        (snap,) = render([
            START, {"frame": frame([Q0, Q1])},
            {"respond": {"status": 409, "text": "this question is already answered"}},
            {"key": "Enter"}, {"clock": 5000}, {"snapshot": True},
        ])
        self.assertIn("Could not send: this question is already answered", full(snap["inbox"]))
        self.assertTrue(picked(snap)[0].endswith("files"))
        (sent,) = render([
            START, {"frame": frame([Q0, Q1])}, {"key": "Enter"}, {"clock": 5000},
            {"snapshot": True},
        ])
        self.assertIn(SENT_TEXT, full(sent["inbox"]))

    def test_a_blocker_reads_stops_all_work_wherever_it_is_drawn(self) -> None:
        Q1B = {**Q1, "blocker": True}
        stops = "Blocks: the reader slice \u00b7 stops all work"
        (lead,) = render([START, {"frame": frame([Q1B])}, {"snapshot": True}])
        self.assertIn(stops, full(lead["inbox"]))
        (behind,) = render([START, {"frame": frame([Q0, Q1B])}, {"snapshot": True}])
        (row,) = [r for r in rows_of(behind) if "May the reader change?" in full(r)]
        self.assertEqual(held_texts(row), [stops])
        (briefed,) = render([START, {"frame": frame([BRIEF_B, Q0, Q1B])}, {"snapshot": True}])
        (row0,) = [r for r in rows_of(briefed) if "Which store keeps" in full(r)]
        (row1,) = [r for r in rows_of(briefed) if "May the reader change?" in full(r)]
        self.assertEqual(held_texts(row0), ["Blocks: the resume slice"])
        self.assertEqual(held_texts(row1), [stops])
        (boxed,) = render([
            START, {"frame": frame([Q0, Q1B])}, {"key": "Enter"}, {"snapshot": True},
        ])
        (row,) = [r for r in rows_of(boxed) if "May the reader change?" in full(r)]
        self.assertTrue([n for n in nodes(row) if has_class(n, "abox")])
        self.assertEqual(held_texts(row), [stops])

    def test_own_words_survive_a_brief_taking_the_keyboard(self) -> None:
        before, after = render([
            START, {"frame": frame([Q0, Q1])},
            {"type": {"class": "words-text", "text": "use the reader"}}, {"snapshot": True},
            {"frame": frame([BRIEF_B, Q0, Q1])}, {"snapshot": True},
        ])
        for snap in (before, after):
            self.assertEqual(snap["active"], "words-text")
            self.assertEqual(snap["field"], {
                "cls": "words-text", "value": "use the reader", "start": 14, "end": 14,
            })
        self.assertEqual(len(brief_cards(after)), 1)
        (focused,) = render([
            START, {"frame": frame([Q0, Q1])}, {"focus_on": "words-text"},
            {"frame": frame([BRIEF_B, Q0, Q1])}, {"snapshot": True},
        ])
        self.assertEqual(focused["active"], "words-text")
        (typed,) = render([
            START, {"frame": frame([Q0, Q1])},
            {"type": {"class": "words-text", "text": "use the reader"}},
            {"focus_on": "ans-words"}, {"frame": frame([BRIEF_B, Q0, Q1])}, {"snapshot": True},
        ])
        self.assertEqual(
            [n["value"] for n in nodes(typed["inbox"]) if has_class(n, "words-text")],
            ["use the reader", ""],
        )

    def test_every_question_row_keeps_its_answer_controls_whoever_holds_the_keys(self) -> None:
        Q1B = {**Q1, "blocker": True}
        for shown in ([Q0, Q1B], [BRIEF_B, Q0, Q1B], [BRIEF_B, Q1B]):
            with self.subTest(items=[i["key"] for i in shown]):
                (snap,) = render([START, {"frame": frame(shown)}, {"snapshot": True}])
                (row,) = [r for r in rows_of(snap) if "May the reader change?" in full(r)]
                self.assertTrue([n for n in nodes(row) if has_class(n, "abox")])
                self.assertEqual(len([n for n in nodes(row) if has_class(n, "words-text")]), 1)
                self.assertEqual(len([n for n in nodes(row) if has_class(n, "ans-words")]), 1)
                options = [n for n in nodes(row) if has_class(n, "opt")]
                self.assertEqual(len(options), 2)
                self.assertFalse(any(n["disabled"] for n in options))

    def test_the_own_words_cannot_be_edited_while_the_answer_is_pending(self) -> None:
        typed = {"type": {"class": "words-text", "text": "use the reader"}}
        waiting, undone, sending, sent = render([
            START, {"frame": frame([Q0, Q1])}, typed, {"click": "ans-words"}, {"snapshot": True},
            {"click": "undo"}, {"snapshot": True},
            {"hold": True}, {"click": "ans-words"}, {"clock": 5000}, {"snapshot": True},
            {"release": {"status": 204, "text": ""}}, {"snapshot": True},
        ])
        for snap in (waiting, sending):
            self.assertTrue(field(snap, "words-text")["disabled"])
            self.assertTrue(field(snap, "ans-words")["disabled"])
            self.assertEqual(field(snap, "words-text")["value"], "use the reader")
        self.assertFalse(field(undone, "words-text")["disabled"])
        self.assertFalse(field(undone, "ans-words")["disabled"])
        (post,) = round_posts(sent)
        self.assertEqual(posted(post)["text"], "use the reader")



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


DEMO_QUESTION = "Open the console at 1440 px and say whether the question is readable at a glance."
DEMO_REST = "Note anything that hides it."


def labels_of(tree: dict) -> list:
    return [n for n in nodes(tree) if has_class(n, "check-id")]


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

    def test_a_failed_check_answer_offers_try_again_with_the_same_answer(self) -> None:
        down = {"respond": {"status": 502, "text": console_answer.NETWORK_DOWN + "\n"}}
        item = {"frame": frame([check_item("A", "manual-check")])}
        with self.subTest("passed"):
            (snap,) = render([START, item, down, {"click": "ans-passed"}, {"clock": 5000},
                              {"click": "answer-again"}, {"snapshot": True}])
            first, second = [posted(p) for p in checks(snap)]
            self.assertEqual(first, second)
            self.assertEqual(first["answer"], "passed")
        with self.subTest("note"):
            (snap,) = render([
                START, item, down, {"type": {"class": "note-text", "text": "Loads"}},
                {"click": "ans-note"}, {"clock": 5000},
                {"type": {"class": "note-text", "text": "Changed"}},
                {"click": "answer-again"}, {"snapshot": True},
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
        self.assertEqual(full(head), "Which database?")
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
            ([ANSWERABLE], "Decision", "owner/p00", "Which host?", "Send answer"),
            ([BRIEF], "Brief", "owner/p01", "owner/p01 brief, version 2", "Approve"),
            ([check_item("M", "manual-check")], "Check", "owner/p00", "Question M?", "Passed"),
            ([check_item("L", "approval")], "Approval", "owner/p00", "Question L?", "Approve"),
        ]
        for open_items, word, project, heading, label in cases:
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
                self.assertEqual(full(primaries[0]), label)
                self.assertEqual([c for c in primaries[0]["children"] if c["tag"] == "kbd"], [])

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
        self.assertEqual(entered, [])

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
TITLE = "Importer resumes after a crash"
LONG_GOAL = "Make the importer resumable after a crash. " + "g" * 1357
GOAL_HEADERS = {"X-Console-Token": TOKEN, "Content-Type": "application/json"}
SPRINT = {
    "type": "sprint", "sprint_id": "a" * 16, "title": TITLE, "goal": GOAL_TEXT,
    "state": "drafting",
    "state_text": "drafting the brief", "stated_at": "2026-11-12T10:00:00+00:00",
    "age_text": "stated 3 min ago", "manager_text": "no manager has picked this up",
    "manager_state": "none", "manager_until": None, "retry": False, "sessions": [],
    "ball": "manager", "ball_text": "manager working", "now_text": "two slices are building",
    "ended_at": None, "closing": None,
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
        for expected in (GOAL_TEXT, "manager working", "two slices are building",
                         "stated 3 min ago", "no manager has picked this up"):
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
        "state": state, "state_text": state, "action_text": None, "read_at": None,
        "reply": None, "reply_at": None, "new": False,
        **extra,
    }


def tell_field(snap: dict) -> dict:
    (found,) = [n for n in nodes(snap["projects"]) if has_class(n, "tell")]
    return found


class PageMessageTest(unittest.TestCase):
    def messages(self) -> list:
        return [
            message_entry(3, "text", "sent"),
            message_entry(4, "approved", "sent"),
            message_entry(5, "text", "replied", text="a third note", reply=REPLY_TEXT,
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
        for expected in (TELL_TEXT, "Approved version 2", "a third note", "sent",
                         "replied", "Manager: " + REPLY_TEXT):
            self.assertIn(expected, shown)
        states = [n for n in nodes(line) if has_class(n, "message-state")]
        self.assertEqual(sorted(full(n) for n in states), ["replied", "sent", "sent"])
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
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
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
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"fail_fetch": True}, {"click": "tell-send"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual([full(n) for n in nodes(line) if has_class(n, "fail")],
                         ["Could not send: the console did not answer"])
        self.assertEqual(tell_field(snap)["value"], TELL_TEXT)

    def test_a_sent_message_closes_the_field(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"click": "tell-send"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual([n for n in nodes(snap["projects"]) if has_class(n, "tell")], [])
        self.assertEqual(
            len([n for n in nodes(line) if n["tag"] == "button" and has_class(n, "tell-open")]), 1
        )
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/message"]
        self.assertEqual(json.loads(post["body"]), {
            "project_id": "owner/p00", "sprint_id": "a" * 16, "text": TELL_TEXT})
        self.assertEqual([n for n in nodes(line) if has_class(n, "fail")], [])

    def test_a_typed_message_keeps_its_focus_and_selection_across_frames(self) -> None:
        sent = message_entry(3, "text", "picked_up")
        before, after, more = render([
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
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
        gone, back = render([
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"frame": with_sprints([])}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
        ])
        self.assertIsNone(gone["active"])
        self.assertEqual([n for n in nodes(back["projects"]) if has_class(n, "tell")], [])


NUDGE_ACTION_TEXT = "Tell the manager again to nudge it, or withdraw the sprint."
HINT_TEXT = "The manager picks it up within a minute."
EARLIER_KEY = "earlier:" + "a" * 16
LIFE_SPRINT = {**REPORTED, "tell_text": HINT_TEXT, "stoppable": True}


def life_entry(mid: int, state: str, state_text: str, **extra: object) -> dict:
    return message_entry(mid, "text", state, state_text=state_text, text="note " + str(mid),
                         **extra)


def life_frame(messages: list, **extra: object) -> dict:
    return with_sprints([{**LIFE_SPRINT, "messages": messages, "reach_text": None, **extra}])


class PageMessageLifeTest(unittest.TestCase):
    def test_only_the_latest_exchange_shows_and_older_ones_sit_behind_a_closed_fold(self) -> None:
        messages = [
            life_entry(3, "picked_up", "picked up"),
            life_entry(4, "picked_up", "picked up"),
            life_entry(5, "replied", "replied", reply=REPLY_TEXT),
        ]
        before, after = render([
            START, {"frame": life_frame(messages)}, {"snapshot": True},
            {"open": EARLIER_KEY}, {"snapshot": True},
        ])
        (line,) = sprint_lines(before)
        shown = visible_text(line)
        for expected in ("note 5", "replied", "Manager: " + REPLY_TEXT):
            self.assertIn(expected, shown)
        for gone in ("note 3", "note 4"):
            self.assertNotIn(gone, shown)
        (fold,) = of_class(line, "details", "sprint-earlier")
        self.assertFalse(fold["open"])
        self.assertEqual(fold["key"], EARLIER_KEY)
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "Earlier messages (2)")
        (line,) = sprint_lines(after)
        for expected in ("note 3", "note 4", "note 5"):
            self.assertIn(expected, visible_text(line))
        detail = [n for n in nodes(line) if n["tag"] == "details" and n["key"] == DETAIL_KEY]
        self.assertEqual([n for d in detail for n in nodes(d) if has_class(n, "message")], [])

    def test_an_approval_from_the_view_draws_no_approval_line_once_picked_up(self) -> None:
        read = message_row(5, event_log.SPRINT_READ, {"through": 4})
        (picked,) = render([
            START, {"frame": with_sprints([life(approval(read), AT + 60_000)])},
            {"snapshot": True},
        ])
        shown = text(picked["projects"])
        self.assertNotIn("Approved version", shown)
        self.assertNotIn("picked up", shown)
        rows = approval(read, message_row(6, event_log.SPRINT_ANSWERED,
                                          {"message": 4, "reply": MESSAGE_ANSWER}))
        replied = view_with(sprint_states(rows), message_at(5), AT + 60_000)
        (snap,) = render([
            START, {"frame": with_sprints([replied["entries"][0]["sprints"][0]])},
            {"snapshot": True},
        ])
        (message,) = of_class(snap["projects"], "li", "message")
        self.assertTrue(has_class(message, "manager-line"))
        (reply,) = of_class(message, "span", "message-reply")
        self.assertEqual(full(reply), "Manager: " + MESSAGE_ANSWER)
        self.assertEqual([full(n) for n in of_class(message, "span", "message-new")], ["new"])
        self.assertEqual(of_class(message, "span", "message-text"), [])
        self.assertEqual(of_class(message, "span", "message-state"), [])
        self.assertNotIn("Approved version", text(snap["projects"]))

    def test_a_single_message_has_no_earlier_fold(self) -> None:
        (snap,) = render([
            START, {"frame": life_frame([life_entry(3, "sent", "sent")])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual(of_class(line, "details", "sprint-earlier"), [])
        self.assertEqual(len(of_class(line, "div", "sprint-exchange")), 1)

    def test_each_message_state_reads_its_words_and_not_picked_up_names_its_action(self) -> None:
        cases = [
            ("sent", "sent, the manager picks it up within a minute", {}),
            ("picked_up", "picked up", {}),
            ("replied", "replied", {"reply": REPLY_TEXT}),
            ("not_picked_up", "not picked up after 5 min", {"action_text": NUDGE_ACTION_TEXT}),
        ]
        snaps = render([
            step for state, words, extra in cases
            for step in ({"frame": life_frame([life_entry(3, state, words, **extra)])},
                         {"snapshot": True})
        ])
        for snap, (state, words, extra) in zip(snaps, cases):
            (line,) = sprint_lines(snap)
            (exchange,) = of_class(line, "div", "sprint-exchange")
            self.assertEqual([full(n) for n in of_class(exchange, "span", "message-state")],
                             [words])
            actions = [full(n) for n in of_class(exchange, "p", "message-action")]
            self.assertEqual(actions, [NUDGE_ACTION_TEXT] if state == "not_picked_up" else [])
            self.assertNotIn("delivered", full(line))

    def test_a_new_reply_is_marked_new_in_its_block(self) -> None:
        reply = {"reply": REPLY_TEXT, "reply_at": "2026-11-12T10:07:00+00:00"}
        fresh, old = render([
            START, {"frame": life_frame([life_entry(3, "replied", "replied", new=True, **reply)])},
            {"snapshot": True},
            {"frame": life_frame([life_entry(3, "replied", "replied", new=False, **reply)])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(fresh)
        self.assertEqual([full(n) for n in of_class(line, "span", "message-new")], ["new"])
        (line,) = sprint_lines(old)
        self.assertEqual(of_class(line, "span", "message-new"), [])

    def test_the_tell_box_says_what_will_happen_before_sending(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([LIFE_SPRINT])}, {"click": "tell-open"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        (box,) = of_class(line, "div", "sprint-tell")
        (hint,) = of_class(box, "p", "tell-hint")
        self.assertEqual(full(hint), HINT_TEXT)
        self.assertEqual([p for p in snap["posts"] if p["url"] == "/api/message"], [])

    def test_a_new_reply_is_announced_under_the_statement_and_not_counted(self) -> None:
        said = "New reply from the manager of " + TITLE
        statement = {"inbox_items": 1, "headline": "1 thing needs you",
                     "sentence": "One question is waiting."}
        full_view = {**with_sprints([LIFE_SPRINT]), "statement": {**view([])["statement"], **statement},
                     "new_replies_text": said}
        bare_view = {**full_view, "new_replies_text": None}
        told, quiet = render([
            START, {"frame": full_view}, {"snapshot": True},
            {"frame": bare_view}, {"snapshot": True},
        ])
        statement_node = told["statement"]
        (h1,) = [n for n in nodes(statement_node) if n["tag"] == "h1"]
        self.assertEqual(full(h1), "1 thing needs you")
        self.assertTrue(has_class(h1, "needs"))
        kids = [c for c in statement_node["children"] if c["tag"] in ("h1", "p")]
        (note,) = [c for c in kids if has_class(c, "new-replies")]
        self.assertEqual(full(note), said)
        self.assertGreater(kids.index(note), max(i for i, c in enumerate(kids) if has_class(c, "sub")))
        self.assertEqual([n for n in nodes(quiet["statement"]) if has_class(n, "new-replies")], [])

    def test_a_reply_to_a_sprint_that_then_ended_opens_from_its_finished_line(self) -> None:
        mark = "c" * 16
        reply = {"reply": REPLY_TEXT, "reply_at": "2026-11-12T10:07:00+00:00"}

        def frame_with(fresh: bool) -> dict:
            messages = [life_entry(3, "picked_up", "picked up"),
                        life_entry(4, "replied", "replied", new=fresh, **reply)]
            ended = {**ended_sprint("c", 10 * 60000, CLOSING), "messages": messages,
                     "tell_text": None}
            return {**with_sprints([ended]),
                    "new_replies_text": "New reply from the manager of Sprint c" if fresh else None}

        closed, listed, opened = render([
            START, {"frame": frame_with(True)}, {"snapshot": True},
            {"open": "finished"}, {"snapshot": True},
            {"open": "ended:" + mark}, {"snapshot": True},
        ])
        (note,) = [n for n in nodes(closed["statement"]) if has_class(n, "new-replies")]
        self.assertEqual(full(note), "New reply from the manager of Sprint c")
        for snap in (closed, listed, opened):
            (fold,) = of_class(snap["projects"], "details", "finished-list")
            (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
            self.assertEqual(summary["text"], "Finished sprints (1)")
            self.assertEqual([full(n) for n in of_class(summary, "span", "message-new")],
                             ["new reply"])
        (line,) = of_class(listed["projects"], "li", "finished-line")
        head = [n for n in nodes(line) if n["tag"] == "summary"][0]
        self.assertEqual([full(n) for n in of_class(head, "span", "message-new")], ["new reply"])
        self.assertNotIn(REPLY_TEXT, visible_text(listed["projects"]))
        (line,) = of_class(opened["projects"], "li", "finished-line")
        (body,) = of_class(line, "div", "finished-messages")
        self.assertEqual([c["cls"] for c in body["children"]],
                         ["sprint-exchange", "sprint-earlier"])
        (report,) = of_class(line, "div", "closing-report")
        flat = nodes(line)
        (exchange,) = of_class(line, "div", "sprint-exchange")
        self.assertLess(flat.index(report), flat.index(exchange))
        self.assertEqual([full(n) for n in of_class(exchange, "p", "message-reply")],
                         ["Manager: " + REPLY_TEXT])
        self.assertEqual([full(n) for n in of_class(exchange, "span", "message-new")], ["new"])
        (earlier,) = of_class(line, "details", "sprint-earlier")
        self.assertFalse(earlier["open"])
        (esum,) = [c for c in earlier["children"] if c["tag"] == "summary"]
        self.assertEqual(full(esum), "Earlier messages (1)")
        self.assertEqual(of_class(line, "button", "tell-open"), [])
        (plain,) = render([START, {"frame": frame_with(False)}, {"open": "finished"},
                           {"open": "ended:" + mark}, {"snapshot": True}])
        self.assertEqual(nodes_of_class(plain["projects"], "message-new"), [])
        self.assertEqual(nodes_of_class(plain["statement"], "new-replies"), [])

    def test_a_new_reply_on_an_older_message_is_marked_on_the_closed_earlier_fold(self) -> None:
        reply = {"reply": REPLY_TEXT, "reply_at": "2026-11-12T10:07:00+00:00"}

        def frame_with(fresh: bool) -> dict:
            return life_frame([life_entry(3, "replied", "replied", new=fresh, **reply),
                               life_entry(4, "picked_up", "picked up"),
                               life_entry(5, "sent", "sent")])

        fresh, old = render([
            START, {"frame": frame_with(True)}, {"snapshot": True},
            {"frame": frame_with(False)}, {"snapshot": True},
        ])
        (line,) = sprint_lines(fresh)
        (fold,) = of_class(line, "details", "sprint-earlier")
        self.assertFalse(fold["open"])
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual([full(n) for n in of_class(summary, "span", "message-new")], ["new reply"])
        (exchange,) = of_class(line, "div", "sprint-exchange")
        self.assertEqual(of_class(exchange, "span", "message-new"), [])
        (line,) = sprint_lines(old)
        (fold,) = of_class(line, "details", "sprint-earlier")
        self.assertEqual(of_class(fold, "span", "message-new"), [])

    def test_a_new_reply_mark_in_a_summary_is_set_off_from_the_words_before_it(self) -> None:
        # The harness applies no CSS: the summaries are not flex boxes, so the span needs its own margin.
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        for selector in (".finished-list > summary .message-new", ".sprint-earlier summary .message-new"):
            merged = {k: v for s, d in rules if s == selector for k, v in d.items()}
            self.assertEqual(merged.get("margin-left"), "10px", selector)

    def test_the_new_marks_are_never_peach(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        found = 0
        for body in re.findall(r"(?s)<style>(.*?)</style>", text):
            css = re.sub(r"(?s)/\*.*?\*/", "", body)
            for selector, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if ".new-replies" in selector or ".message-new" in selector:
                    found += 1
                    self.assertNotIn("var(--peach)", rule)
        self.assertGreater(found, 0)


MORE_KEY = "more:" + "a" * 16
DETAIL_KEY = "sprint:" + "a" * 16


def in_line(line: dict, tag: str, cls: str) -> list:
    return [n for n in visible(line) if n["tag"] == tag and has_class(n, cls)]


def more_fold(line: dict) -> dict:
    (found,) = [n for n in nodes(line) if n["tag"] == "details" and n["key"] == MORE_KEY]
    return found


class PageSprintControlsTest(unittest.TestCase):
    def test_a_sprint_shows_tell_the_manager_and_more_until_used(self) -> None:
        bare, telling, more = render([
            START, {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"click": "tell-open"}, {"snapshot": True},
            {"open": MORE_KEY}, {"snapshot": True},
        ])
        (line,) = sprint_lines(bare)
        self.assertEqual([n for n in visible(line) if n["tag"] == "textarea"], [])
        self.assertEqual([n for n in visible(line) if has_class(n, "withdraw")], [])
        (opener,) = in_line(line, "button", "tell-open")
        self.assertEqual(full(opener), "Tell the manager")
        fold = more_fold(line)
        self.assertFalse(fold["open"])
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "Withdraw")
        self.assertEqual(telling["active"], "tell")
        (line,) = sprint_lines(telling)
        (field,) = in_line(line, "textarea", "tell")
        self.assertTrue(field["focused"])
        (send,) = in_line(line, "button", "tell-send")
        self.assertEqual(full(send), "Send")
        self.assertEqual(in_line(line, "button", "tell-open"), [])
        (line,) = sprint_lines(more)
        (withdraw,) = in_line(line, "button", "withdraw")
        self.assertEqual(full(withdraw), "Withdraw")

    def test_the_work_column_names_its_folds_by_what_they_hold(self) -> None:
        (snap,) = render([
            START,
            {"frame": with_sprints([
                {**LIFE_SPRINT, "messages": [], "reach_text": None},
                {**running_sprint("b"), "stoppable": False}])},
            {"snapshot": True},
        ])
        words = []
        for block in sprint_lines(snap):
            words.append([full(n["children"][0]) for n in nodes(block)
                          if n["tag"] == "details" and (has_class(n, "sprint-detail")
                                                         or has_class(n, "sprint-more"))])
        self.assertEqual(words, [["Show the report", "Stop or withdraw"],
                                 ["Show the goal", "Withdraw"]])
        summaries = {full(n) for n in nodes(snap["projects"]) if n["tag"] == "summary"}
        self.assertEqual(summaries & {"Detail", "More"}, set())

    def test_the_report_fold_holds_the_managers_status_line(self) -> None:
        reported_now = {**REPORTED, "now_text": "building 1 of 2: Importer resumes"}
        (snap,) = render([
            START,
            {"frame": with_sprints([reported_now, {**SPRINT, "sprint_id": "c" * 16}])},
            {"snapshot": True},
        ])
        first, second = sprint_lines(snap)
        (fold,) = detail_nodes(first)
        status = fold["children"][1]
        self.assertEqual((status["tag"], status["cls"], full(status)),
                         ("p", "report-status", REPORTED["status"]))
        outside = [n for n in nodes(first) if full(n) == REPORTED["status"]
                   and n["tag"] == "p" and not has_class(n, "report-status")]
        self.assertEqual(outside, [])
        self.assertEqual(of_class(second, "p", "report-status"), [])

    def test_escape_or_leaving_an_empty_field_closes_it(self) -> None:
        escaped, left, within = render([
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
            {"key": "Escape", "on": "tell"}, {"snapshot": True},
            {"click": "tell-open"}, {"blur_on": "tell"}, {"snapshot": True},
            {"click": "tell-open"}, {"blur_on": "tell", "to": "tell-send"}, {"snapshot": True},
        ])
        for snap in (escaped, left):
            (line,) = sprint_lines(snap)
            self.assertEqual(in_line(line, "textarea", "tell"), [])
            self.assertEqual(len(in_line(line, "button", "tell-open")), 1)
        self.assertEqual(escaped["active"], "tell-open")
        (line,) = sprint_lines(within)
        self.assertEqual(len(in_line(line, "textarea", "tell")), 1)

    def test_a_draft_keeps_the_field_open(self) -> None:
        streamed, left, escaped, again = render([
            START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"type": {"class": "tell", "text": TELL_TEXT}},
            {"blur_on": "tell"}, {"snapshot": True},
            {"key": "Escape", "on": "tell"}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
        ])
        self.assertTrue(tell_field(streamed)["focused"])
        self.assertEqual(streamed["active"], "tell")
        for snap in (left, escaped, again):
            self.assertEqual(tell_field(snap)["value"], TELL_TEXT)

    def test_more_keeps_withdraw_and_its_failure_shows_closed(self) -> None:
        refusal = {"status": 409, "text": "this sprint is not open\n"}
        sending, streamed, failed = render([
            START, {"frame": with_sprints([SPRINT])}, {"open": MORE_KEY}, {"hold": True},
            {"click": "withdraw"}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"release": refusal}, {"snapshot": True},
        ])
        for snap in (sending, streamed, failed):
            (line,) = sprint_lines(snap)
            self.assertTrue(more_fold(line)["open"])
        for snap, disabled in ((sending, True), (streamed, True), (failed, False)):
            (line,) = sprint_lines(snap)
            (withdraw,) = in_line(line, "button", "withdraw")
            self.assertEqual(withdraw["disabled"], disabled)
        closed, failed = render([
            START, {"frame": with_sprints([SPRINT])}, {"open": MORE_KEY}, {"hold": True},
            {"click": "withdraw"}, {"close": MORE_KEY},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
            {"release": refusal}, {"snapshot": True},
        ])
        for snap in (closed, failed):
            (line,) = sprint_lines(snap)
            self.assertFalse(more_fold(line)["open"])
        self.assertIn("Could not withdraw: this sprint is not open", visible_text(line))

    def test_a_failed_manager_start_and_its_retry_need_no_opening(self) -> None:
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
        self.assertIn(reason, visible_text(line))
        (again,) = in_line(line, "button", "retry")
        self.assertFalse(again["disabled"])
        self.assertIn("Could not retry: this sprint has a manager", visible_text(line))
        self.assertEqual(in_line(line, "button", "withdraw"), [])
        self.assertEqual([n for n in visible(line) if n["tag"] == "textarea"], [])

    def test_the_newest_message_shows_and_the_rest_sit_in_the_earlier_fold(self) -> None:
        many = {**SPRINT, "messages": PageMessageTest.messages(None), "reach_text": None}
        one = {**SPRINT, "messages": [message_entry(3, "text", "sent")], "reach_text": None}
        closed, opened, single = render([
            START, {"frame": with_sprints([many])}, {"snapshot": True},
            {"open": EARLIER_KEY}, {"snapshot": True},
            {"frame": with_sprints([one])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(closed)
        shown = visible_text(line)
        self.assertIn("a third note", shown)
        self.assertIn("Manager: " + REPLY_TEXT, shown)
        self.assertNotIn(TELL_TEXT, shown)
        self.assertNotIn("Approved version 2", shown)
        (line,) = sprint_lines(opened)
        shown = visible_text(line)
        self.assertIn(TELL_TEXT, shown)
        self.assertIn("Approved version 2", shown)
        (line,) = sprint_lines(single)
        self.assertIn(TELL_TEXT, visible_text(line))
        (fold,) = [n for n in nodes(line) if n["key"] == DETAIL_KEY]
        self.assertEqual([c["cls"] for c in fold["children"]], ["", "sprint-goal-full"])


STALL = {
    "type": "inbox_item", "reason": "manager", "key": "manager/" + "a" * 16,
    "project_id": "owner/p00", "sprint_id": "a" * 16, "goal": "make the importer resumable",
    "headline": "managers keep failing on make the importer resumable",
    "last_reason": "the manager was gone again", "answered": False,
    "waiting_since": "2026-11-10T08:00:00+00:00",
}


PROGRESS = {
    "type": "inbox_item", "reason": "progress", "key": "progress/" + "a" * 16,
    "project_id": "owner/p00", "sprint_id": "a" * 16, "goal": "make the importer resumable",
    "headline": "the manager has stopped making progress on make the importer resumable",
    "last_status": "two slices are building", "answered": False,
    "waiting_since": "2026-11-10T08:00:00+00:00",
}


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

    def test_a_stall_card_shows_its_headline_reason_and_try_again_posts_the_retry(self) -> None:
        (snap,) = render([
            START, {"frame": frame([STALL])},
            {"respond": {"status": 409, "text": "this sprint has a manager\n"}},
            {"click": "try-again"}, {"snapshot": True},
        ])
        (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "stall")]
        self.assertEqual(card["tag"], "article")
        self.assertTrue(has_class(card, "card"))
        self.assertIn("managers keep failing on make the importer resumable", full(card))
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "reason")],
                         ["the manager was gone again"])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/retry-manager"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p00", "sprint_id": "a" * 16})
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "fail")],
                         ["Could not try again: this sprint has a manager"])
        self.assertEqual([full(n) for n in nodes(card) if n["tag"] == "button"],
                         ["Try again", "Withdraw"])

    def test_both_manager_items_style_the_keep_going_choice_primary_and_withdraw_quiet(self) -> None:
        for item, keep, away in ((STALL, "try-again", "stall-withdraw"),
                                 (PROGRESS, "continue", "progress-withdraw")):
            with self.subTest(item=item["reason"]):
                (snap,) = render([START, {"frame": frame([item])}, {"snapshot": True}])
                (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "card")]
                first, second = [n for n in nodes(card) if n["tag"] == "button"]
                self.assertTrue(has_class(first, keep))
                self.assertTrue(has_class(first, "primary") and has_class(first, "needs"))
                self.assertTrue(has_class(second, away))
                self.assertFalse(has_class(second, "primary") or has_class(second, "needs"))
                (act,) = [n for n in nodes(card) if has_class(n, "act")]
                self.assertEqual([n for n in nodes(act) if n["tag"] == "button"], [first, second])

    def test_the_quiet_withdraw_buttons_share_the_page_button_rules(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        style = text[text.index("<style>"):text.index("</style>")]
        for name in ("continue", "progress-withdraw", "try-again", "stall-withdraw"):
            with self.subTest(name=name):
                for suffix in ("", ":hover:enabled", ":disabled"):
                    self.assertRegex(style, r"(?m)^[^{]*\." + re.escape(name) + re.escape(suffix) + r"[,\s{]")
        self.assertRegex(style, r"\.card \.reason \{[^}]*color: var\(--ov2\)")

    def test_a_stall_card_withdraw_posts_the_withdrawal(self) -> None:
        (snap,) = render([
            START, {"frame": frame([STALL])}, {"click": "stall-withdraw"}, {"snapshot": True},
        ])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/withdraw"]
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p00", "sprint_id": "a" * 16})
        self.assertEqual(
            [p["url"] for p in snap["posts"] if p["url"] == "/api/retry-manager"], [])

    def test_a_progress_card_shows_its_headline_status_and_continue_posts(self) -> None:
        (snap,) = render([
            START, {"frame": frame([PROGRESS])},
            {"respond": {"status": 409, "text": "this sprint's manager is not waiting for you\n"}},
            {"click": "continue"}, {"snapshot": True},
        ])
        (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "progress")]
        self.assertEqual(card["tag"], "article")
        self.assertTrue(has_class(card, "card"))
        self.assertIn(PROGRESS["headline"], full(card))
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "reason")],
                         ["two slices are building"])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/continue"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p00", "sprint_id": "a" * 16})
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "fail")],
                         ["Could not continue: this sprint's manager is not waiting for you"])
        self.assertEqual([full(n) for n in nodes(card) if n["tag"] == "button"],
                         ["Continue", "Withdraw"])

    def test_a_progress_card_withdraw_posts_the_withdrawal(self) -> None:
        (snap,) = render([
            START, {"frame": frame([PROGRESS])}, {"click": "progress-withdraw"},
            {"snapshot": True},
        ])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/withdraw"]
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p00", "sprint_id": "a" * 16})
        self.assertEqual([p["url"] for p in snap["posts"] if p["url"] == "/api/continue"], [])

    def test_a_sprint_waiting_on_quota_reads_until_its_reset(self) -> None:
        (snap,) = render([
            START,
            {"frame": with_sprints([{
                **SPRINT, "state": "quota", "state_text": "waiting on quota until",
                "state_until": "2026-11-13T09:30:00+00:00",
            }])},
            {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertNotIn("waiting on quota until", full(line))
        self.assertIn("Fri 09:30", full(line))

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
            self.assertEqual(full(fold["children"][0]), "Show the report")

    def test_a_reported_sprint_line_reads_state_progress_status_and_age(self) -> None:
        quiet = {**REPORTED, "state": "quiet", "state_text": "quiet for 16 min — may be stuck",
                 "ball": "nobody", "ball_text": "nothing running, may be stuck"}
        snap, stuck = render([
            {"start": {"focused": False, "clock": NOW_MS}},
            {"frame": with_sprints([REPORTED])}, {"snapshot": True},
            {"frame": with_sprints([quiet])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        for expected in ("manager working", "3 of 7", "two slices are building", "4 min ago"):
            self.assertIn(expected, top_text(line))
        self.assertNotIn("on track", top_text(line))
        self.assertIn("3 of 7 landed, 2 in delivery, 2 queued", full(detail(line)))
        (line,) = sprint_lines(stuck)
        self.assertIn("nothing running, may be stuck", top_text(line))
        self.assertNotIn("quiet for 16 min", top_text(line))
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

    def test_a_sprint_without_a_report_holds_only_its_goal_in_the_detail(self) -> None:
        (snap,) = render([START, {"frame": with_sprints([SPRINT])}, {"snapshot": True}])
        (line,) = sprint_lines(snap)
        (fold,) = detail_nodes(line)
        self.assertEqual([c["cls"] for c in fold["children"]], ["", "sprint-goal-full"])
        self.assertEqual(full(fold["children"][0]), "Show the goal")
        for cls in ("progress", "status", "report-status"):
            self.assertEqual([n for n in nodes(line) if has_class(n, cls)], [])


CLOSING = {
    "at": "2026-11-12T11:00:00+00:00", "summary": "The importer now resumes after a crash.",
    "first_line": "Importer resumes after a crash", "differently": "cut smaller slices",
    "landed": [12], "held": [], "dropped": [13], "counts_text": "1 landed, 1 dropped",
}
ASK = ("Stop this sprint? The manager finishes what is mid-merge, starts nothing new "
       "and reports.")
DONE_SPRINT = {
    **SPRINT, "state": "done", "state_text": "done", "stoppable": False,
    "ended_at": "2026-11-12T11:00:00+00:00", "closing": CLOSING,
    "ball": None, "ball_text": None, "now_text": None,
}


def of_class(line: dict, tag: str, cls: str) -> list:
    return [n for n in nodes(line) if n["tag"] == tag and has_class(n, cls)]


def nodes_of_class(line: dict, cls: str) -> list:
    return [n for n in nodes(line) if has_class(n, cls)]


def ended_sprint(mark: str, ago_ms: int, closing: dict | None = None,
                 state_text: str = "done") -> dict:
    return {
        **SPRINT, "sprint_id": mark * 16, "title": "Sprint " + mark,
        "state": "stopped" if state_text.startswith("stopped") else "done",
        "state_text": state_text, "stoppable": False, "ended_at": utc(ago_ms),
        "closing": closing, "ball": None, "ball_text": None, "now_text": None,
    }


def running_sprint(mark: str, **more) -> dict:
    return {**SPRINT, "sprint_id": mark * 16, "title": "Sprint " + mark, "stoppable": True, **more}


def two_projects(first: list, second: list, finished: dict | None = None) -> dict:
    entry = {**project(1, []), "sprints": second}
    if finished is not None:
        entry["finished_sprints"] = finished
    return view([{**project(0, []), "sprints": first}, entry])


HOUR_MS = 3600000


class PageSprintBlockTest(unittest.TestCase):
    def test_each_running_sprint_is_one_block_holding_its_project_and_every_control(self) -> None:
        a = running_sprint("a")
        b = running_sprint("b", retry=True)
        (snap,) = render([
            START, {"frame": two_projects([a], [b])}, {"open": "more:" + "a" * 16},
            {"snapshot": True},
        ])
        projects = snap["projects"]
        (blocks,) = of_class(projects, "ul", "sprint-blocks")
        lines = [n for n in nodes(projects) if n["tag"] == "li" and has_class(n, "sprint")]
        self.assertEqual(len(lines), 2)
        self.assertEqual([c for c in blocks["children"] if has_class(c, "sprint")], lines)
        for block, project_id in zip(lines, ("owner/p00", "owner/p01")):
            self.assertEqual([full(n) for n in of_class(block, "span", "sp-project")], [project_id])
            self.assertEqual([full(n) for n in of_class(block, "p", "sp-now")],
                             ["two slices are building"])
            self.assertEqual([full(n) for n in of_class(block, "span", "sprint-ball")],
                             ["manager working"])
        first, second = lines
        for tag, cls in (("button", "tell-open"), ("button", "stop"), ("button", "withdraw"),
                         ("details", "sprint-detail")):
            self.assertEqual(len(of_class(first, tag, cls)), 1, cls)
        self.assertEqual(len(of_class(second, "button", "retry")), 1)
        for row in of_class(projects, "li", "line"):
            self.assertEqual([n for n in nodes(row) if has_class(n, "sprint")], [])

    def test_running_sprints_render_before_the_finished_list(self) -> None:
        done = ended_sprint("c", HOUR_MS, CLOSING)
        (snap,) = render([
            START,
            {"frame": view([{**project(0, [session("s1", "working", "working")]),
                             "sprints": [done, running_sprint("a")]}])},
            {"snapshot": True},
        ])
        flat = nodes(snap["projects"])
        first = next(i for i, n in enumerate(flat) if n["tag"] == "li" and has_class(n, "sprint"))
        listing = next(i for i, n in enumerate(flat) if n["tag"] == "ul"
                       and any(has_class(c, "line") for c in n["children"]))
        finished = next(i for i, n in enumerate(flat)
                        if n["tag"] == "details" and has_class(n, "finished-list"))
        self.assertLess(first, listing)
        self.assertLess(listing, finished)
        for block in of_class(snap["projects"], "li", "sprint"):
            self.assertNotIn("Sprint c", full(block))

    def test_ended_sprints_fold_into_one_finished_list_one_line_each(self) -> None:
        counted = {**CLOSING, "counts_text": "2 landed"}
        finished = {"label": "Finished sprints", "count": 1,
                    "sprints": [ended_sprint("f", 48 * HOUR_MS)]}
        frame = two_projects(
            [ended_sprint("c", HOUR_MS, counted),
             ended_sprint("d", 3 * HOUR_MS, None, "stopped by you")],
            [ended_sprint("e", 2 * HOUR_MS)], finished)
        closed, opened, line_open = render([
            START, {"frame": frame}, {"snapshot": True}, {"open": "finished"}, {"snapshot": True},
            {"open": "ended:" + "c" * 16}, {"snapshot": True},
        ])
        for snap in (closed, opened, line_open):
            (fold,) = of_class(snap["projects"], "details", "finished-list")
            (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
            self.assertEqual(full(summary), "Finished sprints (4)")
            starts = [n for n in nodes(snap["projects"]) if n["tag"] == "summary"
                      and full(n).startswith("Finished sprints")]
            self.assertEqual(len(starts), 1)
        self.assertFalse(of_class(closed["projects"], "details", "finished-list")[0]["open"])
        rows = of_class(opened["projects"], "li", "finished-line")
        self.assertEqual(len(rows), 4)
        expected = [("Sprint c", "2 landed"), ("Sprint e", "done"),
                    ("Sprint d", "stopped by you"), ("Sprint f", "done")]
        for row, (title, outcome) in zip(rows, expected):
            (summary,) = [n for n in nodes(row) if n["tag"] == "summary"]
            self.assertEqual([full(n) for n in of_class(summary, "span", "title-line")], [title])
            self.assertEqual([full(n) for n in of_class(summary, "span", "outcome")], [outcome])
            (ended,) = of_class(summary, "span", "ended")
            self.assertIn("ended", full(ended))
            self.assertEqual(len([n for n in nodes(ended) if n["tag"] == "time"]), 1)
        self.assertNotIn(CLOSING["summary"], visible_text(closed["projects"]))
        self.assertNotIn(CLOSING["summary"], visible_text(opened["projects"]))
        self.assertIn(CLOSING["summary"], visible_text(line_open["projects"]))

    def test_a_running_block_never_shows_two_contradicting_states(self) -> None:
        idle = {"session_id": "s1", "name": "m", "state": "idle", "state_text": "idle",
                "cwd": "/srv/p00", "deliveries": []}
        stuck = running_sprint(
            "a", state="on_track", state_text="on track", ball="nobody",
            ball_text="nothing running, may be stuck", sessions=[idle])
        (snap,) = render([START, {"frame": with_sprints([stuck])}, {"snapshot": True}])
        (block,) = sprint_lines(snap)
        shown = visible_text(block)
        self.assertIn("nothing running, may be stuck", shown)
        self.assertNotIn("on track", shown)
        self.assertNotIn("manager idle", shown)
        (mark,) = of_class(block, "span", "sic")
        self.assertTrue(has_class(mark, "sic-dashed"))

    def test_only_the_owner_ball_is_peach(self) -> None:
        sprints = [
            running_sprint("a", ball="manager", ball_text="manager working"),
            running_sprint("b", ball="owner", ball_text="waiting on you"),
            running_sprint("c", ball="nobody", ball_text="nothing running, may be stuck"),
        ]
        (snap,) = render([START, {"frame": with_sprints(sprints)}, {"snapshot": True}])
        tones = []
        for block in sprint_lines(snap):
            (ball,) = of_class(block, "span", "sprint-ball")
            tones.append([t for t in ("st-go", "needs", "st-wait") if has_class(ball, t)])
        self.assertEqual(tones, [["st-go"], ["needs"], ["st-wait"]])

    def test_the_work_heading_counts_only_running_sprints(self) -> None:
        done = ended_sprint("c", HOUR_MS, CLOSING)
        other = ended_sprint("d", 2 * HOUR_MS, CLOSING)
        snaps = render([
            START,
            {"frame": two_projects([running_sprint("a"), done], [other])}, {"snapshot": True},
            {"frame": two_projects([done], [other])}, {"snapshot": True},
            {"frame": two_projects([running_sprint("a")], [running_sprint("b"), other])},
            {"snapshot": True},
        ])
        counts = []
        for snap in snaps:
            (h2,) = [n for n in nodes(snap["projects"]) if n["tag"] == "h2"]
            counts.append([full(c) for c in h2["children"]])
        self.assertEqual(counts, [["1 sprint across 1 project"], [],
                                  ["2 sprints across 2 projects"]])

    def test_the_now_sentence_is_clamped_to_two_lines(self) -> None:
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        merged = {k: v for s, d in style_rules(style) if s == ".sp-now" for k, v in d.items()}
        for name, value in (("grid-column", "2 / -1"), ("display", "-webkit-box"),
                            ("-webkit-box-orient", "vertical"), ("-webkit-line-clamp", "2"),
                            ("line-clamp", "2"), ("overflow", "hidden")):
            self.assertEqual(merged.get(name), value, name)
        (snap,) = render([START, {"frame": with_sprints([REPORTED])}, {"snapshot": True}])
        (now,) = of_class(snap["projects"], "p", "sp-now")
        self.assertEqual(now["title"], full(now))
        self.assertEqual(now["title"], REPORTED["now_text"])

    def test_the_now_sentence_is_a_full_width_line_of_at_most_two_lines(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")

        def with_milestone(state, text):
            return dataclasses.replace(state, report=dataclasses.replace(state.report, milestone=text))

        def sentence(state):
            return view_entry(view_line(state, T0_MS + MIN))["now_text"]

        five = ((1, "building"), (2, "building"), (3, "queued"), (4, "queued"), (5, "queued"))
        fit_stage = sentence(with_milestone(
            reported(started(A), T0_MS, issues=five), "the upload form"))
        self.assertEqual(fit_stage, "building 2 of 5: the upload form")
        asked = dataclasses.replace(reported(started(A), T0_MS), questions=(Question(
            1, 0, iso(T0_MS), False, "Which store should the checkpoint use?",
            "the first slice", ("the database", "a file"), "the database"),))
        fit_question = sentence(asked)
        self.assertEqual(fit_question,
                         "waiting for your answer: Which store should the checkpoint use?")
        fit_long = sentence(with_milestone(
            reported(started(A), T0_MS, issues=five),
            "the importer that resumes a broken transfer from its last good part"))
        self.assertEqual(fit_long, "building 2 of 5: the importer that resumes a broken "
                                   "transfer from its last good part")
        clamped_words = " ".join(["word"] * 80)
        clamped = sentence(with_milestone(reported(started(A), T0_MS), clamped_words))
        self.assertEqual(clamped, "building 1 of 7: " + clamped_words)
        texts = (fit_stage, fit_question, fit_long, clamped)
        frame = with_sprints([
            {**LIFE_SPRINT, "sprint_id": c * 16, "now_text": text, "messages": [],
             "reach_text": None} for c, text in zip("abcd", texts)])
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => [...document.querySelectorAll('#projects li.sprint')].map((li) => {
          const now = li.querySelector('.sp-now');
          const box = (e) => e.getBoundingClientRect().toJSON();
          return {now: box(now), title: box(li.querySelector('.title-line')),
                  head: box(li.querySelector('.sp-head')),
                  lineHeight: parseFloat(getComputedStyle(now).lineHeight),
                  scrollHeight: now.scrollHeight, clientHeight: now.clientHeight,
                  tip: now.title};
        })"""
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                for width in (480, 1440):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.add_init_script(fakes)
                    page.route("http://console.test/", lambda route: route.fulfill(
                        body=html, content_type="text/html"))
                    page.goto("http://console.test/")
                    page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})", frame)
                    got = page.evaluate(measure)
                    self.assertEqual(len(got), 4, width)
                    for text, row in zip(texts, got):
                        now, title, head = row["now"], row["title"], row["head"]
                        at = (width, text)
                        self.assertGreaterEqual(now["top"], title["bottom"] - 1, at)
                        self.assertLessEqual(abs(now["left"] - title["left"]), 1, at)
                        self.assertGreaterEqual(now["width"], title["width"] - 1, at)
                        self.assertGreaterEqual(now["width"], head["right"] - title["left"] - 1, at)
                        self.assertLessEqual(now["height"], 2 * row["lineHeight"] + 1, at)
                        self.assertEqual(row["tip"], text, at)
                        if text is clamped:
                            self.assertGreater(row["scrollHeight"], row["clientHeight"] + 1, at)
                        else:
                            self.assertLessEqual(row["scrollHeight"], row["clientHeight"] + 1, at)
                    page.close()
            finally:
                browser.close()


class PageSprintEndTest(unittest.TestCase):
    def test_stop_asks_to_confirm_then_posts_the_sprint(self) -> None:
        asked, sent = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])},
            {"click": "stop"}, {"snapshot": True},
            {"click": "stop-confirm"}, {"snapshot": True},
        ])
        self.assertEqual([p for p in asked["posts"] if p["url"] == "/api/stop"], [])
        (line,) = sprint_lines(asked)
        self.assertEqual([full(n) for n in of_class(line, "span", "stop-ask")], [ASK])
        self.assertEqual(len(of_class(line, "button", "stop-confirm")), 1)
        (post,) = [p for p in sent["posts"] if p["url"] == "/api/stop"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(
            json.loads(post["body"]), {"project_id": "owner/p00", "sprint_id": "a" * 16}
        )

    def test_stop_sits_under_more_beside_withdraw_and_its_question_on_the_line(self) -> None:
        idle, asked = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"snapshot": True},
            {"click": "stop"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(idle)
        (more,) = of_class(line, "details", "sprint-more")
        self.assertEqual(len(of_class(more, "button", "stop")), 1)
        self.assertEqual(len(of_class(more, "button", "withdraw")), 1)
        self.assertEqual(len(of_class(line, "button", "stop")), 1)
        (line,) = sprint_lines(asked)
        (more,) = of_class(line, "details", "sprint-more")
        self.assertEqual(of_class(more, "span", "stop-ask"), [])
        self.assertEqual(of_class(more, "button", "stop-confirm"), [])
        self.assertEqual(len(of_class(line, "button", "stop-confirm")), 1)

    def test_cancel_sends_nothing_and_restores_stop(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])},
            {"click": "stop"}, {"click": "stop-cancel"}, {"snapshot": True},
        ])
        self.assertEqual([p for p in snap["posts"] if p["url"] == "/api/stop"], [])
        (line,) = sprint_lines(snap)
        self.assertEqual(len(of_class(line, "button", "stop")), 1)
        self.assertEqual(of_class(line, "button", "stop-confirm"), [])

    def test_a_refused_stop_says_why(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])},
            {"click": "stop"},
            {"respond": {"status": 409, "text": "this sprint is already stopping\n"}},
            {"click": "stop-confirm"}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual(
            [full(n) for n in nodes(line) if has_class(n, "fail")],
            ["Could not stop: this sprint is already stopping"],
        )

    def test_a_sprint_that_cannot_be_stopped_has_no_stop_button(self) -> None:
        refused, absent = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": False}])}, {"snapshot": True},
            {"frame": with_sprints([SPRINT])}, {"snapshot": True},
        ])
        for snap in (refused, absent):
            (line,) = sprint_lines(snap)
            self.assertEqual(of_class(line, "button", "stop"), [])
            self.assertEqual(len(of_class(line, "button", "withdraw")), 1)

    def test_a_done_sprint_is_a_finished_line_that_opens_to_its_closing_report(self) -> None:
        closed, opened = render([
            START, {"frame": with_sprints([DONE_SPRINT])}, {"open": "finished"},
            {"snapshot": True}, {"open": "ended:" + "a" * 16}, {"snapshot": True},
        ])
        self.assertEqual(sprint_lines(closed), [])
        (row,) = of_class(closed["projects"], "li", "finished-line")
        self.assertEqual([full(n) for n in of_class(row, "span", "outcome")],
                         ["1 landed, 1 dropped"])
        shown = visible_text(closed["projects"])
        for hidden in (CLOSING["summary"], "cut smaller slices"):
            self.assertNotIn(hidden, shown)
        shown = visible_text(opened["projects"])
        for expected in (CLOSING["summary"], "Would do differently: cut smaller slices",
                         "1 landed, 1 dropped"):
            self.assertIn(expected, shown)

    def test_a_closing_summary_keeps_its_line_breaks_and_an_ended_sprint_draws_no_report_data(
            self) -> None:
        stale = {**REPORTED, **DONE_SPRINT, "state": "done", "state_text": "done",
                 "closing": {**CLOSING, "summary": "first\nsecond"}}
        (snap,) = render([START, {"frame": with_sprints([stale])}, {"snapshot": True}])
        (row,) = of_class(snap["projects"], "li", "finished-line")
        (summary,) = of_class(row, "p", "closing-summary")
        self.assertEqual(full(summary), "first\nsecond")
        for cls in ("status", "status-age", "next", "progress", "sp-prog", "pips",
                    "sprint-issues"):
            self.assertEqual(nodes_of_class(row, cls), [], cls)
        for stale_text in ("two slices are building", "start the resume slice", "in delivery"):
            self.assertNotIn(stale_text, full(row))

    def test_an_opened_finished_line_names_its_landed_held_and_dropped_issues_and_the_tracker(
            self) -> None:
        closing = {**CLOSING, "landed": [12, 14], "held": [15], "dropped": [13]}
        done = {**DONE_SPRINT, "closing": closing, "tracker_url": "https://github.com/o/p/milestone/3"}
        bad = {**done, "tracker_url": "javascript:alert(1)"}
        bare = {**DONE_SPRINT, "closing": {**CLOSING, "landed": [], "held": [], "dropped": []},
                "tracker_url": None}
        good, refused, none = render([
            step for frame in (done, bad, bare)
            for step in ({"frame": with_sprints([frame])}, {"open": "finished"},
                         {"open": "ended:" + "a" * 16}, {"snapshot": True})
        ])
        (row,) = of_class(good["projects"], "li", "finished-line")
        self.assertEqual(
            [(full(n), n["cls"]) for n in of_class(row, "p", "closing-landed")
             + of_class(row, "p", "closing-held") + of_class(row, "p", "closing-dropped")],
            [("Landed: #12, #14", "closing-landed"), ("Held: #15", "closing-held"),
             ("Dropped: #13", "closing-dropped")])
        (link,) = of_class(row, "a", "tracker")
        self.assertEqual(link["href"], "https://github.com/o/p/milestone/3")
        (row,) = of_class(refused["projects"], "li", "finished-line")
        self.assertEqual(of_class(row, "a", "tracker"), [])
        (row,) = of_class(none["projects"], "li", "finished-line")
        self.assertEqual([n for key in ("landed", "held", "dropped")
                          for n in of_class(row, "p", "closing-" + key)], [])
        self.assertEqual(of_class(row, "a", "tracker"), [])

    def test_a_stopped_sprint_reads_its_counts_or_stopped_by_you(self) -> None:
        stopped = {**DONE_SPRINT, "state": "stopped", "state_text": "stopped by you"}
        bare = {**stopped, "closing": None}
        with_report, without = render([
            START, {"frame": with_sprints([stopped])}, {"snapshot": True},
            {"frame": with_sprints([bare])}, {"open": "ended:" + "a" * 16}, {"snapshot": True},
        ])
        (row,) = of_class(with_report["projects"], "li", "finished-line")
        self.assertEqual([full(n) for n in of_class(row, "span", "outcome")],
                         ["1 landed, 1 dropped"])
        (row,) = of_class(without["projects"], "li", "finished-line")
        self.assertEqual([full(n) for n in of_class(row, "span", "outcome")], ["stopped by you"])
        self.assertEqual([full(n) for n in of_class(row, "div", "closing-report")],
                         ["No closing report."])

    def test_a_finished_sprint_with_a_report_and_no_closing_keeps_its_report_and_tracker(
            self) -> None:
        for state, text in (("done", "done"), ("stopped", "stopped by you")):
            with self.subTest(state=state):
                ended = {**REPORTED, **DONE_SPRINT, "state": state, "state_text": text,
                         "closing": None}
                (snap,) = render([
                    START, {"frame": with_sprints([ended])}, {"open": "finished"},
                    {"open": "ended:" + "a" * 16}, {"open": "sprint:" + "a" * 16},
                    {"snapshot": True},
                ])
                (row,) = of_class(snap["projects"], "li", "finished-line")
                shown = visible_text(row)
                self.assertIn("two slices are building", shown)
                self.assertEqual(
                    [full(n) for n in of_class(row, "span", "issue")], ["#12", "#13"])
                (link,) = of_class(row, "a", "tracker")
                self.assertEqual(link["href"], "https://github.com/owner/p00/milestone/3")
                self.assertEqual([full(n) for n in of_class(row, "span", "outcome")], [text])

    def test_a_stop_failure_shows_on_the_line(self) -> None:
        text = "could not stop the manager: boom; trying again"
        (snap,) = render([
            START, {"frame": with_sprints([{**SPRINT, "stop_text": text}])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertEqual([full(n) for n in of_class(line, "span", "stop-fail")], [text])

    def test_a_projects_finished_sprints_join_the_one_finished_list(self) -> None:
        finished = {"label": "Finished sprints", "count": 1, "sprints": [DONE_SPRINT]}
        (snap,) = render([
            START,
            {"frame": view([{**project(0, []), "sprints": [], "finished_sprints": finished}])},
            {"snapshot": True},
        ])
        self.assertEqual(of_class(snap["projects"], "details", "finished"), [])
        (fold,) = of_class(snap["projects"], "details", "finished-list")
        self.assertFalse(fold["open"])
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "Finished sprints (1)")
        (item,) = of_class(fold, "li", "finished-line")
        self.assertIn(DONE_SPRINT["title"], full(item))

    def test_an_ended_sprint_offers_no_message_box(self) -> None:
        stopped = {**DONE_SPRINT, "state": "stopped", "state_text": "stopped by you"}
        for sprint, boxes in ((DONE_SPRINT, 0), (stopped, 0), (SPRINT, 1)):
            with self.subTest(state=sprint["state"], ended=sprint.get("ended_at")):
                (snap,) = render([START, {"frame": with_sprints([sprint])}, {"snapshot": True}])
                offered = (of_class(snap["projects"], "div", "sprint-tell")
                           + of_class(snap["projects"], "button", "tell-open"))
                self.assertEqual(len(offered), boxes)

    def test_an_unstopped_manager_is_shown_under_the_statement(self) -> None:
        text = "The manager of a withdrawn goal could not be stopped: boom; trying again"
        (snap,) = render([
            START,
            {"frame": {**view([]), "unstopped": [{
                "project_id": "owner/p00", "sprint_id": "a" * 16, "goal": GOAL_TEXT,
                "text": text, "failed_at": "2026-11-12T10:00:00+00:00"}]}},
            {"snapshot": True},
        ])
        self.assertEqual([full(n) for n in of_class(snap["statement"], "p", "unstopped")], [text])


class PageSprintGlanceTest(unittest.TestCase):
    def test_a_long_goal_shows_only_in_the_closed_sprint_detail(self) -> None:
        sprint = {**SPRINT, "title": TITLE, "goal": LONG_GOAL}
        asked = question(0, "Which store keeps the checkpoints?", ["sqlite", "files"], "files",
                         title=TITLE)
        shown = {**with_sprints([sprint]), "inbox": {"open": [asked], "answered": []}}
        (snap,) = render([START, {"frame": shown}, {"snapshot": True}])
        self.assertNotIn("g" * 200, visible_text(snap["projects"]))
        self.assertNotIn("g" * 200, visible_text(snap["inbox"]))
        (line,) = sprint_lines(snap)
        self.assertEqual([full(n) for n in nodes(line) if has_class(n, "title-line")], [TITLE])
        (fold,) = of_class(line, "details", "sprint-detail")
        self.assertFalse(fold["open"])
        (goal,) = [n for n in nodes(fold) if has_class(n, "sprint-goal-full")]
        self.assertEqual(full(goal), LONG_GOAL)

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

    def test_only_an_owner_ball_reads_as_needs_you(self) -> None:
        cases = [
            ("manager", "manager working", "sic-play", "st-go"),
            ("owner", "waiting on you", "sic-pause", "needs"),
            ("nobody", "nothing running, may be stuck", "sic-dashed", "st-wait"),
        ]
        steps = [START]
        for ball, words, _, _ in cases:
            steps += [{"frame": with_sprints([{**REPORTED, "ball": ball, "ball_text": words}])},
                      {"snapshot": True}]
        for (ball, words, icon_class, tone), snap in zip(cases, render(steps)):
            with self.subTest(ball=ball):
                (line,) = sprint_lines(snap)
                (said,) = [n for n in top(line) if has_class(n, "sprint-ball")]
                self.assertEqual(full(said), words)
                self.assertIs(has_class(said, "needs"), ball == "owner")
                self.assertTrue(has_class(said, tone))
                (mark,) = [n for n in top(line) if has_class(n, "sic")]
                self.assertTrue(has_class(mark, icon_class))
                self.assertTrue(has_class(mark, tone))
                self.assertIs(has_class(mark, "needs"), ball == "owner")
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        rules = style_rules(style)
        for marker, colour in ((".sprint-ball.needs", "var(--peach)"), (".st-go", "var(--green)"),
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
        self.assertEqual([n for n in top(line) if has_class(n, "manager-now")], [])
        self.assertFalse(detail(line)["open"])
        (line,) = sprint_lines(opened)
        self.assertIn(name, visible_text(line))
        (row,) = [n for n in nodes(detail(line)) if has_class(n, "sprint-session")]
        self.assertIn(name, full(row))
        self.assertIn("working", full(row))
        (line,) = sprint_lines(later)
        self.assertTrue(detail(line)["open"])
        (row,) = [n for n in nodes(detail(line)) if has_class(n, "sprint-session")]
        self.assertIn("idle", full(row))
        self.assertEqual([n for n in top(line) if has_class(n, "manager-now")], [])

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

    def test_the_now_sentence_spans_the_text_columns_of_the_head_grid(self) -> None:
        # Grid auto-placement would put it in the 16px icon column; the harness applies no CSS.
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        merged = {k: v for s, d in style_rules(style) if s == ".sp-now" for k, v in d.items()}
        self.assertEqual(merged.get("grid-column"), "2 / -1")

    def test_an_unknown_sprint_ball_fails_loud(self) -> None:
        for ball in ("bogus", "constructor", None):
            sprint = {**REPORTED, "ball": ball}
            with self.subTest(ball=ball):
                with self.assertRaisesRegex(AssertionError, "unknown sprint ball"):
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
        frame = view([{**project(0, [session("s1", "working", "working")]), "sprints": [SPRINT]},
                      group], count=5)
        (snap,) = render([START, {"frame": frame}, {"snapshot": True}])
        buttons = [n for n in nodes(snap["projects"]) if has_class(n, "give-goal")]
        self.assertEqual(len(buttons), 4)
        (folded,) = [n for n in nodes(snap["projects"]) if n["key"] == "quiet"]
        self.assertEqual([n for n in nodes(folded) if has_class(n, "give-goal")], buttons)
        (busy,) = [n for n in nodes(snap["projects"])
                   if n["tag"] == "li" and any(m["key"] == "line:owner/p00" for m in nodes(n))]
        self.assertEqual([n for n in nodes(busy) if has_class(n, "give-goal")], [])

    def test_a_project_with_nothing_under_it_draws_no_heading(self) -> None:
        frame = view([
            {**project(0, []), "sprints": [running_sprint("a")]},
            project(1, [session("s1", "working", "working")]),
            project(2, []),
            project(3, [], quiet=True, ago=timedelta(days=3)),
        ])
        (snap,) = render([START, {"frame": frame}, {"snapshot": True}])
        projects = snap["projects"]
        keys = {n["key"] for n in nodes(projects)
                if n["tag"] == "details" and (n["key"] or "").startswith("line:")}
        self.assertEqual(keys, {"line:owner/p01", "line:owner/p03"})
        self.assertEqual([full(n) for n in nodes(projects) if has_class(n, "sp-project")],
                         ["owner/p00"])
        self.assertEqual([full(n) for n in nodes(projects) if has_class(n, "pname")],
                         ["owner/p01", "owner/p03"])

    def test_a_project_is_a_block_headed_by_its_name(self) -> None:
        (snap,) = render([START, {"frame": view([
            project(0, [session("s1", "working", "working")]),
            project(1, [session("s2", "working", "working")])])},
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
    "project_id": "owner/p01", "sprint_id": "a" * 16, "title": TITLE, "version": 2,
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
    def test_a_brief_leads_with_its_title_and_keeps_the_goal_one_click_away(self) -> None:
        known = {**with_sprints([{**SPRINT, "goal": GOAL_TEXT}]),
                 "inbox": {"open": [BRIEF, ANSWERABLE], "answered": []}}
        (snap,) = render([START, {"frame": known}, {"snapshot": True}])
        first = snap["inbox"]["children"][0]
        self.assertEqual(first["tag"], "article")
        self.assertTrue(has_class(first, "brief"))
        (line,) = [n for n in nodes(first) if n["tag"] == "p" and has_class(n, "title-line")]
        self.assertEqual(full(line), TITLE)
        (fold,) = [n for n in nodes(first) if n["tag"] == "details" and has_class(n, "brief-goal")]
        self.assertFalse(fold["open"])
        self.assertEqual(fold["key"], "brief-goal:" + "a" * 16)
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "The goal")
        self.assertIn(GOAL_TEXT, full(fold))
        self.assertNotIn(GOAL_TEXT, visible_text(first))
        words = full(first)
        self.assertIn("owner/p01 brief, version 2", visible_text(first))
        at = 0
        for needle in (TITLE, LABELS[0], "the importer resumes", LABELS[1], "no new formats",
                       LABELS[2], "checkpoint", "resume", LABELS[3], "partial writes",
                       LABELS[4], "which store?"):
            found = words.find(needle, at)
            self.assertGreaterEqual(found, 0, needle)
            at = found + len(needle)
        self.assertIn("Which host?", full(snap["inbox"]))

    def test_a_brief_whose_sprint_is_unknown_shows_no_goal_fold(self) -> None:
        (snap,) = render([START, {"frame": frame([BRIEF, ANSWERABLE])}, {"snapshot": True}])
        (first,) = [n for n in snap["inbox"]["children"][:1]]
        self.assertEqual([n for n in nodes(first) if has_class(n, "brief-goal")], [])

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

    def test_the_hint_follows_a_brief_row_as_it_folds_and_unfolds(self) -> None:
        # The hint sits on the summary while the row is closed and on the card while it is open;
        # folding or unfolding the row by hand moves it with no redraw in between (DR-003).
        def holder(snap: dict) -> str:
            (strip,) = keys_of(snap)
            (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "details" and has_class(n, "brief-row")]
            (found,) = [c for c in nodes(row) if any(k is strip for k in c["children"])]
            return found["tag"]

        opened, folded, again = render([
            START, {"frame": frame([BRIEF, BRIEF_B])}, {"open": KEY_B}, {"key": "Enter"},
            {"snapshot": True}, {"close": KEY_B}, {"snapshot": True},
            {"open": KEY_B}, {"snapshot": True}])
        self.assertEqual([holder(opened), holder(folded), holder(again)], ["article", "summary", "article"])

    def test_a_register_row_head_keeps_the_flex_layout_of_a_card_head(self) -> None:
        # The harness applies no CSS: a head inside li.row needs the card head's flex layout, gaps
        # and right-aligned wait, or later registration rows run their spans together (DR-002).
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        merged: dict = {}
        for selector in (".card .head", ".rest .head"):
            found = {}
            for name, decls in style_rules(style):
                if name == selector:
                    found.update(decls)
            merged[selector] = found
        self.assertEqual(merged[".rest .head"], merged[".card .head"])
        self.assertEqual(merged[".rest .head"].get("display"), "flex")
        self.assertTrue([d for s, d in style_rules(style) if s == ".head .wait" and d.get("margin-left") == "auto"])

    def test_a_collapsed_row_title_wraps_a_long_unbroken_goal(self) -> None:
        # A goal with a long unbroken token (a filename) sits in a flex item <b>; without
        # overflow-wrap the row grows past a 480px viewport, as .brief .goal-line already avoids.
        style = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))[0]
        merged: dict = {}
        for selector, decls in style_rules(style):
            if selector == ".row-head b":
                merged.update(decls)
        self.assertEqual(merged.get("overflow-wrap"), "anywhere")

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
        self.assertEqual(texts[:3], ["Brief", TITLE, "owner/p01"])
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
                holders = [n for n in nodes(snap["inbox"]) if has_class(n, "card") or has_class(n, "row")]
                self.assertTrue([h for h in holders if id(strip) in {id(n) for n in nodes(h)}])
                self.assertIsNot(snap["inbox"]["children"][-1], strip)
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

    def test_the_goal_field_shows_one_border_in_focus(self) -> None:
        top = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", self.style)
        rules = style_rules(top)
        self.assertTrue([
            d for s, d in rules
            if s == ".goal-in .goal-text:focus-visible" and d.get("outline") in ("none", "0")])
        self.assertTrue([
            d for s, d in rules
            if s == ".goal-in:focus-within" and d.get("border-color") == "var(--lav)"])

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


def si(state: str, days, ask: bool = False, ever=None) -> dict:
    return {"state": state, "ends_at": None, "days_left": days, "ask": ask, "since": None,
            "ever_signed_in": state == "signed_in" if ever is None else ever}


SIGNIN = {
    "type": "inbox_item", "reason": "signin", "key": "signin/work", "project_id": None,
    "profile": "work", "headline": "Sign in to work again",
    "action": "signin", "run": None, "signin": si("signed_in", 2, ask=True),
    "answered": False, "waiting_since": "2026-11-12T08:00:00+00:00",
}
ANSWER = "{\"attempt\":7,\"link\":\"https://claude.example/a?s=1\"}"


def with_run(entry: dict, state: str, attempt: int) -> dict:
    return {**entry, "run": {"state": state, "at": None, "attempt": attempt}}


SIGNED_IN_STEPS = [
    START, {"frame": frame([SIGNIN])}, {"respond": {"status": 200, "text": ANSWER}},
    {"click": "signin-start"}, {"frame": frame([with_run(SIGNIN, "running", 7)])},
]


def sign_in_card(snap: dict) -> dict:
    (card,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "article" and has_class(n, "signin")]
    return card


def classes(snap: dict) -> list:
    return [n["cls"] for n in strip(snap)]


def signed_out_pair() -> dict:
    return real_capacity(NOW_S, [
        {"name": "a", "week": .6, "week_reset": NOW_S + 86400, "refused": True,
         "signin": ("signed_in", NOW_S + 9 * 86400)},
        {"name": "default", "week": .2, "week_reset": NOW_S + 2 * 86400,
         "signin": ("signed_out", None)},
    ])


NOW_S = 1794398400


def real_capacity(now: float, rows: list, excluded=(), pinned=None) -> dict:
    """The capacity view the console builds from readings and sign-ins, not a hand-built one."""
    events, signins = [], {}
    for row in rows:
        name = row["name"]
        if "week" in row or "five" in row:
            refused = row.get("refused", False)
            status = "rejected" if refused else "allowed"
            week_reset = row.get("week_reset")
            seq = len(events) + 1
            events.append(Event(seq, f"t{seq}", console_capacity.READING, None, {
                "profile": name, "http_status": 429 if refused else 200, "status": status,
                "reset": week_reset if refused else None, "binding": "7d" if refused else None,
                "claim": None, "account": None, "session_id": None,
                "windows": {
                    "7d": {"status": status, "utilization": row.get("week"), "reset": week_reset},
                    "5h": {"status": "rejected" if row.get("five_out") else "allowed",
                           "utilization": row.get("five"),
                           "reset": row.get("five_reset")},
                }}))
        if row.get("signin") is not None:
            state, end = row["signin"]
            signins[name] = console_signin.SignIn(
                state,
                None if end is None else datetime.fromtimestamp(end, timezone.utc).isoformat(),
                datetime.fromtimestamp(now, timezone.utc).isoformat(),
                row.get("ever", state == "signed_in"), account=row.get("account"))
    return console_capacity.capacity_view(
        [row["name"] for row in rows], console_capacity.capacity_state(events), now,
        signins=signins, excluded=frozenset(excluded), pinned=pinned)


def panel(snap: dict) -> dict:
    return snap["accounts_body"]


def rows(snap: dict) -> list:
    return [n for n in nodes(panel(snap)) if has_class(n, "acct-row")]


def opened(frame: dict, *steps) -> dict:
    (snap,) = render([START, {"frame": frame}, {"click": "cap"}, *steps, {"snapshot": True}])
    return snap


def weekday(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime("%a %H:%M")


F3 = {**view([]), "capacity": real_capacity(NOW_S, [
    {"name": "a", "week": .35, "five": .6, "week_reset": NOW_S + 4 * 86400,
     "five_reset": NOW_S + 3600, "signin": ("signed_in", NOW_S + 12 * 86400)},
    {"name": "b", "week": .7, "week_reset": NOW_S + 5 * 86400, "refused": True},
    {"name": "c"},
], pinned="a"), "profile_sessions": {"a": 2, "b": 0, "c": 0}}


def one_profile(row: dict, **extra) -> dict:
    return {**view([]), "capacity": real_capacity(NOW_S, [row], **extra)}


def names(snap: dict) -> list:
    return [full(n) for n in nodes(panel(snap)) if has_class(n, "acct-name")]


def details(row: dict) -> list:
    (detail,) = [n for n in row["children"] if has_class(n, "acct-detail")]
    return [full(c) for c in detail["children"]]


class AccountsPanelPageTest(unittest.TestCase):
    def test_the_strip_opens_the_accounts_panel_and_escape_closes_it_returning_focus(self) -> None:
        closed, open_, after = render([
            START, {"frame": F3}, {"snapshot": True}, {"focus_on": "cap"}, {"click": "cap"},
            {"snapshot": True}, {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertIs(closed["accounts"]["hidden"], True)
        self.assertEqual(closed["capacity"]["expanded"], "false")
        self.assertEqual(closed["accounts_body"]["children"], [])
        self.assertIs(open_["accounts"]["hidden"], False)
        self.assertEqual(open_["capacity"]["expanded"], "true")
        self.assertEqual(open_["active"], "acct-panel")
        self.assertEqual(names(open_), ["a", "b", "c"])
        self.assertIs(after["accounts"]["hidden"], True)
        self.assertEqual(after["capacity"]["expanded"], "false")
        self.assertEqual(after["active"], "cap")
        self.assertIs(after["key_prevented"], True)
        self.assertEqual(after["accounts_body"]["children"], [])

    def test_the_a_key_opens_the_panel_and_is_ignored_in_a_field_or_with_a_modifier(self) -> None:
        opened_, closed, in_field, modified = render([
            START, {"frame": F3}, {"key": "a"}, {"snapshot": True}, {"key": "Escape"},
            {"snapshot": True}, {"key": "a", "target": "INPUT"}, {"snapshot": True},
            {"key": "a", "ctrlKey": True}, {"snapshot": True},
        ])
        self.assertIs(opened_["accounts"]["hidden"], False)
        self.assertIs(opened_["key_prevented"], True)
        self.assertIs(closed["accounts"]["hidden"], True)
        self.assertIs(in_field["accounts"]["hidden"], True)
        self.assertIs(modified["accounts"]["hidden"], True)

    def test_the_keyboard_flow_survives_a_panel_opened_with_nothing_focused(self) -> None:
        # A browser's keydown targets the focused element, else the body: after Escape no strip button holds focus.
        with_inbox = {**F3, **frame([ANSWERABLE])}
        closed, reopened = render([
            START, {"frame": with_inbox}, {"key": "a", "follow": True},
            {"key": "Escape", "follow": True}, {"snapshot": True},
            {"key": "a", "follow": True}, {"snapshot": True},
        ])
        self.assertNotIn("cap", (closed["active"] or "").split())
        self.assertIs(reopened["accounts"]["hidden"], False)
        (goal,) = render([
            START, {"frame": with_inbox}, {"key": "a", "follow": True},
            {"key": "Escape", "follow": True}, {"key": "g", "follow": True}, {"snapshot": True},
        ])
        self.assertIs(box_open(goal), True)

    def test_a_streamed_frame_keeps_the_focused_panel_control(self) -> None:
        def focused_in(snap: dict) -> list:
            return [n for n in nodes(panel(snap)) if n["focused"]]

        for cls in ("acct-close", "acct-pin"):
            (snap,) = render([
                START, {"frame": F3}, {"click": "cap"}, {"focus_on": cls},
                {"frame": {**F3, "profile_sessions": {"a": 3, "b": 0, "c": 0}}}, {"snapshot": True},
            ])
            (kept,) = focused_in(snap)
            self.assertIn(cls, kept["cls"].split())
        # The control is found by its row, not by its class alone: the rows reorder under the focus.
        cap = F3["capacity"]
        flipped = {**F3, "capacity": {**cap, "profiles": list(reversed(cap["profiles"]))}}
        (snap,) = render([
            START, {"frame": F3}, {"click": "cap"}, {"focus_on": "acct-pin"},
            {"frame": flipped}, {"snapshot": True},
        ])
        (kept,) = focused_in(snap)
        self.assertIn("acct-pin", kept["cls"].split())
        (owner,) = [r for r in rows(snap) if kept in nodes(r)]
        self.assertEqual(full([n for n in nodes(owner) if has_class(n, "acct-name")][0]), "a")

    def test_a_keyboard_pin_or_exclusion_keeps_the_focus_while_it_posts(self) -> None:
        for cls, url in (("acct-pin", "/api/pin"), ("acct-toggle", "/api/exclusion")):
            with self.subTest(cls=cls):
                (snap,) = render([
                    START, {"frame": F3}, {"click": "cap"}, {"focus_on": cls}, {"hold": True}, {"click": cls},
                    {"snapshot": True},
                ])
                (kept,) = [n for n in nodes(panel(snap)) if n["focused"]]
                self.assertIn(cls, kept["cls"].split())
                self.assertEqual(len([p for p in snap["posts"] if p["url"] == url]), 1)
                (again,) = render([
                    START, {"frame": F3}, {"click": "cap"}, {"focus_on": cls}, {"hold": True}, {"click": cls},
                    {"click": cls}, {"snapshot": True},
                ])
                self.assertEqual(len([p for p in again["posts"] if p["url"] == url]), 1)

    def test_an_exhausted_account_keeps_its_weekly_figure_in_the_panel(self) -> None:
        snap = opened(one_profile({
            "name": "w", "week": .4, "five": 1.0, "five_out": True,
            "week_reset": NOW_S + 4 * 86400, "five_reset": NOW_S + 3600}))
        (row,) = rows(snap)
        out = details(row)
        self.assertTrue(out[0].startswith("out until "), out)
        self.assertIn("60% of the week left", out)

    def test_focus_returns_to_the_element_focused_at_opening(self) -> None:
        with_inbox = {**F3, **frame([ANSWERABLE])}
        (kept,) = render([
            START, {"frame": with_inbox}, {"focus_on": "opt"}, {"click": "cap"},
            {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertIn("opt", kept["active"].split())
        (lost,) = render([
            START, {"frame": with_inbox}, {"focus_on": "opt"}, {"click": "cap"},
            {"frame": with_inbox}, {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertEqual(lost["active"], "cap")

    def test_while_the_panel_is_open_only_escape_acts(self) -> None:
        with_inbox = {**F3, **frame([ANSWERABLE])}
        before, after = render([
            START, {"frame": with_inbox}, {"snapshot": True}, {"click": "cap"},
            {"key": "2"}, {"key": "g"}, {"snapshot": True},
        ])
        self.assertEqual(picked(after), picked(before))
        self.assertIs(box_open(after), False)
        self.assertIs(after["key_prevented"], False)

    def test_escape_closes_the_panel_before_it_undoes_an_answer(self) -> None:
        (snap,) = render([
            START, {"frame": {**F3, **frame([ANSWERABLE])}}, {"key": "Enter"},
            {"click": "cap"}, {"key": "Escape"}, {"snapshot": True},
        ])
        self.assertIs(snap["accounts"]["hidden"], True)
        self.assertIn(WAIT_TEXT, text(snap["inbox"]))

    def test_each_row_holds_the_details_of_its_profile(self) -> None:
        snap = opened(F3)
        a, b, c = rows(snap)
        by_name = {p["profile"]: p for p in F3["capacity"]["profiles"]}
        self.assertEqual(details(a), [
            "65% of the week left", "40% of 5 hours",
            "resets " + weekday(by_name["a"]["next_reset"]), "signed in, ends in 12 days"])
        out = details(b)
        self.assertTrue(out[0].startswith("out until " + weekday(by_name["b"]["out_until"])), out)
        self.assertEqual([n for n in nodes(b) if has_class(n, "acct-reset")], [])
        self.assertEqual(details(c), ["no reading yet", "sign-in unknown"])
        for name in nodes(panel(snap)):
            if has_class(name, "acct-name"):
                self.assertEqual(name["title"], name["text"])
        (mark,) = [n for n in nodes(a) if has_class(n, "acct-pin-mark")]
        self.assertEqual(full(mark), "pinned")
        self.assertEqual({n["tag"] for n in nodes(a) if has_class(n, "acct-pin")}, {"button"})

    def test_the_strip_holds_no_control(self) -> None:
        excluded = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35}, {"name": "b", "week": .7}], excluded=("b",), pinned="a")}
        for shown in (F3, excluded):
            (snap,) = render([START, {"frame": shown}, {"snapshot": True}])
            self.assertEqual(
                [n for n in nodes(snap["capacity"])[1:] if n["tag"] in ("button", "input", "a")], [])

    def test_the_panel_uses_only_the_page_tokens_and_hides_when_hidden(self) -> None:
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))
        rules = style_rules(style)

        def ours(selector: str) -> bool:
            return selector.startswith(".acct-") or selector.startswith("#accounts")

        (hide,) = [d for s, d in rules if s == ".acct-panel[hidden]"]
        self.assertEqual(hide.get("display"), "none")
        declared = {k for s, d in rules if s == ":root" for k in d if k.startswith("--")}
        ours_values = [v for s, d in rules if ours(s) for v in d.values()]
        others = " ".join(v for s, d in rules if not ours(s) for v in d.values())
        sizes = {d["font-size"] for s, d in rules if not ours(s) and "font-size" in d}
        self.assertTrue(ours_values)
        for value in ours_values:
            for token in re.findall(r"var\((--[\w-]+)", value):
                self.assertIn(token, declared)
            for literal in re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", value):
                self.assertIn(literal, others)
        for selector, decls in rules:
            if ours(selector) and "font-size" in decls:
                self.assertIn(decls["font-size"], sizes, selector)

    def test_each_row_offers_one_exclusion_toggle_named_for_its_action(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35}, {"name": "b", "week": .7}, {"name": "c"}],
            excluded=("a", "c"))}
        a, b, c = rows(opened(shown))
        self.assertTrue(has_class(a, "acct-excluded"))
        self.assertTrue(has_class(c, "acct-excluded"))
        self.assertFalse(has_class(b, "acct-excluded"))
        toggles = []
        for n in (a, b, c):
            (toggle,) = [m for m in nodes(n) if has_class(m, "acct-toggle")]
            toggles.append(full(toggle))
        self.assertEqual(toggles, ["Include", "Exclude", "Include"])
        for n in (a, c):
            (mark,) = [m for m in nodes(n) if has_class(m, "acct-excl")]
            self.assertEqual(full(mark), "excluded")
        self.assertEqual([m for m in nodes(b) if has_class(m, "acct-excl")], [])

    def test_the_toggle_posts_one_exclusion_with_the_token(self) -> None:
        for name, excluded, body in (
            ("a", True, {"profile": "a", "excluded": False}),
            ("b", False, {"profile": "b", "excluded": True}),
        ):
            snap = opened(one_profile({"name": name, "week": .35},
                                      excluded=(name,) if excluded else ()),
                          {"click": "acct-toggle"})
            (post,) = [p for p in snap["posts"] if p["url"] == "/api/exclusion"]
            self.assertEqual(post["method"], "POST")
            self.assertEqual(post["headers"],
                             {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
            self.assertEqual(json.loads(post["body"]), body)

    def test_a_refused_toggle_says_why(self) -> None:
        snap = opened(one_profile({"name": "a", "week": .35}, excluded=("a",)),
                      {"respond": {"status": 409, "text": "no such profile\n"}},
                      {"click": "acct-toggle"})
        (fail,) = [n for n in nodes(panel(snap)) if has_class(n, "fail")]
        self.assertEqual(full(fail), "Could not include: no such profile")

    def test_each_row_offers_pin_and_the_pinned_one_unpin(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35}, {"name": "b", "week": .7}], pinned="a")}
        a, b = rows(opened(shown))
        labels = []
        for n in (a, b):
            (pin,) = [m for m in nodes(n) if has_class(m, "acct-pin")]
            labels.append(full(pin))
        self.assertEqual(labels, ["Unpin", "Pin"])
        self.assertTrue(has_class(a, "acct-pinned"))
        self.assertFalse(has_class(b, "acct-pinned"))
        (mark,) = [m for m in nodes(a) if has_class(m, "acct-pin-mark")]
        self.assertEqual(full(mark), "pinned")
        self.assertEqual([m for m in nodes(b) if has_class(m, "acct-pin-mark")], [])

    def test_a_pinned_profile_with_no_reading_has_a_row(self) -> None:
        (c,) = rows(opened(one_profile({"name": "c"}, pinned="c")))
        (pin,) = [m for m in nodes(c) if has_class(m, "acct-pin")]
        self.assertEqual(full(pin), "Unpin")

    def test_the_pin_button_posts_one_pin_with_the_token(self) -> None:
        for name, pinned, body in (
            ("a", "a", {"profile": "a", "pinned": False}),
            ("b", None, {"profile": "b", "pinned": True}),
        ):
            snap = opened(one_profile({"name": name, "week": .35}, pinned=pinned),
                          {"click": "acct-pin"})
            (post,) = [p for p in snap["posts"] if p["url"] == "/api/pin"]
            self.assertEqual(post["method"], "POST")
            self.assertEqual(post["headers"],
                             {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
            self.assertEqual(json.loads(post["body"]), body)

    def test_a_refused_pin_says_why(self) -> None:
        snap = opened(one_profile({"name": "a", "week": .35}, excluded=("a",)),
                      {"respond": {"status": 409, "text": "excluded; include it first\n"}},
                      {"click": "acct-pin"})
        (fail,) = [n for n in nodes(panel(snap)) if has_class(n, "fail")]
        self.assertEqual(full(fail), "Could not pin: excluded; include it first")

    def test_a_refused_unpin_says_why(self) -> None:
        snap = opened(one_profile({"name": "a", "week": .35}, pinned="a"),
                      {"respond": {"status": 500, "text": "could not write\n"}},
                      {"click": "acct-pin"})
        (fail,) = [n for n in nodes(panel(snap)) if has_class(n, "fail")]
        self.assertEqual(full(fail), "Could not unpin: could not write")

    def test_the_panel_says_when_the_pin_is_not_in_effect(self) -> None:
        capacity_ = real_capacity(NOW_S, [
            {"name": "a", "week": .35, "week_reset": NOW_S + 86400, "refused": True},
            {"name": "b", "week": .7}], pinned="a")

        def last(pin: dict | None) -> dict:
            shown = {**view([]), "capacity": capacity_}
            if pin is not None:
                shown["pin"] = pin
            return panel(opened(shown))["children"][-1]

        waiting = last({"profile": "a", "in_effect": False, "reason": "out of allowance",
                        "until": "2026-11-20T09:30:00+00:00", "instead": "b"})
        self.assertTrue(has_class(waiting, "acct-pin-note"))
        self.assertEqual(full(waiting),
                         "a is pinned but not in effect: out of allowance until Fri 09:30. "
                         "New sessions use b.")
        nowhere = last({"profile": "a", "in_effect": False, "reason": "signed out",
                        "until": None, "instead": None})
        self.assertTrue(has_class(nowhere, "acct-pin-note"))
        self.assertEqual(full(nowhere),
                         "a is pinned but not in effect: signed out. "
                         "New sessions have no profile to use.")
        for pin in ({"profile": "a", "in_effect": True, "reason": None,
                     "until": None, "instead": None}, None):
            self.assertFalse(has_class(last(pin), "acct-pin-note"))


class AccountNamePageTest(unittest.TestCase):
    @staticmethod
    def texts(row: dict, cls: str) -> list:
        return [full(n) for n in nodes(row) if has_class(n, cls)]

    @staticmethod
    def two(first: str, second: str) -> dict:
        signed = ("signed_in", NOW_S + 12 * 86400)
        return {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "p1", "week": .35, "signin": signed, "account": first},
            {"name": "p2", "week": .5, "signin": signed, "account": second}])}

    def test_each_row_names_its_account(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35, "signin": ("signed_in", NOW_S + 12 * 86400),
             "account": "a@example.invalid"},
            {"name": "b", "week": .5, "signin": ("signed_in", NOW_S + 20 * 86400),
             "account": "b@example.invalid"},
            {"name": "c", "signin": ("signed_out", None), "ever": True}])}
        snap = opened(shown)
        self.assertEqual(self.texts(row_of(snap, "a"), "acct-account"), ["a@example.invalid"])
        self.assertEqual(self.texts(row_of(snap, "b"), "acct-account"), ["b@example.invalid"])
        self.assertEqual(self.texts(row_of(snap, "c"), "acct-account"), [])
        self.assertEqual(self.texts(panel(snap), "acct-same"), [])

    def test_a_sign_in_to_another_account_renames_the_row_and_flags_both(self) -> None:
        before = self.two("a@example.invalid", "b@example.invalid")
        after = self.two("a@example.invalid", "a@example.invalid")
        one, two = render([START, {"frame": before}, {"click": "cap"}, {"snapshot": True},
                           {"frame": after}, {"snapshot": True}])
        self.assertEqual(len([n for n in strip(one) if has_class(n, "cap-acct")]), 2)
        self.assertEqual(self.texts(panel(one), "acct-same"), [])
        self.assertEqual(self.texts(row_of(two, "p2"), "acct-account"), ["a@example.invalid"])
        self.assertEqual(self.texts(row_of(two, "p1"), "acct-same"), ["same account as p2"])
        self.assertEqual(self.texts(row_of(two, "p2"), "acct-same"), ["same account as p1"])
        on_strip = [full(n) for n in nodes(two["capacity"]) if n["tag"] == "b"]
        self.assertEqual(on_strip, [p["profile"] for p in after["capacity"]["profiles"]
                                    if p["duplicate_of"] is None])
        self.assertEqual(on_strip, ["p1"])

    def test_the_all_out_panel_names_a_shared_account_once(self) -> None:
        signed = ("signed_in", NOW_S + 20 * 86400)
        cap = real_capacity(NOW_S, [
            {"name": "p2", "week": .5, "signin": signed, "account": "a@example.invalid"},
            {"name": "p1", "week": 1.0, "week_reset": NOW_S + 86400, "signin": signed,
             "account": "a@example.invalid"}])
        self.assertIs(cap["all_out"], True)
        result = render_page({**view([]), "capacity": cap}, NOW_MS)
        items = [full(n) for n in nodes(result["promoted"]) if n["tag"] == "li"]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].startswith("p1 "), items)
        self.assertFalse([i for i in items if i.startswith("p2 ")])


class StripPageTest(unittest.TestCase):
    @staticmethod
    def base_rules() -> list:
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))
        base, at = "", 0
        for found in re.finditer(r"@media [^{]+\{", style):
            if found.start() < at:
                continue
            base += style[at:found.start()]
            depth, at = 1, found.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(style[at], 0)
                at += 1
        return style_rules(base + style[at:])

    @staticmethod
    def shown(cap: dict) -> dict:
        (snap,) = render([START, {"frame": {**view([]), "capacity": cap}}, {"snapshot": True}])
        return snap

    def test_each_entry_is_its_name_bar_figure_and_quiet_word(self) -> None:
        cap = real_capacity(NOW_S, [
            {"name": "a", "week": .35, "five": .6, "week_reset": NOW_S + 4 * 86400,
             "signin": ("signed_in", NOW_S + 12 * 86400)},
            {"name": "b", "week": .7, "week_reset": NOW_S + 5 * 86400},
            {"name": "c", "week": .5, "week_reset": NOW_S + 2 * 86400, "refused": True},
        ], excluded=("b",), pinned="a")
        snap = self.shown(cap)
        a, b, c = [n for n in strip(snap) if has_class(n, "cap-acct")]
        shape = lambda n: [(k["tag"], k["cls"]) for k in n["children"]]
        self.assertEqual(shape(a), [("b", ""), ("span", "cap-pin-mark"), ("span", "meter"), ("span", "cap-pc")])
        self.assertEqual(full(a["children"][-1]), "65%")
        self.assertEqual(shape(b), [("b", ""), ("span", "cap-excl"), ("span", "meter"), ("span", "cap-pc")])
        self.assertEqual(full(b["children"][-1]), "30%")
        self.assertEqual([k["tag"] for k in c["children"]], ["b", "span", "span"])
        (out_until,) = [p["out_until"] for p in cap["profiles"] if p["profile"] == "c"]
        self.assertEqual(full(c["children"][-1]), "out until " + weekday(out_until))
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-when")], [])
        self.assertEqual([n for n in nodes(snap["capacity"])
                          if has_class(n, "acct-pin") or has_class(n, "cap-pin")], [])

    def test_sign_in_words_show_only_when_the_sign_in_asks(self) -> None:
        reading = {"week": .5, "week_reset": NOW_S + 86400}
        frame_ = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", **reading, "signin": ("signed_in", NOW_S + 259200)},
            {"name": "b", **reading, "signin": ("signed_in", NOW_S + 259201)},
            {"name": "c", **reading, "signin": ("signed_out", None), "ever": True},
            {"name": "d", **reading},
        ])}
        snap = opened(frame_)
        self.assertEqual(
            [full(n) for n in nodes(snap["capacity"]) if has_class(n, "cap-signin")],
            ["signed in, ends in 3 days", "signed out"])
        self.assertEqual(
            [full(n) for n in nodes(panel(snap)) if has_class(n, "acct-signin-words")],
            ["signed in, ends in 3 days", "signed in, ends in 3 days", "signed out", "sign-in unknown"])

    def test_a_profile_with_no_reading_is_in_the_note_unless_it_asks_or_is_marked(self) -> None:
        cap = real_capacity(NOW_S, [
            {"name": "a", "week": .5, "week_reset": NOW_S + 86400},
            {"name": "b"},
            {"name": "c", "signin": ("signed_in", NOW_S + 2 * 86400)},
            {"name": "d"},
            {"name": "e", "signin": ("signed_in", NOW_S + 20 * 86400)},
        ], pinned="d")
        snap = self.shown(cap)
        self.assertEqual([n["text"] for n in nodes(snap["capacity"]) if n["tag"] == "b"], ["a", "c", "d"])
        self.assertTrue(cap["no_reading"])
        self.assertEqual(full(part(snap, "cap-none")), cap["no_reading"])

    def test_three_accounts_fit_one_line_at_1440(self) -> None:
        rules = self.base_rules()
        (cap,) = [d for s, d in rules if s == ".cap"]
        for name, value in {
            "flex-wrap": "nowrap", "white-space": "nowrap", "overflow": "hidden",
            "min-width": "0", "max-width": "100%", "font": "inherit", "background": "none",
            "border": "0", "padding": "0", "text-align": "left", "cursor": "pointer",
            "font-size": ".8125rem", "color": "var(--sub0)",
        }.items():
            self.assertEqual(cap.get(name), value, name)
        (kids,) = [d for s, d in rules if s == ".cap > *"]
        self.assertEqual(kids.get("flex"), "none")
        for selector in (".cap-excl", ".cap-pin-mark"):
            (quiet,) = [d for s, d in rules if s == selector]
            self.assertEqual(quiet.get("color"), "var(--ov2)", selector)

        worst = real_capacity(NOW_S, [
            {"name": "work-main", "week": .35, "week_reset": NOW_S + 4 * 86400,
             "signin": ("signed_in", NOW_S + 2 * 86400)},
            {"name": "personal", "week": .7, "week_reset": NOW_S + 5 * 86400},
            {"name": "spare-one", "week": .88, "week_reset": NOW_S + 3 * 86400},
        ], excluded=("personal",), pinned="work-main")
        snap = self.shown(worst)

        def width(n: dict) -> int:
            if n["tag"] == "b":
                return min(len(n["text"]) * 8, 144)
            if n["tag"] == "svg":
                return 16
            if has_class(n, "meter"):
                return 34
            return len(full(n)) * 7

        def group(n: dict) -> int:
            if not n["children"]:
                return width(n)
            return sum(width(c) for c in n["children"]) + 7 * (len(n["children"]) - 1)

        kids = strip(snap)
        used = sum(group(n) for n in kids) + 16 * (len(kids) - 1)
        budget = 1360 - 2 * 48 - 7 * 9 - 192 - len("Reconnecting…") * 7 - 3 * 28
        self.assertLessEqual(used, budget)

    def test_at_1440_the_rendered_strip_is_one_unclipped_line_beside_the_goal_bar(self) -> None:
        # Real geometry in headless Chromium; skipped where Playwright or its browser is not installed.
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        worst = real_capacity(NOW_S, [
            {"name": "work-main", "week": .35, "week_reset": NOW_S + 4 * 86400,
             "signin": ("signed_in", NOW_S + 2 * 86400)},
            {"name": "personal", "week": .7, "week_reset": NOW_S + 5 * 86400},
            {"name": "spare-one", "week": .88, "week_reset": NOW_S + 3 * 86400},
        ], excluded=("personal",), pinned="work-main")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const cap = document.getElementById('capacity');
          const bar = document.getElementById('goal').getBoundingClientRect();
          const box = cap.getBoundingClientRect();
          const kids = [...cap.children].map((e) => e.getBoundingClientRect());
          return {
            tops: [...new Set([...cap.children].map((e) => e.offsetTop))].length,
            kids: kids.length,
            inside: kids.every((r) => r.left >= box.left && r.right <= box.right),
            fits: cap.scrollWidth <= cap.clientWidth,
            beside: box.top < bar.bottom && bar.top < box.bottom,
          };
        }"""
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})",
                              {**view([]), "capacity": worst})
                got = page.evaluate(measure)
            finally:
                browser.close()
        self.assertGreater(got["kids"], 3)
        self.assertEqual(got["tops"], 1, got)
        self.assertTrue(got["inside"], got)
        self.assertTrue(got["fits"], got)
        self.assertTrue(got["beside"], got)

    def test_an_excluded_accounts_bar_is_dimmed(self) -> None:
        rules = self.base_rules()
        (dim,) = [d for s, d in rules if s == ".cap-excluded .meter i"]
        self.assertEqual(dim.get("background"), "var(--s2)")
        (fill,) = [d for s, d in rules if s == ".meter i"]
        self.assertEqual(fill.get("background"), "var(--sub0)")
        snap = self.shown(real_capacity(NOW_S, [
            {"name": "a", "week": .35}, {"name": "b", "week": .7}], excluded=("b",)))
        _, b = [n for n in strip(snap) if has_class(n, "cap-acct")]
        self.assertEqual([(k["tag"], k["cls"]) for k in b["children"]],
                         [("b", ""), ("span", "cap-excl"), ("span", "meter"), ("span", "cap-pc")])
        self.assertEqual(full(b["children"][1]), "excluded")

    def test_at_1440_an_excluded_accounts_bar_is_dimmed_and_keeps_its_word(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        worst = real_capacity(NOW_S, [
            {"name": "work-main", "week": .35, "week_reset": NOW_S + 4 * 86400,
             "signin": ("signed_in", NOW_S + 2 * 86400)},
            {"name": "personal", "week": .7, "week_reset": NOW_S + 5 * 86400},
            {"name": "spare-one", "week": .88, "week_reset": NOW_S + 3 * 86400},
        ], excluded=("personal",), pinned="work-main")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const fill = (sel) => getComputedStyle(document.querySelector(sel)).backgroundColor;
          const word = document.querySelector('.cap-excluded .cap-excl');
          return {
            excluded: fill('.cap-excluded .meter i'),
            other: fill('.cap-acct:not(.cap-excluded) .meter i'),
            word: word.textContent,
            display: getComputedStyle(word).display,
          };
        }"""
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})",
                              {**view([]), "capacity": worst})
                got = page.evaluate(measure)
            finally:
                browser.close()
        self.assertEqual(got["excluded"], "rgb(91, 96, 120)", got)
        self.assertEqual(got["other"], "rgb(165, 173, 203)", got)
        self.assertEqual(got["word"], "excluded", got)
        self.assertNotEqual(got["display"], "none", got)

    def test_at_1440_the_strip_never_shrinks_and_the_goal_placeholder_stays_one_line(self) -> None:
        rules = self.base_rules()

        def rule(selector: str) -> dict:
            merged: dict = {}
            for found, decls in rules:
                if found == selector:
                    merged.update(decls)
            return merged

        (style,) = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))
        narrow = style_rules(media_block(style, "(max-width: 900px)"))
        groups = {
            "cap": (rule(".cap"), {
                "flex": "0 0 auto", "overflow": "hidden", "min-width": "0", "max-width": "100%",
                "white-space": "nowrap", "flex-wrap": "nowrap"}),
            "goal-bar": (rule(".goal-bar"), {
                "flex": "1 1 12rem", "min-width": "12rem", "max-width": "440px"}),
            "top-in": (rule(".top-in"), {"flex-wrap": "wrap", "gap": "10px 28px"}),
            "placeholder": (rule(".goal-in .goal-text::placeholder"), {
                "white-space": "nowrap", "overflow": "hidden", "text-overflow": "ellipsis",
                "color": "var(--ov2)"}),
            "placeholder host": (rule(".goal-in .goal-text"), {"text-overflow": "ellipsis"}),
            "narrow goal-bar": (
                {k: v for s, d in narrow if s == ".goal-bar" for k, v in d.items()},
                {"flex": "1 0 100%", "max-width": "none"}),
        }
        for name, (declared, wanted) in groups.items():
            with self.subTest(rule=name):
                for prop, value in wanted.items():
                    self.assertEqual(declared.get(prop), value, prop)

    def test_at_480_only_the_summary_word_and_the_tightest_account_show(self) -> None:
        def rows_(*extra) -> list:
            return [{"name": "a", "week": .35, "week_reset": NOW_S + 86400},
                    {"name": "b", "week": .88, "week_reset": NOW_S + 86400},
                    {"name": "c", "week": .5, "week_reset": NOW_S + 86400}, *extra]

        def kept(snap: dict) -> list:
            return [n for n in strip(snap) if not has_class(n, "cap-extra")]

        snap = self.shown(real_capacity(NOW_S, rows_()))
        self.assertEqual([n["cls"] for n in kept(snap)], ["cap-state cap-fine", "cap-acct cap-tightest"])
        self.assertEqual(kept(snap)[1]["children"][0]["text"], "b")
        out = self.shown(real_capacity(NOW_S, rows_(
            {"name": "d", "week": .5, "week_reset": NOW_S + 86400, "refused": True})))
        self.assertEqual(kept(out)[1]["children"][0]["text"], "d")
        none = self.shown(real_capacity(NOW_S, [{"name": "a"}, {"name": "b"}]))
        self.assertEqual(
            [n for n in nodes(none["capacity"]) if has_class(n, "cap-extra") or has_class(n, "cap-tightest")], [])
        text_ = PAGE.read_text(encoding="utf-8")
        style = text_[text_.index("<style>"):text_.index("</style>")]
        (extra,) = [d for s, d in style_rules(media_block(style, "(max-width: 480px)")) if s == ".cap-extra"]
        self.assertEqual(extra.get("display"), "none")

    def test_an_empty_strip_still_opens_the_panel(self) -> None:
        snap = opened({**view([]), "capacity": console_capacity.EMPTY})
        self.assertEqual([(n["cls"], full(n)) for n in strip(snap)], [("cap-none", "no accounts")])
        self.assertIs(snap["accounts"]["hidden"], False)


class RemovePageTest(unittest.TestCase):
    def removal_frame(self, sessions: dict | None = None, extra: dict | None = None) -> dict:
        return {**view([]), **(extra or {}),
                "capacity": real_capacity(NOW_S, [{"name": "a", "week": .35},
                                                  {"name": "b", "week": .7}]),
                "profile_sessions": sessions or {}}

    def opened(self, *steps) -> dict:
        return opened(self.removal_frame({"a": 2}), {"click": "acct-remove"}, *steps)

    def remove_node(self, snap: dict, cls: str) -> dict:
        (found,) = [n for n in nodes(panel(snap)) if has_class(n, cls)]
        return found

    def render_steps(self, *steps) -> list:
        return render([START, {"frame": self.removal_frame({"a": 2})}, {"click": "cap"},
                       {"click": "acct-remove"}, *steps])

    def test_each_account_offers_remove(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35}, {"name": "b", "signin": ("signed_out", None)}])}
        for row in rows(opened(shown)):
            (remove,) = [m for m in nodes(row) if has_class(m, "acct-remove")]
            self.assertEqual(full(remove), "Remove")

    def test_remove_asks_for_the_typed_name_and_says_how_many_sessions_run(self) -> None:
        for count, words in (
            (2, "2 sessions are running under a and keep running."),
            (1, "1 session is running under a and keeps running."),
            (0, "No session is running under a."),
        ):
            with self.subTest(count=count):
                snap = opened(self.removal_frame({"a": count}), {"click": "acct-remove"})
                self.assertEqual(full(self.remove_node(snap, "acct-remove-sessions")), words)
                self.assertEqual(full(self.remove_node(snap, "acct-remove-note")),
                                 "Type a to remove it. It is signed out first.")
                send = self.remove_node(snap, "acct-remove-send")
                self.assertEqual(full(send), "Remove a")
                self.assertTrue(send["disabled"])
                name = self.remove_node(snap, "acct-remove-name")
                self.assertEqual(name["label"], "Type a to remove it")

    def test_no_count_for_the_profile_says_no_sentence(self) -> None:
        snap = opened(self.removal_frame({}), {"click": "acct-remove"})
        self.assertEqual([n for n in nodes(panel(snap))
                          if has_class(n, "acct-remove-sessions")], [])

    def test_the_send_is_enabled_only_by_the_exact_name(self) -> None:
        for typed, disabled in (("A", True), ("a ", True), ("a", False)):
            with self.subTest(typed=typed):
                snap = self.opened({"type": {"class": "acct-remove-name", "text": typed}})
                self.assertEqual(self.remove_node(snap, "acct-remove-send")["disabled"], disabled)

    def test_a_keyboard_removal_keeps_the_focus_on_its_buttons_while_it_posts(self) -> None:
        named = {"type": {"class": "acct-remove-name", "text": "a"}}
        for cls in ("acct-remove-send", "acct-remove-cancel"):
            with self.subTest(cls=cls):
                (snap,) = self.render_steps(
                    named, {"focus_on": "acct-remove-send"}, {"hold": True}, {"click": "acct-remove-send"},
                    {"focus_on": cls}, {"click": cls}, {"snapshot": True})
                (kept,) = [n for n in nodes(panel(snap)) if n["focused"]]
                self.assertIn(cls, kept["cls"].split())
                self.assertEqual(len([p for p in snap["posts"] if p["url"] == "/api/account-remove"]), 1)
                self.assertEqual(len([n for n in nodes(panel(snap)) if has_class(n, "acct-remove-send")]), 1)

    def test_remove_posts_the_profile_and_the_typed_name_with_the_token(self) -> None:
        snap = self.opened({"type": {"class": "acct-remove-name", "text": "a"}},
                           {"click": "acct-remove-send"})
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/account-remove"]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"],
                         {"X-Console-Token": TOKEN, "Content-Type": "application/json"})
        self.assertEqual(post["body"], '{"profile":"a","typed":"a"}')

    def test_a_refused_removal_says_why(self) -> None:
        snap = self.opened(
            {"type": {"class": "acct-remove-name", "text": "a"}},
            {"respond": {"status": 502,
                         "text": "the account was not removed: its sign-out failed: exited\n"}},
            {"click": "acct-remove-send"})
        (fail,) = [n for n in nodes(panel(snap)) if has_class(n, "fail")]
        self.assertEqual(full(fail), "Could not remove: the account was not removed: "
                                     "its sign-out failed: exited")
        self.remove_node(snap, "acct-remove-box")

    def test_a_removal_closes_the_box(self) -> None:
        snap = self.opened({"type": {"class": "acct-remove-name", "text": "a"}},
                           {"click": "acct-remove-send"})
        self.assertEqual([n for n in nodes(panel(snap))
                          if has_class(n, "acct-remove-box")], [])

    def typed_and_selected(self, *steps) -> dict:
        shown = {**self.removal_frame({"a": 1}), "inbox": {"open": [ANSWERABLE], "answered": []}}
        return opened(
            shown, {"click": "acct-remove"},
            {"type": {"class": "acct-remove-name", "text": "ab"}},
            {"select": {"cls": "acct-remove-name", "start": 0, "end": 1}},
            *steps)

    def assert_kept(self, snap: dict) -> None:
        name = self.remove_node(snap, "acct-remove-name")
        self.assertEqual(name["value"], "ab")
        self.assertTrue(name["focused"])
        self.assertEqual(name["selection"], [0, 1])
        self.remove_node(snap, "acct-remove-box")

    def test_the_typed_name_its_selection_and_focus_survive_two_frames(self) -> None:
        first = {**self.removal_frame({"a": 1}), "inbox": {"open": [ANSWERABLE], "answered": []}}
        second = {**first, "project_count": 1}
        snap = self.typed_and_selected({"frame": first}, {"frame": second})
        self.assert_kept(snap)

    def test_the_typed_name_its_selection_and_focus_survive_a_local_redraw(self) -> None:
        self.assert_kept(self.typed_and_selected({"click": "acct-toggle"}))

    def test_a_profile_that_leaves_the_listing_loses_its_open_box_and_name(self) -> None:
        gone = {**self.removal_frame(), "capacity": real_capacity(NOW_S, [
            {"name": "b", "week": .7}])}
        snap, again = render([
            START, {"frame": self.removal_frame({"a": 1})}, {"click": "cap"},
            {"click": "acct-remove"},
            {"type": {"class": "acct-remove-name", "text": "a"}},
            {"frame": gone}, {"frame": self.removal_frame({"a": 1})}, {"snapshot": True},
            {"click": "acct-remove"}, {"snapshot": True},
        ])
        self.assertEqual([n for n in nodes(panel(snap))
                          if has_class(n, "acct-remove-box")], [])
        self.assertEqual(self.remove_node(again, "acct-remove-name")["value"], "")

    def test_cancel_closes_the_box_and_forgets_the_name(self) -> None:
        snap = self.opened(
            {"type": {"class": "acct-remove-name", "text": "a"}},
            {"click": "acct-remove-cancel"}, {"click": "acct-remove"})
        self.assertEqual(self.remove_node(snap, "acct-remove-name")["value"], "")


class SigninPageTest(unittest.TestCase):
    def test_each_listed_profile_shows_its_sign_in_words(self) -> None:
        reading = {"week": .5, "week_reset": NOW_S + 86400}
        frame_ = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", **reading, "signin": ("signed_in", NOW_S + 12 * 86400)},
            {"name": "b", **reading, "signin": ("signed_in", NOW_S + 86400 + 3600)},
            {"name": "c", **reading, "signin": ("signed_in", NOW_S + 3600)},
            {"name": "d", **reading, "refused": True, "signin": ("signed_in", None)},
            {"name": "e", **reading, "signin": ("unknown", None)},
        ])}
        snap = opened(frame_)
        self.assertEqual(
            [full(n) for n in nodes(snap["capacity"]) if has_class(n, "cap-signin")],
            ["signed in, ends in 1 day", "signed in, ends today"])
        self.assertEqual(
            [full(n) for n in nodes(panel(snap)) if has_class(n, "acct-signin-words")],
            ["signed in, ends in 12 days", "signed in, ends in 1 day", "signed in, ends today",
             "signed in", "sign-in unknown"])

    def test_a_profile_without_a_capacity_reading_shows_its_sign_in_only_when_it_asks(self) -> None:
        snap = capacity_snap(real_capacity(NOW_S, [
            {"name": "a", "week": .4, "week_reset": NOW_S + 86400,
             "signin": ("signed_in", NOW_S + 20 * 86400)},
            {"name": "b", "signin": ("signed_in", NOW_S + 2 * 86400)},
            {"name": "c", "signin": ("unknown", None)},
        ]))
        self.assertEqual(classes(snap), [
            "cap-state cap-fine", "cap-acct cap-tightest", "cap-acct cap-no-reading cap-extra",
            "cap-none cap-extra"])
        b = strip(snap)[2]
        self.assertIn("b", full(b))
        self.assertIn("signed in, ends in 2 days", full(b))
        self.assertEqual([n["text"] for n in nodes(snap["capacity"]) if n["tag"] == "b"], ["a", "b"])
        self.assertEqual(bars(b), [])

    def test_a_signed_out_profile_is_listed_as_signed_out(self) -> None:
        snap = capacity_snap(real_capacity(NOW_S, [
            {"name": "a", "week": .4, "week_reset": NOW_S + 86400,
             "signin": ("signed_in", NOW_S + 20 * 86400)},
            {"name": "default", "signin": ("signed_out", None)},
        ]))
        self.assertEqual(classes(snap), [
            "cap-state cap-fine", "cap-acct cap-tightest", "cap-acct cap-signed-out cap-extra"])
        out = strip(snap)[2]
        self.assertIn("default", full(out))
        self.assertIn("signed out", full(out))
        self.assertEqual(bars(out), [])
        self.assertNotIn("no reading yet", full(snap["capacity"]))

    def test_a_signed_out_profile_with_an_old_reading_drives_nothing(self) -> None:
        snap = capacity_snap(signed_out_pair())
        self.assertEqual(classes(snap)[0], "cap-state cap-out")
        self.assertEqual(full(strip(snap)[0]), "out")
        (default,) = [n for n in accounts(snap) if "default" in full(n)]
        self.assertEqual(default["cls"], "cap-acct cap-signed-out cap-extra")
        self.assertEqual(bars(default), [])
        text = full(snap["capacity"])
        self.assertNotIn("80%", text)
        self.assertNotIn(weekday(datetime.fromtimestamp(NOW_S + 2 * 86400, timezone.utc).isoformat()), text)
        self.assertNotIn("resets", text)

    def test_a_signed_out_profile_with_an_old_reading_never_makes_the_strip_fine(self) -> None:
        cap = signed_out_pair()
        snap = capacity_snap(cap, NOW_MS)
        self.assertEqual(full(strip(snap)[0]), "out")
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-when")], [])
        statement = render_page({**view([]), "capacity": cap}, NOW_MS)["statement"]
        self.assertIn("Resumes " + weekday(cap["resumes_at"]), full(statement))

    def test_the_all_out_panel_names_a_signed_out_profile_as_signed_out(self) -> None:
        result = render_page({**view([]), "capacity": signed_out_pair()}, NOW_MS)
        a, default = [n for n in nodes(result["promoted"]) if n["tag"] == "li"]
        self.assertEqual(a["cls"], "cap-out")
        self.assertTrue(full(a).startswith("a out until"))
        self.assertEqual(default["cls"], "cap-signed-out")
        self.assertEqual(full(default), "default signed out")

    def test_only_signed_out_profiles_show_without_a_state_word(self) -> None:
        snap = capacity_snap(capacity([
            profile("default", "unknown", signin=si("signed_out", None))]))
        self.assertEqual(classes(snap), ["cap-acct cap-signed-out"])

    def test_a_signed_out_profile_with_an_old_reading_alone_gives_no_state_word_or_reset(self) -> None:
        snap = capacity_snap(capacity([
            profile("default", "ok", week_left=80, next_reset="2026-11-16T05:00:00+00:00",
                    signin=si("signed_out", None))]))
        self.assertEqual(classes(snap), ["cap-acct cap-signed-out"])
        self.assertNotIn("resets", full(snap["capacity"]))

    def test_a_view_from_before_sign_in_adds_no_words(self) -> None:
        snap = capacity_snap(capacity(
            [profile("a", "ok", week_left=60), profile("b", "unknown")],
            no_reading="1 with no reading yet"))
        self.assertEqual([n for n in nodes(snap["capacity"]) if has_class(n, "cap-signin")], [])
        self.assertEqual(classes(snap), ["cap-state cap-fine", "cap-acct cap-tightest", "cap-none cap-extra"])

    def test_a_sign_in_ask_is_a_card_with_the_sign_in_action(self) -> None:
        f = frame([SIGNIN])
        f["statement"]["headline"] = "1 thing needs you"
        (snap,) = render([START, {"frame": f}, {"snapshot": True}])
        (card,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "article" and has_class(n, "signin")]
        self.assertTrue(has_class(card, "card"))
        self.assertIn("Sign in to work again", full(card))
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "reason")],
                         ["signed in, ends in 2 days"])
        (start,) = [n for n in nodes(card) if n["tag"] == "button"]
        self.assertTrue(has_class(start, "signin-start"))
        self.assertEqual(full(start), "Sign in again")
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-command")], [])
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-cancel")], [])
        self.assertNotIn("CLAUDE_ACCOUNT", full(card))
        self.assertEqual([n for n in nodes(snap["inbox"]) if has_class(n, "answer")], [])
        self.assertIn("1 thing needs you", full(snap["statement"]))

    def test_the_action_reads_sign_in_again_only_for_a_profile_once_signed_in(self) -> None:
        first = frame([{**SIGNIN, "signin": si("signed_out", None, ask=True, ever=False)}])
        second = frame([{**SIGNIN, "signin": si("signed_out", None, ask=True, ever=True)}])
        one, two = render([START, {"frame": first}, {"snapshot": True},
                           {"frame": second}, {"snapshot": True}])
        for snap, words in ((one, "Sign in"), (two, "Sign in again")):
            (card,) = [n for n in nodes(snap["inbox"])
                       if n["tag"] == "article" and has_class(n, "signin")]
            (start,) = [n for n in nodes(card) if has_class(n, "signin-start")]
            self.assertEqual(full(start), words)

    def test_pressing_sign_in_posts_the_profile_and_shows_the_link(self) -> None:
        (snap,) = render(SIGNED_IN_STEPS + [{"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"]), ("/api/signin", "POST"))
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"profile": "work"})
        card = sign_in_card(snap)
        (link,) = of_class(card, "a", "signin-link")
        self.assertEqual(link["href"], "https://claude.example/a?s=1")
        self.assertEqual(full(link), "Open the sign-in page")
        (code,) = of_class(card, "input", "signin-code")
        self.assertEqual((code["placeholder"], code["label"]),
                         ("Code from the sign-in page", "Sign-in code"))
        self.assertEqual(len(of_class(card, "button", "signin-send")), 1)
        self.assertEqual(len(of_class(card, "button", "signin-cancel")), 1)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-run")],
                         ["A sign-in is running."])

    def test_a_code_is_sent_to_the_code_route_and_the_field_empties(self) -> None:
        (snap,) = render(SIGNED_IN_STEPS + [
            {"type": {"class": "signin-code", "text": "ab#C-1"}},
            {"click": "signin-send"}, {"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual(post["url"], "/api/signin-code")
        self.assertEqual(json.loads(post["body"]), {"profile": "work", "code": "ab#C-1"})
        self.assertEqual(field(snap, "signin-code")["value"], "")

    def test_a_typed_code_and_its_focus_survive_a_new_frame(self) -> None:
        one, two = render(SIGNED_IN_STEPS + [
            {"type": {"class": "signin-code", "text": "ab#C"}},
            {"select": {"cls": "signin-code", "start": 1, "end": 3}},
            {"frame": frame([with_run(SIGNIN, "running", 7), check_item("A", "manual-check")])},
            {"snapshot": True},
            {"append": {"class": "signin-code", "text": "-1"}},
            {"click": "signin-send"}, {"snapshot": True}])
        code = field(one, "signin-code")
        self.assertEqual((code["value"], code["focused"], code["selection"]),
                         ("ab#C", True, [1, 3]))
        self.assertEqual(json.loads(two["posts"][-1]["body"]),
                         {"profile": "work", "code": "ab#C-1"})

    def test_cancel_posts_the_cancel_route(self) -> None:
        (snap,) = render(SIGNED_IN_STEPS + [{"click": "signin-cancel"}, {"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual(post["url"], "/api/signin-cancel")
        self.assertEqual(json.loads(post["body"]), {"profile": "work"})

    def test_cancel_is_offered_while_a_run_has_no_link(self) -> None:
        none = {"status": 200, "text": "{\"attempt\":7,\"link\":null}"}
        one, two = render([
            START, {"frame": frame([SIGNIN])}, {"respond": none}, {"click": "signin-start"},
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True},
            {"click": "signin-cancel"}, {"snapshot": True}])
        card = sign_in_card(one)
        for cls, wanted in (("signin-cancel", 1), ("signin-start", 1), ("signin-link", 0),
                            ("signin-code", 0)):
            with self.subTest(cls=cls):
                self.assertEqual(len([n for n in nodes(card) if has_class(n, cls)]), wanted)
        self.assertEqual(two["posts"][-1]["url"], "/api/signin-cancel")

    def test_a_link_that_is_not_https_is_not_shown(self) -> None:
        bad = {"status": 200, "text": "{\"attempt\":7,\"link\":\"javascript:alert(1)\"}"}
        (snap,) = render([
            START, {"frame": frame([SIGNIN])}, {"respond": bad}, {"click": "signin-start"},
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)

    def test_an_ended_run_drops_the_held_link_and_offers_sign_in_again(self) -> None:
        for state, note in (("timed_out", "The sign-in timed out."),
                            ("cancelled", "The sign-in was cancelled."),
                            ("failed", "The sign-in did not finish.")):
            with self.subTest(state=state):
                (snap,) = render(SIGNED_IN_STEPS + [
                    {"frame": frame([with_run(SIGNIN, state, 7)])}, {"snapshot": True}])
                card = sign_in_card(snap)
                self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
                self.assertEqual([full(n) for n in of_class(card, "p", "signin-run")], [note])
                self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
                self.assertEqual([n for n in nodes(card) if has_class(n, "signin-cancel")], [])

    def test_an_ended_run_drops_the_link_without_a_running_frame(self) -> None:
        one, two = render([
            START, {"frame": frame([SIGNIN])}, {"respond": {"status": 200, "text": ANSWER}},
            {"click": "signin-start"}, {"snapshot": True},
            {"frame": frame([with_run(SIGNIN, "timed_out", 7)])}, {"snapshot": True}])
        self.assertEqual(len(of_class(sign_in_card(one), "a", "signin-link")), 1)
        card = sign_in_card(two)
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)

    def test_a_start_answer_after_the_run_ended_holds_nothing(self) -> None:
        (snap,) = render([
            START, {"frame": frame([SIGNIN])}, {"hold": True}, {"click": "signin-start"},
            {"frame": frame([with_run(SIGNIN, "cancelled", 7)])},
            {"release": {"status": 200, "text": ANSWER}}, {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-run")],
                         ["The sign-in was cancelled."])

    def test_an_older_view_keeps_the_held_link(self) -> None:
        (snap,) = render(SIGNED_IN_STEPS[:-1] + [
            {"frame": frame([with_run(SIGNIN, "timed_out", 6)])}, {"snapshot": True}])
        self.assertEqual(len(of_class(sign_in_card(snap), "a", "signin-link")), 1)

    def test_a_run_that_vanishes_without_an_ending_row_drops_the_held_link(self) -> None:
        for view_after in (SIGNIN, with_run(SIGNIN, "timed_out", 6)):
            with self.subTest(run=view_after["run"]):
                (snap,) = render(SIGNED_IN_STEPS + [
                    {"frame": frame([view_after])}, {"snapshot": True}])
                card = sign_in_card(snap)
                self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
                self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
                self.assertEqual([n for n in nodes(card) if has_class(n, "signin-cancel")], [])

    def test_a_link_does_not_outlive_its_item(self) -> None:
        one, two = render(SIGNED_IN_STEPS + [
            {"frame": frame([])}, {"frame": frame([SIGNIN])}, {"snapshot": True},
            {"hold": True}, {"click": "signin-start"}, {"frame": frame([])},
            {"release": {"status": 200, "text": ANSWER}}, {"frame": frame([SIGNIN])},
            {"snapshot": True}])
        for snap in (one, two):
            card = sign_in_card(snap)
            self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
            self.assertEqual(len(of_class(card, "button", "signin-start")), 1)

    def test_a_refused_start_shows_its_reason(self) -> None:
        (snap,) = render([
            START, {"frame": frame([SIGNIN])},
            {"respond": {"status": 409, "text": "unknown profile\n"}},
            {"click": "signin-start"}, {"snapshot": True}])
        self.assertEqual([full(n) for n in of_class(sign_in_card(snap), "span", "signin-failed")],
                         ["Could not start the sign-in: unknown profile"])

    def test_sign_in_cards_sit_between_progress_and_questions(self) -> None:
        (snap,) = render([
            START, {"frame": frame([PROGRESS, SIGNIN, Q0, ANSWERABLE])}, {"snapshot": True}])
        order = []
        for child in snap["inbox"]["children"]:
            text = full(child)
            if has_class(child, "progress"):
                order.append("progress")
            elif has_class(child, "signin"):
                order.append("signin")
            elif Q0["headline"] in text:
                order.append("question")
            elif ANSWERABLE["headline"] in text:
                order.append("tracker")
        self.assertEqual(order, ["progress", "signin", "question", "tracker"])

    def test_an_adoption_card_sits_between_sign_ins_and_questions(self) -> None:
        (snap,) = render([
            START, {"frame": frame([SIGNIN, ADOPTION_ITEM, Q0, ANSWERABLE])}, {"snapshot": True}])
        order = []
        card = None
        for child in snap["inbox"]["children"]:
            text = full(child)
            if has_class(child, "signin"):
                order.append("signin")
            elif has_class(child, "adoption"):
                order.append("adoption")
                card = child
            elif Q0["headline"] in text:
                order.append("question")
            elif ANSWERABLE["headline"] in text:
                order.append("tracker")
        self.assertEqual(order, ["signin", "adoption", "question", "tracker"])
        (headline,) = of_class(card, "p", "q")
        self.assertEqual(full(headline), ADOPTION_ITEM["headline"])
        (link,) = of_class(card, "a", "pr-link")
        self.assertEqual(full(link), "Open the pull request")
        self.assertEqual(link["href"], ADOPTION_ITEM["url"])


LATER = [START, {"respond": {"status": 200, "text": ANSWER}},
         {"frame": frame([with_run(SIGNIN, "running", 7)])}]


def asks(snap: dict) -> list:
    return [p for p in snap["posts"] if p["url"] == "/api/signin-link"]


def linked(snap: dict) -> list:
    return [n["href"] for n in of_class(sign_in_card(snap), "a", "signin-link")]


class SigninLaterPageTest(unittest.TestCase):
    def test_a_page_loaded_while_a_sign_in_runs_asks_for_its_link_and_shows_the_code_field(self) -> None:
        (snap,) = render(LATER + [{"snapshot": True}])
        (post,) = asks(snap)
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"profile": "work"})
        card = sign_in_card(snap)
        self.assertEqual(linked(snap), ["https://claude.example/a?s=1"])
        self.assertEqual(len(of_class(card, "input", "signin-code")), 1)
        self.assertEqual(len(of_class(card, "button", "signin-cancel")), 1)
        self.assertEqual(of_class(card, "button", "signin-start"), [])

    def test_the_link_is_asked_once_per_attempt(self) -> None:
        one, two, three, four = render([
            START, {"hold": True},
            {"frame": frame([with_run(SIGNIN, "running", 7)])},
            {"frame": frame([with_run(SIGNIN, "running", 7), check_item("A", "manual-check")])},
            {"snapshot": True},
            {"release": {"status": 409, "text": "no sign-in is running for work\n"}},
            {"frame": frame([with_run(SIGNIN, "running", 7)])},
            {"snapshot": True},
            {"respond": {"status": 200, "text": "{\"attempt\":8,\"link\":null}"}},
            {"frame": frame([with_run(SIGNIN, "running", 8)])},
            {"frame": frame([with_run(SIGNIN, "running", 8), check_item("A", "manual-check")])},
            {"snapshot": True},
            {"respond": {"status": 200, "text": "{\"attempt\":9,\"link\":\"https://claude.example/c\"}"}},
            {"frame": frame([with_run(SIGNIN, "running", 9)])},
            {"snapshot": True}])
        self.assertEqual(len(asks(one)), 1)
        self.assertEqual(len(asks(two)), 1)
        self.assertEqual(len(asks(three)), 2)
        self.assertEqual(len(asks(four)), 3)
        self.assertEqual(linked(four), ["https://claude.example/c"])

    def test_an_answer_for_another_attempt_is_not_held(self) -> None:
        (snap,) = render([
            START,
            {"respond": {"status": 200, "text": "{\"attempt\":6,\"link\":\"https://claude.example/old\"}"}},
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True}])
        self.assertEqual(len(asks(snap)), 1)
        self.assertEqual(linked(snap), [])
        self.assertEqual(len(of_class(sign_in_card(snap), "button", "signin-start")), 1)
        # An older attempt's link is also dropped by the page's own reconcile; a newer one only by this rule.
        (newer,) = render([
            START,
            {"respond": {"status": 200, "text": "{\"attempt\":8,\"link\":\"https://claude.example/new\"}"}},
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True}])
        self.assertEqual(linked(newer), [])
        self.assertEqual(len(of_class(sign_in_card(newer), "button", "signin-start")), 1)

    def test_a_refused_ask_leaves_the_sign_in_action(self) -> None:
        (snap,) = render([
            START,
            {"respond": {"status": 409, "text": "no sign-in is running for work\n"}},
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual(len(asks(snap)), 1)
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
        self.assertEqual(linked(snap), [])
        self.assertEqual(of_class(card, "span", "signin-failed"), [])

    def test_a_cancel_from_another_page_ends_the_sign_in_here(self) -> None:
        one, two = render(LATER + [
            {"snapshot": True}, {"frame": frame([with_run(SIGNIN, "cancelled", 7)])},
            {"snapshot": True}])
        self.assertEqual(linked(one), ["https://claude.example/a?s=1"])
        card = sign_in_card(two)
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
        self.assertEqual(of_class(card, "input", "signin-code"), [])
        self.assertEqual(of_class(card, "button", "signin-cancel"), [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-run")],
                         ["The sign-in was cancelled."])

    def test_a_page_holding_the_attempts_link_does_not_ask(self) -> None:
        (snap,) = render(SIGNED_IN_STEPS + [
            {"frame": frame([with_run(SIGNIN, "running", 7)])}, {"snapshot": True}])
        self.assertEqual(asks(snap), [])

    def test_a_late_answer_for_an_older_attempt_does_not_replace_the_newer_link(self) -> None:
        one, two = render([
            START, {"hold": True},
            {"frame": frame([with_run(SIGNIN, "running", 7)])},
            {"respond": {"status": 200, "text": "{\"attempt\":8,\"link\":\"https://claude.example/c\"}"}},
            {"frame": frame([with_run(SIGNIN, "running", 8)])},
            {"snapshot": True},
            {"release": {"status": 200, "text": ANSWER}},
            {"snapshot": True}])
        self.assertEqual(linked(one), ["https://claude.example/c"])
        self.assertEqual(linked(two), ["https://claude.example/c"])
        self.assertEqual(len(asks(two)), 2)
        card = sign_in_card(two)
        self.assertEqual(len(of_class(card, "input", "signin-code")), 1)
        self.assertEqual(of_class(card, "button", "signin-start"), [])



class SigninRecoveredPageTest(unittest.TestCase):
    def test_a_running_sign_in_with_no_inbox_item_is_recovered_from_the_runs(self) -> None:
        run = {"work": {"state": "running", "at": None, "attempt": 7}}
        (snap,) = render([
            START, {"respond": {"status": 200, "text": ANSWER}},
            {"frame": {**frame([]), "signin_runs": run}}, {"snapshot": True}])
        (post,) = asks(snap)
        self.assertEqual(json.loads(post["body"]), {"profile": "work"})
        card = sign_in_card(snap)
        self.assertEqual(linked(snap), ["https://claude.example/a?s=1"])
        self.assertEqual(len(of_class(card, "input", "signin-code")), 1)
        self.assertEqual(len(of_class(card, "button", "signin-cancel")), 1)

    def test_a_typed_code_and_its_focus_survive_a_frame_on_a_recovered_card(self) -> None:
        run = {"work": {"state": "running", "at": None, "attempt": 7}}
        one, two = render([
            START, {"respond": {"status": 200, "text": ANSWER}},
            {"frame": {**frame([]), "signin_runs": run}},
            {"type": {"class": "signin-code", "text": "ab#C"}},
            {"frame": {**frame([check_item("A", "manual-check")]), "signin_runs": run}},
            {"snapshot": True},
            {"append": {"class": "signin-code", "text": "-1"}},
            {"click": "signin-send"}, {"snapshot": True}])
        code = field(one, "signin-code")
        self.assertEqual((code["value"], code["focused"]), ("ab#C", True))
        self.assertEqual(json.loads(two["posts"][-1]["body"]),
                         {"profile": "work", "code": "ab#C-1"})

    def test_an_ended_run_with_no_inbox_item_shows_no_card(self) -> None:
        run = {"work": {"state": "cancelled", "at": None, "attempt": 7}}
        (snap,) = render([START, {"frame": {**frame([]), "signin_runs": run}}, {"snapshot": True}])
        self.assertEqual(asks(snap), [])
        self.assertEqual([n for n in nodes(snap["inbox"]) if has_class(n, "signin")], [])


V = {**frame([]), "capacity": capacity([profile("work", "ok", week_left=50, signin=si("signed_in", 9))])}
FRESH = {**SIGNIN, "key": "signin/fresh", "profile": "fresh", "headline": "Sign in to fresh",
         "signin": si("signed_out", None, ask=True, ever=False)}
ADDED = "{\"attempt\":9,\"link\":\"https://claude.example/b\",\"profile\":\"fresh\"}"
RUNNING = {"fresh": {"state": "running", "at": None, "attempt": 9}}
ENDED = {"fresh": {"state": "cancelled", "at": "2026-11-14T10:00:00+00:00", "attempt": 9}}
ADD_STEPS = [
    START, {"frame": V}, {"click": "account-add-open"},
    {"type": {"class": "account-name", "text": "fresh"}},
    {"respond": {"status": 200, "text": ADDED}}, {"click": "account-add-send"},
]
NO_ITEM = ADD_STEPS + [{"frame": {**V, "signin_runs": RUNNING}}]
ELSE = "Finish this sign-in in Add account in the accounts panel."


def with_item(item: dict, runs: dict) -> dict:
    return {**V, "inbox": {"open": [item], "answered": []},
            "statement": {**V["statement"], "inbox_items": 1}, "signin_runs": runs}


def added(snap: dict, cls: str) -> list:
    return [n for n in nodes(snap["account_add"]) if has_class(n, cls)]


def added_reason(snap: dict) -> str:
    (reason,) = added(snap, "account-add-reason")
    return full(reason)


class AddAccountPageTest(unittest.TestCase):
    def test_an_add_posts_the_name_with_the_token(self) -> None:
        (snap,) = render(ADD_STEPS + [{"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"]), ("/api/account-add", "POST"))
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"name": "fresh"})

    def test_the_add_box_keeps_the_link_and_code_field_while_the_card_shows(self) -> None:
        (snap,) = render(ADD_STEPS + [
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)}, {"snapshot": True}])
        (note,) = added(snap, "account-add-note")
        self.assertEqual(full(note), "Added fresh. Its sign-in has started.")
        (link,) = [n for n in added(snap, "account-add-link") if n["tag"] == "a"]
        self.assertEqual(link["href"], "https://claude.example/b")
        self.assertEqual(len([n for n in added(snap, "account-code") if n["tag"] == "input"]), 1)
        self.assertEqual(len([n for n in added(snap, "account-signin-cancel") if n["tag"] == "button"]), 1)
        card = sign_in_card(snap)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")], [ELSE])
        for cls in ("signin-link", "signin-code", "signin-start", "signin-cancel"):
            self.assertEqual([n for n in nodes(card) if has_class(n, cls)], [], cls)

    def test_the_add_box_shows_the_outcome_when_the_sign_in_ends(self) -> None:
        for state, text in (
            ("signed_in", "fresh is signed in."),
            ("failed", "The sign-in to fresh did not finish."),
            ("timed_out", "The sign-in to fresh timed out."),
            ("cancelled", "The sign-in to fresh was cancelled."),
        ):
            with self.subTest(state=state):
                run = {"state": state, "at": "2026-11-14T10:00:00+00:00", "attempt": 9}
                (snap,) = render(NO_ITEM + [
                    {"frame": {**V, "signin_runs": {"fresh": run}}}, {"snapshot": True}])
                self.assertEqual([full(n) for n in added(snap, "account-add-outcome")], [text])
                self.assertEqual(len([n for n in added(snap, "account-add-open") if n["tag"] == "button"]), 1)
                self.assertEqual(added(snap, "account-code"), [])

    def test_the_outcome_clears_when_add_account_is_pressed(self) -> None:
        one, two, three = render(NO_ITEM + [
            {"frame": {**V, "signin_runs": ENDED}}, {"snapshot": True},
            {"click": "account-add-open"}, {"snapshot": True},
            {"click": "account-add-cancel"}, {"snapshot": True}])
        self.assertEqual(len(added(one, "account-add-outcome")), 1)
        self.assertEqual(added(two, "account-add-outcome"), [])
        self.assertEqual(len([n for n in added(two, "account-name") if n["tag"] == "input"]), 1)
        self.assertEqual(added(three, "account-add-outcome"), [])
        self.assertEqual(len([n for n in added(three, "account-add-open") if n["tag"] == "button"]), 1)

    def test_a_newer_attempt_ends_the_add_box_with_no_outcome(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"frame": {**V, "signin_runs": {"fresh": {"state": "running", "at": None, "attempt": 10}}}},
            {"snapshot": True}])
        self.assertEqual(added(snap, "account-add-outcome"), [])
        self.assertEqual(added(snap, "account-code"), [])
        self.assertEqual(len([n for n in added(snap, "account-add-open") if n["tag"] == "button"]), 1)

    def test_a_stale_add_answer_does_not_replace_a_newer_attempts_link(self) -> None:
        newer = {"fresh": {"state": "running", "at": None, "attempt": 10}}
        steps = [
            START, {"frame": V}, {"click": "account-add-open"},
            {"type": {"class": "account-name", "text": "fresh"}},
            {"hold": True}, {"click": "account-add-send"},
            {"respond": {"status": 200, "text": "{\"attempt\":10,\"link\":\"https://claude.example/ten\"}"}},
            {"frame": with_item(with_run(FRESH, "running", 10), newer)}, {"snapshot": True},
            {"release": {"status": 200, "text": ADDED}}, {"snapshot": True},
        ]
        one, two = render(steps)
        for snap in (one, two):
            self.assertEqual(len(asks(snap)), 1)
            self.assertEqual([n["href"] for n in of_class(sign_in_card(snap), "a", "signin-link")],
                             ["https://claude.example/ten"])
            self.assertEqual(len(of_class(sign_in_card(snap), "input", "signin-code")), 1)
        self.assertEqual(added(two, "account-add-link"), [])

    def test_an_older_attempts_outcome_ends_the_add_box_after_its_run_was_seen_running(self) -> None:
        older = {"fresh": {"state": "cancelled", "at": "2026-11-14T10:00:00+00:00", "attempt": 8}}
        one, two = render(NO_ITEM + [
            {"frame": {**V, "signin_runs": older}}, {"snapshot": True},
            {"frame": with_item(with_run(FRESH, "cancelled", 8), older)}, {"snapshot": True}])
        for snap in (one, two):
            self.assertEqual(added(snap, "account-add-link"), [])
            self.assertEqual(added(snap, "account-code"), [])
            self.assertEqual(added(snap, "account-add-outcome"), [])
            self.assertEqual(len([n for n in added(snap, "account-add-open") if n["tag"] == "button"]), 1)
        card = sign_in_card(two)
        self.assertEqual(of_class(card, "p", "signin-elsewhere"), [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)

    def test_the_card_offers_sign_in_in_the_frame_that_ends_the_added_run(self) -> None:
        (snap,) = render(ADD_STEPS + [
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)},
            {"frame": with_item(with_run(FRESH, "cancelled", 9), ENDED)},
            {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
        self.assertEqual(of_class(card, "p", "signin-elsewhere"), [])
        self.assertEqual([full(n) for n in added(snap, "account-add-outcome")],
                         ["The sign-in to fresh was cancelled."])

    def test_a_card_shown_before_the_add_answers_defers_once_it_answers(self) -> None:
        (snap,) = render([
            START, {"frame": V}, {"click": "account-add-open"},
            {"type": {"class": "account-name", "text": "fresh"}}, {"hold": True},
            {"click": "account-add-send"},
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)},
            {"release": {"status": 200, "text": ADDED}}, {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")], [ELSE])
        self.assertEqual(of_class(card, "input", "signin-code"), [])
        self.assertEqual([n for n in nodes(card) if has_class(n, "signin-link")], [])
        self.assertEqual(len([n for n in added(snap, "account-code") if n["tag"] == "input"]), 1)
        (link,) = [n for n in added(snap, "account-add-link") if n["tag"] == "a"]
        self.assertEqual(link["href"], "https://claude.example/b")

    def test_with_no_sign_in_item_the_control_carries_the_link_and_the_code(self) -> None:
        (snap,) = render(NO_ITEM + [{"snapshot": True}])
        (note,) = added(snap, "account-add-note")
        self.assertEqual(full(note), "Added fresh. Its sign-in has started.")
        (link,) = [n for n in added(snap, "account-add-link") if n["tag"] == "a"]
        self.assertEqual(link["href"], "https://claude.example/b")
        self.assertEqual(len([n for n in added(snap, "account-code") if n["tag"] == "input"]), 1)
        (send,) = [n for n in added(snap, "account-code-send") if n["tag"] == "button"]
        self.assertTrue(send["disabled"])
        self.assertEqual(len([n for n in added(snap, "account-signin-cancel") if n["tag"] == "button"]), 1)
        self.assertFalse([n for n in nodes(snap["inbox"]) if has_class(n, "signin")])

    def test_a_code_sent_from_the_control_posts_it_for_the_added_profile(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"type": {"class": "account-code", "text": " abc "}},
            {"respond": {"status": 204, "text": ""}}, {"click": "account-code-send"},
            {"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"]), ("/api/signin-code", "POST"))
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"profile": "fresh", "code": "abc"})
        (code,) = added(snap, "account-code")
        self.assertEqual(code["value"], "")

    def test_cancel_from_the_control_posts_the_cancel(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"respond": {"status": 204, "text": ""}}, {"click": "account-signin-cancel"},
            {"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"]), ("/api/signin-cancel", "POST"))
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"profile": "fresh"})

    def test_a_refused_code_shows_the_reason_in_the_control(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"type": {"class": "account-code", "text": "abc"}},
            {"respond": {"status": 409, "text": "no sign-in is running for fresh\n"}},
            {"click": "account-code-send"}, {"snapshot": True}])
        self.assertEqual(
            added_reason(snap), "Could not send the code: no sign-in is running for fresh")

    def test_a_link_held_from_an_add_is_dropped_when_its_run_ended(self) -> None:
        first, second = render(ADD_STEPS + [
            {"frame": {**V, "signin_runs": ENDED}}, {"snapshot": True},
            {"frame": with_item(FRESH, ENDED)}, {"snapshot": True}])
        self.assertEqual(added(first, "account-add-link"), [])
        self.assertEqual(len(added(first, "account-add-open")), 1)
        self.assertEqual([full(n) for n in added(first, "account-add-outcome")],
                         ["The sign-in to fresh was cancelled."])
        card = sign_in_card(second)
        self.assertEqual(of_class(card, "a", "signin-link"), [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)

    def test_a_continuation_ends_when_a_restart_drops_its_run_from_the_view(self) -> None:
        (snap,) = render(NO_ITEM + [{"frame": V}, {"snapshot": True}])
        self.assertEqual(added(snap, "account-add-link"), [])
        self.assertEqual(added(snap, "account-add-outcome"), [])
        self.assertEqual(len(added(snap, "account-add-open")), 1)

    def test_a_card_opened_after_a_restart_drops_the_dead_link(self) -> None:
        (snap,) = render(NO_ITEM + [{"frame": with_item(FRESH, {})}, {"snapshot": True}])
        card = sign_in_card(snap)
        self.assertEqual(of_class(card, "a", "signin-link"), [])
        self.assertEqual(len(of_class(card, "button", "signin-start")), 1)
        self.assertEqual(added(snap, "account-add-link"), [])

    def test_an_invalid_default_or_existing_name_disables_add_with_the_reason(self) -> None:
        bad = "not an account name: use a-z, 0-9, - and _"
        for text, reason in (
            ("Work", bad), ("a.b", bad), ("default", "default is not an account name"),
            ("work", "account work already exists"),
        ):
            with self.subTest(text=text):
                (snap,) = render([
                    START, {"frame": V}, {"click": "account-add-open"},
                    {"type": {"class": "account-name", "text": text}},
                    {"click": "account-add-send"}, {"snapshot": True}])
                (send,) = [n for n in added(snap, "account-add-send") if n["tag"] == "button"]
                self.assertTrue(send["disabled"])
                self.assertEqual(added_reason(snap), reason)
                self.assertFalse([p for p in snap["posts"] if p["url"] == "/api/account-add"])

    def test_a_refused_add_shows_the_reason_and_keeps_the_name(self) -> None:
        steps = list(ADD_STEPS)
        steps[4] = {"respond": {"status": 409, "text": "account fresh already exists\n"}}
        (snap,) = render(steps + [{"snapshot": True}])
        self.assertEqual(
            added_reason(snap), "Could not add the account: account fresh already exists")
        (name,) = added(snap, "account-name")
        self.assertEqual(name["value"], "fresh")
        self.assertEqual(added(snap, "account-add-link"), [])

    def test_the_typed_name_and_its_focus_survive_a_frame(self) -> None:
        (snap,) = render([
            START, {"frame": V}, {"click": "account-add-open"},
            {"type": {"class": "account-name", "text": "fre"}}, {"frame": V}, {"snapshot": True}])
        self.assertEqual(snap["field"], {"cls": "account-name", "value": "fre", "start": 3, "end": 3})

    def test_the_typed_code_and_its_focus_survive_a_frame(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"type": {"class": "account-code", "text": "ab"}},
            {"frame": {**V, "signin_runs": RUNNING}}, {"snapshot": True}])
        self.assertEqual(snap["field"], {"cls": "account-code", "value": "ab", "start": 2, "end": 2})


NO_LINK = "{\"attempt\":9,\"link\":null,\"profile\":\"fresh\"}"
NO_LINK_STEPS = ADD_STEPS[:4] + [{"respond": {"status": 200, "text": NO_LINK}}, ADD_STEPS[5]]
NO_LINK_RUNNING = NO_LINK_STEPS + [{"frame": {**V, "signin_runs": RUNNING}}]


class AddAccountNoLinkPageTest(unittest.TestCase):
    def test_an_add_with_no_link_keeps_a_way_to_fetch_the_link_and_to_cancel(self) -> None:
        (snap,) = render(NO_LINK_RUNNING + [{"snapshot": True}])
        (note,) = added(snap, "account-add-note")
        self.assertEqual(full(note), "Added fresh. Its sign-in has started.")
        self.assertEqual(len([n for n in added(snap, "account-link-get") if n["tag"] == "button"]), 1)
        self.assertEqual(len([n for n in added(snap, "account-signin-cancel") if n["tag"] == "button"]), 1)
        self.assertEqual([n for n in added(snap, "account-add-link") if n["tag"] == "a"], [])

    def test_fetching_the_link_posts_the_signin_and_shows_the_link_and_the_code_field(self) -> None:
        (snap,) = render(NO_LINK_RUNNING + [
            {"respond": {"status": 200, "text": ADDED}}, {"click": "account-link-get"},
            {"snapshot": True}])
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"]), ("/api/signin", "POST"))
        self.assertEqual(post["headers"]["X-Console-Token"], TOKEN)
        self.assertEqual(json.loads(post["body"]), {"profile": "fresh"})
        (link,) = [n for n in added(snap, "account-add-link") if n["tag"] == "a"]
        self.assertEqual(link["href"], "https://claude.example/b")
        self.assertEqual(len([n for n in added(snap, "account-code") if n["tag"] == "input"]), 1)

    def test_a_link_answered_after_a_frame_opened_the_card_reaches_the_add_box(self) -> None:
        (snap,) = render(NO_LINK_RUNNING + [
            {"hold": True}, {"click": "account-link-get"},
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)},
            {"release": {"status": 200, "text": ADDED}}, {"snapshot": True}])
        (link,) = [n for n in added(snap, "account-add-link") if n["tag"] == "a"]
        self.assertEqual(link["href"], "https://claude.example/b")
        card = sign_in_card(snap)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")], [ELSE])
        self.assertEqual(of_class(card, "a", "signin-link"), [])

    def test_a_refused_fetch_shows_the_reason_in_the_control(self) -> None:
        (snap,) = render(NO_LINK_RUNNING + [
            {"respond": {"status": 502, "text": "the sign-in could not start\n"}},
            {"click": "account-link-get"}, {"snapshot": True}])
        self.assertEqual(
            added_reason(snap), "Could not get the sign-in link: the sign-in could not start")

    def test_with_no_link_the_add_box_keeps_get_link_and_cancel_while_the_card_shows(self) -> None:
        (snap,) = render(NO_LINK_RUNNING + [
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)}, {"snapshot": True}])
        self.assertEqual(len([n for n in added(snap, "account-link-get") if n["tag"] == "button"]), 1)
        self.assertEqual(len([n for n in added(snap, "account-signin-cancel") if n["tag"] == "button"]), 1)
        card = sign_in_card(snap)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")], [ELSE])
        self.assertEqual(of_class(card, "button", "signin-start"), [])


class AddAccountKeepsCodePageTest(unittest.TestCase):
    def test_a_typed_code_stays_in_the_add_box_when_the_card_arrives(self) -> None:
        (snap,) = render(NO_ITEM + [
            {"type": {"class": "account-code", "text": "ab"}},
            {"frame": with_item(with_run(FRESH, "running", 9), RUNNING)}, {"snapshot": True}])
        self.assertEqual(snap["field"], {"cls": "account-code", "value": "ab", "start": 2, "end": 2})
        self.assertEqual(of_class(sign_in_card(snap), "input", "signin-code"), [])


QUIET = {**frame([]), "capacity": real_capacity(NOW_S, [
    {"name": "a", "week": .35, "signin": ("signed_in", NOW_S + 12 * 86400)},
    {"name": "b", "week": .5, "signin": ("signed_in", NOW_S + 20 * 86400)},
]), "profile_sessions": {"a": 0, "b": 0}}
WORK_CAP = real_capacity(NOW_S, [{"name": "work", "week": .5, "signin": ("signed_in", NOW_S + 2 * 86400)}])
GUARDED = {"X-Console-Token": TOKEN, "Content-Type": "application/json"}
OPEN_A = [{"click": "cap"}, {"respond": {"status": 200, "text": ANSWER}}, {"click": "acct-signin"}]


def row_of(snap: dict, name: str) -> dict:
    (found,) = [r for r in rows(snap) if full(
        next(n for n in nodes(r) if has_class(n, "acct-name"))) == name]
    return found


def in_row(row: dict, tag: str, cls: str) -> list:
    return of_class(row, tag, cls)


class PanelSigninPageTest(unittest.TestCase):
    def test_each_row_offers_sign_in_named_for_its_history(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35, "signin": ("signed_in", NOW_S + 12 * 86400)},
            {"name": "b", "week": .5}])}
        snap = opened(shown)
        self.assertEqual([full(n) for n in nodes(panel(snap)) if has_class(n, "acct-signin")],
                         ["Sign in again", "Sign in"])
        snap = opened(shown, {"click": "acct-signin"})
        post = snap["posts"][-1]
        self.assertEqual((post["url"], post["method"], post["headers"]),
                         ("/api/signin", "POST", GUARDED))
        self.assertEqual(json.loads(post["body"]), {"profile": "a"})

    def test_a_row_carries_its_sign_in_run_status(self) -> None:
        notes = {"running": "A sign-in is running.", "failed": "The sign-in did not finish.",
                 "timed_out": "The sign-in timed out.", "cancelled": "The sign-in was cancelled."}
        for state, note in notes.items():
            with self.subTest(state=state):
                shown = {**view([]), "capacity": real_capacity(NOW_S, [
                    {"name": "work", "week": .5, "signin": ("signed_out", None), "ever": True}]),
                    "signin_runs": {"work": {"state": state, "at": None, "attempt": 3}}}
                (work,) = rows(opened(shown))
                self.assertEqual([full(n) for n in in_row(work, "p", "signin-run")], [note])
        # A renewal outside the three-day window still shows how it ended: the outcome is not the ask.
        for state, note in notes.items():
            with self.subTest(signed_in=state):
                shown = {**view([]), "capacity": real_capacity(
                    NOW_S, [{"name": "work", "week": .5, "signin": ("signed_in", NOW_S + 12 * 86400)}]),
                    "signin_runs": {"work": {"state": state, "at": None, "attempt": 3}}}
                (work,) = rows(opened(shown))
                self.assertEqual([full(n) for n in in_row(work, "p", "signin-run")], [note])
        with self.subTest(signed_in="signed_in"):
            shown = {**view([]), "capacity": real_capacity(
                NOW_S, [{"name": "work", "week": .5, "signin": ("signed_in", NOW_S + 12 * 86400)}]),
                "signin_runs": {"work": {"state": "signed_in", "at": None, "attempt": 3}}}
            (work,) = rows(opened(shown))
            self.assertEqual(in_row(work, "p", "signin-run"), [])

    def _running_in_panel(self) -> list:
        shown = {**frame([SIGNIN]), "capacity": WORK_CAP}
        running = {**frame([with_run(SIGNIN, "running", 7)]), "capacity": WORK_CAP,
                   "signin_runs": {"work": {"state": "running", "at": None, "attempt": 7}}}
        return [START, {"frame": shown}, *OPEN_A, {"frame": running}], running

    def test_with_the_panel_open_the_running_sign_in_shows_in_its_row_and_the_card_points_there(self) -> None:
        steps, _ = self._running_in_panel()
        open_, closed = render([*steps, {"snapshot": True}, {"key": "Escape"}, {"snapshot": True}])
        (work,) = rows(open_)
        (link,) = in_row(work, "a", "signin-link")
        self.assertEqual(link["href"], "https://claude.example/a?s=1")
        self.assertEqual(len(in_row(work, "input", "signin-code")), 1)
        self.assertEqual(len(in_row(work, "button", "signin-send")), 1)
        self.assertEqual(len(in_row(work, "button", "signin-cancel")), 1)
        card = sign_in_card(open_)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")],
                         ["Finish this sign-in in the accounts panel."])
        self.assertEqual(of_class(card, "input", "signin-code"), [])
        card = sign_in_card(closed)
        (link,) = of_class(card, "a", "signin-link")
        self.assertEqual(link["href"], "https://claude.example/a?s=1")
        self.assertEqual(len(of_class(card, "input", "signin-code")), 1)
        self.assertEqual(closed["accounts_body"]["children"], [])

    def test_opening_the_panel_moves_a_running_sign_in_from_the_card_to_its_row(self) -> None:
        _, running = self._running_in_panel()
        before, after = render([
            START, {"respond": {"status": 200, "text": ANSWER}}, {"frame": running},
            {"snapshot": True}, {"click": "cap"}, {"snapshot": True}])
        self.assertEqual(len(of_class(sign_in_card(before), "input", "signin-code")), 1)
        card = sign_in_card(after)
        self.assertEqual([full(n) for n in of_class(card, "p", "signin-elsewhere")],
                         ["Finish this sign-in in the accounts panel."])
        self.assertEqual(of_class(card, "input", "signin-code"), [])
        self.assertEqual(len(in_row(row_of(after, "work"), "input", "signin-code")), 1)

    def test_a_typed_code_and_its_focus_survive_a_frame_in_the_panel(self) -> None:
        steps, running = self._running_in_panel()
        again = {**running, "statement": {**running["statement"], "headline": "again"}}
        snap, after = render([
            *steps, {"type": {"class": "signin-code", "text": "ab#C"}},
            {"select": {"cls": "signin-code", "start": 1, "end": 3}}, {"frame": again},
            {"snapshot": True}, {"key": "Escape"}, {"snapshot": True}])
        (code,) = in_row(row_of(snap, "work"), "input", "signin-code")
        self.assertEqual((code["value"], code["focused"], code["selection"]), ("ab#C", True, [1, 3]))
        (code,) = of_class(sign_in_card(after), "input", "signin-code")
        self.assertEqual(code["value"], "ab#C")

    def test_a_keyboard_code_send_or_cancel_keeps_the_focus_while_it_posts(self) -> None:
        steps, _ = self._running_in_panel()
        for cls, url in (("signin-send", "/api/signin-code"), ("signin-cancel", "/api/signin-cancel")):
            for extra in ([], [{"click": cls}]):
                with self.subTest(cls=cls, second_click=bool(extra)):
                    (snap,) = render([
                        *steps, {"type": {"class": "signin-code", "text": "abc"}}, {"focus_on": cls},
                        {"hold": True}, {"click": cls}, *extra, {"snapshot": True}])
                    (kept,) = [n for n in nodes(panel(snap)) if n["focused"]]
                    self.assertIn(cls, kept["cls"].split())
                    self.assertEqual(len([p for p in snap["posts"] if p["url"] == url]), 1)

    def test_escape_from_a_typed_code_leaves_no_field_focused(self) -> None:
        steps, _ = self._running_in_panel()
        typing, closed = render([
            *steps, {"type": {"class": "signin-code", "text": "ab#C"}}, {"snapshot": True},
            {"key": "Escape"}, {"snapshot": True}])
        self.assertEqual(typing["active"], "signin-code")
        self.assertIs(closed["accounts"]["hidden"], True)
        self.assertIsNone(closed["active"])
        self.assertIsNone(closed["field"])

    def test_a_keyboard_sign_in_keeps_the_focus_while_it_posts(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "b", "week": .5, "signin": ("signed_out", None)}])}
        for extra in ([], [{"click": "acct-signin"}]):
            with self.subTest(second_click=bool(extra)):
                (snap,) = render([
                    START, {"frame": shown}, {"click": "cap"}, {"focus_on": "acct-signin"},
                    {"hold": True}, {"click": "acct-signin"}, *extra, {"snapshot": True}])
                (kept,) = [n for n in nodes(panel(snap)) if n["focused"]]
                self.assertIn("acct-signin", kept["cls"].split())
                self.assertEqual(len([p for p in snap["posts"] if p["url"] == "/api/signin"]), 1)

    def test_a_sign_in_request_redraws_the_row_with_no_frame(self) -> None:
        refused = {"respond": {"status": 409, "text": "a sign-in is already running"}}
        failed = "Could not start the sign-in: a sign-in is already running"
        base = [START, {"frame": QUIET}, {"click": "cap"}]
        with self.subTest("refused_start"):
            first, second = render([*base, refused, {"click": "acct-signin"}, {"snapshot": True},
                                    {"frame": QUIET}, {"snapshot": True}])
            for snap in (first, second):
                a = row_of(snap, "a")
                self.assertEqual([full(n) for n in in_row(a, "span", "signin-failed")], [failed])
                (start,) = in_row(a, "button", "acct-signin")
                self.assertIs(start["disabled"], False)
        with self.subTest("refused_start_with_a_card"):
            shown = {**frame([SIGNIN]), "capacity": WORK_CAP}
            first, second = render([START, {"frame": shown}, {"click": "cap"}, refused,
                                    {"click": "acct-signin"}, {"snapshot": True},
                                    {"frame": shown}, {"snapshot": True}])
            for snap in (first, second):
                self.assertEqual(
                    [full(n) for n in in_row(row_of(snap, "work"), "span", "signin-failed")], [failed])
        with self.subTest("answer_before_the_stream"):
            (snap,) = render([*base, *OPEN_A[1:], {"snapshot": True}])
            a = row_of(snap, "a")
            (link,) = in_row(a, "a", "signin-link")
            self.assertEqual(link["href"], "https://claude.example/a?s=1")
            self.assertEqual(len(in_row(a, "input", "signin-code")), 1)
            self.assertEqual(len(in_row(a, "button", "signin-cancel")), 1)
        with self.subTest("link_fetched_for_a_running_sign_in"):
            running = {**QUIET, "signin_runs": {"a": {"state": "running", "at": None, "attempt": 7}}}
            (snap,) = render([*base, {"respond": {"status": 200, "text": ANSWER}},
                              {"frame": running}, {"snapshot": True}])
            self.assertEqual([json.loads(p["body"]) for p in asks(snap)], [{"profile": "a"}])
            (link,) = in_row(row_of(snap, "a"), "a", "signin-link")
            self.assertEqual(link["href"], "https://claude.example/a?s=1")
        typed = [*base, *OPEN_A[1:], {"type": {"class": "signin-code", "text": "ab#C-1"}}]
        with self.subTest("code_sent"):
            (snap,) = render([*typed, {"click": "signin-send"}, {"snapshot": True}])
            (code,) = in_row(row_of(snap, "a"), "input", "signin-code")
            self.assertEqual(code["value"], "")
        with self.subTest("code_refused"):
            (snap,) = render([*typed, {"respond": {"status": 400, "text": "the code was refused"}},
                              {"click": "signin-send"}, {"snapshot": True}])
            a = row_of(snap, "a")
            self.assertEqual([full(n) for n in in_row(a, "span", "signin-failed")],
                             ["Could not send the code: the code was refused"])
            (code,) = in_row(a, "input", "signin-code")
            self.assertEqual(code["value"], "ab#C-1")
        with self.subTest("cancel_refused"):
            (snap,) = render([*typed, {"respond": {"status": 409, "text": "no sign-in is running"}},
                              {"click": "signin-cancel"}, {"snapshot": True}])
            self.assertEqual([full(n) for n in in_row(row_of(snap, "a"), "span", "signin-failed")],
                             ["Could not cancel: no sign-in is running"])

    def test_the_panel_never_draws_peach(self) -> None:
        nolink = {"respond": {"status": 200, "text": "{\"attempt\":7,\"link\":null}"}}
        (snap,) = render([
            START, {"frame": QUIET}, {"click": "cap"}, nolink, {"click": "acct-signin"}, nolink,
            {"frame": {**QUIET, "signin_runs": {"a": {"state": "running", "at": None, "attempt": 7}}}},
            {"snapshot": True}])
        a = row_of(snap, "a")
        (start,) = in_row(a, "button", "signin-start")
        self.assertIn("acct-signin", start["cls"].split())
        self.assertEqual(len(in_row(a, "button", "signin-cancel")), 1)
        for n in nodes(panel(snap)):
            self.assertFalse({"primary", "needs"} & set(n["cls"].split()), n["cls"])
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))
        for selector, decls in style_rules(style):
            if ".acct-" in selector or "#accounts" in selector:
                for value in decls.values():
                    self.assertNotIn("var(--peach)", value, selector)

    def test_add_account_sits_in_the_panel(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        section = html.index('id="accounts"')
        self.assertLess(section, html.index('id="account-add"'))
        self.assertLess(html.index('id="account-add"'), html.index("</section>", section))
        top_in = html[html.index('<div class="top-in">'):html.index('<section class="acct-panel"')]
        self.assertNotIn('id="account-add"', top_in)
        before = {**frame([]), "capacity": real_capacity(NOW_S, [
            {"name": "work", "week": .5, "signin": ("signed_in", NOW_S + 9 * 86400)}])}
        after = {**frame([]), "capacity": real_capacity(NOW_S, [
            {"name": "work", "week": .5, "signin": ("signed_in", NOW_S + 9 * 86400)},
            {"name": "fresh", "signin": ("signed_out", None), "ever": False}]),
            "signin_runs": RUNNING}
        (snap,) = render([
            START, {"frame": before}, {"click": "cap"}, {"click": "account-add-open"},
            {"type": {"class": "account-name", "text": "fresh"}},
            {"respond": {"status": 200, "text": ADDED}}, {"click": "account-add-send"},
            {"frame": after}, {"snapshot": True}])
        self.assertIs(snap["accounts"]["hidden"], False)
        fresh = row_of(snap, "fresh")
        self.assertEqual([full(n) for n in in_row(fresh, "p", "signin-elsewhere")],
                         ["Finish this sign-in in Add account below."])
        self.assertEqual(in_row(fresh, "input", "signin-code"), [])

    def test_the_panel_holds_every_account_control_and_detail(self) -> None:
        shown = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35, "five": .6, "week_reset": NOW_S + 4 * 86400,
             "five_reset": NOW_S + 3600, "signin": ("signed_in", NOW_S + 12 * 86400)},
            {"name": "b", "signin": ("signed_out", None), "ever": True}],
            excluded=("b",), pinned="a"), "profile_sessions": {"a": 1, "b": 0}}
        snap = opened(shown)
        a, b = rows(snap)
        def labels(r: dict) -> list:
            return [full(n) for n in in_row(r, "div", "acct-act")[0]["children"]
                    if n["tag"] == "button"]

        self.assertEqual(labels(a), ["Exclude", "Unpin", "Sign in again", "Remove"])
        self.assertEqual(labels(b), ["Include", "Pin", "Sign in again", "Remove"])
        shown_details = details(a)
        for want in ("65% of the week left", "40% of 5 hours", "signed in, ends in 12 days"):
            self.assertIn(want, shown_details)
        self.assertTrue(any(d.startswith("resets ") for d in shown_details), shown_details)
        (add,) = [n for n in nodes(snap["account_add"]) if has_class(n, "account-add-open")]
        self.assertEqual(full(add), "Add account")
        self.assertEqual(
            [n for n in nodes(snap["capacity"])[1:] if n["tag"] in ("button", "input", "a")], [])
        (live,) = render([START, {"frame": QUIET}, {"click": "cap"}, *OPEN_A[1:], {"snapshot": True}])
        a = row_of(live, "a")
        for tag, cls in (("a", "signin-link"), ("input", "signin-code"),
                         ("button", "signin-send"), ("button", "signin-cancel")):
            self.assertEqual(len(in_row(a, tag, cls)), 1, cls)

    def test_every_panel_control_posts_a_guarded_page_write(self) -> None:
        from agent_tools.console import service
        two = {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "a", "week": .35, "five": .6, "week_reset": NOW_S + 4 * 86400,
             "five_reset": NOW_S + 3600, "signin": ("signed_in", NOW_S + 12 * 86400)},
            {"name": "b", "signin": ("signed_out", None), "ever": True}],
            excluded=("b",), pinned="a"), "profile_sessions": {"a": 1, "b": 0}}
        (one,) = render([
            START, {"frame": two}, {"click": "cap"}, {"click": "acct-toggle"}, {"click": "acct-pin"},
            {"click": "acct-signin"}, {"click": "acct-remove"},
            {"type": {"class": "acct-remove-name", "text": "a"}}, {"click": "acct-remove-send"},
            {"click": "account-add-open"}, {"type": {"class": "account-name", "text": "fresh"}},
            {"click": "account-add-send"}, {"snapshot": True}])
        (second,) = render([
            START, {"frame": QUIET}, {"click": "cap"}, {"respond": {"status": 200, "text": ANSWER}},
            {"click": "acct-signin"}, {"type": {"class": "signin-code", "text": "ab#C-1"}},
            {"click": "signin-send"}, {"click": "signin-cancel"},
            {"respond": {"status": 200, "text": "{\"attempt\":4,\"link\":\"https://claude.example/b?s=2\"}"}},
            {"frame": {**QUIET, "signin_runs": {
                "a": {"state": "running", "at": None, "attempt": 7},
                "b": {"state": "running", "at": None, "attempt": 4}}}},
            {"snapshot": True}])
        urls = set()
        for snap in (one, second):
            for post in snap["posts"]:
                if post["url"] == "/api/looked":
                    continue
                urls.add(post["url"])
                self.assertIn(post["url"], service.PAGE_WRITES)
                self.assertEqual(post["method"], "POST")
                self.assertEqual(post["headers"], GUARDED)
        self.assertEqual([(p["url"], json.loads(p["body"])) for p in second["posts"]
                          if p["url"] != "/api/looked"], [
            ("/api/signin", {"profile": "a"}),
            ("/api/signin-code", {"profile": "a", "code": "ab#C-1"}),
            ("/api/signin-cancel", {"profile": "a"}),
            ("/api/signin-link", {"profile": "b"})])
        (link,) = in_row(row_of(second, "b"), "a", "signin-link")
        self.assertEqual(link["href"], "https://claude.example/b?s=2")
        self.assertEqual(urls, {"/api/exclusion", "/api/pin", "/api/signin", "/api/account-remove",
                                "/api/account-add", "/api/signin-code", "/api/signin-cancel",
                                "/api/signin-link"})


class PageCheckHeadingTest(unittest.TestCase):
    def test_the_card_is_headed_by_the_ask_with_the_check_id_as_a_label(self) -> None:
        lead = check_item("A", "manual-check", headline=DEMO_QUESTION, check_id="A3",
                          detail=DEMO_REST)
        snap = render([START, {"frame": frame([lead])}, {"snapshot": True}])[-1]
        card = snap["inbox"]["children"][0]
        (heading,) = [n for n in nodes(card) if n["tag"] == "h2" and has_class(n, "q")]
        self.assertEqual(full(heading), DEMO_QUESTION)
        self.assertNotIn("A3", full(heading))
        (label,) = labels_of(card)
        self.assertEqual(full(label), "A3")
        self.assertEqual(label["tag"], "span")
        (head,) = [n for n in nodes(card) if n["tag"] == "p" and has_class(n, "head")]
        classes = [c["cls"].split() for c in head["children"]]
        at = next(i for i, c in enumerate(head["children"]) if c is label)
        self.assertIn("kind", classes[at - 1])
        self.assertIn(DEMO_REST, full(card))
        self.assertEqual(full(card).count(DEMO_QUESTION), 1)

    def test_a_row_puts_the_check_id_beside_its_headline(self) -> None:
        snap = render([START, {"frame": frame([ANSWERABLE, check_item(
            "B", "manual-check", headline=DEMO_QUESTION, check_id="A4")])},
            {"snapshot": True}])[-1]
        (head,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "p" and has_class(n, "row-head")
                   and any(c["tag"] == "b" and c["text"] == DEMO_QUESTION for c in n["children"])]
        kids = head["children"]
        self.assertTrue(has_class(kids[0], "kind"))
        self.assertTrue(has_class(kids[1], "check-id"))
        self.assertEqual(full(kids[1]), "A4")
        self.assertEqual((kids[2]["tag"], kids[2]["text"]), ("b", DEMO_QUESTION))

    def test_an_answered_check_line_starts_with_its_check_id(self) -> None:
        done = check_item("Z", "manual-check", answered=True, headline=DEMO_QUESTION,
                          check_id="A5", answered_at="2026-11-11T10:00:00+00:00")
        snap = render([{"start": {"focused": False, "clock": NOW_MS}},
                       {"frame": frame([], answered=[done])}, {"snapshot": True}])[-1]
        (fold,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "details" and has_class(n, "done-item")]
        (summary,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual([(c["tag"], c["cls"]) for c in summary["children"]],
                         [("span", "check-id"), ("b", ""), ("span", "when")])
        self.assertEqual(summary["children"][0]["text"], "A5")

    def test_an_item_without_a_check_id_has_no_label(self) -> None:
        opened = [ANSWERABLE, check_item("M", "manual-check"),
                  check_item("N", "manual-check", check_id=""),
                  check_item("V", "verdict", check_id=""),
                  item("C", reason="conflict", headline="Landing stopped on a merge conflict.",
                       items=["x"])]
        done = item("Z", answered=True, headline="Which database?",
                    answered_at="2026-11-11T10:00:00+00:00")
        snap = render([{"start": {"focused": False, "clock": NOW_MS}},
                       {"frame": frame(opened, answered=[done])}, {"snapshot": True}])[-1]
        self.assertEqual(labels_of(snap["inbox"]), [])
        (heading,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "h2" and has_class(n, "q")]
        self.assertEqual(full(heading), "Which host?")


class LapsedResetPageTest(unittest.TestCase):
    """#1045: a frame drawn before a reset passed does not keep naming that reset."""
    at_now = {"start": {"focused": False, "clock": NOW_MS}}

    def frame_read_before(self, reset_in_s: int) -> dict:
        """The capacity the console built an hour before the page's clock, its week resetting `reset_in_s` after that."""
        then = NOW_S - 3600
        return {**view([]), "capacity": real_capacity(then, [
            {"name": "p1", "week": .35, "five": .6, "week_reset": then + reset_in_s,
             "five_reset": then + reset_in_s}])}

    def test_a_reset_in_the_past_is_not_shown_on_the_strip_or_in_the_panel(self) -> None:
        strip_snap, panel_snap = (
            render([self.at_now, {"frame": self.frame_read_before(1800)}, {"snapshot": True}])[0],
            opened_at(self.frame_read_before(1800)))
        (acct,) = accounts(strip_snap)
        self.assertEqual(full(part(strip_snap, "cap-acct")), "p1reset, not yet used")
        self.assertEqual(bars(acct), [])
        self.assertNotIn("65%", full(strip_snap["capacity"]))
        (row,) = rows(panel_snap)
        self.assertEqual(details(row), ["reset, not yet used", "sign-in unknown"])
        self.assertEqual([n for n in nodes(row) if has_class(n, "acct-reset")], [])

    def test_a_reset_still_ahead_is_shown(self) -> None:
        panel_snap = opened_at(self.frame_read_before(2 * 3600))
        (row,) = rows(panel_snap)
        self.assertEqual(details(row)[0], "65% of the week left")
        self.assertEqual([full(n) for n in nodes(row) if has_class(n, "acct-reset")],
                         ["resets " + weekday(datetime.fromtimestamp(
                             NOW_S + 3600, timezone.utc).isoformat())])

    def test_a_reset_passing_between_frames_is_dropped_when_the_clock_moves(self) -> None:
        frame = self.frame_read_before(2 * 3600)
        before, after = render([
            self.at_now, {"frame": frame}, {"click": "cap"}, {"snapshot": True},
            {"clock": NOW_MS + 2 * 3600 * 1000}, {"snapshot": True},
        ])
        (row,) = rows(before)
        self.assertIn("65% of the week left", details(row))
        (late,) = rows(after)
        self.assertEqual(details(late), ["reset, not yet used", "sign-in unknown"])
        self.assertIn("reset, not yet used", full(after["capacity"]))
        self.assertNotIn("65%", full(after["capacity"]))

    def refused_frame(self, reset_in_s: int) -> dict:
        """An hour before the page's clock, p1 refused until `reset_in_s` after that and p2 had room."""
        then = NOW_S - 3600
        return {**view([]), "capacity": real_capacity(then, [
            {"name": "p1", "week": 1.0, "five": .6, "refused": True, "week_reset": then + reset_in_s,
             "five_reset": then + reset_in_s}])}

    def test_a_refused_reading_still_out_is_shown_out(self) -> None:
        (row,) = rows(opened_at(self.refused_frame(2 * 3600)))
        self.assertEqual(details(row)[0][:9], "out until")

    def test_an_out_until_in_the_past_is_not_shown_on_the_strip_or_in_the_panel(self) -> None:
        strip_snap, panel_snap = (
            render([self.at_now, {"frame": self.refused_frame(1800)}, {"snapshot": True}])[0],
            opened_at(self.refused_frame(1800)))
        (acct,) = accounts(strip_snap)
        self.assertEqual(full(part(strip_snap, "cap-acct")), "p1reset, not yet used")
        self.assertNotIn("out until", full(strip_snap["capacity"]))
        self.assertNotIn("out until", full(panel(panel_snap)))
        self.assertNotIn("Resumes", full(strip_snap["statement"]))
        self.assertEqual(text(strip_snap["promoted"]), "")
        (row,) = rows(panel_snap)
        self.assertEqual(details(row), ["reset, not yet used", "sign-in unknown"])

    def test_an_out_until_passing_between_frames_is_dropped_when_the_clock_moves(self) -> None:
        before, after = render([
            self.at_now, {"frame": self.refused_frame(2 * 3600)}, {"click": "cap"}, {"snapshot": True},
            {"clock": NOW_MS + 2 * 3600 * 1000}, {"snapshot": True},
        ])
        (row,) = rows(before)
        self.assertEqual(details(row)[0][:9], "out until")
        (late,) = rows(after)
        self.assertEqual(details(late), ["reset, not yet used", "sign-in unknown"])
        self.assertIn("reset, not yet used", full(after["capacity"]))
        self.assertNotIn("out until", full(after["capacity"]))


def opened_at(frame: dict) -> dict:
    (snap,) = render([LapsedResetPageTest.at_now, {"frame": frame}, {"click": "cap"}, {"snapshot": True}])
    return snap


def registered(snap: dict, cls: str) -> list:
    return [n for n in nodes(snap["register"]) if has_class(n, cls)]


REGISTERING = {"root": "/srv/r", "name": "r", "project_id": None, "status": "running",
               "result": None, "outcome": None, "at": None,
               "headline": "Planning the adoption of r…", "lines": [], "note": None,
               "line": "Planning the adoption of r…", "refused": None, "adoption": None,
               "approve": None}
REGISTERED = {**REGISTERING, "status": "done", "result": "planned", "outcome": "reconcile",
              "at": "2026-11-15T08:00:00+00:00",
              "headline": "What adopting r would change: it has agent files or a contract to bring up to date",
              "lines": ["moves 2 agent files under .agents/", "writes the project contract"],
              "note": "The plan has 1 open question.", "line": "Register r: 1 question open"}
Q_CANDIDATE = {
    "id": "candidate-class", "subject": ".claude/odd.md",
    "ask": "What should happen to .claude/odd.md? No rule covers this agent file.",
    "options": [{"value": "archive-history",
                 "label": "Archive it under .agents/knowledge/archive/adopted/"}],
    "recommended": None, "why": None}
Q_REFERENCE = {
    "id": "path-reference", "subject": "tools/show.sh:1:5",
    "ask": "tools/show.sh line 1 names .claude/specs/a.md, which this plan moves. "
           "Should it follow the move?",
    "options": [{"value": "rewrite", "label": "Change it to .agents/artifacts/specs/a.md"},
                {"value": "retain", "label": "Leave it as it is"}],
    "recommended": None, "why": None}
Q_SECRET = {
    "id": "candidate-class", "subject": ".claude/secrets/key.md",
    "ask": "What should happen to .claude/secrets/key.md? No rule covers this agent file.",
    "options": [], "recommended": None,
    "why": ".claude/secrets/key.md looks like a secret, so it cannot be answered here: remove it "
           "from the repository in its own commit, then register the repository again."}
PLAN_A = "sha256:" + "a" * 64
ASKING = {**REGISTERED, "plan_id": PLAN_A, "state": "draft", "refusal": None, "refused": None,
          "note": "The plan has 3 open questions.", "line": "Register r: 3 questions open",
          "questions": [Q_CANDIDATE, Q_REFERENCE, Q_SECRET]}
READY_SHOWN = {**ASKING, "state": "ready", "questions": [],
               "note": "The plan is ready.", "line": "Register r: ready to apply",
               "approve": "approve", "adoption": None}
OPENED_ADOPTION = {
    "status": "done", "step": "opened", "state": "open",
    "headline": "Waiting for the pull request of r to be ready to merge.",
    "lines": ["Applied on the branch adopt-aaaaaaaaaaaa as one commit, cccccccccccc.",
              "Pushed adopt-aaaaaaaaaaaa to origin.", "Opened pull request #7 against main."],
    "note": None, "branch": "adopt-aaaaaaaaaaaa", "commit": "c" * 40,
    "url": "https://github.com/o/r/pull/7"}
ADOPTION_ITEM = {
    "type": "inbox_item", "reason": "adoption", "key": "adoption/" + PLAN_A, "project_id": "o/r",
    "name": "r", "headline": "The adoption of o/r is ready to merge",
    "url": "https://github.com/o/r/pull/7", "number": 7, "answered": False,
    "waiting_since": "2026-11-15T08:00:00+00:00"}
READY = [START, {"frame": {**frame([]), "registration": READY_SHOWN}}]
R_PLAN = PLAN_A


def register_item(n: int, q: dict, **fields) -> dict:
    options = [o["label"] for o in q["options"]]
    base = {"type": "inbox_item", "reason": "register", "key": f"register/{R_PLAN}/{n}",
            "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
            "plan_id": R_PLAN, "id": q["id"], "subject": q["subject"], "headline": q["ask"],
            "why": q["why"], "refusal": None, "more_questions": 0,
            "questions": [{"question": q["ask"], "options": options, "chosen": None,
                           "recommended": None, "recommended_index": None}] if options else [],
            "values": [o["value"] for o in q["options"]], "items": [], "answers": [],
            "answered": False, "waiting_since": "2026-11-15T08:00:00+00:00"}
    base.update(fields)
    return base


R0 = register_item(1, Q_REFERENCE)
R1 = register_item(2, Q_SECRET)
R2 = register_item(0, Q_CANDIDATE)

RETRY_HEADLINE = "r was not registered: the repository has no origin remote."
RETRY_WHY = "Add the repository's origin remote, then choose Retry."
RETRY_ITEM = {
    "type": "inbox_item", "reason": "register_retry",
    "key": f"register-retry/{PLAN_A}/2026-11-15T09:00:00+00:00",
    "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
    "plan_id": PLAN_A, "id": None, "subject": None, "headline": RETRY_HEADLINE,
    "why": RETRY_WHY, "refusal": None, "more_questions": 0,
    "questions": [{"question": RETRY_HEADLINE, "options": ["Retry"], "chosen": None,
                   "recommended": None, "recommended_index": None}],
    "values": ["retry"], "items": [], "answers": [], "answered": False,
    "waiting_since": "2026-11-15T09:00:00+00:00"}
REFUSED_SHOWN = {**READY_SHOWN, "approve": None, "line": RETRY_HEADLINE + " " + RETRY_WHY,
                 "adoption": {**OPENED_ADOPTION, "state": "merged",
                              "headline": RETRY_HEADLINE + " " + RETRY_WHY, "note": None}}

APPLY_ITEM = {
    "type": "inbox_item", "reason": "register_apply",
    "key": f"register-apply/{PLAN_A}/2026-11-15T08:00:00+00:00",
    "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
    "plan_id": PLAN_A, "id": None, "subject": None, "headline": "Apply this adoption?",
    "why": None, "lines": READY_SHOWN["lines"], "refusal": None, "more_questions": 0,
    "text": False,
    "questions": [{"question": "Apply this adoption?", "options": ["Apply it", "Not now"],
                   "chosen": None, "recommended": None, "recommended_index": None}],
    "values": ["apply", "not_now"], "items": [], "answers": [], "answered": False,
    "waiting_since": "2026-11-15T08:00:00+00:00"}
PUSH_FAILED_ADOPTION = {
    **OPENED_ADOPTION, "step": "push_failed", "state": None,
    "headline": "The branch adopt-aaaaaaaaaaaa was not pushed: remote rejected the push.",
    "lines": [OPENED_ADOPTION["lines"][0]],
    "note": "Check that the repository's origin can be reached from this host and accepts the "
            "push, then choose Try again.",
    "url": None}
FAILED_SHOWN = {**READY_SHOWN, "approve": "retry", "adoption": PUSH_FAILED_ADOPTION,
                "lines": [],
                "line": PUSH_FAILED_ADOPTION["headline"] + " " + PUSH_FAILED_ADOPTION["note"]}
TRY_ITEM = {
    **APPLY_ITEM, "key": APPLY_ITEM["key"] + "/2026-11-15T08:05:00+00:00",
    "headline": PUSH_FAILED_ADOPTION["headline"], "why": PUSH_FAILED_ADOPTION["note"],
    "lines": [],
    "questions": [{**APPLY_ITEM["questions"][0], "question": PUSH_FAILED_ADOPTION["headline"],
                   "options": ["Try again", "Not now"]}],
    "values": ["retry", "not_now"]}


CONFIRM_TEXT = "Registering lets agents run in this folder with the folder's own settings and hooks."
WAITING_SHOWN = {**REGISTERED, "result": "not_registered", "outcome": "no_change",
                 "headline": "r is already adopted and is not registered yet.", "lines": [],
                 "note": "Choose Register it to register it.",
                 "line": "r is already adopted and is not registered yet. Choose Register it to register it."}
CONFIRM_ITEM = {
    "type": "inbox_item", "reason": "register_confirm",
    "key": "register-confirm//srv/r/2026-11-15T08:00:00+00:00",
    "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
    "plan_id": None, "id": None, "subject": None, "headline": "Register this project?",
    "why": CONFIRM_TEXT, "lines": [], "refusal": None, "more_questions": 0, "text": False,
    "questions": [{"question": "Register this project?", "options": ["Register it", "Not now"],
                   "chosen": None, "recommended": None, "recommended_index": None}],
    "values": ["register", "not_now"], "items": [], "answers": [], "answered": False,
    "waiting_since": "2026-11-15T08:00:00+00:00"}

FAILED_HEADLINE = ("The adoption plan for r could not start: the agent platform's files are not "
                   "installed on this host.")
FAILED_WHY = "Run just switch on this computer to install them, then choose Try again."
FAILED_ITEM = {
    "type": "inbox_item", "reason": "register_failed",
    "key": "register-failed//srv/r/2026-11-15T08:00:00+00:00",
    "project_id": None, "root": "/srv/r", "name": "r", "title": "Register r",
    "plan_id": None, "id": None, "subject": None, "headline": FAILED_HEADLINE,
    "why": FAILED_WHY, "lines": [], "refusal": None, "more_questions": 0, "text": False,
    "questions": [{"question": FAILED_HEADLINE, "options": ["Try again", "Not now"],
                   "chosen": None, "recommended": None, "recommended_index": None}],
    "values": ["try_again", "not_now"], "items": [], "answers": [], "answered": False,
    "waiting_since": "2026-11-15T08:00:00+00:00"}
FAILED_REGISTRATION = {**WAITING_SHOWN, "result": "failed", "line": "Register r: needs you",
                       "lines": [], "note": None, "adoption": None}


def cards(items: list, registration: dict = ASKING) -> dict:
    return {**frame(items), "registration": registration}


REGISTER_OPEN = [START, {"frame": {**frame([]), "registration": None}}, {"click": "register-open"}]
REGISTER_TYPED = REGISTER_OPEN + [{"type": {"class": "register-path", "text": "/srv/r"}}]


class RegisterControlTest(unittest.TestCase):
    def test_register_sits_at_the_foot_of_the_side_column(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        self.assertLess(html.index('id="unmanaged"'), html.index('id="register"'))
        self.assertLess(html.index('id="register"'), html.index("</aside>"))

    def test_the_control_opens_a_path_field_that_register_enables(self) -> None:
        shut, opened, typed = render([
            START, {"frame": {**frame([]), "registration": None}}, {"snapshot": True},
            {"click": "register-open"}, {"snapshot": True},
            {"type": {"class": "register-path", "text": "/srv/r"}}, {"snapshot": True}])
        self.assertEqual(len(registered(shut, "register-open")), 1)
        self.assertEqual(registered(shut, "register-path"), [])
        (field,) = registered(opened, "register-path")
        self.assertEqual((field["tag"], field["label"], field["placeholder"]),
                         ("input", "Repository path", "Path of a repository on this host"))
        (send,) = registered(opened, "register-send")
        self.assertEqual(full(send), "Register")
        self.assertIs(send["disabled"], True)
        self.assertEqual(full(registered(opened, "register-cancel")[0]), "Cancel")
        self.assertIs(registered(typed, "register-send")[0]["disabled"], False)

    def test_a_typed_path_survives_a_frame(self) -> None:
        (snap,) = render(REGISTER_TYPED + [
            {"frame": {**frame([]), "registration": None}}, {"snapshot": True}])
        self.assertEqual(snap["field"], {"cls": "register-path", "value": "/srv/r", "start": 6, "end": 6})

    def test_a_refused_write_shows_its_reason_and_keeps_the_path(self) -> None:
        (snap,) = render(REGISTER_TYPED + [
            {"respond": {"status": 409, "text": "/srv/r is not the top of a git checkout\n"}},
            {"click": "register-send"}, {"snapshot": True}])
        (reason,) = registered(snap, "register-reason")
        self.assertEqual(full(reason), "/srv/r is not the top of a git checkout")
        self.assertEqual(registered(snap, "register-path")[0]["value"], "/srv/r")
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-project")
        self.assertEqual(json.loads(post["body"]), {"path": "/srv/r"})

    def test_an_accepted_write_closes_the_field(self) -> None:
        (snap,) = render(REGISTER_TYPED + [
            {"respond": {"status": 204, "text": ""}}, {"click": "register-send"}, {"snapshot": True}])
        self.assertEqual(registered(snap, "register-path"), [])
        self.assertEqual(len(registered(snap, "register-open")), 1)

    def test_a_running_registration_shows_its_line_only(self) -> None:
        (snap,) = render([START, {"frame": {**frame([]), "registration": REGISTERING}},
                          {"snapshot": True}])
        (line,) = registered(snap, "register-line")
        self.assertEqual(full(line), REGISTERING["line"])
        self.assertEqual(registered(snap, "register-close"), [])
        self.assertEqual([n for n in nodes(snap["register"]) if n["tag"] == "li"], [])

    def test_a_done_registration_shows_its_line_and_lines_and_no_close(self) -> None:
        done = {**frame([]), "registration": REGISTERED}
        (shown,) = render([START, {"frame": done}, {"snapshot": True}])
        (result,) = registered(shown, "register-result")
        self.assertEqual(
            [full(n) for n in nodes(result)[1:] if n["tag"] in ("p", "li", "button")],
            [REGISTERED["line"], *REGISTERED["lines"]])
        self.assertEqual(registered(shown, "register-close"), [])

    def test_with_no_project_the_register_control_still_shows(self) -> None:
        (snap,) = render([START, {"frame": {**frame([]), "registration": None}}, {"snapshot": True}])
        self.assertIn("No project is registered yet.", full(snap["projects"]))
        self.assertEqual(len(registered(snap, "register-open")), 1)

    def test_at_480_the_register_control_fits(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const box = document.getElementById('register');
          const edge = document.documentElement.clientWidth;
          const kids = [...box.querySelectorAll('*')].map((e) => e.getBoundingClientRect());
          return {fits: box.scrollWidth <= box.clientWidth, kids: kids.length,
                  inside: kids.every((r) => r.right <= edge)};
        }"""
        wide = {**REGISTERED, "root": "/home/anis/Projects/" + "a-long-directory-name/" * 3,
                "lines": ["moves 2 agent files under .agents/", "writes the project contract",
                          "rewrites 14 links in /home/anis/Projects/a-long-directory-name/README.md"]}
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})",
                              {**view([]), "registration": wide})
                page.click(".register-open")
                page.fill(".register-path", "/home/anis/Projects/" + "a-long-directory-name/" * 3)
                got = page.evaluate(measure)
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})",
                              {**view([]), "registration": {
                                  **READY_SHOWN, "approve": None, "adoption": OPENED_ADOPTION}})
                adopted = page.evaluate(measure)
            finally:
                browser.close()
        self.assertGreater(got["kids"], 5)
        self.assertTrue(got["fits"], got)
        self.assertTrue(got["inside"], got)
        self.assertGreater(adopted["kids"], 5)
        self.assertTrue(adopted["fits"], adopted)
        self.assertTrue(adopted["inside"], adopted)

    def test_a_ready_plan_shows_only_that_it_is_ready(self) -> None:
        plan_id = "sha256:" + "3f9a" * 16
        ready = {**REGISTERED, "state": "ready", "plan_id": plan_id, "questions": [],
                 "answered": [], "note": "The plan is ready.", "line": "Register r: ready to apply"}
        (snap,) = render([START, {"frame": {**frame([]), "registration": ready}}, {"snapshot": True}])
        (result,) = registered(snap, "register-result")
        shown = full(result)
        self.assertIn("Register r: ready to apply", shown)
        self.assertNotIn(plan_id, shown)
        self.assertNotIn("sha256", shown)
        self.assertNotIn("adopt-project", shown)
        self.assertNotIn("adopt-project apply", shown)

    def test_an_open_or_ready_adoption_is_one_sentence_with_no_lines_link_or_close(self) -> None:
        for sentence in ("The pull request of r is not ready to merge yet.",
                         "The pull request of r is ready to merge."):
            with self.subTest(sentence=sentence):
                (snap,) = render([
                    START, {"frame": {**frame([]), "registration": {
                        **READY_SHOWN, "approve": None, "lines": [],
                        "adoption": {**OPENED_ADOPTION, "lines": [], "note": None,
                                     "url": "https://github.com/o/r/pull/7"},
                        "line": sentence}}},
                    {"snapshot": True}])
                (result,) = registered(snap, "register-result")
                drawn = [n for n in nodes(result)[1:] if n["tag"] in ("p", "li", "a", "button")]
                self.assertEqual([(n["tag"], full(n)) for n in drawn], [("p", sentence)])
                self.assertTrue(has_class(drawn[0], "register-line"))

    def test_an_adoption_with_a_drafted_contract_draws_no_draft_rows(self) -> None:
        sentence = "The pull request of r is not ready to merge yet."
        (snap,) = render([
            START, {"frame": {**frame([]), "registration": {
                **READY_SHOWN, "approve": None, "lines": [], "draft": None, "draft_more": None,
                "adoption": {**OPENED_ADOPTION, "lines": [], "note": None,
                             "url": "https://github.com/o/r/pull/7"},
                "line": sentence}}},
            {"snapshot": True}])
        for name in ("register-draft", "draft-more", "draft-change", "draft-pick"):
            self.assertEqual(registered(snap, name), [], name)
        (result,) = registered(snap, "register-result")
        drawn = [n for n in nodes(result)[1:] if n["tag"] in ("p", "li", "a", "button")]
        self.assertEqual([(n["tag"], full(n)) for n in drawn], [("p", sentence)])

    def test_at_480_the_plan_question_cards_fit(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const box = document.getElementById('inbox');
          const edge = document.documentElement.clientWidth;
          const kids = [...box.querySelectorAll('*')].map((e) => e.getBoundingClientRect());
          return {fits: box.scrollWidth <= box.clientWidth, kids: kids.length,
                  inside: kids.every((r) => r.right <= edge)};
        }"""
        deep = "a-long-directory-name/" * 3
        long_reference = {
            **Q_REFERENCE, "subject": f"{deep}show.sh:1:5",
            "ask": f"{deep}show.sh line 1 names .claude/{deep}a.md, which this plan moves. "
                   "Should it follow the move?",
            "options": [{"value": "rewrite", "label": f"Change it to .agents/artifacts/{deep}a.md"},
                        {"value": "retain", "label": "Leave it as it is"}]}
        asking = {**view([]), "inbox": {"open": [register_item(1, long_reference), R1], "answered": []},
                  "registration": ASKING}
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})", asking)
                got = page.evaluate(measure)
            finally:
                browser.close()
        self.assertGreater(got["kids"], 10)
        self.assertTrue(got["fits"], got)
        self.assertTrue(got["inside"], got)


Q_TEXT = {"id": "contract-draft", "subject": "project-id",
          "ask": "What is the project id? It is not read from a remote.",
          "options": [], "recommended": None, "why": None}
T0 = register_item(0, Q_TEXT, text=True)
DRAFTED = {**ASKING, "questions": [Q_TEXT],
           "draft": [{"field": "default-branch", "line": "default branch: trunk (read from its remote)",
                      "value": "trunk", "options": [], "text": True, "more": False,
                      "placeholder": "the default branch"},
                     {"field": "release",
                      "line": "release profile: unsupported (the console's starting value)",
                      "value": "unsupported",
                      "options": [{"value": "unsupported", "label": "It makes no releases"}],
                      "text": True, "more": True, "placeholder": "the release profile"}],
           "draft_more": "and 1 more setting at its usual value"}
MANY = [{"field": f"f{n}", "line": f"setting {n}: value {n}", "value": f"value {n}",
         "options": [], "text": True, "more": n >= 7, "placeholder": "the value"}
        for n in range(27)]
DRAFTED_MANY = {**DRAFTED, "draft": MANY, "draft_more": "and 20 more settings at their usual values"}
B_RUNNING = {**REGISTERING, "root": "/srv/b", "name": "b", "headline": "Planning the adoption of b…",
             "line": "Planning the adoption of b…"}
B_DRAFTED = {**DRAFTED_MANY, "root": "/srv/b", "name": "b", "at": "2026-11-15T10:00:00+00:00"}
A_RUNNING = {**REGISTERING, "at": None}


class DraftedContractPageTest(unittest.TestCase):
    def test_a_text_card_shows_a_field_and_sends_the_typed_answer(self) -> None:
        empty, sent = render([
            START, {"frame": cards([T0])}, {"snapshot": True},
            {"type": {"class": "draft-text", "text": " sample-owner/sample-app "}},
            {"respond": {"status": 204, "text": ""}}, {"click": "ans-draft"},
            {"clock": 5000}, {"snapshot": True}])
        (field,) = [n for n in nodes(empty["inbox"]) if has_class(n, "draft-text")]
        self.assertEqual((field["tag"], field["label"], field["placeholder"]),
                         ("input", "Your answer", "Type your answer"))
        (send,) = [n for n in nodes(empty["inbox"]) if has_class(n, "ans-draft")]
        self.assertEqual(full(send), "Send")
        self.assertTrue(send["disabled"])
        self.assertNotIn("Send answer", full(empty["inbox"]))
        (post,) = sent["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")
        self.assertEqual(posted(post), {"plan_id": PLAN_A, "id": "contract-draft",
                                        "subject": "project-id", "value": "sample-owner/sample-app"})
        self.assertIn("Answered, planning again", full(sent["inbox"]))

    def test_enter_in_the_field_sends_and_a_refusal_keeps_the_typed_text(self) -> None:
        (snap,) = render([
            START, {"frame": cards([T0])},
            {"type": {"class": "draft-text", "text": "sample-owner/sample-app"}},
            {"respond": {"status": 409, "text": "that id is held\n"}},
            {"key": "Enter", "on": "draft-text"},
            {"clock": 5000}, {"snapshot": True}])
        self.assertEqual(len(snap["posts"]), 1)
        self.assertIn("Could not send: that id is held", full(snap["inbox"]))
        (field,) = [n for n in nodes(snap["inbox"]) if has_class(n, "draft-text")]
        self.assertEqual(field["value"], "sample-owner/sample-app")

    def test_the_typed_answer_survives_a_frame(self) -> None:
        (snap,) = render([
            START, {"frame": cards([T0])},
            {"type": {"class": "draft-text", "text": "sample-owner/sample-app"}},
            {"select": {"cls": "draft-text", "start": 2, "end": 5}},
            {"frame": cards([register_item(0, Q_TEXT, text=True)])}, {"snapshot": True}])
        self.assertEqual(snap["field"], {"cls": "draft-text", "value": "sample-owner/sample-app",
                                         "start": 2, "end": 5})

    def test_each_drafted_value_shows_with_a_change_control(self) -> None:
        (snap,) = render([START, {"frame": cards([], DRAFTED)}, {"snapshot": True}])
        shown = full(snap["register"])
        for entry in DRAFTED["draft"]:
            self.assertIn(entry["line"], shown)
        self.assertEqual([full(n) for n in registered(snap, "draft-change")], ["Change"])
        self.assertEqual([full(n) for n in registered(snap, "draft-pick")], [DRAFTED["draft"][1]["line"]])
        (drafted,) = registered(snap, "register-draft")
        self.assertEqual(len([n for n in nodes(drafted) if n["tag"] == "li"]), 1)

    def test_change_sends_the_typed_value_and_a_failure_keeps_it(self) -> None:
        opened, sent = render([
            START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"}, {"snapshot": True},
            {"respond": {"status": 409, "text": "not a branch\n"}},
            {"type": {"class": "draft-edit", "text": " main "}},
            {"click": "draft-send"}, {"snapshot": True}])
        (field,) = registered(opened, "draft-edit")
        self.assertEqual(field["value"], "trunk")
        self.assertEqual([full(n) for n in registered(opened, "draft-send")], ["Send"])
        self.assertEqual([full(n) for n in registered(opened, "draft-cancel")], ["Cancel"])
        self.assertEqual(len(registered(opened, "draft-change")), 0)
        (post,) = sent["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")
        self.assertEqual(posted(post), {"plan_id": PLAN_A, "id": "contract-draft",
                                        "subject": "default-branch", "value": "main"})
        self.assertIn("not a branch", full(sent["register"]))
        (field,) = registered(sent, "draft-edit")
        self.assertEqual(field["value"], " main ")

    def test_an_accepted_change_closes_the_entry(self) -> None:
        (snap,) = render([
            START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"},
            {"type": {"class": "draft-edit", "text": "main"}},
            {"respond": {"status": 204, "text": ""}}, {"click": "draft-send"}, {"snapshot": True}])
        self.assertEqual(len(snap["posts"]), 1)
        self.assertEqual(registered(snap, "draft-edit"), [])
        self.assertEqual(len(registered(snap, "draft-change")), 1)

    def test_a_change_the_plan_refuses_after_the_204_shows_why_and_keeps_the_value_for_retry(self) -> None:
        refused = {**DRAFTED, "questions": [], "refusal": "planning timed out, try again",
                   "refused": {"id": "contract-draft", "subject": "default-branch"}}
        opened, shown, retry = render([
            START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"},
            {"type": {"class": "draft-edit", "text": "main"}},
            {"respond": {"status": 204, "text": ""}}, {"click": "draft-send"}, {"snapshot": True},
            {"frame": cards([], refused)}, {"snapshot": True},
            {"click": "draft-change"}, {"snapshot": True}])
        self.assertEqual(registered(opened, "draft-refusal"), [])
        (line,) = registered(shown, "draft-refusal")
        self.assertEqual(full(line), "planning timed out, try again")
        self.assertEqual(len(registered(shown, "draft-change")), 1)
        (field,) = registered(retry, "draft-edit")
        self.assertEqual(field["value"], "main")
        self.assertEqual(registered(retry, "draft-refusal"), [])

    def test_change_on_an_option_entry_offers_the_option_and_the_current_value(self) -> None:
        (snap,) = render([
            START, {"frame": cards([], DRAFTED)}, {"open": "draft-more"}, {"click": "draft-pick"},
            {"snapshot": True}])
        (field,) = registered(snap, "draft-edit")
        self.assertEqual(field["value"], "unsupported")
        self.assertEqual([full(n) for n in registered(snap, "draft-option")], ["It makes no releases"])
        self.assertEqual(len(registered(snap, "draft-change")), 1)
        self.assertEqual(field["placeholder"], "the release profile")

    def test_an_option_is_sent_as_the_choice(self) -> None:
        other = {**DRAFTED, "draft": [DRAFTED["draft"][0], {**DRAFTED["draft"][1], "value": "tagged"}]}
        (snap,) = render([
            START, {"frame": cards([], other)}, {"open": "draft-more"}, {"click": "draft-pick"},
            {"click": "draft-option"}, {"respond": {"status": 204, "text": ""}},
            {"click": "draft-send"}, {"snapshot": True}])
        (post,) = snap["posts"]
        self.assertEqual(posted(post), {"plan_id": PLAN_A, "id": "contract-draft",
                                        "subject": "release", "value": "unsupported"})

    def test_the_open_entry_and_its_typed_text_survive_a_frame_and_cancel_closes_it(self) -> None:
        kept, closed = render([
            START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"},
            {"type": {"class": "draft-edit", "text": "main"}},
            {"frame": cards([], {**DRAFTED, "at": "2026-11-15T09:00:00+00:00"})}, {"snapshot": True},
            {"click": "draft-cancel"}, {"snapshot": True}])
        self.assertEqual(kept["field"], {"cls": "draft-text draft-edit", "value": "main",
                                         "start": 4, "end": 4})
        self.assertEqual(registered(closed, "draft-edit"), [])
        self.assertEqual(len(registered(closed, "draft-change")), 1)

    def test_at_480_a_draft_and_a_text_card_fit(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const edge = document.documentElement.clientWidth;
          const parts = ['inbox', 'register'].map((id) => document.getElementById(id));
          const kids = parts.flatMap((p) => [...p.querySelectorAll('*')].map((e) => e.getBoundingClientRect()));
          return {fits: parts.every((p) => p.scrollWidth <= p.clientWidth), kids: kids.length,
                  inside: kids.every((r) => r.right <= edge),
                  page: document.documentElement.scrollWidth <= edge};
        }"""
        deep = "a-long-directory-name/" * 3
        entries = [{"field": f"field-{n}", "line": f"field {n}: {deep}value-{n} (read from {deep})",
                    "value": f"{deep}value-{n}", "options": [], "text": True} for n in range(27)]
        entries[1]["options"] = [{"value": "x", "label": f"A long option {deep}"}]
        drafted = {**DRAFTED, "draft": entries}
        asking = {**view([]), "inbox": {"open": [T0], "answered": []}, "registration": drafted}
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})", asking)
                page.locator(".draft-change").nth(1).click()
                got = page.evaluate(measure)
            finally:
                browser.close()
        self.assertGreater(got["kids"], 10)
        self.assertTrue(got["fits"], got)
        self.assertTrue(got["inside"], got)
        self.assertTrue(got["page"], got)

    def test_the_work_column_shows_the_read_values_and_one_counted_line(self) -> None:
        closed, opened = render([
            START, {"frame": cards([], DRAFTED_MANY)}, {"snapshot": True},
            {"open": "draft-more"}, {"snapshot": True}])
        controls = [n for n in visible(closed["register"])
                    if has_class(n, "draft-change") or has_class(n, "draft-pick")]
        self.assertLessEqual(len(controls), 8)
        self.assertEqual(len([n for n in visible(closed["register"]) if has_class(n, "draft-change")]), 7)
        (fold,) = [n for n in nodes(closed["register"]) if n["tag"] == "details" and n["key"] == "draft-more"]
        (summary,) = [n for n in fold["children"] if n["tag"] == "summary"]
        self.assertEqual(full(summary), "and 20 more settings at their usual values")
        self.assertNotIn("setting 7: value 7", visible_text(closed["register"]))
        for entry in MANY:
            self.assertIn(entry["line"], visible_text(opened["register"]))
        self.assertEqual(len([n for n in visible(opened["register"]) if has_class(n, "draft-change")]), 7)

    def test_choosing_a_setting_in_the_fold_opens_its_change_and_the_fold_stays_open(self) -> None:
        (snap,) = render([
            START, {"frame": cards([], DRAFTED_MANY)}, {"open": "draft-more"}, {"click": "draft-pick"},
            {"frame": cards([], {**DRAFTED_MANY, "at": "2026-11-15T09:00:00+00:00"})},
            {"snapshot": True}])
        (field,) = registered(snap, "draft-edit")
        self.assertEqual(field["value"], "value 7")
        self.assertEqual(field["placeholder"], "the value")
        (fold,) = [n for n in nodes(snap["register"]) if n["tag"] == "details" and n["key"] == "draft-more"]
        self.assertTrue(fold["open"])
        self.assertIn(field, nodes(fold))

    def test_a_refused_setting_in_the_fold_opens_the_fold(self) -> None:
        refused = {**DRAFTED_MANY, "refusal": "planning timed out, try again",
                   "refused": {"id": "contract-draft", "subject": "f7"}}
        (snap,) = render([START, {"frame": cards([], refused)}, {"snapshot": True}])
        (fold,) = [n for n in nodes(snap["register"]) if n["tag"] == "details" and n["key"] == "draft-more"]
        self.assertTrue(fold["open"])
        self.assertIn("planning timed out, try again", visible_text(snap["register"]))

    def test_a_frame_without_the_counted_line_draws_every_entry_with_change(self) -> None:
        (snap,) = render([
            START, {"frame": cards([], {**DRAFTED_MANY, "draft_more": None})}, {"snapshot": True}])
        self.assertEqual(len(registered(snap, "draft-change")), 27)
        self.assertEqual(registered(snap, "draft-more"), [])

    def test_change_controls_never_wrap_under_their_row(self) -> None:
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

        row = decls(".register-draft li")
        self.assertEqual(row.get("display"), "grid")
        self.assertEqual(row.get("grid-template-columns"), "minmax(0, 1fr) auto")
        self.assertEqual(decls(".draft-change").get("white-space"), "nowrap")

    def test_at_480_and_1440_change_sits_beside_its_line(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const rect = (e) => e.getBoundingClientRect();
          const rows = [...document.querySelectorAll('#register .register-draft > li')]
            .filter((li) => li.querySelector('.draft-change'))
            .map((li) => {
              const line = li.querySelector('.draft-line');
              const change = li.querySelector('.draft-change');
              return {line: rect(line).toJSON(), change: rect(change).toJSON(),
                      height: parseFloat(getComputedStyle(line).lineHeight)};
            });
          const summary = document.querySelector('#register .draft-more > summary');
          return {rows, summary: summary === null ? null : rect(summary).bottom};
        }"""
        deep = "a-long-directory-name/" * 3
        entries = [{**entry, "line": f"setting {n}: {deep}"} if n < 7 else entry
                   for n, entry in enumerate(MANY)]
        drafted = {**DRAFTED_MANY, "draft": entries}
        asking = {**view([]), "inbox": {"open": [], "answered": []}, "registration": drafted}
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                for width in (480, 1440):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.add_init_script(fakes)
                    page.route("http://console.test/", lambda route: route.fulfill(
                        body=html, content_type="text/html"))
                    page.goto("http://console.test/")
                    page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})", asking)
                    got = page.evaluate(measure)
                    self.assertEqual(len(got["rows"]), 7, width)
                    for row in got["rows"]:
                        self.assertGreaterEqual(row["change"]["left"], row["line"]["right"] - 1, (width, row))
                        self.assertLess(row["change"]["top"], row["line"]["top"] + row["height"], (width, row))
                    if width == 1440:
                        self.assertIsNotNone(got["summary"])
                        self.assertLessEqual(got["summary"], 900)
                    page.close()
            finally:
                browser.close()

    def test_the_fold_keeps_its_open_or_closed_state_across_redraws(self) -> None:
        again = {**DRAFTED_MANY, "at": "2026-11-15T09:00:00+00:00"}
        cases = {
            "new frame": ([{"open": "draft-more"}, {"frame": cards([], again)}], True),
            "cancel": ([{"open": "draft-more"}, {"click": "draft-pick"}, {"click": "draft-cancel"}], True),
            "stays closed": ([{"frame": cards([], again)}], False),
        }
        for name, (steps, expected) in cases.items():
            with self.subTest(name):
                (snap,) = render([START, {"frame": cards([], DRAFTED_MANY)}, *steps, {"snapshot": True}])
                (fold,) = [n for n in nodes(snap["register"])
                           if n["tag"] == "details" and n["key"] == "draft-more"]
                self.assertIs(fold["open"], expected)
                self.assertEqual(registered(snap, "draft-edit"), [])

    def test_another_registration_starts_with_the_fold_closed(self) -> None:
        cases = {
            "A then B running then B": [{"frame": cards([], B_RUNNING)}, {"frame": cards([], B_DRAFTED)}],
            "A then B": [{"frame": cards([], B_DRAFTED)}],
            "A registered again": [
                {"frame": cards([], A_RUNNING)},
                {"frame": cards([], {**DRAFTED_MANY, "at": "2026-11-15T10:00:00+00:00"})}],
        }
        for name, steps in cases.items():
            with self.subTest(name):
                (snap,) = render([
                    START, {"frame": cards([], DRAFTED_MANY)}, {"open": "draft-more"}, *steps,
                    {"snapshot": True}])
                (fold,) = [n for n in nodes(snap["register"])
                           if n["tag"] == "details" and n["key"] == "draft-more"]
                self.assertIs(fold["open"], False)
                shown = visible(snap["register"])
                self.assertEqual(len([n for n in shown if has_class(n, "draft-change")]), 7)
                self.assertEqual([n for n in shown if has_class(n, "draft-pick")], [])


class RegisterCardPageTest(unittest.TestCase):
    def test_plan_questions_are_question_cards_with_numbered_options(self) -> None:
        (snap,) = render([START, {"frame": cards([R0, R1])}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        shown = full(lead)
        self.assertIn("Question", shown)
        self.assertIn("Register r", shown)
        self.assertIn(R0["headline"], shown)
        self.assertNotIn("null", shown)
        self.assertEqual([n for n in nodes(lead) if has_class(n, "proj")], [])
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")],
                         ["1Change it to .agents/artifacts/specs/a.md", "2Leave it as it is"])
        self.assertEqual(count(snap, "words-text"), 0)
        self.assertNotIn("Answer on the tracker", full(snap["inbox"]))
        self.assertEqual([n for n in nodes(snap["inbox"]) if n.get("href")], [])

    def test_number_keys_and_enter_answer_a_plan_question(self) -> None:
        first, second = render([
            START, {"frame": cards([R0, R1])}, {"snapshot": True},
            {"respond": {"status": 204, "text": ""}}, {"key": "2"}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True}])
        (strip,) = [n for n in nodes(first["inbox"]) if has_class(n, "keys")]
        self.assertIn("1\u20132 choose", full(strip))
        self.assertNotIn("Enter", full(strip))
        (post,) = second["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")
        self.assertEqual(posted(post), {"plan_id": PLAN_A, "id": "path-reference",
                                        "subject": "tools/show.sh:1:5", "value": "retain"})
        self.assertIn("Answered, planning again", full(second["inbox"]))
        self.assertNotIn(SENT_TEXT, full(second["inbox"]))

    def test_a_plan_question_has_no_preselected_option(self) -> None:
        first, second = render([START, {"frame": cards([R0])}, {"snapshot": True},
                                {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        self.assertEqual(count(first, "opt"), 2)
        self.assertEqual(picked(first), [])
        self.assertEqual(second["posts"], [])

    def test_a_plan_question_with_no_offered_answer_shows_its_next_step(self) -> None:
        (snap,) = render([START, {"frame": cards([R1])}, {"snapshot": True}])
        self.assertIn(Q_SECRET["why"], full(snap["inbox"]))
        self.assertIn("Register r", full(snap["inbox"]))
        self.assertEqual(count(snap, "opt"), 0)
        self.assertNotIn("Send answer", full(snap["inbox"]))
        self.assertNotIn("Answer on the tracker", full(snap["inbox"]))
        self.assertEqual([n for n in nodes(snap["inbox"]) if n.get("href")], [])

    def test_a_refused_plan_answer_shows_its_reason_on_the_card(self) -> None:
        text = "The plan refused that answer: no"
        (snap,) = render([START, {"frame": cards([{**R0, "refusal": text}])}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertIn(text, full(lead))
        reason = "that plan is no longer the one shown; answer the plan shown now"
        (snap,) = render([START, {"frame": cards([R0])},
                          {"respond": {"status": 409, "text": reason + "\n"}},
                          {"key": "1"}, {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        self.assertIn("Could not send: " + reason, full(snap["inbox"]))

    def test_the_work_column_holds_the_line_and_change_lines_and_no_answer_control(self) -> None:
        (snap,) = render([START, {"frame": cards([R0, R1])}, {"snapshot": True}])
        (result,) = registered(snap, "register-result")
        self.assertEqual(
            [full(n) for n in nodes(result)[1:] if n["tag"] in ("p", "li", "button")],
            [ASKING["line"], *ASKING["lines"]])
        self.assertEqual(
            sorted(n["cls"] for n in nodes(snap["register"]) if n["tag"] == "button"),
            ["register-open"])
        self.assertEqual([n for n in nodes(snap["register"]) if has_class(n, "opt")], [])

    def test_a_single_option_card_offers_the_option_as_its_action(self) -> None:
        first, second = render([START, {"frame": cards([R2])}, {"snapshot": True},
                                {"respond": {"status": 204, "text": ""}},
                                {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        (lead,) = [n for n in nodes(first["inbox"]) if has_class(n, "lead")]
        self.assertEqual(count(first, "opt"), 0)
        (send,) = [n for n in nodes(lead) if has_class(n, "send")]
        self.assertEqual(full(send), "Archive it under .agents/knowledge/archive/adopted/")
        self.assertTrue(has_class(send, "primary"))
        (strip,) = [n for n in nodes(first["inbox"]) if has_class(n, "keys")]
        self.assertIn("sends this answer", full(strip))
        self.assertEqual([full(n) for n in nodes(strip) if n["tag"] == "kbd"], ["Enter"])
        self.assertNotIn("only thing", full(first["inbox"]))
        (post,) = [p for p in second["posts"] if p["url"] == "/api/plan-answer"]
        self.assertEqual(json.loads(post["body"])["value"], "archive-history")

    def test_a_second_plan_question_row_offers_its_single_option_as_the_action(self) -> None:
        (snap,) = render([START, {"frame": cards([R0, R2])}, {"snapshot": True}])
        (row,) = rows_of(snap)
        self.assertEqual([n for n in nodes(row) if has_class(n, "opt")], [])
        (send,) = [n for n in nodes(row) if has_class(n, "send")]
        self.assertEqual(full(send), "Archive it under .agents/knowledge/archive/adopted/")
        self.assertIn("Register r", full(row))
        self.assertIn(Q_CANDIDATE["ask"], full(row))
        self.assertNotIn("null", full(row))
        self.assertEqual([n for n in nodes(row) if n.get("href")], [])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertEqual(len([n for n in nodes(lead) if has_class(n, "opt")]), 2)

    def test_a_plan_question_row_shows_its_next_step_or_refusal(self) -> None:
        (snap,) = render([START, {"frame": cards([R0, R1])}, {"snapshot": True}])
        (row,) = rows_of(snap)
        self.assertIn(Q_SECRET["why"], full(row))
        self.assertIn("Register r", full(row))
        self.assertNotIn("null", full(row))
        self.assertNotIn("Answer on the tracker", full(row))
        self.assertEqual([n for n in nodes(row) if has_class(n, "opt") or has_class(n, "send")
                          or n.get("href")], [])
        text = "The plan refused that answer: no"
        (snap,) = render([START, {"frame": cards([R1, {**R0, "refusal": text}])}, {"snapshot": True}])
        (row,) = rows_of(snap)
        self.assertEqual([full(n) for n in nodes(row) if has_class(n, "opt")],
                         ["1Change it to .agents/artifacts/specs/a.md", "2Leave it as it is"])
        self.assertIn(text, full(row))
        self.assertNotIn("null", full(row))
        self.assertEqual([n for n in nodes(row) if n.get("href")], [])


T0P = {**T0, "placeholder": "owner/name"}
T_BRANCH = register_item(3, {
    "id": "contract-draft", "subject": "default-branch",
    "ask": "Which branch is the default branch of r?\nIt has no remote, so the console cannot tell: "
           "choose a branch or type its name.",
    "options": [{"value": "trunk", "label": "trunk"}], "recommended": None, "why": None},
    text=True, placeholder="a branch name")


def keys_of(snap: dict) -> list:
    return [n for n in nodes(snap["inbox"]) if has_class(n, "keys")]


class RegisterCardKeysPageTest(unittest.TestCase):
    def test_every_card_text_field_has_a_placeholder(self) -> None:
        items = [T0P, T_BRANCH]
        self.assertEqual(len({i["key"] for i in items}), len(items))
        registers, managers, checks = render([
            START, {"frame": cards(items)}, {"snapshot": True},
            {"frame": frame([Q0, Q1])}, {"snapshot": True},
            {"frame": frame([check_item("M", "manual-check", answers=["passed", "failed", "note"])])},
            {"snapshot": True}])
        for snap in (registers, managers, checks):
            fields = [n for n in nodes(snap["inbox"]) if n["tag"] in ("input", "textarea")]
            self.assertTrue(fields)
            for field in fields:
                if not has_class(field, "confirm-text"):
                    self.assertTrue(field["placeholder"], field["cls"])
        self.assertEqual([n["placeholder"] for n in nodes(registers["inbox"]) if has_class(n, "draft-text")],
                         ["owner/name", "a branch name"])
        self.assertEqual([n["placeholder"] for n in nodes(managers["inbox"]) if has_class(n, "words-text")],
                         ["Answer in your own words"] * 2)
        self.assertEqual([n["placeholder"] for n in nodes(checks["inbox"]) if has_class(n, "note-text")],
                         ["Write a note"])
        (bare,) = [n for n in nodes(render([START, {"frame": cards([T0])}, {"snapshot": True}])[-1]["inbox"])
                   if has_class(n, "draft-text")]
        self.assertEqual(bare["placeholder"], "Type your answer")

    def test_enter_on_a_text_card_sends_the_typed_value(self) -> None:
        first, second = render([
            START, {"frame": cards([T0P])}, {"key": "Enter"}, {"snapshot": True},
            {"type": {"class": "draft-text", "text": "sample-owner/sample-app"}},
            {"blur_on": "draft-text"}, {"respond": {"status": 204, "text": ""}}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True}])
        self.assertEqual(first["posts"], [])
        self.assertEqual(first["field"]["cls"], "draft-text")
        (post,) = second["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")
        self.assertEqual(posted(post), {"plan_id": PLAN_A, "id": "contract-draft",
                                        "subject": "project-id", "value": "sample-owner/sample-app"})

    def test_exactly_one_key_hint_sits_on_the_current_card(self) -> None:
        items = [T0P, R0]
        self.assertEqual(len({i["key"] for i in items}), len(items))
        (snap,) = render([START, {"frame": cards(items)}, {"snapshot": True}])
        (strip,) = keys_of(snap)
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertIn(id(strip), {id(n) for n in nodes(lead)})
        self.assertIn("sends what you typed", full(strip))
        enters = [n for n in nodes(snap["inbox"]) if n["tag"] == "button"
                  and any(c["tag"] == "kbd" and full(c) == "Enter" for c in n["children"])]
        self.assertEqual(enters, [])
        self.assertIsNot(snap["inbox"]["children"][-1], strip)

    def test_digits_on_a_text_card_without_options_do_nothing(self) -> None:
        (snap,) = render([START, {"frame": cards([T0P])}, {"key": "1"}, {"key": "Enter"},
                          {"snapshot": True}])
        self.assertEqual(snap["posts"], [])

    def test_every_register_card_reads_title_ask_options_hint_in_order(self) -> None:
        items = [R0, T_BRANCH]
        self.assertEqual(len({i["key"] for i in items}), len(items))
        (snap,) = render([START, {"frame": cards(items)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "li" and has_class(n, "row")]
        for name, card, hint in (("lead", lead, True), ("row", row, False)):
            with self.subTest(card=name):
                order = nodes(card)

                def at(test) -> int:
                    return next(i for i, n in enumerate(order) if test(n))
                title = at(lambda n: has_class(n, "sprint-title"))
                ask = at(lambda n: has_class(n, "q") and has_class(n, "reg"))
                field = at(lambda n: has_class(n, "opt") or has_class(n, "draft-text"))
                found = [title, ask, field]
                if hint:
                    found.append(at(lambda n: has_class(n, "keys")))
                self.assertEqual(found, sorted(set(found)))
                self.assertEqual(full(order[title]), "Register r")

    def test_register_asks_are_set_small_enough_to_read_at_480(self) -> None:
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"))
        small = [d for s, d in style_rules(media_block(style, "(max-width: 480px)")) if s == ".card .q.reg"]
        self.assertTrue(small)
        self.assertLessEqual(float(small[-1]["font-size"].removesuffix("rem")), 1.0)
        top = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", style)
        self.assertEqual([d["font-size"] for s, d in style_rules(top) if s == ".card .q.reg" and "font-size" in d],
                         ["1.25rem"])
        self.assertTrue([d for s, d in style_rules(top) if s == ".rest .q.reg" and d.get("font", "").startswith("600 1rem/1.4 ")])

    def test_at_480_a_typical_ask_takes_at_most_three_lines(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const el = document.querySelector('.card.lead .q.reg');
          return el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight);
        }"""
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})", cards([T_BRANCH]))
                lines = page.evaluate(measure)
            finally:
                browser.close()
        self.assertLessEqual(round(lines), 3)

    def test_a_repeated_frame_leaves_one_key_hint(self) -> None:
        (snap,) = render([START, {"frame": frame([BRIEF])}, {"frame": frame([BRIEF])},
                          {"frame": frame([BRIEF])}, {"snapshot": True}])
        (strip,) = keys_of(snap)
        (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "brief") and has_class(n, "lead")]
        self.assertIn(id(strip), {id(n) for n in nodes(card)})
        self.assertEqual([n["text"] for n in nodes(strip) if n["tag"] == "kbd"], ["Enter"])

    def test_when_the_first_brief_waits_the_hint_moves_to_the_next_brief(self) -> None:
        (snap,) = render([START, {"frame": frame([BRIEF, BRIEF_B])}, {"key": "Enter"},
                          {"snapshot": True}])
        (strip,) = keys_of(snap)
        self.assertIn(id(strip), {id(n) for n in visible(snap["inbox"])})
        (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "details" and n["key"] == KEY_B]
        (summary,) = [c for c in row["children"] if c["tag"] == "summary"]
        self.assertIn(id(strip), {id(n) for n in nodes(summary)})
        self.assertEqual([n["text"] for n in nodes(strip) if n["tag"] == "kbd"][0], "Enter")
        self.assertIn("approve", full(strip))
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "brief") and has_class(n, "lead")]
        self.assertNotIn(id(strip), {id(n) for n in nodes(lead)})


class RegisterRetryPageTest(unittest.TestCase):
    ANSWER = [{"respond": {"status": 204, "text": ""}}, {"key": "1"}, {"key": "Enter"},
              {"clock": 5000}, {"snapshot": True}]

    def test_a_refused_registration_is_a_question_card_with_retry_and_no_work_button(self) -> None:
        (snap,) = render([START, {"frame": cards([RETRY_ITEM], REFUSED_SHOWN)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        shown = full(lead)
        for word in ("Question", "Register r", RETRY_HEADLINE, RETRY_WHY):
            self.assertIn(word, shown)
        self.assertNotIn("null", shown)
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")], ["1Retry"])
        self.assertEqual([n for n in nodes(lead) if has_class(n, "proj")], [])
        self.assertEqual(count(snap, "words-text"), 0)
        (line,) = registered(snap, "register-line")
        self.assertEqual(full(line), RETRY_HEADLINE + " " + RETRY_WHY)
        self.assertEqual(registered(snap, "register-approve"), [])
        self.assertNotIn("Retry", [full(n) for n in nodes(snap["register"])])

    def test_one_and_enter_retry_the_registration(self) -> None:
        (snap,) = render([START, {"frame": cards([RETRY_ITEM], REFUSED_SHOWN)}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/adoption-register")
        self.assertEqual(posted(post), {"plan_id": PLAN_A})
        self.assertIn("Answered, registering again", full(snap["inbox"]))
        self.assertNotIn("Answered, planning again", full(snap["inbox"]))

    def test_a_refused_retry_shows_its_reason_on_the_card(self) -> None:
        reason = "that registration is not waiting for a retry"
        (snap,) = render([
            START, {"frame": cards([RETRY_ITEM], REFUSED_SHOWN)},
            {"respond": {"status": 409, "text": reason + "\n"}}, {"key": "1"}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True}])
        self.assertIn(reason, full(snap["inbox"]))

    def test_a_fresh_retry_card_stays_answerable_after_a_late_acknowledgment(self) -> None:
        later = "2026-11-15T09:01:00+00:00"
        retry_2 = {**RETRY_ITEM, "key": f"register-retry/{PLAN_A}/{later}", "waiting_since": later}
        mid, late = render([
            START, {"frame": cards([RETRY_ITEM], REFUSED_SHOWN)}, {"hold": True},
            {"key": "1"}, {"key": "Enter"}, {"clock": 5000},
            {"frame": cards([retry_2], REFUSED_SHOWN)},
            {"release": {"status": 204, "text": ""}}, {"snapshot": True},
            {"key": "1"}, {"key": "Enter"}, {"clock": 10000}, {"snapshot": True}])
        (lead,) = [n for n in nodes(mid["inbox"]) if has_class(n, "lead")]
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")], ["1Retry"])
        self.assertNotIn("Answered, registering again", full(mid["inbox"]))
        self.assertNotIn("Sending", full(mid["inbox"]))
        self.assertEqual([p["url"] for p in late["posts"]], ["/api/adoption-register"] * 2)
        self.assertEqual([posted(p) for p in late["posts"]], [{"plan_id": PLAN_A}] * 2)

    def test_a_plan_question_still_posts_its_answer(self) -> None:
        snap = render([START, {"frame": cards([R0, RETRY_ITEM])},
                       {"respond": {"status": 204, "text": ""}}, {"key": "2"}, {"key": "Enter"},
                       {"clock": 5000}, {"snapshot": True}])[-1]
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")


class RegisterConfirmPageTest(unittest.TestCase):
    ANSWER = [{"respond": {"status": 204, "text": ""}}, {"clock": 5000}, {"snapshot": True}]

    def test_the_card_offers_register_it_and_not_now(self) -> None:
        (snap,) = render([START, {"frame": cards([CONFIRM_ITEM], WAITING_SHOWN)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")],
                         ["1Register it", "2Not now"])
        self.assertIn(CONFIRM_TEXT, full(lead))

    def test_register_it_posts_the_root_and_register(self) -> None:
        (snap,) = render([START, {"frame": cards([CONFIRM_ITEM], WAITING_SHOWN)},
                          {"key": "1"}, {"key": "Enter"}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-confirm")
        self.assertEqual(posted(post), {"root": "/srv/r", "choice": "register"})
        self.assertIn("Answered, registering", full(snap["inbox"]))

    def test_not_now_posts_the_root_and_not_now(self) -> None:
        (snap,) = render([START, {"frame": cards([CONFIRM_ITEM], WAITING_SHOWN)},
                          {"key": "2"}, {"key": "Enter"}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-confirm")
        self.assertEqual(posted(post), {"root": "/srv/r", "choice": "not_now"})
        self.assertIn("Answered, not now", full(snap["inbox"]))


class RegisterFailurePageTest(unittest.TestCase):
    ANSWER = [{"respond": {"status": 204, "text": ""}}, {"clock": 5000}, {"snapshot": True}]

    def test_a_failed_plan_is_a_question_card_with_try_again_and_not_now(self) -> None:
        (snap,) = render([START, {"frame": cards([FAILED_ITEM], FAILED_REGISTRATION)},
                          {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")],
                         ["1Try again", "2Not now"])
        self.assertEqual(full(lead).count(FAILED_HEADLINE), 1)
        self.assertEqual(full(lead).count(FAILED_WHY), 1)
        self.assertEqual(full(registered(snap, "register-line")[0]), "Register r: needs you")

    def test_try_again_posts_the_root_and_try_again(self) -> None:
        (snap,) = render([START, {"frame": cards([FAILED_ITEM], FAILED_REGISTRATION)},
                          {"key": "1"}, {"key": "Enter"}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-confirm")
        self.assertEqual(posted(post), {"root": "/srv/r", "choice": "try_again"})
        self.assertIn("Answered, trying again", full(snap["inbox"]))

    def test_not_now_posts_the_root_and_not_now(self) -> None:
        (snap,) = render([START, {"frame": cards([FAILED_ITEM], FAILED_REGISTRATION)},
                          {"key": "2"}, {"key": "Enter"}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-confirm")
        self.assertEqual(posted(post), {"root": "/srv/r", "choice": "not_now"})
        self.assertIn("Answered, not now", full(snap["inbox"]))

    def test_a_long_path_breaks_after_each_slash(self) -> None:
        line = "writes docs/areas/console/adr/a-very-long-file-name.md"
        item = {**APPLY_ITEM, "lines": [line],
                "questions": [{**APPLY_ITEM["questions"][0], "options": ["docs/x/y", "Not now"]}]}
        (snap,) = render([START, {"frame": cards([item], READY_SHOWN)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        (box,) = [n for n in nodes(lead) if has_class(n, "apply-lines")]
        (li,) = [n for n in nodes(box) if n["tag"] == "li"]
        self.assertEqual(len([n for n in nodes(li) if n["tag"] == "wbr"]), 4)
        self.assertEqual(full(li), line)
        (option,) = [n for n in nodes(lead) if has_class(n, "ot") and full(n) == "docs/x/y"]
        self.assertEqual(len([n for n in nodes(option) if n["tag"] == "wbr"]), 2)
        plain = [n for n in nodes(lead) if has_class(n, "ot") and full(n) == "Not now"]
        self.assertEqual([n for n in nodes(plain[0]) if n["tag"] == "wbr"], [])


class RegisterCancelPageTest(unittest.TestCase):
    CANCELLABLE = cards([FAILED_ITEM], {**FAILED_REGISTRATION, "cancel": True})
    REFUSED = "only a registration that was not applied yet can be cancelled"

    def test_a_cancellable_registration_offers_cancel_registration_and_posts_its_root(self) -> None:
        (snap,) = render([START, {"frame": self.CANCELLABLE},
                          {"respond": {"status": 204, "text": ""}},
                          {"click": "register-withdraw"}, {"snapshot": True}])
        (button,) = registered(snap, "register-withdraw")
        self.assertEqual(full(button), "Cancel registration")
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/register-cancel")
        self.assertEqual(posted(post), {"root": "/srv/r"})

    def test_no_cancel_without_the_offer(self) -> None:
        for registration in ({**FAILED_REGISTRATION, "cancel": False}, REGISTERING):
            with self.subTest(registration["status"], result=registration["result"]):
                (snap,) = render([START, {"frame": cards([FAILED_ITEM], registration)},
                                  {"snapshot": True}])
                self.assertEqual(registered(snap, "register-withdraw"), [])
                self.assertEqual(registered(snap, "register-close"), [])

    def test_a_second_click_while_cancelling_posts_nothing(self) -> None:
        sending, refused = render([
            START, {"frame": self.CANCELLABLE}, {"hold": True},
            {"click": "register-withdraw"}, {"click": "register-withdraw"}, {"snapshot": True},
            {"release": {"status": 409, "text": self.REFUSED + "\n"}}, {"snapshot": True}])
        self.assertEqual([p["url"] for p in sending["posts"]], ["/api/register-cancel"])
        (busy,) = registered(sending, "register-withdraw")
        self.assertTrue(busy["disabled"])
        self.assertEqual([p["url"] for p in refused["posts"]], ["/api/register-cancel"])
        (reason,) = registered(refused, "register-withdraw-reason")
        self.assertEqual(full(reason), self.REFUSED)
        (again,) = registered(refused, "register-withdraw")
        self.assertFalse(again["disabled"])

    def test_a_refused_cancel_can_be_tried_again(self) -> None:
        refused, retried = render([
            START, {"frame": self.CANCELLABLE},
            {"respond": {"status": 409, "text": self.REFUSED + "\n"}},
            {"click": "register-withdraw"}, {"snapshot": True},
            {"respond": {"status": 204, "text": ""}},
            {"click": "register-withdraw"}, {"snapshot": True}])
        self.assertEqual(full(registered(refused, "register-withdraw-reason")[0]), self.REFUSED)
        self.assertEqual([p["url"] for p in retried["posts"]],
                         ["/api/register-cancel", "/api/register-cancel"])


class PathWrapPageTest(unittest.TestCase):
    ID = "example/sample-app"
    ID_ITEM = {**ADOPTION_ITEM, "project_id": ID,
               "headline": f"The adoption of {ID} is ready to merge"}
    SOLE = "Change it to .agents/artifacts/specs/design.md"
    SOLE_ITEM = register_item(3, {**Q_REFERENCE, "options": [{"value": "rewrite", "label": SOLE}]})
    ID_FAILED = {**FAILED_ITEM, "headline": f"The adoption plan for {ID} could not start: try again."}
    PICK_LINE = "design specs are kept in .agents/artifacts/specs"
    PICK_DRAFT = {
        **DRAFTED, "draft_more": "1 more setting",
        "draft": [DRAFTED["draft"][0],
                  {"field": "specs-path", "line": PICK_LINE, "value": ".agents/artifacts/specs",
                   "options": [{"value": ".agents/artifacts/plans",
                                "label": "Keep them under .agents/artifacts/plans"},
                               {"value": "none", "label": "Not kept anywhere"}],
                   "text": True, "more": True, "placeholder": "the path"}]}

    @staticmethod
    def segs(n: dict) -> list:
        return [full(c) for c in nodes(n) if has_class(c, "seg")]

    @staticmethod
    def wbrs(n: dict) -> int:
        return len([c for c in nodes(n) if c["tag"] == "wbr"])

    def test_a_project_id_in_the_ready_card_breaks_only_at_its_slash(self) -> None:
        (snap,) = render([START, {"frame": cards([self.ID_ITEM], READY_SHOWN)}, {"snapshot": True}])
        (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "adoption")]
        (q,) = [n for n in nodes(card) if n["tag"] == "p" and has_class(n, "q")]
        self.assertEqual(self.segs(q), ["example/", "sample-app"])
        self.assertEqual(self.wbrs(q), 1)
        self.assertEqual(full(q), self.ID_ITEM["headline"])
        (meta,) = [n for n in nodes(card) if n["tag"] == "p" and has_class(n, "meta")]
        self.assertEqual(self.segs(meta), ["example/", "sample-app"])

    def test_a_sole_option_button_breaks_only_at_slashes(self) -> None:
        (snap,) = render([START, {"frame": cards([self.SOLE_ITEM], ASKING)}, {"snapshot": True}])
        (send,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "button" and has_class(n, "send")]
        self.assertEqual(self.segs(send), [".agents/", "artifacts/", "specs/", "design.md"])
        self.assertEqual(self.wbrs(send), 3)
        self.assertEqual(full(send), self.SOLE)
        # `.send` is an inline-flex row: its direct children are flex items, so the words sit in
        # one inline span (a single item) or each slash would gain the button's gap.
        (words,) = send["children"]
        self.assertEqual(words["tag"], "span")
        self.assertEqual(full(words), self.SOLE)

    def test_a_register_ask_and_title_break_only_at_slashes(self) -> None:
        (snap,) = render([START, {"frame": cards([self.ID_FAILED], FAILED_REGISTRATION)},
                          {"snapshot": True}])
        (ask,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "h2" and has_class(n, "reg")]
        self.assertEqual(self.segs(ask), ["example/", "sample-app"])
        self.assertEqual(full(ask), self.ID_FAILED["headline"])

    def test_an_expanded_draft_breaks_its_paths_only_at_slashes(self) -> None:
        shown, changing = render([
            START, {"frame": cards([], self.PICK_DRAFT)}, {"open": "draft-more"}, {"snapshot": True},
            {"click": "draft-pick"}, {"snapshot": True}])
        (pick,) = registered(shown, "draft-pick")
        self.assertEqual(self.segs(pick), [".agents/", "artifacts/", "specs"])
        self.assertEqual(self.wbrs(pick), 2)
        self.assertEqual(full(pick), self.PICK_LINE)
        self.assertEqual(pick["label"], "Change: " + self.PICK_LINE)
        options = registered(changing, "draft-option")
        self.assertEqual([full(n) for n in options],
                         ["Keep them under .agents/artifacts/plans", "Not kept anywhere"])
        self.assertEqual(self.segs(options[0]), [".agents/", "artifacts/", "plans"])
        self.assertEqual(self.segs(options[1]), [])

    def test_a_segment_is_an_atomic_inline_block(self) -> None:
        style = PAGE.read_text(encoding="utf-8")
        style = style[style.index("<style>"):style.index("</style>")]
        base = style_rules(style[:style.index("@media")])
        seg = {}
        for selector, decls in base:
            if selector == ".seg":
                seg.update(decls)
        self.assertEqual({k: seg.get(k) for k in ("display", "max-width", "overflow-wrap")},
                         {"display": "inline-block", "max-width": "100%", "overflow-wrap": "anywhere"})

    def test_every_card_ask_uses_the_full_width(self) -> None:
        style = PAGE.read_text(encoding="utf-8")
        style = style[style.index("<style>"):style.index("</style>")]
        base = style_rules(style[:style.index("@media")])
        for selector in (".card .q", ".card .q.reg", ".rest .q.reg"):
            with self.subTest(selector=selector):
                wraps = [d.get("text-wrap") for s, d in base if s == selector and "text-wrap" in d]
                self.assertNotIn("balance", wraps)
        self.assertIn("pretty", [d.get("text-wrap") for s, d in base if s == ".card .q"])

    def test_at_480_no_path_or_id_breaks_inside_a_segment(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        fakes = (
            "window.EventSource = class { constructor() { window.__src = this; this.l = {}; }"
            " addEventListener(name, fn) { this.l[name] = fn; } close() {} };"
            "window.fetch = () => Promise.resolve(new Response(null, {status: 204}));")
        measure = """() => {
          const tops = (range) => [...new Set([...range.getClientRects()].map((r) => Math.round(r.top)))];
          const lines = (node) => {
            const range = document.createRange();
            range.selectNodeContents(node);
            return tops(range).length;
          };
          const room = (node) => {
            let up = node.parentElement;
            while (up && getComputedStyle(up).display.startsWith('inline')) up = up.parentElement;
            const css = getComputedStyle(up);
            return up.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
          };
          const natural = (seg) => {
            const keep = [seg.style.maxWidth, seg.style.whiteSpace];
            seg.style.maxWidth = 'none';
            seg.style.whiteSpace = 'nowrap';
            const width = seg.getBoundingClientRect().width;
            [seg.style.maxWidth, seg.style.whiteSpace] = keep;
            return width;
          };
          const segs = [...document.querySelectorAll('.seg')].map((seg) => ({
            text: seg.textContent, lines: lines(seg), natural: natural(seg), room: room(seg)}));
          const asks = [];
          for (const q of document.querySelectorAll('#inbox .q')) {
            const range = document.createRange();
            range.selectNodeContents(q);
            const byTop = new Map();
            for (const r of range.getClientRects()) {
              const key = Math.round(r.top);
              const got = byTop.get(key) || [Infinity, -Infinity];
              byTop.set(key, [Math.min(got[0], r.left), Math.max(got[1], r.right)]);
            }
            if (byTop.size < 2) continue;
            const widest = Math.max(...[...byTop.values()].map(([a, b]) => b - a));
            asks.push({text: q.textContent, widest, width: q.clientWidth});
          }
          return {segs, asks};
        }"""
        items = [self.ID_ITEM, self.SOLE_ITEM, self.ID_FAILED]
        html = PAGE.read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", "t")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.add_init_script(fakes)
                page.route("http://console.test/", lambda route: route.fulfill(
                    body=html, content_type="text/html"))
                page.goto("http://console.test/")
                page.evaluate("(f) => window.__src.l.view({data: JSON.stringify(f)})",
                              {**view([]), **cards(items, self.PICK_DRAFT)})
                page.evaluate("() => { document.querySelector('#register .draft-more').open = true; }")
                got = page.evaluate(measure)
            finally:
                browser.close()
        found = {s["text"] for s in got["segs"]}
        for text in ("example/", "sample-app", ".agents/", "artifacts/", "specs"):
            self.assertIn(text, found)
        oversized = [s for s in got["segs"] if s["natural"] > s["room"]]
        self.assertEqual(oversized, [])
        for seg in got["segs"]:
            self.assertEqual(seg["lines"], 1, seg)
        for ask in got["asks"]:
            self.assertGreaterEqual(ask["widest"], 0.85 * ask["width"], ask)


TRUST_ITEM = {
    "type": "inbox_item", "reason": "trust_failed",
    "key": "trust/work//srv/r/2026-11-15T10:00:00+00:00",
    "project_id": None, "root": "/srv/r", "name": "r", "profile": "work", "title": "Trust r",
    "plan_id": None, "id": None, "subject": None,
    "headline": "Agents cannot start in r under work yet",
    "why": "Run this in a terminal: cd /srv/r && CLAUDE_ACCOUNT=work claude, then accept the prompt and type /exit.",
    "command": "cd /srv/r && CLAUDE_ACCOUNT=work claude", "lines": [], "refusal": None,
    "more_questions": 0, "text": False,
    "questions": [{"question": "Agents cannot start in r under work yet",
                   "options": ["Check again"], "chosen": None, "recommended": None,
                   "recommended_index": None}],
    "values": ["check"], "items": [], "answers": [], "answered": False,
    "waiting_since": "2026-11-15T10:00:00+00:00"}


class TrustCheckPageTest(unittest.TestCase):
    def test_the_card_shows_the_command_and_check_again_posts_the_pair(self) -> None:
        (snap,) = render([START, {"frame": cards([TRUST_ITEM])}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertIn(TRUST_ITEM["why"], full(lead))
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")], ["1Check again"])
        (snap,) = render([START, {"frame": cards([TRUST_ITEM])},
                          {"respond": {"status": 204, "text": ""}}, {"key": "1"},
                          {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/trust-check")
        self.assertEqual(posted(post), {"root": "/srv/r", "profile": "work"})
        self.assertIn("Answered, checking", full(snap["inbox"]))


class RegisterApplyPageTest(unittest.TestCase):
    ANSWER = [{"respond": {"status": 204, "text": ""}}, {"key": "1"}, {"key": "Enter"},
              {"clock": 5000}, {"snapshot": True}]

    def test_a_ready_plan_is_a_question_card_with_apply_it_and_not_now(self) -> None:
        (snap,) = render([START, {"frame": cards([APPLY_ITEM], READY_SHOWN)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        shown = full(lead)
        for word in ("Question", "Register r", "Apply this adoption?", *READY_SHOWN["lines"]):
            self.assertIn(word, shown)
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")],
                         ["1Apply it", "2Not now"])
        (box,) = [n for n in nodes(lead) if has_class(n, "apply-lines")]
        self.assertEqual([full(n) for n in nodes(box) if n["tag"] == "li"], READY_SHOWN["lines"])
        self.assertEqual([n for n in nodes(lead) if has_class(n, "proj")], [])
        self.assertNotIn("null", shown)

    def test_one_and_enter_apply_the_plan(self) -> None:
        (snap,) = render([START, {"frame": cards([APPLY_ITEM], READY_SHOWN)}, *self.ANSWER])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/plan-approve")
        self.assertEqual(posted(post), {"plan_id": PLAN_A})
        self.assertIn("Answered, applying", full(snap["inbox"]))

    def test_two_and_enter_set_the_card_aside(self) -> None:
        (snap,) = render([START, {"frame": cards([APPLY_ITEM], READY_SHOWN)},
                          {"respond": {"status": 204, "text": ""}}, {"key": "2"},
                          {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/plan-defer")
        self.assertEqual(posted(post), {"plan_id": PLAN_A})

    def test_turn_signed_commits_off_posts_the_draft_change(self) -> None:
        item = {**APPLY_ITEM, "questions": [{**APPLY_ITEM["questions"][0], "options": [
            "Apply it again", "Turn signed commits off", "Not now"]}],
            "values": ["apply", "signing_off", "not_now"]}
        (snap,) = render([START, {"frame": cards([item], READY_SHOWN)},
                          {"respond": {"status": 204, "text": ""}}, {"key": "2"},
                          {"key": "Enter"}, {"clock": 5000}, {"snapshot": True}])
        (post,) = snap["posts"]
        self.assertEqual(post["url"], "/api/plan-answer")
        self.assertEqual(posted(post), {"plan_id": item["plan_id"], "id": "contract-draft",
                                        "subject": "commit-signed", "value": "no"})
        self.assertIn("Answered, turning signed commits off", full(snap["inbox"]))

    def test_a_failed_step_card_offers_try_again(self) -> None:
        (snap,) = render([START, {"frame": cards([TRY_ITEM], FAILED_SHOWN)}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        self.assertEqual([full(n) for n in nodes(lead) if has_class(n, "opt")],
                         ["1Try again", "2Not now"])
        self.assertIn(PUSH_FAILED_ADOPTION["note"], full(lead))
        (answered,) = render([START, {"frame": cards([TRY_ITEM], FAILED_SHOWN)}, *self.ANSWER])
        (post,) = answered["posts"]
        self.assertEqual(post["url"], "/api/plan-approve")
        self.assertEqual(posted(post), {"plan_id": PLAN_A})
        self.assertIn("Answered, trying again", full(answered["inbox"]))

    def test_the_work_column_has_no_approve_or_try_again_control(self) -> None:
        for shown in (READY_SHOWN, {**READY_SHOWN, "approve": "approve"}, FAILED_SHOWN):
            (snap,) = render([START, {"frame": cards([], shown)}, {"snapshot": True}])
            self.assertEqual(registered(snap, "register-approve"), [])
            labels = {full(n) for n in nodes(snap["register"]) if n["tag"] == "button"}
            self.assertEqual(labels & {"Approve", "Try again", "Apply it", "Apply it again"}, set())
            if shown is FAILED_SHOWN:
                self.assertEqual(registered(snap, "register-note"), [])
                (line,) = registered(snap, "register-line")
                self.assertEqual(full(line), FAILED_SHOWN["line"])

    def test_a_refused_apply_shows_its_reason_on_the_card(self) -> None:
        reason = "only a ready plan can be approved"
        (snap,) = render([
            START, {"frame": cards([APPLY_ITEM], READY_SHOWN)},
            {"respond": {"status": 409, "text": reason + "\n"}}, {"key": "1"}, {"key": "Enter"},
            {"clock": 5000}, {"snapshot": True}])
        self.assertIn("Could not send: " + reason, full(snap["inbox"]))


class RegisterAnswerTransitionTest(unittest.TestCase):
    def test_a_second_question_of_the_plan_cannot_be_answered_while_one_is_outstanding(self) -> None:
        (snap,) = render([
            START, {"frame": cards([R0, R2])}, {"key": "1"}, {"key": "Enter"},
            {"key": "1"}, {"key": "Enter"}, {"clock": 20000}, {"snapshot": True}])
        (post,) = snap["posts"]
        self.assertEqual(posted(post)["id"], "path-reference")
        (row,) = rows_of(snap)
        (send,) = [n for n in nodes(row) if has_class(n, "send")]
        self.assertTrue(send["disabled"])

    def test_a_refusal_frame_supersedes_the_late_acknowledgment_of_a_held_answer(self) -> None:
        text = "The plan refused that answer: no"
        refused = {**ASKING, "refusal": text, "refused": {"id": Q_REFERENCE["id"], "subject": Q_REFERENCE["subject"]}}
        running = {**REGISTERING, "plan_id": None}
        (snap,) = render([
            START, {"frame": cards([R0])}, {"hold": True}, {"key": "1"}, {"key": "Enter"},
            {"clock": 5000}, {"frame": cards([], running)},
            {"frame": cards([{**R0, "refusal": text}], refused)},
            {"release": {"status": 204, "text": ""}}, {"snapshot": True}])
        shown = full(snap["inbox"])
        self.assertNotIn("Answered, planning again", shown)
        self.assertIn(text, shown)
        options = [n for n in nodes(snap["inbox"]) if has_class(n, "opt")]
        self.assertEqual(len(options), 2)
        self.assertFalse(any(n["disabled"] for n in options))
