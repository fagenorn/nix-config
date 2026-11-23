"""The lint stopwatch and the lint-time command of `agent_tools.delivery.lint_time`.

Measures the base and branch time of each never-rise lint through the real
comparison, the exception path, the record line's exact bytes and the parse of a
job log line, over a scripted clock. Measures the medians, the one marked issue,
the run listing and the two subcommands over a stub tracker and a stub forge.
"""

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import cleanup_issue, lint_time, never_rise
from agent_tools.delivery.cleanup_issue import Issue
from agent_tools.delivery.lint_time import (
    MARKER, LintTime, Record, Stopwatch, draft, is_lint_time, output, parse_log, reading,
    record_line, run)
from agent_tools.delivery.never_rise import Enforcer, Snapshot

TIER = "integration"  # this module reads the git index and runs a wrapper

REPO_ROOT = Path(__file__).resolve().parents[1]

EXAMPLE = (
    'lint-times v1 {"lints":[{"base_ms":2000,"branch_ms":3000,"lint":"A"},'
    '{"base_ms":1000,"branch_ms":1000,"lint":"B"}],"total_ms":7000}')


class ScriptedClock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


def payload_line(**changes):
    payload = {
        "lints": [{"base_ms": 1, "branch_ms": 2, "lint": "A"}],
        "total_ms": 3,
    }
    payload.update(changes)
    return "lint-times v1 " + json.dumps(payload)


class StopwatchTest(unittest.TestCase):
    def test_each_lint_reports_its_base_and_branch_time_and_the_total(self):
        clock = ScriptedClock([0.0, 2.0, 2.0, 5.0, 5.0, 6.0, 6.0, 7.0])
        enforcers = (Enforcer("A", lambda s: []), Enforcer("B", lambda s: []))
        base = Snapshot("b" * 40, {})
        branch = Snapshot("c" * 40, {})
        watch = Stopwatch(clock)

        never_rise.compare(base, branch, {}, watch.timed(enforcers))
        line = record_line(watch.record())

        self.assertEqual(line, EXAMPLE)
        self.assertEqual(parse_log(line), watch.record())

    def test_timed_enforcers_keep_rule_order_and_per_file(self):
        def find(snapshot):
            return ["found"]

        watch = Stopwatch(ScriptedClock([0.0, 1.0]))
        wrapped = watch.timed((Enforcer("A", find, per_file=True), Enforcer("B", find)))

        self.assertEqual([(e.rule, e.per_file) for e in wrapped], [("A", True), ("B", False)])
        self.assertEqual(wrapped[0].find(Snapshot("b" * 40, {})), ["found"])

    def test_a_find_that_raises_is_timed_and_reraised(self):
        failure = never_rise.EnforcerFailed("A", "x")

        def find(snapshot):
            raise failure

        watch = Stopwatch(ScriptedClock([0.0, 1.5]))
        (wrapped,) = watch.timed((Enforcer("A", find),))

        with self.assertRaises(never_rise.EnforcerFailed) as caught:
            wrapped.find(Snapshot("b" * 40, {}))

        self.assertIs(caught.exception, failure)
        self.assertEqual(watch.record().lints, (LintTime("A", 1500, 0),))

    def test_no_call_records_nothing(self):
        watch = Stopwatch(ScriptedClock([]))
        watch.timed((Enforcer("A", lambda s: []),))

        self.assertIsNone(watch.record())

    def test_a_job_log_line_with_a_timestamp_parses(self):
        watch = Stopwatch(ScriptedClock([0.0, 2.0, 2.0, 5.0, 5.0, 6.0, 6.0, 7.0]))
        never_rise.compare(
            Snapshot("b" * 40, {}), Snapshot("c" * 40, {}), {},
            watch.timed((Enforcer("A", lambda s: []), Enforcer("B", lambda s: []))))
        text = (
            "﻿2026-11-22T10:00:00.1234567Z ##[group]Run conformance\n"
            "2026-11-22T10:00:01.0000000Z " + EXAMPLE + "\n")

        self.assertEqual(parse_log(text), watch.record())
        self.assertEqual(parse_log("\ufeff2026-11-22T10:00:01Z " + EXAMPLE), watch.record())

    def test_a_log_without_a_record_is_none(self):
        self.assertIsNone(parse_log("a\nb\n"))

    def test_two_records_or_a_bad_payload_are_refused(self):
        entry = {"base_ms": 1, "branch_ms": 2, "lint": "A"}
        cases = {
            "two records": payload_line() + "\n" + payload_line(),
            "total off by one": payload_line(total_ms=4),
            "float total": payload_line(total_ms=3.0),
            "bool total": payload_line(lints=[dict(entry, base_ms=0, branch_ms=1)], total_ms=True),
            "bool base": payload_line(lints=[dict(entry, base_ms=True)], total_ms=3),
            "negative branch": payload_line(lints=[dict(entry, branch_ms=-1)], total_ms=0),
            "duplicate lint": payload_line(lints=[entry, entry], total_ms=6),
            "extra key": payload_line(extra=1),
            "empty lints": payload_line(lints=[], total_ms=0),
            "not json": "lint-times v1 {not json",
        }
        for name, text in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    parse_log(text)


