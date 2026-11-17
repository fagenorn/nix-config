"""The guest door's policy (#1237): the access list, admission, the owner-port rule and the probe.

Run: just agent-workflow-tests
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

from agent_tools.console import guest
from agent_tools.console.event_log import (
    SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET, EventLog)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TAILNET = "desk.invented-tailnet.ts.net"
OTHER_HOST = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SECOND = "second@example.invalid"
STRANGER = "stranger@example.invalid"

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
        rows = [
            (guest.NO_ACCESS, [TAILNET], [COLLEAGUE], (None, guest.SHARING_OFF_TEXT)),
            (access, [OTHER_HOST], [COLLEAGUE], (None, guest.HOST_TEXT)),
            (access, [TAILNET + ":443"], [COLLEAGUE], (None, guest.HOST_TEXT)),
            (access, [], [COLLEAGUE], (None, guest.HOST_TEXT)),
            (access, [TAILNET, TAILNET], [COLLEAGUE], (None, guest.HOST_TEXT)),
            (access, [TAILNET.upper()], [COLLEAGUE], (COLLEAGUE, None)),
            (access, [TAILNET], [], (None, guest.NOT_SHARED_TEXT)),
            (access, [TAILNET], [COLLEAGUE, COLLEAGUE], (None, guest.NOT_SHARED_TEXT)),
            (access, [TAILNET], [STRANGER], (None, guest.NOT_SHARED_TEXT)),
            (access, [TAILNET], [COLLEAGUE.upper()], (COLLEAGUE, None)),
            (access, [TAILNET], ["colleague@exämple.invalid"], (None, guest.NOT_SHARED_TEXT)),
            (access, [TAILNET], ["colleague@example.invalid x"], (None, guest.NOT_SHARED_TEXT)),
        ]
        for row_access, hosts, logins, expected in rows:
            with self.subTest(hosts=hosts, logins=logins):
                self.assertEqual(guest.admit(row_access, hosts, logins), expected)
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


class ProbeTest(unittest.TestCase):
    def test_whoami_counts_without_echoing_logins(self):
        forged = "forged-probe@example.invalid"
        result = guest.whoami([TAILNET], [COLLEAGUE, forged], ["100.64.0.1"], [forged])
        self.assertEqual(result, {"host": TAILNET, "hosts": 1, "login_headers": 2,
                                  "forwarded_for": True, "probe_login_arrived": True})
        self.assertNotIn(COLLEAGUE, json.dumps(result))
        self.assertEqual(guest.whoami([], [], [], []),
                         {"host": None, "hosts": 0, "login_headers": 0,
                          "forwarded_for": False, "probe_login_arrived": False})
        twice = guest.whoami([TAILNET], ["a@example.invalid"], [],
                             ["a@example.invalid", "a@example.invalid"])
        self.assertFalse(twice["probe_login_arrived"])


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


if __name__ == "__main__":
    unittest.main()
