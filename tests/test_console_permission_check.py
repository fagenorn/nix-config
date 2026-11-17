"""The verify check that a manager's session runs in the permission mode its started row logged (#1151).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import permission_check
from agent_tools.console.event_log import EventLog
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "home/common/verify-pending/checks/console-manager-permission"
PROJECT = "owner/p01"
S, N = "a" * 16, "owner/p01 sprint " + "a" * 16
BYPASS, AUTO = "bypassPermissions", "auto"


def started(sprint, name, mode, seen_after=0, permission=True, project=PROJECT):
    payload = {"sprint_id": sprint, "profile": "work", "session_name": name, "seen_after": seen_after}
    if permission:
        payload["permission"] = {"mode": mode, "reason": "production rules in place"}
    return ("manager.started", project, payload)


def seen(session_id, name):
    return ("session.seen", PROJECT, {"session_id": session_id, "cwd": "/srv/p01",
                                      "repo": "/srv/p01", "state": "working", "name": name})


class PermissionCheckTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        self.log = self.dir / "events.sqlite3"
        self.accounts = self.dir / "accounts"
        self.home = self.dir / "home"
        self.home.mkdir()

    def append(self, *rows):
        log = EventLog(self.log)
        try:
            log.append(list(rows))
        finally:
            log.close()

    def transcript(self, session_id, *lines, home=False):
        base = (self.home / ".claude" if home else self.accounts / "profiles" / "work")
        folder = base / "projects" / "-srv-p01"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{session_id}.jsonl").write_text(
            "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n",
            encoding="utf-8")

    def mode_lines(self, mode):
        return [{"type": "summary"}, {"type": "user", "permissionMode": mode}]

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = permission_check.main(["--project", PROJECT, "--log", str(self.log),
                                          "--accounts", str(self.accounts), "--home", str(self.home)])
        return code, json.loads(out.getvalue())

    def test_a_session_in_its_logged_mode_is_met(self):
        self.append(started(S, N, BYPASS), seen("s-1", N))
        self.transcript("s-1", *self.mode_lines(BYPASS))
        self.assertEqual(self.run_check(), (0, {
            "status": "met", "sprint_id": S, "session_id": "s-1", "mode": BYPASS,
            "text": "bypass: production rules in place"}))

    def test_a_transcript_under_the_home_directory_is_found(self):
        self.append(started(S, N, BYPASS), seen("s-1", N))
        self.transcript("s-1", *self.mode_lines(BYPASS), home=True)
        self.assertEqual(self.run_check()[0], 0)

    def test_a_session_in_another_mode_is_not_met(self):
        self.append(started(S, N, BYPASS), seen("s-1", N))
        self.transcript("s-1", *self.mode_lines(AUTO))
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(output, {
            "status": "not_met", "sprint_id": S, "session_id": "s-1", "mode": AUTO,
            "expected": BYPASS, "text": "bypass: production rules in place"})

    def test_the_first_mode_of_the_transcript_is_the_one_judged(self):
        self.append(started(S, N, BYPASS), seen("s-1", N))
        self.transcript("s-1", "not json", "[1]", {"permissionMode": 3},
                        {"permissionMode": BYPASS}, {"permissionMode": AUTO})
        self.assertEqual(self.run_check()[0], 0)

    def test_each_missing_piece_is_not_yet(self):
        cases = {
            "no log": (None, "no_log", lambda: None),
            "no permission": ([started(S, N, BYPASS, permission=False), seen("s-1", N)], "no_manager", None),
            "other project": ([started(S, N, BYPASS, project="owner/p02"), seen("s-1", N)], "no_manager", None),
            "string seen_after": ([started(S, N, BYPASS, seen_after="0"), seen("s-1", N)], "no_manager", None),
            "not seen": ([started(S, N, BYPASS)], "not_seen", None),
            "another name": ([started(S, N, BYPASS), seen("s-1", "other")], "not_seen", None),
            "no transcript": ([started(S, N, BYPASS), seen("s-1", N)], "no_transcript", None),
            "no mode": ([started(S, N, BYPASS), seen("s-1", N)], "no_mode",
                        lambda: self.transcript("s-1", {"type": "summary"})),
        }
        for label, (rows, reason, prepare) in cases.items():
            with self.subTest(label):
                self.tearDown_log()
                if rows is not None:
                    self.append(*rows)
                if prepare:
                    prepare()
                code, output = self.run_check()
                self.assertEqual(code, 75)
                self.assertEqual(output["status"], "not_yet")
                self.assertEqual(output["reason"], reason)
                self.assertEqual("sprint_id" in output, reason not in ("no_log", "no_manager"))

    def tearDown_log(self):
        self.log.unlink(missing_ok=True)
        for path in self.dir.rglob("*.jsonl"):
            path.unlink()

    def test_a_session_seen_before_its_started_row_is_found(self):
        self.append(seen("s-0", N), seen("s-1", N), started(S, N, BYPASS, seen_after=1))
        self.transcript("s-0", *self.mode_lines(AUTO))
        self.transcript("s-1", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["session_id"]), (0, "s-1"))

    def test_the_predecessors_session_is_never_this_managers(self):
        self.append(seen("s-0", N), started(S, N, BYPASS, seen_after=1))
        self.transcript("s-0", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["reason"]), (75, "not_seen"))
        self.append(seen("s-1", N), started(S, N, BYPASS, seen_after=3), seen("s-2", N))
        self.transcript("s-1", *self.mode_lines(AUTO))
        self.transcript("s-2", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["session_id"]), (1, "s-1"))

    def test_a_predecessor_seen_again_after_the_started_row_is_not_this_managers(self):
        self.append(seen("s-0", N), started(S, N, BYPASS, seen_after=1), seen("s-0", N), seen("s-1", N))
        self.transcript("s-0", *self.mode_lines(BYPASS))
        self.transcript("s-1", *self.mode_lines(AUTO))
        code, output = self.run_check()
        self.assertEqual((code, output["session_id"], output["mode"]), (1, "s-1", AUTO))

    def test_a_session_seen_after_a_later_started_row_is_not_the_first_managers(self):
        self.append(seen("s-0", N), started(S, N, BYPASS, seen_after=1),
                    started(S, N, BYPASS, seen_after=2), seen("s-2", N))
        self.transcript("s-2", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["reason"]), (75, "not_seen"))

    def test_the_first_manager_after_activation_is_judged_and_a_later_one_cannot_mask_it(self):
        other = "owner/p01 sprint " + "b" * 16
        self.append(started("A", N, BYPASS), started("B", other, BYPASS),
                    seen("s-a", N), seen("s-b", other))
        self.transcript("s-a", *self.mode_lines(AUTO))
        self.transcript("s-b", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["sprint_id"]), (1, "A"))
        self.tearDown_log()
        self.append(started("A", N, BYPASS), started("B", other, BYPASS), seen("s-b", other))
        self.transcript("s-b", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["reason"], output["sprint_id"]), (75, "not_seen", "A"))

    def test_a_manager_started_before_activation_never_counts(self):
        self.append(started(S, N, BYPASS, permission=False), seen("s-1", N))
        self.transcript("s-1", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["reason"]), (75, "no_manager"))
        other = "owner/p01 sprint " + "b" * 16
        self.append(started("B", other, BYPASS), seen("s-2", other))
        self.transcript("s-2", *self.mode_lines(BYPASS))
        code, output = self.run_check()
        self.assertEqual((code, output["sprint_id"]), (0, "B"))

    def test_the_committed_script_runs_the_check(self):
        self.assertTrue(stat.S_IMODE(os.stat(ROOT / SCRIPT).st_mode) & 0o111)
        done = subprocess.run(["/bin/sh", str(ROOT / SCRIPT), "--project", PROJECT,
                               "--log", str(self.dir / "missing.sqlite3")],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertIn("no_log", done.stdout)


if __name__ == "__main__":
    unittest.main()
