import subprocess
import unittest
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

    def test_rebuilt_commit_subjects_ignore_log_show_signature(self):
        start = self.head
        self.write('selected', 'selected effect\n')
        self.commit('selected', 1)
        verifier = self.top / 'verify-signature'
        verifier.write_text("#!/bin/sh\necho 'gpg: Good signature from fixture' >&2\n")
        verifier.chmod(0o755)
        self.git('config', 'gpg.program', str(verifier))
        self.git('config', 'log.showSignature', 'true')
        header, _, message = self.git('cat-file', 'commit', 'HEAD').partition('\n\n')
        signed = header + '\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n fixture\n -----END PGP SIGNATURE-----\n\n' + message + '\n'
        forged = subprocess.run(['git', '-C', str(self.repo), 'hash-object', '-t', 'commit', '-w', '--stdin'],
                                input=signed, check=True, capture_output=True, text=True).stdout.strip()
        with reconstruct_owned(self.repo, start, [forged]) as rebuilt:
            self.assertEqual([row['subject'] for row in rebuilt.commits], ['selected'])


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
