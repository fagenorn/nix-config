# Task 6: Portable replay and the replay command

**Files:**
- Create: `python/agent_tools/review_replay.py`
- Create: `python/agent_tools/replay_retained.py`
- Create: `tests/test_review_replay.py`
- Modify: `justfile` (append `tests/test_review_replay.py` to `agent-workflow-tests`)

**Interfaces:**
- Consumes:
  - From Task 4: `authenticate`, `validate_witness`, `PAYLOAD_NAMES`, `WitnessError`.
  - Validators: `validate_task7` (Task 1), `validate_121`/`unavailable_ids` (Task 2), `validate_100` (Task 3).
  - The real pins from Tasks 1–3.
  - From Task 5: `derive_bundle` and `DeriveInputs`.
  - From the support module: `derivation_fixture`.
  - From CORE: `canonical_bytes`, `strict_json`, `telemetry_digest`.
- Produces:
  - `class ReplayInvalid(Exception)` with `code: str`, and `class ReplayUnavailable(Exception)` with `ids: tuple[str, ...]`.
  - `validate_bundle(anchor: dict, raw: Mapping[str, bytes], *, task7_pins, issue121_pins, issue100_pins) -> dict`. This is replay step 3, the full semantic validation. It returns the decoded payloads. Tests call it directly as the test-only trust injection that the spec names.
  - `replay(bundle_dir: Path, expected_anchor_sha256: str, *, task7_pins, issue121_pins, issue100_pins) -> dict`. It runs steps 1–4 and returns the v3 `review-feasibility-retained-result`, which holds `schema_version`, `kind`, `anchor_sha256`, `issue_121{aggregate, boundaries, operational_effects}` and `issue_100{history_edge_count, disposition_counts, pending_overlap_count, fixture_sha256}`.
  - Command `replay_retained.main(argv=None) -> int`, with parser `prog="replay-retained"`. It requires `--fixtures-dir DIR` and `--expected-anchor-sha256 sha256:HEX`, and has no `--anchor` option (D6). Exits follow D7:
    - Every outcome measured (including over budget): exit 0 with `canonical_bytes(result)`.
    - Any unavailable outcome: exit 2, empty stdout, and one stderr line, `replay-retained: projection_unavailable: <ids joined by ",">`.
    - Invalid input: exit 2, empty stdout, and `replay-retained: invalid: <code>`.

**Invariants:**
- Replay never runs Git and never reads outside `bundle_dir`. It still works when the source repositories are unreachable.
- Step 3 validates everything before step 4 classifies anything:
  - closed shapes and component equality;
  - table references and raw parent ordinals;
  - the issue-121 chain, which must be exactly 30 linear ordinal-1 edges from the pinned base to the pinned head;
  - closure of every issue-100 edge over the pinned range;
  - ordered edge and contribution coverage, unique final records and domain policies;
  - every issue-100 fact and criterion;
  - the Task-7 counts, bounds and identities;
  - every outcome row's references.
- A malformed issue-100 payload or Task-7 table beside a valid issue-121 `projection_unavailable` is `invalid`, never `unavailable`. No mixed success object is ever emitted.
- The `unavailable` stderr line is written only after complete validation. Ids keep payload order (`aggregate.actual`, `aggregate.projected`, `tasks-1-3`, `tasks-4-6`, `tasks-7-8`, filtered).

- [ ] **Step 1: Write the failing tests.** These go in `tests/test_review_replay.py`. `setUp` derives one portable bundle with `derivation_fixture` and `derive_bundle`.

