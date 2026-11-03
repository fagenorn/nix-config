# Task 3: Forecasts accept `rename` with `old_path`

A plan can now forecast a move. `change: rename` carries a required `old_path`, is bounded like an add of its new path, and once completed consumes its old path. `fileless` stays refused (spec § Forecast contract, § Completed effects; D7, D8, D9, D13, D17).

Run every long command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with the timeout shown.

**Files:**
- Modify: `python/agent_tools/review_forecast.py` (`_records` only)
- Modify: `python/agent_tools/review_projection.py` (`_completed_effects` and `project` only)
- Modify: `python/README.md` (the **Review feasibility forecast** paragraph)
- Test: `tests/test_review_feasibility.py` (a `seed` hook in `SourceProjectionFixture`, three rows in the refusal table)
- Test: `tests/test_review_projection_cases.py` (new class `RenameForecastCases` at the end)

**Interfaces:**
- Consumes (Task 2): v2 measurement, where an edited move is one `R<NNN>` record keyed by its new path, and `edge_facts` records `{"operation": "R<NNN>", "path": <new>, "old_path": <old>, …}`.
- Produces: the forecast contribution `{"id", "owner", "path", "old_path", "change": "rename", "last_task", "bounds"}`; `_records(delivery, tasks, boundaries)` keeps its signature (D7, D10). `SourceProjectionFixture.seed: dict[str, str]` is extra base files, `{}` by default.

**Invariants:**
- `_records`. A record is a `rename` when it is a dict whose `change` is `"rename"`; it must have exactly the keys `id owner path old_path change last_task bounds`. Every other record keeps exactly `id owner path change last_task bounds`, so an `old_path` on any other change, or a `rename` without one, fails `closed` (`invalid contribution fields`). `old_path` passes `path_name`, and `old_path == path` raises `ForecastError("rename must change its path")`. `change` must be one of `add modify delete rename fileless`, and `fileless` alone still raises `projection_unavailable: operation requires retained adapter proof`. Ordering, prefix, horizon and boundary checks are unchanged: a rename accumulates under its new `path`. `schema_version` stays 3.
- `project`. The future-content subject check covers `{"add", "modify", "rename"}`: a future task whose rename targets a path absent at the head needs `commit_subject_bytes` (`future task content lacks a commit subject forecast`).
- `_project_input` is unchanged. A future rename is charged at its new path as the larger of its bound and any current record there, plus its unobserved lines. An actual record of `old_path` stays in the projection until the rename completes (D8).
- `_completed_effects`, over the boundary's completed records (`last_task <= completed`):
  - `consumed` is the set of `old_path`s of completed `rename` records.
  - Each completed record still needs an owned effect on its path, an edge record whose `path` or `old_path` is the record's path. An `R<NNN>` edge record at the new path counts, and no `R` edge is required of a rename (D9).
  - A completed `rename` whose `old_path` has no actual record and is present in the candidate's tree raises `ForecastError("completed rename did not consume its old path")`.
  - A completed record whose path has no actual record passes only when its path is absent from the candidate's tree, and either (a) it is a `delete` with an owned effect that removed the path, an effect with `operation == "D"` or an `R…` operation whose `old_path` is the path, or (b) its path is in `consumed`. Otherwise it fails with the existing `completed contribution has no final actual effect`, or `completed deletion is not proven absent` when the path survives.

- [ ] **Step 1: Write the failing tests**

`tests/test_review_feasibility.py`:
- In `SourceProjectionFixture`, add the class attribute `seed = {}  # extra base files: path -> text`, after `plan_stem`.
- In `setUp`, directly after `self.write('delete.txt', 'gone later\n')`, add `for path, content in self.seed.items(): self.write(path, content)` as a two-line loop.
- In `test_identity_invocation_and_closed_schema_refusals`, add after the `fileless` mutation:

```python
                     lambda d: d['process_records'][0].update(old_path='elsewhere.md'),
                     lambda d: d['process_records'][0].update(change='rename', old_path=d['process_records'][0]['path']),
                     lambda d: d['process_records'][0].update(change='rename', old_path='../escape'),
```

The existing `change='rename'` row, which carries no `old_path`, stays and is now refused by the closed key set. These rows touch no hunk of #559's branch (D17).

Append to `tests/test_review_projection_cases.py`:

