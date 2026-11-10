"""`agent_tools.hosts.keepalive_pings.end_turn_cap` and its verify check (issues 502, 638)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.hosts import keepalive_pings
from agent_tools.hosts.keepalive_pings import CapReport, end_turn_cap

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/keepalive-end-turn-cap"
START = datetime(2026, 11, 3, tzinfo=timezone.utc)
END = datetime(2026, 11, 10, tzinfo=timezone.utc)


def line(event, ts, **fields):
    return json.dumps({"event": event, "ts": ts, **fields})


def request(conv, ts, stop="end_turn", ms=1000, status=200, outcome="complete", keepalive="tracked"):
    return line("request", ts, conversation=conv, keepalive=keepalive, duration_ms=ms,
                status=status, outcome=outcome, stop_reason=stop)


def pings(conv, n, minute=10):
    return [line("ping", f"2026-11-04T00:{minute + i:02d}:00.000Z", conversation=conv) for i in range(n)]


class EndTurnCapTest(unittest.TestCase):
    def cap(self, lines):
        return end_turn_cap(lines, START, END, 2)

    def test_end_turn_period_over_cap_is_counted(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(end_turn_periods=1, over_cap=1, max_pings=3))

    def test_end_turn_period_within_cap_passes(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 2),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=2)]
        self.assertEqual(self.cap(lines), CapReport(1, 0, 2))

    def test_tool_use_period_is_not_counted(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z", stop="tool_use"), *pings("A", 9),
                 line("keepalive_end", "2026-11-04T00:30:00.000Z", conversation="A", pings=9)]
        self.assertEqual(self.cap(lines), CapReport(0, 0, 0))

    def test_listening_closes_open_periods_with_their_ping_count(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 4),
                 line("listening", "2026-11-04T00:30:00.000Z"),
                 *pings("A", 5, minute=40)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 4))

    def test_end_of_window_closes_open_periods(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 3)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_older_request_ending_late_never_changes_the_last_reply(self):
        lines = [request("A", "2026-11-04T00:00:05.000Z", stop="end_turn", ms=1000),
                 request("A", "2026-11-04T00:00:09.000Z", stop="tool_use", ms=9000),
                 *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_failed_or_incomplete_request_clears_the_last_reply(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z", status=529), *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(0, 0, 0))

    def test_side_and_untracked_requests_are_ignored(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"),
                 request("A", "2026-11-04T00:00:09.000Z", stop="tool_use", keepalive="no_tail_mark"),
                 request("A", "2026-11-04T00:00:10.000Z", stop="tool_use", keepalive="untracked"),
                 *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_pings_sent_while_the_reply_streams_are_within_the_cap(self):
        # The runtime case of tests/test_cache_keepalive.py: three pings while the reply
        # streams, then end_turn completes and the period ends end_turn_cap with pings=3.
        lines = [*pings("A", 3, minute=1),
                 request("A", "2026-11-04T00:05:00.000Z", ms=300000),
                 line("keepalive_end", "2026-11-04T00:05:00.500Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 0, 3))

    def test_streaming_pings_of_a_new_turn_after_an_end_turn_period_are_not_over(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 2, minute=1),
                 line("keepalive_end", "2026-11-04T00:09:00.000Z", conversation="A", pings=2),
                 *pings("A", 3, minute=10),
                 request("A", "2026-11-04T00:14:00.000Z", ms=300000),
                 line("keepalive_end", "2026-11-04T00:14:00.500Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(2, 0, 3))

    def test_a_period_ended_by_the_resuming_request_is_judged_before_that_request(self):
        # cache_proxy starts the new request before keepalive_end is written, so at the
        # keepalive_end instant the resuming request is still streaming.
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.050Z", conversation="A",
                      reason="resumed", pings=3),
                 request("A", "2026-11-04T00:20:30.000Z", stop="tool_use", ms=30000)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_a_pingless_period_ended_by_the_resuming_request_is_counted(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"),
                 line("keepalive_end", "2026-11-04T00:20:00.050Z", conversation="A",
                      reason="resumed", pings=0),
                 request("A", "2026-11-04T00:20:30.000Z", stop="tool_use", ms=30000)]
        self.assertEqual(self.cap(lines), CapReport(1, 0, 0))

    def test_a_ping_after_end_turn_completes_at_the_cap_is_over(self):
        lines = [line("ping", "2026-11-04T00:01:00.000Z", conversation="A"),
                 request("A", "2026-11-04T00:02:00.000Z", ms=90000),
                 *pings("A", 2, minute=10),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_a_ping_logged_after_the_reply_but_sent_while_it_streamed_is_within_the_cap(self):
        # cache_keepalive logs a ping when its exchange completes, with duration_ms: the
        # third ping was sent at 00:04:50, during the reply (00:00:00 to 00:05:00), and
        # logged at 00:05:10, after end_turn.
        lines = [line("ping", "2026-11-04T00:01:00.000Z", conversation="A", duration_ms=500),
                 line("ping", "2026-11-04T00:02:00.000Z", conversation="A", duration_ms=500),
                 request("A", "2026-11-04T00:05:00.000Z", ms=300000),
                 line("ping", "2026-11-04T00:05:10.000Z", conversation="A", duration_ms=20000),
                 line("keepalive_end", "2026-11-04T00:06:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 0, 3))

    def test_a_ping_sent_after_the_reply_completed_is_over_whatever_its_duration(self):
        lines = [line("ping", "2026-11-04T00:01:00.000Z", conversation="A", duration_ms=500),
                 line("ping", "2026-11-04T00:02:00.000Z", conversation="A", duration_ms=500),
                 request("A", "2026-11-04T00:05:00.000Z", ms=300000),
                 line("ping", "2026-11-04T00:15:10.000Z", conversation="A", duration_ms=20000),
                 line("keepalive_end", "2026-11-04T00:16:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_a_ping_sent_before_the_period_closed_belongs_to_it_though_logged_after(self):
        # The third ping was sent at 00:19:50 and the resuming request closed the period at
        # 00:20:00; the ping's exchange finished and was logged at 00:20:10.
        lines = [request("A", "2026-11-04T00:00:01.000Z"),
                 line("ping", "2026-11-04T00:10:00.000Z", conversation="A", duration_ms=500),
                 line("ping", "2026-11-04T00:11:00.000Z", conversation="A", duration_ms=500),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A",
                      reason="resumed", pings=3),
                 line("ping", "2026-11-04T00:20:10.000Z", conversation="A", duration_ms=20000)]
        self.assertEqual(self.cap(lines), CapReport(1, 1, 3))

    def test_a_ping_without_a_usable_duration_is_judged_at_its_log_time(self):
        for duration in (None, "slow", True, float("nan")):
            fields = {} if duration is None else {"duration_ms": duration}
            lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 2),
                     line("ping", "2026-11-04T00:20:00.000Z", conversation="A", **fields)]
            self.assertEqual(self.cap(lines), CapReport(1, 1, 3), duration)

    def test_lines_outside_the_window_and_garbage_are_skipped(self):
        lines = ["not json", "[1]", line("ping", "bad-ts", conversation="A"),
                 request("A", "2026-11-02T23:59:59.000Z"), *pings("A", 3),
                 line("keepalive_end", "2026-11-10T00:00:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(0, 0, 0))

    def test_a_line_at_the_end_instant_is_outside_the_window(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 2),
                 line("ping", "2026-11-10T00:00:00.000Z", conversation="A")]
        self.assertEqual(self.cap(lines), CapReport(1, 0, 2))

    def test_an_incomplete_request_is_not_an_end_turn_reply(self):
        lines = [request("A", "2026-11-04T00:00:01.000Z", outcome="aborted"), *pings("A", 3),
                 line("keepalive_end", "2026-11-04T00:20:00.000Z", conversation="A", pings=3)]
        self.assertEqual(self.cap(lines), CapReport(0, 0, 0))


class CommandTest(unittest.TestCase):
    def run_check(self, argv, lines=None, cwd=ROOT):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "proxy.log"
            if lines is not None:
                log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
            return subprocess.run([*argv, "--log", str(log), "--end", "2026-11-10T00:00:00Z"],
                                  cwd=cwd, env=env, capture_output=True, text=True, timeout=60)

    def module(self):
        return [sys.executable, "-m", "agent_tools.hosts.keepalive_pings", "end-turn-cap"]

    def test_exit_codes_and_output(self):
        ok = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 2)]
        over = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 3)]
        for lines, code in ((ok, 0), (over, 1), ([], 75)):
            done = self.run_check(self.module(), lines)
            self.assertEqual(done.returncode, code, done.stderr)
            out = json.loads(done.stdout)
            self.assertEqual(sorted(out), ["cap", "end", "end_turn_periods", "log", "max_pings",
                                           "over_cap", "start"])
            self.assertEqual(out["cap"], 2)

    def test_missing_log_exits_2_with_nothing_on_stdout(self):
        done = self.run_check(self.module(), None)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.strip())

    def test_wrapper_runs_the_module_from_the_repository_root(self):
        over = [request("A", "2026-11-04T00:00:01.000Z"), *pings("A", 3)]
        done = self.run_check([str(ROOT / WRAPPER)], over)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(json.loads(done.stdout)["over_cap"], 1)

    def test_wrapper_is_committed_executable(self):
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                             capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("100755 "), out)

    def test_cap_is_the_runtime_constant(self):
        from agent_tools.hosts import cache_keepalive
        self.assertEqual(cache_keepalive.END_TURN_PINGS, 2)
        self.assertTrue(hasattr(keepalive_pings, "main"))


if __name__ == "__main__":
    unittest.main()
