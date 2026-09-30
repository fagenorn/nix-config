# Task 2: Publish and verify the generic managed command

**Files:** Modify `lib/agent-tools.nix`, `CLAUDE.md`; modify/test `tests/test_agent_tools_launchers.py`.

**Consumes:** Task 1's source `review_package.main(argv=None)->int`, `review_feasibility.main(argv=None)->int`, canonical v3 project/result contracts and external pinned `artifact-budget describe/check/validate-*` behavior; existing isolated command-table launcher. Spec D1/D2/D5/D7 and the root's Global Constraints apply. Controller must supply the independently reviewed corrected source identity, exact committed plan identity, complete actual acceptance and the successful entire-plan source-gate result at completed-through 1. A task-range result or a report merely accepted by `validate-result` is insufficient.

**Produces:** managed `~/.agents/bin/review-feasibility` through the command table, alongside the already relocated actual command; living architecture text describing exactly the generic published behavior; source/built canonical and actual-package parity with hostile Python/Nix environment influence blocked. No retained replay claim, caller feasibility adoption or host activation.

**Invariants:**
- Keep the established launcher: unset `NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE`, then store interpreter `-I -m agent_tools.<module>`. No second command mapping or wrapper implementation.
- The built actual producer, projector, validator and external policy query use the same installed closure/policy and preserve all expected identities and four metrics. Logical basename is equal while physical output directories remain separate.
- Every test owns disposable Git/home/output state. Source and built results are obtained independently. No monkeypatched projector, model metric stub or accepted installed skip.
- Existing actual command remains usable unchanged; malformed canonical/result/exits fail with empty success stdout. Generic source correction discovered here returns to fresh source review and whole-plan projection before continuing publication acceptance.

- [ ] **Step 1: Add failing installed contracts.** Extend `LAUNCHER_FLOOR` with `review-feasibility`; Task 1 already added the actual command. Add `json`, `hashlib` and `sys` imports and this test method to the existing `AgentToolsLauncherTest` class. It uses only standard-library fixture setup so the installed recipe need not add source imports/PYTHONPATH:

