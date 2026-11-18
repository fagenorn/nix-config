"""The desk page's access list and the guest's read-only page (#1262).

Run: just agent-workflow-tests
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from collections import defaultdict
from types import MappingProxyType

from agent_tools.console import guest, service, sprints as sprint_words, view as consoleview
from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_SENT, GOAL_STATED, INBOX_SEEN, QUESTIONS_ASKED, Event)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_briefs import PARTS
from .test_console_guest import at, guest_inputs
from .test_console_inbox import C1, approve, comment_node, decision, issue_node
from .test_console_inbox import page as tracker_page, read as tracker_read
from .test_console_page import (
    ACTIVATION, APPROVED_TEXT, APPROVING_TEXT, BRIEF, CHECK, CHECK_ITEM, DONE_SPRINT, F3, HANDOFF_W, HARNESS,
    HEADSUP_W, OWNER_W, PAGE, REPORTED, SENT_TEXT, SPRINT, START, UNDATED_WAIT,
    box_open, full, has_class, message_entry, nodes, posted, project, question, role, view, with_check,
    with_notices, with_sprints)

TAILNET = "desk.invented-tailnet.ts.net"
OTHER_TAILNET = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SECOND = "second@example.invalid"
THIRD = "third@example.invalid"
STRANGER = "stranger@example.invalid"
NO_REPLY = {"status": 204, "text": ""}
HEADERS = {"X-Console-Token": "__CONSOLE_TOKEN__", "Content-Type": "application/json"}


def harness(steps: list, page_bytes: bytes | None = None) -> list:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is not on PATH; the page scenarios need it")
    with tempfile.TemporaryDirectory() as scratch:
        page = PAGE
        if page_bytes is not None:
            page = Path(scratch) / "page.html"
            page.write_bytes(page_bytes)
        done = subprocess.run(
            [node, str(HARNESS), str(page)],
            input=json.dumps(steps),
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "TZ": "UTC"},
        )
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


ACCESS = guest.Access(TAILNET, MappingProxyType({
    COLLEAGUE: frozenset({"owner/p01"}), SECOND: frozenset({"owner/p00", "owner/p01"})}))
SHARED_FRAME = {
    **view([project(1, [])]),
    "recent_projects": ["owner/p00", "owner/p01"],
    "sharing": guest.sharing_entry(
        ACCESS, "serving", guest.reading(ACCESS, [TAILNET], [STRANGER], [], [])),
}
OPEN = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
SNAP = {"snapshot": True}


def named(tree: dict, cls: str) -> list:
    return [n for n in nodes(tree) if has_class(n, cls)]


def writes(snap: dict) -> list:
    return [(p["url"], p["body"]) for p in snap["posts"] if p["url"] != "/api/looked"]


def sharing_frame(state: str, tailnet: str | None, last_request: dict | None) -> dict:
    entry = guest.sharing_entry(ACCESS, state, last_request)
    return {**SHARED_FRAME, "sharing": {**entry, "tailnet": tailnet}}


class SharingPanelTest(unittest.TestCase):
    def test_the_panel_opens_from_the_top_bar_and_escape_closes_it(self) -> None:
        closed, opened, after = harness([
            START, {"frame": SHARED_FRAME}, SNAP, {"focus_on": "share-open"},
            {"click": "share-open"}, {"key": "g"}, SNAP, {"key": "Escape"}, SNAP])
        self.assertIs(closed["sharing"]["hidden"], True)
        self.assertEqual(closed["sharing_open"]["expanded"], "false")
        self.assertEqual(closed["sharing_body"]["children"], [])
        self.assertIs(opened["sharing"]["hidden"], False)
        self.assertEqual(opened["sharing_open"]["expanded"], "true")
        self.assertEqual(opened["active"], "acct-panel share-panel")
        self.assertIs(box_open(opened), False)
        self.assertIs(after["sharing"]["hidden"], True)
        self.assertEqual(role(after["active"]), "share-open")
        self.assertIs(after["key_prevented"], True)
        self.assertEqual(after["sharing_body"]["children"], [])

    def test_one_panel_at_a_time(self) -> None:
        first, second = harness([
            START, {"frame": {**SHARED_FRAME, "capacity": F3["capacity"]}}, {"click": "cap"},
            {"click": "share-open"}, SNAP, {"click": "cap"}, SNAP])
        self.assertIs(first["accounts"]["hidden"], True)
        self.assertIs(first["sharing"]["hidden"], False)
        self.assertIs(second["accounts"]["hidden"], False)
        self.assertIs(second["sharing"]["hidden"], True)

    def test_the_panel_shows_the_access_list_and_its_lines(self) -> None:
        (snap,) = harness([*OPEN, SNAP])
        body = snap["sharing_body"]
        (tailnet,) = named(body, "share-tailnet")
        self.assertEqual(tailnet["value"], TAILNET)
        people = [(full(named(p, "share-who")[0]), full(named(p, "share-projects")[0]))
                  for p in named(body, "share-person")]
        self.assertEqual(people, [(COLLEAGUE, "owner/p01"), (SECOND, "owner/p00, owner/p01")])
        self.assertEqual(
            full(named(body, "share-line")[0]),
            "Sharing is on: Tailscale Serve sends desk.invented-tailnet.ts.net to the guest port.")
        self.assertEqual(
            full(named(body, "share-last")[0]),
            "Last request on the guest port: Host desk.invented-tailnet.ts.net, a login header, "
            "refused because that login is not on the list.")
        self.assertNotIn(STRANGER, full(body))
        self.assertEqual([full(n) for n in named(body, "share-project")],
                         ["owner/p00", "owner/p01"])
        (login,) = named(body, "share-login")
        self.assertEqual([tailnet["label"], login["label"]],
                         ["Tailnet name", "Colleague's Tailscale login"])
        self.assertEqual([n["cls"] for n in nodes(body)
                          if has_class(n, "needs") or has_class(n, "btn-primary")], [])

    def test_the_sharing_and_last_request_lines(self) -> None:
        lines = [
            ("off", None, "Sharing is off: no tailnet name is set."),
            ("unchecked", TAILNET,
             f"Sharing is on at {TAILNET}, but the console cannot tell whether Tailscale Serve "
             "is set up for the guest port."),
            ("not_proxying", TAILNET,
             f"Sharing is on at {TAILNET}, but Tailscale Serve is not set up for the guest port."),
            ("serving", TAILNET,
             f"Sharing is on: Tailscale Serve sends {TAILNET} to the guest port."),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for state, tailnet, _ in lines:
            steps += [{"frame": sharing_frame(state, tailnet, None)}, SNAP]
        for snap, (state, _, text) in zip(harness(steps), lines):
            with self.subTest(state=state):
                self.assertEqual(full(named(snap["sharing_body"], "share-line")[0]), text)
        last = "Last request on the guest port: "
        readings = [
            (guest.reading(ACCESS, [], [], [], []),
             last + "no Host, no login header, refused because the Host is not the tailnet name."),
            (guest.reading(ACCESS, [TAILNET], [COLLEAGUE, SECOND], [], []),
             last + f"Host {TAILNET}, 2 login headers, refused because it had not exactly one login header."),
            (guest.reading(ACCESS, [TAILNET], [], [], []),
             last + f"Host {TAILNET}, no login header, refused because it had not exactly one login header."),
            (guest.reading(ACCESS, [TAILNET], [STRANGER], [], []),
             last + f"Host {TAILNET}, a login header, refused because that login is not on the list."),
            (guest.reading(ACCESS, [TAILNET], [COLLEAGUE], [], []),
             last + f"Host {TAILNET}, a login header, admitted."),
            (guest.reading(guest.NO_ACCESS, [TAILNET], [COLLEAGUE], [], []),
             last + f"Host {TAILNET}, a login header, refused because sharing is off."),
            (None, "No request has come to the guest port yet."),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for reading, _ in readings:
            steps += [{"frame": sharing_frame("serving", TAILNET, reading)}, SNAP]
        for snap, (reading, text) in zip(harness(steps), readings):
            with self.subTest(reading=reading):
                shown = full(named(snap["sharing_body"], "share-last")[0])
                self.assertEqual(shown, text)
                self.assertNotIn("Serve", shown)

    def test_the_controls_call_the_owner_only_writes(self) -> None:
        (snap,) = harness([
            *OPEN, {"type": {"class": "share-tailnet", "text": OTHER_TAILNET}},
            {"click": "share-tailnet-save"}, {"click": "share-off"},
            {"type": {"class": "share-login", "text": THIRD}},
            {"click": "share-project", "nth": 0}, {"click": "share-add"},
            {"click": "share-edit", "nth": 1}, {"click": "share-project", "nth": 0},
            {"click": "share-add"}, {"click": "share-remove", "nth": 1}, SNAP])
        self.assertEqual(writes(snap), [
            (service.SHARE_TAILNET_PATH, '{"tailnet":"other.invented-tailnet.ts.net"}'),
            (service.SHARE_TAILNET_PATH, '{"tailnet":null}'),
            (service.SHARE_COLLEAGUE_PATH,
             '{"login":"third@example.invalid","projects":["owner/p00"]}'),
            (service.SHARE_COLLEAGUE_PATH,
             '{"login":"second@example.invalid","projects":["owner/p01"]}'),
            (service.SHARE_REMOVE_PATH, '{"login":"second@example.invalid"}'),
        ])
        for post in snap["posts"]:
            if post["url"] != "/api/looked":
                self.assertEqual(post["method"], "POST")
                self.assertEqual(post["headers"], HEADERS)
                self.assertIn(post["url"], service.OWNER_ONLY)

    def test_the_add_button_waits_for_a_login_and_a_project(self) -> None:
        shown = harness([
            *OPEN, SNAP, {"type": {"class": "share-login", "text": THIRD}}, SNAP,
            {"click": "share-project", "nth": 0}, SNAP,
            {"type": {"class": "share-login", "text": SECOND}}, SNAP])
        states = [(named(s["sharing_body"], "share-add")[0]["disabled"],
                   full(named(s["sharing_body"], "share-add")[0])) for s in shown]
        self.assertEqual(states, [
            (True, "Add"), (True, "Add"), (False, "Add"), (False, "Save projects")])

    def test_a_refused_write_shows_its_reason(self) -> None:
        sending, refused = harness([
            *OPEN, {"type": {"class": "share-login", "text": THIRD}}, {"click": "share-project"},
            {"hold": True}, {"click": "share-add"}, SNAP,
            {"release": {"status": 409, "text": "owner/p09 is not registered\n"}}, SNAP])
        (add,) = named(sending["sharing_body"], "share-add")
        self.assertEqual(add["aria_disabled"], "true")
        self.assertEqual(add["busy"], "true")
        (add,) = named(refused["sharing_body"], "share-add")
        self.assertIs(add["disabled"], False)
        self.assertIsNone(add["busy"])
        self.assertEqual(
            [full(n) for n in named(refused["sharing_body"], "share-refused")],
            ["The console refused: owner/p09 is not registered."])

    def test_a_busy_sharing_control_keeps_the_focus(self) -> None:
        sending, refused, done = harness([
            *OPEN, {"focus_on": "share-remove", "nth": 1}, {"hold": True},
            {"click": "share-remove", "nth": 1}, SNAP,
            {"release": {"status": 409, "text": "no"}}, SNAP,
            {"hold": True}, {"click": "share-remove", "nth": 1}, {"release": NO_REPLY}, SNAP])
        for snap in (sending, refused, done):
            (focused,) = [n for n in nodes(snap["sharing_body"]) if n["focused"]]
            self.assertTrue(has_class(focused, "share-remove"))
            (owner,) = [p for p in named(snap["sharing_body"], "share-person")
                        if any(n["focused"] for n in nodes(p))]
            self.assertEqual(full(named(owner, "share-who")[0]), SECOND)
        (focused,) = [n for n in nodes(sending["sharing_body"]) if n["focused"]]
        self.assertEqual(focused["busy"], "true")
        self.assertEqual(focused["aria_disabled"], "true")
        self.assertIs(focused["disabled"], False)

    def test_a_frame_keeps_the_typed_login_and_its_focus(self) -> None:
        (snap,) = harness([
            *OPEN, {"type": {"class": "share-login", "text": "sec"}},
            {"frame": SHARED_FRAME}, SNAP])
        self.assertEqual(snap["field"], {
            "cls": "share-login field-line", "value": "sec", "start": 3, "end": 3})
        self.assertIs(snap["sharing"]["hidden"], False)

    def test_a_frame_keeps_the_focus_on_the_same_colleague_and_project(self) -> None:
        remove, project_ = harness([
            *OPEN, {"focus_on": "share-remove", "nth": 1}, {"frame": SHARED_FRAME}, SNAP,
            {"focus_on": "share-project", "nth": 1}, {"frame": SHARED_FRAME}, SNAP])
        body = remove["sharing_body"]
        (focused,) = [n for n in nodes(body) if n["focused"]]
        self.assertTrue(has_class(focused, "share-remove"))
        (owner,) = [p for p in named(body, "share-person")
                    if any(n["focused"] for n in nodes(p))]
        self.assertEqual(full(named(owner, "share-who")[0]), SECOND)
        (focused,) = [n for n in nodes(project_["sharing_body"]) if n["focused"]]
        self.assertTrue(has_class(focused, "share-project"))
        self.assertEqual(full(focused), "owner/p01")

    def test_writes_on_one_tailnet_or_login_wait_their_turn(self) -> None:
        typed = "typed.invented-tailnet.ts.net"
        held, released, sending, done = harness([
            *OPEN, {"type": {"class": "share-tailnet", "text": OTHER_TAILNET}}, {"hold": True},
            {"click": "share-tailnet-save"},
            {"type": {"class": "share-tailnet", "text": typed}}, SNAP,
            {"click": "share-off"}, {"release": NO_REPLY}, SNAP,
            {"click": "share-edit", "nth": 1}, {"hold": True}, {"click": "share-add"}, SNAP,
            {"click": "share-remove", "nth": 1}, {"release": NO_REPLY}, SNAP])
        body = held["sharing_body"]
        self.assertEqual(
            [named(body, c)[0]["aria_disabled"] for c in ("share-off", "share-tailnet-save")],
            ["true", "true"])
        self.assertEqual(writes(released), [
            (service.SHARE_TAILNET_PATH, '{"tailnet":"other.invented-tailnet.ts.net"}')])
        self.assertEqual(named(released["sharing_body"], "share-tailnet")[0]["value"], typed)
        removes = named(sending["sharing_body"], "share-remove")
        self.assertEqual([n["aria_disabled"] for n in removes], [None, "true"])
        paths = [url for url, _ in writes(done)]
        self.assertEqual(paths.count(service.SHARE_COLLEAGUE_PATH), 1)
        self.assertNotIn(service.SHARE_REMOVE_PATH, paths)


GUEST = service.GUEST_PAGE
SCOPED = guest.scrub(consoleview.derive_view(**guest.scoped(guest_inputs(), frozenset({"owner/p01"}))))
OWNER_SPRINT = {**SPRINT, "stoppable": True, "retry": True, "ball": "owner",
                "ball_text": "waiting on you", "now_text": "waiting for your answer: Which store?"}
OWNER_BASE = consoleview.derive_view(**guest_inputs())
OWNER_FRAME = {
    **OWNER_BASE, "capacity": F3["capacity"], "activation": ACTIVATION,
    "sharing": SHARED_FRAME["sharing"], "recent_projects": ["owner/p00", "owner/p01"],
    "entries": [{**entry, "sprints": [OWNER_SPRINT]} if entry["project_id"] == "owner/p01" else entry
                for entry in OWNER_BASE["entries"]],
}
GUEST_STEPS = [START, {"frame": OWNER_FRAME}]
KEYS = [{"focus": True}, {"clock": 10000}, {"blur": True}, {"key": "a"}, {"key": "g"}, {"clock": 40000}]
CONTROLS = {"button", "input", "textarea", "select"}
SECOND_PERSON = re.compile(r"\byour?\b", re.IGNORECASE)
SENTENCES = [
    value.format_map(defaultdict(lambda: "Which store?"))
    for name, value in [*vars(sprint_words).items(), *[("BALL_TEXT", v) for v in sprint_words.BALL_TEXT.values()]]
    if isinstance(value, str) and (name.endswith("_TEXT") or name == "BALL_TEXT") and SECOND_PERSON.search(value)
    and name != "STOP_TEXT"  # the words sent to the manager, never a sentence the page draws
]


def page_of(page_bytes: bytes, steps: list) -> dict:
    return harness([*steps, {"snapshot": "page"}], page_bytes)[-1]


def sprint_text(snap: dict) -> str:
    return " ".join(n["text"] for item in named(snap["projects"], "sprint") if item["tag"] == "li"
                    for n in nodes(item))


class GuestPageTest(unittest.TestCase):
    def test_a_scoped_guest_page_names_only_the_guest_projects(self) -> None:
        snap = page_of(GUEST, [START, {"frame": SCOPED}])
        text = full(snap["page"])
        for kept in ("owner/p01", "own-goal-zq8"):
            self.assertIn(kept, text)
        for gone in ("owner/p00", "/srv/p00", "other-goal-zq7", "other-notice-zq6", "k-p00"):
            self.assertNotIn(gone, text)
        items = named(snap["inbox"], "guest-item")
        self.assertEqual(len(items), 1)
        for item in items:
            (wait,) = named(item, "guest-wait")
            self.assertTrue(full(wait).startswith("Waiting on the owner"))
        (h1,) = [n for n in snap["statement"]["children"] if n["tag"] == "h1"]
        self.assertEqual(full(h1), "1 thing waits on the owner")

    def test_the_guest_page_draws_no_owner_part_even_from_an_owner_frame(self) -> None:
        snap = harness([*GUEST_STEPS, *KEYS, {"snapshot": "page"}], GUEST)[-1]
        for member in ("capacity", "accounts", "accounts_body", "account_add", "spend_link", "sharing",
                       "sharing_body", "sharing_open", "register", "unmanaged", "digest", "promoted"):
            self.assertIsNone(snap[member], member)
        self.assertIsNotNone(snap["goal"])
        self.assertFalse(snap["goal"]["hidden"])
        shown = [n for child in snap["page"]["children"] if child != snap["viewer"] for n in nodes(child)]
        in_goal = nodes(snap["goal"])
        roles = {role(n["cls"]) for n in shown if n["cls"]}
        for banned in ("activation", "ask-open", "ask-box", "ask-text", "register-open", "sprint-acts", "sprint-more"):
            self.assertNotIn(banned, roles)
        self.assertLessEqual(
            {role(n["cls"]) for n in shown if n["tag"] in CONTROLS and n["cls"] and n not in in_goal},
            {"pic-thumb", "sprint-check"})
        for n in shown:
            if n["tag"] == "a":
                self.assertTrue((n["href"] or "").startswith("https:"), n)
            self.assertFalse(has_class(n, "needs") or has_class(n, "btn-primary"), n)
        text = full(snap["page"])
        for words in ("needs you", "waiting on you"):
            self.assertNotIn(words, text)
        self.assertEqual(snap["posts"], [])

    def test_the_owner_page_draws_those_parts(self) -> None:
        snap = page_of(PAGE.read_bytes(), GUEST_STEPS)
        for member in ("capacity", "spend_link", "sharing_open", "goal", "register"):
            self.assertIsNotNone(snap[member], member)
        for member in ("spend_link", "sharing_open", "goal", "capacity"):
            self.assertFalse(snap[member]["hidden"], member)
        roles = {role(n["cls"]) for n in nodes(snap["page"]) if n["cls"]}
        self.assertIn("activation", roles)
        self.assertTrue({"ask-open", "retry"} & roles)

    def test_the_top_bar_says_whose_console_it_is(self) -> None:
        guest_snap = page_of(GUEST, [START, {"frame": SCOPED}])
        owner_snap = page_of(PAGE.read_bytes(), [START, {"frame": SCOPED}])
        who = guest_snap["top_who"]
        self.assertFalse(who["hidden"])
        self.assertEqual(who["text"], "The owner's console, shared with you")
        self.assertNotIn("@", who["text"])
        self.assertNotIn("owner/", who["text"])
        self.assertTrue(owner_snap["top_who"]["hidden"])
        self.assertEqual(owner_snap["top_who"]["text"], "")

    def test_any_door_but_the_owner_s_is_read_only(self) -> None:
        elsewhere = PAGE.read_bytes().replace(
            b'id="console-door" content="owner"', b'id="console-door" content="elsewhere"')
        self.assertNotEqual(elsewhere, PAGE.read_bytes())
        snap = page_of(elsewhere, GUEST_STEPS)
        self.assertIsNone(snap["spend_link"])
        self.assertIsNone(snap["sharing_open"])

    def test_the_guest_reads_every_sprint_sentence_as_the_owner_s(self) -> None:
        self.assertTrue(SENTENCES)
        for text in SENTENCES:
            with self.subTest(text=text):
                frame = {**OWNER_FRAME, "entries": [
                    {**e, "sprints": [{**OWNER_SPRINT, "now_text": text}]} if e["project_id"] == "owner/p01" else e
                    for e in OWNER_FRAME["entries"]]}
                shown = sprint_text(page_of(GUEST, [START, {"frame": frame}]))
                self.assertIsNone(SECOND_PERSON.search(shown), shown)
                self.assertIn("the owner", shown.lower())
                self.assertRegex(sprint_text(page_of(PAGE.read_bytes(), [START, {"frame": frame}])), SECOND_PERSON)
        checked = {**OWNER_SPRINT, "checks": [{**CHECK, "project_id": "owner/p01",
                   "text": sprint_words.CHECK_LINE_TEXT.format(question="Which store?")}]}
        frame = {**OWNER_FRAME, "entries": [
            {**e, "sprints": [checked]} if e["project_id"] == "owner/p01" else e for e in OWNER_FRAME["entries"]]}
        snap = page_of(GUEST, [START, {"frame": frame}])
        shown = sprint_text(snap)
        self.assertIn("waiting on the owner", shown)
        self.assertIn("The owner's check: Which store?", shown)
        balls = [n for n in nodes(snap["projects"]) if has_class(n, "sprint-ball")]
        self.assertTrue(balls)
        self.assertFalse(any(has_class(ball, "needs") for ball in balls))

    def test_the_guest_reads_every_waiting_check_as_the_owner_s(self) -> None:
        self.assertTrue(consoleview.WAIT_TEXT)
        for reason, text in consoleview.WAIT_TEXT.items():
            with self.subTest(reason=reason):
                wait = {**UNDATED_WAIT, "text": text}
                frame = view([{**project(1, []), "waits": [wait]}])
                shown = full(page_of(GUEST, [START, {"frame": frame}])["projects"])
                self.assertIn(text.split(" you")[0], shown)
                self.assertIsNone(SECOND_PERSON.search(shown), shown)
        dated = {**UNDATED_WAIT, "until": "2026-11-18T12:00:00+00:00", "text": "Read what you filed."}
        shown = full(page_of(GUEST, [START, {"frame": view([{**project(1, []), "waits": [dated]}])}])["projects"])
        self.assertIn("Read what you filed.", shown)

    def test_the_guest_statement_counts_what_the_server_counts(self) -> None:
        base = view([project(1, [])])
        statement = base["statement"]

        def drawn(**changes) -> dict:
            frame = {**base, "statement": {**statement, **changes}}
            return page_of(GUEST, [START, {"frame": frame}])["statement"]

        (h1,) = [n for n in drawn(inbox_items=1, headline="1 thing needs you")["children"] if n["tag"] == "h1"]
        self.assertEqual(full(h1), "1 thing waits on the owner")
        self.assertFalse(has_class(h1, "needs"))
        stale = consoleview.STALE_SENTENCE.format(projects="owner/p01")
        shown = drawn(inbox_items=0, sentence=stale)
        self.assertEqual([full(n) for n in named(shown, "sub")], [stale])
        self.assertEqual(named(drawn(inbox_items=0, sentence="Answer it in the manager's terminal."), "sub"), [])

    def test_an_open_guest_fold_stays_open_across_frames(self) -> None:
        frame = view([with_notices(project(1, []), OWNER_W, HEADSUP_W)])
        snap = harness([START, {"frame": frame}, {"open": "notices:owner/p01"}, {"frame": frame}, SNAP], GUEST)[-1]
        (fold,) = [n for n in nodes(snap["projects"]) if n["key"] == "notices:owner/p01"]
        self.assertTrue(fold["open"])

    def test_a_guest_sprint_check_opens_its_card(self) -> None:
        snap = harness([START, {"frame": with_check([CHECK_ITEM])}, {"click": "sprint-check"}, SNAP], GUEST)[-1]
        self.assertEqual(snap["active"], "guest-item")

    def test_the_guest_bytes_hide_the_owner_header_before_the_script(self) -> None:
        markup = GUEST[:GUEST.index(b"<script>")].decode()
        for ident in ("spend-link", "sharing-open", "accounts", "sharing", "goal", "capacity"):
            (tag,) = re.findall(r'<[^>]*\bid="' + ident + r'"[^>]*>', markup)
            self.assertRegex(tag, r"\shidden(\s|>|$)", tag)
        self.assertIn(".top-in > [hidden] { display: none; }", markup)
        snap = harness([START, {"frame": view([])}, SNAP], None)[-1]
        self.assertFalse(snap["spend_link"]["hidden"])
        self.assertFalse(snap["sharing_open"]["hidden"])

    def test_the_guest_reads_notices_and_messages_as_the_owner_s(self) -> None:
        sent = message_entry(3, "text", "sent", text="a note")
        approved = message_entry(4, "approved", "sent")
        frame = view([with_notices({**project(1, []), "sprints": [{**OWNER_SPRINT, "messages": [sent, approved]}]},
                                   OWNER_W, HANDOFF_W, HEADSUP_W)])

        def lines(snap: dict) -> list:
            return [full(n) for n in nodes(snap["projects"])
                    if has_class(n, "notice-head") or has_class(n, "message-text")]

        guest_lines = lines(page_of(GUEST, [START, {"frame": frame}]))
        self.assertEqual(len(guest_lines), 5)
        for line in guest_lines:
            self.assertIsNone(re.search(r"\byou\b", line, re.IGNORECASE), line)
        joined = " ".join(guest_lines)
        self.assertIn("Heads-up, from The owner", joined)
        self.assertIn("Hand-off for the owner, from Fix the settings page", joined)
        self.assertIn("Heads-up, from Keep the importer fast", joined)
        self.assertIn("The owner: a note", guest_lines)
        owner_lines = lines(page_of(PAGE.read_bytes(), [START, {"frame": frame}]))
        self.assertIn("You: a note", owner_lines)
        self.assertIn("Hand-off for you, from Fix the settings page", " ".join(owner_lines))

    def test_the_guest_keeps_a_question_and_a_check_as_the_manager_wrote_them(self) -> None:
        question = "Can you retry? Your call."
        sprint = {**OWNER_SPRINT, "now_text": sprint_words.NOW_QUESTION_TEXT.format(question=question),
                  "checks": [{**CHECK, "project_id": "owner/p01",
                              "text": sprint_words.CHECK_LINE_TEXT.format(question=question)}]}
        frame = {**OWNER_FRAME, "entries": [
            {**e, "sprints": [sprint]} if e["project_id"] == "owner/p01" else e for e in OWNER_FRAME["entries"]]}
        shown = sprint_text(page_of(GUEST, [START, {"frame": frame}]))
        self.assertIn("waiting for the owner's answer: " + question, shown)
        self.assertIn("The owner's check: " + question, shown)

    def test_a_failed_tracker_read_never_reads_as_an_empty_inbox(self) -> None:
        def headline(frame: dict) -> str:
            snap = page_of(GUEST, [START, {"frame": frame}])
            (h1,) = [n for n in snap["statement"]["children"] if n["tag"] == "h1"]
            return full(h1)

        base = view([project(1, [])])
        stale = consoleview.STALE_SENTENCE.format(projects="owner/p00")
        sentence = {**base, "statement": {**base["statement"], "sentence": stale}}
        flagged = {**base, "statement": {**base["statement"], "stale": True}}
        self.assertEqual(headline(sentence), "Nothing known waits on the owner")
        self.assertEqual(headline(flagged), "Nothing known waits on the owner")
        self.assertEqual(headline(base), "Nothing waits on the owner")
        read_at = "2026-11-12T10:00:00+00:00"
        cached = page_of(GUEST, [START, {"frame": with_check([{**CHECK_ITEM, "stale": True, "read_at": read_at}])}])
        (row,) = named(cached["inbox"], "guest-item")
        (shown,) = named(row, "read-at")
        self.assertTrue(full(shown).startswith("read "), full(shown))
        fresh = page_of(GUEST, [START, {"frame": with_check([{**CHECK_ITEM, "stale": False}])}])
        self.assertEqual(named(named(fresh["inbox"], "guest-item")[0], "read-at"), [])


COLLEAGUE_SID, ROUND_SID = "s-mine", "s-round"
ASKED = {"question": "Which store keeps the checkpoints?", "blocks": "the resume slice",
         "options": ["sqlite", "files"], "recommended": "sqlite"}
SECOND_PARTS = {**PARTS, "title": "Reader reads the checkpoint"}


def tracker_items() -> list:
    """The live approval (12), the paid approval (13) and the decision (15), read as the tracker reader reads them."""
    cards = [issue_node(n, [comment_node(C1 + n, body)])
             for n, body in ((12, approve()), (13, approve("paid")), (15, decision()))]
    return [{**item, "project_id": "owner/p01", "repo": "owner/p01",
             **({"confirm": f"owner/p01#{item['issue']}"} if item["confirm"] else {})}
            for item in tracker_read(tracker_page(cards))]


def steer_frame(*, tracker: bool = True, rounds: bool = False, asked: dict = ASKED) -> dict:
    """The colleague's frame by the production path: the log's events, then `scoped`, `scrub` and `mark_steer`."""
    events = [Event(1, at(1), consoleview.REGISTERED, "owner/p01", {"root": "/srv/p01"})]

    def add(kind: str, payload: dict) -> None:
        events.append(Event(len(events) + 1, at(len(events) + 1), kind, "owner/p01", payload))

    for item in tracker_items() if tracker else []:
        add(INBOX_SEEN, item)
    add(GOAL_STATED, {"sprint_id": COLLEAGUE_SID, "goal": "Make the importer resumable", "by": COLLEAGUE})
    add(BRIEF_SENT, {"sprint_id": COLLEAGUE_SID, "version": 1, "brief": PARTS})
    if rounds:
        add(GOAL_STATED, {"sprint_id": ROUND_SID, "goal": "Read the checkpoint back", "by": COLLEAGUE})
        add(BRIEF_SENT, {"sprint_id": ROUND_SID, "version": 1, "brief": SECOND_PARTS})
        add(BRIEF_APPROVED, {"sprint_id": ROUND_SID, "version": 1, "by": COLLEAGUE})
        add(QUESTIONS_ASKED, {"sprint_id": ROUND_SID, "questions": [asked], "blocker": False})
    inputs = {
        "states": consoleview.project_states(events).values(),
        "sprints": sprint_words.sprint_states(events),
        "records": consoleview.inbox_records(events),
        "sessions": [], "owner_notices": {}, "now_ms": 1_000,
    }
    scoped = guest.scoped(inputs, frozenset({"owner/p01"}))
    return guest.mark_steer(guest.scrub(consoleview.derive_view(**scoped)), COLLEAGUE)


def owner_frame_with(sprints: list, **extra: object) -> dict:
    return {**OWNER_FRAME, **extra, "entries": [
        {**entry, "sprints": sprints} if entry["project_id"] == "owner/p01" else entry
        for entry in OWNER_FRAME["entries"]]}


def sprint_of(snap: dict, title: str) -> dict:
    (found,) = [n for n in nodes(snap["projects"])
                if n["tag"] == "li" and has_class(n, "sprint") and title in full(n)]
    return found


def controls_of(tree: dict) -> list:
    return [n for n in nodes(tree) if n["tag"] in CONTROLS]


def posts_to(snap: dict, url: str) -> list:
    return [p for p in snap["posts"] if p["url"] == url]


class GuestSteerPageTest(unittest.TestCase):
    def test_a_finished_sprint_keeps_its_starter_on_both_pages(self) -> None:
        ended = {**DONE_SPRINT, "started_by": COLLEAGUE}
        finished = {"label": "Finished sprints", "count": 1, "sprints": [ended]}
        frame = view([{**project(1, []), "sprints": [], "finished_sprints": finished}])
        for name, page in (("guest", GUEST), ("owner", PAGE.read_bytes())):
            with self.subTest(name):
                snap = page_of(page, [START, {"frame": frame}])
                (line,) = [n for n in nodes(snap["projects"]) if n["tag"] == "li" and has_class(n, "finished-line")]
                (summary,) = [c for c in nodes(line) if c["tag"] == "summary"]
                self.assertIn("started by " + COLLEAGUE, full(summary))
        plain = page_of(GUEST, [START, {"frame": view([{**project(1, []), "sprints": [], "finished_sprints": {
            **finished, "sprints": [DONE_SPRINT]}}])}])
        self.assertNotIn("started by", full(plain["projects"]))

    def test_a_release_paid_or_production_card_waits_on_the_owner_with_no_control(self) -> None:
        frame = steer_frame()
        brief = [item for item in frame["inbox"]["open"] if item["reason"] == "brief"]
        tracker = [item for item in frame["inbox"]["open"] if item["reason"] != "brief"]
        self.assertEqual([item["steer"] for item in brief], [True])
        self.assertEqual(len(tracker), 3)
        self.assertEqual([item["steer"] for item in tracker], [False] * 3)
        snap = page_of(GUEST, [START, {"frame": frame}])
        rows = named(snap["inbox"], "guest-item")
        self.assertEqual(len(rows), 3)
        for row in rows:
            (wait,) = named(row, "guest-wait")
            self.assertTrue(full(wait).startswith("Waiting on the owner"))
            self.assertEqual(controls_of(row), [])
        self.assertEqual(len(named(snap["inbox"], "approve")), 1)
        self.assertEqual(snap["posts"], [])
        (h1,) = [n for n in snap["statement"]["children"] if n["tag"] == "h1"]
        self.assertEqual(full(h1), "3 things wait on the owner")
        self.assertEqual([full(n) for n in named(snap["statement"], "sub")], ["1 thing waits on you"])

    def test_a_mixed_guest_inbox_keeps_its_waiting_rows_through_an_approval(self) -> None:
        frame = steer_frame()
        steps = [START, {"frame": frame}, {"click": "approve"}, SNAP, {"clock": 5001}, SNAP,
                 {"click": "tell-open"}, SNAP]
        waiting, done, opened = harness(steps, GUEST)
        for snap in (waiting, done, opened):
            self.assertEqual(len(named(snap["inbox"], "guest-item")), 3)
        self.assertIn(APPROVING_TEXT, full(waiting["inbox"]))
        self.assertEqual(len(named(waiting["inbox"], "undo")), 1)
        self.assertEqual(waiting["posts"], [])
        (post,) = posts_to(done, "/api/approve")
        self.assertEqual((post["method"], post["headers"]), ("POST", HEADERS))
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p01", "sprint_id": COLLEAGUE_SID, "version": 1})
        self.assertEqual(len(done["posts"]), 1)
        self.assertIn(APPROVED_TEXT, full(opened["inbox"]))
        self.assertEqual(len(posts_to(opened, "/api/approve")), 1)

    def test_a_steerable_brief_asks_for_changes_and_a_question_sends_its_answer(self) -> None:
        frame = steer_frame(tracker=False, rounds=True)
        (asked,) = [item for item in frame["inbox"]["open"] if item["reason"] == "question"]
        self.assertIs(asked["steer"], True)
        snap = harness([
            START, {"frame": frame},
            {"input": {"cls": "reply-text", "value": "split the importer"}}, {"click": "reply-send"},
            {"click": "opt", "nth": 1}, {"click": "send"}, {"clock": 5000}, SNAP], GUEST)[-1]
        (reply,) = posts_to(snap, "/api/reply")
        self.assertEqual(json.loads(reply["body"]), {
            "project_id": "owner/p01", "sprint_id": COLLEAGUE_SID, "version": 1,
            "reply": "split the importer"})
        (answer,) = posts_to(snap, "/api/round-answer")
        self.assertEqual(json.loads(answer["body"]), {
            "project_id": "owner/p01", "sprint_id": ROUND_SID, "round": asked["round"], "question": 0,
            "choice": 1})
        for post in (reply, answer):
            self.assertEqual((post["method"], post["headers"]), ("POST", HEADERS))
        self.assertEqual(len(snap["posts"]), 2)
        self.assertIn(SENT_TEXT, full(snap["inbox"]))
        self.assertEqual([n["disabled"] for n in named(snap["inbox"], "send")], [True])
        self.assertEqual([n["disabled"] for n in named(snap["inbox"], "opt")], [True, True])

    def test_a_withdrawn_question_keeps_the_colleague_s_typed_words_and_its_dismiss(self) -> None:
        frame = steer_frame(tracker=False, rounds=True, asked={**ASKED, "needs_words": ["files"]})
        gone = steer_frame(tracker=False)
        kept, dismissed = harness([
            START, {"frame": frame}, {"click": "opt", "nth": 1},
            {"type": {"class": "words-text", "text": "keep the files"}},
            {"click": "send"}, SNAP, {"frame": gone}, {"clock": 5000}, SNAP,
            {"click": "kept-words-dismiss"}, SNAP], GUEST)[-2:]
        (card,) = named(kept["inbox"], "kept-words")
        self.assertEqual([n["value"] for n in named(card, "kept-words-text")], ["keep the files"])
        self.assertEqual(len(named(card, "kept-words-dismiss")), 1)
        self.assertEqual(named(dismissed["inbox"], "kept-words"), [])

    def test_a_sprint_the_colleague_did_not_start_has_no_control(self) -> None:
        mine = {**OWNER_SPRINT, "sprint_id": "b" * 16, "title": "Mine", "steer": True,
                "started_by": COLLEAGUE, "retry": True}
        theirs = {**OWNER_SPRINT, "sprint_id": "c" * 16, "title": "Theirs", "steer": False,
                  "started_by": None, "retry": True}
        frame = owner_frame_with([mine, theirs])
        opened, sent = harness([
            START, {"frame": frame}, {"click": "tell-open"}, SNAP,
            {"type": {"class": "tell", "text": "keep the reader"}}, {"click": "tell-send"}, SNAP], GUEST)
        line = sprint_of(opened, "Mine")
        self.assertEqual(len(named(line, "tell")), 1)
        self.assertEqual(len(named(line, "tell-send")), 1)
        banned = {"retry", "sprint-more", "withdraw", "stop"}
        self.assertEqual(banned & {role(n["cls"]) for n in nodes(line) if n["cls"]}, set())
        other = sprint_of(opened, "Theirs")
        self.assertLessEqual({role(n["cls"]) for n in controls_of(other)}, {"pic-thumb", "sprint-check"})
        self.assertEqual(named(opened["projects"], "retry"), [])
        self.assertEqual(len(named(other, "tell-open")), 0)
        (post,) = posts_to(sent, "/api/message")
        self.assertEqual(json.loads(post["body"]), {
            "project_id": "owner/p01", "sprint_id": "b" * 16, "text": "keep the reader"})
        self.assertEqual(len(sent["posts"]), 1)

    def test_the_guest_door_asks_no_sign_in_link_from_an_owner_frame(self) -> None:
        brief = {**BRIEF, "steer": True, "started_by": COLLEAGUE}
        frame = {**OWNER_FRAME, "signin_runs": {"work": {"state": "running", "attempt": 1}},
                 "inbox": {"open": [brief], "answered": []}}
        snap = page_of(GUEST, [START, {"frame": frame}])
        self.assertEqual(snap["posts"], [])
        roles = {role(n["cls"]) for n in nodes(snap["page"]) if n["cls"]}
        self.assertEqual({"signin-send", "signin-link"} & roles, set())

    def test_the_waiting_words_follow_who_can_act(self) -> None:
        mine = {**OWNER_SPRINT, "sprint_id": "a" * 16, "title": "Mine", "steer": True,
                "started_by": COLLEAGUE}
        theirs = {**OWNER_SPRINT, "sprint_id": "b" * 16, "title": "Theirs", "steer": False}
        terminal = {**OWNER_SPRINT, "sprint_id": "c" * 16, "title": "Terminal", "steer": True,
                    "started_by": COLLEAGUE,
                    "now_text": "waiting for your answer in the manager's terminal"}
        asked = question(0, "Which store?", ["sqlite", "files"], "files", project_id="owner/p01",
                         steer=True, started_by=COLLEAGUE)
        frame = owner_frame_with([mine, theirs, terminal], inbox={"open": [asked], "answered": []})
        snap = page_of(GUEST, [START, {"frame": frame}])
        text = full(sprint_of(snap, "Mine"))
        self.assertIn("waiting on you", text)
        self.assertIn("waiting for your answer: Which store?", text)
        self.assertNotIn("the owner", text)
        text = full(sprint_of(snap, "Theirs"))
        self.assertIn("waiting on the owner", text)
        self.assertIn("waiting for the owner's answer: Which store?", text)
        self.assertIn("waiting for the owner's answer in the manager's terminal",
                      full(sprint_of(snap, "Terminal")))
        keys = [n for n in nodes(snap["page"]) if n["tag"] == "kbd" or (n["tag"] == "p" and has_class(n, "keys"))]
        self.assertEqual(keys, [])

    def test_the_guest_goal_box_offers_only_their_projects(self) -> None:
        self.assertEqual(SCOPED["recent_projects"], ["owner/p01"])
        typed, sent = harness([
            START, {"frame": SCOPED}, {"focus_on": "goal-text"},
            {"type": {"class": "goal-text", "text": "Make the importer resumable"}}, SNAP,
            {"click": "goal-project"}, {"click": "goal-send"}, SNAP], GUEST)
        self.assertEqual([full(n) for n in named(typed["goal"], "goal-project")], ["owner/p01"])
        (post,) = posts_to(sent, "/api/goal")
        self.assertEqual(json.loads(post["body"]),
                         {"project_id": "owner/p01", "goal": "Make the importer resumable"})
        self.assertEqual((post["method"], post["headers"]), ("POST", HEADERS))
        self.assertEqual(len(sent["posts"]), 1)
