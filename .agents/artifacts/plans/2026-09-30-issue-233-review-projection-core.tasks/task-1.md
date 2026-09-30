# Task 1: Recover and authenticate the shared source closure

**Files:**
- Move with `git mv`: `home/common/agent-skills/skills/sdd/scripts/review-package` → `python/agent_tools/review_publish.py`; retain genuine move history while extracting the recovered responsibilities.
- Create: `python/agent_tools/review_pack.py`, `python/agent_tools/review_actual.py`, `python/agent_tools/review_budget.py`, `python/agent_tools/review_package.py`, `python/agent_tools/review_forecast.py`, `python/agent_tools/review_projection.py`, `python/agent_tools/review_feasibility.py`, `python/agent_tools/review_git.py`.
- Create/test: `tests/test_review_pack.py`, `tests/test_review_feasibility.py`, `tests/test_review_projection_cases.py`, `tests/test_review_history.py`.
- Modify/test: `tests/test_agent_tools_launchers.py`, `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/tests/test_review_package.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
- Modify: `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `justfile`, `CLAUDE.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/fix-loop.md`.

**Consumes:** spec D2–D7, recovery R1–R4; fixed child base from the root; frozen R2 commit `adf52bdba1e204a4945f811d9fea03c1836ddaa7` and R3 commit `35e6fd7aa59f11160b08047b967e0be6cd919bac`. The retained parent is read-only provenance. Complete pre-recovery actual acceptance and the committed plan are prerequisites, supplied by the controller.

**Produces:** source `python -m agent_tools.review_package PLAN BASE HEAD [OUTPUT]` and unchanged named detail CLI; source `python -m agent_tools.review_feasibility project --plan PATH --base SHA --head SHA --completed-through N [--package-name NAME]`; source `validate-result --input PATH|- --producer-exit 0|3`. Only the existing actual command gets managed registration here. All returned dictionaries and canonical wire fields retain R2/v3 definitions; the new raw-history module is internal, not a new CLI.

**Exact interfaces:** recover the existing callable signatures from the pinned source, without a gratuitous rewrite:
- `review_pack`: frozen `ReviewLimits`, `ReviewRecord`, `ReviewRecordSize`; `pack_whole_records(records, ceiling, *, strategy) -> tuple[bytes,...]`, `place_record_sizes(sizes, ceiling, *, strategy) -> tuple[tuple[int,...],...]`, `measure_lengths(root_bytes, sizes, limits) -> (metrics,status,violations)` and canonical manifest encoding. Actual manifest JSON preserves non-ASCII UTF-8/LF; forecast/result JSON is canonical ASCII/LF.
- `review_actual`: `CandidateInput`, `FutureCommit`, `ReviewCandidate`, `ReviewMeasurement`; `actual_inputs(repo,base,head,package_name,limits)`, `actual_inputs_from_trees(repo,base_tree,head_tree,*,base,head,commits,package_name,limits)`, `pack_input`, `measure_input`, `select_candidate(inputs,limits,*,transform=None,measurement_only=False)`; shared `RECORD_POLICY_SHA256`/`PACKING_POLICY_SHA256`. Keep these pinned callable signatures unchanged.
- `review_budget.describe(kind:str, *, policy:str|None=None) -> BudgetAuthority`; authority `check(kind,root)`, `validate_report(raw,boundary)`, `validate_detail(raw)` pins the same raw policy identity for every call. External `artifact-budget describe --kind KIND --format json [--policy PATH]` returns exactly `schema_version:1`, `kind:"artifact-budget-description"`, `artifact_kind`, the four `limits`, `report_wire_max_bytes`, `policy_sha256`. `check`, `validate-report`, `validate-detail-input` accept optional `--expected-policy-sha256`. Existing invocations remain compatible.
- `review_forecast.load_plan(repo:Path,plan:Path,base:str,head:str,authority:BudgetAuthority) -> ForecastPlan`; `edge_facts(repo,parent,commit,ordinal)->dict`, `ancestor(repo,base,head)->bool`, `commit_range(repo,base,head)->tuple[str,...]` retain their callers and route original-graph decisions through the new authority.
- `review_projection.project(repo:Path,plan:Path,base:str,head:str,completed_through:int,package_name:str|None=None)->dict`; `validate_result(raw:bytes,producer_exit:int,authority:BudgetAuthority)->bytes`; `reconstruct_owned(repo:Path,prerequisite_commit:str,owned_commits:Sequence[str])->Reconstruction` context manager. R3's `ReconstructionUnavailable(ForecastError)` retains `.code`, `.commit` and neutral diagnostics.
- New `review_git`: `HistoryError(Exception)` with `.code` (raw parent membership/order violations use `original_parent_mismatch`); frozen `OriginalCommit(oid:str,tree:str,parents:tuple[str,...],raw:bytes)`; `original_commit(repo:Path,oid:str)->OriginalCommit`; `original_range(repo:Path,base:str,head:str,*,topological:bool=True)->tuple[str,...]`; `original_ancestor(repo:Path,base:str,head:str)->bool`; `original_edge(repo:Path,parent:str,commit:str,ordinal:int)->None`. These authenticate raw object identity/ordered parents and reject inconsistent effective traversal. They import no review forecast/projection/publication module, avoiding cycles. Callers translate `HistoryError` into their existing invalid-input error with `raise ... from exc`, preserving its cause, bounded stderr and exit 2 (D9).