```python
MOVED = ''.join(f'moved line {n:02d}\n' for n in range(60))


class RenameForecastCases(source_cases.SourceProjectionFixture, unittest.TestCase):
    """Issue 569: a forecast `rename` names its old path and is bounded by the record measured at its new path."""
    seed = {'old.txt': MOVED}

    def rename(self, name, owner, old, new, *, size, horizon=None, covers=None):
        row = self.record(name, owner, new, change='rename', size=size, added=2, deleted=2,
                          horizon=horizon or owner, covers=covers)
        row['old_path'] = old
        return row

    def move(self, old, new, owner, *, keep=False):
        """Commit `old`'s content at `new` with two lines edited, deleting `old` unless `keep`."""
        content = (self.repo / old).read_text().replace('moved line 10', 'edited line 10').replace(
            'moved line 40', 'edited line 40')
        if not keep:
            (self.repo / old).unlink()
        self.write(new, content)
        return self.commit('move ' + old, owner)

    def test_future_rename_projects_and_bounds_the_measured_record(self):
        from agent_tools.review_actual import actual_inputs
        from agent_tools.review_pack import ReviewLimits
        self.tasks[0]['task']['commit_subject_bytes'] = [120]
        self.tasks[0]['task']['records'] = [self.rename('moved', 1, 'old.txt', 'new.txt', size=4096)]
        self.emit(); self.commit('forecast')
        before = self.project(0)
        self.assertEqual(before.returncode, 0, before.stderr)
        before = json.loads(before.stdout)
        self.assertEqual(before['projected_record_count'], before['actual_record_count'] + 1)
        self.move('old.txt', 'new.txt', 1)
        self.tasks[0]['task']['commit_subject_bytes'] = []
        self.checkpoint()
        measured, manifest = self.actual()
        initial = next(actual_inputs(self.repo, self.base, self.head, 'review.json',
                                     ReviewLimits(16384, 65536, 8, 524288)))
        (record,) = [r for r in initial.records if r.path == 'new.txt']
        self.assertTrue(record.payload.startswith(b'diff --git a/old.txt b/new.txt\nsimilarity index '))
        self.assertNotIn('old.txt', [r.path for r in initial.records])
        self.assertLessEqual(record.source_bytes, 4096)
        self.assertEqual(manifest['coverage']['file_diff_count'], before['projected_record_count'])
        self.assertLessEqual(measured['total_bytes'], before['metrics']['total_bytes'])
        completed = self.project(1)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['metrics'], measured)

    def test_future_rename_to_an_absent_path_needs_a_subject_forecast(self):
        self.tasks[0]['task']['records'] = [self.rename('moved', 1, 'old.txt', 'new.txt', size=4096)]
        self.emit(); self.commit('forecast without subject')
        refused = self.project(0)
        self.assert_refused(refused)
        self.assertIn(b'future task content lacks a commit subject forecast', refused.stderr)

    def test_completed_rename_consumes_an_earlier_modify_of_its_old_path(self):
        self.tasks[0]['task']['records'] = [self.record('touch', 1, 'old.txt', change='modify', size=2048, horizon=1)]
        self.tasks[1]['task']['records'] = [self.rename('moved', 2, 'old.txt', 'new.txt', size=4096)]
        self.write('old.txt', MOVED + 'appended\n'); self.commit('modify old', 1)
        self.move('old.txt', 'new.txt', 2)
        self.checkpoint()
        result = self.project(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])

    def test_forecast_delete_and_add_that_git_pairs_is_accepted(self):
        self.tasks[0]['task']['records'] = [
            self.record('gone', 1, 'old.txt', change='delete', size=4096, added=0, deleted=60, horizon=1),
            self.record('new', 1, 'new.txt', change='add', size=4096, added=60, horizon=1)]
        self.move('old.txt', 'new.txt', 1)
        self.checkpoint()
        result = self.project(1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['metrics'], self.actual()[0])

    def test_completed_rename_whose_old_path_survives_is_refused(self):
        self.tasks[0]['task']['records'] = [self.rename('moved', 1, 'old.txt', 'new.txt', size=4096)]
        self.move('old.txt', 'new.txt', 1, keep=True)
        self.checkpoint()
        result = self.project(1)
        self.assert_refused(result)
        self.assertIn(b'completed rename did not consume its old path', result.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH=python timeout 900 python3 -m unittest tests.test_review_projection_cases.RenameForecastCases tests.test_review_feasibility.SourceProjectionTest.test_identity_invocation_and_closed_schema_refusals 2>&1 | grep -E '^(FAIL|ERROR):|^(OK|FAILED)'`
