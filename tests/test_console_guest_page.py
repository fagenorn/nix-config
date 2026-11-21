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
    HEADSUP_W, NOW_S, OWNER_W, PAGE, REPORTED, SENT_TEXT, SPRINT, START, UNDATED_WAIT,
    box_open, full, has_class, message_entry, nodes, posted, project, question, real_capacity, role, view,
    with_check, with_notices, with_sprints)

TAILNET = "desk.invented-tailnet.ts.net"
OTHER_TAILNET = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SECOND = "second@example.invalid"
THIRD = "third@example.invalid"
STRANGER = "stranger@example.invalid"
NO_REPLY = {"status": 204, "text": ""}
HEADERS = {"X-Console-Token": "__CONSOLE_TOKEN__", "Content-Type": "application/json"}
OWN = guest.own_addresses({"Self": {"TailscaleIPs": ["100.64.0.10"]}})
SELF_ADDRESS = "100.64.0.10"
OTHER_DEVICE_ADDRESS = "100.64.0.20"
OUTSIDE_SEEN = "A request from another device has reached the guest door since the console started."
OUTSIDE_NONE = (
    "No request from another device has reached the guest door since the console started; "
    "the tailnet's access rules must allow TCP 443 to this host for the people this console is shared with.")


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


ACCESS = guest.Access(True, MappingProxyType({
    COLLEAGUE: frozenset({"owner/p01"}), SECOND: frozenset({"owner/p00", "owner/p01"})}))
SHARED_FRAME = {
    **view([project(1, [])]),
    "recent_projects": ["owner/p00", "owner/p01"],
    "sharing": guest.sharing_entry(
        ACCESS, TAILNET, "serving",
        guest.reading(ACCESS, TAILNET, ["localhost"], [TAILNET], [STRANGER], [], [])),
}
UNSHARED_FRAME = {**SHARED_FRAME, "sharing": guest.sharing_entry(guest.Access(False, ACCESS.colleagues), TAILNET, "off")}
OPEN = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
UNSHARED_OPEN = [START, {"frame": UNSHARED_FRAME}, {"click": "share-open"}]
SNAP = {"snapshot": True}


def named(tree: dict, cls: str) -> list:
    return [n for n in nodes(tree) if has_class(n, cls)]


def writes(snap: dict) -> list:
    return [(p["url"], p["body"]) for p in snap["posts"] if p["url"] != "/api/looked"]


