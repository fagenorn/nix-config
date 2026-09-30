import unittest
from dataclasses import replace
from unittest import mock
import subprocess

from agent_tools.review_pack import (ReviewRecord, ReviewLimits, ReviewPackError,
    pack_whole_records, measure_candidate, canonical_manifest)
from agent_tools.review_actual import CandidateInput, GenerationError, git_diff, pack_input, select_candidate
from pathlib import Path
from agent_tools.review_budget import BudgetError, describe


class WholeRecordTest(unittest.TestCase):
    def test_first_fit_preserves_whole_records_and_manifest_metrics(self):
        rows = tuple(ReviewRecord(p, raw, len(raw), None) for p, raw in
                     (("a", b"AAAAAA"), ("b", b"BBBBBB"), ("c", b"CCCC"), ("d", b"DDDD")))
        sequential = pack_whole_records(rows, 10, strategy="sequential")
        packed = pack_whole_records(rows, 10, strategy="stable-first-fit-whole-file")
        self.assertEqual(sequential, (b"AAAAAA", b"BBBBBBCCCC", b"DDDD"))
        self.assertEqual(packed, (b"AAAAAACCCC", b"BBBBBBDDDD"))
        metrics, status, violations = measure_candidate({}, packed, ReviewLimits(3, 10, 2, 23))
        self.assertEqual(metrics, {"root_bytes": 3, "total_bytes": 23,
                                  "file_count": 3, "largest_member_bytes": 10})
        self.assertEqual((status, violations), ("within_budget", ()))
        _, status, violations = measure_candidate({}, packed, ReviewLimits(2, 9, 1, 22))
        self.assertEqual((status, violations), ("over_budget",
                         ("root_bytes", "member_bytes", "member_count", "aggregate_bytes")))

    def test_oversized_record_stays_whole_and_duplicate_paths_are_rejected(self):
        record = ReviewRecord("a", b"abcdefghijk", 11, None)
        for strategy in ("sequential", "stable-first-fit-whole-file"):
            self.assertEqual(pack_whole_records((record,), 10, strategy=strategy), (record.payload,))
            with self.assertRaises(ReviewPackError):
                pack_whole_records((record, record), 10, strategy=strategy)

    def test_manifest_wire_preserves_non_ascii_and_lf(self):
        self.assertEqual(canonical_manifest({"z": "é", "a": 1}), b'{"a":1,"z":"\xc3\xa9"}\n')


class ActualSelectionTest(unittest.TestCase):
    limits = ReviewLimits(16384, 10, 1, 524288)

    def item(self, context=None, *, size=8):
        records = (ReviewRecord("a", b"A" * size, size, None),
                   ReviewRecord("b", b"B" * size, size, None))
        return CandidateInput(context, records, (),
            {"files_changed": 2, "insertions": 2, "deletions": 0}, 2 * size,
            "a" * 40, "b" * 40, "review.json")

    def test_each_adaptive_context_is_first_passing_candidate(self):
        contexts = (None, 7, 5, 3, 1, 0)
        for selected in contexts[1:]:
            with self.subTest(context=selected):
                def inputs():
                    for context in contexts:
                        yield self.item(context, size=4 if context == selected else 8)
                        if context == selected:
                            self.fail("selector consumed beyond its first passing candidate")
                candidate = select_candidate(inputs(), self.limits)
                self.assertEqual(candidate.status, "within_budget")
                self.assertEqual(candidate.shards, (b"AAAABBBB",))
                self.assertEqual(candidate.manifest["packaging"],
                    {"context_lines": selected, "shard_strategy": "stable-first-fit-whole-file"})

    def test_all_adaptive_overflow_retains_initial_wire(self):
        initial = pack_input(self.item(), self.limits)
        selected = select_candidate((self.item(c) for c in (None, 7, 5, 3, 1, 0)), self.limits)
        self.assertEqual(selected, initial)
        self.assertEqual(selected.manifest["interface_version"], 1)
        self.assertEqual(selected.violations, ("member_count",))

    def test_root_or_member_overflow_and_success_do_not_attempt_adaptation(self):
        for limits in (replace(self.limits, root_max_bytes=1),
                       replace(self.limits, member_max_bytes=7),
                       replace(self.limits, max_members=2)):
            def inputs():
                yield self.item()
                self.fail("ineligible adaptation consumed a second input")
            result = select_candidate(inputs(), limits)
            self.assertEqual(result.manifest["interface_version"], 1)

    def test_empty_range_has_manifest_only_metrics(self):
        item = replace(self.item(), records=(), stat={"files_changed": 0, "insertions": 0, "deletions": 0},
                       source_diff_bytes=0)
        result = select_candidate((item,), self.limits)
        self.assertEqual(result.shards, ())
        self.assertEqual(result.metrics["file_count"], 1)
        self.assertEqual(result.metrics["largest_member_bytes"], 0)
        self.assertEqual(result.metrics["total_bytes"], result.metrics["root_bytes"])

    def test_transform_is_packed_and_cannot_authorize_generated_evidence(self):
        item = self.item()
        transformed = select_candidate((item,), self.limits,
            transform=lambda value: replace(value, records=(ReviewRecord("a", b"x" * 11, 11, None),),
                source_diff_bytes=11, stat={"files_changed": 1, "insertions": 1, "deletions": 0}))
        self.assertIn("member_bytes", transformed.violations)
        evidence = {"path": "a", "kind": "ef-core-migration-designer", "source_diff_bytes": 9999}
        record = ReviewRecord("a", canonical_manifest({"review-package-generated-evidence": evidence}),
                              9999, evidence)
        with self.assertRaisesRegex(GenerationError, "unauthorized"):
            select_candidate((item,), self.limits,
                transform=lambda value: replace(value, records=(record,)))

    def test_fresh_view_cannot_override_pinned_record_policy(self):
        with self.assertRaisesRegex(GenerationError, "unsupported diff view"):
            git_diff(Path("."), "a" * 40, "b" * 40, "--no-renames")


