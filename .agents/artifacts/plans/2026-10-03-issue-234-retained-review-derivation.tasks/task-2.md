# Task 2: Issue-121 adapter, raw-parent ancestry, outcomes and payload

**Files:**
- Create: `python/agent_tools/review_issue121.py`
- Create: `tests/test_review_issue121.py`
- Modify: `tests/retained_review_test_support.py` (add `linear_fixture`, `task7_fixture`, and `rehashed_with_extra_edge(repo, pins, target, extra)`, which returns the clean raw edge table plus an ordinal-2 `extra→target` edge with every `id` recomputed)
- Modify: `justfile` (append `tests/test_review_issue121.py` to `agent-workflow-tests`)

**Recovery:** R1 (`35e6fd7a`, `review_contributions.py` and its test) supplies the fixed assignments, the plan-anchor signature check, the selector and prerequisite fact shapes, and the `reconstruct_boundary`/`derive_121` structure. Re-author all of it here. Do not copy R1's `rev-list --parents`/`--topo-order` edge enumeration or its ancestry check (D2). The task report names the R1/R2 rows it consumes and the effects it leaves out.

**Interfaces:**
- Consumes (CORE): `review_git.original_range(repo, base, head)`, `original_commit(repo, oid) -> OriginalCommit(oid, tree, parents, raw)`, `HistoryError(code)`; `review_forecast.edge_facts(repo, parent, commit, ordinal)` (which raises `ForecastError` from `HistoryError`); `review_projection.reconstruct_owned(repo, prerequisite_commit, owned) -> Reconstruction` and `ReconstructionUnavailable(code, commit)`; plus everything `actual_inputs_from_trees`, `select_candidate` and `describe` provide. From Task 1: `Task7Pins`, `derive_task7`, `validate_task7`, `compose`, `TASK8_EFFECT` and `EstimateError`.
- Produces:
  - `class ContributionError(Exception)` with `code: str`. Every `HistoryError` or `ForecastError` raised from the history read surfaces as `ContributionError("history_unauthenticated")` with the original as `__cause__`.
  - `@dataclass(frozen=True) Issue121Pins(base: str, head: str, assignments: tuple[tuple[str, int, str | None], ...], plan_prefix: str, plan_blobs: tuple[tuple[str, str], ...], allowed_signer: bytes, task_count: int)`. Each assignment is `(commit, owner, process_reason)`, with owner 0 for process. `ISSUE_121_PINS` holds the real range `65748f48…..fe85677c…`, the twelve process pairs from issue 226 (both `design_budget_fix` rows included), the eighteen task 1–6 assignments with `8e6f0681…` as Task 3, blobs `8294252b…`/`c8c622dd…` and the SSH signer.
  - `classify(repo, pins) -> tuple[dict, ...]`, giving `{commit, owner, reason}` rows in raw range order.
  - `contribution_edges(repo, pins, classes) -> tuple[dict, ...]`. Each edge is an `edge_facts` row plus `owner`, `parent_ordinal` and `id`, where `id` is the `telemetry_digest` of the rest. Source bodies are never kept.
  - `plan_anchors(repo, pins) -> list[dict]`
  - `reconstruct_boundary(repo, pins, *, boundary: str, prerequisite: Mapping, edges: Sequence[dict], table: dict, task7_pins, authority) -> dict`, which returns one closed outcome row.
  - `derive_121(repo, pins, task7_pins, authority) -> dict`, the payload. Its keys are `schema_version` (3), `kind`, `range`, `classes`, `edges`, `anchors`, `aggregate{actual, projected}`, `boundaries` (`tasks-1-3`, `tasks-4-6`, `tasks-7-8`, in that order), `operational_effects` (`[TASK8_EFFECT]`) and `record_table_policy{domain, policy_sha256}`.
  - `validate_121(payload, pins, table) -> None`, which checks structure only and never touches Git, and `unavailable_ids(payload) -> tuple[str, ...]`.

**Invariants:**
- `classify` requires the exact ordered raw range from `original_range` and assigns every commit exactly once. An unknown, task-zero, invented, duplicate, multiple or Task 7/8 assignment fails.
- Edges come only from `original_commit(...).parents` (D2). Every commit has exactly one raw parent, which equals the previous range member (the base for the first commit), so there are exactly 30 edges. The module never runs `git rev-list`, `git log` or `rev-parse <c>^{tree}`.
- A graft, replace ref, shallow file or `GIT_*` routing variable raises `ContributionError`. It never yields a valid `projection_unavailable` row.
- `reconstruct_boundary` recomputes the complete edge table through `contribution_edges` and requires the caller's `edges` to be canonically equal: a rehashed 31-edge, reordered, dropped or added table is invalid. Selectors are exactly `tasks-N`/`tasks-N-M` over owners 1–6. The prerequisite is the base or an authenticated commit/tree whose product closure is exactly `1..first-1`, and `null`/`null` is allowed only when no such commit exists. Ownership never comes from a caller's plan path.
- Each plan anchor's latest writer is verified with `git verify-commit` under a private `gpg.ssh.allowedSignersFile` and an empty revocation file. The writer and blob come from the raw closure.
- Outcome rows are closed (spec "Historical outcomes"):
  - `measured` adds `result_tree`, `record_refs` and `measurement`.
  - `projection_unavailable` adds only `failure{stage, code, evidence_refs}`.
  - `edge_ids` always lists the full selected edge sequence.
  - Every ref resolves exactly once.
  - Nothing hard-codes or asserts a status.