def rec(**ms) -> Record:
    return Record(tuple(LintTime(lint, value, 0) for lint, value in ms.items()))


class StubTracker:
    def __init__(self, open_issues=None, writer=True):
        self.open = list(open_issues or [])
        self.writer = writer
        self.created: list[tuple[str, str]] = []

    def trusted_writer(self) -> bool:
        return self.writer

    def open_issues(self) -> list[Issue]:
        return list(self.open)

    def create(self, title: str, body: str) -> int:
        number = 101 + len(self.created)
        self.created.append((title, body))
        self.open.append(Issue(number, body))
        return number


SLOW = [rec(B17=40_000, PY6=25_000)] * 20


class LintTimeRunTest(unittest.TestCase):
    def test_twenty_runs_over_the_budget_file_one_issue_naming_the_slowest_lint(self):
        tracker = StubTracker()

        outcome = run(tracker, SLOW, "main")

        self.assertEqual((outcome.action, outcome.issue), ("filed", 101))
        self.assertEqual(len(tracker.created), 1)
        title, body = tracker.created[0]
        self.assertTrue(title.endswith("slowest lint B17"))
        self.assertEqual(body.splitlines()[0], MARKER)
        self.assertIn("| B17 | 40.0 |\n| PY6 | 25.0 |\n", body)
        self.assertEqual(output(outcome), json.dumps({
            "action": "filed", "issue": 101, "runs": 20, "median_seconds": 65.0,
            "slowest": {"lint": "B17", "median_seconds": 40.0}}))

    def test_the_issue_text_is_exact(self):
        title, body = draft(reading(SLOW), "main")

        self.assertEqual(
            title,
            "Lint time: median 65.0 s of the last 20 runs is over the 60 s budget; slowest lint B17")
        self.assertEqual(body, (
            "<!-- agent:lint-time v1 -->\n"
            "The median total lint time of the last 20 completed Conformance runs on main is "
            "65.0 s, over the 60 s budget. The slowest lint is B17, with a median of 40.0 s.\n"
            "\n## Lints\n\n| Lint | Median seconds |\n|---|---:|\n| B17 | 40.0 |\n| PY6 | 25.0 |\n"
            "\n## What to change\n\n"
            "Make the slowest lint faster, or the lints together, until the median total is at "
            "most 60 s. A slow run never fails a change; this issue is the only signal.\n"
            "\n## Acceptance criteria\n\n"
            "- [ ] [evidence] The median total lint time of the last 20 completed Conformance "
            "runs on main is at most 60 s \u2014 measured: the Lint Time job log on main prints "
            '"action": "within"\n'))

    def test_a_median_at_the_budget_files_nothing(self):
        tracker = StubTracker()

        outcome = run(tracker, [rec(B17=60_000)] * 20, "main")

        self.assertEqual(outcome.action, "within")
        self.assertEqual(tracker.created, [])
        self.assertEqual(json.loads(output(outcome))["median_seconds"], 60.0)

    def test_nineteen_runs_file_nothing(self):
        tracker = StubTracker()

        outcome = run(tracker, [rec(B17=90_000)] * 19, "main")

        self.assertEqual(outcome.action, "too_few")
        self.assertIsNone(json.loads(output(outcome))["median_seconds"])
        self.assertIsNone(json.loads(output(outcome))["slowest"])
        self.assertEqual(tracker.created, [])

    def test_an_open_lint_time_issue_files_nothing(self):
        tracker = StubTracker([Issue(9, "x\n" + MARKER + "\n"), Issue(7, MARKER)])

        outcome = run(tracker, SLOW, "main")

        self.assertEqual((outcome.action, outcome.issue), ("open", 7))
        self.assertEqual(tracker.created, [])

    def test_the_slowest_lint_is_chosen_by_its_median_not_the_newest_run(self):
        tracker = StubTracker()
        records = [rec(A=10_000, B=70_000)] + [rec(A=50_000, B=20_000)] * 19

        run(tracker, records, "main")

        self.assertTrue(tracker.created[0][0].endswith("slowest lint A"))

    def test_only_the_newest_twenty_records_count(self):
        records = [rec(A=1_000)] * 20 + [rec(A=90_000)] * 30

        self.assertEqual(run(StubTracker(), records, "main").action, "within")

    def test_a_lint_missing_from_old_runs_is_judged_on_the_runs_that_carry_it(self):
        found = reading([rec(A=70_000, N=5_000)] * 10 + [rec(A=70_000)] * 10)

        self.assertEqual(dict(found.lints)["N"], 5000)
        self.assertEqual(reading([rec(Z=1_000, Y=1_000)] * 20).slowest[0], "Y")

    def test_the_marker_counts_only_as_a_whole_line(self):
        self.assertTrue(is_lint_time(MARKER + "  \r"))
        for body in ("x " + MARKER, "<!-- agent:lint-time v2 -->",
                     "<!-- agent:cleanup v1 rule=B17 -->"):
            with self.subTest(body):
                self.assertFalse(is_lint_time(body))

    def test_a_filer_that_would_not_be_trusted_files_nothing(self):
        tracker = StubTracker(writer=False)

        with self.assertRaises(cleanup_issue.Refusal):
            run(tracker, SLOW, "main")

        self.assertEqual(tracker.created, [])


