# Task 1: Inherited SOURCE corrections

Three corrections to published SOURCE modules, made before any new module builds on them (RP1; spec § *Inherited SOURCE corrections*). Every other inherited finding is declined there; change nothing else in these files.

**Files:**
- Modify: `python/agent_tools/review_task7.py` (`_numstat`)
- Modify: `python/agent_tools/review_issue100.py` (`_checked`)
- Modify: `python/agent_tools/review_issue121.py` (`_assigned`)
- Modify: `tests/test_review_task7.py`, `tests/test_review_issue100.py`, `tests/test_review_issue121.py`

**Interfaces:**
- Consumes: the published signatures, unchanged: `compose(repo, table, pins, *, base_tree, final_tree, limits)`, `verify_archive(archive_dir, issue_repo, pins)`, `validate_100(payload, pins)`, `classify(repo, pins)`, `validate_121(payload, pins, table)`. Test helpers already in the suites: `tree_with`, `limits` and `Task7ModelTest` (`tests/test_review_task7.py`), `Issue100Test`, and `AncestryTest` with `self.repo/pins/task7_pins/table/authority` (`tests/test_review_issue121.py`).
- Produces: no new name. Three behaviours later tasks rely on:
  - `_numstat` accepts a path that holds a tab.
  - `_checked` refuses a `producer_sha256` or `manifest_sha256` that is not a `str` of 64 lowercase hex, with `Issue100Error("invalid_pins")`, before any archive read.
  - `_assigned` refuses pins whose assignment list is empty or whose last row's commit is not `pins.head`, with `ContributionError("assignment_mismatch")`, after its existing row checks. Every public entry point that calls `_assigned` inherits it, the Git-free `validate_121` included.

**Invariants:**
- `_numstat` splits each row into the two counts and the remainder only (`row.split(b"\t", 2)`); the rename branch and every refusal stay as they are.
- The digest check uses the module's own `_hex(value, 64)`; `_read`'s `...` sentinel and its `archive_digest_mismatch` refusal are unchanged.
- The existing `test_none_digest_pin_never_switches_the_digest_check_off` asserts `archive_digest_mismatch` for a `None` pin. A `None` pin is now `invalid_pins`, so that test is replaced by the two tests below (RP15). No other existing test changes; all of them stay green (measured at planning: 62 tests, only that one fails after the three edits).
- Docstrings touched by an edit describe the new behaviour: `_assigned` names the head rule, `_checked` the digest rule.

- [ ] **Step 1: Write the failing tests.**

In `Task7ModelTest`:

```python
    def test_compose_measures_a_path_holding_a_tab(self):
        table = derive_task7(self.repo, self.pins)
        base = self.pins.prerequisite_tree
        final = tree_with(self.repo, base, b"src/tab\there.txt", b"one\ntwo\n")
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=base, final_tree=final,
                                              limits=limits())}
        row = rows["src/tab\there.txt"]
        self.assertEqual((row["added_lines"], row["deleted_lines"]), (2, 0))
```

In `Issue100Test`, replacing `test_none_digest_pin_never_switches_the_digest_check_off`:

```python
    def malformed_digest_pin(self, field):
        good = getattr(self.pins, field)
        before = self.archive_bytes()
        for value in (None, good[:-1], good.upper(), "sha256:" + good, good.encode()):
            for call in (lambda p: verify_archive(self.archive, self.repo, p), lambda p: validate_100({}, p)):
                with self.subTest(value=value), self.assertRaises(Issue100Error) as caught:
                    call(replace(self.pins, **{field: value}))
                self.assertEqual(caught.exception.code, "invalid_pins")
        self.assertEqual(self.archive_bytes(), before)

    def test_malformed_producer_digest_pin_is_invalid_pins(self):
        self.malformed_digest_pin("producer_sha256")

    def test_malformed_manifest_digest_pin_is_invalid_pins(self):
        self.malformed_digest_pin("manifest_sha256")
```

In `AncestryTest`:

