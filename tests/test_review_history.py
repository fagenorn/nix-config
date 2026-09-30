import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from tests.test_review_feasibility import SourceProjectionFixture
from agent_tools.review_forecast import ForecastError, edge_facts, load_plan
from agent_tools.review_projection import ReconstructionUnavailable, reconstruct_owned, _prerequisite
from agent_tools.review_budget import describe

class OriginalHistoryTest(SourceProjectionFixture, unittest.TestCase):
    def snapshot(self):
        return tuple(sorted((str(p.relative_to(self.repo)), hashlib.sha256(p.read_bytes()).hexdigest())
                            for p in self.repo.rglob('*') if p.is_file()))

    def seed_owned(self):
        self.write('owned.txt', 'first\n')
        first = self.commit('owned first', 1)
        self.write('owned.txt', 'second\n')
        second = self.commit('owned second', 2)
        self.checkpoint()
        return first, second

    def producer(self):
        return subprocess.run([sys.executable, '-m', 'agent_tools.review_package',
            str(self.repo / 'all.md'), self.base, self.head, str(self.top / 'actual.json')],
            cwd=self.repo, env=self.env, capture_output=True)

    def assert_invalid(self, result):
        self.assertEqual((result.returncode, result.stdout), (2, b''), result.stderr)
        self.assertNotIn(b'projection_unavailable', result.stderr)

    def assert_actual_invalid(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        if result.stdout:
            value = json.loads(result.stdout)
            self.assertEqual((value['state'], value['artifact']), ('failed', None))
        self.assertNotIn(b'projection_unavailable', result.stderr)

    def test_raw_parent_order_and_nonparent_edge_are_not_traversal_claims(self):
        from agent_tools.review_git import original_commit, original_edge, HistoryError
        first, second = self.seed_owned()
        raw = subprocess.check_output(['git', '-C', str(self.repo), 'cat-file', 'commit', second])
        parent_headers = tuple(line[7:].decode() for line in raw.split(b'\n\n', 1)[0].splitlines()
                               if line.startswith(b'parent '))
        evidence = original_commit(self.repo, second)
        self.assertEqual((evidence.oid, evidence.parents, evidence.raw), (second, parent_headers, raw))
        self.assertEqual(evidence.tree, self.git('rev-parse', second + '^{tree}'))
        original_edge(self.repo, first, second, 1)
        with self.assertRaises(HistoryError):
            original_edge(self.repo, self.base, second, 1)
        with self.assertRaises(HistoryError):
            original_edge(self.repo, first, second, 2)
        with self.assertRaises(ForecastError):
            edge_facts(self.repo, self.base, second, 1)

    def test_redundant_graft_is_invalid_at_actual_generic_edge_and_reconstruction(self):
        first, second = self.seed_owned()
        raw = subprocess.check_output(['git', '-C', str(self.repo), 'cat-file', 'commit', second])
        members = self.git('rev-list', self.base + '..' + self.head).splitlines()
        graft = self.repo / '.git/info/grafts'
        graft.write_text(f'{second} {first} {self.base}\n')
        self.assertEqual(raw, subprocess.check_output(['git', '-C', str(self.repo), 'cat-file', 'commit', second]))
        self.assertEqual(set(members), set(self.git('rev-list', self.base + '..' + self.head).splitlines()))
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        with self.assertRaises(ForecastError):
            edge_facts(self.repo, first, second, 1)
        with self.assertRaises(ForecastError) as caught:
            with reconstruct_owned(self.repo, first, [second]):
                self.fail('virtual parent accepted')
        self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
        self.assertEqual(before, self.snapshot())

    def test_replacement_and_alternate_graft_environment_are_invalid(self):
        first, second = self.seed_owned()
        self.git('replace', '--graft', second, first, self.base)
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        self.assertEqual(before, self.snapshot())
        self.git('replace', '-d', second)
        graft = self.top / 'alternate-grafts'
        graft.write_text(f'{second} {first} {self.base}\n')
        self.env['GIT_GRAFT_FILE'] = str(graft)
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(ForecastError) as caught:
                with reconstruct_owned(self.repo, first, [second]):
                    self.fail('environment graft accepted')
            self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
        self.assertEqual(before, self.snapshot())

    def test_prerequisite_rechecks_original_graph_after_plan_load(self):
        first, second = self.seed_owned()
        with patch.dict(os.environ, self.env, clear=True):
            plan = load_plan(self.repo, self.repo / 'all.md', self.base, self.head,
                             describe('review-package'))
            boundary = dict(plan.boundaries[0], prerequisite=dict(kind='completed-tasks',
                tasks=[1], commit=first, tree=self.git('rev-parse', first + '^{tree}')))
            self.assertEqual(_prerequisite(plan, boundary, 1), first)
            parent = self.git('rev-parse', first + '^')
            (self.repo / '.git/info/grafts').write_text(f'{first} {parent} {self.base}\n')
            before = self.snapshot()
            with self.assertRaises(ForecastError) as caught:
                _prerequisite(plan, boundary, 1)
            self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
            self.assertEqual(before, self.snapshot())

    def test_invalid_later_edge_precedes_honest_unsupported_earlier_effect(self):
        self.write('shared.txt', 'seed\nexcluded\n')
        excluded = self.commit('excluded edit', 1)
        self.write('shared.txt', 'seed\nexcluded\nselected\n')
        selected = self.commit('selected needs excluded', 2)
        self.write('later.txt', 'later\n')
        later = self.commit('later', 2)
        (self.repo / '.git/info/grafts').write_text(f'{later} {selected} {self.base}\n')
        before = self.snapshot()
        with self.assertRaises(ForecastError) as caught:
            with reconstruct_owned(self.repo, self.base, [selected, later]):
                self.fail('invalid later edge hidden by earlier refusal')
        self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
        self.assertEqual(before, self.snapshot())

    def test_parent_deletion_shallow_and_alternate_replace_namespace_fail_closed(self):
        first, second = self.seed_owned()
        cases = [('deleted-parent', str(second) + '\n', {}),
                 ('shallow-file', None, {}),
                 ('alternate-shallow', None, {})]
        for label, graft_text, env_update in cases:
            with self.subTest(route=label):
                if graft_text is not None:
                    metadata = self.repo / '.git/info/grafts'
                    metadata.write_text(graft_text)
                elif label == 'shallow-file':
                    metadata = self.repo / '.git/shallow'
                    metadata.write_text(second + '\n')
                else:
                    metadata = self.top / 'shallow'
                    metadata.write_text(second + '\n')
                    env_update = {'GIT_SHALLOW_FILE': str(metadata)}
                before = self.snapshot()
                saved = dict(self.env)
                self.env.update(env_update)
                try:
                    self.assert_invalid(self.project())
                    self.assert_actual_invalid(self.producer())
                    with patch.dict(os.environ, self.env, clear=True):
                        with self.assertRaises(ForecastError) as caught:
                            with reconstruct_owned(self.repo, first, [second]):
                                self.fail('virtualization accepted')
                        self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
                    self.assertEqual(before, self.snapshot())
                finally:
                    self.env = saved
                    metadata.unlink()
        self.git('replace', '--graft', second, first, self.base)
        replacement = self.git('rev-parse', 'refs/replace/' + second)
        self.git('replace', '-d', second)
        self.git('update-ref', 'refs/virtual/' + second, replacement)
        self.env['GIT_REPLACE_REF_BASE'] = 'refs/virtual/'
        self.assertEqual(self.git('rev-list', '--parents', '-n', '1', second).split()[1:],
                         [first, self.base])
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        self.assertEqual(before, self.snapshot())

    def test_original_merge_order_is_authenticated(self):
        from agent_tools.review_git import original_commit, original_edge, HistoryError
        first, second = self.seed_owned()
        tree = self.git('rev-parse', second + '^{tree}')
        merged = self.git('commit-tree', tree, '-p', second, '-p', self.base, '-m', 'merge')
        self.assertEqual(original_commit(self.repo, merged).parents, (second, self.base))
        original_edge(self.repo, second, merged, 1)
        original_edge(self.repo, self.base, merged, 2)
        with self.assertRaises(HistoryError):
            original_edge(self.repo, self.base, merged, 1)
        graft = self.repo / '.git/info/grafts'
        graft.write_text(f'{merged} {self.base} {second}\n')
        before = self.snapshot()
        with self.assertRaises(HistoryError):
            original_edge(self.repo, second, merged, 1)
        with self.assertRaises(ForecastError) as caught:
            with reconstruct_owned(self.repo, second, [merged]):
                self.fail('reordered merge accepted')
        self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
        self.assertEqual(before, self.snapshot())

    def test_rehashed_original_edge_mutation_is_invalid_at_prerequisite_boundary(self):
        from dataclasses import replace
        from agent_tools.canonical import telemetry_digest
        from agent_tools.review_actual import git_diff, _split_diff
        from agent_tools.review_forecast import tree_entry
        from agent_tools.review_git import HistoryError
        first, second = self.seed_owned()
        with patch.dict(os.environ, self.env, clear=True):
            plan = load_plan(self.repo, self.repo / 'all.md', self.base, self.head,
                             describe('review-package'))
            original = plan.ownership
            checkpoint = original.ordered_commits.index(original.evidence_head)
            def envelope(ownership):
                return dict(evidence=plan.delivery['actual_evidence'],
                    task_ranges=[task['actual_ranges'] for task in plan.tasks],
                    commits=[dict(commit=c, owner=ownership.owners[c],
                                  boundaries=list(ownership.process_memberships.get(c, ())))
                             for c in ownership.ordered_commits],
                    edges=list(ownership.edges),
                    metadata_tail=list(ownership.ordered_commits[checkpoint + 1:]))
            self.assertEqual(telemetry_digest(envelope(original)), original.digest)
            boundary = dict(plan.boundaries[0], prerequisite=dict(kind='completed-tasks',
                tasks=[1], commit=first, tree=self.git('rev-parse', first + '^{tree}')))
            before = self.snapshot()
            self.assertEqual(_prerequisite(plan, boundary, 1), first)
            self.assertEqual(before, self.snapshot())
            edges = json.loads(json.dumps(original.edges))
            target = next(row for row in edges if row['commit'] == first)
            self.assertNotEqual(target['parent'], self.base)
            # Fresh facts for the false pair: only original parent membership is false.
            names = git_diff(self.repo, self.base, first, '--name-status', '-z').split(b'\0')
            self.assertEqual(names.pop(), b'')
            facts = []
            while names:
                operation = names.pop(0).decode('ascii')
                old = names.pop(0).decode('utf-8')
                new = names.pop(0).decode('utf-8') if operation == 'R100' else old
                self.assertIn(operation, ('A', 'M', 'D', 'T', 'R100'))
                facts.append(dict(operation=operation, path=new, old_path=old,
                    before=tree_entry(self.repo, self.base, old),
                    after=tree_entry(self.repo, first, new)))
            chunks = _split_diff(git_diff(self.repo, self.base, first, '--binary', '-U10'))
            self.assertEqual(len(chunks), len(facts))
            for fact, chunk in zip(facts, chunks, strict=True):
                fact.update(record_bytes=len(chunk),
                            record_sha256='sha256:' + hashlib.sha256(chunk).hexdigest())
            target.update(parent=self.base, parent_ordinal=1, records=facts)
            altered = replace(original, edges=tuple(edges))
            altered = replace(altered, digest=telemetry_digest(envelope(altered)))
            self.assertEqual(telemetry_digest(envelope(altered)), altered.digest)
            self.assertNotEqual(altered.digest, original.digest)
            before = self.snapshot()
            with self.assertRaises(ForecastError) as caught:
                _prerequisite(replace(plan, ownership=altered), boundary, 1)
            self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
            self.assertIsInstance(caught.exception.__cause__, HistoryError)
            self.assertEqual(caught.exception.__cause__.code, 'original_parent_mismatch')
            self.assertEqual(before, self.snapshot())

    def test_missing_original_parent_object_fails_without_source_writes(self):
        first, second = self.seed_owned()
        parent_object = self.repo / '.git/objects' / first[:2] / first[2:]
        self.assertTrue(parent_object.is_file())
        parent_object.unlink()
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        with self.assertRaises(ForecastError) as caught:
            with reconstruct_owned(self.repo, self.base, [second]):
                self.fail('missing original parent accepted')
        self.assertNotIsInstance(caught.exception, ReconstructionUnavailable)
        self.assertEqual(before, self.snapshot())

    def test_raw_object_hash_is_independent_of_unchanged_parent_headers(self):
        import zlib
        from agent_tools.review_git import original_commit, HistoryError
        first, second = self.seed_owned()
        self.assertEqual(original_commit(self.repo, second).parents, (first,))
        path = self.repo / '.git/objects' / second[:2] / second[2:]
        original = zlib.decompress(path.read_bytes())
        altered = original.replace(b'owned second', b'forged thing')
        self.assertNotEqual(original, altered)
        path.chmod(0o600)
        path.write_bytes(zlib.compress(altered))
        before = self.snapshot()
        with self.assertRaises(HistoryError) as caught:
            original_commit(self.repo, second)
        self.assertEqual(caught.exception.code, 'original_object_identity_mismatch')
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        self.assertEqual(before, self.snapshot())

    def test_environment_config_can_reenable_replacement_traversal(self):
        first, second = self.seed_owned()
        self.git('replace', '--graft', second, first, self.base)
        self.git('config', 'core.useReplaceRefs', 'false')
        self.assertEqual(self.git('rev-list', '--parents', '-n', '1', second).split()[1:], [first])
        self.env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.useReplaceRefs', GIT_CONFIG_VALUE_0='true')
        self.assertEqual(self.git('rev-list', '--parents', '-n', '1', second).split()[1:], [first, self.base])
        before = self.snapshot()
        self.assert_invalid(self.project())
        self.assert_actual_invalid(self.producer())
        self.assertEqual(before, self.snapshot())

    def test_source_actual_library_requires_full_object_identities(self):
        from agent_tools.review_actual import actual_inputs, GenerationError
        from agent_tools.review_pack import ReviewLimits
        self.seed_owned()
        with self.assertRaises(GenerationError):
            tuple(actual_inputs(self.repo, self.base[:12], self.head, 'review.json',
                                ReviewLimits(16384, 65536, 8, 524288)))

    def test_rehashed_commit_graph_tree_cannot_replace_original_facts(self):
        first, second = self.seed_owned()
        trees = [self.git('rev-parse', oid + '^{tree}') for oid in (first, second)]
        expected = edge_facts(self.repo, first, second, 1)
        self.assertTrue(expected['records'])
        with reconstruct_owned(self.repo, first, [second]) as clean:
            expected_tree, expected_edges = clean.result_tree, clean.ordered_edges
        self.assertEqual(expected_tree, trees[1])
        self.git('commit-graph', 'write', '--reachable')
        graph = self.repo / '.git/objects/info/commit-graph'
        original = graph.read_bytes()
        self.assertEqual(original[:-20].count(bytes.fromhex(trees[1])), 1)
        changed = original[:-20].replace(bytes.fromhex(trees[1]), bytes.fromhex(trees[0]))
        graph.chmod(0o600)
        graph.write_bytes(changed + hashlib.sha1(changed).digest())
        self.assertNotEqual(original, graph.read_bytes())
        before = self.snapshot()
        self.assertEqual(edge_facts(self.repo, first, second, 1), expected)
        with reconstruct_owned(self.repo, first, [second]) as rebuilt:
            self.assertEqual(rebuilt.result_tree, expected_tree)
            self.assertEqual(rebuilt.ordered_edges, expected_edges)
        self.assertEqual(before, self.snapshot())
