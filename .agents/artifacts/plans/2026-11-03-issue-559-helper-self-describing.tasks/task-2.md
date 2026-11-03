# Task 2: `review-feasibility forecast` writes the forecast blocks

**Files:**
- Create: `python/agent_tools/review_forecast_writer.py`
- Modify: `python/agent_tools/review_feasibility.py` (`main`; new `_read_input`)
- Modify: `python/README.md` (§ Review packaging and feasibility: a new paragraph after the one that starts "**Review feasibility forecast.**")
- Test: `tests/test_review_feasibility.py` (new class `ForecastGeneratorTest`, appended at the end of the file)

**Interfaces:**
- Consumes: Task 1's `BudgetAuthority.check(kind, root) -> BudgetCheck`, which raises `BudgetError("budget check failed: <checker line>")` on a refusal. From `agent_tools.review_forecast`: `ForecastError`, `canonical_bytes(value) -> bytes` (sorted, compact, ASCII JSON plus `\n`), `strict_json(raw) -> object` (raises `ForecastError("invalid JSON")`), `read_regular(repo, relative, limit=None) -> bytes` (no symlink followed), `tree_entry(repo, tree, path) -> dict | None` (`{mode, kind, oid}`), `full_commit(repo, value) -> str`, `history_commit(repo, value)` (has `.tree`), `path_name(value) -> str` (raises `invalid path` or `unsafe path`), `validate_boundaries(boundaries, task_count, proposed)`, `_records(delivery, tasks, boundaries)` and `_block(raw, heading) -> dict`. From `agent_tools.review_record`: `DELIVERY_HEADING` and `TASK_HEADING`. From `agent_tools.review_actual`: `_run_git(repo, *args, binary=False)`.
- Produces:
  - `agent_tools.review_forecast_writer.write_forecast(repo: Path, plan: Path, base: str, spec: Path, raw: bytes, authority: BudgetAuthority) -> list[str]`. It returns the repository-relative POSIX paths whose bytes it changed, the root first and then the members in task order, and raises `ForecastError` or `BudgetError` (or `OSError` from a read or write) on a refusal.
  - `agent_tools.review_forecast_writer.HELP: str`, the `forecast --help` description, built from the module's constants: `RECORD_BASE_BYTES = 2560`, `LINE_BYTES = 128`, `REVISION_BYTES = 4096`, `RECORDING_BYTES_PER_TASK = 256`, `ALLOWANCE_LINE_BYTES = 64`, `SUBJECT_BYTES = 64`, `TASK_SUBJECTS = 3`, `PROCESS_SUBJECTS_BEYOND_TASKS = 4`, `BOUNDARY = "all"` and `ACCEPTANCE = "Every task of the plan is complete and the declared verification passes"` (D2, D3).
  - `review-feasibility forecast --plan P --base B --spec S --input FILE|-`: exit 0 prints `canonical_bytes({"written": [...]})`. Every refusal exits 2 with empty stdout and one stderr line `review-feasibility: <reason>`.

**Invariants:**
- Every value is a function of the plan bytes, B, S and the estimate. All values are computed and checked before the first write, so a validation refusal changes no file (D5). Writes are per file: an `OSError` in step 9 can leave earlier files replaced, each atomically, and a rerun with the same inputs converges.
- A rerun with the same inputs prints `{"written":[]}` and leaves every byte unchanged.
- The generated blocks pass `validate_boundaries` and `_records`; if they do not, the generator refuses and writes nothing.
- Every process record's `record_bytes` is at least `2560 + bytes + lines + 4096 + 256 × N` of the file as written, and its `added_lines` at least `lines + ceil((4096 + 256 × N) / 64)`, the root's own record included (D3).
- No reason echoes an estimate value or key; an estimate reason names the member in wire spelling (`tasks[i].files[j].<key>`, 0-based) and the rule (D5, D13).
- Nothing is committed. `project`, `validate-result`, `gate` and `confirm` behave exactly as before.

- [ ] **Step 1: Write the failing tests**

Append this class at the end of `tests/test_review_feasibility.py`:

