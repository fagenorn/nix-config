import unittest
from agent_tools.review_forecast import ForecastError, tree_entry, validate_boundaries

class BoundaryTreeTest(unittest.TestCase):
    def row(self, name, parent, tasks, deps=()):
        return dict(id=name, parent=parent, tasks=tasks,
                    acceptance="Independent repository acceptance", depends_on=list(deps),
                    prerequisite={"kind": "delivery-base"} if not deps else
                        {"kind": "completed-tasks", "tasks": [1], "commit": None, "tree": None},
                    process_package={"spec": name + "-spec.md", "plan": name + ".md",
                        "tasks": [name + ".tasks/task-" + str(i) + ".md" for i in range(1, len(tasks) + 1)]},
                    process_forecast_ids=[name + "-process-" + str(i) for i in range(len(tasks) + 2)],
                    process_commit_subject_bytes=[])

    def test_disconnected_cycle_and_dependency_cycle_are_refused(self):
        good = [self.row("all", None, [1, 2]), self.row("one", "all", [1]),
                self.row("two", "all", [2], ["one"])]
        self.assertEqual([r["id"] for r in validate_boundaries(good, 2, "all")],
                         ["all", "one", "two"])
        disconnected = good + [self.row("x", "y", [1]), self.row("y", "x", [1])]
        with self.assertRaises(ForecastError):
            validate_boundaries(disconnected, 2, "all")
        cyclic = [self.row("all", None, [1, 2]), self.row("one", "all", [1], ["two"]),
                  self.row("two", "all", [2], ["one"])]
        with self.assertRaises(ForecastError):
            validate_boundaries(cyclic, 2, "all")

import copy
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch


class SharedPackingPolicyTest(unittest.TestCase):
    def test_shared_policy_identity_and_mutation_refusal(self):
        from agent_tools.canonical import telemetry_digest
        from agent_tools.review_actual import PACKING_POLICY, PACKING_POLICY_SHA256, select_candidate, GenerationError
        from agent_tools.review_pack import ReviewLimits
        self.assertEqual(PACKING_POLICY_SHA256, telemetry_digest(PACKING_POLICY))
        self.assertEqual(PACKING_POLICY['initial'], {'context_lines': 10, 'strategy': 'sequential'})
        self.assertEqual([r['context_lines'] for r in PACKING_POLICY['adaptive']], [7, 5, 3, 1, 0])
        for group, key, changed in ((PACKING_POLICY, 'fallback', 'last'),
                (PACKING_POLICY['forecast_measurement'], 'subject_json_bytes_per_reserved_byte', 5)):
            previous = group[key]
            try:
                group[key] = changed
                with self.assertRaises(GenerationError):
                    select_candidate([], ReviewLimits(100, 100, 8, 1000))
            finally:
                group[key] = previous


