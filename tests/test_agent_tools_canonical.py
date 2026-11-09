"""The one shared home of canonical-JSON knowledge (#175 D3, parent D11).

Run: just agent-workflow-tests
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

from agent_tools.canonical import (reject_duplicate_keys, reject_nonfinite_literal,
                                   telemetry_digest)

# Unsorted keys at two levels, nesting, a non-ASCII string and a float.
GOLDEN_BODY = {"z": [1, 2.5, {"b": "é", "a": None}], "a": True}
# sha256 over the 46 ASCII bytes {"a":true,"z":[1,2.5,{"a":null,"b":"\u00e9"}]}
# (the "é" travels as the six ASCII characters \u00e9), computed outside
# Python. Every other digest assertion recomputes its expected value with the
# function it checks, so only this literal catches a format drift.
GOLDEN_DIGEST = "sha256:aac12d1f6010a8c2744d12c9a15e43fe5a6c3995b75d1cc756a742da24a5b682"


class TelemetryDigestTest(unittest.TestCase):
    def test_the_digest_format_is_pinned_by_a_golden_value(self):
        self.assertEqual(telemetry_digest(GOLDEN_BODY), GOLDEN_DIGEST)


class StrictLoadHookTest(unittest.TestCase):
    def test_a_repeated_key_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            json.loads('{"a": 1, "b": 2, "a": 3}', object_pairs_hook=reject_duplicate_keys)
        self.assertEqual(str(caught.exception), "duplicate JSON key 'a'")

    def test_distinct_keys_build_the_object_in_document_order(self):
        value = json.loads('{"b": 1, "a": {"c": 2}}', object_pairs_hook=reject_duplicate_keys)
        self.assertEqual(list(value), ["b", "a"])
        self.assertEqual(value, {"b": 1, "a": {"c": 2}})

    def test_each_nonfinite_literal_is_refused_by_name(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                with self.assertRaises(ValueError) as caught:
                    json.loads(f'{{"x": {literal}}}', parse_constant=reject_nonfinite_literal)
                self.assertEqual(str(caught.exception), f"JSON constant {literal} is not allowed")


if __name__ == "__main__":
    unittest.main()


class Rfc3339Test(unittest.TestCase):
    def test_parse_returns_an_aware_utc_instant(self):
        from agent_tools.canonical import parse_rfc3339_utc
        self.assertEqual(parse_rfc3339_utc("2026-11-09T21:22:00Z"),
                         datetime(2026, 11, 9, 21, 22, tzinfo=timezone.utc))
        offset = parse_rfc3339_utc("2026-11-09T23:22:00.5+02:00")
        self.assertEqual(offset, datetime(2026, 11, 9, 21, 22, 0, 500000, tzinfo=timezone.utc))
        self.assertEqual(offset.utcoffset(), timedelta(0))

    def test_parse_refuses_what_is_not_an_rfc3339_instant(self):
        from agent_tools.canonical import parse_rfc3339_utc
        for value in (None, 3, "2026-11-09", "2026-11-09T21:22:00", "2026-13-09T21:22:00Z",
                      "2026-11-09 21:22:00Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rfc3339_utc(value)