SLUG = "octo/widgets"
LISTING = (f"repos/{SLUG}/actions/workflows/conformance.yaml/runs"
           "?branch=main&event=push&status=completed&per_page=50")


def log_of(run_id: int) -> str:
    line = record_line(Record((LintTime("A", run_id * 1000, 0),)))
    return f"2026-11-22T10:00:00.0000000Z {line}\n"


def forge(runs, jobs, logs, listing=LISTING):
    """Stubs of `api_get` and `run_gh` for a listing, its jobs by run id and its logs by job id."""
    asked = []
    answers = {listing: {"workflow_runs": runs}}
    for run_id, found in jobs.items():
        answers[f"repos/{SLUG}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"] = {"jobs": found}

    def api_get(path, allow=()):
        return answers[path]

    def run_gh(argv, allow=()):
        asked.append(argv[1])
        job_id = int(argv[1].split("/")[-2])
        return logs[job_id]

    return api_get, run_gh, asked


class GitHubLintTimeTest(unittest.TestCase):
    def test_runs_without_a_record_are_skipped_and_reading_stops_at_twenty(self):
        runs = [{"id": n, "created_at": f"2026-11-{n:02d}T00:00:00Z"} for n in range(1, 26)]
        jobs = {n: [{"id": 1, "name": "Other"}, {"id": 1000 + n, "name": "Conformance"}]
                for n in range(1, 26)}
        jobs[22] = [{"id": 1, "name": "Other"}]
        logs = {1000 + n: (0, log_of(n)) for n in range(1, 26)}
        logs[1020] = (0, "no record here\n")
        api_get, run_gh, asked = forge(runs, jobs, logs)

        with mock.patch.object(lint_time.forge_api, "api_get", api_get), \
                mock.patch.object(lint_time.forge_api, "run_gh", run_gh):
            records = lint_time.GitHubLintTime(SLUG, "main").records()

        self.assertEqual([r.total_ms for r in records],
                         [n * 1000 for n in (25, 24, 23, 21, *range(19, 3, -1))])
        self.assertEqual(len(records), 20)
        self.assertEqual(len(asked), 21)
        self.assertNotIn(f"repos/{SLUG}/actions/jobs/1003/logs", asked)

    def test_a_log_gh_refuses_for_terminal_escape_sequences_is_read_with_the_flag(self):
        runs = [{"id": 1, "created_at": "2026-11-01T00:00:00Z"}]
        jobs = {1: [{"id": 1001, "name": "Conformance"}]}
        api_get, stub, _ = forge(runs, jobs, {1001: (0, log_of(1))})
        refusal = ("the response contains terminal escape sequences; "
                   "pass --allow-escape-sequences to output it anyway")

        def run_gh(argv, allow=()):
            if "--allow-escape-sequences" not in argv:
                raise lint_time.forge_api.ForgeError("gh_failed", refusal)
            return stub([a for a in argv if a != "--allow-escape-sequences"], allow)

        with mock.patch.object(lint_time.forge_api, "api_get", api_get), \
                mock.patch.object(lint_time.forge_api, "run_gh", run_gh):
            records = lint_time.GitHubLintTime(SLUG, "main").records()

        self.assertEqual([r.total_ms for r in records], [1000])

    def test_a_gone_log_is_skipped(self):
        runs = [{"id": n, "created_at": f"2026-11-{n:02d}T00:00:00Z"} for n in (1, 2)]
        jobs = {n: [{"id": 1000 + n, "name": "Conformance"}] for n in (1, 2)}
        api_get, run_gh, _ = forge(runs, jobs, {1001: (0, log_of(1)), 1002: (410, log_of(2))})

        with mock.patch.object(lint_time.forge_api, "api_get", api_get), \
                mock.patch.object(lint_time.forge_api, "run_gh", run_gh):
            records = lint_time.GitHubLintTime(SLUG, "main").records()

        self.assertEqual([r.total_ms for r in records], [1000])


