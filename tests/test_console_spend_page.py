"""The Spend page's static invariants and render (#1135)."""

import copy
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_page import media_block, style_rules

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEND = REPO_ROOT / "python/agent_tools/console/spend.html"
DESK = REPO_ROOT / "python/agent_tools/console/page.html"
PYPROJECT = REPO_ROOT / "python/pyproject.toml"
SERVICE = REPO_ROOT / "python/agent_tools/console/service.py"
ADR_DIR = REPO_ROOT / "docs/areas/console/adr"


HARNESS = r"""
const REQUESTS = [];
class Node {
  constructor(tag) {
    this.tagName = tag; this.className = ""; this.title = ""; this.dataset = {};
    this.style = {}; this.attrs = {}; this.listeners = {}; this.children = [];
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...nodes) { this.children = nodes; }
  submit() { REQUESTS.push(["submit", this.tagName]); }
  set textContent(text) { this.children = [{text: String(text)}]; }
  get textContent() {
    return this.children.map((c) => c.text !== undefined ? c.text : c.textContent).join("");
  }
}
const ELEMENTS = {};
const document = {
  createElement: (tag) => new Node(tag),
  getElementById(id) {
    if (!(id in ELEMENTS)) ELEMENTS[id] = new Node("div");
    return ELEMENTS[id];
  },
};
const kept = {};
class EventSource {
  constructor(url) { REQUESTS.push(["EventSource", url]); }
  addEventListener(name, fn) { kept[name] = fn; }
}
const fetch = (url) => { REQUESTS.push(["fetch", String(url)]); return Promise.resolve({}); };
class XMLHttpRequest {
  open(method, url) { REQUESTS.push(["XMLHttpRequest", method, String(url)]); }
  send() {}
}
class WebSocket { constructor(url) { REQUESTS.push(["WebSocket", String(url)]); } }
const navigator = {sendBeacon(url) { REQUESTS.push(["sendBeacon", String(url)]); return true; }};
function setTimeout() { return 0; }
function clearTimeout() {}
const location = {hash: (JSON.parse(process.argv[2])[0] || {}).start_hash || ""};
const WINDOW_LISTENERS = {};
const window = {
  location,
  addEventListener(name, fn) { (WINDOW_LISTENERS[name] = WINDOW_LISTENERS[name] || []).push(fn); },
};
"""
DRIVER = r"""
const tree = (n) => ({
  tag: n.tagName, cls: n.className, text: n.textContent, title: n.title,
  attrs: {...n.attrs, ...Object.fromEntries(
    Object.entries(n.dataset).map(([k, v]) => ["data-" + k, String(v)]))},
  style: {...n.style},
  children: n.children.filter((c) => c.tagName !== undefined).map(tree),
});
const snapshots = [];
for (const step of JSON.parse(process.argv[2])) {
  if (Object.keys(step).length === 1 && "start_hash" in step) {
    continue;
  } else if ("hash" in step) {
    location.hash = step.hash;
    for (const fn of WINDOW_LISTENERS.hashchange || []) fn({});
  } else if ("frame" in step) {
    kept.view({data: JSON.stringify(step.frame)});
  } else if ("click" in step) {
    const buttons = ELEMENTS.spans.children.filter(
      (c) => c.tagName === "button" && c.textContent === step.click);
    if (buttons.length !== 1) throw new Error("no button " + step.click);
    for (const fn of buttons[0].listeners.click || []) fn({});
  } else if (step.snapshot) {
    const out = {};
    for (const id of ["spans", "note", "item", "summary", "trend", "breakdowns"]) {
      out[id] = tree(document.getElementById(id));
    }
    snapshots.push(out);
  }
}
console.log(JSON.stringify({snapshots, requests: REQUESTS}));
"""


