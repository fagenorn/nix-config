# Task 5: Derivation and the derive command

**Files:**
- Create: `python/agent_tools/review_derivation.py`
- Create: `python/agent_tools/derive_review_feasibility_fixtures.py`
- Create: `tests/test_review_derivation.py`
- Modify: `tests/retained_review_test_support.py` (add `derivation_fixture` and `tool_fixture`; fourth and final contribution)
- Modify: `justfile` (append `tests/test_review_derivation.py` to `agent-workflow-tests`)

**Interfaces:**
- Consumes:
  - From Task 1: `derive_task7`, `validate_task7`, `TASK7_PINS`, `EstimateError`.
  - From Task 2: `derive_121`, `validate_121`, `ISSUE_121_PINS`, `ContributionError`.
  - From Task 3: `derive_100`, `validate_100`, `ISSUE_100_PINS`, `Issue100Error`.
  - From Task 4: `tool_closure`, `verify_running_closure`, `build_witness`, `build_anchor`, `validate_witness`, `ANCHOR_NAME`, `PAYLOAD_NAMES`, `WitnessError`.
  - From CORE: `review_budget.describe`, `BudgetError`, `canonical_bytes`, `telemetry_digest`.
  - From the support module: `snapshot`, `source_budget_env`, `linear_fixture`, `task7_fixture`, `issue100_fixture`.
- Produces:
  - `@dataclass(frozen=True) DeriveInputs(issue_121_repo: Path, issue_100_repo: Path, archive_dir: Path, tool_repo: Path, tool_commit: str, output_dir: Path)`.
  - `class DerivationError(Exception)` with `code: str`.
  - `derive_bundle(inputs: DeriveInputs, *, task7_pins, issue121_pins, issue100_pins, authority) -> dict`. It returns the summary `{anchor_sha256, members: [{path, bytes, raw_sha256}]}`, with members sorted by path over all five files.
  - `INVALID = (DerivationError, EstimateError, ContributionError, Issue100Error, WitnessError, BudgetError, OSError, ValueError)`, so the error tuple is shared rather than restated.
  - Command `derive_review_feasibility_fixtures.main(argv=None) -> int`, with parser `prog="derive-review-feasibility-fixtures"`. It requires `--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`, `--tool-commit` (a full 40-hex SHA) and `--output-dir`, and offers no pin override (D12). On success it writes `canonical_bytes(summary)` to stdout and exits 0. Any invalid input exits 2 with one stderr line, `derive-review-feasibility-fixtures: invalid: <code>`, and empty stdout. The parser's `error` raises rather than exits, as `review_feasibility._Parser` does.

**Invariants:**
- The output directory must not exist. Its resolved path must not equal, contain or lie inside any input path (`Path.resolve` plus `is_relative_to` both ways).
- Scratch is one `tempfile.mkdtemp(dir=output_dir.parent, prefix=".derive-")`. Every file is written there, and the directory is renamed to `output_dir` only after all validation passes. A `finally` removes the scratch on every outcome, so a failure leaves no output directory.
- `snapshot` of each input repository and a byte map of the archive are taken before and compared after, on both success and failure. A difference raises `DerivationError("input_mutated")`.
- Order follows the spec ("Construction is acyclic"):
  1. Run `verify_running_closure(tool_closure(...))`.
  2. Build the table, then the issue-121 payload, then the issue-100 payload.
  3. Run each module's `validate_*` (D11).
  4. Build and validate the witness.
  5. Write the anchor last.
- Output is deterministic: canonical ASCII-LF bytes, sorted members, and no clock, locale, temporary path or environment value inside any output. Two runs into fresh directories give byte-identical files.
- The command module only parses, reads, calls, writes and maps exits (agent-helper standard 2).

- [ ] **Step 1: Write the failing tests.** These go in `tests/test_review_derivation.py` and use fixture pins assembled from the support module. The support module gains two helpers. `tool_fixture(tmp)` commits a copy of the running `python/agent_tools/` bytes into a fixture tool repository. `derivation_fixture(tmp)` puts every input repository and the archive under `tmp/repos` and returns `(DeriveInputs, (task7, issue121, issue100) pins)`.

