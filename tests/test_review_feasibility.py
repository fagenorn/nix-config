import unittest
from agent_tools.review_forecast import ForecastError, validate_boundaries

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

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

class SequentialCandidateTest(unittest.TestCase):
    def test_owned_candidate_matches_independent_actual_range(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as raw:
            top = Path(raw); repo = top / "repo"; repo.mkdir()
            home = top / "home"
            (home / ".agents/lib/python").mkdir(parents=True)
            (home / ".agents/share").mkdir(parents=True)
            legacy = source / "home/common/agent-skills"
            (home / ".agents/lib/python/artifact_budget.py").symlink_to(legacy / "scripts/artifact_budget.py")
            (home / ".agents/share/artifact-budget-policy.json").symlink_to(legacy / "artifact-budget-policy.json")
            env = dict(os.environ, HOME=str(home), PYTHONPATH=str(source / "python"),
                       PATH=str(legacy / "scripts") + os.pathsep + os.environ["PATH"])
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], env=env,
                    check=True, capture_output=True, text=True).stdout.strip()
            def commit(subject):
                git("add", "-A"); git("commit", "-qm", subject)
                return git("rev-parse", "HEAD")
            def write(path, text):
                target = repo / path; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            def canonical(value):
                return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            def package(name, count):
                return dict(spec=name + "-spec.md", plan=name + ".md",
                            tasks=[f"{name}.tasks/task-{n}.md" for n in range(1, count + 1)])
            def process_records(name, pkg):
                return [dict(id=f"{name}-p{i}", owner=0, path=path, change="add", last_task=2,
                    bounds=[dict(boundary=name, added_lines=1, deleted_lines=0, record_bytes=1,
                        support=dict(kind="authored-cumulative/v1", covers=[f"{name}-p{i}"]))])
                    for i, path in enumerate([pkg["spec"], pkg["plan"], *pkg["tasks"]])]
            git("init", "-q"); git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.test")
            git("config", "commit.gpgsign", "false")
            git("config", "diff.renames", "false")
            write("shared.txt", "seed\n"); base = commit("base")
            pkgs = {"all": package("all", 2), "one": package("one", 1), "two": package("two", 1)}
            process = {name: process_records(name, pkg) for name, pkg in pkgs.items()}
            def boundary(name, parent, tasks, deps, prerequisite):
                return dict(id=name, parent=parent, tasks=tasks, acceptance="Independent repository review",
                    depends_on=deps, prerequisite=prerequisite, process_package=pkgs[name],
                    process_forecast_ids=[r["id"] for r in process[name]], process_commit_subject_bytes=[])
            delivery = dict(schema_version=3, kind="review-feasibility-delivery", delivery_base=base,
                proposed_boundary="all", boundaries=[
                    boundary("all", None, [1, 2], [], dict(kind="delivery-base")),
                    boundary("one", "all", [1], [], dict(kind="delivery-base")),
                    boundary("two", "all", [2], ["one"],
                             dict(kind="completed-tasks", tasks=[1], commit=None, tree=None))],
                process_records=sum(process.values(), []), derived_from=None,
                actual_evidence=dict(kind="git-range-ownership/v1", head=base,
                                     tree=git("rev-parse", base + "^{tree}"), process_ranges=[]))
            task_blocks = [dict(schema_version=3, kind="review-feasibility-task",
                task=dict(id=n, commit_subject_bytes=[], actual_ranges=[], records=[])) for n in (1, 2)]
            def emit():
                write("all-spec.md", "# Spec\n")
                write("all.md", "# Plan\n\n## Task index\n\n" + "\n".join(
                    f"Task {n} — Case — shared.txt — full — [task-{n}.md](all.tasks/task-{n}.md)"
                    for n in (1, 2)) + "\n\n## Review feasibility delivery\n\n```json\n" + canonical(delivery) + "\n```\n")
                for n, block in enumerate(task_blocks, 1):
                    write(f"all.tasks/task-{n}.md", f"# Task {n}\n\n## Review feasibility task\n\n```json\n" + canonical(block) + "\n```\n")
            def standalone_docs(name):
                write(name + "-spec.md", "# Candidate spec\n")
                write(name + ".md", "# Plan\n\n## Task index\n\nTask 1 — Case — shared.txt — full — "
                      f"[task-1.md]({name}.tasks/task-1.md)\n")
                write(name + ".tasks/task-1.md", "# Task 1\n")
            emit(); standalone_docs("one"); process_head = commit("process")
            for n in range(7): write(f"prerequisite-{n}.txt", "x" * 60000 + "\n")
            write("shared.txt", "first edit\n"); first = commit("task one")
            for n in range(3): write(f"candidate-{n}.txt", "y" * 50000 + "\n")
            write("shared.txt", "second edit\n"); second = commit("task two")
            standalone_docs("two"); checkpoint = commit("candidate process")
            task_blocks[0]["task"]["actual_ranges"] = [dict(base=process_head, head=first)]
            task_blocks[1]["task"]["actual_ranges"] = [dict(base=first, head=second)]
            delivery["actual_evidence"] = dict(kind="git-range-ownership/v1", head=checkpoint,
                tree=git("rev-parse", checkpoint + "^{tree}"), process_ranges=[
                    dict(base=base, head=process_head, boundaries=["all", "one"]),
                    dict(base=second, head=checkpoint, boundaries=["all", "two"])])
            delivery["boundaries"][2]["prerequisite"].update(
                commit=first, tree=git("rev-parse", first + "^{tree}"))
            emit(); head = commit("ownership checkpoint")
            def project(head, completed=1):
                return subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "project",
                    "--plan", str(repo / "all.md"), "--base", base, "--head", head,
                    "--completed-through", str(completed), "--package-name", "review.json"],
                    cwd=repo, env=env, capture_output=True, text=True)
            result = project(head)
            self.assertEqual(result.returncode, 3, result.stderr)
            recommended = json.loads(result.stdout)["recommended_boundary"]
            self.assertEqual(recommended["id"], "two")
            self.assertEqual(recommended["prerequisite_commit"], first)
            self.assertEqual(recommended["actual_tree"], git("rev-parse", checkpoint + "^{tree}"))
            out = top / "review.json"
            actual = subprocess.run([sys.executable, "-m", "agent_tools.review_package",
                str(repo / "all.md"), first, checkpoint, str(out)], cwd=repo, env=env,
                capture_output=True, text=True)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(recommended["metrics"], json.loads(actual.stdout)["artifact"]["metrics"])
            checked = subprocess.run(["artifact-budget", "check", "--kind", "review-package",
                "--root", str(out), "--format", "json"], cwd=repo, env=env,
                capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(recommended["metrics"], json.loads(checked.stdout)["metrics"])
            final = project(head, completed=2)
            self.assertEqual(final.returncode, 3, final.stderr)
            full_out = top / "full" / "review.json"
            full_out.parent.mkdir()
            full_actual = subprocess.run([sys.executable, "-m", "agent_tools.review_package",
                str(repo / "all.md"), base, head, str(full_out)], cwd=repo, env=env,
                capture_output=True, text=True)
            self.assertEqual(full_actual.returncode, 3, full_actual.stderr)
            self.assertEqual(json.loads(final.stdout)["metrics"],
                             json.loads(full_actual.stdout)["artifact"]["metrics"])
            self.assertIsNone(json.loads(final.stdout)["recommended_boundary"])
            # Tree-consistent but wrong prerequisite includes the candidate itself.
            delivery["boundaries"][2]["prerequisite"].update(
                commit=second, tree=git("rev-parse", second + "^{tree}"))
            emit(); bad = project(commit("wrong prerequisite"))
            self.assertEqual((bad.returncode, bad.stdout), (2, ""))
            delivery["boundaries"][2]["prerequisite"].update(
                commit=first, tree=git("rev-parse", first + "^{tree}"))
            task_blocks[0]["task"]["actual_ranges"] += task_blocks[1]["task"]["actual_ranges"]
            task_blocks[1]["task"]["actual_ranges"] = []
            emit(); bad = project(commit("wrong ownership"))
            self.assertEqual((bad.returncode, bad.stdout), (2, ""))

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


class SourceProjectionFixture:
    """All command fixtures use actual Git objects and source subprocesses."""
    plan_stem = 'all'

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.top = Path(self.scratch.name)
        self.repo = self.top / 'repo'
        self.repo.mkdir()
        source = Path(__file__).resolve().parents[1]
        home = self.top / 'home'
        (home / '.agents/lib/python').mkdir(parents=True)
        (home / '.agents/share').mkdir(parents=True)
        legacy = source / 'home/common/agent-skills'
        (home / '.agents/lib/python/artifact_budget.py').symlink_to(legacy / 'scripts/artifact_budget.py')
        (home / '.agents/share/artifact-budget-policy.json').symlink_to(legacy / 'artifact-budget-policy.json')
        self.env = dict(os.environ, HOME=str(home), PYTHONPATH=str(source / 'python'),
                        PATH=str(legacy / 'scripts') + os.pathsep + os.environ['PATH'])
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'commit.gpgsign', 'false')
        self.write('shared.txt', 'seed\n')
        self.write('delete.txt', 'gone later\n')
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

    def invoke(self, *args, input=None, timeout=None):
        return subprocess.run([sys.executable, '-m', 'agent_tools.review_feasibility', *args],
            cwd=self.repo, env=self.env, input=input, capture_output=True, timeout=timeout)

    def project(self, completed=2, package='review.json', **overrides):
        args = dict(plan=str(self.repo / (self.plan_stem + '.md')), base=self.base, head=self.head,
                    completed_through=str(completed), package_name=package)
        args.update(overrides)
        return self.invoke('project', *(part for key, value in args.items() for part in ('--' + key.replace('_', '-'), str(value))))

    def actual(self, directory=None):
        out = (directory or self.top) / 'review.json'
        result = subprocess.run([sys.executable, '-m', 'agent_tools.review_package',
            str(self.repo / (self.plan_stem + '.md')), self.base, self.head, str(out)], cwd=self.repo,
            env=self.env, capture_output=True)
        self.assertIn(result.returncode, (0, 3), result.stderr)
        checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package', '--root', str(out),
                                 '--format', 'json'], env=self.env, capture_output=True)
        self.assertEqual(checked.returncode, result.returncode, checked.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['artifact']['metrics'], json.loads(checked.stdout)['metrics'])
        return report['artifact']['metrics'], json.loads(out.read_bytes())

    def assert_refused(self, result):
        self.assertEqual((result.returncode, result.stdout), (2, b''), result.stderr)


