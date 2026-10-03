# Task 4: Witness, anchor and tool closure

**Files:**
- Create: `python/agent_tools/review_witness.py`
- Create: `tests/test_review_witness.py`
- Modify: `justfile` (append `tests/test_review_witness.py` to `agent-workflow-tests`)

**Interfaces:**
- Consumes (CORE): `review_forecast.canonical_bytes`, `strict_json`, `read_regular`, `committed_bytes`, `tree_entry`, `full_commit`; `review_forecast._derivation` is the loader this anchor must satisfy, per D3; `agent_tools.canonical.telemetry_digest`. It also consumes the support module's `init_repo`, `commit_files` and `snapshot`.
- Produces:
  - `class WitnessError(Exception)` with `code: str`.
  - `ANCHOR_NAME = "derivation-anchor.json"`.
  - `PAYLOAD_NAMES = ("derivation-witness.json", "issue-100-derived.json", "issue-121.json", "task7-estimate.json")`.
  - `ANCHOR_MAX_BYTES`, a module constant that the implementer sizes from the real anchor and documents.
  - `tool_closure(tool_repo: Path, tool_commit: str) -> dict`, giving `{commit, files: [{path, blob, raw_sha256}]}`. The files are every blob under `python/agent_tools/` at the commit, sorted by path.
  - `verify_running_closure(closure: dict) -> None`, which compares each file's bytes, read through `importlib.resources.files("agent_tools")`, with the closure (D6). It never imports or loads a module by path.
  - `build_witness(components: dict, fixtures: dict, tables: dict, table_policies: dict) -> dict`, giving the version-2 keys `schema_version`, `kind`, `components`, `fixtures`, `tables` and `table_policies`.
  - `build_anchor(components: dict, payload_raw: Mapping[str, bytes]) -> dict`, giving keys `schema_version` (2), `kind` (`review-feasibility-derivation-anchor`), `tool`, `issue_121`, `issue_100`, `archive`, `estimate` and `payload{encoding: "canonical-json-ascii-lf/v1", members: [{path, bytes, raw_sha256}]}`.
  - `authenticate(bundle_dir: Path, expected_anchor_sha256: str) -> tuple[dict, dict[str, bytes]]`, which performs replay steps 1–2.
  - `validate_witness(witness: dict, anchor: dict) -> None`.

**Invariants:**
- Construction is acyclic. The witness holds no anchor identity and no digest of itself. The anchor is built last, over the raw bytes of the four payloads.
- `authenticate` follows a fixed order:
  1. Read the anchor with `read_regular` under `ANCHOR_MAX_BYTES`, strictly decode it, require canonical bytes, and compare `telemetry_digest(anchor)` with the expected `sha256:HEX`.
  2. Require the directory to hold exactly five regular, non-symlinked entries named `ANCHOR_NAME` plus `PAYLOAD_NAMES`. Check each member's byte length and SHA-256, using the anchor's declared `bytes` as the read limit, before anything decodes it.

  A missing, extra, symlinked or traversing member raises `WitnessError`.
- The witness `components` equal the anchor's five provenance groups exactly. `table_policies` maps every raw-record table.
- An anchor that `build_anchor` produces passes CORE's `_derivation` loader when it is committed beside the four payloads. A test proves this against the real loader.
- `tool_closure` reads blobs with `git ls-tree -r -z` and `git cat-file` at the full commit only. The output directory and test scratch lie outside the closure.

- [ ] **Step 1: Write the failing tests.** These go in `tests/test_review_witness.py`. `bundle(tmp)` writes four small canonical payloads, a witness and an anchor via the module.

```python
class WitnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.dir, self.expected = bundle(self.tmp)

    def test_member_bytes_are_bound_before_decode(self):
        (self.dir / "issue-121.json").write_bytes(b"{not json")
        with self.assertRaises(WitnessError) as caught:
            authenticate(self.dir, self.expected)
        self.assertEqual(caught.exception.code, "member_digest")

    def test_replacement_anchor_against_unchanged_digest_fails(self):
        anchor = json.loads((self.dir / ANCHOR_NAME).read_bytes())
        anchor["tool"] = {**anchor["tool"], "commit": "0" * 40}
        (self.dir / ANCHOR_NAME).write_bytes(canonical_bytes(anchor))
        with self.assertRaises(WitnessError):
            authenticate(self.dir, self.expected)

    def test_core_loader_accepts_committed_anchor(self):
        repo = init_repo(self.tmp / "r")
        files = {f"fx/{p.name}": p.read_bytes() for p in self.dir.iterdir()}
        head = commit_files(repo, files, "bundle")
        anchor = json.loads(files["fx/" + ANCHOR_NAME])
        _derivation(repo, head, {"kind": "retained-anchor/v2", "path": "fx/" + ANCHOR_NAME,
                                 "anchor_sha256": telemetry_digest(anchor)})
```

  Add these named cases with exact assertions:
  - `test_missing_extra_symlinked_member_fails`
  - `test_traversing_member_name_fails`
  - `test_oversized_anchor_fails_before_decode`
  - `test_witness_component_mismatch_fails`
  - `test_witness_carrying_anchor_identity_fails`
  - `test_tool_closure_is_sorted_and_complete`, against a fixture repository with a `python/agent_tools/` tree.
  - `test_running_closure_mismatch_fails`, using a closure whose one `raw_sha256` differs.
- [ ] **Step 2: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_witness.py`. The expected result is an ImportError.
- [ ] **Step 3: Implement the module.** Implement the interfaces above. Error codes are short slugs, among them `anchor_digest`, `member_set`, `member_digest`, `noncanonical`, `component_mismatch` and `tool_closure`.
- [ ] **Step 4: Verify.** The focused command must pass, and `just agent-workflow-tests` must report zero failures. To confirm the check can fail: before Step 3, `grep -c review_witness justfile` prints `0`.
- [ ] **Step 5: Commit.** Stage only these three files and commit `feat(review): anchor retained bundles acyclically (#234)`.

## Forecast basis

Estimates per D15:
- Module: 300 lines / 15,000 B → 15,812.
- Test: 260 lines / 14,500 B → 15,272.
- `justfile`: fourth contribution, with a cumulative 3,584 B / +5.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":300,"boundary":"derive","deleted_lines":0,"record_bytes":15812,"support":{"covers":["t4-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-1","last_task":4,"owner":4,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":260,"boundary":"derive","deleted_lines":0,"record_bytes":15272,"support":{"covers":["t4-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-2","last_task":4,"owner":4,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":5,"boundary":"derive","deleted_lines":0,"record_bytes":3584,"support":{"covers":["t1-4","t2-4","t3-4","t4-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t4-3","last_task":8,"owner":4,"path":"justfile"}]}}
```
