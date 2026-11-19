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
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_guest import guest_inputs
from .test_console_page import (
    ACTIVATION, CHECK, CHECK_ITEM, F3, HANDOFF_W, HARNESS, HEADSUP_W, OWNER_W, PAGE, REPORTED, SPRINT, START,
    UNDATED_WAIT,
    box_open, full, has_class, message_entry, nodes, project, role, view, with_check, with_notices,
    with_sprints)

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


def sharing_frame(state: str, tailnet: str | None, last_request: dict | None, shared: bool = True) -> dict:
    return {**SHARED_FRAME, "sharing": guest.sharing_entry(
        guest.Access(shared, ACCESS.colleagues), tailnet, state, last_request)}


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
             last + f"Host localhost, forwarded Host {TAILNET}, a login header, "
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
                       "sharing_body", "sharing_open", "goal", "register", "unmanaged", "digest", "promoted"):
            self.assertIsNone(snap[member], member)
        shown = [n for child in snap["page"]["children"] if child != snap["viewer"] for n in nodes(child)]
        roles = {role(n["cls"]) for n in shown if n["cls"]}
        for banned in ("activation", "ask-open", "ask-box", "ask-text", "register-open", "sprint-acts", "sprint-more"):
            self.assertNotIn(banned, roles)
        self.assertLessEqual({role(n["cls"]) for n in shown if n["tag"] in CONTROLS and n["cls"]},
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
        self.assertEqual(who["text"], "The owner's console, shared with you to read")
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
