import json
import subprocess
import sys
import unittest
from pathlib import Path
import tests.test_review_feasibility as source_cases
from agent_tools.review_projection import ReconstructionUnavailable, reconstruct_owned

class ProofCases(source_cases.SourceProjectionFixture, unittest.TestCase):
    def test_independent_hunks_are_unproved_without_claiming_dependency(self):
        self.write('shared.txt', ''.join(f'line-{i}\n' for i in range(100)))
        prerequisite = self.commit('prerequisite', 1)
        lines = [f'line-{i}\n' for i in range(100)]
        lines[5] = 'excluded disjoint hunk\n'
        self.write('shared.txt', ''.join(lines)); self.commit('excluded', 1)
        lines[90] = 'selected disjoint hunk\n'
        self.write('shared.txt', ''.join(lines)); selected = self.commit('selected', 2)
        before = (self.git('status', '--porcelain'), self.git('write-tree'),
                  self.git('count-objects', '-v'))
        with self.assertRaises(ReconstructionUnavailable) as caught:
            with reconstruct_owned(self.repo, prerequisite, [selected]):
                self.fail('whole-path proof cannot establish this independent hunk')
        self.assertEqual(caught.exception.code, 'whole_path_preimage_unproved')
        self.assertEqual(caught.exception.commit, selected)
        self.assertIn('projection_unavailable', str(caught.exception))
        self.assertNotIn('depends on', str(caught.exception))
        self.assertEqual(before, (self.git('status', '--porcelain'),
            self.git('write-tree'), self.git('count-objects', '-v')))


class IndependentPositiveCases(source_cases.SourceProjectionFixture, unittest.TestCase):
    def test_cheaper_unrelated_descendant_is_excluded_with_real_standalone_parity(self):
        root = self.delivery['boundaries'][0]
        root['process_commit_subject_bytes'] = [120] * 30
        owned = {}; processes = {}
        for name, tasks, size in [('one', [1], 5000), ('two', [2], 10)]:
            boundary = source_cases.BoundaryTreeTest().row(name, 'all', tasks)
            boundary['process_commit_subject_bytes'] = []
            self.delivery['boundaries'].append(boundary)
            pkg = boundary['process_package']
            self.write(name + '.txt', 'x' * size + '\n')
            owned[name] = self.commit('product ' + name, tasks[0])
            self.write(pkg['spec'], '# Independent case\n')
            self.write(pkg['plan'], '# Plan\n\n## Task index\n\n'
                f'Task 1 — Case — {name}.txt — full — [task-1.md]({name}.tasks/task-1.md)\n')
            self.write(pkg['tasks'][0], '# Task 1\n')
            processes[name] = self.commit('process ' + name, boundaries=['all', name])
            for i, path in enumerate([pkg['spec'], pkg['plan'], *pkg['tasks']]):
                row = self.record(boundary['process_forecast_ids'][i], 0, path)
                row['bounds'][0]['boundary'] = name
                self.delivery['process_records'].append(row)
        self.checkpoint()
        before = (self.git('status', '--porcelain'), self.git('write-tree'), self.git('count-objects', '-v'))
        metrics = {}; trees = {}; records = {}
        for name in ('one', 'two'):
            separate = self.top / ('standalone-' + name)
            subprocess.run(['git', 'clone', '-q', '--no-local', str(self.repo), str(separate)],
                           env=self.env, check=True, capture_output=True)
            def sg(*args):
                return subprocess.run(['git', '-C', str(separate), *args], env=self.env,
                    check=True, capture_output=True).stdout
            sg('config', 'user.name', 'Fixture'); sg('config', 'user.email', 'fixture@example.test')
            sg('config', 'commit.gpgsign', 'false'); sg('checkout', '-q', '--detach', self.base)
            sg('cherry-pick', owned[name], processes[name])
            head = sg('rev-parse', 'HEAD').decode().strip()
            trees[name] = sg('rev-parse', 'HEAD^{tree}').decode().strip()
            directory = self.top / ('package-' + name); directory.mkdir()
            out = directory / 'review.json'
            produced = subprocess.run([sys.executable, '-m', 'agent_tools.review_package',
                str(separate / (name + '.md')), self.base, head, str(out)], cwd=separate,
                env=self.env, capture_output=True)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(out), '--format', 'json'], env=self.env, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            metrics[name] = json.loads(produced.stdout)['artifact']['metrics']
            self.assertEqual(metrics[name], json.loads(checked.stdout)['metrics'])
            manifest = json.loads(out.read_bytes())
            records[name] = b''.join((directory / r['path']).read_bytes() for r in manifest['shards'])
        self.assertLess(metrics['two']['total_bytes'], metrics['one']['total_bytes'])
        projected = self.project(0)
        self.assertEqual(projected.returncode, 3, projected.stderr)
        validated = self.invoke('validate-result', '--input', '-', '--producer-exit', '3', input=projected.stdout)
        self.assertEqual((validated.returncode, validated.stdout), (0, projected.stdout))
        chosen = json.loads(projected.stdout)['recommended_boundary']
        self.assertEqual(chosen['id'], 'one')
        self.assertEqual(chosen['tasks'], [1])
        self.assertEqual(chosen['actual_tree'], trees['one'])
        self.assertEqual(chosen['metrics'], metrics['one'])
        # Inspect the shared builder's records as well as its public recommendation.
        from agent_tools.review_actual import actual_inputs_from_trees
        from agent_tools.review_pack import ReviewLimits
        with reconstruct_owned(self.repo, self.base, [owned['one'], processes['one']]) as rebuilt:
            initial = next(actual_inputs_from_trees(rebuilt.repo, rebuilt.prerequisite_tree,
                rebuilt.result_tree, base=self.base, head=processes['one'], commits=rebuilt.commits,
                package_name='review.json', limits=ReviewLimits(16384, 65536, 8, 524288)))
            self.assertEqual(b''.join(r.payload for r in initial.records), records['one'])
        self.assertEqual(before, (self.git('status', '--porcelain'), self.git('write-tree'), self.git('count-objects', '-v')))
        # Completed projection has no future reserve: it must fit and equal actual production.
        fitted = self.project(2)
        self.assertEqual(fitted.returncode, 0, fitted.stderr)
        actual_metrics, _ = self.actual()
        self.assertEqual(json.loads(fitted.stdout)['metrics'], actual_metrics)


