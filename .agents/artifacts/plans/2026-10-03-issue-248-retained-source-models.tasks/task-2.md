# Task 2: Issue-121 adapter, raw-parent ancestry, outcomes and payload

**Files:**
- Create: `python/agent_tools/review_issue121.py`
- Create: `tests/test_review_issue121.py`
- Modify: `tests/retained_review_test_support.py` (add `linear_fixture`, `task7_fixture`, `rehash_edges`; second of three contributions)
- Modify: `justfile` (add `tests/test_review_issue121.py \` after `tests/test_review_task7.py \`; second of three contributions)

**Recovery:** parent R1 (`35e6fd7a`: `python/agent_tools/review_contributions.py`, `tests/test_review_contributions.py`) supplies the fixed assignments, the plan-anchor signature check, the selector and prerequisite fact shapes, and the `reconstruct_boundary`/`derive_121` structure. Re-author them here. Leave out R1's `rev-list --parents`/`--topo-order` enumeration and its ancestry check (parent D2). The report names the R1 rows consumed and the effects omitted.

**Interfaces:**
- Consumes (CORE): `review_git.original_range(repo, base, head)`, `original_commit(repo, oid) -> OriginalCommit(oid, tree, parents, raw)`, `HistoryError(code)`; `review_forecast.edge_facts(repo, parent, commit, ordinal)`, `ForecastError`, `raw_digest`, `canonical_bytes`; `review_actual._split_diff`, `git_diff`, `actual_inputs_from_trees`, `select_candidate(inputs, limits, *, transform=None, measurement_only=False)`, `PACKING_POLICY_SHA256`; `review_projection.reconstruct_owned(repo, prerequisite_commit, owned)`, `ReconstructionUnavailable(code, commit)`; `review_budget.describe`. From Task 1: `Task7Pins`, `TASK7_PINS`, `derive_task7`, `validate_task7`, `compose`, `TASK8_EFFECT`, `EstimateError`, and the support helpers `git`, `init_repo`, `commit_files`, `ssh_signer`, `snapshot`, `source_budget_env`.
- Produces (parent D12 shapes, carried forward):
  - `class ContributionError(Exception)` with `code: str`.
  - `@dataclass(frozen=True) Issue121Pins(base: str, head: str, assignments: tuple[tuple[str, int, str | None], ...], plan_prefix: str, plan_blobs: tuple[tuple[str, str], ...], allowed_signer: bytes, task_count: int)`. `ISSUE_121_PINS` holds the range `65748f48…..fe85677c8bd26c808ac69c2ee21b17ff6e262923` (full ids from R1), the twelve process pairs (both `design_budget_fix` rows), the eighteen task 1–6 assignments with `8e6f0681…` as Task 3, blobs `8294252b…`/`c8c622dd…` and the SSH signer.
  - `classify(repo, pins) -> tuple[dict, ...]`: `{commit, owner, reason}` rows in raw range order.
  - `contribution_edges(repo, pins, classes) -> tuple[dict, ...]`: each an `edge_facts` row plus `owner` and `id` (the `telemetry_digest` of every other member); each record gains `hunk_header_sha256` (the digest of that record's `@@` lines from the same `--binary -U10` chunk, whose `raw_digest` must equal `record_sha256`; no lines digest empty bytes).
  - `plan_anchors(repo, pins) -> list[dict]`.
  - `reconstruct_boundary(repo, pins, *, boundary: str, prerequisite: Mapping, edges: Sequence[dict], table: dict, task7_pins, authority) -> dict`: one closed outcome row.
  - `derive_121(repo, pins, task7_pins, authority) -> dict` with keys `schema_version` (3), `kind`, `range`, `classes`, `edges`, `anchors`, `records`, `aggregate{actual, projected}`, `boundaries` (`tasks-1-3`, `tasks-4-6`, `tasks-7-8`, in order), `operational_effects` (`[TASK8_EFFECT]`) and `record_table_policy{domain, policy_sha256}`.
  - `records`, the final-record table: one closed row per final record of a measured outcome, ordered by outcome (`aggregate.actual`, `aggregate.projected`, then the boundaries) and by path. An `actual` row is `{id, kind: "actual", scope, path, record_bytes, record_sha256, edge_ids}`: one whole initial-context record from `actual_inputs_from_trees` over that outcome's trees, with `edge_ids` its ordered, non-empty edge lineage (R1's `_record_facts` rule). An `estimate` row is `{id, kind: "estimate", scope, path, record_bytes, added_lines, deleted_lines}`: one `compose` row (`aggregate.projected`) or one Task-7 table bound (`tasks-7-8`). `scope` is the outcome label, so a cumulative or composed record is one row of its outcome, never a parent-edge record. `id` is the `telemetry_digest` of every other member, and `(scope, path)` is unique.
  - `validate_121(payload, pins, table) -> None` (Git-free) and `unavailable_ids(payload) -> tuple[str, ...]`.
  - Support: `linear_fixture(tmp, owners=(1, 1, 2, 3, 3, 4, 5, 6), touches=None) -> tuple[Path, Issue121Pins]`: a linear repository whose first commit writes the plan root and Task-7 member under `plan_prefix`, plus a Task-7 seed (one file under each move root, every `TARGETS` input and a renderer source), and is SSH-signed by an `ssh_signer` key (the pins' `allowed_signer`); product commit `k` (0-based, after that commit) then writes `src/c<k>.txt` for owner `owners[k]`, and `touches={k: j}` makes commit `k` also edit commit `j`'s file. Owner 0 rows get a process reason. `task7_fixture(repo, pins) -> tuple[Task7Pins, dict]`: Task-7 pins over that same repository, with `prerequisite_commit == pins.head`, its tree, the plan blobs and the seed renderer, and their `derive_task7` table; `rehash_edges(edges) -> list[dict]` (copies each edge and recomputes its `id`).

**Invariants:**
- **I1 in both entry points (S9).** `contribution_edges` is the only edge source. It reads `original_range` order and `original_commit(...).parents`, and requires exactly one raw parent per commit, equal to the preceding member (the base for the first). `derive_121` and `reconstruct_boundary` both call it. `reconstruct_boundary` compares the caller's `edges` canonically with its own recomputation and raises `ContributionError("edge_table_mismatch")` on any difference.
- Every `HistoryError` or `ForecastError` reaching either entry point becomes `ContributionError("history_unauthenticated")` with the original as `__cause__`, including inside a reconstruction. `ReconstructionUnavailable` is caught first, by type, and only it yields `projection_unavailable` (S9).
- `classify` assigns each commit of the exact raw range exactly once. Unknown, task-zero, invented, duplicate, multiple, Task 7/8, reordered and omitted assignments raise `ContributionError`. Selectors are exactly `tasks-N`/`tasks-N-M` over owners 1–6; ownership never comes from a caller's plan path.
- Each plan anchor's latest writer is checked with `git verify-commit` under a private `gpg.ssh.allowedSignersFile` (from `pins.allowed_signer`) and an empty revocation file; writer and blob come from the raw closure.
- Outcome rows follow parent § *Historical outcomes* exactly: common `boundary,state,prerequisite,edge_ids,estimate_refs`; `measured` adds `result_tree,record_refs,measurement`; `projection_unavailable` adds only `failure{stage,code,evidence_refs}`. Every ref resolves exactly once: `edge_ids` and `failure.evidence_refs` into `edges`; `record_refs` into `records`, listing exactly the rows whose `scope` is that outcome, in table order, so every record is referenced once; `estimate_refs` is `[telemetry_digest(table)]` for `aggregate.projected` and `tasks-7-8` and empty otherwise. `validate_121` checks each rule. Neither source nor tests name a status for a real boundary; fixture tests assert the status each fixture forces.
- `tasks-7-8` uses the prerequisite `fe85677c…` with no owned commits; its `result_tree` is the prerequisite tree and its records are the table's bounds (parent D5). `aggregate.projected` comes from `compose`; an `EstimateError` there makes it unavailable with stage `estimate`.
- Measurement uses `actual_inputs_from_trees` + `select_candidate(..., measurement_only=True)` with `describe("review-package")` limits, package name `review-<base[:7]>..<head[:7]>.json`. Source refs, index, objects and files are unchanged by every call.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_issue121.py`:

```python
import os, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_budget import describe
from agent_tools.review_forecast import ForecastError
from agent_tools.review_git import HistoryError
from agent_tools.review_issue121 import (ContributionError, classify, contribution_edges, derive_121,
                                         reconstruct_boundary, validate_121)

from .retained_review_test_support import (git, linear_fixture, rehash_edges, snapshot, source_budget_env,
                                           task7_fixture)


class AncestryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.pins = linear_fixture(self.tmp)
        self.task7_pins, self.table = task7_fixture(self.repo, self.pins)
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.authority = describe("review-package")
        self.edges = list(contribution_edges(self.repo, self.pins, classify(self.repo, self.pins)))

    def selector(self, edges):
        return reconstruct_boundary(self.repo, self.pins, boundary="tasks-1",
                                    prerequisite={"kind": "delivery-base"}, edges=edges, table=self.table,
                                    task7_pins=self.task7_pins, authority=self.authority)

    def entry_points(self, edges, env):
        def scoped(call):
            def run():
                with patch.dict(os.environ, env):
                    return call()
            return run
        return (scoped(lambda: contribution_edges(self.repo, self.pins, classify(self.repo, self.pins))),
                scoped(lambda: derive_121(self.repo, self.pins, self.task7_pins, self.authority)),
                scoped(lambda: self.selector(edges)))

    def test_clean_control_has_one_raw_edge_per_commit(self):
        commits = [c for c, _, _ in self.pins.assignments]
        self.assertEqual([e["commit"] for e in self.edges], commits)
        self.assertEqual([e["parent"] for e in self.edges], [self.pins.base, *commits[:-1]])
        self.assertEqual({e["parent_ordinal"] for e in self.edges}, {1})
        self.assertIn(self.selector(self.edges)["state"], {"measured", "projection_unavailable"})

    def test_clean_payload_validates_over_one_history(self):
        self.assertEqual(self.task7_pins.prerequisite_commit, self.pins.head)
        payload = derive_121(self.repo, self.pins, self.task7_pins, self.authority)
        self.assertIsNone(validate_121(payload, self.pins, self.table))
        self.assertEqual([r["boundary"] for r in payload["boundaries"]], ["tasks-1-3", "tasks-4-6", "tasks-7-8"])

    def test_virtualized_history_is_invalid_at_both_entry_points(self):
        commits = [c for c, _, _ in self.pins.assignments]
        target, extra = commits[3], commits[0]
        forged = rehash_edges(self.edges[:4] + [{**self.edges[3], "parent": extra, "parent_ordinal": 2}]
                              + self.edges[4:])
        gitdir = Path(git(self.repo, "rev-parse", "--absolute-git-dir"))
        outside = self.tmp / "grafts"; outside.write_text(f"{target} {commits[2]} {extra}\n")
        attacks = {
            "graft": (lambda: (gitdir / "info/grafts").write_text(f"{target} {commits[2]} {extra}\n"), {}),
            "replace_ref": (lambda: git(self.repo, "replace", "--graft", target, commits[2], extra), {}),
            "alternate_replace_base": (lambda: git(self.repo, "replace", "--graft", target, commits[2], extra,
                                                   env={"GIT_REPLACE_REF_BASE": "refs/alt/"}),
                                       {"GIT_REPLACE_REF_BASE": "refs/alt/"}),
            "shallow": (lambda: (gitdir / "shallow").write_text(commits[1] + "\n"), {}),
            "GIT_DIR": (lambda: None, {"GIT_DIR": str(gitdir)}),
            "GIT_OBJECT_DIRECTORY": (lambda: None, {"GIT_OBJECT_DIRECTORY": str(gitdir / "objects")}),
            "GIT_GRAFT_FILE": (lambda: None, {"GIT_GRAFT_FILE": str(outside)}),
        }
        for name, (apply, env) in attacks.items():
            with self.subTest(attack=name):
                apply()
                before = snapshot(self.repo)  # the entry points, not the attack setup, must write nothing
                try:
                    for call in self.entry_points(forged, env):
                        with self.assertRaises(ContributionError) as caught:
                            call()
                        self.assertEqual(caught.exception.code, "history_unauthenticated")
                        self.assertIsInstance(caught.exception.__cause__, (HistoryError, ForecastError))
                    self.assertEqual(snapshot(self.repo), before)
                finally:
                    for path in (gitdir / "info/grafts", gitdir / "shallow"):
                        path.unlink(missing_ok=True)
                    for ref in git(self.repo, "for-each-ref", "--format=%(refname)", "refs/replace/",
                                   "refs/alt/").split():
                        git(self.repo, "update-ref", "-d", ref)

    def test_rehashed_parent_deletion_or_reorder_is_invalid(self):
        for forged in (rehash_edges(self.edges[:2] + self.edges[3:]),
                       rehash_edges([self.edges[1], self.edges[0], *self.edges[2:]]),
                       rehash_edges(self.edges + [{**self.edges[-1], "parent_ordinal": 2}])):
            with self.assertRaises(ContributionError) as caught:
                self.selector(forged)
            self.assertEqual(caught.exception.code, "edge_table_mismatch")
```

  Add these named cases with exact assertions:
  - `test_hunk_header_digest_change_is_invalid`: one record's `hunk_header_sha256` changed and ids rehashed → `edge_table_mismatch`.
  - `test_assignment_mutations_fail`: unknown, task-zero, duplicate, multiple, owner 7, owner 8, reordered and omitted assignments each raise `ContributionError` from `classify`.
  - `test_forged_or_wrong_key_signature_and_substituted_plan_blob_fail`: an unsigned anchor writer, a writer signed by a second `ssh_signer` key, and a pinned plan blob that differs from the committed one each raise `ContributionError` from `plan_anchors`.
  - `test_late_fix_touching_excluded_path_yields_unavailable_with_that_edge`: in `linear_fixture(tmp, owners=(1, 2, 3, 6, 3), touches={4: 3})` the second Task-3 commit edits the path Task 6 introduced; `tasks-1-3` is `projection_unavailable`, its `failure.evidence_refs` names that commit's edge id and `edge_ids` lists all four selected edges (commits 0, 1, 2 and 4), in order.
  - `test_prerequisite_without_matching_closure_is_unavailable`: in `linear_fixture(tmp, owners=(1, 2, 4, 3, 5, 6))` the Task-4 commit precedes the last Task-3 commit, so no prefix has product closure exactly tasks 1–3; `tasks-4-6` has `failure.code == "prerequisite_composition_unsupported"`. (The default fixture closes tasks 1–3 at commit 4 and cannot force this route.)
  - `test_future_only_boundary_has_prerequisite_tree_and_table_records`: `tasks-7-8` reports `result_tree` equal to the prerequisite tree and records equal to the table's bounds.
  - `test_unavailable_row_with_tree_metrics_or_records_fails_validation`, `test_edge_removed_or_reordered_after_failure_fails_validation`, `test_forged_or_removed_failure_reference_fails`, `test_duplicate_final_record_fails` (a second `records` row with the same `scope` and `path`, id rehashed and referenced), `test_record_refs_resolve_exactly_once` (an unresolved ref, a ref listed twice or by two outcomes, an unreferenced record, a ref to another scope's record, a wrong estimate ref): each mutates the clean, validated `derive_121` payload and expects `ContributionError` from `validate_121`.
  - `test_payload_rows_are_closed`: every outcome row has exactly the parent-spec field set for its `state`.

- [ ] **Step 2: Run the tests and watch them fail.** `PYTHONPATH=python python3 -m unittest tests.test_review_issue121 2>&1 | tail -3` → ImportError for `agent_tools.review_issue121`.

- [ ] **Step 3: Implement the module and support helpers** to the interfaces and invariants above. Wrap every CORE history call at the module boundary; catch `ReconstructionUnavailable` before `ForecastError`.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_issue121 tests.test_review_task7 2>&1 | tail -3
if rg -q 'rev-list|"log"|\^\{tree\}' python/agent_tools/review_issue121.py; then exit 1; fi
grep -q 'tests/test_review_issue121.py' justfile
just agent-workflow-tests 2>&1 | tail -3
```

  At the Task-1 commit the import fails and the `justfile` grep fails, so this gate can fail.

- [ ] **Step 5: Commit.** Stage only the four Files; commit `feat(review): authenticate issue-121 raw history (#248)`.

## Forecast basis

No recovered blob exists; priced per parent D15 from the parent plan's Task-2 estimate, raised for the S9 table (seven attacks at three entry points):
- Module: 590 lines / 30,500 B → 31,602 B (raised for the final-record table and its reference checks); S20 revises it to the measured 35,373 B / +607 plus a fix-round reserve: 37,888 B / +660.
- Test: 590 lines / 32,400 B → 33,502 B (raised for the clean-payload control, the record-reference cases and the two forcing fixtures).
- Support: adds about 150 lines / 7,300 B over Task 1's bound (including the Task-7 seed), cumulative 14,848 B / +280.
- `justfile`: cumulative 2,560 B / +3.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"a0b606d718e51fb3b4391b7fee5c3dbc59b8d176","head":"1230db3f5d86a04c1360092940d61796726606d8"},{"base":"2862f9eac2d740ecb62d8689be3133abf0056ecd","head":"0370c4cf23939e3ca88f94458de30a95043a687b"}],"commit_subject_bytes":[64,64,64,48],"id":2,"records":[{"bounds":[{"added_lines":680,"boundary":"source","deleted_lines":0,"record_bytes":38912,"support":{"covers":["t2-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":590,"boundary":"source","deleted_lines":0,"record_bytes":33502,"support":{"covers":["t2-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-2","last_task":2,"owner":2,"path":"tests/test_review_issue121.py"},{"bounds":[{"added_lines":280,"boundary":"source","deleted_lines":0,"record_bytes":14848,"support":{"covers":["t1-2","t2-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-3","last_task":3,"owner":2,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":3,"boundary":"source","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t1-4","t2-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-4","last_task":3,"owner":2,"path":"justfile"}]}}
```