```python
class ForecastGeneratorTest(SourceProjectionFixture, unittest.TestCase):
    """`review-feasibility forecast` from source (issue 559 AC1, D1-D5, D12, D13)."""
    ROOT, SPEC = 'gen/plan.md', 'gen/spec.md'
    MEMBERS = ('gen/plan.tasks/task-1.md', 'gen/plan.tasks/task-2.md')
    ESTIMATE = {'tasks': [
        {'files': [{'path': 'src/new.py', 'change': 'add', 'added_lines': 40},
                   {'path': 'shared.txt', 'change': 'modify', 'added_lines': 3, 'deleted_lines': 1}]},
        {'files': [{'path': 'src/new.py', 'change': 'modify', 'added_lines': 10, 'deleted_lines': 2},
                   {'path': 'delete.txt', 'change': 'delete'}]}]}

    def setUp(self):
        super().setUp()
        self.base = self.head
        self.write(self.SPEC, '# Spec\n')
        self.write(self.ROOT, '# Plan\n\n## Task index\n\n'
                   'Task 1 — Add — src/new.py — full — [task-1.md](plan.tasks/task-1.md)\n'
                   'Task 2 — Change — src/new.py — full — [task-2.md](plan.tasks/task-2.md)\n')
        for number, member in enumerate(self.MEMBERS, 1):
            self.write(member, f'# Task {number}\n\nBody.\n')
        self.commit('plan')

    def forecast(self, estimate=None):
        return self.invoke('forecast', '--plan', str(self.repo / self.ROOT), '--base', self.base,
                           '--spec', str(self.repo / self.SPEC), '--input', '-',
                           input=json.dumps(estimate or self.ESTIMATE).encode())

    def files(self):
        return {path: (self.repo / path).read_bytes() for path in (self.ROOT, *self.MEMBERS)}

    def block(self, path, heading):
        text = (self.repo / path).read_text(encoding='utf-8')
        return json.loads(text.split(heading + '\n\n```json\n', 1)[1].split('\n', 1)[0])

    def assert_refused_naming(self, result, member, before, value=None):
        self.assert_refused(result)
        self.assertTrue(result.stderr.startswith(b'review-feasibility: '), result.stderr)
        self.assertEqual(result.stderr.count(b'\n'), 1, result.stderr)
        self.assertIn(member.encode(), result.stderr)
        if value is not None:
            self.assertNotIn(value.encode(), result.stderr)
        self.assertEqual(self.files(), before)

    def test_generated_blocks_pass_the_gate_and_a_rerun_writes_nothing(self):
        first = self.forecast()
        self.assertEqual((first.returncode, first.stderr), (0, b''))
        self.assertEqual(json.loads(first.stdout), {'written': [self.ROOT, *self.MEMBERS]})
        written = self.files()
        again = self.forecast()
        self.assertEqual((again.returncode, again.stdout), (0, b'{"written":[]}\n'))
        self.assertEqual(self.files(), written)
        self.commit('forecast')
        gated = self.invoke('gate', '--plan', str(self.repo / self.ROOT), '--base', self.base,
                            '--head', self.head, '--completed-through', '0')
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertEqual(json.loads(gated.stdout)['state'], 'complete')

    def test_blocks_carry_the_estimate_rule_and_cover_each_process_file(self):
        self.assertEqual(self.forecast().returncode, 0)
        self.commit('forecast')
        bound = lambda added, deleted, size, covers: [{'boundary': 'all', 'added_lines': added,
            'deleted_lines': deleted, 'record_bytes': size,
            'support': {'kind': 'authored-cumulative/v1', 'covers': covers}}]
        self.assertEqual(self.block(self.MEMBERS[1], '## Review feasibility task')['task'], {
            'id': 2, 'commit_subject_bytes': [64, 64, 64], 'actual_ranges': [], 'records': [
                {'id': 'r2-1', 'owner': 2, 'path': 'src/new.py', 'change': 'modify', 'last_task': 2,
                 'bounds': bound(50, 2, 2560 + 128 * 52, ['r1-1', 'r2-1'])},
                {'id': 'r2-2', 'owner': 2, 'path': 'delete.txt', 'change': 'delete', 'last_task': 2,
                 'bounds': bound(0, 1, 2560 + len('gone later\n') + 1, ['r2-2'])}]})
        delivery = self.block(self.ROOT, '## Review feasibility delivery')
        self.assertEqual((delivery['delivery_base'], delivery['proposed_boundary'], delivery['derived_from']),
                         (self.base, 'all', None))
        self.assertEqual(delivery['actual_evidence'], {'kind': 'git-range-ownership/v1', 'head': self.base,
            'tree': self.git('rev-parse', self.base + '^{tree}'), 'process_ranges': []})
        boundary, = delivery['boundaries']
        self.assertEqual((boundary['tasks'], boundary['process_forecast_ids'],
                          boundary['process_commit_subject_bytes']), ([1, 2], ['s', 'p', 't1', 't2'], [64] * 6))
        self.assertEqual([r['path'] for r in delivery['process_records']], [self.SPEC, self.ROOT, *self.MEMBERS])
        for record in delivery['process_records']:
            raw = (self.repo / record['path']).read_bytes()
            diff = subprocess.run(['git', '-C', str(self.repo), 'diff', '--binary', '-U10', self.base, 'HEAD',
                                   '--', record['path']], env=self.env, check=True, capture_output=True).stdout
            size, = record['bounds']
            with self.subTest(path=record['path']):
                self.assertEqual((record['change'], record['last_task']), ('add', 2))
                self.assertGreaterEqual(size['record_bytes'], 2560 + len(raw) + raw.count(b'\n') + 4096 + 256 * 2)
                self.assertGreaterEqual(size['record_bytes'], len(diff))
                self.assertGreaterEqual(size['added_lines'], raw.count(b'\n') + (4096 + 256 * 2 + 63) // 64)

    def test_estimate_refusals_name_the_failing_member_and_change_nothing(self):
        add = lambda path, **extra: {'path': path, 'change': 'add', 'added_lines': 1, **extra}
        modify = lambda path: {'path': path, 'change': 'modify', 'added_lines': 1, 'deleted_lines': 0}
        two = lambda first, second=(): {'tasks': [{'files': list(first)}, {'files': list(second)}]}
        cases = (
            ({'tasks': [{'files': []}]}, 'tasks must be a list with one entry per task member', None),
            (two([add('shared.txt')]), 'tasks[0].files[0].change', 'shared.txt'),
            (two([], [modify('src/absent.py')]), 'tasks[1].files[0].change', 'src/absent.py'),
            (two([add('src/new.py', extra=1)]), 'tasks[0].files[0] must have exactly the keys', 'extra'),
            (two([{'path': 'a.py', 'change': 'rename'}]), 'tasks[0].files[0].change', 'rename'),
            (two([modify(self.SPEC)]), 'tasks[0].files[0].path', self.SPEC),
            (two([modify('all.tasks')]), 'tasks[0].files[0].path', 'all.tasks'),
            (two([add('a.py'), add('a.py')]), 'tasks[0].files[1].path', 'a.py'),
            (two([add('a.py', added_lines=-1)]), 'tasks[0].files[0].added_lines', None),
            (two([add('../escape.py')]), 'tasks[0].files[0].path', 'escape'),
        )
        before = self.files()
        for estimate, member, value in cases:
            with self.subTest(member=member, estimate=estimate):
                self.assert_refused_naming(self.forecast(estimate), member, before, value)

    def test_file_refusals_name_the_file_and_change_nothing(self):
        self.write(self.MEMBERS[0], '# Task 1\n\n## Review feasibility task\n\nx\n\n## Review feasibility task\n')
        before = self.files()
        self.assert_refused_naming(self.forecast(), self.MEMBERS[0], before)
        self.write(self.MEMBERS[0], '# Task 1\n\nBody.\n')
        self.assertEqual(self.forecast().returncode, 0)
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        for path, heading, mutate in (
                (self.ROOT, '## Review feasibility delivery', lambda block: block['actual_evidence'].update(
                    process_ranges=[{'base': self.base, 'head': self.head, 'boundaries': ['all']}])),
                (self.MEMBERS[1], '## Review feasibility task', lambda block: block['task'].update(
                    actual_ranges=[{'base': self.base, 'head': self.head}]))):
            with self.subTest(path=path):
                original = (self.repo / path).read_bytes()
                block = self.block(path, heading)
                old = canonical(block)
                mutate(block)
                self.write(path, original.replace(old.encode(), canonical(block).encode()))
                before = self.files()
                self.assert_refused_naming(self.forecast(), path, before)
                self.write(path, original)
        root = (self.repo / self.ROOT).read_bytes()
        self.write(self.ROOT, root.replace('Task 2 — Change'.encode(), b'Task 2 Change', 1))
        before = self.files()
        self.assert_refused_naming(self.forecast(), 'budget check failed: artifact-budget: invalid input: '
                                   'invalid task index row', before)

    def test_help_prints_the_estimate_shape_and_the_sizing_rule(self):
        shown = self.invoke('forecast', '--help')
        self.assertEqual(shown.returncode, 0, shown.stderr)
        for token in (b'"change":"modify"', b'"deleted_lines"', b'2560', b'128', b'4096', b'256', b'64'):
            with self.subTest(token=token):
                self.assertIn(token, shown.stdout)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 900 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_feasibility -k ForecastGeneratorTest 2>&1 | tail -6'`
Expected: FAIL, `Ran 5 tests` and `FAILED`. argparse refuses the unknown `forecast` choice, so each call exits 2 (`invalid choice: 'forecast'`) where the tests expect 0, and the help test finds none of its tokens.

- [ ] **Step 3: Write the minimal implementation**

**`python/agent_tools/review_feasibility.py`.**
- Extract the duplicated `--input` read from the `confirm` and `validate-result` branches into `_read_input(value: str, bound: int) -> bytes`. For `-` it returns `sys.stdin.buffer.read(bound + 1)`; otherwise it returns `read_regular(path.parent, path.name, bound)` for `path = Path(value).absolute()`. Both branches call it with `describe("review-package").report_wire_max_bytes`, and their behaviour does not change.
- Add the subparser `commands.add_parser("forecast", help="write the forecast blocks from an estimate", description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)` with `--plan` (required, `type=Path`), `--base` (required), `--spec` (required, `type=Path`) and `--input` (required).
- Add the `forecast` branch: `authority = describe("review-package")`, `raw = _read_input(args.input, authority.report_wire_max_bytes)`, `plan = args.plan.absolute()`, `repo = Path(_run_git(plan.parent, "rev-parse", "--show-toplevel").strip())`, then `written = write_forecast(repo, plan, args.base, args.spec.absolute(), raw, authority)`, write `canonical_bytes({"written": written})` to stdout and return 0. The existing `except` tuple and the 400-character stderr line already cover its refusals.
- Change the module docstring's "read-only review feasibility" to "review feasibility: projection, gate, confirmation and forecast writing".

**`python/agent_tools/review_forecast_writer.py`** (module docstring: "Write the canonical review-feasibility forecast blocks from a planner's estimate (issue 559).").

`write_forecast` runs these steps in order. Its first refusal wins, and it writes nothing before step 9.

1. **Bound.** If `len(raw) > authority.report_wire_max_bytes`, refuse `estimate exceeds the <bound>-byte report wire bound`.
2. **Paths.** `root` and `spec_path` are `Path(os.path.realpath(x)).relative_to(os.path.realpath(repo)).as_posix()` for `plan` and `spec`, each passed through `path_name`. On `ValueError` the reason is `plan is outside the repository` or `spec is outside the repository`. `full_commit(repo, base)` checks B, and `base_tree = history_commit(repo, base).tree`.
3. **Members.** `count = authority.check("implementation-plan", repo / root).metrics["file_count"] - 1`. The check's `status` is ignored and a `BudgetError` propagates. With `count < 1`, refuse `missing indexed tasks`. `members[n-1] = str(PurePosixPath(root).with_suffix(".tasks") / f"task-{n}.md")`. If `spec_path` is the root or a member, refuse `spec is the plan root or a task member`.
4. **Reads.** Read the root and each member with `read_regular(repo, path)` and decode them as UTF-8; a decode failure is `<path> is not UTF-8`. Read the spec with `read_regular` as bytes. For each of the root (with `DELIVERY_HEADING`) and every member (with `TASK_HEADING`), in that order: when the heading line occurs more than once in `text.splitlines()`, refuse `<path>: "<heading>" appears more than once`. When it occurs once and `_block(raw, heading)` parses, refuse `<path>: its forecast block carries recorded evidence, which sdd-gate record owns` if the delivery block's `actual_evidence` is a dict whose `process_ranges` is present and not `[]`, or the task block's `task` is a dict whose `actual_ranges` is present and not `[]`. A block that does not parse is simply replaced.
5. **Estimate.** Parse `raw` with `strict_json`, where `invalid JSON` becomes `estimate: invalid JSON`. Then check, in this order, with the reasons given here (`i` and `j` are 0-based):
   - the value is a dict with exactly the key `tasks`, else `estimate must be a JSON object with exactly the key tasks`;
   - `tasks` is a list of length `count`, else `tasks must be a list with one entry per task member (<count>)`;
   - each `tasks[i]` is a dict with exactly the key `files`, else `tasks[i] must be a JSON object with exactly the key files`, and `files` is a list, else `tasks[i].files must be a list`;
   - each entry `tasks[i].files[j]`, in order:
     - it is a dict, else `tasks[i].files[j] must be a JSON object`;
     - `change` is one of `add`, `modify`, `delete`, else `tasks[i].files[j].change must be add, modify or delete`;
     - its keys are exactly `path, change, added_lines` (add), `path, change, added_lines, deleted_lines` (modify) or `path, change` (delete), else `tasks[i].files[j] must have exactly the keys <that list>`;
     - `path_name(path)` passes, else `tasks[i].files[j].path: <its reason>`;
     - the path is not the spec, the root or a member, else `tasks[i].files[j].path names the spec, the plan root or a task member`;
     - the path is not already in `tasks[i]`, else `tasks[i].files[j].path repeats a path of tasks[i]`;
     - each line count is an `int` (not `bool`) ≥ 0, else `tasks[i].files[j].<key> must be an integer >= 0`;
     - `tree_entry(repo, base, path)` is `None` or a `blob`, else `tasks[i].files[j].path is not a blob at the base`;
     - the path state fits. The state starts present iff the base entry exists, and is updated after each entry. An `add` on a present path is `tasks[i].files[j].change add needs an absent path, but the path exists after the base and earlier tasks`. A `modify` or `delete` on an absent path is `tasks[i].files[j].change <change> needs a present path, but the path is absent after the base and earlier tasks`. An add makes the path present, and a delete makes it absent.
6. **Task records** (D2). Walk the tasks and entries in order, keeping per path the cumulative `added`, `deleted` and `charge` and the list of ids. Entry `k` (1-based) of task `n` gets the id `r<n>-<k>`. An `add` or `modify` adds its line counts (a missing `deleted_lines` counts 0) and `128 × (added_lines + deleted_lines)` to the charge. A `delete` of a path present at the base and not deleted earlier adds the blob's byte length plus its line count to the charge and its line count to `deleted`; any other delete adds 0. The blob is read with `_run_git(repo, "cat-file", "blob", oid, binary=True)`. A line count is `raw.count(b"\n")`, plus 1 when `raw` is non-empty and does not end in `\n`. The record is `{id, owner: n, path, change, last_task: <the last task whose estimate names path>, bounds: [{boundary: "all", added_lines: added, deleted_lines: deleted, record_bytes: 2560 + charge, support: {kind: "authored-cumulative/v1", covers: <the path's ids so far>}}]}`. Task `n`'s block is `{schema_version: 3, kind: "review-feasibility-task", task: {id: n, commit_subject_bytes: [64, 64, 64], actual_ranges: [], records}}`.
7. **Sections.** The section text is `f"{heading}\n\n```json\n{canonical_bytes(block).decode('ascii')}```\n"`. Split the text into `lines = text.splitlines(keepends=True)` and `bare = text.splitlines()`; both have the same length. When the heading occurs once at `start`, `end` is the next index whose `bare` line starts with `## `, or `len(lines)`. The new text is `"".join(lines[:start]) + section + ("\n" if end < len(lines) else "") + "".join(lines[end:])`. When the heading is absent, the new text is `section` for an empty text, otherwise `text + ("" if text.endswith("\n") else "\n") + "\n" + section`. Render every member's new text this way.
8. **Process records** (D3). `A = 4096 + 256 × count`. Record `s` is the spec, `p` the root and `t<n>` member `n`, in that order. Each has `owner: 0`, `last_task: count` and change `add` when `tree_entry(repo, base, path)` is `None`, else `modify`; a non-blob base entry is refused `<path> is not a blob at the base`. Its one `all` bound has `added_lines = lines + ceil(A / 64)`, `deleted_lines: 0`, `record_bytes = 2560 + len(bytes) + lines + A` and `covers: [id]`. The spec is measured on its read bytes and each member on its new text. The root is measured on its new text, and that text contains `p` itself, so start `p` at `record_bytes = 0, added_lines = 0`, render the root, recompute both, and raise each value to the larger of the two until a render no longer raises either. After 8 renders, refuse `the root's process record did not settle`. The delivery block is `{schema_version: 3, kind: "review-feasibility-delivery", delivery_base: B, proposed_boundary: "all", boundaries: [{id: "all", parent: null, tasks: [1..count], acceptance: ACCEPTANCE, depends_on: [], prerequisite: {kind: "delivery-base"}, process_package: {spec, plan: root, tasks: members}, process_forecast_ids: ["s", "p", "t1".."t<count>"], process_commit_subject_bytes: [64] × (count + 4)}], process_records: [s, p, t1..], actual_evidence: {kind: "git-range-ownership/v1", head: B, tree: base_tree, process_ranges: []}, derived_from: null}`.
9. **Check, then write.** Run `boundaries = validate_boundaries(delivery["boundaries"], count, "all")` and then `_records(delivery, tuple(block["task"] for block in task_blocks), boundaries)`; a `ForecastError` there is `forecast self-check failed: <its reason>`. Then, for the root and each member in order whose new bytes differ from its current bytes, write the new bytes to a `tempfile.mkstemp` file beside the target, `chmod` it to the target's current permission bits, and `os.replace` it over the target. On `OSError`, unlink the temporary file and re-raise. Return the changed paths in that order.