class RankedPositiveCases(source_cases.SourceProjectionFixture, unittest.TestCase):
    def snapshot(self):
        return tuple(self.git(*args) for args in [('rev-parse', 'HEAD'), ('status', '--porcelain'),
                                                ('write-tree',), ('count-objects', '-v')])

    def boundary(self, name, parent, tasks, *, size=20, deps=()):
        row = source_cases.BoundaryTreeTest().row(name, parent, tasks, deps)
        self.delivery['boundaries'].append(row)
        package = row['process_package']
        self.write(package['spec'], '# Independent acceptance\n' + 's' * size + '\n')
        self.write(package['plan'], '# Plan\n\n## Task index\n\n' + ''.join(
            f'Task {n} — Case — product.txt — full — [task-{n}.md]({name}.tasks/task-{n}.md)\n'
            for n in range(1, len(tasks) + 1)))
        for path in package['tasks']:
            self.write(path, '# Task\n')
        process = self.commit('process ' + name, boundaries=['all', name])
        for identity, path in zip(row['process_forecast_ids'],
                                  [package['spec'], package['plan'], *package['tasks']], strict=True):
            record = self.record(identity, 0, path)
            record['bounds'][0]['boundary'] = name
            self.delivery['process_records'].append(record)
        return row, process

    def standalone(self, name, owned, *, base=None):
        """Actual independent cherry-picks, publication and checker; no metric stubs."""
        from agent_tools.review_actual import actual_inputs_from_trees
        from agent_tools.review_pack import ReviewLimits
        base = base or self.base
        separate = self.top / ('standalone-' + name)
        subprocess.run(['git', 'clone', '-q', '--no-local', str(self.repo), str(separate)],
                       env=self.env, check=True, capture_output=True)
        def git(*args):
            return subprocess.run(['git', '-C', str(separate), *args], env=self.env,
                                  check=True, capture_output=True).stdout.decode().strip()
        git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.test')
        git('config', 'commit.gpgsign', 'false'); git('checkout', '-q', '--detach', base)
        git('cherry-pick', *owned)
        tree = git('rev-parse', 'HEAD^{tree}')
        directory = self.top / ('package-' + name); directory.mkdir()
        out = directory / 'review.json'
        produced = subprocess.run([sys.executable, '-m', 'agent_tools.review_package',
            str(separate / (name + '.md')), base, git('rev-parse', 'HEAD'), str(out)],
            cwd=separate, env=self.env, capture_output=True)
        self.assertIn(produced.returncode, (0, 3), produced.stderr)
        checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
            '--root', str(out), '--format', 'json'], env=self.env, capture_output=True)
        self.assertEqual(checked.returncode, produced.returncode, checked.stderr)
        metrics = json.loads(produced.stdout)['artifact']['metrics']
        self.assertEqual(metrics, json.loads(checked.stdout)['metrics'])
        manifest = json.loads(out.read_bytes())
        raw = b''.join((directory / shard['path']).read_bytes() for shard in manifest['shards'])
        with reconstruct_owned(self.repo, base, owned) as rebuilt:
            self.assertEqual(rebuilt.result_tree, tree)
            inputs = next(actual_inputs_from_trees(rebuilt.repo, rebuilt.prerequisite_tree, tree,
                base=base, head=owned[-1], commits=rebuilt.commits, package_name='review.json',
                limits=ReviewLimits(16384, 65536, 8, 524288)))
            self.assertEqual(b''.join(record.payload for record in inputs.records), raw)
        return metrics, tree

    def recommendation(self, completed=0):
        projected = self.project(completed)
        self.assertEqual(projected.returncode, 3, projected.stderr)
        checked = self.invoke('validate-result', '--input', '-', '--producer-exit', '3', input=projected.stdout)
        self.assertEqual((checked.returncode, checked.stdout), (0, projected.stdout))
        return json.loads(projected.stdout)['recommended_boundary']

    def test_smaller_task_count_wins_despite_larger_actual_bytes(self):
        self.delivery['boundaries'][0]['process_commit_subject_bytes'] = [120] * 30
        self.write('one.txt', 'one\n'); first = self.commit('product one', 1)
        self.write('two.txt', 'two\n'); second = self.commit('product two', 2)
        _, middle = self.boundary('mid', 'all', [1, 2])
        _, smaller = self.boundary('one', 'mid', [1], size=16000)
        self.boundary('two', 'mid', [2])
        self.checkpoint()
        before = self.snapshot()
        mid_metrics, _ = self.standalone('mid', [first, second, middle])
        one_metrics, one_tree = self.standalone('one', [first, smaller])
        self.assertGreater(one_metrics['total_bytes'], mid_metrics['total_bytes'])
        chosen = self.recommendation()
        self.assertEqual((chosen['id'], chosen['tasks']), ('one', [1]))
        self.assertEqual((chosen['metrics'], chosen['actual_tree']), (one_metrics, one_tree))
        self.assertEqual(before, self.snapshot())

    def test_equal_task_count_uses_unequal_measured_bytes(self):
        self.delivery['boundaries'][0]['process_commit_subject_bytes'] = [120] * 30
        self.write('product.txt', 'product\n'); product = self.commit('product one', 1)
        _, alpha = self.boundary('alpha', 'all', [1, 2], size=12000)
        _, omega = self.boundary('omega', 'alpha', [1, 2], size=10)
        self.checkpoint()
        before = self.snapshot()
        a, _ = self.standalone('alpha', [product, alpha])
        b, tree = self.standalone('omega', [product, omega])
        self.assertGreater(a['total_bytes'], b['total_bytes'])
        chosen = self.recommendation()
        self.assertEqual(chosen['id'], 'omega')
        self.assertEqual((chosen['metrics'], chosen['actual_tree']), (b, tree))
        self.assertEqual(before, self.snapshot())

    def test_equal_tasks_and_actual_bytes_follow_committed_boundary_order(self):
        self.delivery['boundaries'][0]['process_commit_subject_bytes'] = [120] * 30
        self.write('product.txt', 'product\n'); product = self.commit('product one', 1)
        _, alpha = self.boundary('alpha', 'all', [1, 2])
        _, omega = self.boundary('omega', 'alpha', [1, 2])
        self.checkpoint()
        before = self.snapshot()
        a, a_tree = self.standalone('alpha', [product, alpha])
        b, b_tree = self.standalone('omega', [product, omega])
        self.assertEqual(a, b)
        chosen = self.recommendation()
        self.assertEqual((chosen['id'], chosen['metrics'], chosen['actual_tree']), ('alpha', a, a_tree))
        self.assertEqual(before, self.snapshot())
        self.delivery['boundaries'][1:] = list(reversed(self.delivery['boundaries'][1:]))
        self.checkpoint()
        before = self.snapshot()
        chosen = self.recommendation()
        self.assertEqual((chosen['id'], chosen['metrics'], chosen['actual_tree']), ('omega', b, b_tree))
        self.assertEqual(before, self.snapshot())

    def test_sequential_shared_path_prerequisite_has_standalone_record_parity(self):
        self.delivery['boundaries'][0]['process_commit_subject_bytes'] = [120] * 30
        self.write('shared.txt', 'first\n'); first = self.commit('product one', 1)
        self.boundary('one', 'all', [1])
        self.write('shared.txt', 'second\n'); second = self.commit('product two', 2)
        row, process = self.boundary('two', 'all', [2], deps=['one'])
        row['prerequisite'].update(commit=first, tree=self.git('rev-parse', first + '^{tree}'))
        self.checkpoint()
        before = self.snapshot()
        metrics, tree = self.standalone('two', [second, process], base=first)
        chosen = self.recommendation(1)
        self.assertEqual((chosen['id'], chosen['prerequisite_commit']), ('two', first))
        self.assertEqual((chosen['metrics'], chosen['actual_tree']), (metrics, tree))
        self.assertEqual(before, self.snapshot())
        # Matching commit/tree cannot excuse an excluded completed owner.
        row['prerequisite'].update(commit=second, tree=self.git('rev-parse', second + '^{tree}'))
        self.checkpoint(); before = self.snapshot()
        self.assert_refused(self.project(1))
        self.assertEqual(before, self.snapshot())

    def test_no_fitting_declared_candidate_returns_null(self):
        self.write('one.txt', 'x' * 66000 + '\n'); self.commit('product one', 1)
        self.write('two.txt', 'y' * 66000 + '\n'); self.commit('product two', 2)
        self.boundary('one', 'all', [1]); self.boundary('two', 'all', [2])
        self.checkpoint(); before = self.snapshot()
        self.assertIsNone(self.recommendation())
        completed = self.project(2)
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['metrics'], self.actual()[0])
        self.assertEqual(before, self.snapshot())