class CommandTest(unittest.TestCase):
    def call(self, argv, api_get, run_gh):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(lint_time.forge_api, "api_get", api_get), \
                mock.patch.object(lint_time.forge_api, "run_gh", run_gh), \
                mock.patch.object(lint_time.forge_api, "api_pages", return_value=[[]]), \
                mock.patch.object(lint_time.forge_api, "create_issue", return_value=41) as create, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lint_time.main(argv)
        return code, out.getvalue(), err.getvalue(), create

    def test_a_malformed_record_exits_2_and_files_nothing(self):
        runs = [{"id": 1, "created_at": "2026-11-01T00:00:00Z"}]
        bad = 'lint-times v1 {"lints":[],"total_ms":0}\n'
        api_get, run_gh, _ = forge(runs, {1: [{"id": 11, "name": "Conformance"}]}, {11: (0, bad)})

        code, out, err, create = self.call(
            ["file", "--repo", SLUG, "--branch", "main"], api_get, run_gh)

        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("lint-time: "))
        self.assertEqual(out, "")
        create.assert_not_called()

    def test_file_files_one_issue_and_prints_the_outcome(self):
        runs = [{"id": n, "created_at": f"2026-11-{n:02d}T00:00:00Z"} for n in range(1, 21)]
        jobs = {n: [{"id": 100 + n, "name": "Conformance"}] for n in range(1, 21)}
        slow = record_line(rec(B17=70_000)) + "\n"
        api_get, run_gh, _ = forge(runs, jobs, {100 + n: (0, slow) for n in range(1, 21)})

        def api_get_all(path, allow=()):
            return None if path == "user" else api_get(path, allow)

        code, out, _, create = self.call(
            ["file", "--repo", SLUG, "--branch", "main"], api_get_all, run_gh)

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "filed")
        self.assertEqual(json.loads(out)["issue"], 41)
        create.assert_called_once()

    def test_observed_reads_the_newest_lint_time_output(self):
        listing = (f"repos/{SLUG}/actions/workflows/lint-time.yaml/runs"
                   "?branch=main&event=push&status=completed&per_page=1")
        stamp = "2026-11-22T10:00:00.0000000Z "
        within = json.dumps({"action": "within", "issue": None, "runs": 20, "median_seconds": 12.5,
                             "slowest": {"lint": "PY6", "median_seconds": 8.25}})
        too_few = json.dumps({"action": "too_few", "issue": None, "runs": 3,
                              "median_seconds": None, "slowest": None})
        cases = [
            ("within", [{"id": 5, "created_at": "2026-11-01T00:00:00Z"}],
             f"setup\n{stamp}{within}\n", 0, "met"),
            ("too few", [{"id": 5, "created_at": "2026-11-01T00:00:00Z"}],
             f"{stamp}{too_few}\n", 75, "not_yet"),
            ("no run", [], "", 75, "not_yet"),
            ("no output line", [{"id": 5, "created_at": "2026-11-01T00:00:00Z"}],
             "nothing\n", 1, "not_met"),
        ]
        for name, runs, text, want_code, want_state in cases:
            with self.subTest(name):
                api_get, run_gh, _ = forge(
                    runs, {5: [{"id": 55, "name": "Lint Time"}]}, {55: (0, text)}, listing)

                code, out, _, _ = self.call(
                    ["observed", "--repo", SLUG, "--branch", "main"], api_get, run_gh)

                self.assertEqual(code, want_code)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertEqual(json.loads(out)["state"], want_state)

    def test_observed_met_prints_the_median_and_the_slowest_lint(self):
        listing = (f"repos/{SLUG}/actions/workflows/lint-time.yaml/runs"
                   "?branch=main&event=push&status=completed&per_page=1")
        within = json.dumps({"action": "within", "issue": None, "runs": 20, "median_seconds": 12.5,
                             "slowest": {"lint": "PY6", "median_seconds": 8.25}})
        api_get, run_gh, _ = forge(
            [{"id": 5, "created_at": "2026-11-01T00:00:00Z"}],
            {5: [{"id": 55, "name": "Lint Time"}]}, {55: (0, within + "\n")}, listing)

        _, out, _, _ = self.call(["observed", "--repo", SLUG, "--branch", "main"], api_get, run_gh)

        self.assertEqual(json.loads(out), {
            "state": "met", "run": 5, "median_seconds": 12.5, "slowest": "PY6"})

    def test_a_repository_outside_the_slug_is_refused(self):
        code, out, err, _ = self.call(["file", "--repo", "bad", "--branch", "main"], None, None)

        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("lint-time: "))

    def test_the_command_is_a_row_of_the_command_table_and_its_check_is_committed(self):
        row = '    "lint-time" = "delivery.lint_time";'
        wrapper = "home/common/verify-pending/checks/lint-time-reading"

        table = (REPO_ROOT / "lib/agent-tools.nix").read_text().splitlines()
        verdicts = json.loads(
            (REPO_ROOT / "python/agent_tools/delivery/command_verdicts.json").read_text())
        staged = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", wrapper],
            capture_output=True, text=True, check=True).stdout
        bare = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / wrapper)], cwd=REPO_ROOT, capture_output=True,
            text=True, stdin=subprocess.DEVNULL, timeout=60)

        self.assertEqual(table.count(row), 1)
        self.assertIsNone(verdicts["lint-time"])
        self.assertTrue(staged.startswith("100755"))
        self.assertEqual(bare.returncode, 2)


if __name__ == "__main__":
    unittest.main()
