# Task 3: Issue-100 verifier and byte domains

**Files:**
- Create: `python/agent_tools/review_issue100.py`
- Create: `tests/test_review_issue100.py`
- Modify: `tests/retained_review_test_support.py` (add `issue100_fixture`; third of four contributions)
- Modify: `justfile` (append `tests/test_review_issue100.py` to `agent-workflow-tests`)

**Recovery:** R3 (`55cef035`, blob `913ab952`) supplies the issue-100 constants, the criteria rows, `PROCESS_PATHS`, `PENDING_PATHS`, the producer and manifest SHA-256 values, and the archive-envelope check (`archive_evidence`). R2 (`a5e942fd`, parent D10/D11) supplies the full domain digests that the spec abbreviates. Port all of these. Drop R3's pathname-multiplier projections and its hard-coded boundary expectations, which are the rejected I2 model. The report names the rows consumed and the effects omitted.

**Interfaces:**
- Consumes (CORE): `review_git.original_range`, `original_commit`; `review_forecast.edge_facts`, `read_regular(repo, relative, limit)` (no-follow and bounded), `canonical_bytes`, `strict_json`; `review_actual.RECORD_POLICY`, `actual_inputs_from_trees`; `agent_tools.canonical.telemetry_digest`.
- Produces:
  - `class Issue100Error(Exception)` with `code: str`.
  - `@dataclass(frozen=True) Domain(name: str, policy_sha256: str, bytes: int, records: int, sha256: str)`.
  - `@dataclass(frozen=True) Issue100Pins(base: str, head: str, live: str, producer_name: str, manifest_name: str, producer_sha256: str, manifest_sha256: str, process_paths: frozenset[str], pending_paths: tuple[str, ...], criteria: tuple[dict, ...], recipe_source_commit: str, recipe_blob: str, historical: Domain, fresh: Domain, expected_counts: dict)`.
  - `ISSUE_100_PINS`. It holds base `6d4b7a49dd3a44c079c8310e902a86665a6805f0`, head `a7b7c6f45787c7c928d064b46ed499087b5b3c46` and live `cba57498b1ec25f904bd2653029636c79abba41f`. The historical domain is `retained-git-records/v1` with 1,005,707 B and 115 records; the fresh domain is `review-git-records/v1` with 1,012,913 B and 115 records. `expected_counts` is `{edges: 543, contributions: 115, historical_process: 8, integrated: 38, candidate: 69, candidate_ordinary: 65, candidate_reconciliation: 4, pending_overlaps: 4, reconciled: 0}`.
  - `verify_archive(archive_dir: Path, issue_repo: Path, pins) -> dict`, giving `{producer_sha256, manifest_sha256, shards: [{path, bytes, sha256}]}`.
  - `historical_records(issue_repo, pins) -> tuple[dict, ...]`, which runs the fixed `retained-git-records/v1` recipe (exact argv/config from R3).
  - `fresh_records(issue_repo, pins, limits) -> tuple[dict, ...]`, which uses `actual_inputs_from_trees`.
  - `derive_100(issue_repo: Path, live_repo: Path, archive_dir: Path, pins, limits) -> dict`. The payload keys are `schema_version`, `kind`, `range`, `edges`, `contributions`, `pending_overlaps`, `criteria`, `tables` and `summary`, where `tables` maps each domain's `{record_table_policy: {domain, policy_sha256}, records}`.
  - `validate_100(payload, pins) -> None`, which uses no Git.

**Invariants:**
- Producer, manifest and ordered shards are read through `read_regular` without following symlinks, each with an explicit byte limit, and their raw SHA-256 values are checked against the pins before any JSON decode.
- The shards concatenate to the recipe's output exactly, matching the historical domain's bytes, record count and digest. The fresh records match the fresh domain. The two domains never mix: relabelling a table's `record_table_policy` fails, historical bytes are never used as a fresh bound, and no function measures the historical domain as a review package.
- History edges come from raw parents in `original_range` order, including merges at every parent ordinal. There are 543 of them, and every edge's commit and parent close over the pinned range.
- `summary` is recomputed from the complete tables by `validate_100` and compared; it is never an independent assertion. A candidate label proves neither integration nor activation, and no field says it does.
- Every governing and superseded criterion keeps its original digest.
- Derivation leaves the archive files byte-identical and the repositories' refs, index and objects unchanged.

