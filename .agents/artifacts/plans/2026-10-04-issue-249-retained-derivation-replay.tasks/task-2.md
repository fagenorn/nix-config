# Task 2: Tool closure, witness, anchor and bundle validation

The bundle contract in one module: spec § *Tool closure*, § *Witness and anchor*, § *Replay and its command* steps 1–3 and § *Error codes* bind in full (RP2, RP3, RP7, RP8, RP16).

**Files:**
- Create: `python/agent_tools/review_witness.py`
- Create: `tests/test_review_witness.py`
- Modify: `tests/retained_review_test_support.py` (add `retained_fixture` and `tool_fixture`)
- Modify: `justfile` (add `tests/test_review_witness.py \` after `tests/test_review_issue100.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes (CORE): `review_forecast.canonical_bytes`, `strict_json`, `read_regular(directory, relative, limit)`, `full_commit`, `raw_digest`, `ForecastError`, and in tests `_derivation(repo, head, derived)`; `review_actual.PACKING_POLICY_SHA256`, `RECORD_POLICY_SHA256`, `_run_git`; `canonical.telemetry_digest`.
- Consumes (SOURCE): `validate_task7(table, pins)`, `validate_121(payload, pins, table)`, `validate_100(payload, pins)`; in tests `derive_task7(repo, pins)`, `derive_121(repo, pins, task7_pins, authority)`, `derive_100(issue_repo, live_repo, archive_dir, pins, limits)`, `verify_archive(archive_dir, issue_repo, pins)`, `unavailable_ids(payload)`.
- Produces (`review_witness`), exactly the spec's public surface:
  - `class WitnessError(Exception)` with `code`; an undeclared code raises `ValueError`. The codes are the spec's twelve.
  - `ANCHOR_NAME = "derivation-anchor.json"`; `PAYLOAD_NAMES = ("derivation-witness.json", "issue-100-derived.json", "issue-121.json", "task7-estimate.json")`; `ANCHOR_MAX_BYTES = 32768`; `MEMBER_MAX_BYTES = 1048576`.
  - `tool_closure(tool_repo: Path, tool_commit: str) -> dict` and `verify_running_closure(closure: dict) -> None`.
  - `build_witness(components: dict, payloads: Mapping[str, dict], raw: Mapping[str, bytes]) -> dict`, both mappings keyed by the three fixture names.
  - `build_anchor(components: dict, raw: Mapping[str, bytes]) -> dict`, `raw` keyed by the four `PAYLOAD_NAMES`.
  - `authenticate(bundle_dir: Path, expected_anchor_sha256: str) -> tuple[dict, dict[str, bytes]]`.
  - `validate_bundle(anchor: dict, raw: Mapping[str, bytes], *, task7_pins, issue121_pins, issue100_pins) -> dict[str, dict]`, the four decoded payloads by name.
- Produces (support; RP12: plain paths and pins, no import of this task's module):
  - `retained_fixture(tmp, **shape) -> tuple[Path, Path, Path, tuple]`: `(issue_121_repo, issue_100_repo, archive_dir, (task7_pins, issue121_pins, issue100_pins))`, all under `tmp/repos/`. It is `linear_fixture(tmp/"repos/121", **shape)` with `task7_fixture` on that repository, and `issue100_fixture(tmp/"repos/100")`, whose issue repository also holds the live commit (RP4). The default shape measures every outcome; `owners=(1, 2, 3, 6, 3), touches={4: 3}` leaves `tasks-1-3` and `tasks-4-6` unavailable (both measured at planning).
  - `tool_fixture(tmp) -> tuple[Path, str]`: a repository under `tmp/repos/tool` whose one commit holds `SOURCE/"python/agent_tools"` at `python/agent_tools/`, without `__pycache__` directories; returns it and the full commit.

**Invariants:**
- Closure rows (RP16) are `{path, blob, raw_sha256}` sorted by `path`; `path` is relative to `python/agent_tools/` and `raw_sha256` is bare 64-hex. `tool_closure` authenticates the commit with `full_commit`, lists with `git ls-tree -r -z` and reads blobs with `cat-file`. A mode other than `100644`/`100755`, an empty listing or a `ForecastError` is `tool_closure`.
- `verify_running_closure` walks `importlib.resources.files("agent_tools")` and skips `__pycache__` directories only. It loads no module by path and reads no `__file__`.
- `fixtures` and the anchor's `members` are the same `{path, bytes, raw_sha256}` rows with bare 64-hex digests. In the table constant, `tables.historical` and `tables.fresh` denote that member's `records` list; `table_policies` keys are `"<fixture>#<table>"`.
- `authenticate` is spec steps 1–2. A directory entry outside the five names, a missing name or a non-regular entry (`lstat`) is `member_set`. Members are read with `read_regular` limited to their declared `bytes`; a `ForecastError`, a length difference or a digest difference is `member_digest`.
- `validate_bundle` is spec step 3, in its order. Component checks are Git-free (RP7, RP16); a difference is `component_mismatch` unless stated:

| Group | Member | Requirement |
|---|---|---|
| `tool` | `commit`, `files` | closed shape only: 40-hex; non-empty rows strictly sorted by `path` |
| `tool` | `packing_policy_sha256`, `record_policy_sha256` | CORE's two constants |
| `tool` | `artifact_policy_sha256` | a `sha256:` digest equal to every measured issue-121 outcome's, else `policy_mismatch` |
| `issue_121` | `base`, `head`; `tree`; `signer_sha256` | the pins; `task7_pins.prerequisite_tree`; `raw_digest(issue121_pins.allowed_signer)` |
| `issue_100` | `base`, `head`, `live`, `parent_edges_sha256` | the pins |
| `archive` | `producer_sha256`, `manifest_sha256`; `shards` | the pins; closed `{path, bytes, sha256}` rows only |
| `estimate` | five pin members; `table_sha256` | `task7_pins`; `telemetry_digest` of the decoded estimate |

- `EstimateError`, `ContributionError` and `Issue100Error` pass through `validate_bundle` unchanged; nothing else is caught (RP8). Git runs only inside `tool_closure`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_witness.py`. These two helpers are the wire contract for assembling a bundle; write them as given.

```python
FIXTURES = ("issue-100-derived.json", "issue-121.json", "task7-estimate.json")


def derived(tmp, **shape):
    """Components, fixture payloads and pins, assembled the way derivation assembles them."""
    repo121, repo100, archive, pins = retained_fixture(tmp, **shape)
    task7, p121, p100 = pins
    with patch.dict(os.environ, source_budget_env(tmp), clear=True):
        authority = describe("review-package")
    table = derive_task7(repo121, task7)
    payloads = {"task7-estimate.json": table, "issue-121.json": derive_121(repo121, p121, task7, authority),
                "issue-100-derived.json": derive_100(repo100, repo100, archive, p100, authority.limits)}
    components = {
        "tool": {**tool_closure(*tool_fixture(tmp)), "artifact_policy_sha256": authority.policy_sha256,
                 "packing_policy_sha256": PACKING_POLICY_SHA256, "record_policy_sha256": RECORD_POLICY_SHA256},
        "issue_121": {"base": p121.base, "head": p121.head, "tree": task7.prerequisite_tree,
                      "signer_sha256": raw_digest(p121.allowed_signer)},
        "issue_100": {"base": p100.base, "head": p100.head, "live": p100.live,
                      "parent_edges_sha256": p100.parent_edges_sha256},
        "archive": verify_archive(archive, repo100, p100),
        "estimate": {"prerequisite_commit": task7.prerequisite_commit, "prerequisite_tree": task7.prerequisite_tree,
                     "plan_root_blob": task7.plan_root_blob, "task7_blob": task7.task7_blob,
                     "model_version": task7.model_version, "table_sha256": telemetry_digest(table)}}
    return components, payloads, pins


def bound(components, payloads):
    """`(anchor, raw)` with every in-bundle digest recomputed: the test-only trust injection."""
    components = {**components, "estimate": {**components["estimate"],
                                             "table_sha256": telemetry_digest(payloads["task7-estimate.json"])}}
    raw = {name: canonical_bytes(payloads[name]) for name in FIXTURES}
    raw["derivation-witness.json"] = canonical_bytes(build_witness(components, payloads, raw))
    return build_anchor(components, raw), raw
```

`WitnessTest.setUpClass` builds `derived(tmp, owners=(1, 2, 3, 6, 3), touches={4: 3})` once. `setUp` writes `bound(...)` and the canonical anchor into a fresh `self.dir` and sets `self.expected = telemetry_digest(anchor)`; `kwargs()` returns the three pin keywords.

```python
    def test_member_bytes_are_bound_before_decode(self):
        (self.dir / "issue-121.json").write_bytes(b"{not json")
        with self.assertRaises(WitnessError) as caught:
            authenticate(self.dir, self.expected)
        self.assertEqual(caught.exception.code, "member_digest")

    def test_core_loader_accepts_a_committed_bundle(self):
        repo = init_repo(self.tmp / "committed")
        head = commit_files(repo, {f"fx/{p.name}": p.read_bytes() for p in self.dir.iterdir()}, "bundle")
        self.assertIsNone(_derivation(repo, head, {"kind": "retained-anchor/v2", "path": "fx/" + ANCHOR_NAME,
                                                   "anchor_sha256": self.expected}))

    def test_malformed_sibling_beside_an_unavailable_outcome_is_invalid(self):
        control = validate_bundle(*authenticate(self.dir, self.expected), **self.kwargs())
        self.assertEqual(unavailable_ids(control["issue-121.json"]), ("tasks-1-3", "tasks-4-6"))
        hundred = copy.deepcopy(self.payloads["issue-100-derived.json"])
        hundred["summary"]["integrated"] += 1
        table = copy.deepcopy(self.payloads["task7-estimate.json"])
        table["rows"] = table["rows"][:-1]
        for name, broken, error in (("issue-100-derived.json", hundred, Issue100Error),
                                    ("task7-estimate.json", table, EstimateError)):
            with self.subTest(member=name), self.assertRaises(error):
                validate_bundle(*bound(self.components, {**self.payloads, name: broken}), **self.kwargs())
```

  Add these named cases, each asserting the exact `code`:
  - `test_replacement_anchor_fails_the_unchanged_digest`: `tool.commit` set to `"0" * 40`, rewritten canonically → `anchor_digest`.
  - `test_malformed_expected_digest`: `"sha256:xyz"` and bare hex → `expected_digest`.
  - `test_oversized_anchor_fails_before_decode`: `ANCHOR_MAX_BYTES + 1` bytes of `b"{"` → `anchor_unreadable`.
  - `test_noncanonical_or_open_anchor_is_anchor_shape`: indented JSON; an extra key; `schema_version` `True`.
  - `test_missing_extra_and_symlinked_members_fail` → `member_set` each.
  - `test_declared_member_above_the_cap_is_refused`: declared `bytes` of `MEMBER_MAX_BYTES + 1`, expected digest recomputed → `member_digest`.
  - `test_noncanonical_member_is_refused`: a member re-encoded with spaces, anchor rebuilt → `member_noncanonical`.
  - `test_witness_has_six_keys_and_no_anchor_identity`: exact key set; neither `self.expected` nor `ANCHOR_NAME` occurs in the witness bytes; an added key → `witness_shape`.
  - `test_component_substitutions_under_trust_injection`: each pin-determined member of the table changed and passed through `bound` → `component_mismatch`; `tool.artifact_policy_sha256` changed → `policy_mismatch`.
  - `test_stale_table_digest_or_policy_is_table_mismatch`: one altered `tables` row, then one altered `table_policies` entry, anchor rebuilt.
  - `test_tool_closure_is_sorted_and_complete`: paths equal the fixture's files, sorted, with each file's SHA-256; a committed symlink → `tool_closure`.
  - `test_running_closure_changed_extra_or_missing_file_fails`: three mutated closures → `tool_closure`; the untouched one passes.

- [ ] **Step 2: Run and watch them fail.** `PYTHONPATH=python python3 -m unittest tests.test_review_witness 2>&1 | tail -3` → `ImportError` (no `agent_tools.review_witness`).

- [ ] **Step 3: Implement** the support fixtures, then the module. Its docstrings state implemented behaviour in present tense.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_witness 2>&1 | tail -3
if grep -Eq 'import_module|__file__|sys\.path' python/agent_tools/review_witness.py; then exit 1; fi
if grep -q 'review_witness' tests/retained_review_test_support.py; then exit 1; fi
test "$(wc -c < python/agent_tools/review_witness.py)" -le 19456
grep -q 'tests/test_review_witness.py' justfile
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

  At the starting commit the focused suite and the `justfile` grep fail.

- [ ] **Step 5: Commit.** Stage only the four Files; subject at most 64 bytes: `feat(review): anchor and validate retained bundles (#249)`. A review fix uses `fix(review): address Task-2 review findings (#249)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges`, refresh `actual_evidence`, then renew G0 at `--completed-through 2` (RP14).

## Forecast basis

Parent D15 price (bytes + one per line + 512) plus about ten percent: module 390 lines / 17,500 B → 20,480 B / +430; test 360 lines / 17,500 B → 20,480 B / +400; support (modify, U10) +40 lines → 5,120 B / +48 / −2; `justfile` (modify, U10), first of four cumulative contributions → 2,048 B / +1.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"8755b2f8ec9412242dab254f9ef318da1e78eb24","head":"5f67003b83503fb56037c7a9720812cf611c79e8"},{"base":"60c8d67cebaaa3290bc4410235ea12df13df55cc","head":"5b241d3445114a97c9d450c4cbf10abf8043764a"},{"base":"3509778ccddb9c484f1daa60f82da441c2a49a5b","head":"16d19909484964717c8eff470a4f4ca46d1aa937"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":430,"boundary":"replay","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t2-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-1","last_task":2,"owner":2,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":400,"boundary":"replay","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t2-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2-2","last_task":2,"owner":2,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":48,"boundary":"replay","deleted_lines":2,"record_bytes":5120,"support":{"covers":["t2-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-3","last_task":2,"owner":2,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":1,"boundary":"replay","deleted_lines":0,"record_bytes":2048,"support":{"covers":["t2-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t2-4","last_task":6,"owner":2,"path":"justfile"}]}}
```