`HELP` is this text. It is an f-string whose sizing numbers (2560, 128, 4096, 256, 64, 3 and 4) come from the constants, while the example's line counts are literal; the example stays one line:

```text
Write the root's "## Review feasibility delivery" block and each task member's
"## Review feasibility task" block from an estimate, then print {"written":[...]}:
the repository-relative paths whose bytes changed, the root first. Nothing is
committed. Rerun it after any edit that changes a task's files.

The estimate (--input FILE, or - for stdin) is one JSON object with one tasks
entry per task member, in task order:

  {"tasks":[{"files":[{"path":"src/a.py","change":"add","added_lines":120},{"path":"src/b.py","change":"modify","added_lines":30,"deleted_lines":10},{"path":"old.py","change":"delete"}]}]}

An add has path, change and added_lines, a modify adds deleted_lines, and a
delete has path and change only. Line counts are integers >= 0. A path appears
once per task, is never the spec, the root or a member, and its change must fit
the path's state walked task by task from the base tree.

Sizing: a task record's record_bytes is 2560 plus 128 per added or deleted
line, cumulative per path, and a delete of a base file is charged that file's
bytes and lines once. A process record (the spec, the root, each member) is
2560 + its bytes + its lines + 4096 + 256 per task, and its added_lines add
(4096 + 256 per task) / 64, rounded up. Each task is budgeted 3 commit subjects
of 64 bytes, and the process the task count + 4.
```

