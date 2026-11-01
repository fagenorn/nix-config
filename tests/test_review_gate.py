"""`review-feasibility gate` and `confirm` from source (issue 227, D3, D4, D10)."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

import tests.test_review_feasibility as source_cases
from agent_tools.review_budget import describe
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_gate import GateError, SUMMARY_KEYS, capture

DIGESTS = ("plan_package_sha256", "forecast_sha256", "packing_policy_sha256", "artifact_policy_sha256")
METRICS = ("root_bytes", "total_bytes", "file_count", "largest_member_bytes")


class GateFixture(source_cases.SourceProjectionFixture):
    def plan_path(self):
        return str(self.repo / 'all.md')

    def gate(self, completed=0, save=None):
        return self.invoke('gate', '--plan', self.plan_path(), '--base', self.base, '--head', self.head,
                           '--completed-through', str(completed), *(('--save-dir', str(save)) if save else ()))

    def confirm(self, raw, base=None, plan=None):
        return self.invoke('confirm', '--plan', plan or self.plan_path(), '--base', base or self.base,
                           '--input', '-', input=raw)

    def oversize(self, leaf=True):
        """RecommendationTest's shape: the root overflows root_bytes; the leaf `end`, when declared, fits."""
        root = self.delivery['boundaries'][0]
        root['process_commit_subject_bytes'] = [120] * 30
        if leaf:
            leaf = source_cases.BoundaryTreeTest().row('end', 'all', [1, 2])
            leaf['process_commit_subject_bytes'] = [1]
            self.delivery['boundaries'] = [root, leaf]
            paths = [leaf['process_package']['spec'], leaf['process_package']['plan'], *leaf['process_package']['tasks']]
            for index, path in enumerate(paths):
                record = self.record(leaf['process_forecast_ids'][index], 0, path)
                record['bounds'][0]['boundary'] = 'end'
                self.delivery['process_records'].append(record)
        self.emit(); self.commit('boundaries')

    def bare_overflow(self):
        """An overflow no declared boundary fits: a null recommendation (D18)."""
        self.oversize(leaf=False)

    def assert_refused(self, result, needle):
        self.assertEqual((result.returncode, result.stdout), (2, b''), result.stderr)
        lines = result.stderr.decode().splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertTrue(lines[0].startswith('review-feasibility: '), lines[0])
        self.assertIn(needle, lines[0])