- `tasks-7-8` uses the prerequisite `fe85677c` and has no owned commits. Its `result_tree` equals the prerequisite tree, and its records are the table's bounds (D5). `aggregate.projected` comes from `compose`, and an `EstimateError` there makes it unavailable with stage `estimate`.

- [ ] **Step 1: Write the failing tests.** These go in `tests/test_review_issue121.py`, using the D12 support module. `linear_fixture(tmp, n=6, owners=...)` builds a signed linear repository plus `Issue121Pins`, and `task7_fixture` builds a small table. Both are added to the support module as its second cumulative contribution.

```python
class AncestryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.pins = linear_fixture(self.tmp)
        self.task7_pins, self.table = task7_fixture(self.tmp)       # Task-1 shaped table over its own repo
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.authority = describe("review-package")

    def test_clean_control_has_one_raw_edge_per_commit(self):
        edges = contribution_edges(self.repo, self.pins, classify(self.repo, self.pins))
        self.assertEqual([e["parent_ordinal"] for e in edges], [1] * len(self.pins.assignments))

    def test_graft_is_invalid_at_both_entry_points_and_preserves_state(self):
        before = snapshot(self.repo)
        extra = self.pins.assignments[0][0]
        target = self.pins.assignments[3][0]
        parent = git(self.repo, "cat-file", "-p", target).split("\n")[1].split()[1]
        forged = rehashed_with_extra_edge(self.repo, self.pins, target, extra)   # built before the graft
        (self.repo / ".git/info/grafts").write_text(f"{target} {parent} {extra}\n")
        with self.assertRaises(ContributionError):
            contribution_edges(self.repo, self.pins, classify(self.repo, self.pins))
        with self.assertRaises(ContributionError):
            reconstruct_boundary(self.repo, self.pins, boundary="tasks-1", prerequisite={"kind": "delivery-base"},
                                 edges=forged, table=self.table, task7_pins=self.task7_pins, authority=self.authority)
        (self.repo / ".git/info/grafts").unlink()
        self.assertEqual(snapshot(self.repo), before)
```

  Add these named cases with exact assertions:
  - `test_replace_ref_is_invalid`
  - `test_shallow_file_is_invalid`
  - `test_alternate_replace_base_is_invalid`
  - `test_git_routing_variables_are_invalid`: `GIT_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_REPLACE_REF_BASE` and `GIT_GRAFT_FILE`.
  - `test_rehashed_reordered_dropped_added_edges_are_invalid`
  - `test_assignment_mutations_fail`: unknown, task-zero, duplicate, multiple, observed-7/8, reordered and omitted.
  - `test_forged_or_wrong_key_signature_and_substituted_plan_blob_fail`
  - `test_unavailable_row_with_tree_metrics_or_records_fails_validation`
  - `test_edge_removed_or_reordered_after_failure_fails_validation`
  - `test_forged_or_removed_failure_reference_fails`
  - `test_late_fix_touching_excluded_path_yields_unavailable_with_that_edge`, on a fixture where Task 3's last commit edits a path that Task 6 introduced.
  - `test_duplicate_final_record_fails`
  - `test_payload_rows_are_closed_and_statuses_are_not_asserted`
- [ ] **Step 2: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_issue121.py`. The expected result is an ImportError for `agent_tools.review_issue121`.
- [ ] **Step 3: Implement the module.** Implement the interfaces above. Wrap every CORE history call so that its error becomes a `ContributionError` cause. Measure through `actual_inputs_from_trees` plus `select_candidate(..., measurement_only=True)` with `describe("review-package")` limits, and never copy those limits. The package name is `review-<base[:7]>..<head[:7]>.json`.
- [ ] **Step 4: Verify.** The focused command above must pass. Run `just agent-workflow-tests` and expect zero failures. To confirm the check can fail: `rg -n 'rev-list|"log"|\^\{tree\}' python/agent_tools/review_issue121.py` must print nothing; write it as `if rg -q ...; then exit 1; fi`.
- [ ] **Step 5: Commit.** Stage only these four files and commit `feat(review): authenticate issue-121 raw history (#234)`.

## Forecast basis

Estimates per D15:
- Module: 560 lines / 29,000 B → 30,072.
- Test: 520 lines / 29,000 B → 30,032.

The `justfile` contribution is the second of seven, with a cumulative bound of 2,560 B / +3. Support module: second of four, adding 120 lines / 6,500 B for a cumulative 19,872 B / +360.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":560,"boundary":"derive","deleted_lines":0,"record_bytes":30072,"support":{"covers":["t2-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":520,"boundary":"derive","deleted_lines":0,"record_bytes":30032,"support":{"covers":["t2-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-2","last_task":2,"owner":2,"path":"tests/test_review_issue121.py"},{"bounds":[{"added_lines":360,"boundary":"derive","deleted_lines":0,"record_bytes":19872,"support":{"covers":["t1-2","t2-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-3","last_task":5,"owner":2,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":3,"boundary":"derive","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t1-4","t2-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-4","last_task":8,"owner":2,"path":"justfile"}]}}
```
