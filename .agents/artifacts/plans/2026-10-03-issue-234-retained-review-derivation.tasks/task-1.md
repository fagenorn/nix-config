# Task 1: Task-7 estimate model and Task-8 effect

**Files:**
- Create: `python/agent_tools/review_task7.py`
- Create: `tests/retained_review_test_support.py` (shared portable fixtures, per D12)
- Create: `tests/test_review_task7.py`
- Modify: `justfile` (append `tests/test_review_task7.py` to `agent-workflow-tests`)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`LEGACY_MIGRATION_INPUTS` entries for `review_task7.py` and its test)

**Interfaces:**
- Consumes (CORE, base `93e6059`): `review_actual.RECORD_POLICY`, `PACKING_POLICY_SHA256`, `actual_inputs_from_trees(repo, base_tree, head_tree, *, base, head, commits, package_name, limits)`, `select_candidate(inputs, limits, *, transform=None, measurement_only=False)`; `review_budget.describe("review-package") -> BudgetAuthority` (`.limits`, `.policy_sha256`); `review_forecast.history_commit`, `tree_entry`, `canonical_bytes`, `strict_json`; `agent_tools.canonical.telemetry_digest`.
- Produces:
  - `class EstimateError(Exception)` with attribute `code: str` (`unsupported_estimate`, `unsupported_composition`, `invalid_table`, `inventory_mismatch`).
  - `@dataclass(frozen=True) RendererSpec(target: str, renderer_path: str, renderer_blob: str, fixed_bytes: int, fixed_lines: int, fields: tuple[tuple[str, int, int], ...])`. Each field is `(name, count, max_encoded_bytes)`.
  - `@dataclass(frozen=True) Task7Pins(prerequisite_commit: str, prerequisite_tree: str, plan_root_blob: str, task7_blob: str, model_version: str, subject_template: str, move_roots: tuple[tuple[str, str, str], ...], renderers: tuple[RendererSpec, ...], project_id_max_bytes: int)`. Each move root is `(old_prefix, new_prefix, class)`, where class is one of `spec`, `plan` or `decision`.
  - `TASK7_PINS: Task7Pins`, holding the real values: commit `fe85677c8bd26c808ac69c2ee21b17ff6e262923`, its tree, blobs `8294252b…` and `c8c622dd…`, the adopt tool sources at `fe85677c` (`adopt-project.py`, `adopt_apply.py`, `adopt_inspection.py`, `adopt_planning.py`, `adopt_verify.py`, `agent_platform.py`, `resolve-project.py`, `platform-manifest.json`), and the subject template `chore(adopt): adopt <project_id> at plan <12-char fragment>`.
  - `TASK8_EFFECT = {"task": 8, "repository_bytes": 0, "state": "unexecuted", "acceptance": "post-integration-registration-evidence"}`.
  - `derive_task7(repo: Path, pins: Task7Pins) -> dict`, which returns the `task7-estimate/v1` table. Its keys are `schema_version`, `kind`, `identities` (with `rules`, `move_roots` and `tool_closure`), `subject`, `rows`, `rows_sha256` (the `telemetry_digest` of `rows`), `counts`, `historical_scope`, `projection_estimate` and `observed_actual` (always `null`).
  - `validate_task7(table: dict, pins: Task7Pins) -> None`.
  - `compose(repo: Path, table: dict, pins: Task7Pins, *, base_tree: str, final_tree: str, limits) -> tuple[dict, ...]`. It returns rows `{path, record_bytes, added_lines, deleted_lines}` sorted by path.
  - Row shape (compact, D18): a move is `{operation, new_path, input, record_bytes}`; a write or add is `{operation, new_path, input, facts, output, record_bytes}`, where `facts.renderers` lists only the contributing specs (blobs live in `identities.renderers`). A move's old path, class and rule are re-derived from `identities.move_roots` and `identities.rules`, and its output is its input. The real table's canonical bytes are at most 49,152.