```python
    def test_review_source_and_built_canonical_actual_parity(self):
        import hashlib
        import json
        import sys
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'review-case'
        top.mkdir()
        repo = top / 'repo'
        repo.mkdir()
        clean = {k: v for k, v in os.environ.items()
                 if k not in ('PYTHONPATH', 'NIX_PYTHONPATH',
                              'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        envs = {}
        for label, agents in (('source', source / 'home/common/agent-skills'),
                              ('built', self.root / '.agents')):
            home = top / (label + '-home')
            home.mkdir()
            if label == 'built':
                (home / '.agents').symlink_to(agents, target_is_directory=True)
                bins = agents / 'bin'
            else:
                lib = home / '.agents/lib/python'
                lib.mkdir(parents=True)
                (lib / 'artifact_budget.py').symlink_to(agents / 'scripts/artifact_budget.py')
                (lib / 'delivery_model').symlink_to(agents / 'scripts/delivery_model',
                                                    target_is_directory=True)
                (home / '.agents/share').mkdir()
                (home / '.agents/share/artifact-budget-policy.json').symlink_to(
                    agents / 'artifact-budget-policy.json')
                bins = agents / 'scripts'
            envs[label] = dict(clean, HOME=str(home),
                PATH=str(bins) + os.pathsep + clean['PATH'])
        envs['source']['PYTHONPATH'] = str(source / 'python')
        envs['built'].update(PYTHONPATH=str(self.hostile),
            NIX_PYTHONPATH=str(self.hostile), NIX_PYTHONPREFIX=str(self.hostile),
            NIX_PYTHONEXECUTABLE=str(self.hostile / 'no-python'))
        def run(argv, *, label='source', payload=None):
            return subprocess.run(argv, cwd=repo, env=envs[label], input=payload,
                                  capture_output=True, timeout=60)
        def git(*args):
            result = run(['git', *args])
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.decode().strip()
        def write(path, value):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value if isinstance(value, bytes) else value.encode())
        def commit(subject):
            git('add', '-A'); git('commit', '-qm', subject)
            return git('rev-parse', 'HEAD')
        def wire(value):
            return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True) + '\n').encode()
        def command(label, name, *args, payload=None):
            argv = ([sys.executable, '-m', 'agent_tools.' + name.replace('-', '_')]
                    if label == 'source' else [str(self.root / '.agents/bin' / name)])
            result = run([*argv, *args], label=label, payload=payload)
            self.assertNotIn(MARKER.encode(), result.stdout + result.stderr)
            return result
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test')
        git('config', 'commit.gpgsign', 'false')
        write('seed.txt', 'seed\n'); base = commit('base')
        write('seed.txt', 'seed\nchanged\n'); product = commit('product')
        package = dict(spec='spec.md', plan='plan.md', tasks=['plan.tasks/task-1.md'])
        paths = [package['spec'], package['plan'], *package['tasks']]
        records = [dict(id=f'p{n}', owner=0, path=path, change='add', last_task=1,
            bounds=[dict(boundary='core', added_lines=1, deleted_lines=0, record_bytes=1,
                support=dict(kind='authored-cumulative/v1', covers=[f'p{n}']))])
            for n, path in enumerate(paths)]
        delivery = dict(schema_version=3, kind='review-feasibility-delivery',
            delivery_base=base, proposed_boundary='core', derived_from=None,
            boundaries=[dict(id='core', parent=None, tasks=[1], acceptance='Generic source/built parity',
                depends_on=[], prerequisite=dict(kind='delivery-base'), process_package=package,
                process_forecast_ids=[r['id'] for r in records], process_commit_subject_bytes=[])],
            process_records=records, actual_evidence=dict(kind='git-range-ownership/v1',
                head=product, tree=git('rev-parse', product + '^{tree}'), process_ranges=[]))
        task = dict(schema_version=3, kind='review-feasibility-task', task=dict(id=1,
            commit_subject_bytes=[], actual_ranges=[dict(base=base, head=product)], records=[]))
        write('spec.md', '# Generic parity\n')
        write('plan.md', '# Plan\n\n## Task index\n\nTask 1 — Case — seed.txt — full — '
            '[task-1.md](plan.tasks/task-1.md)\n\n## Review feasibility delivery\n\n```json\n'
            + wire(delivery).decode() + '```\n')
        write('plan.tasks/task-1.md', '# Task 1\n\n## Review feasibility task\n\n```json\n'
            + wire(task).decode() + '```\n')
        head = commit('process package')
        before = git('status', '--porcelain'), git('rev-parse', 'HEAD^{tree}')
        projected = {}
        for label in ('source', 'built'):
            outdir = top / (label + '-out'); outdir.mkdir()
            root = outdir / 'review.json'
            actual = command(label, 'review-package', str(repo / 'plan.md'), base, head, str(root))
            self.assertEqual(actual.returncode, 0, actual.stderr)
            # The external checker uses the same private layout but no hostile startup variables.
            checkenv = dict(envs[label])
            for key in ('PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE'):
                checkenv.pop(key, None)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json'], env=checkenv, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            metrics = json.loads(actual.stdout)['artifact']['metrics']
            self.assertEqual(metrics, json.loads(checked.stdout)['metrics'])
            result = command(label, 'review-feasibility', 'project', '--plan', str(repo / 'plan.md'),
                '--base', base, '--head', head, '--completed-through', '1', '--package-name', 'review.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['metrics'], metrics)
            self.assertEqual((value['base'], value['head'], value['tree']),
                             (base, head, git('rev-parse', head + '^{tree}')))
            self.assertEqual((value['completed_through'], value['boundary'], value['package_name']),
                             (1, 'core', 'review.json'))
            self.assertEqual((value['state'], value['budget_status'], value['violations'],
                              value['recommended_boundary']), ('complete', 'within_budget', [], None))
            validated = command(label, 'review-feasibility', 'validate-result', '--input', '-',
                                '--producer-exit', '0', payload=result.stdout)
            self.assertEqual((validated.returncode, validated.stdout), (0, result.stdout), validated.stderr)
            for bad, status in ((b'', '0'), (result.stdout + b' ', '0'),
                    (result.stdout.replace(b'"schema_version":3', b'"schema_version":true'), '0'),
                    (result.stdout, '3')):
                refused = command(label, 'review-feasibility', 'validate-result', '--input', '-',
                                  '--producer-exit', status, payload=bad)
                self.assertEqual((refused.returncode, refused.stdout), (2, b''), refused.stderr)
            projected[label] = result.stdout
            description = subprocess.run(['artifact-budget', 'describe', '--kind', 'review-package',
                '--format', 'json'], env=checkenv, capture_output=True)
            self.assertEqual(description.returncode, 0, description.stderr)
            policy = Path(checkenv['HOME']) / '.agents/share/artifact-budget-policy.json'
            self.assertEqual(json.loads(description.stdout)['policy_sha256'],
                             'sha256:' + hashlib.sha256(policy.read_bytes()).hexdigest())
            self.assertEqual(value['artifact_policy_sha256'], json.loads(description.stdout)['policy_sha256'])
            refused = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json', '--expected-policy-sha256', 'sha256:' + '0' * 64],
                env=checkenv, capture_output=True)
            self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertEqual(projected['source'], projected['built'])
        self.assertEqual((top / 'source-out/review.json').read_bytes(),
                         (top / 'built-out/review.json').read_bytes())
        for a in (top / 'source-out/review.shards').iterdir():
            self.assertEqual(a.read_bytes(), (top / 'built-out/review.shards' / a.name).read_bytes())
        self.assertEqual(before, (git('status', '--porcelain'), git('rev-parse', 'HEAD^{tree}')))
