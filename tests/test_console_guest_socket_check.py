"""The held check that another account cannot open the console's guest socket (#1299).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import guest_socket_check
from agent_tools.console.guest_socket_check import owner_connects
from tests.test_verify_checks import committed_mode
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-guest-socket"
SOCK = "/tmp/cg-x/guest/guest.sock"


def state(socket):
    return {"sharing": {"tailnet": None, "socket": socket}}


def run_main(argv, **seams):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = guest_socket_check.main(argv, **seams)
    return code, out.getvalue()


class RulesTest(unittest.TestCase):
    def test_the_rules_in_order(self):
        rows = [
            (None, None, None, 75, "not_yet", "not_running"),
            ({}, None, None, 75, "not_yet", "no_guest_door"),
            (state(None), None, None, 75, "not_yet", "no_guest_door"),
            (state("guest.sock"), None, None, 75, "not_yet", "no_guest_door"),
            (state(SOCK), [False], None, 75, "not_yet", "door_not_answering"),
            (state(SOCK), [True], "connected", 1, "not_met", "reachable_by_other_user"),
            (state(SOCK), [True], "unknown", 75, "not_yet", "isolation_not_proven"),
            (state(SOCK), [True, False], "denied", 75, "not_yet", "door_not_answering"),
            (state(SOCK), [True, True], "denied", 0, "met", None),
        ]
        for read, owner_ok, other, code, status, reason in rows:
            with self.subTest(state=read, owner=owner_ok, other=other):
                owner_calls, other_calls = [], []
                answers = iter(owner_ok or [])

                def connect_owner(path, calls=owner_calls, answers=answers):
                    calls.append(path)
                    return next(answers)

                def connect_other(user, path, calls=other_calls, answer=other):
                    calls.append((user, path))
                    return answer

                got, printed = run_main(["--as", "_runner"], read_state=lambda port, r=read: r,
                                        connect_owner=connect_owner, connect_other=connect_other)
                self.assertEqual(got, code)
                self.assertEqual(json.loads(printed),
                                 {"status": status, **({"reason": reason} if reason else {})})
                self.assertNotIn(SOCK, printed)
                self.assertNotIn("@", printed)
                known = isinstance(read, dict) and isinstance(
                    read.get("sharing", {}).get("socket"), str) and read["sharing"]["socket"].startswith("/")
                reached = other is not None
                self.assertEqual(owner_calls, ([SOCK] * (2 if other == "denied" else 1)
                                               if known else []))
                self.assertEqual(other_calls, [("_runner", SOCK)] if reached else [])

    def test_a_bad_argument_is_2(self):
        for argv in ([], ["--as", "u", "--port", "x"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    guest_socket_check.main(argv)
                self.assertEqual(raised.exception.code, 2)


class ServiceTest(unittest.TestCase):
    def test_the_owner_connects_to_a_running_door(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "state/console/events.sqlite3"
        registry = Path(tmp.name) / "state/fleet/registry.json"
        support.write_registry(registry, support.entries(2))
        svc = support.service(self, store, registry, guest_socket=support.guest_socket_path(self))
        self.assertTrue(owner_connects(svc.guest_socket))
        self.assertFalse(owner_connects("/tmp/cg-missing/none.sock"))
        code, printed = run_main(["--as", "_runner", "--port", str(svc.address[1])],
                                 connect_other=lambda user, path: "denied")
        self.assertEqual(code, 0)
        self.assertEqual(printed.strip(), '{"status": "met"}')


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(WRAPPER), "100755")
        lines = [line for line in (ROOT / WRAPPER).read_text().splitlines() if line.strip()]
        self.assertEqual(
            lines[-1], 'PYTHONPATH=python exec python3 -m agent_tools.console.guest_socket_check "$@"')


if __name__ == "__main__":
    unittest.main()
