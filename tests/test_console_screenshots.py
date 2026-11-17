"""The sprint screenshot set against a fixture console (#1086).

Run: just agent-workflow-tests
"""
import dataclasses
import json
import os
import pwd
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from . import accounts_sandbox
from . import console_screenshots as shots
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def fixture_paths(fixture):
    paths = [value for field in dataclasses.fields(fixture) if field.name != "holding"
             for value in ([getattr(fixture, field.name)] if field.name != "projects"
                           else list(fixture.projects))]
    return paths


def entries_of(view):
    for entry in view["entries"]:
        yield from (entry["projects"] if entry["type"] == "quiet_group" else [entry])


def all_sprints(view):
    found = []
    for project in entries_of(view):
        found.extend(project.get("sprints") or [])
        found.extend((project.get("finished_sprints") or {"sprints": []})["sprints"])
    return found


class ScreenshotFixtureTest(unittest.TestCase):
    def test_the_set_is_twenty_states_at_two_widths(self) -> None:
        self.assertEqual(len(shots.STATES), 20)
        self.assertEqual(shots.STATES.index("waiting-its-turn"),
                         shots.STATES.index("nothing-running") + 1)
        self.assertEqual(shots.STATES[-9:], ("owner-check", "spend-page", "notices-fold",
                                             "notice-post-open", "desk-spend", "goal-open",
                                             "inbox-card", "accounts-panel", "ask-box"))
        self.assertEqual(shots.STATES.index("tell-box-open"), shots.STATES.index("stuck") + 1)
        self.assertEqual(shots.WIDTHS, (1440, 480))

    def test_a_shot_with_jargon_or_a_clamped_sentence_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 0, 1))
        self.assertEqual(code, 1)
        self.assertIn("jargon label", text)
        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 1, 0))
        self.assertEqual(code, 1)
        self.assertIn("squeezes the now sentence", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 (False, None, None)))
        self.assertEqual(code, 1)
        self.assertIn("does not show the open Tell box", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 shots.OPEN_TELL))
        self.assertEqual(code, 0)

    def test_an_ask_box_shot_without_the_open_box_and_its_questions_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the open Ask box"
        for ask in ((False, None, None), (True, None, shots.ASK_READ_LINE),
                    (True, "Working on it", None)):
            with self.subTest(ask=ask):
                code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=ask))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=shots.OPEN_ASK))
        self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=None))
        self.assertEqual(code, 0)
        self.assertNotIn(phrase, text)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 ask=(False, None, None)))
        self.assertEqual(code, 0)

    def test_the_ask_box_shot_opens_owner_webs_box_only_on_a_page_that_has_one(self) -> None:
        field = 'li.asks[data-project="owner/web"] textarea.ask-text'

        def fake(has_ask):
            class Page:
                def __init__(self):
                    self.clicks = []
                    self.waits = []
                    self.reads = 0

                def goto(self, url):
                    pass

                def wait_for_selector(self, selector):
                    self.waits.append(selector)

                def query_selector(self, selector):
                    return object() if has_ask and selector == "li.asks" else None

                def click(self, selector):
                    self.clicks.append(selector)

                def evaluate(self, expression):
                    if expression == shots.ASK_READING:
                        self.reads += 1
                        return list(shots.OPEN_ASK)
                    if expression == shots.SCROLL_Y:
                        return 0.0
                    if expression == "document.documentElement.scrollWidth":
                        return 480
                    if expression == shots.SHORT_CONTROLS:
                        return []
                    return 0

                def screenshot(self, path, full_page):
                    pass

                def close(self):
                    pass

            page = Page()

            class Browser:
                def new_page(self, viewport):
                    return page

            return Browser(), page

        cases = (("head", "ask-box", True, [shots.ASK_OPEN], shots.OPEN_ASK),
                 ("base", "ask-box", False, [], None),
                 ("other state", "live-several", True, [], None))
        for name, state, has_ask, clicks, ask in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake(has_ask)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.ask, ask)
                self.assertEqual(page.reads, 1 if ask else 0)
                self.assertEqual(field in page.waits, bool(clicks))

    def test_a_shot_with_a_short_control_fails_the_command(self) -> None:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", return_value=[
                    shots.Shot("live-several", 1440, Path(tmp) / "p.png", 1440,
                               short=("button.undo 24px",))]), \
                redirect_stdout(out):
            code = shots.main(["--out", tmp])
        self.assertEqual(code, 1)
        self.assertIn("has a control under 32 px", out.getvalue())
        self.assertIn("button.undo 24px", out.getvalue())

    def test_a_shot_not_taken_from_the_top_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=240.0))
        self.assertEqual(code, 1)
        self.assertIn("x.png is not taken from the top of the page", text)
        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=0.0))
        self.assertEqual(code, 0)
        self.assertNotIn("not taken from the top", text)

    def test_a_shot_scrolls_back_to_the_top_before_its_capture(self) -> None:
        def fake(reset_to):
            class Page:
                y = 0.0

                def __init__(self):
                    self.captured = []

                def goto(self, url):
                    pass

                def wait_for_selector(self, selector):
                    pass

                def click(self, selector):
                    self.y = 300.0

                def evaluate(self, expression):
                    if expression == shots.SCROLL_TOP:
                        self.y = reset_to
                        return None
                    if expression == shots.SCROLL_Y:
                        return self.y
                    if expression == "document.documentElement.scrollWidth":
                        return 480
                    if expression == shots.SHORT_CONTROLS:
                        return []
                    return 0

                def screenshot(self, path, full_page):
                    self.captured.append((self.y, full_page))

                def close(self):
                    pass

            page = Page()

            class Browser:
                def new_page(self, viewport):
                    return page

            return Browser(), page

        for reset_to in (0.0, 40.0):
            with self.subTest(reset_to=reset_to), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake(reset_to)
                shot = shots._shoot(browser, "http://console.test/", "finished-list", 480,
                                    Path(tmp))
                self.assertEqual(page.captured, [(reset_to, True)])
                self.assertEqual(shot.scroll_y, reset_to)
                self.assertEqual(shot.scroll_y, page.captured[0][0])

    def test_every_fixture_path_is_temporary_and_never_a_real_one(self) -> None:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        real_registry = real_home / ".agents" / "state" / "fleet" / "registry.json"
        protected = [*accounts_sandbox.real_accounts_dirs(), real_home / ".agents" / "state"]
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = shots.build_fixture(root, state, time.time())
                paths = fixture_paths(fixture)
                for path in paths:
                    self.assertTrue(path.resolve().is_relative_to(root), path)
                self.assertFalse(accounts_sandbox.overlaps(paths, protected))
                self.assertNotEqual(fixture.registry.resolve(), real_registry.resolve())
                for value in shots.sandbox_environ(root).values():
                    self.assertTrue(Path(value).resolve().is_relative_to(root), value)
                self.assertEqual(
                    sorted(shots.sandbox_environ(root)),
                    ["CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR", "HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME"])
                svc = shots.start_service(fixture, time.time())
                try:
                    self.assertEqual(svc.registry, fixture.registry)
                finally:
                    svc.close()

    def test_the_fixture_service_never_reads_a_real_keepalive_log(self) -> None:
        # On darwin the service's default ping log is under the real HOME; the fixture
        # must not read it, or today's real pings price as keepalive spend (#1135).
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as tmp:
            log = Path(home) / "Library/Logs/claude-cache-proxy.log"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({
                "event": "ping", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "conversation": "real", "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 1000000}}) + "\n", encoding="utf-8")
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "finished-list", now_s)
            with mock.patch.dict(os.environ, {"HOME": home}), \
                    mock.patch.object(sys, "platform", "darwin"):
                svc = shots.start_service(fixture, now_s)
            try:
                days = json.loads(svc.view_bytes)["spend"]["days"]
            finally:
                svc.close()
            self.assertEqual([d["total"]["dollars"] for d in days if d["total"]["dollars"]], [])

    def test_each_fixture_view_shows_its_state(self) -> None:
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                launches: list = []
                svc = shots.start_service(fixture, now_s, launches)
                try:
                    view = json.loads(svc.view_bytes)
                finally:
                    svc.close()
                sprints = all_sprints(view)
                running = [s for s in sprints if s["ended_at"] is None]
                ended = [s for s in sprints if s["ended_at"] is not None]
                self.assertEqual(launches, [])
                for sprint in running:
                    self.assertEqual(sprint["manager_state"], "started", sprint["title"])
                    self.assertIsNone(sprint["manager_text"], sprint["title"])
                    self.assertFalse(sprint["now_text"].startswith("Working on"), sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["status"])
                    self.assertEqual(
                        [m for m in sprint["messages"]
                         if m["kind"] == "approved" and m["state"] == "picked_up"], [])
                latest = [s["messages"][-1] for s in running if s["messages"]]
                if state == "live-several":
                    self.assertEqual(len(running), 3)
                    self.assertEqual(
                        len({p["project_id"] for p in entries_of(view) if p.get("sprints")}), 2)
                    self.assertEqual({s["ball"] for s in running},
                                     {"manager", "owner", "nobody"})
                elif state == "waiting-on-you":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "waiting for your answer: Which store should the checkpoint use?")
                elif state == "stuck":
                    self.assertEqual([s["ball"] for s in running], ["nobody"])
                    self.assertEqual(running[0]["now_text"],
                                     "last seen building 1 of 2: the upload form")
                elif state == "tell-box-open":
                    self.assertEqual(len(running), 1)
                    self.assertEqual(running[0]["messages"], [])
                    self.assertIsInstance(running[0]["tell_text"], str)
                elif state == "message-sent":
                    self.assertEqual(len(running[0]["messages"]), 1)
                    self.assertEqual(latest[-1]["state"], "sent")
                elif state == "message-picked-up":
                    self.assertEqual(latest[-1]["state"], "picked_up")
                elif state == "message-replied":
                    self.assertEqual(latest[-1]["state"], "replied")
                    self.assertTrue(latest[-1]["new"])
                    self.assertIsInstance(view["new_replies_text"], str)
                elif state == "message-not-picked-up":
                    self.assertEqual(latest[-1]["state"], "not_picked_up")
                    self.assertTrue(latest[-1]["action_text"])
                elif state == "finished-list":
                    self.assertGreaterEqual(len(ended), 2)
                    self.assertTrue(any(s["closing"] for s in ended))
                elif state == "owner-check":
                    self.assertEqual([s["ball"] for s in running], ["manager"])
                    self.assertEqual(running[0]["now_text"], "building 1 of 3: the upload form")
                    self.assertEqual(
                        [c["text"] for c in running[0]["checks"]],
                        ["Your check: Do the before and after pictures read well?"])
                    self.assertEqual(view["statement"]["inbox_items"], 1)
                elif state == "nothing-running":
                    self.assertEqual(running, [])
                elif state == "waiting-its-turn":
                    self.assertEqual(
                        [(s["state"], s["ball"], s["now_text"]) for s in running],
                        [("on_track", "manager", "waiting its turn to merge")])
                    web = next(p for p in entries_of(view) if p.get("project_id") == "owner/web")
                    lone = next(d for s in web["outside_sprints"]["sessions"]
                                for d in s["deliveries"] if d["run_id"] == "wf_l1")
                    self.assertEqual(
                        (lone["quiet"], lone["moved_text"], lone["wait_text"]),
                        (False, "waiting its turn to merge", "waiting its turn to merge"))
                elif state == "goal-open":
                    other = shots.build_fixture(Path(tmp) / "other", "tell-box-open", now_s)
                    again = shots.start_service(other, now_s)
                    try:
                        self.assertEqual(
                            [s["title"] for s in running],
                            [s["title"] for s in all_sprints(json.loads(again.view_bytes))])
                    finally:
                        again.close()
                elif state == "inbox-card":
                    self.assertEqual(len(view["inbox"]["open"][0]["questions"][0]["options"]), 2)
                elif state == "accounts-panel":
                    self.assertEqual(
                        sorted(e["profile"] for e in view["capacity"]["profiles"]),
                        ["work-main", "work-spare"])
                elif state in ("notices-fold", "notice-post-open"):
                    self.assertEqual(
                        sorted(s["title"] for s in running),
                        ["Add resumable uploads", "Fix the settings page"])
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertTrue(web["notice_post"])
                    self.assertEqual(
                        [(n["poster"], n["kind"], n["text"], n["owner"]) for n in web["notices"]],
                        [("You", "heads-up", "routes are frozen until Friday", True),
                         ("Fix the settings page", "claim", "reworking the settings form",
                          False)])
                elif state == "ask-box":
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertEqual([q["state"] for q in web["questions"]],
                                     ["working", "answered"])
                    self.assertEqual([q["question"] for q in web["questions"]],
                                     [shots.ASK_WORKING_QUESTION, shots.ASK_ANSWERED_QUESTION])
                    self.assertEqual(web["questions"][1]["read_text"], shots.ASK_READ_LINE)
                    self.assertEqual(web["questions"][1]["ran_text"], "Ran: just build")
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                days = (view["spend"] or {"days": []})["days"]
                self.assertIsNotNone(view["spend"])
                if state == "desk-spend":
                    self.assertEqual(len(running), 1)
                    self.assertGreaterEqual(len(ended), 1)
                    self.assertLessEqual(
                        {running[0]["sprint_id"], ended[0]["sprint_id"]},
                        set().union(*(d["sprint"] for d in days[-7:])))
                    line = next(p for p in entries_of(view)
                                if p.get("project_id") == "owner/web")["outside_sprints"]
                    outside = {s["session_id"]: s for s in line["sessions"]}
                    self.assertEqual(
                        [d["run_id"] for d in outside["outside-1136"]["deliveries"]], ["wf_9"])
                    self.assertIn("wf_9", set().union(*(d["run"] for d in days[-7:])))
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                elif state == "spend-page":
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                    self.assertGreaterEqual(
                        sum(1 for d in days[-7:] if d["total"]["dollars"] > 0), 4)
                    self.assertGreaterEqual(
                        len(set().union(*(d["phase"] for d in days[-7:]))), 2)
                    self.assertIn(running[0]["sprint_id"],
                                  set().union(*(d["sprint"] for d in days[-7:])))
                else:
                    self.assertEqual(days[-1]["total"]["dollars"], 0)