```

The fixture uses actual-only process records whose owned effects are all present; its tiny bound values are never estimates for this delivery. Source and built equality compares the entire closed canonical result, including forecast/package/ownership/packing/policy identities and record counts, not only metrics. The full source cases already test recommendations, refusal classes and policy change during operations; this installed seam verifies deployment preserves that behavior. Preserve existing hostile-channel controls so a dead adversary cannot make isolation appear correct.

- [ ] **Step 2: Verify red at Task-1 boundary.** Build the current source head and run `just agent-installed-skill-tests`. The new floor/parity checks must fail because Task 1 deliberately omits the `review-feasibility` command-table row. The pre-task launcher and floor were inspected during planning; the generic module/launcher are absent at the original child base. Missing `AGENT_SKILLS_INSTALLED_HOME` is not a red or passing installed result: the recipe must supply the real built layout.

- [ ] **Step 3: Publish minimally.** Add `review-feasibility` to `lib/agent-tools.nix` beside the existing actual row; use the generated isolated launcher unchanged. Update CLAUDE's current agent-helper architecture paragraph to name the actual/shared-generic source/managed commands, external budget identity and read-only project/validate role. Do not alter historical plans or imply retained replay or caller rollout. Preserve all unrelated current CLAUDE content. This is the second ordered contribution to all three shared files; its forecast is cumulative from the immutable child base, not merely this task's patch.

- [ ] **Step 4: Verify final behavior.** Run Task 1's focused source command, `just agent-workflow-tests`, `just build`, then `just agent-installed-skill-tests`. Require zero failures and no skip in the installed launcher class; inspect the two managed command rows, unique actual mapping and built module import checks. Require real source/built result-byte equality, manifest/shard-byte equality, independent budget metrics and hostile-channel controls. New command-specific failures are not waived by a green help probe. Keep logs outside the worktree and report commands/exits/counts succinctly.

- [ ] **Step 5: Commit and deliver evidence.** Stage only these three Files, sign `feat(review): publish generic projection command` with root co-author. Controller records Task-2 ranges and a process-only ownership checkpoint; rechecks affected artifact budgets and complete actual package; projects completed-through 2 with exact actual basename and requires actual-only candidate/four-metric parity. Fresh task review and separate final conformance/correctness reviews accept the complete fixed-base delivery, including process artifacts. No task-range or historical result clears this gate. Source fixes require fresh source review/projection; actual/projected exit 2/3 stops. Required CI remains mandatory before merge.

## Forecast basis

The installed test above is a measured source template; its complete added lines plus existing ten-line context and headers support a finite modification forecast, with 4,096 bytes/60 added and 20 deleted lines reserved for the floor/imports, fixture correction and required review fixes. Task 1's measured actual-command table/CLAUDE relocation templates are the base for cumulative Task-2 support. The new command row changes one line; architecture addition reserves 1,024 bytes with 12 added/12 deleted lines and ten-line context. Task-2 shared-path bounds must cover both IDs in order. Scope exceeding these operations requires a supported committed forecast revision and the full gates, never a lower estimate.

Measured installed-method template: 9408 bytes/140 lines. For a conservative complete modification record include the entire original launcher file (8,002 bytes/170 lines), every plus/minus prefix and 512 bytes of headers: 18232 bytes, then 4,096 bytes of generic operation/review reserve plus Task 1's 4160-byte actual-method/floor contribution = 26488 bytes. Deletion allowance covers the original file plus 20 lines; additions cover both methods plus 60. This overcounts unaffected context deliberately. Shared cumulative final bounds: command table 1458 bytes/+6/−4; CLAUDE 11951 bytes/+17/−17, including both Task-1 relocation and Task-2 generic prose.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[120,120,120],"id":2,"records":[{"bounds":[{"added_lines":6,"boundary":"core","deleted_lines":4,"record_bytes":1458,"support":{"covers":["t1-17","t2-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-1","last_task":2,"owner":2,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":17,"boundary":"core","deleted_lines":17,"record_bytes":11951,"support":{"covers":["t1-20","t2-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-2","last_task":2,"owner":2,"path":"CLAUDE.md"},{"bounds":[{"added_lines":246,"boundary":"core","deleted_lines":190,"record_bytes":26488,"support":{"covers":["t1-26","t2-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-3","last_task":2,"owner":2,"path":"tests/test_agent_tools_launchers.py"}]}}
```