class SymbolicMeasurementTest(unittest.TestCase):
    def test_shared_placement_and_length_metrics(self):
        from agent_tools.review_pack import place_record_sizes, measure_lengths
        self.assertEqual(place_record_sizes((6, 6, 4, 4), 10, strategy='sequential'),
                         ((0,), (1, 2), (3,)))
        self.assertEqual(place_record_sizes((6, 6, 4, 4), 10, strategy='stable-first-fit-whole-file'),
                         ((0, 2), (1, 3)))
        self.assertEqual(place_record_sizes((0, 0, 11, 0, 2), 10, strategy='sequential'),
                         ((0, 1), (2,), (3, 4)))
        self.assertEqual(measure_lengths(3, (10, 10), ReviewLimits(3, 10, 2, 23)),
                         ({'root_bytes': 3, 'total_bytes': 23, 'file_count': 3,
                           'largest_member_bytes': 10}, 'within_budget', ()))
        for size in (True, -1, '10'):
            with self.subTest(size=size), self.assertRaises(ReviewPackError):
                place_record_sizes((size,), 10, strategy='sequential')

    def test_small_symbolic_candidates_equal_materialized_packages(self):
        from agent_tools.review_pack import ReviewRecordSize
        from agent_tools.review_actual import FutureCommit, ReviewMeasurement, measure_input
        limits = ReviewLimits(16384, 10, 8, 524288)
        subjects = tuple(FutureCommit(str(n) * 40, size) for n, size in ((1, 0), (2, 3), (3, 7)))
        actual_commits = ({'sha': 'a' * 40, 'subject': 'actual é\n'},)
        records = (ReviewRecord('a', b'AAAAAA', 6, None),
                   *(ReviewRecordSize(path, size) for path, size in (('b', 6), ('c', 4), ('d', 4))))
        for context in (None, 7, 5, 3, 1, 0):
            item = CandidateInput(context, records, actual_commits,
                {'files_changed': 4, 'insertions': 4, 'deletions': 0}, 20,
                'a' * 40, 'b' * 40, 'review.json', future_commits=subjects)
            concrete = replace(item, records=(records[0], *(ReviewRecord(path, b'x' * size, size, None)
                for path, size in (('b', 6), ('c', 4), ('d', 4)))), future_commits=(),
                commits=actual_commits + tuple({'sha': row.sha, 'subject': '\x01' * row.subject_bytes}
                                              for row in subjects))
            measured = measure_input(item, limits)
            actual = pack_input(concrete, limits)
            self.assertIsInstance(measured, ReviewMeasurement)
            self.assertEqual((measured.metrics, measured.status, measured.violations),
                             (actual.metrics, actual.status, actual.violations))
            self.assertFalse(hasattr(measured, 'manifest'))
            self.assertFalse(hasattr(measured, 'shards'))
            for unpublished in (item, replace(item, records=concrete.records),
                                replace(item, future_commits=())):
                with self.assertRaisesRegex(GenerationError, 'symbolic'):
                    pack_input(unpublished, limits)
            with self.assertRaises(ReviewPackError):
                pack_whole_records(records, 10, strategy='sequential')

    def test_large_bounds_have_hand_computed_exact_metrics(self):
        import sys
        from agent_tools.review_pack import ReviewRecordSize
        from agent_tools.review_actual import FutureCommit, measure_input
        limits = ReviewLimits(16384, 65536, 8, 524288)
        for amount in (100000000000, sys.maxsize + 1):
            item = CandidateInput(None, (ReviewRecordSize('future', amount),), (),
                {'files_changed': 1, 'insertions': 1, 'deletions': 0}, amount,
                'a' * 40, 'b' * 40, 'review.json',
                future_commits=(FutureCommit('c' * 40, amount),))
            # Independent literal wire shape; subjects add six bytes each for \\u0001.
            root = ('{"commits":[{"sha":"' + 'c' * 40 + '","subject":""}],'
                '"coverage":{"complete":true,"file_diff_count":1},"interface_version":1,'
                '"kind":"review-package","purpose":"diff-review","range":{"base":"' + 'a' * 40 +
                '","head":"' + 'b' * 40 + '"},"shards":[{"bytes":' + str(amount) +
                ',"path":"review.shards/shard-001.diff"}],"stat":{"deletions":0,'
                '"files_changed":1,"insertions":1},"total_diff_bytes":' + str(amount) + '}\n')
            root_bytes = len(root.encode()) + 6 * amount
            result = measure_input(item, limits)
            self.assertEqual(result.metrics, {'root_bytes': root_bytes, 'total_bytes': root_bytes + amount,
                'file_count': 2, 'largest_member_bytes': amount})
            self.assertEqual((result.status, result.violations),
                             ('over_budget', ('root_bytes', 'member_bytes', 'aggregate_bytes')))

    def test_symbolic_selection_preserves_adaptation_and_initial_fallback(self):
        from agent_tools.review_pack import ReviewRecordSize
        from agent_tools.review_actual import measure_input
        fixture = ActualSelectionTest()
        contexts = (None, 7, 5, 3, 1, 0)
        def symbolic(item):
            return replace(item, records=tuple(ReviewRecordSize(row.path, len(row.payload)) for row in item.records))
        for selected in contexts[1:]:
            result = select_candidate((symbolic(fixture.item(context, size=4 if context == selected else 8))
                                       for context in contexts), fixture.limits, measurement_only=True)
            self.assertEqual(result.context_lines, selected)
            self.assertEqual(result.status, 'within_budget')
        initial = symbolic(fixture.item())
        result = select_candidate((symbolic(fixture.item(context)) for context in contexts),
                                  fixture.limits, measurement_only=True)
        self.assertEqual(result, measure_input(initial, fixture.limits))


