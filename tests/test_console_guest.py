"""The guest door's policy (#1237): the access list, admission, the owner-port rule and the probe.

Run: just agent-workflow-tests
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

from agent_tools.console import guest, sprints, view
from agent_tools.console import capacity as capacity_module
from agent_tools.console.event_log import (
    GOAL_STATED, INBOX_SEEN, SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET,
    Event, EventLog)
from agent_tools.console.guest import Access
from agent_tools.console.sessions import SessionState
from agent_tools.console.sprints import Notice
from agent_tools.console.view import REGISTERED, derive_view, encode_view
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TAILNET = "desk.invented-tailnet.ts.net"
OTHER_HOST = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SECOND = "second@example.invalid"
STRANGER = "stranger@example.invalid"
FORGED = "forged-probe@example.invalid"

NOW = "2026-11-11T00:00:00.000000+00:00"
LONG_AGO = "2026-05-01T00:00:00.000000+00:00"


def access_rows():
    return [
        (SHARING_TAILNET, None, {"tailnet": TAILNET}),
        (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": ["owner/p01"]}),
        (SHARING_COLLEAGUE, None, {"login": SECOND, "projects": ["owner/p00", "owner/p01"]}),
        (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": ["owner/p00"]}),
        (SHARING_REMOVED, None, {"login": SECOND}),
    ]


class LogCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = NOW

    def open(self):
        log = EventLog(Path(self.tmp.name) / "console" / "events.sqlite3",
                       clock=lambda: self.now)
        self.addCleanup(log.close)
        return log


class AccessFoldTest(LogCase):
    def test_the_fold_reads_the_tailnet_and_colleagues(self):
        log = self.open()
        log.append(access_rows())
        events = log.events()
        whole = guest.access_list(events)
        halves = guest.access_list(events[3:], guest.access_list(events[:3]))
        for access in (whole, halves):
            self.assertEqual(access.tailnet, TAILNET)
            self.assertEqual(dict(access.colleagues), {COLLEAGUE: frozenset({"owner/p00"})})

    def test_a_malformed_row_fails_closed(self):
        log = self.open()
        log.append([
            (SHARING_TAILNET, None, {"tailnet": TAILNET}),
            (SHARING_TAILNET, None, {"tailnet": "Not A Name"}),
            (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": ["owner/p01"]}),
            (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": []}),
            (SHARING_COLLEAGUE, None, {"login": "Colleague@Example.invalid",
                                       "projects": ["owner/p01"]}),
        ])
        access = guest.access_list(log.events())
        self.assertIsNone(access.tailnet)
        self.assertNotIn(COLLEAGUE, access.colleagues)
        self.assertNotIn("Colleague@Example.invalid", access.colleagues)


class AdmissionTest(unittest.TestCase):
    def test_the_admission_table(self):
        access = guest.Access(TAILNET, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        local = "localhost"
        rows = [
            (access, [local], [TAILNET], [COLLEAGUE], (COLLEAGUE, None)),
            (access, ["LOCALHOST"], [TAILNET.upper()], [COLLEAGUE], (COLLEAGUE, None)),
            (access, [local], [TAILNET], [COLLEAGUE.upper()], (COLLEAGUE, None)),
            (guest.NO_ACCESS, [local], [TAILNET], [COLLEAGUE], (None, guest.SHARING_OFF_TEXT)),
        ]
        for hosts in ([TAILNET], ["localhost:80"], ["127.0.0.1"], [], [local, local]):
            rows.append((access, hosts, [TAILNET], [COLLEAGUE], (None, guest.HOST_TEXT)))
        for forwarded in ([], [TAILNET, TAILNET], [TAILNET + ":443"], [OTHER_HOST],
                          [TAILNET + ", " + OTHER_HOST]):
            rows.append((access, [local], forwarded, [COLLEAGUE], (None, guest.HOST_TEXT)))
        for logins in ([], [COLLEAGUE, COLLEAGUE], [STRANGER], ["colleague@exämple.invalid"],
                       ["colleague@example.invalid x"]):
            rows.append((access, [local], [TAILNET], logins, (None, guest.NOT_SHARED_TEXT)))
        for row_access, hosts, forwarded, logins, expected in rows:
            with self.subTest(hosts=hosts, forwarded=forwarded, logins=logins):
                self.assertEqual(guest.admit(row_access, hosts, forwarded, logins), expected)
        for text in (guest.SHARING_OFF_TEXT, guest.HOST_TEXT, guest.NOT_SHARED_TEXT):
            for secret in ("owner/p0", COLLEAGUE, STRANGER, TAILNET):
                self.assertNotIn(secret, text)


class OwnerPortTest(unittest.TestCase):
    def test_identity_and_forwarding_headers_are_refused(self):
        for names, expected in [
            (["Host", "Origin"], None),
            (["Host", "Tailscale-User-Login"], guest.OWNER_PORT_TEXT),
            (["tailscale-user-name"], guest.OWNER_PORT_TEXT),
            (["TAILSCALE-USER-PROFILE-PIC"], guest.OWNER_PORT_TEXT),
            (["Tailscale-Headers-Info"], guest.OWNER_PORT_TEXT),
            (["X-Forwarded-For"], guest.OWNER_PORT_TEXT),
            (["x-forwarded-for"], guest.OWNER_PORT_TEXT),
            (["X-Forwarded-Host"], None),
        ]:
            with self.subTest(names=names):
                self.assertEqual(guest.owner_port_refusal(names), expected)


    def test_the_refusal_names_the_guest_socket(self):
        self.assertIn("guest socket", guest.OWNER_PORT_TEXT)
        self.assertNotIn("guest port", guest.OWNER_PORT_TEXT)


class ProbeTest(unittest.TestCase):
    def test_whoami_counts_without_echoing_logins(self):
        forged = FORGED
        result = guest.whoami(["localhost"], [TAILNET], [COLLEAGUE, forged], ["100.64.0.1"],
                              [forged])
        self.assertEqual(result, {"host": "localhost", "hosts": 1, "forwarded_host": TAILNET,
                                  "forwarded_hosts": 1, "login_headers": 2,
                                  "forwarded_for": True, "probe_login_arrived": True})
        self.assertNotIn(COLLEAGUE, json.dumps(result))
        self.assertEqual(guest.whoami([], [], [], [], []),
                         {"host": None, "hosts": 0, "forwarded_host": None, "forwarded_hosts": 0,
                          "login_headers": 0, "forwarded_for": False,
                          "probe_login_arrived": False})
        twice = guest.whoami(["localhost"], [TAILNET], ["a@example.invalid"], [],
                             ["a@example.invalid", "a@example.invalid"])
        self.assertFalse(twice["probe_login_arrived"])


class ReadingTest(unittest.TestCase):
    def test_the_reading_table(self):
        access = Access(TAILNET, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        other_probe = "other-probe@example.invalid"
        loc = ["localhost"]
        rows = [
            (access, loc, [TAILNET], [COLLEAGUE], ["100.64.0.1"], [],
             {"admitted": True, "forwarded_for": True, "forwarded_host": TAILNET,
              "forwarded_host_form": "exact", "forwarded_hosts": 1, "host": "localhost",
              "host_local": True, "hosts": 1, "login_headers": 1, "login_valid": True,
              "probe": False, "probe_login_arrived": False, "reason": None}),
            (access, loc, [TAILNET + ":443"], [COLLEAGUE], [], [],
             {"admitted": False, "reason": "host", "forwarded_host_form": "with_port",
              "forwarded_host": TAILNET + ":443"}),
            (access, loc, [TAILNET.upper()], [COLLEAGUE], [], [],
             {"admitted": True, "forwarded_host_form": "exact", "forwarded_host": TAILNET.upper()}),
            (access, loc, [OTHER_HOST], [COLLEAGUE], [], [],
             {"forwarded_host_form": "other", "reason": "host", "forwarded_host": OTHER_HOST}),
            (access, loc, [], [COLLEAGUE], [], [],
             {"forwarded_hosts": 0, "forwarded_host": None, "forwarded_host_form": "none",
              "reason": "host"}),
            (access, loc, [TAILNET, TAILNET], [COLLEAGUE], [], [],
             {"forwarded_hosts": 2, "forwarded_host": None, "forwarded_host_form": "none",
              "reason": "host"}),
            (access, [TAILNET], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": False, "reason": "host", "host": TAILNET, "admitted": False}),
            (access, ["localhost", "localhost"], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": False, "hosts": 2, "host": None, "reason": "host"}),
            (access, ["LOCALHOST"], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": True, "host": "LOCALHOST", "admitted": True}),
            (access, loc, [TAILNET], [STRANGER], [], [],
             {"admitted": False, "reason": "not_shared", "login_headers": 1}),
            (access, loc, [TAILNET], [COLLEAGUE, COLLEAGUE], [], [],
             {"login_headers": 2, "reason": "not_shared"}),
            (access, loc, [TAILNET], [], [], [], {"login_headers": 0, "reason": "not_shared"}),
            (guest.NO_ACCESS, loc, [TAILNET], [COLLEAGUE], [], [],
             {"reason": "sharing_off", "forwarded_host_form": "other"}),
            (access, loc, [STRANGER], [COLLEAGUE], [], [],
             {"forwarded_host": None, "forwarded_host_form": "other"}),
            (access, loc, ["a" * 300], [COLLEAGUE], [], [], {"forwarded_host": None}),
            (access, loc, [TAILNET], [FORGED], [], [FORGED],
             {"probe": True, "probe_login_arrived": True, "reason": "not_shared"}),
            (access, loc, [TAILNET], [COLLEAGUE], ["100.64.0.1"], [FORGED],
             {"probe": True, "probe_login_arrived": False, "admitted": True}),
            (access, loc, [TAILNET], [FORGED], ["100.64.0.1"], [other_probe],
             {"probe": False, "probe_login_arrived": True}),
            (access, loc, [TAILNET], [COLLEAGUE], [], [other_probe],
             {"probe": False, "probe_login_arrived": False}),
            (access, loc, [TAILNET], [FORGED.upper()], [], [FORGED.upper()],
             {"probe": True, "probe_login_arrived": True}),
            (access, loc, [TAILNET], [COLLEAGUE], [], [FORGED, FORGED], {"probe": False}),
            (access, loc, [TAILNET], [FORGED + ", " + COLLEAGUE], ["100.64.0.1"], [FORGED],
             {"login_headers": 1, "login_valid": False, "probe": True,
              "probe_login_arrived": False, "reason": "not_shared"}),
            (access, loc, [TAILNET], [COLLEAGUE, COLLEAGUE], [], [], {"login_valid": True}),
            (access, loc, [TAILNET], [COLLEAGUE, "not a login"], [], [], {"login_valid": False}),
            (access, loc, [TAILNET], [], [], [], {"login_valid": False}),
        ]
        self.assertEqual(guest.PROBE_LOGIN, FORGED)
        for a, hosts, forwarded_hosts, logins, forwarded, probes, expected in rows:
            with self.subTest(hosts=hosts, forwarded_hosts=forwarded_hosts, logins=logins,
                              forwarded=forwarded, probes=probes):
                result = guest.reading(a, hosts, forwarded_hosts, logins, forwarded, probes)
                self.assertEqual(set(result), set(guest.READING_MEMBERS))
                if len(expected) == len(guest.READING_MEMBERS):
                    self.assertEqual(result, expected)
                for name, value in expected.items():
                    self.assertEqual(result[name], value, name)
                text = json.dumps(result).lower()
                for secret in (COLLEAGUE, STRANGER, FORGED, "other-probe"):
                    self.assertNotIn(secret, text)


class ParseTest(unittest.TestCase):
    def test_the_write_bodies_parse(self):
        self.assertEqual(
            guest.parse_tailnet(b'{"tailnet": "DESK.invented-tailnet.ts.net"}'), TAILNET)
        self.assertIsNone(guest.parse_tailnet(b'{"tailnet": null}'))
        self.assertEqual(
            guest.parse_colleague(json.dumps(
                {"login": "Colleague@Example.invalid",
                 "projects": ["owner/p01", "owner/p00"]}).encode()),
            (COLLEAGUE, ("owner/p00", "owner/p01")))
        self.assertEqual(guest.parse_removal(json.dumps({"login": COLLEAGUE}).encode()), COLLEAGUE)

    def test_a_malformed_body_is_refused(self):
        def colleague(**changes):
            return json.dumps({"login": COLLEAGUE, "projects": ["owner/p01"], **changes}).encode()

        tailnet = [b"not json", b"[]", b'{"tailnet": null, "extra": 1}',
                   b'{"tailnet": "invented-tailnet.ts.net"}',
                   b'{"tailnet": "desk.example.com"}', b'{"tailnet": 3}']
        for body in tailnet:
            with self.subTest(parser="tailnet", body=body):
                with self.assertRaises(ValueError):
                    guest.parse_tailnet(body)
        for body in [colleague(projects=[]), colleague(projects=["owner/p01", "owner/p01"]),
                     colleague(projects=[""]),
                     colleague(projects=[f"owner/p{n:02d}" for n in range(51)]),
                     colleague(login="colleague.example.invalid"),
                     colleague(login="colleague @example.invalid"),
                     colleague(extra=1)]:
            with self.subTest(parser="colleague", body=body):
                with self.assertRaises(ValueError):
                    guest.parse_colleague(body)
        for body in [b"not json", b'{"login": "colleague.example.invalid"}',
                     json.dumps({"login": COLLEAGUE, "extra": 1}).encode()]:
            with self.subTest(parser="removal", body=body):
                with self.assertRaises(ValueError):
                    guest.parse_removal(body)


class RetentionTest(LogCase):
    def test_retention_keeps_the_access_list_in_force(self):
        log = self.open()
        self.now = LONG_AGO
        log.append([
            (SHARING_TAILNET, None, {"tailnet": OTHER_HOST}),
            (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": ["owner/p01"]}),
            (SHARING_COLLEAGUE, None, {"login": SECOND, "projects": ["owner/p01"]}),
            (SHARING_TAILNET, None, {"tailnet": TAILNET}),
            (SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": ["owner/p00"]}),
            (SHARING_REMOVED, None, {"login": SECOND}),
        ])
        before = guest.access_list(log.events())
        self.now = NOW
        log.retain()
        after = guest.access_list(log.events())
        self.assertEqual(after, before)
        self.assertEqual(after.tailnet, TAILNET)
        self.assertEqual(
            [(event.kind, event.payload) for event in log.events()
             if event.kind in (SHARING_TAILNET, SHARING_COLLEAGUE, SHARING_REMOVED)],
            [(SHARING_TAILNET, {"tailnet": TAILNET}),
             (SHARING_COLLEAGUE, {"login": COLLEAGUE, "projects": ["owner/p00"]})])


def at(n):
    return f"2026-11-11T00:00:{n:02d}.000000+00:00"


def guest_inputs():
    events = [
        Event(1, at(1), REGISTERED, "owner/p00", {"root": "/srv/p00"}),
        Event(2, at(2), REGISTERED, "owner/p01", {"root": "/srv/p01"}),
        Event(3, at(3), GOAL_STATED, "owner/p00", {"sprint_id": "s-p00", "goal": "other-goal-zq7"}),
        Event(4, at(4), GOAL_STATED, "owner/p01", {"sprint_id": "s-p01", "goal": "own-goal-zq8"}),
        Event(5, at(5), INBOX_SEEN, "owner/p00", inbox_item("owner/p00", "k-p00")),
        Event(6, at(6), INBOX_SEEN, "owner/p01", inbox_item("owner/p01", "k-p01")),
    ]
    return {
        "states": view.project_states(events).values(),
        "sprints": sprints.sprint_states(events),
        "records": view.inbox_records(events),
        "sessions": [SessionState("sid-p00", "/srv/p00", "/srv/p00", "idle", None, 7, at(7), None),
                     SessionState("sid-p01", "/srv/p01", "/srv/p01", "idle", None, 8, at(8), None),
                     SessionState("sid-x", "/srv/unregistered-zq9", "/srv/unregistered-zq9",
                                  "idle", None, 9, at(9), None)],
        "owner_notices": {"owner/p00": (Notice(1, at(10), "heads-up", "other-notice-zq6"),)},
        "now_ms": 1_000,
    }


def inbox_item(project_id, key):
    return {"key": key, "project_id": project_id, "repo": project_id, "issue": 7,
            "comment_id": 11, "url": f"https://example.test/{key}",
            "reason": "question", "question": "Which one?", "questions": [],
            "items": [], "answered": False, "held_work": 1}


class ScopeTest(unittest.TestCase):
    def test_scoped_inputs_keep_only_the_guest_projects(self):
        inputs = guest_inputs()
        everything = encode_view(derive_view(**inputs))
        for marker in (b"owner/p00", b"/srv/p00", b"other-goal-zq7", b"other-notice-zq6",
                       b"unregistered-zq9"):
            self.assertIn(marker, everything)
        kept = guest.scoped(inputs, frozenset({"owner/p01"}))
        self.assertEqual([session.session_id for session in kept["sessions"]], ["sid-p01"])
        self.assertEqual([state.project_id for state in kept["states"]], ["owner/p01"])
        self.assertEqual(kept["owner_notices"], {})
        scoped = encode_view(guest.scrub(derive_view(**kept)))
        for marker in (b"owner/p00", b"/srv/p00", b"other-goal-zq7", b"other-notice-zq6",
                       b"unregistered-zq9"):
            self.assertNotIn(marker, scoped)
        for marker in (b"own-goal-zq8", b"owner/p01"):
            self.assertIn(marker, scoped)

    def test_owner_only_inputs_are_reset(self):
        result = guest.scoped({name: object() for name in guest.OWNER_ONLY_INPUTS},
                              frozenset())
        for name, reset in guest.OWNER_ONLY_INPUTS.items():
            with self.subTest(name=name):
                self.assertEqual(result[name], reset)

    def test_an_unclassified_input_is_refused(self):
        with self.assertRaisesRegex(ValueError, "new_member"):
            guest.scoped({"now_ms": 1, "new_member": 2}, frozenset())

    def test_scrub_removes_the_owner_members(self):
        access = Access(TAILNET, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        owner_view = derive_view([], sharing=guest.sharing_entry(access, "serving"))
        owner_view["spend"] = {"x": 1}
        owner_view["unmanaged"] = [{"root": "/srv/x"}]
        owner_view["profile_sessions"] = {"work": 1}
        result = guest.scrub(owner_view)
        self.assertNotIn("sharing", result)
        resets = {"unmanaged": [], "profile_sessions": {}, "signin_runs": {},
                  "accounts_added": [], "pin": None, "pin_launches": [], "registration": None,
                  "digest": None, "activation": None, "spend": None,
                  "capacity": dict(capacity_module.EMPTY)}
        for name, reset in resets.items():
            with self.subTest(name=name):
                self.assertEqual(result[name], reset)
        encoded = encode_view(result)
        for secret in (COLLEAGUE.encode(), TAILNET.encode()):
            self.assertNotIn(secret, encoded)

    def test_picture_ids_walk_every_pictures_list(self):
        walked = {"inbox": {"open": [{"pictures": [{"id": "a"}, {"id": "b"}]}]},
                  "entries": [{"sprints": [{"pictures": [{"id": "c"}]}]}],
                  "other": [{"id": "not-a-picture"}]}
        self.assertEqual(guest.picture_ids(walked), frozenset({"a", "b", "c"}))


class DoorTest(unittest.TestCase):
    def test_the_door_refusal_table(self):
        def st(mode, uid):
            return os.stat_result((mode, 1, 1, 1, uid, 0, 0, 0, 0, 0))

        D, S = stat.S_IFDIR, stat.S_IFSOCK
        good_folder, good_sock = st(D | 0o700, 501), st(S | 0o600, 501)
        rows = [
            (good_folder, good_sock, None),
            (st(D | 0o500, 501), st(S | 0o400, 501), None),
            (st(D | 0o750, 501), good_sock, guest.DOOR_WIDER),
            (st(D | 0o701, 501), good_sock, guest.DOOR_WIDER),
            (st(D | 0o1700, 501), good_sock, guest.DOOR_WIDER),
            (st(D | 0o700, 502), good_sock, guest.DOOR_WIDER),
            (st(stat.S_IFLNK | 0o700, 501), good_sock, guest.DOOR_WIDER),
            (good_folder, st(S | 0o660, 501), guest.DOOR_WIDER),
            (good_folder, st(S | 0o602, 501), guest.DOOR_WIDER),
            (good_folder, st(S | 0o700, 501), guest.DOOR_WIDER),
            (good_folder, st(S | 0o4600, 501), guest.DOOR_WIDER),
            (good_folder, st(S | 0o600, 502), guest.DOOR_WIDER),
            (good_folder, st(stat.S_IFREG | 0o600, 501), guest.DOOR_WIDER),
            (None, good_sock, guest.DOOR_WIDER),
            (good_folder, None, guest.DOOR_WIDER),
        ]
        for folder, sock, expected in rows:
            with self.subTest(folder=folder, sock=sock):
                self.assertEqual(guest.door_refusal(folder, sock, 501), expected)
        self.assertEqual((guest.FOLDER_MODE, guest.SOCKET_MODE), (0o700, 0o600))
        self.assertEqual(guest.DOOR_WIDER, "door_wider")


class AclTest(unittest.TestCase):
    """macOS keeps an ACL beside the mode bits, so a 0700 folder can still grant another account."""

    def test_the_acl_reader_exists_only_where_an_acl_outranks_the_mode(self):
        self.assertIs(guest.acl_reader_for("darwin"), guest.acl_grants)
        self.assertIsNone(guest.acl_reader_for("linux"))
        self.assertIsNone(guest.acl_reader_for("freebsd13"))

    @unittest.skipUnless(sys.platform == "darwin", "ACLs outside the mode bits are macOS's")
    def test_acl_grants_reads_an_allow_entry_not_a_deny_one(self):
        root = Path(tempfile.mkdtemp(prefix="acl-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, root, True)
        rows = [(None, False), ("everyone deny delete", False),
                ("everyone allow list,search", True)]
        for number, (entry, grants) in enumerate(rows):
            with self.subTest(entry=entry):
                target = root / f"d{number}"
                target.mkdir(mode=0o700)
                if entry is not None:
                    subprocess.run(["/bin/chmod", "+a", entry, str(target)], check=True)
                    self.addCleanup(subprocess.run, ["/bin/chmod", "-N", str(target)])
                self.assertIs(guest.acl_grants(str(target)), grants)


class SharingTest(unittest.TestCase):
    def test_serve_state_table(self):
        SOCK = "/s/guest/guest.sock"

        def serving(key=f"{TAILNET}:443", proxy=f"unix:{SOCK}"):
            return {"Web": {key: {"Handlers": {"/": {"Proxy": proxy}}}}}

        rows = [
            (None, None, SOCK, "off"),
            ({"Web": {}}, None, SOCK, "off"),
            (None, TAILNET, SOCK, "unchecked"),
            ({}, TAILNET, SOCK, "not_proxying"),
            (serving(), TAILNET, SOCK, "serving"),
            (serving(proxy="unix:/s/other.sock"), TAILNET, SOCK, "not_proxying"),
            (serving(proxy=f"unix:{SOCK}/"), TAILNET, SOCK, "not_proxying"),
            (serving(proxy="http://127.0.0.1:27185"), TAILNET, SOCK, "not_proxying"),
            (serving(proxy="http://localhost:27185"), TAILNET, SOCK, "not_proxying"),
            (serving(key=f"{TAILNET}:8443"), TAILNET, SOCK, "not_proxying"),
            (serving(key=f"{OTHER_HOST}:443"), TAILNET, SOCK, "not_proxying"),
            ({"Web": []}, TAILNET, SOCK, "not_proxying"),
            (serving(), TAILNET, None, "not_proxying"),
            (serving(proxy="unix:"), TAILNET, "", "not_proxying"),
        ]
        for status, tailnet, sock, expected in rows:
            with self.subTest(status=status, tailnet=tailnet, sock=sock):
                self.assertEqual(guest.serve_state(status, tailnet, sock), expected)

    def test_the_view_carries_the_sharing_entry(self):
        self.assertEqual(derive_view([])["sharing"], view.SHARING_OFF)
        self.assertEqual(guest.sharing_entry(guest.NO_ACCESS, "off"), view.SHARING_OFF)
        access = Access(TAILNET, MappingProxyType({
            SECOND: frozenset({"owner/p01", "owner/p00"}), COLLEAGUE: frozenset({"owner/p01"})}))
        entry = guest.sharing_entry(access, "serving", socket="/s/g.sock")
        self.assertEqual(entry, {"tailnet": TAILNET, "colleagues": [
            {"login": COLLEAGUE, "projects": ["owner/p01"]},
            {"login": SECOND, "projects": ["owner/p00", "owner/p01"]}], "state": "serving",
            "last_request": None, "socket": "/s/g.sock"})
        self.assertIsNone(view.SHARING_OFF["socket"])
        self.assertEqual(derive_view([], sharing=entry)["sharing"], entry)
        r = guest.reading(access, ["localhost"], [TAILNET], [COLLEAGUE], [], [])
        entry = guest.sharing_entry(access, "serving", r)
        self.assertEqual(entry["last_request"], r)
        self.assertEqual(derive_view([], sharing=entry)["sharing"]["last_request"], r)
        derive_view([], sharing=entry)["sharing"]["last_request"]["host"] = "x"
        self.assertEqual(r["host"], "localhost")
        self.assertIsNone(view.SHARING_OFF["last_request"])
        derive_view([])["sharing"]["colleagues"].append("x")
        self.assertEqual(view.SHARING_OFF["colleagues"], [])


if __name__ == "__main__":
    unittest.main()
