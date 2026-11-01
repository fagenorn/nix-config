# Task 1: Summary, capture, `review-feasibility gate` and `confirm`

**Files:**
- Create: `python/agent_tools/review_gate.py`
- Modify: `python/agent_tools/review_feasibility.py`
- Create: `tests/test_review_gate.py`
- Modify: `tests/test_agent_tools_launchers.py`
- Modify: `python/README.md`
- Modify: `justfile`

**Interfaces:**
- Consumes (unchanged, accepted in issue 226): `agent_tools.review_projection.validate_result(raw, producer_exit, authority) -> bytes`; `agent_tools.review_budget.describe("review-package") -> BudgetAuthority` (`.report_wire_max_bytes` is 8192); `agent_tools.review_forecast.{ForecastError, canonical_bytes, strict_json, read_regular}`; `agent_tools.siblings.sibling_argv(module) -> list[str]`; the test fixture `tests.test_review_feasibility.SourceProjectionFixture` (plan `all.md`, boundary `all`, `record()`, `emit()`, `commit()`, `checkpoint()`, `invoke()`, `project()`).
- Produces, in `agent_tools.review_gate` (Tasks 2, 3 and 5 import these names):
  - `SUMMARY_KEYS: tuple[str, ...]` = `("artifact_policy_sha256", "base", "completed_through", "forecast_sha256", "head", "kind", "metrics", "packing_policy_sha256", "plan", "plan_package_sha256", "recommended_boundary", "schema_version", "state", "violations")`; `RECOMMENDATION_KEYS = ("id", "metrics", "prerequisite_commit", "tasks")`.
  - `class GateError(ForecastError)`: one-line reason, no prefix.
  - `@dataclass(frozen=True) class Capture: exit: int; raw: bytes; result: dict` (exit is 0 or 3; raw passed `validate_result`).
  - `project_argv(plan: Path, base: str, head: str, completed_through: int) -> list[str]` = `[*sibling_argv("review_feasibility"), "project", "--plan", str(plan), "--base", base, "--head", head, "--completed-through", str(completed_through)]`.
  - `capture(argv: Sequence[str], *, cwd: Path, authority: BudgetAuthority) -> Capture`.
  - `summarize(capture: Capture, plan: str) -> dict` (`plan` repository-relative POSIX).
  - `plan_relative(plan: Path) -> str`: the plan's path relative to `git rev-parse --show-toplevel` run in the plan's directory, as POSIX.
  - `gate(plan: Path, base: str, head: str, completed_through: int, *, argv: Sequence[str] | None = None) -> tuple[int, bytes]`: `(0 | 3, canonical summary bytes)`.
  - `confirm(plan: Path, base: str, raw: bytes, *, argv: Callable[[str, str, int], Sequence[str]] | None = None) -> tuple[int, bytes]`.
  - CLI: `review-feasibility gate --plan P --base B --head H --completed-through N` and `review-feasibility confirm --plan P --base B --input FILE|-`.

**Invariants:**
- A summary is derived only from bytes that passed `validate_result` with their producer's exit; exit 2 yields no summary (D3).
- Summary bytes are `canonical_bytes(summary)`: sorted keys, compact, ASCII-escaped, LF-terminated.
- `state == "complete"` iff exit 0 iff `violations == []` iff `recommended_boundary is None`.
- Every refusal of `gate` or `confirm` exits 2 with empty stdout and exactly one stderr line `review-feasibility: <reason>`.
- `capture` reads at most `report_wire_max_bytes + 1` stdout bytes; more is a refusal. Stderr is drained by a thread into a tail of at most 4096 bytes, so a chatty child never blocks.
- `confirm` never trusts the input: it recomputes through `capture` and requires byte equality of `canonical_bytes(parsed input)` with the recomputed summary (D4).
- The command table, `project` and `validate-result` are unchanged.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_gate.py`

```python
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

    def gate(self, completed=0):
        return self.invoke('gate', '--plan', self.plan_path(), '--base', self.base, '--head', self.head,
                           '--completed-through', str(completed))

    def confirm(self, raw, base=None, plan=None):
        return self.invoke('confirm', '--plan', plan or self.plan_path(), '--base', base or self.base,
                           '--input', '-', input=raw)

    def oversize(self):
        """RecommendationTest's shape: the root overflows root_bytes, the leaf `end` fits."""
        root = self.delivery['boundaries'][0]
        leaf = source_cases.BoundaryTreeTest().row('end', 'all', [1, 2])
        leaf['process_commit_subject_bytes'] = [1]
        self.delivery['boundaries'] = [root, leaf]
        root['process_commit_subject_bytes'] = [120] * 30
        paths = [leaf['process_package']['spec'], leaf['process_package']['plan'], *leaf['process_package']['tasks']]
        for index, path in enumerate(paths):
            record = self.record(leaf['process_forecast_ids'][index], 0, path)
            record['bounds'][0]['boundary'] = 'end'
            self.delivery['process_records'].append(record)
        self.emit(); self.commit('boundaries')

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
        gated = self.gate(0)
        self.assertEqual((result.returncode, gated.returncode), (3, 3), gated.stderr)
        full = json.loads(result.stdout)['recommended_boundary']
        self.assertEqual(json.loads(gated.stdout)['recommended_boundary'],
                         {key: full[key] for key in ('id', 'tasks', 'prerequisite_commit', 'metrics')})

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
        for build in (lambda: None, self.oversize):
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
                 ('completed_through', lambda v: v.update(completed_through=1)),
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
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_gate.py 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_tools.review_gate'`.