class RecordPolicyDomainTest(unittest.TestCase):
    """Issue 569: the retained domain's record policy v1 is frozen beside the living policy."""

    def test_frozen_v1_identities_and_the_closed_policy_set(self):
        from agent_tools.canonical import telemetry_digest
        from agent_tools.review_actual import (PACKING_POLICY, PACKING_POLICY_V1, PACKING_POLICY_V1_SHA256,
            RECORD_POLICY, RECORD_POLICY_V1, RECORD_POLICY_V1_SHA256, GenerationError, git_diff)
        self.assertEqual(RECORD_POLICY_V1_SHA256,
                         'sha256:73cc5609e8a395d33a210b20f413a72179300475b2f6d1c55fed097c7f6ee63b')
        self.assertEqual(PACKING_POLICY_V1_SHA256,
                         'sha256:fbb7b821b21015c5e56a4829c0c33dd2e7233a09a5826287cc563634098b43bf')
        self.assertEqual(telemetry_digest(RECORD_POLICY_V1), RECORD_POLICY_V1_SHA256)
        self.assertEqual(telemetry_digest(PACKING_POLICY_V1), PACKING_POLICY_V1_SHA256)
        self.assertEqual(PACKING_POLICY_V1['record_policy_sha256'], RECORD_POLICY_V1_SHA256)
        self.assertEqual({k: v for k, v in PACKING_POLICY_V1.items() if k != 'record_policy_sha256'},
                         {k: v for k, v in PACKING_POLICY.items() if k != 'record_policy_sha256'})
        self.assertIsNot(RECORD_POLICY_V1, RECORD_POLICY)
        empty = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # refused before any repository read
        for policy in (dict(RECORD_POLICY), dict(RECORD_POLICY_V1), {}):
            with self.subTest(policy=policy.get('kind')), \
                    self.assertRaisesRegex(GenerationError, 'unsupported record policy'):
                git_diff(Path('.'), empty, empty, '--name-only', '-z', record_policy=policy)
        for group, key, label in ((RECORD_POLICY_V1, 'kind', 'unsupported record policy'),
                                  (PACKING_POLICY_V1, 'fallback', 'unsupported packing policy')):
            previous = group[key]
            try:
                group[key] = 'mutated'
                with self.subTest(key=key), self.assertRaisesRegex(GenerationError, label):
                    git_diff(Path('.'), empty, empty, '--name-only', '-z', record_policy=RECORD_POLICY_V1)
            finally:
                group[key] = previous

    def test_living_policy_is_v2_with_a_fifty_percent_rename_threshold(self):
        from agent_tools.review_actual import (PACKING_POLICY, PACKING_POLICY_SHA256, PACKING_POLICY_V1_SHA256,
            RECORD_POLICY, RECORD_POLICY_SHA256, RECORD_POLICY_V1)
        self.assertEqual(RECORD_POLICY, {**RECORD_POLICY_V1, 'kind': 'review-git-records/v2',
                                         'diff_args': ['--find-renames=50%', *RECORD_POLICY_V1['diff_args'][1:]]})
        self.assertEqual(RECORD_POLICY_V1['diff_args'][0], '--find-renames=100%')
        self.assertEqual(RECORD_POLICY['git_config'], ['-c', 'diff.renames=true', '-c', 'diff.renameLimit=0',
                                                       '-c', 'core.quotePath=true'])
        self.assertEqual((PACKING_POLICY['kind'], PACKING_POLICY['record_policy_sha256']),
                         ('review-packing/v1', RECORD_POLICY_SHA256))
        self.assertNotEqual(PACKING_POLICY_SHA256, PACKING_POLICY_V1_SHA256)
        self.assertEqual(PACKING_POLICY['adaptive_violations'], ['member_count', 'aggregate_bytes'])

    def test_operation_rule_follows_each_policy_threshold(self):
        from agent_tools.review_actual import RECORD_POLICY, RECORD_POLICY_V1, GenerationError, _record_operations
        accepted = ((RECORD_POLICY, b'R050\0old\0new\0', ['new'], ('R050',)),
                    (RECORD_POLICY, b'R100\0old\0new\0M\0kept\0', ['new', 'kept'], ('R100', 'M')),
                    (RECORD_POLICY_V1, b'R100\0old\0new\0', ['new'], ('R100',)),
                    (RECORD_POLICY_V1, b'A\0a\0D\0d\0T\0t\0', ['a', 'd', 't'], ('A', 'D', 'T')))
        for policy, raw, paths, expected in accepted:
            with self.subTest(raw=raw, policy=policy['kind']):
                self.assertEqual(_record_operations(raw, paths, policy), expected)
        refused = ((RECORD_POLICY, b'R049\0old\0new\0', ['new']),
                   (RECORD_POLICY_V1, b'R099\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R101\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R50\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'C100\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R100\0old\0new\0extra\0', ['new', 'extra']),
                   (RECORD_POLICY, b'R100\0old\0', ['old']))
        for policy, raw, paths in refused:
            with self.subTest(raw=raw, policy=policy['kind']), self.assertRaises(GenerationError):
                _record_operations(raw, paths, policy)


class SourceProjectionFixture:
    """All command fixtures use actual Git objects and source subprocesses."""
    plan_stem = 'all'
    seed = {}  # extra base files: path -> text

    # What `_build` leaves on the instance besides its directory; each test takes a deep copy (issue 613).
    _STATE = ('ranges', 'base', 'head', 'tasks', 'delivery')

    @classmethod
    def setUpClass(cls):
        """Build the fixture once per class into a template that every test copies (issue 613)."""
        super().setUpClass()
        template = tempfile.TemporaryDirectory()
        cls.addClassCleanup(template.cleanup)
        builder = cls.__new__(cls)
        builder._enter(Path(template.name))
        builder._build()
        cls._template = (Path(template.name), {name: getattr(builder, name) for name in cls._STATE})

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        template, state = self._template
        shutil.copytree(template, self.scratch.name, symlinks=True, dirs_exist_ok=True)
        self._enter(Path(self.scratch.name))
        for name, value in state.items():
            setattr(self, name, copy.deepcopy(value))

    def _enter(self, top):
        """Point the instance at the fixture directory `top`: its repository and its budget home."""
        self.top = top
        self.repo = self.top / 'repo'
        source = Path(__file__).resolve().parents[1]
        home = self.top / 'home'
        legacy = source / 'home/common/agent-skills'
        self.env = dict(os.environ, HOME=str(home), PYTHONPATH=str(source / 'python'),
                        PATH=str(legacy / 'scripts') + os.pathsep + os.environ['PATH'])

    def _build(self):
        """The fixture: a budget home and a repository with its base, process and checkpoint commits."""
        source = Path(__file__).resolve().parents[1]
        home, legacy = self.top / 'home', source / 'home/common/agent-skills'
        (home / '.agents/lib/python').mkdir(parents=True)
        (home / '.agents/share').mkdir(parents=True)
        (home / '.agents/lib/python/artifact_budget.py').symlink_to(legacy / 'scripts/artifact_budget.py')
        (home / '.agents/share/artifact-budget-policy.json').symlink_to(legacy / 'artifact-budget-policy.json')
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'commit.gpgsign', 'false')
        self.write('shared.txt', 'seed\n')
        self.write('delete.txt', 'gone later\n')
        for path, content in self.seed.items():
            self.write(path, content)
        self.ranges = []
        self.base = self.commit('base')
        self.ranges.clear()
        self.tasks = [dict(schema_version=3, kind='review-feasibility-task', task=dict(
            id=n, commit_subject_bytes=[], actual_ranges=[], records=[])) for n in (1, 2)]
        row = BoundaryTreeTest().row('all', None, [1, 2])
        row['process_package'] = dict(spec=self.plan_stem + '-spec.md', plan=self.plan_stem + '.md',
            tasks=[f'{self.plan_stem}.tasks/task-{n}.md' for n in (1, 2)])
        self.delivery = dict(schema_version=3, kind='review-feasibility-delivery', delivery_base=self.base,
            proposed_boundary='all', boundaries=[row], process_records=[], derived_from=None,
            actual_evidence=dict(kind='git-range-ownership/v1', head=self.base,
                tree=self.git('rev-parse', self.base + '^{tree}'), process_ranges=[]))
        for i, path in enumerate([row['process_package']['spec'], row['process_package']['plan'],
                                  *row['process_package']['tasks']]):
            self.delivery['process_records'].append(self.record(f'all-process-{i}', 0, path))
        self.emit()
        self.commit('process')
        self.checkpoint()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.env,
            check=True, capture_output=True, text=True).stdout.strip()

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    def commit(self, subject, owner=0, boundaries=None):
        previous = getattr(self, 'head', None)
        self.git('add', '-A')
        self.git('commit', '--allow-empty', '-qm', subject)
        head = self.git('rev-parse', 'HEAD')
        if previous:
            self.ranges.append((owner, dict(base=previous, head=head), boundaries or ['all']))
        self.head = head
        return head

    def record(self, name, owner, path, *, change='add', size=1, added=1, deleted=0, horizon=2, covers=None):
        return dict(id=name, owner=owner, path=path, change=change, last_task=horizon,
            bounds=[dict(boundary='all', added_lines=added, deleted_lines=deleted, record_bytes=size,
                         support=dict(kind='authored-cumulative/v1', covers=covers or [name]))])

    def emit(self):
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        stem = self.plan_stem
        self.write(stem + '-spec.md', '# Spec\n')
        self.write(stem + '.md', '# Plan\n\n## Task index\n\n' + '\n'.join(
            f'Task {n} — Case — shared.txt — full — [task-{n}.md]({stem}.tasks/task-{n}.md)'
            for n in range(1, len(self.tasks) + 1))
            + '\n\n## Review feasibility delivery\n\n```json\n' + canonical(self.delivery) + '\n```\n')
        for n, block in enumerate(self.tasks, 1):
            self.write(f'{stem}.tasks/task-{n}.md', f'# Task {n}\n\n## Review feasibility task\n\n```json\n'
                       + canonical(block) + '\n```\n')

    def checkpoint(self):
        for task in self.tasks:
            task['task']['actual_ranges'] = [row for owner, row, _ in self.ranges if owner == task['task']['id']]
        self.delivery['actual_evidence'] = dict(kind='git-range-ownership/v1', head=self.head,
            tree=self.git('rev-parse', self.head + '^{tree}'),
            process_ranges=[dict(**row, boundaries=bounds) for owner, row, bounds in self.ranges if owner == 0])
        self.emit()
        return self.commit('checkpoint')


