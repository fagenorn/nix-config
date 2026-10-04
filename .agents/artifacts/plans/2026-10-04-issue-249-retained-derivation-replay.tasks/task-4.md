# Task 4: Portable replay and the replay command

Classification of a validated bundle, the retained result and the exit contract (spec § *Replay and its command*, § *Error codes*; RP2, RP7, RP8, RP17). This task completes `python/`: the controller runs G2 on its accepted head.

**Files:**
- Create: `python/agent_tools/review_replay.py`
- Create: `python/agent_tools/replay_retained.py`
- Create: `tests/test_review_replay.py`
- Modify: `justfile` (add `tests/test_review_replay.py \` after `tests/test_review_derivation.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes (Task 2, `agent_tools.review_witness`): `WitnessError` (with `code`), `ANCHOR_NAME`, `authenticate(bundle_dir, expected_anchor_sha256) -> (anchor, raw)` (replay steps 1–2; `raw` holds the four payloads' bytes by name), `validate_bundle(anchor, raw, *, task7_pins, issue121_pins, issue100_pins) -> dict[str, dict]` (step 3, the decoded payloads by name), `build_anchor(components, raw) -> dict` (tests only).
- Consumes (Task 3, `agent_tools.review_derivation`, tests only): `DeriveInputs(issue_121_repo, issue_100_repo, archive_dir, tool_repo, tool_commit, output_dir)`, `derive_bundle(inputs, *, task7_pins, issue121_pins, issue100_pins, authority) -> {anchor_sha256, members}`.
- Consumes (SOURCE): `unavailable_ids(payload) -> tuple[str, ...]`; the errors `EstimateError`, `ContributionError`, `Issue100Error`; the constants `TASK7_PINS`, `ISSUE_121_PINS`, `ISSUE_100_PINS`.
- Consumes (CORE): `review_forecast.canonical_bytes`; `agent_tools.canonical.telemetry_digest`. Support: `retained_fixture`, `tool_fixture`, `source_budget_env`.
- Produces (`review_replay`):
  - `class ReplayUnavailable(Exception)` with `ids: tuple[str, ...]`.
  - `replay(bundle_dir: Path, expected_anchor_sha256: str, *, task7_pins, issue121_pins, issue100_pins) -> dict`.
- Produces (`replay_retained`): `main(argv=None) -> int`, parser `prog="replay-retained"`, exactly two required options `--fixtures-dir` and `--expected-anchor-sha256`. No `--anchor` and no pin option.

**Invariants:**
- `replay` is `authenticate`, then `validate_bundle`, then classification, in that order; it adds no validation of its own. It raises `ReplayUnavailable(unavailable_ids(issue_121_payload))` when that tuple is non-empty, after validation has passed.
- The result has exactly these members: `schema_version` 3; `kind` `"review-feasibility-retained-result"`; `anchor_sha256` (the expected digest); `issue_121` = `{aggregate, boundaries, operational_effects}` copied from the issue-121 payload; `issue_100` = `{history_edge_count, disposition_counts, pending_overlap_count, fixture_sha256}`, where the counts are the validated `summary`'s `edge_records`, its `historical_process`/`integrated`/`candidate` members, and `pending_overlaps`, and `fixture_sha256` is the anchor member row's `raw_sha256` for `issue-100-derived.json`.
- Neither module runs Git, imports `subprocess`, calls the budget authority or reads outside `bundle_dir`.
- The command passes the three real pin constants. Exits (spec's table): every outcome measured → `canonical_bytes(result)` on stdout, empty stderr, 0; `ReplayUnavailable` → `replay-retained: projection_unavailable: <ids joined by ",">`, 2; the parser's raised usage error → `usage`; `WitnessError`, `EstimateError`, `ContributionError`, `Issue100Error` → `replay-retained: invalid: <code>`, 2; `OSError` → `io_error`. Exit 2 always has empty stdout and exactly one stderr line. Any other exception propagates (RP8).

- [ ] **Step 1: Write the failing tests** in `tests/test_review_replay.py`.

```python
UNAVAILABLE = dict(owners=(1, 2, 3, 6, 3), touches={4: 3})
NAMES = ("task7_pins", "issue121_pins", "issue100_pins")


def derived_bundle(tmp, limits=None, **shape):
    """`(bundle_dir, expected digest, pin keywords)` from `derive_bundle` over the portable fixture."""
    repo121, repo100, archive, pins = retained_fixture(tmp, **shape)
    with patch.dict(os.environ, source_budget_env(tmp), clear=True):
        authority = describe("review-package")
    if limits:
        authority = replace(authority, limits=replace(authority.limits, **limits))
    kwargs = dict(zip(NAMES, pins))
    summary = derive_bundle(DeriveInputs(repo121, repo100, archive, *tool_fixture(tmp), tmp / "bundle"),
                            authority=authority, **kwargs)
    return tmp / "bundle", summary["anchor_sha256"], kwargs


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def test_unavailable_bundle_replays_without_sources_in_outcome_order(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, **UNAVAILABLE)
        moved = self.tmp / "portable"; shutil.copytree(bundle, moved)
        shutil.rmtree(self.tmp / "repos"); shutil.rmtree(bundle)
        with self.assertRaises(ReplayUnavailable) as caught:
            replay(moved, expected, **kwargs)
        self.assertEqual(caught.exception.ids, ("tasks-1-3", "tasks-4-6"))

    def test_over_budget_measured_outcomes_are_a_result(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, limits={"root_max_bytes": 1})
        result = replay(bundle, expected, **kwargs)
        self.assertEqual(set(result), {"schema_version", "kind", "anchor_sha256", "issue_121", "issue_100"})
        self.assertEqual((result["schema_version"], result["kind"], result["anchor_sha256"]),
                         (3, "review-feasibility-retained-result", expected))
        rows = [*result["issue_121"]["aggregate"].values(), *result["issue_121"]["boundaries"]]
        self.assertEqual({row["measurement"]["budget_status"] for row in rows}, {"over_budget"})

    def test_validation_precedes_classification(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, **UNAVAILABLE)
        anchor, raw = authenticate(bundle, expected)
        broken = {**raw, "issue-100-derived.json": canonical_bytes({"schema_version": 1})}
        rebound = build_anchor({k: anchor[k] for k in ("tool", "issue_121", "issue_100", "archive", "estimate")}, broken)
        (bundle / "issue-100-derived.json").write_bytes(broken["issue-100-derived.json"])
        (bundle / ANCHOR_NAME).write_bytes(canonical_bytes(rebound))
        with self.assertRaises(WitnessError):   # coherent anchor digest, stale witness: invalid, never unavailable
            replay(bundle, telemetry_digest(rebound), **kwargs)
```

  Add these named cases with exact assertions:
  - `test_result_reports_the_issue100_summary`: on the default shape, `issue_100` equals `{history_edge_count: 20, disposition_counts: {historical_process: 1, integrated: 1, candidate: 6}, pending_overlap_count: 2, fixture_sha256: <SHA-256 hex of the member file>}` and `issue_121.operational_effects` equals the payload's.
  - `test_wrong_expected_digest_is_anchor_digest`; `test_partial_bundle_is_member_set` (one payload removed).
  - `test_command_real_pins_refuse_a_portable_bundle`: `sys.executable -m agent_tools.replay_retained` on a derived bundle → `(2, b"", b"replay-retained: invalid: component_mismatch\n")`.
  - `test_command_usage_and_input_refusals`: a missing option and an extra `--anchor x` → `invalid: usage`; `sha256:xyz` → `invalid: expected_digest`; a missing directory → `invalid: anchor_unreadable`; each with exit 2, empty stdout and one stderr line.
  - `test_main_maps_measured_and_unavailable_outcomes`: in process, under `patch.multiple("agent_tools.replay_retained", TASK7_PINS=..., ISSUE_121_PINS=..., ISSUE_100_PINS=...)` with the fixture pins and redirected `sys.stdout`/`sys.stderr` (RP17): the default shape returns 0, stdout `canonical_bytes(replay(...))`, empty stderr; the unavailable shape returns 2, empty stdout and stderr exactly `replay-retained: projection_unavailable: tasks-1-3,tasks-4-6\n`.

- [ ] **Step 2: Run and watch them fail.** `PYTHONPATH=python python3 -m unittest tests.test_review_replay 2>&1 | tail -3` → `ImportError` (no `agent_tools.review_replay`).

- [ ] **Step 3: Implement** the library, then the command. Docstrings state implemented behaviour in present tense.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_replay 2>&1 | tail -3
if grep -Eq 'subprocess|_run_git|review_budget|import_module|__file__' \
    python/agent_tools/review_replay.py python/agent_tools/replay_retained.py; then exit 1; fi
grep -q 'tests/test_review_replay.py' justfile
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  At the starting commit the focused suite and the `justfile` grep fail.

- [ ] **Step 5: Commit.** Stage only the four Files; subject at most 64 bytes: `feat(review): replay retained bundles without Git (#249)`. A review-fix commit uses `fix(review): address Task-4 review findings (#249)`.

- [ ] **Step 6: G1, then G2 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence`, renew G0 at `--completed-through 4` (RP14), then run G2 and record the pinned source commit. Tasks 5 and 6 change no `python/` byte.

## Forecast basis

Parent D15 price plus about ten percent; RP2 moved validation to Task 2, so the library is small:
- Library: 110 lines / 5,400 B → 6,022 → 7,168 B / +125.
- Command: 70 lines / 3,000 B → 3,582 → 4,096 B / +80.
- Test: 300 lines / 16,500 B → 17,312 → 19,456 B / +330.
- `justfile`: third cumulative contribution, the same hunk → 2,560 B / +3.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":125,"boundary":"replay","deleted_lines":0,"record_bytes":7168,"support":{"covers":["t4-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-1","last_task":4,"owner":4,"path":"python/agent_tools/review_replay.py"},{"bounds":[{"added_lines":80,"boundary":"replay","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t4-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-2","last_task":4,"owner":4,"path":"python/agent_tools/replay_retained.py"},{"bounds":[{"added_lines":330,"boundary":"replay","deleted_lines":0,"record_bytes":19456,"support":{"covers":["t4-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-3","last_task":4,"owner":4,"path":"tests/test_review_replay.py"},{"bounds":[{"added_lines":3,"boundary":"replay","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t2-4","t3-4","t4-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t4-4","last_task":6,"owner":4,"path":"justfile"}]}}
```