class GateTest(GateFixture, unittest.TestCase):
    def test_complete_summary_copies_the_validated_result(self):
        result = self.project(0, package=f'review-{self.base[:7]}..{self.head[:7]}.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        gated = self.gate(0)
        self.assertEqual(gated.returncode, 0, gated.stderr)
        summary, value = json.loads(gated.stdout), json.loads(result.stdout)
        self.assertEqual(tuple(sorted(summary)), SUMMARY_KEYS)
        self.assertEqual(gated.stdout, canonical_bytes(summary))
        self.assertEqual((summary['schema_version'], summary['kind'], summary['plan']),
                         (1, 'review-feasibility-summary', 'all.md'))
        for key in ('state', 'base', 'head', 'completed_through', 'metrics', 'violations', *DIGESTS):
            self.assertEqual(summary[key], value[key], key)
        self.assertIsNone(summary['recommended_boundary'])

    def test_overflow_summary_trims_the_recommendation(self):
        self.oversize()
        result = self.project(0, package=f'review-{self.base[:7]}..{self.head[:7]}.json')
        save = self.top / 'saved'; save.mkdir()
        gated = self.gate(0, save)
        self.assertEqual((result.returncode, gated.returncode), (3, 3), gated.stderr)
        self.assertEqual((save / f'projection-{self.head[:7]}-0.json').read_bytes(), result.stdout)  # D20
        full = json.loads(result.stdout)['recommended_boundary']
        self.assertEqual(json.loads(gated.stdout)['recommended_boundary'],
                         {key: full[key] for key in ('id', 'tasks', 'prerequisite_commit', 'metrics')})

    def test_an_overflow_without_a_fitting_boundary_carries_null(self):
        self.bare_overflow()
        gated = self.gate(0)
        summary = json.loads(gated.stdout)
        self.assertEqual((gated.returncode, summary['state'], summary['recommended_boundary']),
                         (3, 'decompose_required', None), gated.stderr)

    def test_invalid_input_is_one_reason_line(self):
        self.write('all.md', '# Plan without a forecast\n'); self.commit('break the plan')
        self.assert_refused(self.gate(0), 'review-feasibility: ')

    def test_capture_refuses_output_no_real_producer_emits(self):
        good = self.project(0).stdout
        authority = describe('review-package')
        over = json.loads(good); over['metrics']['root_bytes'] += 1
        cases = {
            'noncanonical': (good + b' ', 0), 'exit disagrees': (good, 3), 'unknown exit': (good, 1),
            'oversized': (b'x' * (authority.report_wire_max_bytes + 1), 0),
            'duplicate key': (b'{"a":1,"a":1}\n', 0), 'one metric drift': (canonical_bytes(over), 0)}
        for label, (raw, code) in cases.items():
            script = f'import sys; sys.stdout.buffer.write({raw!r}); sys.exit({code})'
            with self.subTest(label), self.assertRaises(GateError):
                capture([sys.executable, '-c', script], cwd=self.repo, authority=authority)
        script = 'import sys; sys.stderr.write("review-feasibility: boom\\n"); sys.exit(2)'
        with self.assertRaisesRegex(GateError, '^boom$'):
            capture([sys.executable, '-c', script], cwd=self.repo, authority=authority)


class ConfirmTest(GateFixture, unittest.TestCase):
    def test_confirm_reproduces_both_states(self):
        for build in (lambda: None, self.bare_overflow, self.oversize):
            build()
            gated = self.gate(0)
            confirmed = self.confirm(gated.stdout)
            self.assertEqual((confirmed.returncode, confirmed.stdout), (gated.returncode, gated.stdout),
                             confirmed.stderr)
            pretty = json.dumps(json.loads(gated.stdout), indent=2).encode()
            self.assertEqual(self.confirm(pretty).stdout, gated.stdout)

    def test_every_tamper_is_refused_by_field(self):
        self.oversize()
        summary = json.loads(self.gate(0).stdout)
        def tamper(edit):
            value = copy.deepcopy(summary); edit(value); return canonical_bytes(value)
        cases = [('extra', lambda v: v.update(extra=1)), ('kind', lambda v: v.pop('kind')),
                 ('state', lambda v: v.update(state='complete')),
                 ('completed_through', lambda v: v.update(completed_through=True)),
                 ('violations', lambda v: v.update(violations=[])),
                 ('recommended_boundary', lambda v: v['recommended_boundary'].update(tasks=[1]))]
        cases += [('metrics', lambda v, m=m: v['metrics'].update({m: v['metrics'][m] + 1})) for m in METRICS]
        cases += [(d, lambda v, d=d: v.update({d: v[d][:-1] + ('0' if v[d][-1] != '0' else '1')}))
                  for d in DIGESTS]
        for field, edit in cases:
            with self.subTest(field):
                self.assert_refused(self.confirm(tamper(edit)), field)
        self.assert_refused(self.confirm(canonical_bytes(summary), base=self.head), 'base')
        self.write('other.md', '# x\n'); self.commit('other')
        self.assert_refused(self.confirm(canonical_bytes(summary), plan=str(self.repo / 'other.md')), 'plan')
        self.assert_refused(self.confirm(canonical_bytes(summary)), 'mismatch')  # HEAD moved: stale head

    def test_input_is_read_strictly(self):
        raw = self.gate(0).stdout
        for bad in (b'{"a":1,"a":1}', b'[]', raw.replace(b'"completed_through":0', b'"completed_through":NaN'),
                    b' ' * 8193):
            with self.subTest(bad=bad[:40]):
                self.assert_refused(self.confirm(bad), 'review-feasibility: ')
        link = self.top / 'link.json'; target = self.top / 'summary.json'
        target.write_bytes(raw); link.symlink_to(target)
        self.assert_refused(self.invoke('confirm', '--plan', self.plan_path(), '--base', self.base,
                                        '--input', str(link)), 'review-feasibility: ')


if __name__ == '__main__':
    unittest.main()