class TreeEntryTest(SourceProjectionFixture, unittest.TestCase):
    def test_colon_prefixed_path_is_a_literal_name_not_a_pathspec(self):
        self.write(':(top)literal.txt', 'literal\n')
        self.write('other.txt', 'other\n')
        tree = self.git('rev-parse', self.commit('colon names') + '^{tree}')
        entry = tree_entry(self.repo, tree, ':(top)literal.txt')
        self.assertIsNotNone(entry, 'a file literally named like pathspec syntax is a tree entry')
        self.assertEqual((entry['mode'], entry['kind']), ('100644', 'blob'))
        self.assertIsNone(tree_entry(self.repo, tree, ':(top)other.txt'),
                          'pathspec magic must not resolve to a different path')


class TreeEntriesTest(unittest.TestCase):
    """Issue 613: `tree_entries` answers every path as `tree_entry` does, from one `ls-tree` per tree."""

    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        repo = cls.repo = Path(cls.scratch.name) / 'repo'
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        run = lambda *args: subprocess.run(['git', '-C', str(repo), *args], env=env, check=True,
                                           capture_output=True, text=True).stdout.strip()
        repo.mkdir()
        run('init', '-q')
        for name, data in (('a.txt', 'a'), ('exec.sh', 'x'), ('d/e/f.txt', 'f'), ('d/g.txt', 'g'),
                           ('caf\u00e9.txt', 'c'), (':(top)literal.txt', 'l'), ('spaced name.txt', 's')):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(data)
        (repo / 'exec.sh').chmod(0o755)
        (repo / 'link').symlink_to('a.txt')
        run('add', '-A')
        run('update-index', '--add', '--cacheinfo', '160000,' + '1' * 40 + ',sub')
        cls.tree = run('write-tree')
        # No path is a directory prefix of another, so one listing answers them all.
        cls.paths = ('a.txt', 'exec.sh', 'link', 'd/e', 'd/g.txt', 'caf\u00e9.txt', ':(top)literal.txt',
                     'spaced name.txt', 'sub', 'missing', 'D/G.TXT', ':(top)a.txt', 'd/missing', 'nowhere/x')

    @staticmethod
    def outcome(call):
        """`call()`'s answer, or the type and message of what it raised."""
        try:
            return call()
        except Exception as exc:  # the per-path lookup's refusal is part of its answer
            return type(exc), str(exc)

    def counted(self, call):
        """`call()`'s result and the `ls-tree` runs it made."""
        from agent_tools import review_forecast
        runs, real = [], review_forecast._run_git
        def run(repo, *args, **kwargs):
            runs.append(args)
            return real(repo, *args, **kwargs)
        with patch.object(review_forecast, '_run_git', run):
            return call(), [args for args in runs if 'ls-tree' in args]

    def test_batched_lookup_equals_the_per_path_lookup_with_one_listing(self):
        from agent_tools.review_forecast import tree_entries
        expected = {path: tree_entry(self.repo, self.tree, path) for path in self.paths}
        self.assertEqual({expected[p]['kind'] for p in ('a.txt', 'd/e', 'sub', 'link')}, {'blob', 'tree', 'commit'})
        lookup, runs = self.counted(lambda: tree_entries(self.repo, self.tree, [*self.paths, 'a.txt']))
        self.assertEqual(runs, [], 'the listing runs on the first lookup')
        answers, runs = self.counted(lambda: {path: lookup(path) for path in self.paths})
        self.assertEqual(answers, expected)
        self.assertEqual(len(runs), 1)
        answers['a.txt']['oid'] = 'changed'
        self.assertEqual(lookup('a.txt'), expected['a.txt'], 'each answer is a fresh copy')

    def test_nested_unrequested_or_unlisted_paths_take_the_per_path_lookup(self):
        from agent_tools import review_forecast
        from agent_tools.review_forecast import tree_entries
        for paths in (('d', 'd/e/f.txt', 'a.txt'), ('d/e', 'd/e/f.txt'), ('a.txt', 'a.txt/x'), ('sub', 'sub/x'),
                      ('link', 'link/x'), ('a.txt', '', 'd'), ('./a.txt', 'd'), ('d/../a.txt',), ('d//g.txt',)):
            with self.subTest(paths=paths):
                lookup = tree_entries(self.repo, self.tree, paths)
                answers, runs = self.counted(lambda: [self.outcome(lambda: lookup(p)) for p in paths if p])
                self.assertEqual(answers, [self.outcome(lambda: tree_entry(self.repo, self.tree, p))
                                           for p in paths if p])
                self.assertEqual(len(runs), len([p for p in paths if p]))
        lookup = tree_entries(self.repo, self.tree, ('a.txt', 'exec.sh'))
        answer, runs = self.counted(lambda: lookup('d/g.txt'))
        self.assertEqual((answer, len(runs)), (tree_entry(self.repo, self.tree, 'd/g.txt'), 1))
        real = review_forecast._run_git
        def folding(repo, *args, **kwargs):  # a Git whose pathspecs fold case: `D/G.TXT` lists `d/g.txt`
            listed = real(repo, *args, **kwargs)
            return listed + b'100644 blob ' + b'2' * 40 + b'\td/g.txt\0' if 'D/G.TXT' in args else listed
        paths = ('a.txt', 'D/G.TXT', 'exec.sh')
        with patch.object(review_forecast, '_run_git', folding):
            lookup = tree_entries(self.repo, self.tree, paths)
            self.assertEqual([self.outcome(lambda: lookup(p)) for p in paths],
                             [self.outcome(lambda: tree_entry(self.repo, self.tree, p)) for p in paths])
            self.assertEqual(self.outcome(lambda: lookup('D/G.TXT')), (ForecastError, 'tree path mismatch'))

    def test_refusals_are_the_per_path_refusals(self):
        from agent_tools.review_actual import GenerationError
        from agent_tools.review_forecast import tree_entries
        with self.assertRaises(GenerationError):
            tree_entry(self.repo, '0' * 40, 'a.txt')
        with self.assertRaises(GenerationError):
            tree_entries(self.repo, '0' * 40, ['a.txt', 'd'])('a.txt')