**Invariants:**
- Actual record/subject collection and every generic graph, edge, metadata-tail, prerequisite and direct reconstruction trust point use the same original-history authority. Invalid provenance fails before a conservative unsupported-proof refusal can hide any later invalid edge.
- Raw object hashes/tree/ordered parent headers authenticate history; `rev-list`, `merge-base`, signatures and rehashed evidence are observations to compare, never their own authority. A valid unrelated commit is not an original parent.
- Preserve signed-object and replacement defenses already present in recovered shared code. Graft/replacement/shallow/environment/config routes changing or preventing original proof fail closed. Source refs/index/worktree/objects remain unchanged; generated reconstruction objects exist only in disposable storage.
- Recovered generic behavior includes exact dependency prerequisites; no synthetic combination, invented dependency, general hunk proof or retained replay. Larger actual records win, completed forecasts need owned effects, future same-path bounds include the entire ordered prefix, and huge scalar forecasts do not allocate proportional buffers.
- D7 wiring adds only `review-package` to the table, removes its superseded legacy mapping, repoints minimum living invocations and updates their existing assertions. `review-feasibility` remains absent from that table until Task 2. No new consumer feasibility gate.

- [ ] **Step 1: Recover the existing source contracts as tests, then add raw-history regressions.** Read each file first. Recover `tests/test_review_pack.py` and `tests/test_review_feasibility.py` from R2, `tests/test_review_projection_cases.py` from R3; port R1's exact source subprocess/budget/legacy test effects to current files. Register all four new test modules in the full recipe. Exclude retained tests/registration. Prior assertions are contracts, not fresh acceptance. Add the following complete tests to `tests/test_review_history.py` (the recovered fixture is an existing source seam):

```python
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
```

Use disposable fixtures, clean controls and unchanged-input assertions. Review environment/config/missing-object defenses before the source gate; altered graphs are invalid, never neutral refusal.

D7/D8 also require the relocated existing managed command to work. Add only `review-package` to `LAUNCHER_FLOOR` and this method to the existing `AgentToolsLauncherTest` class in `tests/test_agent_tools_launchers.py`; the generic installed test belongs to Task 2:

```python
    def test_relocated_actual_command_matches_source(self):
        import json
        import sys
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'actual-parity'
        top.mkdir()
        repo = top / 'repo'; repo.mkdir()
        home = top / 'home'; home.mkdir()
        (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
        env = {k: v for k, v in os.environ.items() if k not in
               ('PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        env.update(HOME=str(home), PYTHONPATH=str(source / 'python'),
                   PATH=self.dependency_env()['PATH'])
        def git(*args):
            result = subprocess.run(['git', *args], cwd=repo, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.decode().strip()
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test'); git('config', 'commit.gpgsign', 'false')
        (repo / 'value.txt').write_text('before\n')
        git('add', '-A'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
        (repo / 'value.txt').write_text('after\n')
        (repo / 'plan.md').write_text('# Plan\n\n## Task index\n\nTask 1 — Case — value.txt — full — '
                                    '[task-1.md](plan.tasks/task-1.md)\n')
        (repo / 'plan.tasks').mkdir(); (repo / 'plan.tasks/task-1.md').write_text('# Task 1\n')
        git('add', '-A'); git('commit', '-qm', 'change'); head = git('rev-parse', 'HEAD')
        roots = []
        for label in ('source', 'built'):
            out = top / label; out.mkdir(); root = out / 'review.json'; roots.append(root)
            childenv = dict(env)
            argv = [sys.executable, '-m', 'agent_tools.review_package']
            if label == 'built':
                argv = [str(self.root / '.agents/bin/review-package')]
                childenv.update(PYTHONPATH=str(self.hostile), NIX_PYTHONPATH=str(self.hostile))
            produced = subprocess.run([*argv, str(repo / 'plan.md'), base, head, str(root)],
                                      cwd=repo, env=childenv, capture_output=True)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            self.assertNotIn(MARKER.encode(), produced.stdout + produced.stderr)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json'], env=env, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(produced.stdout)['artifact']['metrics'],
                             json.loads(checked.stdout)['metrics'])
        self.assertEqual(roots[0].read_bytes(), roots[1].read_bytes())
        for member in roots[0].with_suffix('.shards').iterdir():
            self.assertEqual(member.read_bytes(), (roots[1].with_suffix('.shards') / member.name).read_bytes())
```