```python
class DerivationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.inputs, self.pins = derivation_fixture(self.tmp)   # DeriveInputs + (task7, 121, 100) pins
        with patch.dict(os.environ, source_budget_env(self.tmp), clear=True):
            self.authority = describe("review-package")

    def run_derive(self, out):
        return derive_bundle(replace(self.inputs, output_dir=out), task7_pins=self.pins[0],
                             issue121_pins=self.pins[1], issue100_pins=self.pins[2], authority=self.authority)

    def test_two_derivations_are_byte_identical(self):
        a, b = self.tmp / "a", self.tmp / "b"
        self.assertEqual(self.run_derive(a), self.run_derive(b))
        self.assertEqual({p.name: p.read_bytes() for p in a.iterdir()},
                         {p.name: p.read_bytes() for p in b.iterdir()})

    def test_existing_or_aliasing_output_is_refused_and_leaves_nothing(self):
        for out in (self.inputs.archive_dir, self.inputs.issue_121_repo / "out"):
            with self.assertRaises(DerivationError):
                self.run_derive(out)
        self.assertFalse((self.inputs.issue_121_repo / "out").exists())

    def test_failure_leaves_no_output_and_inputs_unchanged(self):
        before = snapshot(self.inputs.issue_121_repo)
        bad = replace(self.pins[2], producer_sha256="0" * 64)
        with self.assertRaises(Issue100Error):
            derive_bundle(replace(self.inputs, output_dir=self.tmp / "c"), task7_pins=self.pins[0],
                          issue121_pins=self.pins[1], issue100_pins=bad, authority=self.authority)
        self.assertFalse((self.tmp / "c").exists())
        self.assertEqual(list(self.tmp.glob(".derive-*")), [])
        self.assertEqual(snapshot(self.inputs.issue_121_repo), before)
```

  Add these named cases with exact assertions:
  - `test_tool_commit_mismatch_is_refused`
  - `test_outputs_contain_no_scratch_path_or_home`: no output contains `str(self.tmp)` or `os.environ["HOME"]`.
  - `test_command_requires_every_argument`: run via `subprocess` with `python -m agent_tools.derive_review_feasibility_fixtures`; expect exit 2, empty stdout and the `invalid:` stderr prefix.
  - `test_command_refuses_existing_output_dir`: exit 2.
- [ ] **Step 2: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests/test_review_derivation.py`. The expected result is an ImportError.
- [ ] **Step 3: Implement the module and the command.** Implement the interfaces above. The command passes `TASK7_PINS`, `ISSUE_121_PINS`, `ISSUE_100_PINS` and `describe("review-package")`.
- [ ] **Step 4: Verify.** The focused command must pass, and `just agent-workflow-tests` must report zero failures. To confirm the check can fail: `PYTHONPATH=python python3 -m agent_tools.derive_review_feasibility_fixtures` exits 1 (no module) before Step 3 and exits 2 after it.
- [ ] **Step 5: Commit.** Stage only these five files and commit `feat(review): derive retained review bundles (#234)`.

## Forecast basis

Estimates per D15:
- Module: 280 lines / 14,000 B → 14,792.
- Command: 80 lines / 3,400 B → 3,992.
- Test: 260 lines / 14,500 B → 15,272.
- Support module: fourth contribution, adding 60 lines / 3,500 B for a cumulative 29,532 B / +520.
- `justfile`: fifth contribution, with a cumulative 4,096 B / +6.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":5,"records":[{"bounds":[{"added_lines":280,"boundary":"derive","deleted_lines":0,"record_bytes":14792,"support":{"covers":["t5-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5-1","last_task":5,"owner":5,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":80,"boundary":"derive","deleted_lines":0,"record_bytes":3992,"support":{"covers":["t5-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5-2","last_task":5,"owner":5,"path":"python/agent_tools/derive_review_feasibility_fixtures.py"},{"bounds":[{"added_lines":260,"boundary":"derive","deleted_lines":0,"record_bytes":15272,"support":{"covers":["t5-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5-3","last_task":5,"owner":5,"path":"tests/test_review_derivation.py"},{"bounds":[{"added_lines":520,"boundary":"derive","deleted_lines":0,"record_bytes":29532,"support":{"covers":["t1-2","t2-3","t3-3","t5-4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5-4","last_task":5,"owner":5,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":6,"boundary":"derive","deleted_lines":0,"record_bytes":4096,"support":{"covers":["t1-4","t2-4","t3-4","t4-3","t5-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t5-5","last_task":8,"owner":5,"path":"justfile"}]}}
```