- [ ] **Step 1: Write the failing tests.** These go in `tests/test_review_issue100.py`. `issue100_fixture(tmp)` builds a real Git history with one merge, a live branch, an archive directory whose producer, manifest and shards come from running the fixture-pinned recipe, and matching `Issue100Pins`, with `expected_counts` taken from the fixture's own facts.

```python
class Issue100Test(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.live, self.archive, self.pins = issue100_fixture(self.tmp)
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.limits = describe("review-package").limits

    def test_derive_validates_and_preserves_archive(self):
        before = {p.name: p.read_bytes() for p in self.archive.rglob("*") if p.is_file()}
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        validate_100(payload, self.pins)
        self.assertEqual({p.name: p.read_bytes() for p in self.archive.rglob("*") if p.is_file()}, before)

    def test_symlinked_shard_is_refused_before_decode(self):
        shard = sorted((self.archive).rglob("shard-*.diff"))[0]
        target = self.tmp / "elsewhere.diff"; target.write_bytes(shard.read_bytes())
        shard.unlink(); shard.symlink_to(target)
        with self.assertRaises(Issue100Error):
            verify_archive(self.archive, self.repo, self.pins)

    def test_domain_label_swap_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        tables = payload["tables"]
        swapped = {**payload, "tables": {"historical": {**tables["historical"], "record_table_policy": tables["fresh"]["record_table_policy"]},
                                         "fresh": tables["fresh"]}}
        with self.assertRaises(Issue100Error):
            validate_100(swapped, self.pins)
```

  Add these named cases with exact assertions:
  - `test_rehashed_edge_order_or_coverage_change_is_invalid`
  - `test_rehashed_contribution_fact_change_is_invalid`
  - `test_summary_disagreeing_with_tables_is_invalid`
  - `test_missing_superseded_criterion_is_invalid`
  - `test_oversized_or_wrong_digest_producer_is_refused`
  - `test_edge_parent_outside_range_is_invalid`
  - `test_inputs_unchanged_on_failure`
- [ ] **Step 2: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_issue100.py`. The expected result is an ImportError.
- [ ] **Step 3: Implement the module.** Implement the interfaces above. The criteria and the integrated/candidate classification rules follow R3's `derive_issue_100`, minus the multiplier projections.
- [ ] **Step 4: Verify.** The focused command must pass, and `just agent-workflow-tests` must report zero failures. To confirm the check can fail: before Step 3, `grep -c review_issue100 justfile` prints `0`.
- [ ] **Step 5: Commit.** Stage only these four files and commit `feat(review): verify issue-100 payload and byte domains (#234)`.

## Forecast basis

Estimates per D15:
- Module: 400 lines / 20,500 B → 21,412.
- Test: 280 lines / 15,500 B → 16,292.
- Support module: third of four contributions, adding 100 lines / 5,500 B for a cumulative 25,472 B / +460.
- `justfile`: third contribution, with a cumulative 3,072 B / +4.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[120,120,120],"id":3,"records":[{"bounds":[{"added_lines":400,"boundary":"derive","deleted_lines":0,"record_bytes":21412,"support":{"covers":["t3-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-1","last_task":3,"owner":3,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":280,"boundary":"derive","deleted_lines":0,"record_bytes":16292,"support":{"covers":["t3-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-2","last_task":3,"owner":3,"path":"tests/test_review_issue100.py"},{"bounds":[{"added_lines":460,"boundary":"derive","deleted_lines":0,"record_bytes":25472,"support":{"covers":["t1-2","t2-3","t3-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-3","last_task":5,"owner":3,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":4,"boundary":"derive","deleted_lines":0,"record_bytes":3072,"support":{"covers":["t1-4","t2-4","t3-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-4","last_task":8,"owner":3,"path":"justfile"}]}}
```