class GraphRefusalTest(BoundaryTreeTest):
    def test_partitions_parents_dependencies_and_types_are_closed(self):
        import copy
        good = [self.row('all', None, [1, 2, 3]), self.row('one', 'all', [1]),
                self.row('rest', 'all', [2, 3], ['one'])]
        cases = [lambda rows: rows[1].update(parent='absent'),
                 lambda rows: rows[1].update(tasks=[1, 2]),
                 lambda rows: rows[2].update(tasks=[3]),
                 lambda rows: rows[1].update(depends_on=['rest']),
                 lambda rows: rows[2].update(depends_on=['all']),
                 lambda rows: rows[2].update(depends_on=['absent']),
                 lambda rows: rows[0].update(parent='rest'),
                 lambda rows: rows[0].update(tasks=[1, 2]),
                 lambda rows: rows[2]['prerequisite'].update(tasks=[1, 2]),
                 lambda rows: rows[2]['prerequisite'].update(commit='a' * 40),
                 lambda rows: rows[1].update(tasks=[True]),
                 lambda rows: rows[1].update(unknown='field'),
                 lambda rows: rows[1]['process_package'].update(tasks=['escape/../task-1.md']),
                 lambda rows: rows[1].update(process_commit_subject_bytes=[True])]
        self.assertEqual(validate_boundaries(good, 3, 'all'), tuple(good))
        for mutate in cases:
            rows = copy.deepcopy(good); mutate(rows)
            with self.subTest(rows=rows), self.assertRaises(ForecastError):
                validate_boundaries(rows, 3, 'all')