class ScreenshotCaptureTest(unittest.TestCase):
    def test_the_command_writes_a_png_per_state_and_width_and_nothing_scrolls_sideways(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            taken = shots.capture(out)
            self.assertEqual([s for s in taken if s.width == 480 and s.scroll_width > 480], [])
            self.assertEqual([s for s in taken if s.squeezed], [])
            self.assertEqual([s for s in taken if s.jargon], [])
            self.assertEqual([(s.path.name, s.scroll_y) for s in taken if s.scroll_y != 0], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "tell-box-open" and s.tell == shots.OPEN_TELL],
                list(shots.WIDTHS))
            self.assertEqual(
                [s for s in taken if s.state != "tell-box-open" and s.tell is not None], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "ask-box" and s.ask == shots.OPEN_ASK],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.state != "ask-box" and s.ask is not None], [])
            self.assertEqual(shots.main(["--out", str(out)]), 0)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(
                names, sorted(f"{s}-{w}.png" for s in shots.STATES for w in shots.WIDTHS))
            self.assertEqual(len(names), 2 * len(shots.STATES))
            for path in out.iterdir():
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class ScreenshotReadingTest(unittest.TestCase):
    def read_pages(self, htmls, expression):
        """Load each markup alone in one 1440x900 Chromium page and return what `expression` reads."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                found = []
                for html in htmls:
                    page.set_content(html)
                    found.append(page.evaluate(expression))
                return found
            finally:
                browser.close()

    def test_the_jargon_count_counts_each_visible_review_phrase(self) -> None:
        samples = {
            "on track": "<p>The sprint for owner/p00 is now on track: x</p>",
            "stated": '<div id="projects"><span>stated <time>3 min ago</time></span></div>',
            "withdraw": '<div id="projects"><button>Withdraw</button></div>',
            "nudge": '<div id="projects"><p>Tell the manager again to nudge it.</p></div>',
            "stop or": '<div id="projects"><p>Stop or go</p></div>',
            "would do differently":
                '<div id="projects"><p>Would do differently: cut smaller slices</p></div>',
            "approval row": '<div id="projects"><ul><li class="message">'
                            '<span class="message-text">You: Approved version 2</span>'
                            '<span class="message-state">picked up</span></li></ul></div>'}
        counts = self.read_pages([f"<body>{html}</body>" for html in samples.values()],
                                 shots.JARGON_COUNT)
        for name, count in zip(samples, counts):
            with self.subTest(name):
                self.assertEqual(count, 1)

    def test_the_jargon_count_skips_the_owners_withdraw(self) -> None:
        owners = ('<body><div id="projects"><button class="notice-withdraw">Withdraw</button>'
                  '</div></body>')
        other = '<body><div id="projects"><button>Withdraw</button></div></body>'
        self.assertEqual(self.read_pages([owners, other], shots.JARGON_COUNT), [0, 1])

    def test_the_jargon_count_skips_hidden_text_and_the_new_words(self) -> None:
        html = ('<body><div id="projects"><details><summary>End the sprint</summary>'
                '<button>Drop the sprint</button>'
                '<p>withdraw nudge on track stated 3 min ago Stop or go Would do differently</p>'
                '</details><p style="display:none">Withdraw</p>'
                '<span>goal set <time>3 min ago</time></span><p><button>Stop and report</button></p>'
                '<p>Could not drop: no</p><p>Next time: cut smaller slices</p>'
                '<ul><li class="message"><span class="message-text">You: Approved version 2</span>'
                '<span class="message-state">sent just now</span></li></ul></div></body>')
        self.assertEqual(self.read_pages([html], shots.JARGON_COUNT), [0])

    def test_the_control_reading_flags_a_control_under_32_px(self) -> None:
        bodies = ['<button style="height:24px">a</button>',
                  '<button style="min-height:32px">b</button>',
                  '<button style="display:none;height:10px">c</button>',
                  '<input style="height:20px">',
                  '<button style="height:31.75px;padding:0;border:0">e</button>',
                  '<details><summary class="more-open btn-quiet" '
                  'style="display:block;height:24px">f</summary></details>']
        found = self.read_pages([f"<body>{html}</body>" for html in bodies], shots.SHORT_CONTROLS)
        self.assertEqual([len(f) for f in found], [1, 0, 0, 1, 1, 1])
        self.assertEqual(found[5], ["summary.more-open 24px"])

    def test_the_tell_reading_flags_an_overlapping_or_narrow_field(self) -> None:
        def layout(*, hint_first=False, field="width:100%"):
            hint = '<p class="tell-hint">hint</p>'
            label = ('<label class="tell-label" style="display:block">'
                     '<span style="display:block">Tell the manager</span>'
                     f'<textarea class="tell" style="display:block;{field};box-sizing:border-box">'
                     '</textarea></label>')
            body = (hint + label if hint_first else label + hint) + '<button class="tell-send">Send</button>'
            return ('<ul><li class="sprint" style="width:600px;padding:0 12px;list-style:none">'
                    f'<div class="sprint-tell">{body}</div></li></ul>')

        layouts = {"good": layout(), "hint above": layout(hint_first=True),
                   "narrow": layout(field="width:200px")}
        readings = self.read_pages(list(layouts.values()), shots.TELL_READING)
        for (name, _), reading in zip(layouts.items(), readings):
            with self.subTest(name):
                self.assertEqual(reading[:3], [True, "Send", "hint"])
                self.assertIs(reading[3], name == "good")

    def test_the_ask_reading_reads_the_open_box_and_its_questions(self) -> None:
        field = ('<div class="ask-box"><textarea class="ask-text" '
                 'style="width:300px;height:60px"></textarea></div>')

        def block(*, textarea=True, working_style=""):
            return ('<ul><li class="line asks" data-project="owner/web">'
                    + (field if textarea else '<div class="ask-box"></div>')
                    + '<ul class="ask-list"><li class="ask"' + working_style + '>'
                    '<p class="ask-question">Is the importer deployed on this host? '
                    '<time>just now</time></p><p class="ask-state">Working on it</p></li>'
                    '<li class="ask"><p class="ask-question">What does the build check? '
                    '<time>3 min ago</time></p><p class="ask-answer">It builds.</p>'
                    '<p class="ask-read">Read: flake.nix, lib/helpers.nix</p></li></ul>'
                    '</li></ul>')

        found = self.read_pages(
            [block(), block(textarea=False), block(working_style=' style="display:none"'),
             "<ul><li>nothing</li></ul>"], shots.ASK_READING)
        self.assertEqual(found, [
            list(shots.OPEN_ASK),
            [False, "Working on it", "Read: flake.nix, lib/helpers.nix"],
            [True, None, "Read: flake.nix, lib/helpers.nix"],
            None])


if __name__ == "__main__":
    unittest.main()