class SourceProjectionTest(SourceProjectionFixture, unittest.TestCase):
    def test_actual_only_rename_binary_and_unforecast_parity(self):
        self.git('config', 'diff.renames', 'false')
        self.git('mv', 'shared.txt', 'renamed "é".txt')
        self.write('binary.dat', bytes(range(256)) * 20)
        self.write('unforecast.txt', 'unforecast actual\n')
        self.commit('product é', 1)
        self.checkpoint()
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        measured, manifest = self.actual()
        self.assertEqual(value['metrics'], measured)
        self.assertEqual(value['actual_record_count'], value['projected_record_count'])
        self.assertEqual(value['actual_record_count'], manifest['coverage']['file_diff_count'])
        validated = self.invoke('validate-result', '--input', '-', '--producer-exit', '0', input=result.stdout)
        self.assertEqual((validated.returncode, validated.stdout), (0, result.stdout), validated.stderr)

    def test_completed_add_modify_absence_and_proven_delete(self):
        for operation in ('add', 'modify'):
            with self.subTest(operation=operation):
                self.tasks[0]['task']['records'] = [self.record('missing', 1, 'missing.txt', change=operation, horizon=1)]
                self.emit(); self.commit('bad completed forecast')
                self.assert_refused(self.project())
        self.tasks[0]['task']['records'] = [self.record('deleted', 1, 'delete.txt', change='delete', horizon=1)]
        (self.repo / 'delete.txt').unlink()
        self.commit('delete', 1)
        self.checkpoint()
        good = self.project()
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['metrics'], self.actual()[0])

    def test_completed_add_then_delete_net_absence_is_proven(self):
        self.write('transient', 'short lived\n'); self.commit('add transient', 1)
        (self.repo / 'transient').unlink(); self.commit('delete transient', 1)
        self.tasks[0]['task']['records'] = [self.record('deleted', 1, 'transient', change='delete', horizon=1)]
        self.checkpoint()
        good = self.project()
        self.assertEqual(good.returncode, 0, good.stderr)

    def test_future_same_path_is_one_record_with_complete_prefix(self):
        self.tasks[0]['task']['commit_subject_bytes'] = [120]
        self.tasks[1]['task']['commit_subject_bytes'] = [120]
        self.tasks[0]['task']['records'] = [self.record('first', 1, 'future', size=3000)]
        self.tasks[1]['task']['records'] = [self.record('second', 2, 'future', size=5000, covers=['first', 'second'])]
        self.emit(); self.commit('forecast')
        good = self.project(0)
        self.assertEqual(good.returncode, 0, good.stderr)
        value = json.loads(good.stdout)
        self.assertEqual(value['projected_record_count'], value['actual_record_count'] + 1)
        self.tasks[1]['task']['records'][0]['bounds'][0]['support']['covers'] = ['second']
        self.emit(); self.commit('missing support')
        self.assert_refused(self.project(0))

    def test_actual_larger_than_forecast_preserves_metrics(self):
        self.write('large', 'x' * 12000 + '\n'); self.commit('large actual', 1)
        self.tasks[0]['task']['records'] = [self.record('large', 1, 'large', size=1, added=1, horizon=2)]
        self.checkpoint()
        projected = self.project(1)
        self.assertEqual(projected.returncode, 0, projected.stderr)
        self.assertEqual(json.loads(projected.stdout)['metrics'], self.actual()[0])

    def test_process_tail_cannot_hide_product_or_merge(self):
        self.write('hidden-product', 'bad tail\n'); self.commit('undeclared tail')
        self.assert_refused(self.project())

    def test_dirty_missing_unknown_and_symlink_package_refusals(self):
        root = (self.repo / 'all.md').read_bytes()
        member = (self.repo / 'all.tasks/task-1.md').read_bytes()
        cases = ('dirty root', 'dirty member', 'unknown member', 'missing member', 'symlink member', 'symlink spec')
        for case in cases:
            with self.subTest(case=case):
                if case == 'dirty root': self.write('all.md', root + b'changed\n')
                if case == 'dirty member': self.write('all.tasks/task-1.md', member + b'changed\n')
                if case == 'unknown member': self.write('all.tasks/unknown.md', 'unknown\n')
                if case == 'missing member': (self.repo / 'all.tasks/task-1.md').unlink()
                if case == 'symlink member':
                    (self.repo / 'all.tasks/task-1.md').unlink()
                    (self.repo / 'all.tasks/task-1.md').symlink_to(self.repo / 'all.tasks/task-2.md')
                if case == 'symlink spec':
                    (self.repo / 'all-spec.md').unlink()
                    (self.repo / 'all-spec.md').symlink_to(self.repo / 'shared.txt')
                self.assert_refused(self.project())
                self.git('reset', '--hard', self.head)
                if (self.repo / 'all.tasks/unknown.md').exists(): (self.repo / 'all.tasks/unknown.md').unlink()

    def test_identity_invocation_and_closed_schema_refusals(self):
        import copy
        for override in ({'base': self.base[:7]}, {'head': self.base}, {'completed_through': '-1'},
                         {'completed_through': '3'}, {'package_name': '../review.json'},
                         {'package_name': 'review.txt'}):
            with self.subTest(override=override): self.assert_refused(self.project(**override))
        original = copy.deepcopy(self.delivery)
        mutations = [lambda d: d.update(schema_version=True), lambda d: d.update(unknown=1),
                     lambda d: d['actual_evidence'].update(tree='a' * 40),
                     lambda d: d['boundaries'][0].update(tasks=[True, 2]),
                     lambda d: d['process_records'][0].update(path='../escape'),
                     lambda d: d['process_records'][0].update(owner=True),
                     lambda d: d['process_records'][0].update(change='rename'),
                     lambda d: d['process_records'][0].update(change='fileless'),
                     lambda d: d['process_records'][0]['bounds'][0].update(record_bytes=True),
                     lambda d: d['process_records'][0]['bounds'][0].update(added_lines=float('inf'))]
        for mutate in mutations:
            self.delivery = copy.deepcopy(original); mutate(self.delivery)
            self.emit(); self.commit('invalid shape')
            self.assert_refused(self.project())

    def test_duplicate_json_and_ambiguous_sections(self):
        original = (self.repo / 'all.md').read_bytes()
        for raw in (original.replace(b'"schema_version":3', b'"schema_version":3,"schema_version":3'),
                    original + b'\n## Review feasibility delivery\n',
                    original.replace(b'```json\n{', b'```json\n{ ')):
            self.write('all.md', raw); self.commit('invalid block')
            self.assert_refused(self.project())

    def test_ownership_overlap_missing_and_wrong_tree(self):
        import copy
        original = copy.deepcopy(self.delivery)
        mutations = [lambda d: d['actual_evidence']['process_ranges'].append(d['actual_evidence']['process_ranges'][0]),
                     lambda d: d['actual_evidence'].update(process_ranges=[]),
                     lambda d: d['actual_evidence'].update(tree='a' * 40)]
        for mutate in mutations:
            self.delivery = copy.deepcopy(original); mutate(self.delivery)
            self.emit(); self.commit('bad ownership')
            self.assert_refused(self.project())

    def test_actual_line_counts_are_not_double_charged_by_cumulative_bound(self):
        self.write('lines', 'x\n' * 970)
        self.commit('line actual', 1)
        self.tasks[0]['task']['records'] = [self.record('lines', 1, 'lines', size=1, added=900)]
        self.checkpoint()
        actual_count = sum(int(row.split('\t')[0]) for row in self.git('diff', '--numstat', self.base, self.head).splitlines())
        self.assertGreaterEqual(actual_count, 970)
        self.assertLess(actual_count, 1000)
        result = self.project(1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])

    def test_each_budget_overflow_and_no_candidate_null(self):
        import copy
        process = copy.deepcopy(self.delivery['process_records'])
        for expected in ('root_bytes', 'member_bytes', 'member_count', 'aggregate_bytes'):
            with self.subTest(expected=expected):
                self.delivery['process_records'] = copy.deepcopy(process)
                self.tasks[0]['task']['records'] = []
                self.tasks[0]['task']['commit_subject_bytes'] = [120]
                if expected == 'root_bytes':
                    self.tasks[0]['task']['commit_subject_bytes'] = [120] * 30
                elif expected == 'member_bytes':
                    self.tasks[0]['task']['records'] = [self.record('big', 1, 'big', size=65537)]
                elif expected == 'member_count':
                    self.tasks[0]['task']['records'] = [self.record(f'p{n}', 1, f'p{n}', size=40000) for n in range(9)]
                else:
                    for record in self.delivery['process_records']:
                        record['bounds'][0]['record_bytes'] = 65536
                    self.tasks[0]['task']['records'] = [self.record(f'p{n}', 1, f'p{n}', size=65536) for n in range(4)]
                self.emit(); self.commit('overflow forecast')
                result = self.project(0)
                self.assertEqual(result.returncode, 3, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value['violations'], [expected])
                self.assertIsNone(value['recommended_boundary'])
                validated = self.invoke('validate-result', '--input', '-', '--producer-exit', '3', input=result.stdout)
                self.assertEqual((validated.returncode, validated.stdout), (0, result.stdout), validated.stderr)
                self.assert_refused(self.invoke('validate-result', '--input', '-', '--producer-exit', '0', input=result.stdout))

    def test_validator_closed_canonical_types_policy_and_wire(self):
        import copy
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        good = json.loads(result.stdout)
        mutations = [lambda v: v.update(schema_version=True), lambda v: v.update(unknown=1),
            lambda v: v.update(completed_through=True), lambda v: v.update(actual_record_count=True),
            lambda v: v['metrics'].update(root_bytes=True), lambda v: v['metrics'].update(total_bytes=1.5),
            lambda v: v.update(state='decompose_required'), lambda v: v.update(violations=['member_bytes']),
            lambda v: v.update(packing_policy_sha256='sha256:' + '0' * 64),
            lambda v: v.update(artifact_policy_sha256='sha256:' + '0' * 64),
            lambda v: v.update(plan_package_sha256='bad'), lambda v: v.update(forecast_sha256='bad'),
            lambda v: v.update(actual_evidence_sha256='bad'), lambda v: v.update(tree='abc'),
            lambda v: v.update(package_name='a/../review.json'),
            lambda v: v.update(recommended_boundary={})]
        raws = [result.stdout + b'\n', b' ' + result.stdout, result.stdout + b'{}', b'x' * 200000,
                result.stdout.replace(b'"schema_version":3', b'"schema_version":3,"schema_version":3')]
        for mutate in mutations:
            value = copy.deepcopy(good); mutate(value)
            raws.append((json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode())
        for raw in raws:
            with self.subTest(raw=raw[:100]):
                self.assert_refused(self.invoke('validate-result', '--input', '-', '--producer-exit', '0', input=raw))
        self.assert_refused(self.invoke('validate-result', '--input', '-', '--producer-exit', '3', input=result.stdout))
        oversized = self.top / 'oversized'
        oversized.write_bytes(b'x' * 200000)
        self.assert_refused(self.invoke('validate-result', '--input', str(oversized), '--producer-exit', '0'))
        linked = self.top / 'linked'; linked.symlink_to(oversized)
        self.assert_refused(self.invoke('validate-result', '--input', str(linked), '--producer-exit', '0'))

    def test_validate_result_refuses_fifo_input_without_blocking(self):
        fifo = self.top / 'result.fifo'
        os.mkfifo(fifo)
        # No writer ever opens the FIFO: a blocking open would hang until the timeout.
        self.assert_refused(self.invoke('validate-result', '--input', str(fifo), '--producer-exit', '0', timeout=20))

    def test_default_package_identity_and_changed_forecast_identity(self):
        result = self.invoke('project', '--plan', str(self.repo / 'all.md'), '--base', self.base,
            '--head', self.head, '--completed-through', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['package_name'], f'review-{self.base[:7]}..{self.head[:7]}.json')
        self.tasks[1]['task']['commit_subject_bytes'] = [123]
        self.emit(); self.commit('changed forecast')
        changed = self.project()
        self.assertEqual(changed.returncode, 0, changed.stderr)
        next_value = json.loads(changed.stdout)
        for field in ('head', 'tree', 'forecast_sha256', 'plan_package_sha256', 'actual_evidence_sha256'):
            self.assertNotEqual(value[field], next_value[field])
        self.assertEqual(value['packing_policy_sha256'], next_value['packing_policy_sha256'])

    def test_retained_anchor_authenticates_payloads_without_operation_authority(self):
        import hashlib
        from agent_tools.canonical import telemetry_digest
        names = ['derivation-witness.json', 'issue-100-derived.json', 'issue-121.json', 'task7-estimate.json']
        payload = b'{}\n'
        for filename in names: self.write('retained/' + filename, payload)
        anchor = dict(schema_version=2, kind='review-feasibility-derivation-anchor', tool={}, issue_121={},
            issue_100={}, archive={}, estimate={}, payload=dict(encoding='canonical-json-ascii-lf/v1', members=[
                dict(path=filename, bytes=len(payload), raw_sha256=hashlib.sha256(payload).hexdigest()) for filename in names]))
        raw = (json.dumps(anchor, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.write('retained/anchor.json', raw)
        self.delivery['derived_from'] = dict(kind='retained-anchor/v2', path='retained/anchor.json',
                                             anchor_sha256=telemetry_digest(anchor))
        self.commit('retained payloads', 1); self.checkpoint()
        good = self.project()
        self.assertEqual(good.returncode, 0, good.stderr)
        self.write('retained/issue-121.json', b'{"substituted":true}\n')
        self.commit('substitute payload', 1); self.checkpoint()
        self.assert_refused(self.project())
        self.write('retained/issue-121.json', payload)
        self.commit('restore payload', 1); self.checkpoint()
        self.tasks[1]['task']['records'] = [self.record('fileless', 2, 'fileless', change='fileless')]
        self.emit(); self.commit('unsupported operation')
        unavailable = self.project(1)
        self.assert_refused(unavailable)
        self.assertIn(b'projection_unavailable', unavailable.stderr)


class NonAsciiPlanTest(SourceProjectionFixture, unittest.TestCase):
    plan_stem = 'café'

    def test_non_ascii_plan_members_match_complete_index(self):
        self.write('product.txt', 'product\n'); self.commit('product', 1)
        self.checkpoint()
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])


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


class RecommendationTest(SourceProjectionFixture, unittest.TestCase):
    def test_stable_tie_order_and_unrelated_descendant(self):
        root = self.delivery['boundaries'][0]
        middle = BoundaryTreeTest().row('mid', 'all', [1, 2])
        leaf = BoundaryTreeTest().row('end', 'mid', [1, 2])
        self.delivery['boundaries'] = [root, leaf, middle]
        root['process_commit_subject_bytes'] = [120] * 30
        for boundary in (leaf, middle):
            boundary['process_commit_subject_bytes'] = [1]
            paths = [boundary['process_package']['spec'], boundary['process_package']['plan'], *boundary['process_package']['tasks']]
            for index, path in enumerate(paths):
                record = self.record(boundary['process_forecast_ids'][index], 0, path)
                record['bounds'][0]['boundary'] = boundary['id']
                self.delivery['process_records'].append(record)
        self.emit(); self.commit('boundaries')
        result = self.project(0)
        self.assertEqual(result.returncode, 3, result.stderr)
        recommendation = json.loads(result.stdout)['recommended_boundary']
        self.assertEqual(recommendation['id'], 'end')
        self.assertEqual(recommendation['actual_tree'], self.git('rev-parse', self.base + '^{tree}'))
        self.delivery['boundaries'] = [root, middle, leaf]
        self.emit(); self.commit('reorder tied boundaries')
        changed = self.project(0)
        self.assertEqual(changed.returncode, 3, changed.stderr)
        self.assertEqual(json.loads(changed.stdout)['recommended_boundary']['id'], 'mid')


class ActualProjectionParityTest(SourceProjectionFixture, unittest.TestCase):
    def test_adaptive_and_initial_fallback_source_parity(self):
        sizes = [25203, 10617, 59012, 8037, 50410, 18999, 22184, 54145, 42155,
                 44332, 19559, 12004, 25696, 15635, 23066, 34082, 5682, 6805]
        # Reserve space for the complete four-file committed process package.
        for n, size in enumerate(sizes): self.write(f'f-{n:02d}', chr(65 + n) * (size - 1000) + '\n')
        self.commit('fragmented actual', 1); self.checkpoint()
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics, manifest = self.actual()
        self.assertEqual(manifest['interface_version'], 3)
        self.assertEqual(manifest['packaging']['context_lines'], 7)
        self.assertEqual(json.loads(result.stdout)['metrics'], metrics)
        for n in range(9): self.write(f'overflow-{n}', 'z' * 50000 + '\n')
        self.commit('overflow all contexts', 2); self.checkpoint()
        result = self.project()
        self.assertEqual(result.returncode, 3, result.stderr)
        # Use a fresh destination for independent producer publication.
        (self.top / 'review.json').unlink()
        import shutil
        shutil.rmtree(self.top / 'review.shards')
        metrics, manifest = self.actual()
        self.assertEqual(manifest['interface_version'], 1)
        self.assertEqual(json.loads(result.stdout)['metrics'], metrics)

    def test_generated_actual_parity_and_no_estimated_exemption(self):
        stem = 'src/App/Migrations/20260826010101_AddWidgets'
        self.write(stem + '.cs', 'public class AddWidgets { public void Up() {} public void Down() {} }\n')
        self.write(stem + '.Designer.cs', '\ufeff// <auto-generated />\n[Migration("20260826010101_AddWidgets")]\n'
            'partial class AddWidgets {\n void BuildTargetModel() {\n'
            ' modelBuilder.HasAnnotation("ProductVersion", "10.0.10");\n'
            + ' modelBuilder.Entity("Widget", b => { b.Property<int>("Id"); b.HasIndex("Id"); b.HasOne("Owner"); b.ToTable("widgets"); });\n' * 1100 + ' }\n}\n')
        self.commit('generated designer', 1); self.checkpoint()
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics, manifest = self.actual()
        self.assertEqual(manifest['interface_version'], 2)
        self.assertEqual(json.loads(result.stdout)['metrics'], metrics)
        self.tasks[1]['task']['records'] = [self.record('future-designer', 2, stem + '.Designer.cs', change='modify', size=70000)]
        self.emit(); self.commit('future generated change')
        future = self.project(1)
        self.assertEqual(future.returncode, 3, future.stderr)
        self.assertIn('member_bytes', json.loads(future.stdout)['violations'])


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

    def test_recommendation_refuses_relocated_excluded_content(self):
        root = self.delivery['boundaries'][0]
        root['process_commit_subject_bytes'] = [120] * 30
        for name, tasks in (('one', [1]), ('two', [2])):
            boundary = BoundaryTreeTest().row(name, 'all', tasks)
            boundary['process_commit_subject_bytes'] = [120]
            self.delivery['boundaries'].append(boundary)
            package = boundary['process_package']
            for index, path in enumerate([package['spec'], package['plan'], *package['tasks']]):
                record = self.record(boundary['process_forecast_ids'][index], 0, path)
                record['bounds'][0]['boundary'] = name
                self.delivery['process_records'].append(record)
        self.write('shared.txt', 'same\n' * 100)
        self.base = self.commit('delivery prerequisite')
        self.delivery['delivery_base'] = self.base
        self.ranges.clear()
        self.write('shared.txt', 'same\n' * 200)
        self.commit('excluded task two content', 2)
        lines = ['same\n'] * 200
        lines[150] = 'owned\n'
        self.write('shared.txt', ''.join(lines))
        self.commit('task one edits excluded content', 1)
        self.checkpoint()
        result = self.project(0)
        self.assert_refused(result)
        self.assertIn(b'projection_unavailable', result.stderr)
        self.assertIn(b'excluded effects', result.stderr)

    def test_recommendation_proves_completed_deletion_in_candidate_tree(self):
        # Task 1 adds then deletes a transient path; excluded task 3 recreates it.
        self.tasks.append(dict(schema_version=3, kind='review-feasibility-task', task=dict(
            id=3, commit_subject_bytes=[], actual_ranges=[], records=[])))
        root = BoundaryTreeTest().row('all', None, [1, 2, 3])
        root['process_commit_subject_bytes'] = [120] * 30
        front = BoundaryTreeTest().row('front', 'all', [1, 2])
        back = BoundaryTreeTest().row('back', 'all', [3])
        self.delivery['boundaries'] = [root, front, back]
        self.delivery['process_records'] = []
        for boundary in (root, front, back):
            if boundary is not root:
                boundary['process_commit_subject_bytes'] = [120]
            package = boundary['process_package']
            for index, path in enumerate([package['spec'], package['plan'], *package['tasks']]):
                record = self.record(boundary['process_forecast_ids'][index], 0, path)
                record['bounds'][0]['boundary'] = boundary['id']
                self.delivery['process_records'].append(record)
        deleted = self.record('transient-deleted', 1, 'transient', change='delete', horizon=1)
        deleted['bounds'].append(dict(deleted['bounds'][0], boundary='front'))
        self.tasks[0]['task']['records'] = [deleted]
        self.emit()
        self.base = self.commit('three task delivery')
        self.delivery['delivery_base'] = self.base
        self.ranges.clear()
        self.write('transient', 'short lived\n'); self.commit('add transient', 1)
        (self.repo / 'transient').unlink(); self.commit('delete transient', 1)
        self.write('transient', 'recreated later\n'); self.commit('excluded task recreates transient', 3)
        self.checkpoint()
        result = self.project(1)
        self.assertEqual(result.returncode, 3, result.stderr)
        recommendation = json.loads(result.stdout)['recommended_boundary']
        self.assertEqual(recommendation['id'], 'front')
        self.assertEqual(recommendation['actual_tree'], self.git('rev-parse', self.base + '^{tree}'))

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


class AdditionalBoundaryTest(SourceProjectionFixture, unittest.TestCase):
    def test_beyond_index_forecasts_have_exact_symbolic_metrics(self):
        self._assert_large_forecast_metrics(sys.maxsize + 1)

    def test_large_representable_forecasts_have_exact_symbolic_metrics(self):
        self._assert_large_forecast_metrics(100000000000)

    def _assert_large_forecast_metrics(self, amount):
        task = self.tasks[0]['task']
        boundary = self.delivery['boundaries'][0]
        for field in ('record_bytes', 'task_subject', 'process_subject'):
            with self.subTest(field=field):
                task['records'] = []
                task['commit_subject_bytes'] = []
                boundary['process_commit_subject_bytes'] = []
                if field == 'record_bytes':
                    task['records'] = [self.record('large-future', 1, 'future.txt', size=amount)]
                    task['commit_subject_bytes'] = [120]
                elif field == 'task_subject':
                    task['commit_subject_bytes'] = [amount]
                else:
                    boundary['process_commit_subject_bytes'] = [amount]
                self.emit(); self.commit('large future forecast')
                result = self.project(0)
                self.assertEqual(result.returncode, 3, result.stderr)
                directory = self.top / field
                directory.mkdir()
                _, expected = self.actual(directory)
                self.assertEqual(expected['interface_version'], 1)
                self.assertEqual(len(expected['shards']), 1)
                # Independent actual producer supplies existing metadata and bytes.
                # The synthetic SHA's value does not change its 40-byte wire cost.
                expected['commits'].append({'sha': '0' * 40, 'subject': ''})
                if field == 'record_bytes':
                    expected['shards'].append({'bytes': amount, 'path': 'review.shards/shard-002.diff'})
                    expected['coverage']['file_diff_count'] += 1
                    expected['stat']['files_changed'] += 1
                    expected['stat']['insertions'] += 1
                    expected['total_diff_bytes'] += amount
                reserve = 120 if field == 'record_bytes' else amount
                root_bytes = len((json.dumps(expected, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False) + '\n').encode()) + 6 * reserve
                member_sizes = [row['bytes'] for row in expected['shards']]
                value = json.loads(result.stdout)
                self.assertEqual(value['metrics'], {'root_bytes': root_bytes,
                    'total_bytes': root_bytes + sum(member_sizes), 'file_count': len(member_sizes) + 1,
                    'largest_member_bytes': max(member_sizes)})
                self.assertEqual(value['violations'], ['member_bytes', 'aggregate_bytes'] if field == 'record_bytes'
                                 else ['root_bytes', 'aggregate_bytes'])
                validated = self.invoke('validate-result', '--input', '-', '--producer-exit', '3', input=result.stdout)
                self.assertEqual((validated.returncode, validated.stdout), (0, result.stdout), validated.stderr)

    def test_missing_task_content_requires_subject_forecast_until_authored(self):
        task = self.tasks[0]['task']
        for operation in ('add', 'modify'):
            with self.subTest(operation=operation):
                task['records'] = [self.record('future-product', 1, 'future-product.txt',
                                              change=operation, horizon=1)]
                task['commit_subject_bytes'] = []
                self.emit(); self.commit('missing task subject')
                self.assert_refused(self.project(0))
                task['commit_subject_bytes'] = [120]
                self.emit(); self.commit('complete task subject')
                result = self.project(0)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value['projected_record_count'], value['actual_record_count'] + 1)
        self.write('future-product.txt', 'authored product\n')
        self.commit('authored product', 1)
        task['commit_subject_bytes'] = []
        self.checkpoint()
        result = self.project(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])

    def test_missing_candidate_process_files_require_subject_forecast(self):
        root = self.delivery['boundaries'][0]
        child = BoundaryTreeTest().row('future', 'all', [1, 2])
        self.delivery['boundaries'].append(child)
        package = child['process_package']
        for index, path in enumerate([package['spec'], package['plan'], *package['tasks']]):
            record = self.record(child['process_forecast_ids'][index], 0, path,
                                 size=1000, added=10)
            record['bounds'][0]['boundary'] = child['id']
            self.delivery['process_records'].append(record)
            self.assertFalse((self.repo / path).exists())
        # Validate every declared package, even before overflow makes it eligible.
        for root_subjects in ([], [120] * 30):
            with self.subTest(root_subjects=len(root_subjects)):
                root['process_commit_subject_bytes'] = root_subjects
                child['process_commit_subject_bytes'] = []
                self.emit(); self.commit('missing candidate process subjects')
                self.assert_refused(self.project(0))
                child['process_commit_subject_bytes'] = [120]
                self.emit(); self.commit('complete candidate process subjects')
                result = self.project(0)
                self.assertEqual(result.returncode, 3 if root_subjects else 0, result.stderr)
                if root_subjects:
                    self.assertEqual(json.loads(result.stdout)['recommended_boundary']['id'], 'future')

    def test_nonancestor_ownership_ranges_cover_full_reachable_difference(self):
        start = self.head
        process_ranges = list(self.ranges)
        branch = self.git('branch', '--show-current')
        self.git('switch', '-qc', 'side')
        self.write('side.txt', 'side effect\n'); side = self.commit('side work', 1)
        self.git('switch', '-q', branch)
        self.head = start
        self.write('main.txt', 'main effect\n'); main = self.commit('main work', 2)
        self.git('merge', '--no-ff', '-qm', 'merge owned work', 'side')
        merge = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.git('rev-list', main + '..' + side).splitlines(), [side])
        self.assertEqual(set(self.git('rev-list', side + '..' + merge).splitlines()), {main, merge})
        self.head = merge
        self.ranges = process_ranges + [
            (1, dict(base=main, head=side), ['all']),
            (2, dict(base=side, head=merge), ['all'])]
        self.checkpoint()
        result = self.project(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])

    def test_outside_range_endpoint_is_rejected_even_with_exact_owned_coverage(self):
        start = self.head
        process_ranges = list(self.ranges)
        branch = self.git('branch', '--show-current')
        self.git('switch', '-qc', 'outside')
        self.write('outside.txt', 'outside evidence\n')
        outside = self.commit('outside work', 1)
        self.git('switch', '-q', branch)
        self.head = start
        self.write('owned.txt', 'owned effect\n'); owned = self.commit('owned work', 1)
        self.assertEqual(self.git('rev-list', outside + '..' + owned).splitlines(), [owned])
        self.ranges = process_ranges + [(1, dict(base=outside, head=owned), ['all'])]
        self.checkpoint()
        self.assert_refused(self.project(2))
        self.tasks[0]['task']['actual_ranges'] = [dict(base=start, head=owned)]
        self.emit(); self.commit('authenticated range endpoint')
        result = self.project(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])
        valid = dict(base=start, head=owned)
        for first, second in (([], []), ([valid], [valid]),
                              ([dict(base=start, head=outside)], [])):
            with self.subTest(first=first, second=second):
                self.tasks[0]['task']['actual_ranges'] = first
                self.tasks[1]['task']['actual_ranges'] = second
                self.emit(); self.commit('invalid ownership coverage')
                self.assert_refused(self.project(2))

    def test_result_rejects_impossible_member_metrics(self):
        result = self.project()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        value['metrics']['largest_member_bytes'] = 0
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.assert_refused(self.invoke('validate-result', '--input', '-', '--producer-exit', '0', input=raw))

    def test_future_subjects_are_charged_until_task_and_process_horizons(self):
        self.tasks[0]['task']['commit_subject_bytes'] = [50]
        self.tasks[1]['task']['commit_subject_bytes'] = [70]
        self.delivery['boundaries'][0]['process_commit_subject_bytes'] = [90]
        self.emit(); self.commit('subject reserves')
        results = [self.project(n) for n in (0, 1, 2)]
        for result in results: self.assertEqual(result.returncode, 0, result.stderr)
        roots = [json.loads(result.stdout)['metrics']['root_bytes'] for result in results]
        self.assertGreater(roots[0], roots[1])
        self.assertGreater(roots[1], roots[2])
        self.assertEqual(json.loads(results[2].stdout)['metrics'], self.actual()[0])

    def test_descending_horizons_cannot_hide_unfinished_contribution(self):
        self.tasks[0]['task']['records'] = [self.record('first', 1, 'future', horizon=2),
            self.record('second', 1, 'future', horizon=1, covers=['first', 'second'])]
        self.emit(); self.commit('invalid horizon')
        self.assert_refused(self.project(0))
