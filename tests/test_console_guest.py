"""The guest door's policy (#1237): the access list, admission, the owner-port rule and the probe.

Run: just agent-workflow-tests
"""

import copy
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
from agent_tools.console.guest import Access, GuestActor
from agent_tools.console.sessions import SessionState
from agent_tools.console.sprints import Notice
from agent_tools.console.view import REGISTERED, derive_view, encode_view
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TAILNET = "desk.invented-tailnet.ts.net"
OTHER_HOST = "other.invented-tailnet.ts.net"
SELF = {"Self": {"DNSName": "DESK.invented-tailnet.ts.net."}}
COLLEAGUE = "colleague@example.invalid"
SECOND = "second@example.invalid"
STRANGER = "stranger@example.invalid"
FORGED = "forged-probe@example.invalid"
SELF_V4 = "100.64.0.10"
SELF_V6 = "fd7a:115c:a1e0::a"
OTHER_DEVICE_ADDRESS = "100.64.0.20"
OWN = {"Self": {"DNSName": TAILNET + ".", "TailscaleIPs": [SELF_V4, SELF_V6]}}

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
            self.assertIs(access.shared, True)
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
        self.assertIs(access.shared, False)
        self.assertNotIn(COLLEAGUE, access.colleagues)
        self.assertNotIn("Colleague@Example.invalid", access.colleagues)


    def test_a_stored_name_only_turns_sharing_on(self):
        rows = [({"tailnet": OTHER_HOST}, True), ({"tailnet": None}, False),
                ({"shared": True}, True), ({"shared": False}, False),
                ({"shared": False, "tailnet": TAILNET}, False), ({"shared": 1}, False),
                ({"shared": "yes"}, False), ({"tailnet": "Not A Name"}, False), ([], False)]
        for payload, expected in rows:
            with self.subTest(payload=payload):
                access = guest.access_list([Event(1, NOW, SHARING_TAILNET, None, payload)])
                self.assertIs(access.shared, expected)
                self.assertFalse(hasattr(access, "tailnet"))


class SelfNameTest(unittest.TestCase):
    def test_the_self_name_table(self):
        rows = [(SELF, TAILNET), ({"Self": {"DNSName": TAILNET}}, TAILNET),
                (None, None), ([], None), ({}, None), ({"Self": None}, None),
                ({"Self": {}}, None), ({"Self": {"DNSName": ""}}, None),
                ({"Self": {"DNSName": 3}}, None),
                ({"Self": {"DNSName": "desk.example.com."}}, None),
                ({"Self": {"DNSName": "invented-tailnet.ts.net."}}, None),
                ({"Self": {"DNSName": TAILNET + ".."}}, None),
                ({"Self": {"DNSName": "a.b." + TAILNET + "."}}, None),
                ({"Self": {"DNSName": "extra." + TAILNET}}, None),
                ({"Self": {"DNSName": "DES\u212a.invented-tailnet.ts.net."}}, None),
                ({"Peer": {"x": {"DNSName": TAILNET + "."}}}, None)]
        for status, expected in rows:
            with self.subTest(status=status):
                self.assertEqual(guest.self_name(status), expected)

    def test_the_status_reader_runs_the_status_command(self):
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout='{"Self": {}}', stderr="")

        self.assertEqual(guest.status_reader("/x/bin/tailscale", run=run)(), {"Self": {}})
        args, kwargs = calls[0]
        self.assertEqual(args, ["/x/bin/tailscale", "status", "--json"])
        self.assertEqual(kwargs["timeout"], 15.0)
        self.assertNotIn("shell", kwargs)

        def failing(error):
            def run(args, **kwargs):
                raise error
            return run

        rows = (
            ("a nonzero exit", lambda args, **kw: subprocess.CompletedProcess(
                args, 1, stdout='{"Self": {}}', stderr="")),
            ("unparsable output", lambda args, **kw: subprocess.CompletedProcess(
                args, 0, stdout="not json", stderr="")),
            ("an OSError", failing(OSError("no such file"))),
            ("a timeout", failing(subprocess.TimeoutExpired("x", 15))),
        )
        for name, row in rows:
            with self.subTest(row=name):
                self.assertIsNone(guest.status_reader("/x/bin/tailscale", run=row)())