Expected: `FAILED (failures=5)`, one failure for each `RenameForecastCases` test:
- The four rename cases stop at `invalid contribution fields`.
- `test_forecast_delete_and_add_that_git_pairs_is_accepted` stops at `completed contribution has no final actual effect`.
The refusal-table test passes before and after: each of its new rows is refused at Task 2's head too.

- [ ] **Step 3: Implement**

Apply the invariants in `_records`, `project` and `_completed_effects`. Precede the consumption check with the comment `# A completed rename consumes its old path unless an actual record still holds it (issue 569).`

In `python/README.md`'s **Review feasibility forecast** paragraph:
- Replace `\`change\` (\`add\`, \`modify\` or \`delete\`; \`rename\` and \`fileless\` are refused as \`projection_unavailable\`),` with `\`change\` (\`add\`, \`modify\`, \`delete\` or \`rename\`; \`fileless\` is refused as \`projection_unavailable\`), \`old_path\` on a \`rename\` and on no other change (the path the content moves from, a safe path other than \`path\`),`.
- After the sentence ending `the projection never undercounts what \`review-package\` later measures.`, insert: `A \`rename\` accumulates under its new \`path\`. Its bound is the whole record \`review-package\` will measure there: Git's rename section from the base blob the content came from to the final blob, earlier edits in the boundary included, or the header alone for a pure move. When Git will not pair the move, because \`old_path\` survives at the boundary's end or another added path matches it better, the bound is the whole-file addition. Until the rename completes, any record of \`old_path\` stays charged, and a future rename to a path absent at the head needs a subject forecast, as future \`add\` and \`modify\` content does. A completed rename consumes \`old_path\`: \`old_path\` must be absent from the candidate's tree unless the package still holds a record for it. A completed contribution with no record of its own is accepted only when its path is absent from that tree, and it is either a \`delete\` with an owned effect that removed its path (a \`D\` record, or a rename record moving it away), or the \`old_path\` of a completed rename in the same boundary (#569).`

- [ ] **Step 4: Verify**

Run Step 2's command. Expected: `OK` (6 tests).

Run: `env PYTHONPATH=python timeout 1800 python3 -m agent_tools.suite_runner --jobs 4 tests/test_review_feasibility.py tests/test_review_projection_cases.py tests/test_review_history.py home/common/agent-skills/tests/test_review_package.py 2>&1 | grep -E 'suite-runner: (failed|summary)'`
Expected: `suite-runner: summary members=4 passed=4 failed=0 …`.

```bash
if git grep -n -F 'in {"rename", "fileless"}' -- python/agent_tools/review_forecast.py; then exit 1; fi
git diff --quiet 3be26be2878da02e4aa9417719f3388f08f0298c -- python/agent_tools/review_budget.py python/agent_tools/review_feasibility.py
```

Expected: no output, exit 0: the old refusal of `rename` is gone, and the two modules #559 edits are untouched (D10).

- [ ] **Step 5: Commit**

Stage exactly the Files above, then `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(review): forecast moves as rename records" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"fe9fa1a3470f4422902c6d8d6eec40793d9b3f22","head":"dc854e69206e7590571c0915bebc0fa9b2ed9c03"}],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":28,"boundary":"all","deleted_lines":14,"record_bytes":13312,"support":{"covers":["r1b","r2b","r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/review_forecast.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":14,"record_bytes":14336,"support":{"covers":["r1c","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"python/agent_tools/review_projection.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":3,"record_bytes":32768,"support":{"covers":["r1i","r2c","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":3,"owner":3,"path":"python/README.md"},{"bounds":[{"added_lines":82,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["r1j","r2f","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":3,"owner":3,"path":"tests/test_review_feasibility.py"},{"bounds":[{"added_lines":95,"boundary":"all","deleted_lines":0,"record_bytes":11264,"support":{"covers":["r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":3,"owner":3,"path":"tests/test_review_projection_cases.py"}]}}
```