**`python/README.md`.** Add this paragraph, as one line, directly after the paragraph that starts "**Review feasibility forecast.**":

> `review-feasibility forecast --plan P --base B --spec S --input FILE|-` (issue 559) writes those blocks from the plan bytes, B, S and a planner's estimate, so no planner composes them by hand. Its members are the ones `artifact-budget check --kind implementation-plan` discovers, and a refusal there relays the checker's line. B must be a full commit id, and S, recorded repository-relative as the root boundary's `process_package.spec`, must be neither the root nor a member. The estimate is read like `confirm`'s input (a file read without following a symlink, or stdin, at most the report wire bound) and loaded strictly: `{"tasks":[{"files":[...]}]}` with one entry per member in task order. Each `files` entry is `{path, change: "add", added_lines}`, `{path, change: "modify", added_lines, deleted_lines}` or `{path, change: "delete"}`, its line counts are integers ≥ 0, and its path appears at most once per task, is never S, the root or a member, and fits the path state walked task by task from B's tree: an `add` needs the path absent there or deleted earlier, a `modify` or `delete` needs it present and not deleted since, and a base entry must be a blob. The output is one boundary `all` (`parent` null, every task, a fixed `acceptance`, the `delivery-base` prerequisite, `process_package` {S, P, the members}, `process_forecast_ids` `s`, `p`, `t1`..`tN` and N + 4 process subjects of 64 bytes), `actual_evidence` `{kind: git-range-ownership/v1, head: B, tree: B's tree, process_ranges: []}` and `derived_from` null. Each task gets `commit_subject_bytes` `[64,64,64]`, empty `actual_ranges` and one record `r<N>-<k>` per estimate entry, in input order, whose `last_task` is the last task naming its path and whose one `all` bound covers that path's record ids so far. A task record's `record_bytes` is 2560 plus, cumulatively per path, 128 per added or deleted line; a delete of a path present in B's tree and not yet deleted is charged that blob's bytes plus its line count, and the line count joins `deleted_lines`. A process record is `add` when its path is absent from B's tree and `modify` otherwise. Its `record_bytes` is 2560 + the file's bytes + its line count + 4096 + 256 × N, and its `added_lines` is the line count plus (4096 + 256 × N) / 64 rounded up, both measured on the bytes as written, so the root's own record is re-rendered until it covers the rendered root. Everything is computed, and checked with the loader's `validate_boundaries` and `_records`, before any write. A heading present once is replaced over the parser's extent (to the next line starting `## `), and an absent one is appended after a blank line. A repeated heading is refused, and so is a parsed block holding a non-empty `actual_ranges` or `process_ranges`, because `sdd-gate record` owns the blocks from the first recording. Each changed file is replaced atomically with its permission bits kept, an unchanged file is left alone, and nothing is committed; a write failure can leave earlier files replaced, and a rerun converges. Exit 0 prints `{"written":[...]}`, the repository-relative paths whose bytes changed, the root first. Every refusal exits 2 with empty stdout and one stderr line `review-feasibility: <reason>`; an estimate reason names the failing member in wire spelling (`tasks[1].files[0].change`) and its rule, never an input value or key. The constants live in `agent_tools.review_forecast_writer`, and `review-feasibility forecast --help` prints the estimate shape and the rule.