class AdmissionTest(unittest.TestCase):
    def test_the_admission_table(self):
        access = guest.Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        local = "localhost"
        rows = [
            (access, TAILNET, [local], [TAILNET], [COLLEAGUE], (COLLEAGUE, None)),
            (access, TAILNET, ["LOCALHOST"], [TAILNET.upper()], [COLLEAGUE], (COLLEAGUE, None)),
            (access, TAILNET, [local], [TAILNET], [COLLEAGUE.upper()], (COLLEAGUE, None)),
            (guest.NO_ACCESS, TAILNET, [local], [TAILNET], [COLLEAGUE],
             (None, guest.SHARING_OFF_TEXT)),
            (guest.NO_ACCESS, None, [local], [TAILNET], [COLLEAGUE],
             (None, guest.SHARING_OFF_TEXT)),
            (access, None, [local], [TAILNET], [COLLEAGUE], (None, guest.NAME_UNREAD_TEXT)),
            (access, TAILNET, [local], [OTHER_HOST], [COLLEAGUE], (None, guest.HOST_TEXT)),
            (access, OTHER_HOST, [local], [TAILNET], [COLLEAGUE], (None, guest.HOST_TEXT)),
        ]
        for hosts in ([TAILNET], ["localhost:80"], ["127.0.0.1"], [], [local, local]):
            rows.append((access, TAILNET, hosts, [TAILNET], [COLLEAGUE], (None, guest.HOST_TEXT)))
        for forwarded in ([], [TAILNET, TAILNET], [TAILNET + ":443"], [OTHER_HOST],
                          [TAILNET + ", " + OTHER_HOST]):
            rows.append((access, TAILNET, [local], forwarded, [COLLEAGUE],
                         (None, guest.HOST_TEXT)))
        for logins in ([], [COLLEAGUE, COLLEAGUE], [STRANGER], ["colleague@exämple.invalid"],
                       ["colleague@example.invalid x"]):
            rows.append((access, TAILNET, [local], [TAILNET], logins,
                         (None, guest.NOT_SHARED_TEXT)))
        for row_access, name, hosts, forwarded, logins, expected in rows:
            with self.subTest(name=name, hosts=hosts, forwarded=forwarded, logins=logins):
                self.assertEqual(guest.admit(row_access, name, hosts, forwarded, logins), expected)
        self.assertEqual(guest.REASON_CODES[guest.NAME_UNREAD_TEXT], "name_unread")
        for text in (guest.SHARING_OFF_TEXT, guest.NAME_UNREAD_TEXT, guest.HOST_TEXT,
                     guest.NOT_SHARED_TEXT):
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
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        other_probe = "other-probe@example.invalid"
        loc = ["localhost"]
        rows = [
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE], ["100.64.0.1"], [],
             {"admitted": True, "forwarded_for": True, "forwarded_host": TAILNET,
              "forwarded_host_form": "exact", "forwarded_hosts": 1, "host": "localhost",
              "host_local": True, "hosts": 1, "login_headers": 1, "login_valid": True,
              "probe": False, "probe_login_arrived": False, "reason": None, "client": "unknown"}),
            (access, TAILNET, loc, [TAILNET + ":443"], [COLLEAGUE], [], [],
             {"admitted": False, "reason": "host", "forwarded_host_form": "with_port",
              "forwarded_host": TAILNET + ":443"}),
            (access, TAILNET, loc, [TAILNET.upper()], [COLLEAGUE], [], [],
             {"admitted": True, "forwarded_host_form": "exact", "forwarded_host": TAILNET.upper()}),
            (access, TAILNET, loc, [OTHER_HOST], [COLLEAGUE], [], [],
             {"forwarded_host_form": "other", "reason": "host", "forwarded_host": None}),
            (access, TAILNET, loc, [], [COLLEAGUE], [], [],
             {"forwarded_hosts": 0, "forwarded_host": None, "forwarded_host_form": "none",
              "reason": "host"}),
            (access, TAILNET, loc, [TAILNET, TAILNET], [COLLEAGUE], [], [],
             {"forwarded_hosts": 2, "forwarded_host": None, "forwarded_host_form": "none",
              "reason": "host"}),
            (access, TAILNET, [TAILNET], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": False, "reason": "host", "host": TAILNET, "admitted": False}),
            (access, TAILNET, ["localhost", "localhost"], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": False, "hosts": 2, "host": None, "reason": "host"}),
            (access, TAILNET, ["LOCALHOST"], [TAILNET], [COLLEAGUE], [], [],
             {"host_local": True, "host": "LOCALHOST", "admitted": True}),
            (access, TAILNET, loc, [TAILNET], [STRANGER], [], [],
             {"admitted": False, "reason": "not_shared", "login_headers": 1}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE, COLLEAGUE], [], [],
             {"login_headers": 2, "reason": "not_shared"}),
            (access, TAILNET, loc, [TAILNET], [], [], [], {"login_headers": 0, "reason": "not_shared"}),
            (guest.NO_ACCESS, None, loc, [TAILNET], [COLLEAGUE], [], [],
             {"reason": "sharing_off", "forwarded_host_form": "other"}),
            (access, None, loc, [TAILNET], [COLLEAGUE], [], [],
             {"admitted": False, "reason": "name_unread", "forwarded_host_form": "other"}),
            (access, TAILNET, loc, [STRANGER], [COLLEAGUE], [], [],
             {"forwarded_host": None, "forwarded_host_form": "other"}),
            (access, TAILNET, loc, ["a" * 300], [COLLEAGUE], [], [], {"forwarded_host": None}),
            (access, TAILNET, loc, [TAILNET], [FORGED], [], [FORGED],
             {"probe": True, "probe_login_arrived": True, "reason": "not_shared"}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE], ["100.64.0.1"], [FORGED],
             {"probe": True, "probe_login_arrived": False, "admitted": True}),
            (access, TAILNET, loc, [TAILNET], [FORGED], ["100.64.0.1"], [other_probe],
             {"probe": False, "probe_login_arrived": True}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE], [], [other_probe],
             {"probe": False, "probe_login_arrived": False}),
            (access, TAILNET, loc, [TAILNET], [FORGED.upper()], [], [FORGED.upper()],
             {"probe": True, "probe_login_arrived": True}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE], [], [FORGED, FORGED], {"probe": False}),
            (access, TAILNET, loc, [TAILNET], [FORGED + ", " + COLLEAGUE], ["100.64.0.1"], [FORGED],
             {"login_headers": 1, "login_valid": False, "probe": True,
              "probe_login_arrived": False, "reason": "not_shared"}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE, COLLEAGUE], [], [], {"login_valid": True}),
            (access, TAILNET, loc, [TAILNET], [COLLEAGUE, "not a login"], [], [], {"login_valid": False}),
            (access, TAILNET, loc, [TAILNET], [], [], [], {"login_valid": False}),
        ]
        self.assertEqual(guest.PROBE_LOGIN, FORGED)
        for a, name, hosts, forwarded_hosts, logins, forwarded, probes, expected in rows:
            with self.subTest(name=name, hosts=hosts, forwarded_hosts=forwarded_hosts, logins=logins,
                              forwarded=forwarded, probes=probes):
                result = guest.reading(a, name, hosts, forwarded_hosts, logins, forwarded, probes)
                self.assertEqual(set(result), set(guest.READING_MEMBERS))
                if len(expected) == len(guest.READING_MEMBERS):
                    self.assertEqual(result, expected)
                for name, value in expected.items():
                    self.assertEqual(result[name], value, name)
                text = json.dumps(result).lower()
                for secret in (COLLEAGUE, STRANGER, FORGED, "other-probe"):
                    self.assertNotIn(secret, text)


