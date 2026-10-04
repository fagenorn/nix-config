# Task 3: Derivation and the derive command

Deterministic five-file derivation into a fresh directory, and its thin command (spec § *Derivation and its command*, § *Error codes*; RP4, RP5, RP6, RP9, RP16, RP17).

**Files:**
- Create: `python/agent_tools/review_derivation.py`
- Create: `python/agent_tools/derive_review_feasibility_fixtures.py`
- Create: `tests/test_review_derivation.py`
- Modify: `justfile` (add `tests/test_review_derivation.py \` after `tests/test_review_witness.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes (Task 2, `agent_tools.review_witness`): `WitnessError`, `ANCHOR_NAME`, `PAYLOAD_NAMES`, `MEMBER_MAX_BYTES`, `tool_closure(tool_repo, tool_commit) -> dict` (`{commit, files}`), `verify_running_closure(closure) -> None`, `build_witness(components, payloads, raw) -> dict` (keyed by the three fixture names), `build_anchor(components, raw) -> dict` (keyed by the four `PAYLOAD_NAMES`), `validate_bundle(anchor, raw, *, task7_pins, issue121_pins, issue100_pins) -> dict[str, dict]`.
- Consumes (SOURCE): `derive_task7(repo, pins)`, `derive_121(repo, pins, task7_pins, authority)`, `derive_100(issue_repo, live_repo, archive_dir, pins, limits)`, `verify_archive(archive_dir, issue_repo, pins)`, the errors `EstimateError`, `ContributionError`, `Issue100Error` (each with `code`) and the constants `TASK7_PINS`, `ISSUE_121_PINS`, `ISSUE_100_PINS`.
- Consumes (CORE): `review_budget.describe`, `BudgetAuthority`, `BudgetError`; `review_forecast.canonical_bytes`, `raw_digest`; `review_actual.PACKING_POLICY_SHA256`, `RECORD_POLICY_SHA256`, `_run_git`; `agent_tools.canonical.telemetry_digest`.
- Consumes (support): `retained_fixture(tmp, **shape) -> (issue_121_repo, issue_100_repo, archive_dir, (task7_pins, issue121_pins, issue100_pins))` with everything under `tmp/repos/`; `tool_fixture(tmp) -> (tool_repo, tool_commit)`; `snapshot(repo)`; `source_budget_env(tmp)`; `git`.
- Produces (`review_derivation`):
  - `@dataclass(frozen=True) DeriveInputs(issue_121_repo: Path, issue_100_repo: Path, archive_dir: Path, tool_repo: Path, tool_commit: str, output_dir: Path)`.
  - `class DerivationError(Exception)` with `code`; an undeclared code raises `ValueError`. Codes: `invalid_inputs, output_exists, output_aliases_input, member_oversize`.
  - `derive_bundle(inputs: DeriveInputs, *, task7_pins, issue121_pins, issue100_pins, authority: BudgetAuthority) -> dict`: `{anchor_sha256, members}`, members being all five files in path order as `{path, bytes, raw_sha256}` with bare 64-hex digests.
- Produces (`derive_review_feasibility_fixtures`): `main(argv=None) -> int`, parser `prog="derive-review-feasibility-fixtures"`, exactly the six required options `--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`, `--tool-commit`, `--output-dir`, and no other option.

**Invariants:**
- `derive_bundle` follows the spec's seven steps in order. Step 1 detail: an input that is not a directory, a `--tool-commit` that is not 40 lowercase hex, or a repository whose `git rev-parse --git-common-dir` fails is `invalid_inputs`. The output is refused before any Git object is read.
- Aliasing compares resolved paths: the output's resolved parent joined with its name must not equal, be inside, or contain any of the four input paths or the three repositories' common Git directories.
- Components (RP16), each computed once: `tool` = the verified closure plus `authority.policy_sha256` and CORE's two policy constants; `issue_121` = pins `base`, `head`, `task7_pins.prerequisite_tree` and `raw_digest(issue121_pins.allowed_signer)`; `issue_100` = pins `base`, `head`, `live`, `parent_edges_sha256`; `archive` = `verify_archive`'s result unchanged; `estimate` = the five Task-7 pin members plus `telemetry_digest(table)`.
- `derive_task7` runs first and any `EstimateError` propagates (RP5). `derive_100` receives `issue_100_repo` twice (RP4) and `authority.limits`.
- Scratch is one `tempfile.mkdtemp(dir=output_dir.parent, prefix=".derive-")`; the single `os.rename` to `output_dir` follows `validate_bundle`; a `finally` removes the scratch if it still exists. No before/after input snapshot is taken (RP6).
- Outputs are `canonical_bytes` only. No path, clock, hostname, locale or environment value is written.
- The command only parses, calls `describe("review-package")` and `derive_bundle` with the three real pin constants, writes `canonical_bytes(summary)` to stdout and returns 0. It catches exactly: the parser's raised usage error → `usage`; `DerivationError`, `WitnessError`, `EstimateError`, `ContributionError`, `Issue100Error` → their `code`; `BudgetError` → `budget_unavailable`; `OSError` → `io_error`. Each prints `derive-review-feasibility-fixtures: invalid: <code>` to stderr, nothing to stdout, and returns 2. Any other exception propagates (RP8).

- [ ] **Step 1: Write the failing tests** in `tests/test_review_derivation.py`.

```python
class DerivationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        repo121, repo100, archive, cls.pins = retained_fixture(cls.tmp)
        tool_repo, tool_commit = tool_fixture(cls.tmp)
        cls.inputs = DeriveInputs(repo121, repo100, archive, tool_repo, tool_commit, cls.tmp / "unused")
        with patch.dict(os.environ, source_budget_env(cls.tmp), clear=True):
            cls.authority = describe("review-package")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def derive(self, out, **changed):
        pins = dict(zip(("task7_pins", "issue121_pins", "issue100_pins"), self.pins), **changed)
        return derive_bundle(replace(self.inputs, output_dir=out), authority=self.authority, **pins)

    def state(self):
        repos = (self.inputs.issue_121_repo, self.inputs.issue_100_repo, self.inputs.tool_repo)
        archive = {p.relative_to(self.inputs.archive_dir): p.read_bytes()
                   for p in self.inputs.archive_dir.rglob("*") if p.is_file()}
        return tuple(snapshot(repo) for repo in repos), archive

    def leftovers(self):
        return sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(".derive-"))

    def test_two_derivations_are_byte_identical_and_inputs_unchanged(self):
        before = self.state()
        a, b = self.tmp / "a", self.tmp / "b"
        self.assertEqual(self.derive(a), self.derive(b))
        files = {p.name: p.read_bytes() for p in a.iterdir()}
        self.assertEqual(files, {p.name: p.read_bytes() for p in b.iterdir()})
        self.assertEqual(set(files), {ANCHOR_NAME, *PAYLOAD_NAMES})
        self.assertEqual((self.state(), self.leftovers()), (before, []))

    def test_failing_pin_leaves_no_output_no_scratch_and_unchanged_inputs(self):
        before = self.state()
        bad = replace(self.pins[2], producer_sha256="0" * 64)
        with self.assertRaises(Issue100Error) as caught:
            self.derive(self.tmp / "c", issue100_pins=bad)
        self.assertEqual(caught.exception.code, "archive_digest_mismatch")
        self.assertFalse((self.tmp / "c").exists())
        self.assertEqual((self.state(), self.leftovers()), (before, []))
```

  Add these named cases with exact assertions; every refusal also asserts `leftovers() == []`, no output path, and `state()` unchanged. One of them, `test_publication_failure_removes_scratch`, patches `os.rename` in the derivation module to raise `OSError` (a failure after the scratch exists) and asserts the same three facts through `derive_bundle`, and exit 2 with `invalid: io_error` through `main`:
  - `test_summary_names_the_written_bundle`: `anchor_sha256 == telemetry_digest` of the decoded anchor file; `members` lists the five names sorted, each row's `bytes` and `raw_sha256` equal to the file; every file equals `canonical_bytes` of its decoded value.
  - `test_existing_or_dangling_output_is_output_exists`: an existing directory, an existing file, a dangling symlink, and an output whose parent is missing; the existing entries are untouched.
  - `test_aliasing_output_is_refused`: outputs `issue_121_repo/"out"`, `archive_dir/"out"`, `issue_100_repo/".git"/"out"`, and, with `tool_repo` replaced by a `git worktree add` checkout of the tool fixture, an output inside the tool fixture's `.git` → `output_aliases_input` each.
  - `test_invalid_inputs`: a 39-hex and an uppercase `tool_commit`; a file as `archive_dir`; a plain directory as `tool_repo` → `invalid_inputs`.
  - `test_mismatched_running_closure_is_refused`: a second commit in a copy of the tool fixture changes one byte of one module → `WitnessError` with code `tool_closure`.
  - `test_estimate_pin_fault_is_fatal`: `task7_pins` with `prerequisite_tree="0" * 40` → `EstimateError`; no bundle (RP5).
  - `test_oversized_member_is_refused`: under `patch("agent_tools.review_derivation.MEMBER_MAX_BYTES", 64)` → `DerivationError` with code `member_oversize` (RP17).
  - `test_outputs_hold_no_scratch_or_home_path`: no output file contains `str(self.tmp)`, `os.environ["HOME"]` or `os.getcwd()` as bytes.
  - `test_command_missing_option_is_usage`: `sys.executable -m agent_tools.derive_review_feasibility_fixtures` with each one of the six options omitted in turn, and with all six plus `--pin x`, `env=source_budget_env(tmp)` → `(2, b"", b"derive-review-feasibility-fixtures: invalid: usage\n")` each.
  - `test_command_refuses_an_existing_output_dir`: all six options, an existing empty output → exit 2, empty stdout, `invalid: output_exists`, directory still empty.
  - `test_command_without_a_budget_helper_is_budget_unavailable`: the same call with `PATH` set to an empty directory and a fresh output path → `invalid: budget_unavailable`; no output.

- [ ] **Step 2: Run and watch them fail.** `PYTHONPATH=python python3 -m unittest tests.test_review_derivation 2>&1 | tail -3` → `ImportError` (no `agent_tools.review_derivation`).

- [ ] **Step 3: Implement** the library, then the command. Docstrings state implemented behaviour in present tense.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_derivation tests.test_review_witness 2>&1 | tail -3
if grep -Eq 'import_module|__file__|sys\.path' \
    python/agent_tools/review_derivation.py python/agent_tools/derive_review_feasibility_fixtures.py; then exit 1; fi
grep -q 'tests/test_review_derivation.py' justfile
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  At the starting commit the focused suite and the `justfile` grep fail.

- [ ] **Step 5: Commit.** Stage only the four Files; subject at most 64 bytes: `feat(review): derive retained review bundles (#249)`. A review-fix commit uses `fix(review): address Task-3 review findings (#249)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence`, then renew G0 at `--completed-through 3` (RP14).

## Forecast basis

Parent D15 price plus about ten percent:
- Library: 280 lines / 14,000 B → 14,792 → 16,384 B / +310.
- Command: 80 lines / 3,400 B → 3,992 → 4,608 B / +90.
- Test: 310 lines / 16,500 B → 17,322 → 19,456 B / +340.
- `justfile`: second cumulative contribution, the same hunk → 2,560 B / +2.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"ea8ec47c75012a6e95867795d71e8c566aee03cc","head":"c9df07df2e4d1412d6d7e625eaf088ba33ea7217"},{"base":"5b241d3445114a97c9d450c4cbf10abf8043764a","head":"5893dbb58dadcbdf449e4399c3a6d3061160e917"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":310,"boundary":"replay","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t3-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-1","last_task":3,"owner":3,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":90,"boundary":"replay","deleted_lines":0,"record_bytes":4608,"support":{"covers":["t3-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-2","last_task":3,"owner":3,"path":"python/agent_tools/derive_review_feasibility_fixtures.py"},{"bounds":[{"added_lines":340,"boundary":"replay","deleted_lines":0,"record_bytes":19456,"support":{"covers":["t3-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3-3","last_task":3,"owner":3,"path":"tests/test_review_derivation.py"},{"bounds":[{"added_lines":2,"boundary":"replay","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t2-4","t3-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-4","last_task":6,"owner":3,"path":"justfile"}]}}
```