def render_spend(steps: list) -> dict:
    """Run the Spend page's script under node (TZ=UTC) through `steps`; the snapshots and requests."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the Spend page render tests need it")
    html = SPEND.read_text(encoding="utf-8")
    script = re.search(r"(?s)<script>(.*?)</script>", html).group(1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.js"
        path.write_text(
            HARNESS + "(function () {\n" + script + "\n})();\n" + DRIVER, encoding="utf-8")
        done = subprocess.run(
            [node, str(path), json.dumps(steps)],
            capture_output=True, text=True, timeout=30, check=False,
            env={**os.environ, "TZ": "UTC"})
    if done.returncode != 0:
        raise AssertionError(f"the Spend page failed under node: {done.stderr}")
    return json.loads(done.stdout)


def tokens(dollars: float, scale: float = 1.0, base: dict | None = None,
           approximate: bool = False) -> dict:
    base = base or {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    return {
        "input": int(base["input"] * scale), "cache_write": int(base["cache_write"] * scale),
        "cache_read": int(base["cache_read"] * scale), "output": int(base["output"] * scale),
        "dollars": dollars, "approximate": approximate}


SHARES = {
    "project": [("owner/api", .1, .7), ("unattributed", .3, .1), ("owner/web", .6, .2)],
    "sprint": [("aaaaaaaaaaaaaaaa", .1, .1), ("fedcba9876543210", .2, .2),
               ("0123456789abcdef", .5, .5)],
    "phase": [("plan", .3, .3), ("implement", .3, .3), ("other", .4, .4)],
    "account": [("unattributed", .3, .3), ("work-main", .7, .7)],
    "aspect": [("keepalive", .05, .05), ("questions", .07, .07), ("outside_sprint", .08, .08),
               ("managers", .3, .3), ("deliveries", .5, .5)],
}
FIRST_DAY = date(2026, 10, 18)


def split_phases(item: dict, shares: list[tuple[str, float | None]]) -> dict:
    """Split one wire entry into phases that sum exactly to it; the last phase takes the remainder."""
    fields = ("input", "cache_write", "cache_read", "output")
    phases: dict = {}
    left = {**{f: item[f] for f in fields}, "dollars": item["dollars"]}
    for name, share in shares[:-1]:
        phase = {f: int(item[f] * share) for f in fields}
        phase["dollars"] = item["dollars"] * share
        for key in left:
            left[key] -= phase[key]
        phases[name] = {**phase, "approximate": item["approximate"]}
    phases[shares[-1][0]] = {**left, "approximate": item["approximate"]}
    return phases


def spend_view_fixture() -> dict:
    """A desk view with the production entry shapes and 30 spend days (7 with breakdowns)."""
    quiet = [{"type": "project", "project_id": "owner/api", "sprints": [],
              "finished_sprints": {"label": "Finished sprints", "count": 1, "sprints": [
                  {"sprint_id": "fedcba9876543210", "title": "Trim the upload queue"}]}}]
    quiet += [{"type": "project", "project_id": f"owner/q{n}", "sprints": [],
               "finished_sprints": None} for n in (1, 2, 3)]
    entries = [
        {"type": "project", "project_id": "owner/web",
         "sprints": [{"sprint_id": "0123456789abcdef", "title": "Add resumable uploads"}],
         "finished_sprints": None},
        {"type": "quiet_group", "label": "4 quiet projects", "count": 4, "projects": quiet},
    ]
    days = []
    for i in range(30):
        base = {"input": 1000 * (i + 1), "cache_write": 10,
                "cache_read": 45_600_000 if i == 29 else 0, "output": 512}
        approx = i == 25
        day = {"day": (FIRST_DAY + timedelta(days=i)).isoformat(),
               "total": tokens(float(i + 1), 1.0, base, approx)}
        for dimension, keys in SHARES.items():
            day[dimension] = {}
            if i < 23:
                continue
            for key, share, today_share in keys:
                share = today_share if i == 29 else share
                day[dimension][key] = tokens(share * (i + 1), share, base, approx)
        day["run"], day["sprint_phase"], day["run_phase"] = {}, {}, {}
        if i >= 23:
            day["run"] = {"wf_1": tokens(.3 * (i + 1), .3, base, approx)}
            day["sprint_phase"] = {"0123456789abcdef": split_phases(
                day["sprint"]["0123456789abcdef"],
                [("implement", .64), ("manager", .24), ("plan", None)])}
            day["run_phase"] = {"wf_1": split_phases(
                day["run"]["wf_1"], [("implement", .7), ("plan", None)])}
        days.append(day)
    return {"entries": entries, "spend": {"approximate": True, "days": days}}


def walk(tree: dict):
    yield tree
    for child in tree["children"]:
        yield from walk(child)


def find(tree: dict, tag: str, cls: str) -> list:
    return [n for n in walk(tree) if n["tag"] == tag and n["cls"] == cls]


def dollars_of(text: str) -> float:
    return float(text.removeprefix("~$").replace(",", ""))


def pressed(snapshot: dict) -> list:
    return [b["text"] for b in snapshot["spans"]["children"]
            if b["attrs"].get("aria-pressed") == "true"]


def rows_of(snapshot: dict, heading: str) -> list:
    (section,) = [s for s in find(snapshot["breakdowns"], "section", "breakdown")
                  if s["children"][0]["text"] == heading]
    return find(section, "li", "row")


def row_names(snapshot: dict, heading: str) -> list:
    return [find(r, "span", "row-name")[0]["text"] for r in rows_of(snapshot, heading)]


def summed(view: dict, dimension: str, key: str, span: int) -> float:
    total = 0.0
    for day in view["spend"]["days"][-span:]:
        total += day[dimension].get(key, {"dollars": 0.0})["dollars"]
    return total


class SpendRenderTest(unittest.TestCase):
    def test_the_default_span_is_seven_days_with_today_beside_it(self) -> None:
        fx = spend_view_fixture()
        (snap,) = render_spend([{"frame": fx}, {"snapshot": True}])["snapshots"]
        self.assertEqual(pressed(snap), ["7 days"])
        buttons = snap["spans"]["children"]
        self.assertEqual([b["text"] for b in buttons], ["Today", "7 days", "30 days"])
        self.assertEqual([b["attrs"]["data-span"] for b in buttons], ["1", "7", "30"])
        self.assertEqual({b["attrs"]["type"] for b in buttons}, {"button"})
        self.assertEqual({b["tag"] for b in buttons}, {"button"})
        self.assertEqual({b["cls"] for b in buttons}, {"span btn-quiet"})
        figures = find(snap["summary"], "div", "figure")
        self.assertEqual(
            [find(f, "span", "figure-label")[0]["text"] for f in figures],
            ["Today", "Last 7 days"])
        week = sum(d["total"]["dollars"] for d in fx["spend"]["days"][-7:])
        self.assertEqual(week, sum(range(24, 31)))
        self.assertEqual(
            [find(f, "span", "usd")[0]["text"] for f in figures],
            ["~$30.00", "~$" + f"{week:,.2f}"])
        self.assertEqual(
            find(figures[0], "p", "tokens")[0]["text"],
            "input 30k · cache writes 10 · cache reads 45.6M · output 512")
        self.assertEqual(find(figures[0], "span", "approx"), [])
        self.assertEqual(
            [n["text"] for n in find(figures[1], "span", "approx")], ["approximate"])
        self.assertTrue(snap["note"]["text"].endswith("priced like its family."))

    def test_each_span_draws_one_trend_point_per_day(self) -> None:
        fx = spend_view_fixture()
        shots = render_spend([
            {"frame": fx}, {"snapshot": True}, {"click": "Today"}, {"snapshot": True},
            {"click": "30 days"}, {"snapshot": True}])["snapshots"]
        week, today, month = shots
        points = [find(s["trend"], "li", "trend-day") for s in shots]
        self.assertEqual([len(p) for p in points], [7, 1, 30])
        days = fx["spend"]["days"]
        labels = lambda lis: [find(li, "span", "trend-label")[0]["text"] for li in lis]
        self.assertEqual(
            labels(points[0]),
            [(date(2026, 11, 10) + timedelta(days=n)).strftime("%a %-d %b")
             for n in range(6)] + ["Today"])
        self.assertEqual(labels(points[1]), ["Today"])
        month_labels = labels(points[2])
        self.assertEqual([t for t in month_labels if t], ["Sun 18 Oct", "Today"])
        self.assertEqual(month_labels[0], "Sun 18 Oct")
        self.assertEqual(month_labels[-1], "Today")
        self.assertTrue(all(li["title"] for li in points[2]))
        for lis, span in zip(points, (7, 1, 30)):
            chosen = days[-span:]
            top = max(d["total"]["dollars"] for d in chosen)
            for li, day in zip(lis, chosen):
                (bar,) = find(li, "span", "trend-bar")
                (fill,) = bar["children"]
                self.assertEqual(fill["tag"], "i")
                self.assertEqual(
                    fill["style"]["height"],
                    f"{math.floor(day['total']['dollars'] / top * 100 + 0.5)}%")
        for li in points[0]:
            self.assertEqual(
                li["title"].endswith(", approximate"),
                li["title"].startswith("Thu 12 Nov"))
        self.assertEqual(len(find(today["summary"], "div", "figure")), 1)
        self.assertEqual(len(find(month["summary"], "div", "figure")), 2)
        self.assertEqual(
            find(find(month["summary"], "div", "figure")[1], "span", "figure-label")[0]["text"],
            "Last 30 days")

    def test_a_new_frame_keeps_the_chosen_span(self) -> None:
        fx = spend_view_fixture()
        (snap,) = render_spend([
            {"frame": fx}, {"click": "30 days"}, {"frame": fx}, {"snapshot": True}])["snapshots"]
        self.assertEqual(pressed(snap), ["30 days"])
        self.assertEqual(len(find(snap["trend"], "li", "trend-day")), 30)

    def test_breakdowns_sort_by_estimated_dollars_with_unattributed_its_own_row(self) -> None:
        fx = spend_view_fixture()
        week, today = render_spend([
            {"frame": fx}, {"snapshot": True}, {"click": "Today"}, {"snapshot": True}])["snapshots"]
        headings = ["By project", "By sprint", "By phase", "By account", "By aspect"]
        for snap in (week, today):
            sections = find(snap["breakdowns"], "section", "breakdown")
            self.assertEqual([s["children"][0]["text"] for s in sections], headings)
            self.assertEqual([s["children"][0]["tag"] for s in sections], ["h2"] * 5)
            for heading in headings:
                values = [dollars_of(find(r, "span", "usd")[0]["text"])
                          for r in rows_of(snap, heading)]
                self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(row_names(week, "By project"), ["owner/web", "unattributed", "owner/api"])
        self.assertEqual(
            row_names(week, "By sprint"),
            ["Add resumable uploads", "Trim the upload queue", "sprint aaaaaaaa"])
        self.assertEqual(row_names(week, "By phase"), ["other", "implement", "plan"])
        self.assertEqual(row_names(week, "By account"), ["work-main", "unattributed"])
        self.assertEqual(
            row_names(week, "By aspect"),
            ["Deliveries", "Managers", "Outside-sprint sessions", "Questions", "Keepalive pings"])
        self.assertEqual(
            row_names(today, "By project"), ["owner/api", "owner/web", "unattributed"])
        for snap, span in ((week, 7), (today, 1)):
            rows = rows_of(snap, "By project")
            (row,) = [r for r in rows if find(r, "span", "row-name")[0]["text"] == "unattributed"]
            self.assertEqual(
                find(row, "span", "usd")[0]["text"],
                "~$" + f"{summed(fx, 'project', 'unattributed', span):,.2f}")
            self.assertEqual(len(find(row, "span", "tokens")), 1)
        bare = copy.deepcopy(fx)
        for day in bare["spend"]["days"]:
            day["account"] = {}
        (snap,) = render_spend([{"frame": bare}, {"snapshot": True}])["snapshots"]
        (section,) = [s for s in find(snap["breakdowns"], "section", "breakdown")
                      if s["children"][0]["text"] == "By account"]
        self.assertEqual(
            [(n["tag"], n["text"]) for n in find(section, "p", "empty")],
            [("p", "Nothing in this span.")])
        self.assertEqual(find(section, "li", "row"), [])

    def test_every_dollar_figure_is_labelled_an_estimate(self) -> None:
        fx = spend_view_fixture()
        shots = render_spend([
            {"frame": fx}, {"snapshot": True}, {"click": "Today"}, {"snapshot": True},
            {"click": "30 days"}, {"snapshot": True}])["snapshots"]
        seen = 0
        for snap in shots:
            self.assertTrue(snap["note"]["text"].startswith(
                "Dollar figures (~) are estimates at API list prices."))
            for tree in snap.values():
                for node in walk(tree):
                    if "$" in node["text"] and not any("$" in c["text"] for c in node["children"]):
                        seen += 1
                        self.assertEqual((node["tag"], node["cls"]), ("span", "usd"))
                        self.assertRegex(node["text"], r"^~\$\d{1,3}(,\d{3})*\.\d{2}$")
                        self.assertEqual(node["title"], "Estimated at API list prices")
            for li in find(snap["trend"], "li", "trend-day"):
                self.assertRegex(li["title"], r": ~\$")
        self.assertGreater(seen, 0)
        big = copy.deepcopy(fx)
        big["spend"]["days"][-1]["total"]["dollars"] = 1234.5
        (snap,) = render_spend([{"frame": big}, {"snapshot": True}])["snapshots"]
        (today,) = find(snap["summary"], "div", "figure")[:1]
        self.assertEqual(find(today, "span", "usd")[0]["text"], "~$1,234.50")

    def test_no_spend_yet_reads_a_sentence(self) -> None:
        fx = spend_view_fixture()
        fx["spend"] = None
        (snap,) = render_spend([{"frame": fx}, {"snapshot": True}])["snapshots"]
        self.assertEqual(
            snap["summary"]["text"], "Spend shows once the console has read the transcripts.")
        self.assertEqual(snap["trend"]["children"], [])
        self.assertEqual(snap["breakdowns"]["children"], [])
        self.assertEqual(snap["note"]["text"], "")

    def test_no_raw_date_is_shown(self) -> None:
        fx = spend_view_fixture()
        shots = render_spend([
            {"frame": fx}, {"snapshot": True}, {"click": "Today"}, {"snapshot": True},
            {"click": "30 days"}, {"snapshot": True}])["snapshots"]
        self.assertTrue(find(shots[0]["trend"], "li", "trend-day"))
        for snap in shots:
            for tree in snap.values():
                for node in walk(tree):
                    self.assertNotRegex(node["text"], r"\d{4}-\d{2}-\d{2}")
                    self.assertNotRegex(node["title"], r"\d{4}-\d{2}-\d{2}")

    def test_the_spend_page_sends_no_write_request(self) -> None:
        fx = spend_view_fixture()
        quiet = dict(fx, spend=None)
        result = render_spend([
            {"frame": fx}, {"click": "Today"}, {"click": "30 days"}, {"click": "7 days"},
            {"frame": quiet}, {"frame": fx}, {"snapshot": True}])
        self.assertEqual(result["requests"], [["EventSource", "/api/stream"]])


class SpendItemTest(unittest.TestCase):
    """A fragment opens one sprint or run with its phase breakdown (#1136)."""

    @staticmethod
    def item_rows(item: dict) -> list:
        return [(find(r, "span", "row-name")[0]["text"], find(r, "span", "usd")[0]["text"],
                 find(r, "span", "tokens")[0]["text"]) for r in find(item, "li", "row")]

    @staticmethod
    def item_figure(item: dict) -> dict:
        (figure,) = find(item, "div", "figure")
        return figure

    def test_a_sprint_fragment_shows_its_total_and_phase_breakdown(self) -> None:
        fx = spend_view_fixture()
        first, second = render_spend([
            {"start_hash": "#sprint=0123456789abcdef"}, {"frame": fx}, {"snapshot": True},
            {"click": "Today"}, {"snapshot": True}])["snapshots"]
        item = first["item"]
        self.assertEqual(find(item, "h2", "")[0]["text"], "Add resumable uploads")
        figure = self.item_figure(item)
        self.assertEqual(find(figure, "span", "figure-label")[0]["text"], "So far, last 30 days")
        self.assertEqual(find(figure, "span", "usd")[0]["text"], "~$94.50")
        self.assertEqual([n["text"] for n in find(figure, "span", "approx")], ["approximate"])
        self.assertEqual(
            find(figure, "p", "tokens")[0]["text"],
            "input 94.5k · cache writes 35 · cache reads 22.8M · output 1.8k")
        self.assertEqual(self.item_rows(item), [
            ("implement", "~$60.48", "input 60.5k · cache writes 21 · cache reads 14.6M · output 1.1k"),
            ("Manager", "~$22.68", "input 22.7k · cache writes 7 · cache reads 5.5M · output 427"),
            ("plan", "~$11.34", "input 11.3k · cache writes 7 · cache reads 2.7M · output 224"),
        ])
        self.assertEqual(second["item"], item)

    def test_a_run_fragment_names_the_run_and_its_phases(self) -> None:
        (snap,) = render_spend([
            {"start_hash": "#run=wf_1"}, {"frame": spend_view_fixture()},
            {"snapshot": True}])["snapshots"]
        item = snap["item"]
        self.assertEqual(find(item, "h2", "")[0]["text"], "Run wf_1")
        figure = self.item_figure(item)
        self.assertEqual(find(figure, "span", "usd")[0]["text"], "~$56.70")
        self.assertEqual(
            find(figure, "p", "tokens")[0]["text"],
            "input 56.7k · cache writes 21 · cache reads 13.7M · output 1.1k")
        self.assertEqual(self.item_rows(item), [
            ("implement", "~$39.69", "input 39.7k · cache writes 14 · cache reads 9.6M · output 749"),
            ("plan", "~$17.01", "input 17k · cache writes 7 · cache reads 4.1M · output 322"),
        ])

    def test_the_item_total_sums_its_own_entries_not_its_rounded_phases(self) -> None:
        fx = spend_view_fixture()
        sprint_id = "0123456789abcdef"
        for day in fx["spend"]["days"]:
            day["sprint"] = {sprint_id: {
                "input": 4, "cache_write": 0, "cache_read": 0, "output": 0,
                "dollars": 0.0002, "approximate": False}}
            day["sprint_phase"] = {sprint_id: {
                p: {"input": 1, "cache_write": 0, "cache_read": 0, "output": 0,
                    "dollars": 0.0, "approximate": False}
                for p in ("plan", "implement", "task review", "manager")}}
        (snap,) = render_spend([
            {"start_hash": "#sprint=" + sprint_id}, {"frame": fx}, {"snapshot": True}])["snapshots"]
        figure = self.item_figure(snap["item"])
        self.assertEqual(find(figure, "span", "usd")[0]["text"], "~$0.01")
        self.assertEqual(
            find(figure, "p", "tokens")[0]["text"],
            "input 120 · cache writes 0 · cache reads 0 · output 0")
        rows = self.item_rows(snap["item"])
        self.assertEqual(len(rows), 4)
        self.assertEqual({usd for _, usd, _ in rows}, {"~$0.00"})

    def test_a_hash_change_redraws_the_item(self) -> None:
        shots = render_spend([
            {"frame": spend_view_fixture()}, {"snapshot": True}, {"hash": "#run=wf_1"},
            {"snapshot": True}, {"hash": ""}, {"snapshot": True}])["snapshots"]
        before, during, after = (s["item"] for s in shots)
        self.assertEqual(before["children"], [])
        self.assertEqual(find(during, "h2", "")[0]["text"], "Run wf_1")
        self.assertEqual(after["children"], [])

    def test_an_item_without_spend_reads_a_sentence(self) -> None:
        (snap,) = render_spend([
            {"start_hash": "#sprint=ffffffffffffffff"}, {"frame": spend_view_fixture()},
            {"snapshot": True}])["snapshots"]
        item = snap["item"]
        self.assertEqual(find(item, "h2", "")[0]["text"], "sprint ffffffff")
        self.assertEqual(
            [n["text"] for n in find(item, "p", "empty")],
            ["Nothing for this sprint in the last 30 days."])
        self.assertEqual(find(item, "div", "figure"), [])
        self.assertEqual(find(item, "ol", "rows"), [])

    def test_an_item_named_like_an_inherited_member_reads_a_sentence(self) -> None:
        for kind in ("sprint", "run"):
            for name in ("constructor", "__proto__", "toString"):
                with self.subTest(kind=kind, name=name):
                    (snap,) = render_spend([
                        {"start_hash": "#" + kind + "=" + name}, {"frame": spend_view_fixture()},
                        {"snapshot": True}])["snapshots"]
                    item = snap["item"]
                    self.assertEqual(
                        [n["text"] for n in find(item, "p", "empty")],
                        ["Nothing for this " + kind + " in the last 30 days."])
                    self.assertEqual(find(item, "div", "figure"), [])
                    self.assertEqual(find(item, "ol", "rows"), [])

    def test_a_fragment_of_another_form_opens_nothing(self) -> None:
        for fragment in ("#sprint=%E0%A4%A", "#project=owner/web", "#sprint="):
            with self.subTest(fragment=fragment):
                (snap,) = render_spend([
                    {"start_hash": fragment}, {"frame": spend_view_fixture()},
                    {"snapshot": True}])["snapshots"]
                self.assertEqual(snap["item"]["children"], [])


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


    def test_the_spend_page_uses_no_peach_and_only_the_desk_palette(self) -> None:
        self.assertNotIn("peach", self.text.lower())
        self.assertNotIn("#f5a97f", self.text.lower())

        def root_of(text: str) -> dict:
            (block,) = re.findall(r"(?s):root\s*\{(.*?)\}", text)
            pairs = (decl.partition(":") for decl in block.split(";"))
            return {n.strip(): v.strip() for n, _, v in pairs if n.strip().startswith("--")}

        mine, desk = root_of(self.text), root_of(DESK.read_text(encoding="utf-8"))
        self.assertTrue(mine)
        for name, value in mine.items():
            self.assertEqual(desk.get(name), value, name)
        for name in ("--peach", "--green", "--yellow", "--red"):
            self.assertNotIn(name, mine)
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", self.text)
        outside = re.sub(r"(?s):root\s*\{.*?\}", "", style)
        for pattern in (r"#[0-9a-fA-F]{3,8}\b", r"rgba?\(", r"hsla?\("):
            self.assertEqual(re.findall(pattern, outside), [], pattern)
        for _, decls in style_rules(outside):
            for prop, value in decls.items():
                if not re.fullmatch(
                        r"color|background|background-color|border.*|outline.*|fill|stroke", prop):
                    continue
                rest = re.sub(r"var\(--([a-z0-9-]+)\)",
                              lambda m: "" if "--" + m.group(1) in mine else m.group(0), value)
                rest = re.sub(r"-?\d*\.?\d+(?:px|rem|em|%)?", "", rest)
                rest = re.sub(r"\b(?:none|transparent|currentColor|inherit|solid|dashed|dotted)\b", "", rest)
                self.assertEqual(rest.strip(), "", f"{prop}: {value}")
        script = self.text[self.text.index("<script>"):]
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}", script), [])

    def test_the_spend_page_fits_480_wide(self) -> None:
        (style,) = re.findall(r"(?s)<style>(.*?)</style>", self.text)
        narrow = media_block(style, "(max-width: 480px)")
        base = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", style)
        narrow_rules = style_rules(narrow)
        self.assertEqual(
            [d.get("flex-wrap") for s, d in narrow_rules if s == ".top-in"], ["wrap"])
        rules = style_rules(base) + narrow_rules
        measured = 0
        for selector, decls in rules:
            for prop in ("width", "min-width", "flex-basis"):
                if prop not in decls:
                    continue
                measured += 1
                value = decls[prop]
                px = re.fullmatch(r"(\d+(?:\.\d+)?)px", value)
                self.assertTrue(
                    value in ("auto", "0") or re.fullmatch(r"\d+(?:\.\d+)?%", value)
                    or "100vw" in value or (px and float(px.group(1)) <= 448),
                    f"{selector} {prop}: {value}")
        self.assertGreater(measured, 0)
        merged = {}
        for selector, decls in rules:
            merged.setdefault(selector, {}).update(decls)
        self.assertEqual(
            merged.get(".trend-day", merged.get(".trend li", {})).get("min-width"), "0")
        self.assertEqual(merged.get(".row-name", {}).get("overflow-wrap"), "anywhere")


class SpendDecisionCitationTest(unittest.TestCase):
    def test_the_service_cites_the_spend_page_decision_under_the_number_main_left_free(
            self) -> None:
        # origin/main took 050 and 051 for the wait-signals (#1110) and owner-check (#1111)
        # decisions; the Spend page decision is the next free number, and a file under the
        # cited number, once it exists, must be the decision made in #1135.
        cited = re.findall(
            r"GET /spend. serves the Spend page.*?\(#1135, ADR-console-(\d+)\)",
            SERVICE.read_text(encoding="utf-8"), re.S)
        self.assertEqual(cited, ["052"])
        for path in ADR_DIR.glob("%s-*.md" % cited[0]):
            self.assertIn("- **Decided in:** #1135", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