- [ ] **Step 3: Implement `agent_tools/review_gate.py`**

```python
def capture(argv, *, cwd, authority):
    """Contract: bounded stdout, drained stderr, exit in {0, 2, 3}, validate_result with that exit."""
```

- Start the child with `subprocess.Popen(argv, cwd=cwd, stdout=PIPE, stderr=PIPE)`; an `OSError` is `GateError("cannot run review-feasibility project")`. A daemon thread reads stderr in 4096-byte chunks, keeping the last 4096 bytes. The main thread reads `stdout.read(bound + 1)`; at `bound + 1` bytes it kills the child, waits, and raises `GateError("projection result exceeds report wire bound")`.
- Exit 2: the reason is the last non-empty stderr line, decoded with `replace`, minus a leading `review-feasibility: `, whitespace-collapsed and cut to 300 characters (`"projection failed"` when empty). Any exit outside {0, 2, 3}: `GateError(f"projection exit {code} is not 0, 2 or 3")`.
- Exit 0 or 3: `validate_result(raw, exit, authority)`; its `ForecastError` becomes `GateError(f"invalid projection result: {reason}")`. Return `Capture(exit, raw, strict_json(raw))`.
- `summarize` copies `state, base, head, completed_through, metrics, violations` and the four digests, sets `schema_version: 1`, `kind: "review-feasibility-summary"`, `plan`, and `recommended_boundary` to null or the four `RECOMMENDATION_KEYS` of the result's recommendation. It asserts the invariant chain above and raises `GateError("summary state disagrees with its exit")` otherwise.
- `gate` runs `capture(argv or project_argv(...), cwd=plan.parent, authority=describe("review-package"))` and returns `(capture.exit, canonical_bytes(summarize(capture, plan_relative(plan))))`.
- `confirm`, in order: refuse `len(raw) > bound` (`"summary exceeds report wire bound"`); `strict_json` (its error is `GateError("invalid summary JSON")`); require a dict with exactly `SUMMARY_KEYS`, `type(completed_through) is int` and `>= 0`, `head` a full lowercase SHA, `state` in the two states (else `"confirm: <key> disagrees"`, naming the first offending key in sorted order); require `plan == plan_relative(plan)` and `base == base`, else `"confirm: plan disagrees"` / `"confirm: base disagrees"`; run `gate(plan, base, value["head"], value["completed_through"], argv=...)`; compare `canonical_bytes(value)` with the recomputed bytes and, on difference, name the first sorted top-level key whose values differ; require the recomputed exit to be `0` for `complete` and `3` otherwise. Return the recomputed `(exit, bytes)`.
- `review_feasibility.main` gains the two subparsers. `gate` writes the summary and returns its exit. `confirm --input -` reads `sys.stdin.buffer.read(bound + 1)`; a file is read with `read_regular(path.parent, path.name, bound)` (no symlink following). The existing exception handler, `GateError` included, keeps the one-line refusal.
- `python/README.md` § Review packaging and feasibility: one paragraph documenting `gate`, `confirm`, the summary fields and exits (the Invariants above), and one paragraph **Review feasibility forecast** carrying the v3 block field semantics that writing-plans' compact skeleton cites (D14): every field `load_plan` and `_records` check, with the conservative-bound rule (whole-record bytes at 10 lines of context, cumulative per path, a 64-byte subject per future commit).
- `justfile`: add `tests/test_review_gate.py` to `agent-workflow-tests` beside `tests/test_review_feasibility.py`.
- `tests/test_agent_tools_launchers.py::test_review_source_and_built_canonical_actual_parity`: after the `project` assertions in each label, run `gate` with the same plan, base, head and `--completed-through 1`, and `confirm` over its stdout; assert exit 0 in both labels, `confirm` stdout equal to `gate` stdout, and the source and built `gate` bytes equal.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_gate.py tests/test_review_feasibility.py 2>&1 | tail -3` — Expected: `OK`.
Run: `timeout 3600 just agent-installed-skill-tests 2>&1 | tail -3` — Expected: `OK` (built parity, D10).
Run: `timeout 3600 just build 2>&1 | tail -2` — Expected: success; a new unstaged module fails evaluation, so stage first.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_gate.py python/agent_tools/review_feasibility.py tests/test_review_gate.py tests/test_agent_tools_launchers.py python/README.md justfile
git commit -m "feat(review): add review-feasibility gate and confirm"
```

Decisions: D3, D4, D10, D14.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":1,"records":[{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}},{"added_lines":320,"boundary":"c1","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/review_gate.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":10,"record_bytes":6144,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}},{"added_lines":60,"boundary":"c1","deleted_lines":10,"record_bytes":6144,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"python/agent_tools/review_feasibility.py"},{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}},{"added_lines":260,"boundary":"c1","deleted_lines":0,"record_bytes":14336,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1c","last_task":1,"owner":1,"path":"tests/test_review_gate.py"},{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":5,"record_bytes":6144,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}},{"added_lines":40,"boundary":"c1","deleted_lines":5,"record_bytes":6144,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":1,"owner":1,"path":"tests/test_agent_tools_launchers.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":2,"record_bytes":12288,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}},{"added_lines":6,"boundary":"c1","deleted_lines":2,"record_bytes":12288,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":1,"owner":1,"path":"python/README.md"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r1f"],"kind":"authored-cumulative/v1"}},{"added_lines":1,"boundary":"c1","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r1f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1f","last_task":1,"owner":1,"path":"justfile"}]}}
```