```python
class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.bundle, self.expected, self.pins = derived_bundle(self.tmp)   # derive_bundle over derivation_fixture

    def kwargs(self):
        return dict(task7_pins=self.pins[0], issue121_pins=self.pins[1], issue100_pins=self.pins[2])

    def test_replay_without_sources(self):
        moved = self.tmp / "portable"; shutil.copytree(self.bundle, moved)
        shutil.rmtree(self.tmp / "repos")   # derivation_fixture keeps every input repo under tmp/repos
        try:
            result = replay(moved, self.expected, **self.kwargs())
            self.assertEqual(result["kind"], "review-feasibility-retained-result")
        except ReplayUnavailable as unavailable:
            self.assertTrue(unavailable.ids)

    def test_malformed_sibling_beside_unavailable_is_invalid(self):
        anchor, raw = authenticate(self.bundle, self.expected)
        broken = dict(raw); broken["issue-100-derived.json"] = canonical_bytes({"schema_version": 1})
        with self.assertRaises(ReplayInvalid):
            validate_bundle(anchor, broken, **self.kwargs())

    def test_rehashed_121_chain_break_is_invalid(self):
        anchor, raw = authenticate(self.bundle, self.expected)
        payload = json.loads(raw["issue-121.json"]); edge = dict(payload["edges"][2]); edge["parent_ordinal"] = 2
        edge["id"] = telemetry_digest({k: v for k, v in edge.items() if k != "id"})
        payload["edges"][2] = edge
        with self.assertRaises(ReplayInvalid):
            validate_bundle(anchor, {**raw, "issue-121.json": canonical_bytes(payload)}, **self.kwargs())
```

  Add these named cases with exact assertions:
  - `test_command_exit_contract`: run `python -m agent_tools.replay_retained` on a bundle with fixture pins. The command uses the real pins, so a portable bundle exits 2 with `invalid:`. Assert empty stdout and exactly one stderr line.
  - `test_wrong_expected_digest_is_invalid`
  - `test_partial_bundle_is_invalid`
  - `test_unavailable_ids_follow_payload_order`
  - `test_over_budget_measured_outcome_is_exit_zero_result`, using a fixture whose limits force over budget.
- [ ] **Step 2: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_replay.py`. The expected result is an ImportError.
- [ ] **Step 3: Implement the module and the command.** Implement the interfaces above. The command maps `WitnessError`/`ReplayInvalid` and each domain error to `invalid:<code>`.
- [ ] **Step 4: Verify.** The focused command must pass, and `just agent-workflow-tests` must report zero failures. To confirm the check can fail: `rg -n 'subprocess|_run_git|"git"' python/agent_tools/review_replay.py` prints nothing; write it as `if rg -q ...; then exit 1; fi`. Also, `python -m agent_tools.replay_retained` is absent before Step 3.
- [ ] **Step 5: Commit.** Stage only these four files and commit `feat(review): replay retained bundles without Git (#234)`. The controller then pins this head as the source-review commit (D13).

## Forecast basis

Estimates per D15:
- Module: 280 lines / 14,000 B → 14,792.
- Command: 70 lines / 3,000 B → 3,582.
- Test: 280 lines / 15,500 B → 16,292.
- `justfile`: sixth contribution, with a cumulative 4,608 B / +7.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[120,120,120],"id":6,"records":[{"bounds":[{"added_lines":280,"boundary":"derive","deleted_lines":0,"record_bytes":14792,"support":{"covers":["t6-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-1","last_task":6,"owner":6,"path":"python/agent_tools/review_replay.py"},{"bounds":[{"added_lines":70,"boundary":"derive","deleted_lines":0,"record_bytes":3582,"support":{"covers":["t6-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-2","last_task":6,"owner":6,"path":"python/agent_tools/replay_retained.py"},{"bounds":[{"added_lines":280,"boundary":"derive","deleted_lines":0,"record_bytes":16292,"support":{"covers":["t6-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-3","last_task":6,"owner":6,"path":"tests/test_review_replay.py"},{"bounds":[{"added_lines":7,"boundary":"derive","deleted_lines":0,"record_bytes":4608,"support":{"covers":["t1-4","t2-4","t3-4","t4-3","t5-5","t6-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t6-4","last_task":8,"owner":6,"path":"justfile"}]}}
```