class ClientTest(unittest.TestCase):
    def test_the_own_addresses_table(self):
        rows = [
            (OWN, {SELF_V4, SELF_V6}),
            ({"Self": {"TailscaleIPs": ["::ffff:100.64.0.10"]}}, {SELF_V4}),
            (None, set()),
            ({}, set()),
            ({"Self": None}, set()),
            ({"Self": {}}, set()),
            ({"Self": {"TailscaleIPs": []}}, set()),
            ({"Self": {"TailscaleIPs": SELF_V4}}, set()),
            ({"Self": {"TailscaleIPs": [SELF_V4, 7]}}, set()),
            ({"Self": {"TailscaleIPs": [SELF_V4, "not-an-address"]}}, set()),
            ({"Self": {"TailscaleIPs": ["100.064.0.10"]}}, set()),
            ({"Self": {"TailscaleIPs": [SELF_V4, "fd7a:115c:a1e0::a%eth0"]}}, set()),
        ]
        for status, expected in rows:
            with self.subTest(status=status):
                self.assertEqual({str(a) for a in guest.own_addresses(status)}, expected)

    def test_the_client_table(self):
        own = guest.own_addresses(OWN)
        rows = [
            ([SELF_V4], own, "this_host"),
            ([" 100.64.0.10 "], own, "this_host"),
            (["\t100.64.0.10\t"], own, "this_host"),
            (["\u00a0100.64.0.20\u00a0"], own, "unknown"),
            (["\u00a0100.64.0.10"], own, "unknown"),
            (["100.64.0.20\u2003"], own, "unknown"),
            (["100.64.0.20\n"], own, "unknown"),
            (["FD7A:115C:A1E0:0:0:0:0:A"], own, "this_host"),
            (["::ffff:100.64.0.10"], own, "this_host"),
            ([OTHER_DEVICE_ADDRESS], own, "other_device"),
            (["fd7a:115c:a1e0::14"], own, "other_device"),
            ([], own, "unknown"),
            ([SELF_V4, OTHER_DEVICE_ADDRESS], own, "unknown"),
            (["100.64.0.20, 100.64.0.10"], own, "unknown"),
            (["not-an-address"], own, "unknown"),
            ([""], own, "unknown"),
            (["fd7a:115c:a1e0::a%eth0"], own, "unknown"),
            (["::ffff:100.64.0.10%1"], own, "unknown"),
            ([OTHER_DEVICE_ADDRESS], frozenset(), "unknown"),
            ([SELF_V4], frozenset(), "unknown"),
        ]
        self.assertEqual(guest.CLIENT_FORMS, ("this_host", "other_device", "unknown"))
        for forwarded, addresses, expected in rows:
            with self.subTest(forwarded=forwarded, own=bool(addresses)):
                self.assertEqual(guest.client_of(forwarded, addresses), expected)

    def test_the_reading_never_keeps_an_address_as_a_host(self):
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        for value in (OTHER_DEVICE_ADDRESS, OTHER_DEVICE_ADDRESS + ":443", SELF_V4 + ":8", "0100.064.0.5",
                      "1684300805", "0x64000005", "0x64.0.0.5:443", OTHER_DEVICE_ADDRESS + ".",
                      OTHER_DEVICE_ADDRESS + ".:443", "1684300805.", "0x64000005.:8", "100.64.0.5.."):
            with self.subTest(value=value):
                r = guest.reading(access, TAILNET, [value], [value], [COLLEAGUE], [], [])
                self.assertEqual((r["host"], r["forwarded_host"]), (None, None))
                self.assertEqual(r["host_local"], False)
                text = json.dumps(r)
                for part in ("100.64", "1684300805", "0x64"):
                    self.assertNotIn(part, text)
        for host, forwarded in (("localhost", TAILNET), ("LocalHost", TAILNET.upper()),
                                (TAILNET, TAILNET + ":443"), (TAILNET + ":443", "localhost")):
            with self.subTest(host=host, forwarded=forwarded):
                r = guest.reading(access, TAILNET, [host], [forwarded], [COLLEAGUE], [], [])
                self.assertEqual((r["host"], r["forwarded_host"]), (host, forwarded))
        for value in (OTHER_HOST, OTHER_HOST + ":443", "v4.example", "a1.b2.example:8", TAILNET + ":8"):
            with self.subTest(value=value):
                r = guest.reading(access, TAILNET, [value], [value], [COLLEAGUE], [], [])
                self.assertEqual((r["host"], r["forwarded_host"]), (None, None))

    def test_a_host_carrying_the_clients_address_is_not_kept(self):
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        own = guest.own_addresses(OWN)
        for address, forwarded in ((OTHER_DEVICE_ADDRESS, [OTHER_DEVICE_ADDRESS]),
                                   (OTHER_DEVICE_ADDRESS, [" " + OTHER_DEVICE_ADDRESS + "\t"]),
                                   (OTHER_DEVICE_ADDRESS, ["::ffff:" + OTHER_DEVICE_ADDRESS]),
                                   (OTHER_DEVICE_ADDRESS, [SELF_V4 + ", " + OTHER_DEVICE_ADDRESS]),
                                   (SELF_V4, [SELF_V4])):
            for value in (address + ".example.invalid", "A." + address + ".example",
                          address + ".example.invalid:443"):
                with self.subTest(forwarded=forwarded, value=value):
                    r = guest.reading(access, TAILNET, [value], [value], [COLLEAGUE], forwarded, [],
                                      own=own)
                    self.assertEqual((r["host"], r["forwarded_host"]), (None, None))
                    text = json.dumps(r)
                    for part in ("100.64", "example.invalid"):
                        self.assertNotIn(part, text)
        r = guest.reading(access, TAILNET, ["localhost"], [TAILNET], [COLLEAGUE],
                          [OTHER_DEVICE_ADDRESS], [], own=own)
        self.assertEqual((r["host"], r["forwarded_host"]), ("localhost", TAILNET))

    def test_a_host_spelling_the_clients_address_in_any_encoding_is_not_kept(self):
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        own = guest.own_addresses(OWN)
        client = OTHER_DEVICE_ADDRESS  # 100.64.0.20
        for value in ("app-64400014.example.invalid", "magic-c0a80101.nip.io",
                      "100-064-000-020.example.invalid", "app.1681915924.example.invalid",
                      "fd7a-115c-a1e0-0-0-0-0-a.example.invalid", "100-64-0-20.example.invalid",
                      "0x64400014.example.invalid", "x.0144.0100.0.0024.example.invalid"):
            for host, forwarded in ((value, value), ("localhost", value), (value, TAILNET)):
                with self.subTest(value=value, host=host, forwarded=forwarded):
                    r = guest.reading(access, TAILNET, [host], [forwarded], [COLLEAGUE], [client], [],
                                      own=own)
                    self.assertEqual(r["host"], "localhost" if host == "localhost" else None)
                    self.assertEqual(r["forwarded_host"], TAILNET if forwarded == TAILNET else None)
                    self.assertNotIn(value, json.dumps(r))

    def test_the_reading_keeps_only_the_comparison(self):
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        own = guest.own_addresses(OWN)
        for forwarded, expected in (([SELF_V4], "this_host"), ([OTHER_DEVICE_ADDRESS], "other_device"),
                                    ([], "unknown")):
            with self.subTest(forwarded=forwarded):
                r = guest.reading(access, TAILNET, ["localhost"], [TAILNET], [COLLEAGUE],
                                  forwarded, [], own=own)
                self.assertEqual(r["client"], expected)
                self.assertEqual(set(r), set(guest.READING_MEMBERS))
                self.assertIn("client", guest.READING_MEMBERS)
                self.assertEqual(guest.READING_MEMBERS, tuple(sorted(guest.READING_MEMBERS)))
                text = json.dumps(r)
                for value in (SELF_V4, SELF_V6, OTHER_DEVICE_ADDRESS, "100.64"):
                    self.assertNotIn(value, text)


