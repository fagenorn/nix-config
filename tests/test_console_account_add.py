"""The console's account adder (#1027): the name rule, the request, the row, the launcher run.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import account_add, account_remove, event_log, folder_trust
from agent_tools.console.event_log import Event
from agent_tools.console.account_add import AddFailed, Adder, adder_for, added, added_state
from agent_tools.console.account_add import already_exists, guest_name, identities_state, identity, mark, owners_state
from agent_tools.console.account_add import parse_add_request, parse_guest_add_request, refusal
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_guest import LONG_AGO, NOW, LogCase

A = "colleague@example.invalid"
B = "second@example.invalid"

LAUNCHER = (Path(__file__).resolve().parents[1]
            / "home/common/claude-code/accounts/bin/claude-account")
BASH = shutil.which("bash")


def launcher_env(root: Path) -> dict[str, str]:
    claude = root / "home" / ".claude"
    claude.mkdir(parents=True)
    (root / "store").mkdir()
    (root / "store" / "settings.json").write_text("{}")
    (claude / "settings.json").symlink_to(root / "store" / "settings.json")
    (claude / "CLAUDE.md").write_text("guidance")
    (claude / "skills").mkdir()
    return {"HOME": str(root / "home"), "CLAUDE_ACCOUNTS_DIR": str(root / "accounts"),
            "PATH": os.environ["PATH"]}


class NameRuleTest(unittest.TestCase):
    def test_the_console_rule_is_the_launchers(self):
        names = ["work", "a-b_c9", "-h", "0", "", "default", "Work", "a.b", "../x", "a b",
                 "x/y", "é", "a\n"]
        with tempfile.TemporaryDirectory() as tmp:
            env = launcher_env(Path(tmp))
            for name in names:
                with self.subTest(name=name):
                    proc = subprocess.run([BASH, str(LAUNCHER), "add", name], env=env,
                                          stdin=subprocess.DEVNULL, capture_output=True,
                                          timeout=30)
                    self.assertEqual(proc.returncode == 0, refusal(name) is None)

    def test_refusal_reasons(self):
        text = "not an account name: use a-z, 0-9, - and _"
        self.assertEqual(refusal("Work"), text)
        self.assertEqual(refusal(""), text)
        self.assertEqual(refusal("../x"), text)
        self.assertEqual(refusal("default"), "default is not an account name")
        self.assertIsNone(refusal("work"))
        self.assertEqual(already_exists("work"), "account work already exists")


class RequestTest(unittest.TestCase):
    def test_parse_add_request(self):
        self.assertEqual(parse_add_request(b'{"name":"work"}'), "work")
        self.assertEqual(parse_add_request(b'{"name":""}'), "")
        for body in (b'{}', b'{"name":1}', b'{"name":"a","x":1}', b'[]', b'"work"', b'\xff',
                     b'not json'):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    parse_add_request(body)

    def test_the_added_row(self):
        self.assertEqual(added("work"), ("account.added", None, {"by": "owner",
                                                                  "profile": "work"}))
        for name in ("default", "Work"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    added(name)
        self.assertEqual(account_add.ADDED, "account.added")
        self.assertEqual(event_log.ACCOUNT_ADDED, "account.added")
        self.assertNotIn("account.added", event_log.KEPT_KINDS)

    def test_added_state_folds_the_added_rows(self):
        rows = [("account.added", None, {"by": "owner", "profile": "b"}),
                ("account.added", None, {"by": "owner", "profile": "a"}),
                ("account.added", None, {"profile": "default"}),
                ("account.added", None, {"profile": 3}),
                ("signin.acted", None, {"by": "owner", "profile": "z", "action": "start",
                                        "outcome": "started"})]
        events = [Event(seq=n, at=f"t{n}", kind=kind, project=project, payload=payload)
                  for n, (kind, project, payload) in enumerate(rows, start=1)]
        self.assertEqual(added_state(events), frozenset({"a", "b"}))
        later = Event(seq=9, at="t9", kind="account.added", project=None,
                      payload={"by": "owner", "profile": "c"})
        self.assertEqual(added_state([later], frozenset({"a"})), frozenset({"a", "c"}))


class AdderTest(unittest.TestCase):
    def test_the_adder_runs_the_launchers_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = launcher_env(root)
            Adder(command=[BASH, str(LAUNCHER)], environ=env)("solo")
            profile = root / "accounts" / "profiles" / "solo"
            self.assertTrue(profile.is_dir())
            self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)
            self.assertEqual(os.readlink(profile / "settings.json"),
                             str(root / "home/.claude/settings.json"))
            self.assertEqual(os.readlink(profile / "skills"),
                             str(root / "home/.claude/skills"))

    def test_an_add_that_loses_the_race_for_the_directory_fails_and_makes_nothing_of_it(self):
        # Another add of the name lands between the launcher's look and its mkdir: the shim makes the
        # directory first, as that other add would. The launcher's own mkdir must then fail the add.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = launcher_env(root)
            real = shutil.which("mkdir")
            shim = root / "shim"
            shim.mkdir()
            (shim / "mkdir").write_text(
                f'#!{BASH}\nfor last; do :; done\ncase "$last" in */profiles/solo) {real} -p "$last" ;; esac\n'
                f'exec {real} "$@"\n')
            (shim / "mkdir").chmod(0o755)
            env["PATH"] = f"{shim}:{env['PATH']}"
            with self.assertRaises(AddFailed) as caught:
                Adder(command=[BASH, str(LAUNCHER)], environ=env)("solo")
            self.assertEqual(caught.exception.kind, "failed")
            self.assertEqual(os.listdir(root / "accounts" / "profiles" / "solo"), [])

    def test_an_invalid_name_starts_no_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ran"
            command = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]
            for name in ("../x", "default", ""):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        Adder(command=command)(name)
            self.assertFalse(marker.exists())

    def test_failures_have_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                ("not_installed", Adder(command=[str(Path(tmp) / "missing")])),
                ("failed", Adder(command=[sys.executable, "-c", "import sys; sys.exit(3)"])),
                ("timed_out", Adder(command=[sys.executable, "-c", "import time; time.sleep(30)"],
                                    timeout=0.5)),
            ]
            for kind, adder in cases:
                with self.subTest(kind=kind):
                    started = time.monotonic()
                    with self.assertRaises(AddFailed) as caught:
                        adder("work")
                    self.assertEqual(caught.exception.kind, kind)
                    self.assertEqual(str(caught.exception), kind)
                    self.assertLess(time.monotonic() - started, 10)
        self.assertIsNone(Adder(command=[sys.executable, "-c", "pass"])("work"))

    def test_a_timeout_ends_the_launchers_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "wrote"
            script = f"(sleep 2; touch {marker}) & wait"
            adder = Adder(command=[BASH, "-c", script, "launcher"], timeout=0.5)
            with self.assertRaises(AddFailed) as caught:
                adder("work")
            self.assertEqual(caught.exception.kind, "timed_out")
            time.sleep(3)
            self.assertFalse(marker.exists())

    def test_the_adder_withholds_the_launchers_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seen = root / "seen"
            script = root / "launcher"
            script.write_text('#!/bin/sh\nprintf %s "$CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST" > "$SEEN"\n')
            script.chmod(0o755)
            Adder(command=[str(script)], environ={"SEEN": str(seen), "PATH": os.environ["PATH"]})(
                "solo")
            self.assertEqual(seen.read_text(), "1")
            self.assertEqual(account_add.SKIP_TRUST_ENV, "CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST")

    def test_adder_for(self):
        self.assertIsInstance(adder_for("linux"), Adder)
        self.assertIsInstance(adder_for("darwin"), Adder)
        self.assertIsNone(adder_for("win32"))


def events_of(rows):
    return [Event(n, "2026-11-11T00:00:00.000000+00:00", kind, None, payload)
            for n, (kind, _, payload) in enumerate(rows, 1)]


class OwnerRecordTest(unittest.TestCase):
    def test_a_colleagues_add_row_names_his_login(self):
        self.assertEqual(added("colleague-1", by=A),
                         ("account.added", None, {"by": A, "profile": "colleague-1"}))
        self.assertEqual(added("work")[2], {"by": "owner", "profile": "work"})
        for by in ("Colleague@Example.invalid", "", "someone"):
            with self.subTest(by=by), self.assertRaises(ValueError):
                added("work", by=by)

    def test_the_newest_added_row_decides_the_owner(self):
        rows = events_of([
            ("account.added", None, {"by": A, "profile": "colleague-1"}),
            ("account.added", None, {"by": B, "profile": "colleague-2"}),
            ("account.added", None, {"by": "owner", "profile": "colleague-2"}),
            ("account.added", None, {"by": "x", "profile": "colleague-3"}),
            ("account.added", None, {"by": A, "profile": "Bad Name"}),
            ("signin.acted", None, {"by": A, "profile": "colleague-4"}),
        ])
        earlier = {"colleague-9": A}
        self.assertEqual(owners_state(rows), {"colleague-1": A})
        self.assertEqual(owners_state(rows[3:], owners_state(rows[:3])), {"colleague-1": A})
        self.assertEqual(owners_state(rows[3:], earlier), {"colleague-9": A})
        self.assertEqual(earlier, {"colleague-9": A})

    def test_a_completed_removal_ends_the_ownership_and_a_failed_one_keeps_it(self):
        rows = [added("colleague-1", by=A), added("colleague-2", by=A),
                account_remove.removed("colleague-1", "removed", None),
                account_remove.removed("colleague-2", "remove_failed", "failed"),
                account_remove.removed("colleague-3", "removed_signed_out_already", "failed")]
        self.assertEqual(owners_state(events_of(rows)), {"colleague-2": A})
        rows.append(added("colleague-1", by=B))
        self.assertEqual(owners_state(events_of(rows)), {"colleague-1": B, "colleague-2": A})

    def test_the_gone_outcomes_are_the_folder_trust_ones(self):
        self.assertEqual(account_add.GONE_OUTCOMES, folder_trust.GONE_OUTCOMES)
        self.assertEqual(event_log.ACCOUNT_GONE_OUTCOMES, folder_trust.GONE_OUTCOMES)

    def test_the_console_names_a_colleagues_profile_after_the_taken_names(self):
        self.assertEqual(guest_name(()), "colleague-1")
        self.assertEqual(guest_name({"colleague-1", "colleague-3", "work"}), "colleague-2")
        self.assertIsNone(refusal(guest_name({"colleague-1"})))

    def test_a_guest_add_body_is_a_consent_bool_and_at_most_the_shown_attempt(self):
        self.assertEqual(parse_guest_add_request(b'{"consent": true}'), (True, None))
        self.assertEqual(parse_guest_add_request(b'{"consent": false}'), (False, None))
        self.assertEqual(parse_guest_add_request(b'{"consent": true, "attempt": 7}'), (True, 7))
        for body in (b'{}', b'{"consent": 1}', b'{"consent": "true"}',
                     b'{"consent": true, "profile": "work"}', b'{"consent": true, "consent": true}',
                     b'{"attempt": 7}', b'{"consent": true, "attempt": 0}',
                     b'{"consent": true, "attempt": -1}', b'{"consent": true, "attempt": true}',
                     b'{"consent": true, "attempt": "7"}', b'{"consent": true, "attempt": 7.0}',
                     b'{"consent": true, "attempt": null}',
                     b'{"consent": true, "attempt": 7, "profile": "work"}',
                     b'{"consent": true, "attempt": 7, "attempt": 7}',
                     b'[]', b'\xff', b'{"consent": NaN}', b'[' * 100000):
            with self.subTest(body=body[:30]), self.assertRaises(ValueError):
                parse_guest_add_request(body)

    def test_a_colleagues_row_carries_the_identity_of_the_directory_it_added(self):
        self.assertEqual(added("colleague-1", by=A, identity="9:1")[2],
                         {"by": A, "profile": "colleague-1", "identity": "9:1"})
        for bad in ("", 5):
            with self.subTest(identity=bad), self.assertRaises(ValueError):
                added("colleague-1", by=A, identity=bad)

    def test_a_directory_made_in_place_of_a_freed_one_is_not_the_same_directory_even_with_its_inode(self):
        same = os.stat_result((0o40700, 4242, 1, 2, 0, 0, 64, 0, 0, 0))
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(account_add, "_stat", lambda _: same):
            root = Path(raw)
            (root / "colleague-1").mkdir()
            self.assertIsNone(identity(root / "colleague-1"))  # no marker yet
            first = mark(root / "colleague-1")
            self.assertRegex(first, r"^4242:[0-9]*:[0-9a-f]{32}$")
            self.assertEqual(identity(root / "colleague-1"), first)
            self.assertIsNone(mark(root / "colleague-1"))  # never marked twice
            shutil.rmtree(root / "colleague-1")
            (root / "colleague-1").mkdir()  # the freed inode, as the filesystem hands it out again
            self.assertIsNone(identity(root / "colleague-1"))
            second = mark(root / "colleague-1")
            self.assertNotEqual(second, first)
            self.assertIsNone(identity(root / "missing"))
            self.assertIsNone(mark(root / "missing"))

    def test_the_birth_time_is_the_platforms_when_it_gives_one(self):
        class Born:
            st_ino = 7
            st_birthtime = 1.5

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(account_add, "_stat", lambda _: Born()):
            (Path(raw) / "p").mkdir()
            self.assertRegex(mark(Path(raw) / "p"), r"^7:1500000000:[0-9a-f]{32}$")

    def test_a_marker_that_is_not_a_token_or_a_link_is_no_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "p"
            directory.mkdir()
            marker = directory / account_add.MARKER
            for content in (b"", b"abc", b"G" * 32, b"a" * 33, b"\xff" * 32):
                marker.write_bytes(content)
                with self.subTest(content=content):
                    self.assertIsNone(identity(directory))
            marker.unlink()
            (Path(raw) / "elsewhere").write_text("a" * 32)
            marker.symlink_to(Path(raw) / "elsewhere")
            self.assertIsNone(identity(directory))

    def test_a_marker_that_is_a_fifo_is_no_marker_and_blocks_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "p"
            directory.mkdir()
            fifo = directory / account_add.MARKER
            os.mkfifo(fifo)
            found = []
            worker = threading.Thread(target=lambda: found.append(identity(directory)), daemon=True)
            worker.start()
            worker.join(5)
            stuck = worker.is_alive()
            if stuck:  # let the blocked open return so the thread ends
                try:
                    os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
                except OSError:
                    pass
                worker.join(5)
            self.assertFalse(stuck, "reading a FIFO at the marker path blocked")
            self.assertEqual(found, [None])
            self.assertIsNone(mark(directory))  # a marker path already taken is never marked

    def test_the_identities_fold_follows_the_owners_fold(self):
        rows = events_of([
            ("account.added", None, {"by": A, "profile": "colleague-1", "identity": "1:a"}),
            ("account.added", None, {"by": A, "profile": "colleague-2", "identity": "2:a"}),
            ("account.added", None, {"by": B, "profile": "colleague-3"}),
            ("account.added", None, {"by": "owner", "profile": "colleague-2", "identity": "x"}),
            ("account.added", None, {"by": A, "profile": "colleague-4", "identity": ""}),
            ("account.added", None, {"by": "x", "profile": "colleague-5", "identity": "5:a"}),
            ("account.added", None, {"by": A, "profile": "Bad Name", "identity": "6:a"}),
            ("account.added", None, {"by": A, "profile": "colleague-7", "identity": "7:a"}),
            ("account.removal", None, {"profile": "colleague-7", "outcome": "removed"}),
            ("account.added", None, {"by": A, "profile": "colleague-8", "identity": "8:a"}),
            ("account.removal", None, {"profile": "colleague-8", "outcome": "remove_failed"}),
        ])
        earlier = {"colleague-9": "9:a"}
        self.assertEqual(identities_state(rows), {"colleague-1": "1:a", "colleague-8": "8:a"})
        self.assertEqual(identities_state(rows[4:], identities_state(rows[:4])),
                         {"colleague-1": "1:a", "colleague-8": "8:a"})
        self.assertEqual(identities_state(rows[5:6], earlier), {"colleague-9": "9:a"})
        self.assertEqual(earlier, {"colleague-9": "9:a"})


class OwnerRetentionTest(LogCase):
    def test_retention_keeps_the_newest_colleague_added_row_and_drops_the_owners(self):
        log = self.open()
        self.now = LONG_AGO
        log.append([added("colleague-1", by=A), added("fresh"), added("colleague-2", by=B),
                    added("colleague-2"), added("colleague-3", by=A),
                    account_remove.removed("colleague-3", "removed", None),
                    added("colleague-4", by=B),
                    account_remove.removed("colleague-4", "remove_failed", "failed")])
        before = owners_state(log.events())
        self.now = NOW
        log.retain()
        self.assertEqual([event.payload for event in log.events() if event.kind == "account.added"],
                         [{"by": A, "profile": "colleague-1"}, {"by": B, "profile": "colleague-4"}])
        self.assertEqual(owners_state(log.events()), before)
        self.assertEqual(before, {"colleague-1": A, "colleague-4": B})

    def test_retention_keeps_the_identity_with_the_colleagues_row(self):
        log = self.open()
        self.now = LONG_AGO
        log.append([added("colleague-1", by=A, identity="1:a")])
        self.now = NOW
        log.retain()
        self.assertEqual(identities_state(log.events()), {"colleague-1": "1:a"})

    def test_a_later_add_row_the_fold_ignores_does_not_end_a_colleagues_kept_row(self):
        log = self.open()
        self.now = LONG_AGO
        ignored = [("account.added", None, {"by": by, "profile": "colleague-1"})
                   for by in ("Colleague@Example.invalid", "someone", "", 7, None)]
        log.append([added("colleague-1", by=A), *ignored])
        before = owners_state(log.events())
        self.assertEqual(before, {"colleague-1": A})
        self.now = NOW
        log.retain()
        self.assertEqual([event.payload for event in log.events() if event.kind == "account.added"],
                         [{"by": A, "profile": "colleague-1"}])
        self.assertEqual(owners_state(log.events()), before)

    def test_an_old_row_with_an_unreadable_login_is_not_kept(self):
        log = self.open()
        self.now = LONG_AGO
        log.append([("account.added", None, {"by": "Colleague@Example.invalid", "profile": "x"}),
                    ("account.added", None, {"by": "someone", "profile": "y"})])
        self.now = NOW
        log.retain()
        self.assertEqual([e for e in log.events() if e.kind == "account.added"], [])


if __name__ == "__main__":
    unittest.main()