def sharing_frame(state: str, tailnet: str | None, last_request: dict | None, shared: bool = True,
                  seen: bool = False) -> dict:
    return {**SHARED_FRAME, "sharing": guest.sharing_entry(
        guest.Access(shared, ACCESS.colleagues), tailnet, state, last_request, other_device_seen=seen)}


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
        self.assertEqual(named(body, "share-tailnet"), [])
        self.assertEqual(named(body, "share-tailnet-save"), [])
        self.assertEqual(
            full(named(body, "share-name")[0]),
            "This host's tailnet name, read from Tailscale: desk.invented-tailnet.ts.net.")
        self.assertEqual(len(named(body, "share-off")), 1)
        self.assertEqual(named(body, "share-on"), [])
        people = [(full(named(p, "share-who")[0]), full(named(p, "share-projects")[0]))
                  for p in named(body, "share-person")]
        self.assertEqual(people, [(COLLEAGUE, "owner/p01"), (SECOND, "owner/p00, owner/p01")])
        self.assertEqual(
            full(named(body, "share-line")[0]),
            "Sharing is on: Tailscale Serve sends desk.invented-tailnet.ts.net to the guest door.")
        self.assertEqual(
            full(named(body, "share-last")[0]),
            "Last request on the guest door: Host localhost, forwarded Host "
            "desk.invented-tailnet.ts.net, a login header, "
            "refused because that login is not on the list.")
        self.assertNotIn(STRANGER, full(body))
        self.assertEqual([full(n) for n in named(body, "share-project")],
                         ["owner/p00", "owner/p01"])
        (login,) = named(body, "share-login")
        self.assertEqual([n["label"] for n in nodes(body) if n.get("label")],
                         ["Colleague's Tailscale login"])
        self.assertEqual(login["label"], "Colleague's Tailscale login")
        self.assertEqual([n["cls"] for n in nodes(body)
                          if has_class(n, "needs") or has_class(n, "btn-primary")], [])

    def test_the_sharing_and_last_request_lines(self) -> None:
        named_line = f"This host's tailnet name, read from Tailscale: {TAILNET}."
        unread = "can't read this host's tailnet name"
        lines = [
            ("off", False, TAILNET, "Sharing is off.", named_line),
            ("off", False, None,
             "Sharing is off, and the console can't read this host's tailnet name from Tailscale.", None),
            ("unreadable", True, None,
             "Sharing is on, but the console can't read this host's tailnet name from Tailscale, "
             "so guests can't get in.", None),
            ("unchecked", True, TAILNET,
             f"Sharing is on at {TAILNET}, but the console cannot tell whether Tailscale Serve "
             "is set up for the guest door.", named_line),
            ("not_proxying", True, TAILNET,
             f"Sharing is on at {TAILNET}, but Tailscale Serve is not set up for the guest door.",
             named_line),
            ("serving", True, TAILNET,
             f"Sharing is on: Tailscale Serve sends {TAILNET} to the guest door.", named_line),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for state, shared, tailnet, _, _ in lines:
            steps += [{"frame": sharing_frame(state, tailnet, None, shared)}, SNAP]
        for snap, (state, shared, tailnet, text, name_line) in zip(harness(steps), lines):
            with self.subTest(state=state, shared=shared, tailnet=tailnet):
                body = snap["sharing_body"]
                self.assertEqual(full(named(body, "share-line")[0]), text)
                self.assertEqual([full(n) for n in named(body, "share-name")],
                                 [] if name_line is None else [name_line])
                if tailnet is None:
                    self.assertEqual(
                        sum(unread in full(n) for cls in ("share-name", "share-line", "share-last")
                            for n in named(body, cls)), 1)
                drawn, absent = ("share-off", "share-on") if shared else ("share-on", "share-off")
                self.assertEqual(len(named(body, drawn)), 1)
                self.assertEqual(named(body, absent), [])
                self.assertIsNot(named(body, drawn)[0]["disabled"], True)
        last = "Last request on the guest door: "
        why_host = "refused because the Host is not localhost or the forwarded Host is not the tailnet name."
        why_login = "refused because it had not exactly one login header."
        local = ["localhost"]
        readings = [
            (guest.reading(ACCESS, TAILNET, [], [], [], [], []),
             last + "no Host, no forwarded Host, no login header, " + why_host),
            (guest.reading(ACCESS, TAILNET, [TAILNET], [TAILNET], [COLLEAGUE], [], []),
             last + f"Host {TAILNET}, forwarded Host {TAILNET}, a login header, " + why_host),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET, TAILNET], [COLLEAGUE], [], []),
             last + "Host localhost, 2 forwarded Host headers, a login header, " + why_host),
            (guest.reading(ACCESS, TAILNET, local, ["a" * 300], [COLLEAGUE], [], []),
             last + "Host localhost, a forwarded Host the console does not keep, "
                    "a login header, " + why_host),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE, SECOND], [], []),
             last + f"Host localhost, forwarded Host {TAILNET}, 2 login headers, " + why_login),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [], [], []),
             last + f"Host localhost, forwarded Host {TAILNET}, no login header, " + why_login),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [STRANGER], [], []),
             last + f"Host localhost, forwarded Host {TAILNET}, a login header, "
                    "refused because that login is not on the list."),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [], []),
             last + f"Host localhost, forwarded Host {TAILNET}, a login header, admitted."),
            (guest.reading(guest.NO_ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [], []),
             last + f"Host localhost, forwarded Host {TAILNET}, a login header, "
                    "refused because sharing is off."),
            (guest.reading(ACCESS, None, local, [TAILNET], [COLLEAGUE], [], []),
             last + "Host localhost, a forwarded Host the console does not keep, a login header, "
                    "refused because the console could not read this host's tailnet name."),
            (None, "No request has come to the guest door yet."),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for reading, _ in readings:
            steps += [{"frame": sharing_frame("serving", TAILNET, reading)}, SNAP]
        for snap, (reading, text) in zip(harness(steps), readings):
            with self.subTest(reading=reading):
                shown = full(named(snap["sharing_body"], "share-last")[0])
                self.assertEqual(shown, text)
                self.assertNotIn("Serve", shown)

    def test_the_outside_line_says_whether_another_device_came(self) -> None:
        local = ["localhost"]
        self_probe = guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [SELF_ADDRESS], [], own=OWN)
        outside = guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [OTHER_DEVICE_ADDRESS], [], own=OWN)
        rows = [
            (sharing_frame("serving", TAILNET, None), [OUTSIDE_NONE]),
            (sharing_frame("serving", TAILNET, self_probe), [OUTSIDE_NONE]),
            (sharing_frame("serving", TAILNET, outside, seen=True), [OUTSIDE_SEEN]),
            (sharing_frame("serving", TAILNET, self_probe, seen=True), [OUTSIDE_SEEN]),
            (sharing_frame("not_proxying", TAILNET, None), [OUTSIDE_NONE]),
            (sharing_frame("unreadable", None, None), [OUTSIDE_NONE]),
            (sharing_frame("off", TAILNET, None, shared=False), []),
            (sharing_frame("off", TAILNET, outside, shared=False, seen=True), []),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for frame, _ in rows:
            steps += [{"frame": frame}, SNAP]
        self.assertIn("TCP 443", OUTSIDE_NONE)
        for n, (snap, (_, expected)) in enumerate(zip(harness(steps), rows)):
            with self.subTest(row=n + 1):
                body = snap["sharing_body"]
                self.assertEqual([full(node) for node in named(body, "share-outside")], expected)
                if expected:
                    order = [next(i for i, node in enumerate(nodes(body)) if has_class(node, cls))
                             for cls in ("share-line", "share-outside")]
                    self.assertEqual(order[1], order[0] + 1)
                self.assertNotIn("100.64", full(body))
                for node in named(body, "share-outside") + named(body, "share-last"):
                    self.assertNotIn("@", full(node))
                    self.assertNotIn("100.64", full(node))

    def test_the_last_request_line_names_where_it_came_from(self) -> None:
        local = ["localhost"]
        tail = f"Host localhost, forwarded Host {TAILNET}, a login header, admitted."
        rows = [
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [SELF_ADDRESS], [], own=OWN),
             "Last request on the guest door, from this host: " + tail),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [OTHER_DEVICE_ADDRESS], [], own=OWN),
             "Last request on the guest door, from another device: " + tail),
            (guest.reading(ACCESS, TAILNET, local, [TAILNET], [COLLEAGUE], [], []),
             "Last request on the guest door: " + tail),
        ]
        steps = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]
        for reading, _ in rows:
            steps += [{"frame": sharing_frame("serving", TAILNET, reading)}, SNAP]
        for snap, (_, text) in zip(harness(steps), rows):
            with self.subTest(text=text):
                self.assertEqual(full(named(snap["sharing_body"], "share-last")[0]), text)

    def test_the_controls_call_the_owner_only_writes(self) -> None:
        (snap,) = harness([
            *OPEN, {"click": "share-off"},
            {"frame": UNSHARED_FRAME}, {"click": "share-on"},
            {"type": {"class": "share-login", "text": THIRD}},
            {"click": "share-project", "nth": 0}, {"click": "share-add"},
            {"click": "share-edit", "nth": 1}, {"click": "share-project", "nth": 0},
            {"click": "share-add"}, {"click": "share-remove", "nth": 1}, SNAP])
        self.assertEqual(writes(snap), [
            (service.SHARE_TAILNET_PATH, '{"shared":false}'),
            (service.SHARE_TAILNET_PATH, '{"shared":true}'),
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

    def test_writes_on_the_switch_or_one_login_wait_their_turn(self) -> None:
        held, released, sending, done = harness([
            *OPEN, {"hold": True}, {"click": "share-off"}, {"click": "share-off"}, SNAP,
            {"release": NO_REPLY}, SNAP,
            {"click": "share-edit", "nth": 1}, {"hold": True}, {"click": "share-add"}, SNAP,
            {"click": "share-remove", "nth": 1}, {"release": NO_REPLY}, SNAP])
        self.assertEqual(named(held["sharing_body"], "share-off")[0]["aria_disabled"], "true")
        self.assertEqual(writes(released), [(service.SHARE_TAILNET_PATH, '{"shared":false}')])
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
        in_goal = nodes(snap["goal"]) + nodes(snap["own_account"])
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

    def test_a_production_question_the_manager_marked_owner_only_waits_with_no_control(self) -> None:
        frame = steer_frame(tracker=False, rounds=True, asked={**ASKED, "owner_only": True})
        (asked,) = [item for item in frame["inbox"]["open"] if item["reason"] == "question"]
        self.assertIs(asked["owner_only"], True)
        self.assertIs(asked["steer"], False)
        snap = page_of(GUEST, [START, {"frame": frame}])
        (row,) = named(snap["inbox"], "guest-item")
        (wait,) = named(row, "guest-wait")
        self.assertTrue(full(wait).startswith("Waiting on the owner"))
        self.assertIn(ASKED["question"], full(row))
        self.assertEqual(controls_of(row), [])
        self.assertEqual(snap["posts"], [])

    def test_a_goal_never_goes_to_another_project_when_the_chosen_one_leaves_the_list(self) -> None:
        both = {**SCOPED, "recent_projects": ["owner/p01", "owner/p02"]}
        left = {**SCOPED, "recent_projects": ["owner/p01"]}
        words = "Make the importer resumable"
        refused, sent = harness([
            START, {"frame": both}, {"focus_on": "goal-text"},
            {"type": {"class": "goal-text", "text": words}}, {"click": "goal-project", "nth": 1},
            {"frame": left}, {"click": "goal-send"}, SNAP,
            {"click": "goal-project"}, {"click": "goal-send"}, SNAP], GUEST)
        self.assertEqual(posts_to(refused, "/api/goal"), [])
        self.assertIn("Could not send: choose a project", full(refused["goal"]))
        self.assertEqual([n["value"] for n in named(refused["goal"], "goal-text")], [words])
        (post,) = posts_to(sent, "/api/goal")
        self.assertEqual(json.loads(post["body"]), {"project_id": "owner/p01", "goal": words})

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

    def test_a_mixed_round_names_the_owner_for_an_owner_only_first_question(self) -> None:
        mine = {**OWNER_SPRINT, "sprint_id": "a" * 16, "title": "Mine", "steer": True,
                "started_by": COLLEAGUE, "now_text": "waiting for your answer: Which store?"}
        first = question(0, "Which store?", ["sqlite", "files"], "files", project_id="owner/p01",
                         sprint_id="a" * 16, steer=False, started_by=COLLEAGUE, owner_only=True)
        later = question(1, "May the reader change?", ["yes", "no"], "no", project_id="owner/p01",
                         sprint_id="a" * 16, steer=True, started_by=COLLEAGUE)
        frame = owner_frame_with([mine], inbox={"open": [first, later], "answered": []})
        text = full(sprint_of(page_of(GUEST, [START, {"frame": frame}]), "Mine"))
        self.assertIn("waiting for the owner's answer: Which store?", text)
        self.assertNotIn("waiting for your answer", text)
        reversed_ = owner_frame_with([mine], inbox={"open": [{**first, "steer": True}, {**later, "steer": False}],
                                                    "answered": []})
        text = full(sprint_of(page_of(GUEST, [START, {"frame": reversed_}]), "Mine"))
        self.assertIn("waiting for your answer: Which store?", text)

    def test_an_answered_look_card_never_decides_who_the_sprint_waits_on(self) -> None:
        mine = {**OWNER_SPRINT, "sprint_id": "a" * 16, "title": "Mine", "steer": True,
                "started_by": COLLEAGUE, "now_text": "waiting for your answer: May the reader change?"}
        look = question(0, "Does the new line read right?", ["Approve", "Ask for changes"], "Approve",
                        project_id="owner/p01", sprint_id="a" * 16, steer=False, answered=True,
                        started_by=COLLEAGUE)
        later = question(1, "May the reader change?", ["yes", "no"], "no", project_id="owner/p01",
                         sprint_id="a" * 16, steer=True, started_by=COLLEAGUE)
        frame = owner_frame_with([mine], inbox={"open": [look, later], "answered": []})
        text = full(sprint_of(page_of(GUEST, [START, {"frame": frame}]), "Mine"))
        self.assertIn("waiting for your answer: May the reader change?", text)
        self.assertNotIn("the owner's answer", text)

    def test_a_guest_answer_option_has_no_badge_column(self) -> None:
        frame = steer_frame(tracker=False, rounds=True)
        snap = page_of(GUEST, [START, {"frame": frame}])
        options = named(snap["inbox"], "opt")
        self.assertEqual(len(options), 2)
        for option in options:
            self.assertTrue(has_class(option, "keyless"), option["cls"])
        owner = harness([START, {"frame": {**OWNER_FRAME, "inbox": {"open": [
            question(0, "Which store?", ["sqlite", "files"], "files")], "answered": []}}},
            {"snapshot": "page"}])[-1]
        for option in named(owner["inbox"], "opt"):
            self.assertFalse(has_class(option, "keyless"))

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


A1 = {"label": "Account 1", "state": "ok", "week_left": 62, "five_hour_left": 80,
      "week_reset": "2099-01-06T14:00:00+00:00", "five_hour_reset": "2099-01-01T15:00:00+00:00",
      "next_reset": "2099-01-01T15:00:00+00:00", "out_until": None, "in_use": True}
A2 = {"label": "Account 2", "state": "out", "week_left": 0, "five_hour_left": 100,
      "week_reset": "2099-01-03T09:00:00+00:00", "five_hour_reset": "2099-01-01T18:00:00+00:00",
      "next_reset": "2099-01-01T18:00:00+00:00", "out_until": "2099-01-03T09:00:00+00:00", "in_use": True}
A3 = {"label": "Account 3", "state": "unknown", "week_left": None, "five_hour_left": None,
      "week_reset": None, "five_hour_reset": None, "next_reset": None, "out_until": None, "in_use": False}
POOL_TIGHT = {"state": "tight", "tight": True, "all_out": False, "resumes_at": None, "no_reading": None,
              "accounts": [A1, A2, A3]}


def pool_rows(snap: dict) -> list:
    return [n for n in nodes(snap["pool"]) if n["tag"] == "li" and has_class(n, "pool-account")]


def span(row: dict, cls: str) -> dict | None:
    found = [n for n in nodes(row) if has_class(n, cls)]
    return found[0] if found else None


def titles(node: dict) -> list:
    return [n["title"] for n in nodes(node) if n["tag"] == "time"]


def pool_page(pool: dict) -> dict:
    return page_of(GUEST, [START, {"frame": {**SCOPED, "pool": pool}}])


class GuestPoolTest(unittest.TestCase):
    def test_the_guest_page_draws_the_pool_line_and_each_account(self) -> None:
        snap = pool_page(POOL_TIGHT)
        self.assertIs(snap["pool"]["hidden"], False)
        rows = pool_rows(snap)
        self.assertEqual([next(n["text"] for n in nodes(r) if n["tag"] == "b") for r in rows],
                         ["Account 1", "Account 2", "Account 3"])
        self.assertIsNone(span(rows[0], "pool-status"))
        self.assertTrue(full(span(rows[0], "pool-week")).startswith("62% of the week left"))
        self.assertTrue(full(span(rows[0], "pool-session")).startswith("80% of the session left"))
        self.assertEqual(span(rows[2], "pool-status")["text"], "not in use")
        self.assertIsNone(span(rows[2], "pool-week"))
        self.assertFalse([n for n in nodes(snap["pool"]) if n["tag"] in CONTROLS])
        self.assertNotIn("@", full(snap["pool"]))
        self.assertIn("The pool is tight: one account has room.", full(snap["pool"]))

    def test_each_window_shows_its_own_figure_and_reset(self) -> None:
        a4 = {**A1, "label": "Account 4", "state": "reset", "week_left": 100, "five_hour_left": 100,
              "week_reset": None, "five_hour_reset": None, "next_reset": None}
        a5 = {**A1, "label": "Account 5", "week_left": 35, "in_use": False}
        snap = pool_page({**POOL_TIGHT, "accounts": [A2, a4, a5]})
        r2, r4, r5 = pool_rows(snap)
        self.assertTrue(full(span(r2, "pool-status")).startswith("out until"))
        self.assertEqual(titles(span(r2, "pool-status")), ["2099-01-03 09:00"])
        self.assertTrue(full(span(r2, "pool-week")).startswith("0% of the week left, resets"))
        self.assertEqual(titles(span(r2, "pool-week")), ["2099-01-03 09:00"])
        self.assertTrue(full(span(r2, "pool-session")).startswith("100% of the session left, resets"))
        self.assertEqual(titles(span(r2, "pool-session")), ["2099-01-01 18:00"])
        self.assertEqual(full(span(r4, "pool-status")), "reset, not yet used")
        self.assertEqual(full(span(r4, "pool-week")), "100% of the week left")
        self.assertEqual(full(span(r4, "pool-session")), "100% of the session left")
        self.assertEqual(titles(span(r4, "pool-week")) + titles(span(r4, "pool-session")), [])
        self.assertEqual(full(span(r5, "pool-status")), "not in use")
        self.assertTrue(full(span(r5, "pool-week")).startswith("35% of the week left, resets"))
        self.assertEqual(titles(span(r5, "pool-week")), ["2099-01-06 14:00"])

    def test_the_pool_line_takes_the_strips_state_word(self) -> None:
        rows = [A2, {**A2, "label": "Account 4"}]
        for state, cls in (("fine", "cap-fine"), ("tight", "cap-tight"), ("out", "cap-out"), (None, None)):
            with self.subTest(state=state):
                out = state == "out"
                snap = pool_page({"state": state, "tight": state == "tight", "all_out": out,
                                  "resumes_at": "2099-01-03T09:00:00+00:00" if out else None,
                                  "no_reading": None, "accounts": rows})
                words = [n for n in nodes(snap["pool"]) if has_class(n, "cap-state")]
                if cls is None:
                    self.assertEqual(words, [])
                    continue
                (word,) = words
                self.assertTrue(has_class(word, cls))
                if out:
                    self.assertIn("Every account is out until", full(snap["pool"]))

    def test_a_pool_with_no_account_in_use_says_so(self) -> None:
        excluded = {"state": None, "tight": False, "all_out": False, "resumes_at": None, "no_reading": None,
                    "accounts": [{**A1, "in_use": False}, {**A1, "label": "Account 2", "week_left": 30,
                                                           "in_use": False}]}
        waiting = {**excluded, "no_reading": "1 with no reading yet", "accounts": [{**A3, "in_use": True}]}
        first, second = pool_page(excluded), pool_page(waiting)
        for snap in (first, second):
            self.assertEqual([n for n in nodes(snap["pool"]) if has_class(n, "cap-state")], [])
        self.assertIn("No account is in use.", full(first["pool"]))
        self.assertNotIn("reading", full(first["pool"]))
        rows = pool_rows(first)
        self.assertEqual([full(span(r, "pool-status")) for r in rows], ["not in use", "not in use"])
        self.assertEqual([full(span(r, "pool-week")).split("%")[0] for r in rows], ["62", "30"])
        self.assertIn("No account in use has a reading yet.", full(second["pool"]))
        self.assertIn("1 with no reading yet", full(second["pool"]))

    def test_a_session_reset_keeps_the_week_and_a_lapsed_out_account_frees_the_line_without_a_frame(self) -> None:
        clock = 2524608000000
        b1 = {"label": "Account 1", "state": "out", "week_left": 0, "week_reset": "2050-01-01T02:00:00+00:00",
              "five_hour_left": 40, "five_hour_reset": "2050-01-01T01:00:00+00:00",
              "next_reset": "2050-01-01T01:00:00+00:00", "out_until": "2050-01-01T02:00:00+00:00",
              "in_use": True}
        b2 = {"label": "Account 2", "state": "out", "week_left": 0, "week_reset": "2050-01-05T00:00:00+00:00",
              "five_hour_left": 90, "five_hour_reset": "2050-01-01T03:00:00+00:00",
              "next_reset": "2050-01-01T03:00:00+00:00", "out_until": "2050-01-05T00:00:00+00:00",
              "in_use": True}
        pool = {"state": "out", "tight": False, "all_out": True, "resumes_at": "2050-01-01T02:00:00+00:00",
                "no_reading": None, "accounts": [b1, b2]}
        start, mid, late = harness([
            {"start": {"focused": False, "clock": clock}}, {"frame": {**SCOPED, "pool": pool}}, SNAP,
            {"clock": clock + 90 * 60000}, SNAP, {"clock": clock + 150 * 60000}, SNAP], GUEST)

        def line(snap: dict) -> list:
            return [n["cls"] for n in nodes(snap["pool"]) if has_class(n, "cap-state")]
        self.assertTrue(has_class(next(n for n in nodes(start["pool"]) if has_class(n, "cap-state")), "cap-out"))
        self.assertEqual(titles(span(pool_rows(start)[0], "pool-session")), ["2050-01-01 01:00"])
        one = pool_rows(mid)[0]
        self.assertEqual(full(span(one, "pool-session")), "100% of the session left")
        self.assertEqual(titles(span(one, "pool-session")), [])
        self.assertTrue(full(span(one, "pool-week")).startswith("0% of the week left, resets"))
        self.assertEqual(titles(span(one, "pool-week")), ["2050-01-01 02:00"])
        self.assertTrue(full(span(one, "pool-status")).startswith("out until"))
        self.assertTrue(any("cap-out" in cls for cls in line(mid)))
        one, two = pool_rows(late)
        self.assertEqual(full(span(one, "pool-status")), "reset, not yet used")
        self.assertEqual(full(span(one, "pool-week")), "100% of the week left")
        self.assertTrue(any("cap-tight" in cls for cls in line(late)))
        self.assertEqual(titles(span(two, "pool-week")), ["2050-01-05 00:00"])
        self.assertTrue(full(span(two, "pool-session")).startswith("90% of the session left"))
        self.assertEqual(titles(span(two, "pool-session")), ["2050-01-01 03:00"])

    def test_an_ok_account_whose_last_window_resets_reads_reset_without_a_frame(self) -> None:
        clock = 2524608000000
        ok = {"label": "Account 1", "state": "ok", "week_left": 40, "week_reset": "2050-01-01T02:00:00+00:00",
              "five_hour_left": 60, "five_hour_reset": "2050-01-01T01:00:00+00:00",
              "next_reset": "2050-01-01T01:00:00+00:00", "out_until": None, "in_use": True}
        pool = {"state": "fine", "tight": False, "all_out": False, "resumes_at": None,
                "no_reading": None, "accounts": [ok]}
        start, mid, late = harness([
            {"start": {"focused": False, "clock": clock}}, {"frame": {**SCOPED, "pool": pool}}, SNAP,
            {"clock": clock + 90 * 60000}, SNAP, {"clock": clock + 150 * 60000}, SNAP], GUEST)
        self.assertIsNone(span(pool_rows(start)[0], "pool-status"))
        self.assertIsNone(span(pool_rows(mid)[0], "pool-status"))
        one = pool_rows(late)[0]
        self.assertEqual(full(span(one, "pool-status")), "reset, not yet used")
        self.assertEqual(full(span(one, "pool-week")), "100% of the week left")
        self.assertEqual(full(span(one, "pool-session")), "100% of the session left")

    def test_a_session_reset_does_not_mark_an_account_unused_while_part_of_its_week_is_used(self) -> None:
        clock = 2524608000000
        ok = {"label": "Account 1", "state": "ok", "week_left": 40, "week_reset": None,
              "five_hour_left": 60, "five_hour_reset": "2050-01-01T01:00:00+00:00",
              "next_reset": "2050-01-01T01:00:00+00:00", "out_until": None, "in_use": True}
        out = {"label": "Account 2", "state": "out", "week_left": 40, "week_reset": None,
               "five_hour_left": 0, "five_hour_reset": "2050-01-01T01:00:00+00:00",
               "next_reset": "2050-01-01T01:00:00+00:00", "out_until": "2050-01-01T01:00:00+00:00",
               "in_use": True}
        pool = {"state": "fine", "tight": False, "all_out": False, "resumes_at": None,
                "no_reading": None, "accounts": [ok, out]}
        _, late = harness([
            {"start": {"focused": False, "clock": clock}}, {"frame": {**SCOPED, "pool": pool}}, SNAP,
            {"clock": clock + 90 * 60000}, SNAP], GUEST)
        for row in pool_rows(late):
            with self.subTest(row=full(row)):
                self.assertIsNone(span(row, "pool-status"))
                self.assertEqual(full(span(row, "pool-week")), "40% of the week left")
                self.assertEqual(full(span(row, "pool-session")), "100% of the session left")

    def test_the_fine_line_claims_room_only_when_an_account_in_use_has_it(self) -> None:
        unread = {**A3, "in_use": True}
        base = {"state": "fine", "tight": False, "all_out": False, "resumes_at": None,
                "no_reading": "1 with no reading yet"}
        bare = pool_page({**base, "accounts": [A2, unread]})
        roomy = pool_page({**base, "accounts": [A1, A2, unread]})
        self.assertNotIn("The pool has room.", full(bare["pool"]))
        self.assertIn("No account read so far has room.", full(bare["pool"]))
        self.assertIn("The pool has room.", full(roomy["pool"]))
        self.assertNotIn("No account read so far has room.", full(roomy["pool"]))

    def test_the_running_sprint_shows_its_account_on_the_guest_page_only(self) -> None:
        frame = with_sprints([{**SPRINT, "account_label": "Account 2"}])
        guest_page = page_of(GUEST, [START, {"frame": frame}])
        owner_page = page_of(PAGE.read_bytes(), [START, {"frame": frame}])
        marks = [n for n in nodes(guest_page["projects"]) if has_class(n, "sprint-account")]
        self.assertEqual([full(n) for n in marks], ["on Account 2"])
        self.assertEqual([n for n in nodes(owner_page["projects"]) if has_class(n, "sprint-account")], [])

    def test_the_owner_page_keeps_the_pool_hidden(self) -> None:
        snap = page_of(PAGE.read_bytes(), [START, {"frame": {**view([project(1, [])]), "pool": POOL_TIGHT}}])
        self.assertIs(snap["pool"]["hidden"], True)
        self.assertEqual(snap["pool"]["children"], [])


GUEST_CONSENT = "Your sign-in is kept on the owner's host under the owner's user, so any process the owner runs can use it."
GUEST_LOOPBACK = (
    "This sign-in can only finish on the owner's machine, so it cannot finish from here. "
    "Cancel it and tell the owner.")
GUEST_NO_LINK = "No sign-in link came yet. Press Sign in again to fetch it, or Cancel."
MANUAL_WORDS = "Sign in on that page; it then shows a code. Paste the code here and press Send code."
UNKNOWN_WORDS = (
    "The console could not tell where this sign-in returns, so a browser on another machine may not finish it.")
RUNNING_WORDS = "A sign-in is running."
FAILED_WORDS = "The sign-in did not finish."
MANUAL = "https://claude.ai/oauth/authorize?code=true&client_id=invented"
OWN_FRAME = {**SCOPED, "pool": POOL_TIGHT, "own_signin": None}
OPEN_OWN = [START, {"frame": OWN_FRAME}, {"click": "pool-add"}]
TICK = {"check": {"cls": "guest-tick", "checked": True}}
UNTICK = {"check": {"cls": "guest-tick", "checked": False}}


def attempt_reply(attempt: int, link: str | None, route: str | None) -> dict:
    return {"respond": {"status": 200, "text": json.dumps({"attempt": attempt, "link": link, "route": route})}}


def own_run(state: str, attempt: int) -> dict:
    return {**OWN_FRAME, "own_signin": {"state": state, "at": None if state == "running" else "2026-11-10T08:30:00+00:00",
                                        "attempt": attempt}}


def own_writes(snap: dict) -> list:
    return [(url, json.loads(body)) for url, body in writes(snap) if url.startswith("/api/guest-")]


def own_of(snap: dict, cls: str) -> list:
    return named(snap["own_account"], cls)


class OwnAccountPageTest(unittest.TestCase):
    def test_the_owner_page_names_the_login_beside_a_colleagues_account(self) -> None:
        cap = real_capacity(NOW_S, [
            {"name": "work", "week": .6, "five": .5, "week_reset": NOW_S + 4 * 86400, "five_reset": NOW_S + 3600},
            {"name": "colleague-1", "week": .3, "five": .4, "week_reset": NOW_S + 5 * 86400,
             "five_reset": NOW_S + 3600}])
        cap = {**cap, "profiles": [{**p, "owner": COLLEAGUE if p["profile"] == "colleague-1" else None}
                                   for p in cap["profiles"]]}
        (snap,) = harness([START, {"frame": {**view([]), "capacity": cap}}, {"click": "cap"}, SNAP], PAGE.read_bytes())
        accts = [n for n in snap["capacity"]["children"] if has_class(n, "cap-acct")]
        by_name = {next(c["text"] for c in nodes(n) if c["tag"] == "b"): n for n in accts}
        self.assertEqual([full(c) for c in named(by_name["colleague-1"], "cap-owner")], [COLLEAGUE])
        self.assertEqual(named(by_name["work"], "cap-owner"), [])
        row = next(n for n in nodes(snap["accounts_body"]) if n["tag"] == "li" and has_class(n, "acct-row")
                   and any(c["text"] == "colleague-1" for c in nodes(n)))
        self.assertEqual([full(c) for c in named(row, "acct-owner")], [COLLEAGUE])
        work = next(n for n in nodes(snap["accounts_body"]) if n["tag"] == "li" and has_class(n, "acct-row")
                    and any(c["text"] == "work" for c in nodes(n)))
        self.assertEqual(named(work, "acct-owner"), [])

    def test_the_guest_pool_reads_yours_for_his_account(self) -> None:
        snap = pool_page({**POOL_TIGHT, "accounts": [{**A1, "label": "yours"}, A2, A3]})
        rows = pool_rows(snap)
        self.assertEqual([next(n["text"] for n in nodes(r) if n["tag"] == "b") for r in rows],
                         ["yours", "Account 2", "Account 3"])
        self.assertEqual([has_class(r, "pool-yours") for r in rows], [True, False, False])
        self.assertNotIn("@", full(snap["pool"]))

    def test_sign_in_stays_disabled_until_the_tick(self) -> None:
        closed, opened, pressed, ticked, unticked = harness([
            START, {"frame": OWN_FRAME}, SNAP, {"click": "pool-add"}, SNAP, {"click": "guest-signin"}, SNAP,
            TICK, SNAP, UNTICK, SNAP], GUEST)
        self.assertEqual(own_of(closed, "guest-account"), [])
        self.assertEqual([full(n) for n in own_of(opened, "guest-consent")], [GUEST_CONSENT])
        self.assertEqual([n["disabled"] for n in own_of(opened, "guest-signin")], [True])
        self.assertEqual([n["disabled"] for n in own_of(pressed, "guest-signin")], [True])
        self.assertEqual(own_writes(pressed), [])
        self.assertEqual([n["disabled"] for n in own_of(ticked, "guest-signin")], [False])
        self.assertEqual([n["disabled"] for n in own_of(unticked, "guest-signin")], [True])
        self.assertEqual(own_writes(unticked), [])
        self.assertEqual(len(own_of(opened, "pool-add")), 1)
        self.assertEqual(named(opened["pool"], "pool-add"), [])
        self.assertEqual(len(own_of(opened, "guest-tick")), 1)
        self.assertIn("I agree", full(own_of(opened, "guest-account")[0]))

    def test_the_tick_does_not_outlive_the_form_or_the_attempt(self) -> None:
        reopened, failed, cancelled = (harness(steps, GUEST)[0] for steps in (
            [*OPEN_OWN, TICK, {"click": "pool-add"}, {"click": "pool-add"}, SNAP],
            [*OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"},
             {"frame": own_run("failed", 7)}, SNAP],
            [*OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"},
             {"respond": NO_REPLY}, {"click": "guest-cancel"}, SNAP]))
        for snap in (reopened, failed, cancelled):
            self.assertEqual(len(own_of(snap, "guest-tick")), 1)
            self.assertEqual([n["disabled"] for n in own_of(snap, "guest-signin")], [True])
        self.assertEqual(own_writes(reopened), [])

    def test_a_ticked_sign_in_posts_the_consent_and_shows_the_link_and_the_code_box(self) -> None:
        linked, done = harness([
            *OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"}, SNAP,
            {"type": {"class": "signin-code", "text": "  abc#def "}}, {"respond": NO_REPLY},
            {"click": "guest-code"}, {"respond": NO_REPLY}, {"click": "guest-cancel"}, SNAP], GUEST)
        (link,) = own_of(linked, "signin-link")
        self.assertEqual(link["href"], MANUAL)
        self.assertEqual([full(n) for n in own_of(linked, "signin-route")], [MANUAL_WORDS])
        self.assertEqual(len(own_of(linked, "signin-code")), 1)
        self.assertEqual(len(own_of(linked, "guest-cancel")), 1)
        self.assertEqual(own_writes(done), [
            ("/api/guest-account", {"consent": True}),
            ("/api/guest-signin-code", {"attempt": 7, "code": "abc#def"}),
            ("/api/guest-signin-cancel", {"attempt": 7})])
        for post in done["posts"]:
            if post["url"] != "/api/looked":
                self.assertEqual((post["method"], post["headers"]), ("POST", HEADERS))

    def test_each_route_tells_the_guest_how_to_go_on(self) -> None:
        unknown, loopback, nolink = (harness([*OPEN_OWN, TICK, attempt_reply(7, link, route),
                                              {"click": "guest-signin"}, SNAP], GUEST)[0]
                                     for link, route in ((MANUAL, "unknown"), (None, "loopback"), (None, None)))
        self.assertEqual(own_of(unknown, "signin-link")[0]["href"], MANUAL)
        self.assertEqual([full(n) for n in own_of(unknown, "signin-route")], [UNKNOWN_WORDS])
        self.assertEqual(len(own_of(unknown, "signin-code")), 1)
        self.assertEqual(len(own_of(unknown, "guest-cancel")), 1)
        self.assertEqual([full(n) for n in own_of(loopback, "guest-loopback")], [GUEST_LOOPBACK])
        self.assertEqual(len(own_of(loopback, "guest-cancel")), 1)
        self.assertEqual(own_of(loopback, "signin-link"), [])
        self.assertEqual(own_of(loopback, "signin-code"), [])
        self.assertEqual([full(n) for n in own_of(nolink, "guest-nolink")], [GUEST_NO_LINK])
        self.assertEqual([n["disabled"] for n in own_of(nolink, "guest-signin")], [False])
        self.assertEqual(len(own_of(nolink, "guest-cancel")), 1)
        again = harness([*OPEN_OWN, TICK, attempt_reply(7, None, None), {"click": "guest-signin"},
                         attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"}, SNAP], GUEST)[0]
        self.assertEqual(own_writes(again), [("/api/guest-account", {"consent": True}),
                                             ("/api/guest-account", {"consent": True, "attempt": 7})])
        self.assertEqual(own_of(again, "signin-link")[0]["href"], MANUAL)

    def test_a_refused_sign_in_shows_its_reason(self) -> None:
        (snap,) = harness([
            *OPEN_OWN, TICK, {"respond": {"status": 409, "text": "Tick that you agree before you sign in.\n"}},
            {"click": "guest-signin"}, SNAP], GUEST)
        (failed,) = own_of(snap, "signin-failed")
        self.assertTrue(full(failed).startswith("Could not start the sign-in: Tick that you agree"))
        self.assertEqual(own_of(snap, "signin-link"), [])

    def test_a_frame_while_typing_keeps_the_code_and_its_focus(self) -> None:
        (snap,) = harness([
            *OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"},
            {"type": {"class": "signin-code", "text": "abc"}}, {"frame": own_run("running", 7)}, SNAP], GUEST)
        (code,) = own_of(snap, "signin-code")
        self.assertEqual(code["value"], "abc")
        self.assertEqual(role(snap["active"]), "signin-code")

    def test_a_newer_attempt_drops_the_old_link_and_draft(self) -> None:
        (snap,) = harness([
            *OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"},
            {"type": {"class": "signin-code", "text": "abc"}}, {"frame": own_run("running", 9)}, SNAP], GUEST)
        self.assertEqual(own_of(snap, "signin-link"), [])
        self.assertEqual(own_of(snap, "signin-code"), [])
        self.assertIn(RUNNING_WORDS, full(snap["own_account"]))
        self.assertEqual(len(own_of(snap, "guest-signin")), 1)

    def test_the_attempt_that_ended_while_an_older_one_still_runs_drops_its_link_and_id(self) -> None:
        # The newer attempt (9) was shown running, then the view falls back to the older running one (7): the page
        # must not keep 9's link or submit 9 for Send code or Cancel.
        gone = harness([
            *OPEN_OWN, TICK, attempt_reply(9, MANUAL, "manual"), {"click": "guest-signin"},
            {"frame": own_run("running", 9)}, {"type": {"class": "signin-code", "text": "abc"}},
            {"frame": own_run("running", 7)}, SNAP], GUEST)[0]
        self.assertEqual(own_of(gone, "signin-link"), [])
        self.assertEqual(own_of(gone, "signin-code"), [])
        self.assertEqual(own_of(gone, "guest-cancel"), [])
        self.assertIn(RUNNING_WORDS, full(gone["own_account"]))
        self.assertEqual(own_writes(gone), [("/api/guest-account", {"consent": True})])
        # A frame that has not caught up with the attempt just answered does not drop it.
        early = harness([
            *OPEN_OWN, TICK, attempt_reply(9, MANUAL, "manual"), {"click": "guest-signin"},
            {"frame": own_run("cancelled", 7)}, SNAP], GUEST)[0]
        self.assertEqual(own_of(early, "signin-link")[0]["href"], MANUAL)
        self.assertEqual(len(own_of(early, "guest-cancel")), 1)
        # The same holds once the held attempt was shown and the frames show none of the colleague's runs.
        vanished = harness([
            *OPEN_OWN, TICK, attempt_reply(9, MANUAL, "manual"), {"click": "guest-signin"},
            {"frame": own_run("running", 9)}, {"frame": OWN_FRAME}, SNAP], GUEST)[0]
        self.assertEqual(own_of(vanished, "signin-link"), [])
        self.assertEqual(own_of(vanished, "guest-cancel"), [])

    def test_a_link_retry_sends_the_attempt_the_page_shows(self) -> None:
        (snap,) = harness([
            *OPEN_OWN, TICK, attempt_reply(7, None, None), {"click": "guest-signin"},
            attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"}, SNAP], GUEST)
        self.assertEqual(own_writes(snap), [("/api/guest-account", {"consent": True}),
                                            ("/api/guest-account", {"consent": True, "attempt": 7})])
        self.assertEqual(own_of(snap, "signin-link")[0]["href"], MANUAL)

    def test_a_sign_in_pressed_after_a_reload_names_the_attempt_the_page_shows_running(self) -> None:
        # The page was reloaded while a sign-in ran (nothing held): the press must join that attempt, so a run that
        # ended in another tab is refused by the console instead of making another account.
        (snap,) = harness([
            START, {"frame": own_run("running", 7)}, {"click": "pool-add"}, TICK,
            attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"}, SNAP], GUEST)
        self.assertEqual(own_writes(snap), [("/api/guest-account", {"consent": True, "attempt": 7})])
        self.assertEqual(own_of(snap, "signin-link")[0]["href"], MANUAL)
        (ended,) = harness([
            START, {"frame": own_run("signed_in", 7)}, {"click": "pool-add"}, TICK,
            attempt_reply(8, MANUAL, "manual"), {"click": "guest-signin"}, SNAP], GUEST)
        self.assertEqual(own_writes(ended), [("/api/guest-account", {"consent": True})])

    def test_the_run_ending_drops_the_link(self) -> None:
        (snap,) = harness([
            *OPEN_OWN, TICK, attempt_reply(7, MANUAL, "manual"), {"click": "guest-signin"},
            {"frame": own_run("failed", 7)}, SNAP], GUEST)
        self.assertEqual(own_of(snap, "signin-link"), [])
        self.assertIn(FAILED_WORDS, full(snap["own_account"]))

    def test_the_owner_page_has_no_add_your_account(self) -> None:
        (snap,) = harness([START, {"frame": {**view([project(1, [])]), "pool": POOL_TIGHT}}, {"snapshot": "page"}],
                          PAGE.read_bytes())
        self.assertEqual([n for n in nodes(snap["page"]) if has_class(n, "pool-add")], [])