class NeutralRefusalCases(source_cases.SourceProjectionFixture, unittest.TestCase):
    def test_dependency_and_ambiguous_context_refuse_with_same_neutral_proof(self):
        for repeated in (False, True):
            with self.subTest(repeated=repeated):
                self.write('shared.txt', ('same\n' * 100) if repeated else 'original\n')
                prerequisite = self.commit('prerequisite', 1)
                self.write('shared.txt', ('same\n' * 200) if repeated else 'excluded\n')
                self.commit('excluded', 1)
                self.write('shared.txt', ('same\n' * 150 + 'selected\n' + 'same\n' * 49)
                           if repeated else 'excluded plus selected\n')
                selected = self.commit('selected', 2)
                before = (self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain'),
                          self.git('write-tree'), self.git('count-objects', '-v'))
                with self.assertRaises(ReconstructionUnavailable) as caught:
                    reconstruct_owned(self.repo, prerequisite, [selected])
                self.assertEqual(caught.exception.code, 'whole_path_preimage_unproved')
                self.assertEqual(caught.exception.commit, selected)
                self.assertNotIn('depends on', str(caught.exception))
                self.assertEqual(before, (self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain'),
                                          self.git('write-tree'), self.git('count-objects', '-v')))

    def test_invalid_identities_and_duplicates_are_not_proof_refusals(self):
        from agent_tools.review_forecast import ForecastError
        from agent_tools.review_actual import GenerationError
        self.write('selected.txt', 'selected\n'); selected = self.commit('selected', 1)
        for base, owned in ((self.base, [selected, selected]), (self.base, ['0' * 40]),
                            (self.git('rev-parse', self.base + '^{tree}'), [selected])):
            with self.subTest(base=base, owned=owned):
                try:
                    reconstruct_owned(self.repo, base, owned)
                except (ForecastError, GenerationError) as exc:
                    self.assertNotIsInstance(exc, ReconstructionUnavailable)
                else:
                    self.fail('invalid evidence accepted as reconstruction')

    def test_owned_root_and_unproved_merge_have_distinct_typed_codes(self):
        start = self.head
        root = self.git('commit-tree', self.git('rev-parse', start + '^{tree}'), '-m', 'isolated root')
        branch = self.git('branch', '--show-current')
        self.git('switch', '-qc', 'side')
        self.write('side', 'side\n'); self.commit('side', 1)
        self.git('switch', '-q', branch)
        self.write('main', 'main\n'); self.commit('main', 1)
        self.git('merge', '--no-ff', '-qm', 'merge', 'side')
        merge = self.git('rev-parse', 'HEAD')
        before = (self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain'),
                  self.git('write-tree'), self.git('count-objects', '-v'))
        for selected, code in ((root, 'owned_root_unproved'), (merge, 'merge_effects_unproved')):
            with self.subTest(code=code), self.assertRaises(ReconstructionUnavailable) as caught:
                reconstruct_owned(self.repo, start, [selected])
            self.assertEqual((caught.exception.code, caught.exception.commit), (code, selected))
            self.assertIn('projection_unavailable', str(caught.exception))
            self.assertNotIn('depends on', str(caught.exception))
        self.assertEqual(before, (self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain'),
                                  self.git('write-tree'), self.git('count-objects', '-v')))