class BudgetDescriptionTest(unittest.TestCase):
    def test_closed_bounded_canonical_description(self):
        description = {"schema_version": 1, "kind": "artifact-budget-description",
            "artifact_kind": "review-package", "limits": {"root_max_bytes": 16384,
                "member_max_bytes": 65536, "max_members": 8, "aggregate_max_bytes": 524288},
            "report_wire_max_bytes": 4096, "policy_sha256": "sha256:" + "a" * 64}
        wire = canonical_manifest(description)
        mutations = [wire + b" ", b" " * 4097, wire.replace(b'"schema_version":1', b'"schema_version":true'),
            wire.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
            wire.replace(b'"root_max_bytes":16384', b'"root_max_bytes":NaN'),
            canonical_manifest({**description, "extra": 1}),
            canonical_manifest({**description, "artifact_kind": "handoff"})]
        for raw in mutations:
            with self.subTest(raw=raw[:100]), mock.patch("agent_tools.review_budget.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, raw, b"")):
                with self.assertRaises(BudgetError):
                    describe("review-package")
        for status, stderr in ((2, b""), (0, b"warning")):
            with mock.patch("agent_tools.review_budget.subprocess.run",
                    return_value=subprocess.CompletedProcess([], status, wire, stderr)):
                with self.assertRaises(BudgetError):
                    describe("review-package")