- [ ] **Step 4: Verify**

1. Focused tests, green (timeout 900 s): the Step 2 command.
   Expected: `Ran 5 tests` and `OK`.
2. Regression over the shared input reader and the gate (timeout 2400 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_feasibility tests.test_review_gate 2>&1 | tail -4'`
   Expected: `OK`. A failure in `ConfirmTest` or `test_validate_result_refuses_fifo_input_without_blocking` means `_read_input` changed `confirm` or `validate-result`.
3. Static scope (instant): `test "$(grep -c 'sys.stdin.buffer.read' python/agent_tools/review_feasibility.py)" = 1 && grep -q 'formatter_class=argparse.RawDescriptionHelpFormatter' python/agent_tools/review_feasibility.py`
   Expected: exit 0. Exit 1 means the input read is still duplicated or the help is reflowed.
4. Build (timeout 3600 s). The build imports every `agent_tools` module and sees only tracked content, so stage first: `git add python/agent_tools/review_forecast_writer.py python/agent_tools/review_feasibility.py python/README.md tests/test_review_feasibility.py`, then `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; just build 2>&1 | tail -3'`
   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_forecast_writer.py python/agent_tools/review_feasibility.py python/README.md tests/test_review_feasibility.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-559): add review-feasibility forecast" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | sort | tr '\n' ' ')" = "python/README.md python/agent_tools/review_feasibility.py python/agent_tools/review_forecast_writer.py tests/test_review_feasibility.py "`
Expected: exit 0. A non-zero exit means the commit touched another file or missed one.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":400,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["r2-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_forecast_writer.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":12,"record_bytes":8192,"support":{"covers":["r2-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2-2","last_task":2,"owner":2,"path":"python/agent_tools/review_feasibility.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":20480,"support":{"covers":["r1-2","r2-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2-3","last_task":2,"owner":2,"path":"python/README.md"},{"bounds":[{"added_lines":212,"boundary":"all","deleted_lines":0,"record_bytes":32768,"support":{"covers":["r1-3","r2-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2-4","last_task":2,"owner":2,"path":"tests/test_review_feasibility.py"}]}}
```