class ReconstructionTest(SourceProjectionFixture, unittest.TestCase):
    def test_repeated_context_cannot_relocate_an_excluded_line(self):
        from agent_tools.review_projection import reconstruct_owned
        self.write('shared.txt', 'same\n' * 100)
        prerequisite = self.commit('prerequisite', 1)
        self.write('shared.txt', 'same\n' * 200)
        self.commit('excluded appended content', 1)
        lines = ['same\n'] * 200
        lines[150] = 'owned\n'
        self.write('shared.txt', ''.join(lines))
        selected = self.commit('edit excluded line', 2)
        try:
            with reconstruct_owned(self.repo, prerequisite, [selected]) as rebuilt:
                content = subprocess.run(['git', '-C', str(rebuilt.repo), 'show',
                    rebuilt.result_tree + ':shared.txt'], check=True, capture_output=True).stdout.splitlines()
        except ForecastError as exc:
            self.assertIn('projection_unavailable', str(exc))
            self.assertIn('excluded effects', str(exc))
        else:
            self.fail(f'accepted excluded effect: {len(content)} lines, owned at line {content.index(b"owned") + 1}')

    def test_independent_effects_excluded_dependencies_and_duplicate_commits(self):
        from agent_tools.review_projection import reconstruct_owned
        start = self.head
        self.write('excluded', 'excluded effect\n'); excluded = self.commit('excluded', 1)
        self.write('selected', 'selected effect\n'); selected = self.commit('selected', 2)
        before = self.git('status', '--porcelain'), self.git('count-objects', '-v')
        with reconstruct_owned(self.repo, start, [selected]) as rebuilt:
            self.assertEqual(subprocess.run(['git', '-C', str(rebuilt.repo), 'show', rebuilt.result_tree + ':selected'],
                                          capture_output=True).stdout, b'selected effect\n')
            self.assertNotEqual(subprocess.run(['git', '-C', str(rebuilt.repo), 'cat-file', '-e',
                                               rebuilt.result_tree + ':excluded'], capture_output=True).returncode, 0)
            self.assertEqual([c['sha'] for c in rebuilt.commits], [selected])
            self.assertEqual(rebuilt.ordered_edges[0]['parent'], excluded)
        self.assertFalse(rebuilt.repo.exists())
        self.assertEqual(before, (self.git('status', '--porcelain'), self.git('count-objects', '-v')))
        with self.assertRaises(ForecastError): reconstruct_owned(self.repo, start, [selected, selected])
        self.write('excluded', 'dependent effect\n'); dependent = self.commit('dependent', 2)
        with self.assertRaisesRegex(ForecastError, 'excluded effects'):
            reconstruct_owned(self.repo, start, [dependent])

    def test_merge_all_parent_provenance_and_duplicate_effect_refusal(self):
        from agent_tools.review_projection import reconstruct_owned
        start = self.head
        branch = self.git('branch', '--show-current')
        self.git('switch', '-qc', 'side')
        self.write('side', 'side\n'); side = self.commit('side', 1)
        self.git('switch', '-q', branch)
        self.write('main', 'main\n'); main = self.commit('main', 1)
        self.git('merge', '--no-ff', '-qm', 'merge', 'side')
        merge = self.git('rev-parse', 'HEAD')
        with reconstruct_owned(self.repo, start, [merge, main, side]) as rebuilt:
            self.assertEqual(rebuilt.result_tree, self.git('rev-parse', merge + '^{tree}'))
            edges = [e for e in rebuilt.ordered_edges if e['commit'] == merge]
            self.assertEqual([e['parent_ordinal'] for e in edges], [1, 2])
            self.assertEqual([e['parent'] for e in edges], [main, side])
        with self.assertRaisesRegex(ForecastError, 'merge effects'):
            reconstruct_owned(self.repo, start, [merge])


class BudgetRefusalReasonTest(unittest.TestCase):
    """A checker refusal names the checker's last stderr line (issue 559 D12)."""
    def test_check_refusal_relays_the_checkers_last_line_or_its_exit(self):
        from unittest.mock import patch
        from agent_tools import review_budget
        authority = review_budget.BudgetAuthority(None, 'sha256:' + '0' * 64, 4096)
        for stderr, expected in ((b'noise\nartifact-budget: invalid input:  invalid task index row\n\n',
                                  'artifact-budget: invalid input: invalid task index row'),
                                 (b'x' * 300 + b'\n', 'x' * 200), (b'', 'exit 2')):
            refused = subprocess.CompletedProcess([], 2, b'', stderr)
            with self.subTest(stderr=stderr[:20]), patch.object(review_budget, '_invoke', return_value=refused):
                with self.assertRaises(review_budget.BudgetError) as caught:
                    authority.check('review-package', Path('review.json'))
                self.assertEqual(str(caught.exception), 'budget check failed: ' + expected)