**Invariants:**
- Rows are derived from `pins.prerequisite_tree` and the typed rules only. The table covers exactly 173 unique final paths, with counts 165/54/108/3/5/3 (D4). `counts` is recomputed from `rows` and never authored.
- Every integer is a non-Boolean `int`. No multiplier, percentage reserve or unexplained ceiling appears anywhere.
- A move needs equal blob and mode. Its bound is the exact R100 header text (`diff --git`, `similarity index 100%`, `rename from`, `rename to`) with Git C-style quoting of both paths. When identical blobs admit several pairings, each destination takes the maximum over compatible sources.
- A write or add bounds the full delete/add record: Git and hunk headers, every line prefix, and the no-newline markers. That bound is computed from the `RendererSpec` fixed portion plus `count × max_encoded_bytes` for each field. A missing renderer or field, or a count or maximum that is not an int, raises `EstimateError("unsupported_estimate")`.
- The project identity is labelled `authored-estimate` with `max_encoded_bytes` only. No project contract is read (D4). Unknown digests in paths are 64-hex placeholders, charged at full length.
- `compose` works in a disposable scratch repository whose `objects/info/alternates` names the source object store read-only, as CORE's `reconstruct_owned` does (D17). It relocates moves there as exact blobs, writes and measures every tree there with the shared builder, and removes the scratch repository only after measuring. A write takes the larger of (measured removal plus output bound) and the observed record. Anything else raises `unsupported_composition`. The source repository's refs, index and object contents stay unchanged.

- [ ] **Step 1: Write the shared portable support module.** `tests/retained_review_test_support.py` exports these helpers, all on real Git:
  - `git(repo, *args, env=None) -> str`
  - `init_repo(tmp) -> Path`, with fixed author/committer dates and `commit.gpgsign=false` unless signing is enabled
  - `commit_files(repo, files: dict[str, bytes|None], message, *, sign_key=None) -> str`
  - `ssh_signer(tmp) -> tuple[Path, bytes]`, which generates an ephemeral key with `ssh-keygen -t ed25519 -N ''` and returns the key and its allowed-signers line
  - `HOSTILE_GIT_ENV: dict[str, str]`, which sets `GIT_CONFIG_COUNT` entries for `diff.renames=copies`, `diff.renameLimit=1`, `core.quotePath=false`, `diff.noprefix=true`, `diff.mnemonicPrefix=true`, `color.ui=always` and `diff.external=false`
  - `snapshot(repo) -> tuple`, which captures refs (`for-each-ref`), the index digest, `status --porcelain=v2`, and a sorted `(path, sha256)` for every file under the repository directory, `.git` included (D17). Its Git reads run with `GIT_OPTIONAL_LOCKS=0`, so collecting it writes nothing
  - `source_budget_env(tmp) -> dict`, which stages `HOME/.agents/lib/python/artifact_budget.py` and the policy from `home/common/agent-skills/` and puts the source `scripts/` directory on `PATH`, as `tests/test_review_feasibility.py` does. Tests call `describe("review-package")` under `patch.dict(os.environ, env, clear=True)`; the installed helper lacks `describe` until a switch
- [ ] **Step 2: Write the failing tests.** These go in `tests/test_review_task7.py` (import with `from .retained_review_test_support import ...`).

