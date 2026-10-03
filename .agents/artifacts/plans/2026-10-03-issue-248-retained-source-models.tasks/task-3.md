# Task 3: Issue-100 verifier and byte domains

**Files:**
- Create: `python/agent_tools/review_issue100.py`
- Create: `tests/test_review_issue100.py`
- Modify: `tests/retained_review_test_support.py` (add `issue100_fixture`; third of three contributions)
- Modify: `justfile` (add `tests/test_review_issue100.py \` after `tests/test_review_issue121.py \`; third of three contributions)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one `LEGACY_MIGRATION_INPUTS` row, `"python/agent_tools/review_issue100.py": frozenset({"resolve-bindings"}),  # policy-gate-pattern`, beside Task 1's rows; S21)

**Recovery:** parent R3 (`55cef035`, deriver blob `913ab952`) supplies the issue-100 constants, the criteria rows, `PROCESS_PATHS`, `PENDING_PATHS`, the producer and manifest SHA-256 values and the archive-envelope check (`archive_evidence`). Port them. Replace its `rev-list` range with `original_range` and its `nofollow` reads with `read_regular`. Drop its pathname-multiplier projections, its hard-coded boundary expectations (rejected I2) and `ARCHIVE_RELATIVE` (S11). The report names the rows consumed and the effects omitted.

**Interfaces:**
- Consumes (CORE): `review_git.original_range`, `original_commit`, `HistoryError`; `review_forecast.edge_facts`, `read_regular(repo, relative, limit)` (no-follow, bounded), `canonical_bytes`, `strict_json`, `ForecastError`; `review_actual.RECORD_POLICY`, `actual_inputs_from_trees`; `agent_tools.canonical.telemetry_digest`. Support helpers from Tasks 1–2.
- Produces:
  - `class Issue100Error(Exception)` with `code: str`.
  - `@dataclass(frozen=True) Domain(name: str, policy_sha256: str, bytes: int, records: int, sha256: str)`.
  - `@dataclass(frozen=True) Issue100Pins(base: str, head: str, live: str, producer_name: str, manifest_name: str, producer_bytes: int, manifest_bytes: int, producer_sha256: str, manifest_sha256: str, process_paths: frozenset[str], pending_paths: tuple[str, ...], criteria: tuple[dict, ...], recipe: tuple[str, ...], historical: Domain, fresh: Domain, expected_counts: dict)`. `recipe` is the exact R3 argv and `-c` config of the `retained-git-records/v1` producer.
  - `ISSUE_100_PINS`: base `6d4b7a49dd3a44c079c8310e902a86665a6805f0`, head `a7b7c6f45787c7c928d064b46ed499087b5b3c46`, live `cba57498b1ec25f904bd2653029636c79abba41f`; historical domain `retained-git-records/v1` (1,005,707 B, 115 records); fresh domain `review-git-records/v1` (1,012,913 B, 115 records); `expected_counts` `{commits: 82, parent_edges: 91, merge_edges: 9, edge_records: 543, contributions: 115, historical_process: 8, integrated: 38, candidate: 69, candidate_ordinary: 65, candidate_reconciliation: 4, pending_overlaps: 4, reconciled: 0}` (S10).
  - `verify_archive(archive_dir: Path, issue_repo: Path, pins) -> dict`: `{producer_sha256, manifest_sha256, shards: [{path, bytes, sha256}]}`.
  - `historical_records(issue_repo, pins) -> tuple[dict, ...]` (the fixed recipe) and `fresh_records(issue_repo, pins, limits) -> tuple[dict, ...]` (`actual_inputs_from_trees` under `RECORD_POLICY`).
  - `derive_100(issue_repo: Path, live_repo: Path, archive_dir: Path, pins, limits) -> dict` with keys `schema_version`, `kind`, `range`, `parent_edges`, `edges`, `contributions`, `pending_overlaps`, `criteria`, `tables`, `summary`. `parent_edges` is the ordered raw `{parent, commit, parent_ordinal}` list; `edges` holds each parent edge's `edge_facts` records; `tables` maps `historical` and `fresh` to `{record_table_policy: {domain, policy_sha256}, records}`.
  - `validate_100(payload, pins) -> None`, Git-free.
  - Support: `issue100_fixture(tmp) -> tuple[Path, Path, Path, Issue100Pins]` (issue repo, live repo, archive dir, pins): a real history with one merge, a live branch, and an archive whose producer, manifest and `shard-NNN.diff` shards come from running the fixture-pinned recipe; `expected_counts` come from the fixture's own facts.

**Invariants:**
- `archive_dir` is an explicit argument; no module derives it from a repository path (S11). Producer and manifest are read with `read_regular` limited to the pinned `producer_bytes`/`manifest_bytes`, and each shard limited to the byte count the verified manifest declares. A symlink, a non-regular file or an over-limit read raises `Issue100Error("archive_unreadable")`; a raw SHA-256 or size that differs from its pin raises `Issue100Error("archive_digest_mismatch")`. Both checks precede any `strict_json` decode.
- The shards concatenate to the recipe's output byte for byte, matching the historical domain's bytes, record count and digest; fresh records match the fresh domain. Each table carries its own `record_table_policy`; swapping a label or a digest is invalid. No function measures the historical domain as a review package, and historical bytes never bound fresh ones.
- Parent edges come from `original_commit` parents in `original_range` order, every ordinal included. `validate_100` recomputes commits, parent edges, merge edges and edge records (82/91/9/543 on the real range) from the tables and compares them with `expected_counts`; `summary` is likewise recomputed, never trusted (S10).
- Every governing and superseded criterion keeps its original digest. A candidate label proves neither integration nor activation.
- Every `HistoryError`/`ForecastError` becomes `Issue100Error("history_unauthenticated")` with the original as `__cause__`. Derivation leaves archive bytes and the repositories' refs, index and objects unchanged.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_issue100.py`:

```python
import os, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_budget import describe
from agent_tools.review_issue100 import Issue100Error, derive_100, validate_100, verify_archive

from .retained_review_test_support import issue100_fixture, snapshot, source_budget_env


class Issue100Test(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.live, self.archive, self.pins = issue100_fixture(self.tmp)
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.limits = describe("review-package").limits

    def archive_bytes(self):
        return {p.relative_to(self.archive): p.read_bytes() for p in self.archive.rglob("*") if p.is_file()}

    def refused(self, call):
        with self.assertRaises(Issue100Error):
            call()

    def test_derive_validates_and_preserves_inputs(self):
        before = self.archive_bytes(), snapshot(self.repo), snapshot(self.live)
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        validate_100(payload, self.pins)
        merges = [e for e in payload["parent_edges"] if e["parent_ordinal"] > 1]
        self.assertEqual(len(merges), self.pins.expected_counts["merge_edges"])
        self.assertGreater(self.pins.expected_counts["merge_edges"], 0)
        self.assertEqual((self.archive_bytes(), snapshot(self.repo), snapshot(self.live)), before)

    def test_symlinked_oversized_or_wrong_digest_archive_member_is_refused(self):
        members = [self.archive / self.pins.producer_name, self.archive / self.pins.manifest_name,
                   sorted(self.archive.rglob("*.diff"))[0]]
        for member in members:
            original = member.read_bytes()
            for code, mutate in (
                    ("archive_unreadable", lambda: (member.unlink(), (self.tmp / "t").write_bytes(original),
                                                    member.symlink_to(self.tmp / "t"))),
                    ("archive_unreadable", lambda: member.write_bytes(original + b" ")),
                    ("archive_digest_mismatch", lambda: member.write_bytes(original[:-1] + b"X"))):
                with self.subTest(member=member.name, code=code):
                    mutate()
                    with self.assertRaises(Issue100Error) as caught:
                        verify_archive(self.archive, self.repo, self.pins)
                    self.assertEqual(caught.exception.code, code)
                    member.unlink(); member.write_bytes(original)

    def test_domain_label_or_policy_swap_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        tables = payload["tables"]
        h, f = tables["historical"]["record_table_policy"], tables["fresh"]["record_table_policy"]
        for historical, fresh in ((f, h), ({**h, "domain": f["domain"]}, f),
                                  ({**h, "policy_sha256": f["policy_sha256"]}, f)):
            swapped = {**payload, "tables": {"historical": {**tables["historical"], "record_table_policy": historical},
                                             "fresh": {**tables["fresh"], "record_table_policy": fresh}}}
            self.refused(lambda: validate_100(swapped, self.pins))

    def test_rehashed_edge_order_or_coverage_change_is_invalid(self):
        payload = derive_100(self.repo, self.live, self.archive, self.pins, self.limits)
        edges = payload["parent_edges"]
        for changed in ([edges[1], edges[0], *edges[2:]], edges[:-1],
                        [*edges[:-1], {**edges[-1], "parent": self.pins.live}]):
            self.refused(lambda: validate_100({**payload, "parent_edges": changed}, self.pins))
```

  Add these named cases with exact assertions, each expecting `Issue100Error` from `validate_100` unless stated:
  - `test_rehashed_contribution_fact_change_is_invalid`: one contribution's fact changed with any digest recomputed by `telemetry_digest`.
  - `test_summary_disagreeing_with_tables_is_invalid`: `summary.integrated` incremented.
  - `test_edge_record_count_is_recomputed`: one record removed from one edge, so the recomputed edge-record count disagrees with `expected_counts`.
  - `test_missing_superseded_criterion_is_invalid`.
  - `test_historical_bytes_never_bound_fresh`: replacing the fresh records with the historical ones fails.
  - `test_inputs_unchanged_on_failure`: after a refused wrong-digest producer, archive bytes and both snapshots are unchanged.
  - `test_virtualized_history_is_unauthenticated`: a graft in the issue repo makes `derive_100` raise `Issue100Error` with code `history_unauthenticated`.

- [ ] **Step 2: Run the tests and watch them fail.** `PYTHONPATH=python python3 -m unittest tests.test_review_issue100 2>&1 | tail -3` → ImportError.

- [ ] **Step 3: Implement the module and `issue100_fixture`** to the interfaces and invariants above, following R3's `derive_issue_100` for criteria and the integrated/candidate rules, minus the multiplier projections.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_issue100 tests.test_review_issue121 tests.test_review_task7 2>&1 | tail -3
if rg -q 'rev-list|"log"|\^\{tree\}|ARCHIVE_RELATIVE|nofollow' python/agent_tools/review_issue100.py; then exit 1; fi
grep -q 'tests/test_review_issue100.py' justfile
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  At the Task-2 commit the import and the `justfile` grep fail, so this gate can fail.

- [ ] **Step 5: Commit.** Stage only the four Files; commit `feat(review): verify issue-100 payload and byte domains (#248)`.

## Forecast basis

Priced per parent D15 (S14). R3's issue-100 half (its lines 1–370 of 544, about 22,000 B) is the measured base; the two-level edges, the domain tables and `validate_100` add the rest:
- Module: 500 lines / 26,000 B → 27,012 B.
- Test: 340 lines / 19,000 B → 19,852 B.
- Support: adds about 125 lines / 6,500 B, cumulative 21,504 B / +405.
- `justfile`: cumulative 3,072 B / +4.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"73a36925420b6f4a8a2ffe5f6d1493dbf2cd063f","head":"4698f28dfe59cbdad7b33e4c7d145c524251c6b5"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":500,"boundary":"source","deleted_lines":0,"record_bytes":27012,"support":{"covers":["t3-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-1","last_task":3,"owner":3,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":340,"boundary":"source","deleted_lines":0,"record_bytes":19852,"support":{"covers":["t3-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-2","last_task":3,"owner":3,"path":"tests/test_review_issue100.py"},{"bounds":[{"added_lines":405,"boundary":"source","deleted_lines":0,"record_bytes":21504,"support":{"covers":["t1-2","t2-3","t3-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-3","last_task":3,"owner":3,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":4,"boundary":"source","deleted_lines":0,"record_bytes":3072,"support":{"covers":["t1-4","t2-4","t3-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-4","last_task":3,"owner":3,"path":"justfile"},{"bounds":[{"added_lines":5,"boundary":"source","deleted_lines":0,"record_bytes":3072,"support":{"covers":["t1-5","t3-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-5","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