```python
    def test_last_assignment_must_be_the_pinned_head(self):
        payload = derive_121(self.repo, self.pins, self.task7_pins, self.authority)
        cases = {"short": replace(self.pins, assignments=self.pins.assignments[:-1]),
                 "foreign_head": replace(self.pins, head="f" * 40),
                 "empty": replace(self.pins, assignments=())}
        for name, pins in cases.items():
            with self.subTest(case=name), self.assertRaises(ContributionError) as caught:
                validate_121(payload, pins, self.table)
            self.assertEqual(caught.exception.code, "assignment_mismatch")
```

- [ ] **Step 2: Run them and watch them fail.**

```bash
PYTHONPATH=python python3 -m unittest \
  tests.test_review_task7.Task7ModelTest.test_compose_measures_a_path_holding_a_tab \
  tests.test_review_issue100.Issue100Test.test_malformed_producer_digest_pin_is_invalid_pins \
  tests.test_review_issue100.Issue100Test.test_malformed_manifest_digest_pin_is_invalid_pins \
  tests.test_review_issue121.AncestryTest.test_last_assignment_must_be_the_pinned_head 2>&1 | tail -4
```

Expected at the starting commit (measured at planning): the tab case errors with `EstimateError: unsupported_composition`; the digest cases fail with `'archive_digest_mismatch' != 'invalid_pins'`; the head case fails with `'invalid_payload' != 'assignment_mismatch'`.

- [ ] **Step 3: Make the three edits.**
  1. `review_task7._numstat`: `parts = row.split(b"\t", 2)`.
  2. `review_issue100._checked`: add `all(_hex(v, 64) for v in (p.producer_sha256, p.manifest_sha256))` to the first `_require(..., bad)` conjunction.
  3. `review_issue121._assigned`: after the row loop, `if not rows or rows[-1]["commit"] != pins.head: raise ContributionError("assignment_mismatch")`.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_task7 tests.test_review_issue121 tests.test_review_issue100 2>&1 | tail -3
if grep -q 'test_none_digest_pin_never_switches' tests/test_review_issue100.py; then exit 1; fi
git diff --stat 218f5bc0bf3556fa05959e6ba24175685b58e2a9 -- python/agent_tools | tail -1
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  The three suites end `OK` (they take about four minutes). The `--stat` line names exactly three files with at most 10 insertions and 5 deletions in total; a larger diff means a declined finding was touched.

- [ ] **Step 5: Commit.** Stage only the six Files. Check `printf %s "$subject" | wc -c` is at most 64, then commit `fix(review): tighten inherited retained source checks (#249)`. A review-fix commit uses `fix(review): address Task-1 review findings (#249)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 1` (RP14).

## Forecast basis

Modify records are the U10 diff of each path against `DELIVERY_BASE` (parent D15): each small hunk carries twenty context lines of up to 120 bytes, plus 512 header bytes.
- `review_task7.py`: +1/−1 → 3,072 B / +4 / −4.
- `review_issue100.py`: +1 inside a long conjunction, plus a docstring line → 4,096 B / +4 / −2.
- `review_issue121.py`: +2, plus a docstring line → 4,096 B / +5 / −2.
- `tests/test_review_task7.py`: +9 → 4,096 B / +14 / −0.
- `tests/test_review_issue100.py`: one test replaced by three definitions → 6,144 B / +24 / −18.
- `tests/test_review_issue121.py`: +10 → 4,096 B / +14 / −0.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"5d5a5d70a25bdbf15c234a60e10f891f7727d5d1","head":"d5232acfe2494ef5ed415f75c72906807dc3f91f"}],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":4,"boundary":"replay","deleted_lines":4,"record_bytes":3072,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_task7.py"},{"bounds":[{"added_lines":4,"boundary":"replay","deleted_lines":2,"record_bytes":4096,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-2","last_task":1,"owner":1,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":5,"boundary":"replay","deleted_lines":2,"record_bytes":4096,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-3","last_task":1,"owner":1,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":14,"boundary":"replay","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-4","last_task":1,"owner":1,"path":"tests/test_review_task7.py"},{"bounds":[{"added_lines":24,"boundary":"replay","deleted_lines":18,"record_bytes":6144,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-5","last_task":1,"owner":1,"path":"tests/test_review_issue100.py"},{"bounds":[{"added_lines":14,"boundary":"replay","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t1-6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-6","last_task":1,"owner":1,"path":"tests/test_review_issue121.py"}]}}
```