class ParseTest(unittest.TestCase):
    def test_the_write_bodies_parse(self):
        self.assertIs(guest.parse_sharing(b'{"shared": true}'), True)
        self.assertIs(guest.parse_sharing(b'{"shared": false}'), False)
        self.assertEqual(
            guest.parse_colleague(json.dumps(
                {"login": "Colleague@Example.invalid",
                 "projects": ["owner/p01", "owner/p00"]}).encode()),
            (COLLEAGUE, ("owner/p00", "owner/p01")))
        self.assertEqual(guest.parse_removal(json.dumps({"login": COLLEAGUE}).encode()), COLLEAGUE)

    def test_a_malformed_body_is_refused(self):
        def colleague(**changes):
            return json.dumps({"login": COLLEAGUE, "projects": ["owner/p01"], **changes}).encode()

        sharing = [b'{"tailnet": "desk.invented-tailnet.ts.net"}', b'{"tailnet": null}',
                   b'{"shared": true, "tailnet": "desk.invented-tailnet.ts.net"}',
                   b'{"shared": 1}', b'{"shared": "true"}', b'{"shared": null}',
                   b'{"shared": true, "shared": false}', b"[]", b"not json"]
        for body in sharing:
            with self.subTest(parser="sharing", body=body):
                with self.assertRaises(ValueError):
                    guest.parse_sharing(body)
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
        self.assertIs(after.shared, True)
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
        access = Access(True, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        owner_view = derive_view([], sharing=guest.sharing_entry(access, TAILNET, "serving"))
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
            (True, None, None, SOCK, "unreadable"),
            (True, None, serving(), SOCK, "unreadable"),
            (False, TAILNET, serving(), SOCK, "off"),
            (False, None, None, SOCK, "off"),
            (True, TAILNET, None, SOCK, "unchecked"),
            (True, TAILNET, {}, SOCK, "not_proxying"),
            (True, TAILNET, serving(), SOCK, "serving"),
            (True, TAILNET, serving(proxy="unix:/s/other.sock"), SOCK, "not_proxying"),
            (True, TAILNET, serving(proxy=f"unix:{SOCK}/"), SOCK, "not_proxying"),
            (True, TAILNET, serving(proxy="http://127.0.0.1:27185"), SOCK, "not_proxying"),
            (True, TAILNET, serving(proxy="http://localhost:27185"), SOCK, "not_proxying"),
            (True, TAILNET, serving(key=f"{TAILNET}:8443"), SOCK, "not_proxying"),
            (True, TAILNET, serving(key=f"{OTHER_HOST}:443"), SOCK, "not_proxying"),
            (True, TAILNET, {"Web": []}, SOCK, "not_proxying"),
            (True, TAILNET, serving(), None, "not_proxying"),
            (True, TAILNET, serving(proxy="unix:"), "", "not_proxying"),
        ]
        for shared, name, status, sock, expected in rows:
            with self.subTest(shared=shared, name=name, status=status, sock=sock):
                self.assertEqual(guest.serve_state(shared, name, status, sock), expected)

    def test_the_view_carries_the_sharing_entry(self):
        self.assertEqual(derive_view([])["sharing"], view.SHARING_OFF)
        self.assertEqual(guest.sharing_entry(guest.NO_ACCESS, None, "off"), view.SHARING_OFF)
        access = Access(True, MappingProxyType({
            SECOND: frozenset({"owner/p01", "owner/p00"}), COLLEAGUE: frozenset({"owner/p01"})}))
        entry = guest.sharing_entry(access, TAILNET, "serving", socket="/s/g.sock")
        self.assertEqual(entry, {"shared": True, "tailnet": TAILNET, "colleagues": [
            {"login": COLLEAGUE, "projects": ["owner/p01"]},
            {"login": SECOND, "projects": ["owner/p00", "owner/p01"]}], "state": "serving",
            "last_request": None, "socket": "/s/g.sock", "other_device_seen": False})
        self.assertIs(guest.sharing_entry(
            access, TAILNET, "serving", other_device_seen=True)["other_device_seen"], True)
        self.assertIs(view.SHARING_OFF["other_device_seen"], False)
        self.assertIsNone(view.SHARING_OFF["socket"])
        self.assertEqual(derive_view([], sharing=entry)["sharing"], entry)
        r = guest.reading(access, TAILNET, ["localhost"], [TAILNET], [COLLEAGUE], [], [])
        entry = guest.sharing_entry(access, TAILNET, "serving", r)
        self.assertEqual(entry["last_request"], r)
        self.assertEqual(derive_view([], sharing=entry)["sharing"]["last_request"], r)
        derive_view([], sharing=entry)["sharing"]["last_request"]["host"] = "x"
        self.assertEqual(r["host"], "localhost")
        self.assertIsNone(view.SHARING_OFF["last_request"])
        derive_view([])["sharing"]["colleagues"].append("x")
        self.assertEqual(view.SHARING_OFF["colleagues"], [])