B1 requires adapting the existing probe, not changing the legacy actual parser. Replace `hostile_env` and `test_a_hostile_agent_tools_on_every_channel_is_ignored`, adding `dependency_env`, with this code. Replace the nearby `MISUSE_USAGE` comment with: “Legacy commands may treat --help as misuse, including parser-backed commands with help disabled; pin each existing exit/stdout/stderr contract.” Keep its context-map prefix entry. In `test_each_hostile_channel_is_live_without_the_launcher`, derive `clean` from `self.dependency_env().items()` instead of `os.environ.items()`; preserve all three live-channel controls and their exit-97/marker assertions.

```python
    def dependency_env(self):
        home = self.hostile / 'dependencies'
        bins = self.hostile / 'dependency-bin'
        if not home.exists():
            home.mkdir(); bins.mkdir()
            (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
            (bins / 'python3').symlink_to(self.launchers()['review-package'][0])
        return dict(os.environ, HOME=str(home),
                    PATH=str(bins) + os.pathsep + str(self.root / '.agents/bin')
                    + os.pathsep + os.environ['PATH'])

    def hostile_env(self):
        return dict(self.dependency_env(), PYTHONPATH=str(self.hostile),
                    NIX_PYTHONPATH=str(self.hostile))

    def test_a_hostile_agent_tools_on_every_channel_is_ignored(self):
        for name in self.launchers():
            with self.subTest(launcher=name):
                completed = self.run_child(
                    [str(self.root / '.agents/bin' / name), '--help'],
                    self.hostile_env(), self.hostile)
                if name == 'review-package':
                    self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                                     (2, '', 'review-package: invalid invocation\n'))
                elif name in MISUSE_USAGE:
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertEqual(completed.stdout, '')
                    self.assertIn(MISUSE_USAGE[name], completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertTrue(completed.stdout.startswith(f'usage: {name} '), completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)
```

The private layout selects built budget dependencies/interpreter; dependency failure cannot count as misuse. The actual parity method also uses `self.dependency_env()['PATH']`. Controller calls use the root’s matching environment.