```python
class Task7ModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.pins = fixture_pins(self.tmp)   # 2 specs, 3 plans, 1 decision, 5 rewrite targets

    def test_counts_are_recomputed_and_exact(self):
        table = derive_task7(self.repo, self.pins)
        self.assertEqual(table["counts"], {"paths": 14, "moves": 6, "specs": 2, "plans": 3,
                                           "decisions": 1, "rewrites": 5, "additions": 3})
        self.assertIsNone(table["observed_actual"])
        validate_task7(table, self.pins)

    def test_removing_a_field_bound_is_unsupported(self):
        broken = replace(self.pins, renderers=self.pins.renderers[:-1])
        with self.assertRaises(EstimateError) as caught:
            derive_task7(self.repo, broken)
        self.assertEqual(caught.exception.code, "unsupported_estimate")

    def test_rehashed_fact_change_is_invalid(self):
        table = derive_task7(self.repo, self.pins)
        row = dict(table["rows"][0]); row["output"] = {**row["output"], "bytes": 1}
        rows = [row, *table["rows"][1:]]
        forged = {**table, "rows": rows, "rows_sha256": telemetry_digest(rows)}
        with self.assertRaises(EstimateError):
            validate_task7(forged, self.pins)

    def test_real_producer_stays_within_bounds_under_hostile_config(self):
        table = derive_task7(self.repo, self.pins)
        after = apply_fixture_adoption(self.repo, self.pins, env=HOSTILE_GIT_ENV)  # moves, quoted/non-ASCII paths, all rewrites/adds at field maxima
        observed = measured_records(self.repo, self.pins.prerequisite_commit, after)
        for row in table["rows"]:
            self.assertLessEqual(observed[row["new_path"]], row["record_bytes"], row["new_path"])
```

  Add these named cases with exact assertions:
  - `test_duplicate_blob_destinations_take_maximum`: two sources share one blob, and both destination bounds equal the larger pairing.
  - `test_unequal_mode_move_is_invalid`
  - `test_inventory_with_extra_or_missing_move_root_path_raises_inventory_mismatch`
  - `test_bool_count_is_invalid`
  - `test_compose_over_foreign_final_tree_measures_moves_and_leaves_source_unchanged`: `snapshot` is equal before and after.
  - `test_compose_unexpressible_raises_unsupported_composition`
  - `test_task8_effect_is_fileless_and_unexecuted`
- [ ] **Step 3: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_task7.py`. The expected result is an ImportError for `agent_tools.review_task7`.
- [ ] **Step 4: Implement the minimal module.** Implement the interfaces above. Derive the real `RendererSpec`s and move roots by reading the pinned renderer blobs and the signed Task-7 brief (`git cat-file -p c8c622dd…` in the primary checkout's object store). Record each field's source function in the row's `facts`. Use `canonical_bytes` and `telemetry_digest` only; per D4, apply no reserve.
- [ ] **Step 5: Verify.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_task7.py` and expect every case to pass. Then run `just agent-workflow-tests`; the summary line must show zero failures. To confirm the gate can fail: before Step 4, `grep -c review_task7 justfile` prints `0`.
- [ ] **Step 6: Commit.** Stage only the four files above and commit `feat(review): model the Task-7 estimate and Task-8 effect (#234)`.

## Forecast basis

All forecasts are estimates per D15 (lines × bytes + one prefix byte per line + 512):

| Path | Estimate |
|---|---|
| `review_task7.py` | 500 lines / 26,000 B → 27,012 |
| `tests/retained_review_test_support.py` | 240 / 12,500 → 13,252 |
| `tests/test_review_task7.py` | 380 / 21,000 → 21,892 |

`justfile` is the first of seven ordered cumulative contributions (horizon 8). Its U10 record is 2,048 B / +2. The contracts-test record is 2,560 B / +4 (measured 1,763 B). The support module is the first of four contributions (horizon 5).

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":500,"boundary":"derive","deleted_lines":0,"record_bytes":27012,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_task7.py"},{"bounds":[{"added_lines":240,"boundary":"derive","deleted_lines":0,"record_bytes":13252,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-2","last_task":5,"owner":1,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":380,"boundary":"derive","deleted_lines":0,"record_bytes":21892,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-3","last_task":1,"owner":1,"path":"tests/test_review_task7.py"},{"bounds":[{"added_lines":2,"boundary":"derive","deleted_lines":0,"record_bytes":2048,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-4","last_task":8,"owner":1,"path":"justfile"},{"bounds":[{"added_lines":4,"boundary":"derive","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-5","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
