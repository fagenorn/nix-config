"""The lint stopwatch of `agent_tools.delivery.lint_time`.

Measures the base and branch time of each never-rise lint through the real
comparison, the exception path, the record line's exact bytes and the parse of a
job log line, over a scripted clock.
"""

import json
import unittest

from agent_tools.delivery import never_rise
from agent_tools.delivery.lint_time import LintTime, Stopwatch, parse_log, record_line
from agent_tools.delivery.never_rise import Enforcer, Snapshot

TIER = "fast"

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


if __name__ == "__main__":
    unittest.main()