class GuestWriteRuleTest(unittest.TestCase):
    def test_the_write_refusal_checks_sharing_then_the_name_then_the_login_then_the_project(self):
        colleagues = MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})})
        on = guest.Policy(Access(True, colleagues), TAILNET)
        off = guest.Policy(Access(False, colleagues), TAILNET)
        unread = guest.Policy(Access(True, colleagues), None)
        renamed = guest.Policy(Access(True, colleagues), OTHER_HOST)
        c = GuestActor(COLLEAGUE, TAILNET)
        s = GuestActor(STRANGER, TAILNET)
        rows = [
            (off, c, "owner/p01", guest.SHARING_OFF_TEXT),
            (unread, c, "owner/p01", guest.NAME_UNREAD_TEXT),
            (renamed, c, "owner/p01", guest.HOST_TEXT),
            (on, s, "owner/p01", guest.NOT_SHARED_TEXT),
            (on, c, "owner/p00", guest.NOT_YOUR_PROJECT_TEXT),
            (on, c, "owner/p01", None),
            (off, s, "owner/p00", guest.SHARING_OFF_TEXT),
            (unread, s, "owner/p00", guest.NAME_UNREAD_TEXT),
            (renamed, s, "owner/p00", guest.HOST_TEXT),
        ]
        for policy, actor, project, expected in rows:
            with self.subTest(shared=policy.access.shared, name=policy.name, login=actor.login,
                              project=project):
                self.assertEqual(guest.write_refusal(policy, actor, project), expected)
        for text in (guest.NOT_YOUR_PROJECT_TEXT, guest.NOT_YOUR_SPRINT_TEXT,
                     guest.OWNER_LOOK_TEXT, guest.SHARING_OFF_TEXT, guest.NAME_UNREAD_TEXT,
                     guest.HOST_TEXT, guest.NOT_SHARED_TEXT, guest.OWNER_ONLY_TEXT):
            with self.subTest(text=text):
                self.assertNotIn("@", text)
                self.assertNotIn("owner/", text)

    def test_only_the_sprint_s_starter_steers_it(self):
        self.assertIsNone(guest.steer_refusal(COLLEAGUE, COLLEAGUE))
        self.assertEqual(guest.steer_refusal(COLLEAGUE, None), guest.NOT_YOUR_SPRINT_TEXT)
        self.assertEqual(guest.steer_refusal(COLLEAGUE, SECOND), guest.NOT_YOUR_SPRINT_TEXT)

    def test_mark_steer_marks_only_the_login_s_sprints_and_cards(self):
        c = COLLEAGUE
        sprint = lambda sid, by: {"type": "sprint", "sprint_id": sid, "started_by": by}  # noqa: E731
        question = lambda **more: {"reason": "question", **more}  # noqa: E731
        view_in = {
            "projects": [
                {"type": "project", "sprints": [sprint("a", c), sprint("b", None)]},
                {"type": "quiet", "projects": [{"type": "project", "sprints": [sprint("q", c)]}]}],
            "inbox": {"open": [
                {"reason": "brief", "started_by": c},
                question(started_by=SECOND),
                question(started_by=c, pictures=[{"id": "p1", "line": "one", "pair": None}]),
                question(started_by=c, pictures=[{"id": "p1", "pair": "before"},
                                                 {"id": "p2", "pair": "after"}]),
                question(started_by=c, owner_only=True),
                {"reason": "verify-approve", "kind": "approval", "confirm": "owner/p01#12",
                 "started_by": c},
                {"reason": "verify-approve", "kind": "paid-approval", "paid": True}],
                "answered": []}}
        before = copy.deepcopy(view_in)
        result = guest.mark_steer(view_in, c)
        found = {}

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "sprint":
                    found[node["sprint_id"]] = node["steer"]
                for member in node.values():
                    walk(member)
            elif isinstance(node, list):
                for member in node:
                    walk(member)

        walk(result["projects"])
        self.assertEqual(found, {"a": True, "b": False, "q": True})
        self.assertEqual([item["steer"] for item in result["inbox"]["open"]],
                         [True, False, True, False, False, False, False])
        self.assertEqual(result["inbox"]["answered"], [])
        self.assertFalse(guest.is_look([None, None]))
        self.assertFalse(guest.is_look([None, "after"]))
        self.assertFalse(guest.is_look(["before"]))
        self.assertTrue(guest.is_look(["after", None, "before"]))
        self.assertEqual(view_in, before)
        self.assertEqual(json.dumps(result).count(c), json.dumps(view_in).count(c))

    def test_mark_steer_offers_a_colleague_no_drop_on_an_unpicked_message(self):
        nudge = "Tell the manager again, or drop the sprint."
        turn = "It waits for the manager's next turn; drop the sprint if none comes."
        sprint = lambda sid, by, action: {  # noqa: E731
            "type": "sprint", "sprint_id": sid, "started_by": by,
            "messages": [{"id": 1, "state": "not_picked_up", "action_text": action}]}
        view_in = {"projects": [{"type": "project", "sprints": [
            sprint("a", COLLEAGUE, nudge), sprint("b", None, nudge), sprint("c", COLLEAGUE, turn),
            sprint("d", COLLEAGUE, None)]}], "inbox": {"open": [], "answered": []}}
        before = copy.deepcopy(view_in)
        result = guest.mark_steer(view_in, COLLEAGUE)
        actions = [s["messages"][0]["action_text"] for s in result["projects"][0]["sprints"]]
        self.assertEqual(actions, ["Tell the manager again.", "Tell the manager again.", turn, None])
        self.assertEqual(view_in, before)


if __name__ == "__main__":
    unittest.main()