- [ ] **Step 2: Establish red evidence.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_history.py tests/test_review_pack.py tests/test_review_feasibility.py tests/test_review_projection_cases.py`. At the child start, these modules and product imports are absent (verified during planning). After selective recovery, demonstrate that the redundant-graft generic/actual/direct-prerequisite tests fail on the uncorrected source. A missing-import red alone does not prove the provenance correction. Report concise failures; do not commit uncorrected source for a red checkpoint.

- [ ] **Step 3: Recover R1/R2 and only R3's generic effects.** Use frozen blobs/effects, never whole mixed commits. Preserve `git mv` and extraction history; a necessary separate move commit stays inside the fully reviewed/measured Task-1 range. Recover complete R2, plus only R3 typed refusals, generic proof cases and their registration. Omit `review_contributions.py`, retained tests/registration, parent artifacts and DERIVE/EVIDENCE files. Report R1–R4→child effects and omissions.

Implement `review_git` as the common authority per D4. Read the exact raw commit object through a replacement-disabled plumbing path, validate the requested object identity against Git's repository object format and recomputed object hash, strictly extract one tree plus the original ordered parent list from the header, and resolve/authenticate its required ancestry closure. Never use traversal output to supply the expected parents. Inspect effective ancestry sources (common/worktree Git metadata, environment and config, including alternate graft/replacement/shallow routes); reject virtualization that changes or prevents proof. Compare each effective traversal's complete membership and ordered parents with the original authority before accepting it. Keep original commit enumeration/subject order required by the actual manifest; topological ownership expansion remains parent-before-child. Reuse raw authority without caching across a provenance-changing boundary. Resolve abbreviations only at the legacy actual CLI as before; the committed v3 contract still requires full IDs.

Apply `original_edge` before building any diff facts: ordinal is a non-boolean integer indexing the raw parent list, and both parent/child identities/tree facts must authenticate. Apply range/ancestor authority at actual `_commits` and inputs, `full_commit`/`ancestor`/`commit_range`, ownership including process-only tails, `_prerequisite`, direct reconstruction and its subject/manifest ordering. Authenticate the entire requested original edge closure before creating a reconstruction refusal; all later edges remain checked even if an earlier whole-path operation will be unsupported. Preserve pure tree-diff construction for authenticated disposable reconstructed trees. Translate invalid history at library and CLI boundaries without swallowing original failure context.

Reconstruction then checks exact prerequisite closure/tree and every touched original preimage/postimage; merges retain all parent edges and prove each included effect exactly once. Honest whole-path failures stay neutral typed unavailability, with no partial tree/metrics/success. Keep the R2 canonical loader/result schemas, bounded decoding, symbolically measured huge records/subjects, adaptive policy and independent policy pinning. Correct only contract gaps exposed by these tests and the spec; no adapter or alternative estimator.

For D7 relocate the actual command in the table and remove the old Nix mapping in this same coherent commit; update only actual-command references in CLAUDE and sdd's three living files plus their existing assertions. Keep remaining docs truthful about the absent generic launcher. Register source tests in `justfile`. Build import checks remain meaningful; no temporary duplicate command or broken mapping.

- [ ] **Step 4: Verify the whole recovered/corrected source contract.** Run the focused command below and require no failures:

```sh
PYTHONPATH=python python3 -m unittest tests/test_review_history.py tests/test_review_pack.py tests/test_review_feasibility.py tests/test_review_projection_cases.py home/common/agent-skills/tests/test_review_package.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

Keep every frozen assertion, covering: ordinary/detail/safe actual publication and all caps/edges; empty/rename/binary/generated records; hostile diff settings and exact-rename policy; every adaptive choice and initial fallback; policy changes between describe/check/report/detail validation; strict full-indexed committed v3 linkage, malformed canonical data, unknown/bool/duplicate/nonfinite fields, dirty/symlink/unsafe inputs; ownership gaps/overlaps/topology/outside endpoints and undeclared product tails; actual/future substitution/completed absence, cumulative shared paths and huge exact symbolic bounds; actual-only exact producer/checker parity; graph/partition/dependency/prerequisite rejection; separate real disjoint-path/shared-path positives, each ranking tie-break, order reversal, unrelated-cheaper exclusion and no-fit null; dependent/independent same-path, split/context/relocation/merge/synthetic refusal with complete evidence. Tighten conflicting historical expectations to authenticated closure; never delete the assertion. Review tree/record/metric equality, not counts.

Run `just agent-workflow-tests` and `just build`; capture logs outside the worktree and summarize failing lines or exit/count. Run `just agent-installed-skill-tests` and require the new actual parity method to execute without a skip; source/built manifests/shards and independently checked metrics must match. Do not add generic installed assertions yet. The root's complete actual gate includes every recovery/ref/fix/process effect; exact-count assertions or subject checks over an unscoped range are forbidden. Inspect history with `git log --follow -- python/agent_tools/review_publish.py`; an actual visible move from the legacy path is required. Verify `lib/agent-tools.nix` includes `review-package` and excludes `review-feasibility` at this boundary.

- [ ] **Step 5: Commit and stop at the mandatory source gate.** Use the root’s matching gate environment for every controller producer/checker/project/validator call. Stage only the Files above; signed subject `feat(review): recover generic source with original Git ancestry` plus root co-author. Report task-start/task-head, recovery/omission manifest, tests/build and concerns through SDD. Controller performs independent full-lane review, complete actual production/checking and the root's earliest-source gate, including checkpoint ownership refresh, corrected closure fingerprint and entire committed-plan projection at completed-through 1. This task is not accepted by historical Task-1/2 reviews. No Task-2 file edits until validated exit 0, exact identity/metric agreement and within-budget status. A fix uses its own signed commit and fresh review/complete gate; exit 2/3 stops.

## Forecast basis

Frozen U10 complete-record measurements below are relative to the child base, not the parent base. Unless marked R3 they use R2; an immutable commit/path identifies its exact blob. The operation is add for new modules/tests, delete for the old script, modify otherwise. Measurements use fixed full-index/a-b/Myers/no-heuristics/no-external/no-textconv flags; rename detection is disabled solely for a conservative add/delete move forecast, never for production. U0 cannot exceed these U10 upper templates for the same operation. Recovery table digest and allowances are recorded below; source bytes alone were not used as diff sizes. Existing child additions in unrelated areas are never copied wholesale from an older file.

| Path (R2 unless marked) | Measured U10 bytes / + / − | Correction estimate bytes / + / − | Final bound bytes / + / − |
|---|---:|---:|---:|
| `python/agent_tools/review_pack.py` | 7705 / 203 / 0 | 512 / 8 / 0 | 8217 / 211 / 0 |
| `python/agent_tools/review_actual.py` | 22093 / 463 / 0 | 3072 / 64 / 0 | 25165 / 527 / 0 |
| `python/agent_tools/review_budget.py` | 6609 / 131 / 0 | 1024 / 16 / 0 | 7633 / 147 / 0 |
| `python/agent_tools/review_publish.py` | 26088 / 647 / 0 | 1024 / 16 / 0 | 27112 / 663 / 0 |
| `python/agent_tools/review_package.py` | 3135 / 75 / 0 | 512 / 8 / 0 | 3647 / 83 / 0 |
| `python/agent_tools/review_forecast.py` | 28487 / 562 / 0 | 5120 / 96 / 0 | 33607 / 658 / 0 |
| `python/agent_tools/review_projection.py` (R3) | 22108 / 364 / 0 | 6144 / 112 / 0 | 28252 / 476 / 0 |
| `python/agent_tools/review_feasibility.py` | 2972 / 58 / 0 | 512 / 8 / 0 | 3484 / 66 / 0 |
| `home/common/agent-skills/skills/sdd/scripts/review-package` | 45975 / 0 / 1185 | 0 / 0 / 0 | 45975 / 0 / 1185 |
| `home/common/agent-skills/scripts/artifact_budget.py` | 6772 / 39 / 6 | 1024 / 16 / 16 | 7796 / 55 / 22 |
| `home/common/agent-skills/tests/test_artifact_budget.py` | 4210 / 40 / 0 | 1024 / 16 / 16 | 5234 / 56 / 16 |
| `home/common/agent-skills/tests/test_review_package.py` | 21966 / 129 / 48 | 2048 / 32 / 32 | 24014 / 161 / 80 |
| `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | 2506 / 6 / 7 | 512 / 8 / 8 | 3018 / 14 / 15 |
| `tests/test_review_pack.py` | 13897 / 218 / 0 | 512 / 8 / 0 | 14409 / 226 / 0 |
| `tests/test_review_feasibility.py` | 56092 / 886 / 0 | 1024 / 16 / 0 | 57116 / 902 / 0 |
| `tests/test_review_projection_cases.py` (R3) | 20279 / 310 / 0 | 1024 / 16 / 0 | 21303 / 326 / 0 |
| `lib/agent-tools.nix` | 946 / 1 / 0 | 256 / 2 / 2 | 1202 / 3 / 2 |
| `home/common/agent-skills/default.nix` | 1743 / 0 / 12 | 512 / 4 / 4 | 2255 / 4 / 16 |
| `justfile` | 1534 / 2 / 0 | 512 / 4 / 4 | 2046 / 6 / 4 |
| `CLAUDE.md` | 8879 / 1 / 1 | 1024 / 4 / 4 | 9903 / 5 / 5 |
| `home/common/agent-skills/skills/sdd/SKILL.md` | 3808 / 2 / 2 | 512 / 4 / 4 | 4320 / 6 / 6 |
| `home/common/agent-skills/skills/sdd/final-review.md` | 4399 / 2 / 2 | 512 / 4 / 4 | 4911 / 6 / 6 |
| `home/common/agent-skills/skills/sdd/fix-loop.md` | 1930 / 1 / 1 | 512 / 4 / 4 | 2442 / 5 / 5 |

Frozen measurement table identity: `sha256:f7ea33a5264afdae72632026012ef299a076a179be6bccc4fefd1b774096765e` (SHA-256 of sorted-key compact ASCII JSON rows containing path, source commit, blob, file bytes/lines, U10 record bytes, additions/deletions and raw record SHA-256; rows retain table order). Reproduction reads each R2/R3 blob with `git show COMMIT:PATH` and fixed child-base `git diff --binary -U10 --no-renames --full-index --no-ext-diff --no-textconv --no-relative --src-prefix=a/ --dst-prefix=b/ --diff-algorithm=myers --no-indent-heuristic --inter-hunk-context=0 --no-color --line-prefix= --output-indicator-new=+ --output-indicator-old=- --output-indicator-context=' ' BASE COMMIT -- PATH`, with `core.quotePath=true`; count numstat with the same policy. `314,133` measured recovery bytes are not a review-package metric.

Correction allowances are scope-specific estimates replacing parent task ceilings, not arbitrary discounts: unchanged extraction/command/packer tests get 512 bytes; budget/legacy-query cases get 1,024; actual source gets 3,072 for authenticated collection; ownership loader gets 5,120 for closure/tail/edge checks; reconstruction gets 6,144 for pre-authentication/prerequisite defenses; legacy producer test adaptation gets 2,048. Ten-line context is already in each template. The table's added/deleted-line allowances bound those operations independently. Test-feasibility's 56,092-byte record is already large: only a 1,024-byte contract-correction allowance belongs there; new history cases have their own coherent file.

New authority estimate: 19,712 bytes, 240 added lines. This is 64 raw-object/hash/header lines + 64 closure/range/ancestor lines + 48 virtualization/comparison lines + 24 API/error lines + 40 review-fix lines, at 80 bytes/line (19,200) plus 512 for whole-record headers. These are finite source-operation estimates, not runtime limits. The measured source test code in Step 1 is 15002 bytes/267 lines; its full add-record template is 15781 bytes including plus prefixes and 512 header bytes. Add 4,096 bytes/48 lines for independent reviewer corrections, giving 19877 bytes/315 lines. No unbounded speculative test growth is hidden in another task. All source/API corrections must stay within these supported scopes or return for a committed forecast revision.

The commit-graph cache regression adds 23 lines/1,563 source bytes. Its final complete history record is 19,088 bytes/+329 lines; preserve the 19,877-byte bound and raise line support to 338, retaining nine correction lines.

Existing-actual installed method template: 3062 bytes/46 lines. Include original launcher file (8,002 bytes/170 lines) as conservative context, line prefixes, 512 header bytes and 1,024 bytes of floor/import/review allowance plus 2852 for B1: 15668 bytes. This is t1-26 and remains open through Task 2; its final cumulative support is in that member.

B1 probe/environment template: 1796 bytes/32 lines; plus line prefixes and 1,024 bytes for the comment, clean-control adaptation and review fixes = 2852 extra cumulative bytes. The installed bounds include this whole contribution through Task 2; no prior allowance was lowered. B2’s controller setup is process content. S1’s revised complete-envelope template is included in the source test measurement above.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"4e1211909f053bc1b0ab72f7f97ae4a33e0512b5","head":"9bc9b2a2f713719b7e9f73ababf57cc125da7218"}],"commit_subject_bytes":[120,120,120,120],"id":1,"records":[{"bounds":[{"added_lines":211,"boundary":"core","deleted_lines":0,"record_bytes":8217,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_pack.py"},{"bounds":[{"added_lines":527,"boundary":"core","deleted_lines":0,"record_bytes":25165,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-2","last_task":1,"owner":1,"path":"python/agent_tools/review_actual.py"},{"bounds":[{"added_lines":147,"boundary":"core","deleted_lines":0,"record_bytes":7633,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-3","last_task":1,"owner":1,"path":"python/agent_tools/review_budget.py"},{"bounds":[{"added_lines":663,"boundary":"core","deleted_lines":0,"record_bytes":27112,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-4","last_task":1,"owner":1,"path":"python/agent_tools/review_publish.py"},{"bounds":[{"added_lines":83,"boundary":"core","deleted_lines":0,"record_bytes":3647,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-5","last_task":1,"owner":1,"path":"python/agent_tools/review_package.py"},{"bounds":[{"added_lines":658,"boundary":"core","deleted_lines":0,"record_bytes":33607,"support":{"covers":["t1-6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-6","last_task":1,"owner":1,"path":"python/agent_tools/review_forecast.py"},{"bounds":[{"added_lines":476,"boundary":"core","deleted_lines":0,"record_bytes":28252,"support":{"covers":["t1-7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-7","last_task":1,"owner":1,"path":"python/agent_tools/review_projection.py"},{"bounds":[{"added_lines":66,"boundary":"core","deleted_lines":0,"record_bytes":3484,"support":{"covers":["t1-8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-8","last_task":1,"owner":1,"path":"python/agent_tools/review_feasibility.py"},{"bounds":[{"added_lines":0,"boundary":"core","deleted_lines":1185,"record_bytes":45975,"support":{"covers":["t1-9"],"kind":"authored-cumulative/v1"}}],"change":"delete","id":"t1-9","last_task":1,"owner":1,"path":"home/common/agent-skills/skills/sdd/scripts/review-package"},{"bounds":[{"added_lines":55,"boundary":"core","deleted_lines":22,"record_bytes":7796,"support":{"covers":["t1-10"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-10","last_task":1,"owner":1,"path":"home/common/agent-skills/scripts/artifact_budget.py"},{"bounds":[{"added_lines":56,"boundary":"core","deleted_lines":16,"record_bytes":5234,"support":{"covers":["t1-11"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-11","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_artifact_budget.py"},{"bounds":[{"added_lines":161,"boundary":"core","deleted_lines":80,"record_bytes":24014,"support":{"covers":["t1-12"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-12","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_review_package.py"},{"bounds":[{"added_lines":14,"boundary":"core","deleted_lines":15,"record_bytes":3018,"support":{"covers":["t1-13"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-13","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":226,"boundary":"core","deleted_lines":0,"record_bytes":14409,"support":{"covers":["t1-14"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-14","last_task":1,"owner":1,"path":"tests/test_review_pack.py"},{"bounds":[{"added_lines":902,"boundary":"core","deleted_lines":0,"record_bytes":57116,"support":{"covers":["t1-15"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-15","last_task":1,"owner":1,"path":"tests/test_review_feasibility.py"},{"bounds":[{"added_lines":326,"boundary":"core","deleted_lines":0,"record_bytes":21303,"support":{"covers":["t1-16"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-16","last_task":1,"owner":1,"path":"tests/test_review_projection_cases.py"},{"bounds":[{"added_lines":3,"boundary":"core","deleted_lines":2,"record_bytes":1202,"support":{"covers":["t1-17"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-17","last_task":2,"owner":1,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":4,"boundary":"core","deleted_lines":16,"record_bytes":2255,"support":{"covers":["t1-18"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-18","last_task":1,"owner":1,"path":"home/common/agent-skills/default.nix"},{"bounds":[{"added_lines":6,"boundary":"core","deleted_lines":4,"record_bytes":2046,"support":{"covers":["t1-19"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-19","last_task":1,"owner":1,"path":"justfile"},{"bounds":[{"added_lines":5,"boundary":"core","deleted_lines":5,"record_bytes":9903,"support":{"covers":["t1-20"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-20","last_task":2,"owner":1,"path":"CLAUDE.md"},{"bounds":[{"added_lines":6,"boundary":"core","deleted_lines":6,"record_bytes":4320,"support":{"covers":["t1-21"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-21","last_task":1,"owner":1,"path":"home/common/agent-skills/skills/sdd/SKILL.md"},{"bounds":[{"added_lines":6,"boundary":"core","deleted_lines":6,"record_bytes":4911,"support":{"covers":["t1-22"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-22","last_task":1,"owner":1,"path":"home/common/agent-skills/skills/sdd/final-review.md"},{"bounds":[{"added_lines":5,"boundary":"core","deleted_lines":5,"record_bytes":2442,"support":{"covers":["t1-23"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-23","last_task":1,"owner":1,"path":"home/common/agent-skills/skills/sdd/fix-loop.md"},{"bounds":[{"added_lines":240,"boundary":"core","deleted_lines":0,"record_bytes":19712,"support":{"covers":["t1-24"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-24","last_task":1,"owner":1,"path":"python/agent_tools/review_git.py"},{"bounds":[{"added_lines":338,"boundary":"core","deleted_lines":0,"record_bytes":19877,"support":{"covers":["t1-25"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-25","last_task":1,"owner":1,"path":"tests/test_review_history.py"},{"bounds":[{"added_lines":110,"boundary":"core","deleted_lines":194,"record_bytes":15668,"support":{"covers":["t1-26"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-26","last_task":2,"owner":1,"path":"tests/test_agent_tools_launchers.py"}]}}
```
