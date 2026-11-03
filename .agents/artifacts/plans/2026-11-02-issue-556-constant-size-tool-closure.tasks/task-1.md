# Task 1: The tool group binds the closure by one digest

The encoding, its validator, their tests and every living sentence that names the tool group (spec § *The tool group*, § *Validation*, § *Documents*; D1, D2, D3, D6, D7, D9). This task changes every `python/` path the delivery changes: its last commit, once its review has passed with any fixes, is the tool commit `T` that Task 2 publishes under (D5 step 1).

Run every command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <command>` with the timeout shown.

**Files:**
- Modify: `python/agent_tools/review_witness.py` (the module docstring's last paragraph; `_components`)
- Modify: `python/agent_tools/review_derivation.py` (`derive_bundle`: the `tool` group literal and docstring item 5)
- Modify: `python/README.md` (§ *Retained review evidence*: one sentence appended to its paragraph)
- Modify: `tests/test_review_witness.py` (`derived`, a new `closure` helper, the substitution table, one new case, two closure cases)
- Modify: `tests/test_review_derivation.py` (two imports, one new case)
- Modify: `tests/test_review_retained_full.py` (the comment above `GIT_FREE_SITES` only)

**Interfaces:**
- Consumes, unchanged (D3): `tool_closure(tool_repo: Path, tool_commit: str) -> dict` returning `{"commit", "files"}` with `files` the `{path, blob, raw_sha256}` rows sorted by `path`; `verify_running_closure(closure: dict) -> None`; `agent_tools.canonical.telemetry_digest`.
- Produces: in both the anchor and the witness's `components`, the tool group `{"commit": <40 lowercase hex>, "files_sha256": telemetry_digest(<the rows>), "artifact_policy_sha256", "packing_policy_sha256", "record_policy_sha256"}`; `validate_bundle` accepts that shape only. Task 2 consumes `T`.

**Invariants:**
- `anchor["tool"]["files_sha256"] == telemetry_digest(tool_closure(tool_repo, tool_commit)["files"])` for every derived bundle, and `witness["components"]["tool"] == anchor["tool"]` (D2, RP3).
- A tool group with any key set other than the five, or whose `files_sha256` is not `sha256:` plus 64 lowercase hex, is `component_mismatch`, so a `files` member is refused beside or in place of the digest (D2, D4).
- `tool_closure` and `verify_running_closure` keep their bodies; no public name is added to `review_witness` or `review_derivation` (D3). `_CODES` keeps its twelve codes, `DerivationError` its four, and both `schema_version`s stay 2.
- No bound moves (D7): `ANCHOR_MAX_BYTES = 32768`, `MEMBER_MAX_BYTES`, the tier's `MEMBER_CAP, BUNDLE_CAP = 65536, 3 * 65536`, and `home/common/agent-skills/artifact-budget-policy.json`.
- No file under `tests/fixtures/` or `tests/retained_evidence_test_support.py` changes here (Task 2 owns them).

- [ ] **Step 1: Write the failing tests**

In `tests/test_review_witness.py`, make `derived` assemble the tool group as derivation will. Replace the line `"tool": {**tool_closure(*tool_fixture(tmp)), "artifact_policy_sha256": authority.policy_sha256,` and its opening `components = {` with:

```python
    closure = tool_closure(*tool_fixture(tmp))
    components = {
        "tool": {"commit": closure["commit"], "files_sha256": telemetry_digest(closure["files"]),
                 "artifact_policy_sha256": authority.policy_sha256,
```

(the next line, `"packing_policy_sha256": PACKING_POLICY_SHA256, "record_policy_sha256": RECORD_POLICY_SHA256},`, stays). Add this method to `WitnessTest` directly after `kwargs`:

```python
    def closure(self):
        """`tool_closure` of the class's tool fixture commit, the rows the tool group's digest binds."""
        repo = self.root / "repos/tool/repo"
        return tool_closure(repo, git(repo, "rev-parse", "HEAD"))
```

In `test_component_substitutions_under_trust_injection`, the three `("tool", "files", ...)` cases go (the tool group has no `files` member to substitute); the `cases +=` list becomes:

```python
        cases += [("tool", "commit", "HEAD"), ("tool", "artifact_policy_sha256", "sha256:xyz"),
                  ("issue_100", "extra", "member"),
                  ("archive", "shards", [{**parts["archive"]["shards"][0], "extra": 1}])]
```

Add this case directly before `test_forged_issue_121_head_tree_is_component_mismatch` (the three rows that drop or replace a member are why it is a case of its own and not table rows):

```python
    def test_tool_group_binds_the_closure_by_one_digest(self):
        tool, rows = self.components["tool"], self.closure()["files"]
        self.assertEqual(set(tool), {"commit", "files_sha256", "artifact_policy_sha256", "packing_policy_sha256",
                                     "record_policy_sha256"})
        self.assertEqual(tool["files_sha256"], telemetry_digest(rows))
        undigested = {name: value for name, value in tool.items() if name != "files_sha256"}
        for label, group in (("the rows beside the digest", {**tool, "files": rows}),
                             ("the rows in place of the digest", {**undigested, "files": rows}),
                             ("no digest", undigested),
                             ("the rows as the digest", {**tool, "files_sha256": rows}),
                             ("a bare hex digest", {**tool, "files_sha256": tool["files_sha256"][len("sha256:"):]}),
                             ("a non-hex digest", {**tool, "files_sha256": "sha256:xyz"})):
            with self.subTest(label):
                self.refused("component_mismatch", validate_bundle, *bound({**self.components, "tool": group},
                                                                           self.payloads), **self.kwargs())
```

In `test_tool_closure_is_sorted_and_complete`, replace `self.assertEqual(tool_closure(repo / "python", head)["files"], self.components["tool"]["files"])` with `self.assertEqual(tool_closure(repo / "python", head), self.closure())`. In `test_running_closure_changed_extra_or_missing_file_fails`, replace `closure = self.components["tool"]` with `closure = self.closure()`.

In `tests/test_review_derivation.py`, add `from agent_tools.review_actual import PACKING_POLICY_SHA256, RECORD_POLICY_SHA256` after the `telemetry_digest` import, add `tool_closure` to the `agent_tools.review_witness` import, and add this case directly before `test_existing_or_dangling_output_is_output_exists`. It is the one binding no Git-free check makes (spec § *Test seams*):

```python
    def test_tool_group_binds_the_tool_commits_rows_by_digest(self):
        out, _ = self.shared()
        anchor, witness = (json.loads((out / name).read_bytes()) for name in (ANCHOR_NAME, PAYLOAD_NAMES[0]))
        rows = tool_closure(self.inputs.tool_repo, self.inputs.tool_commit)["files"]
        self.assertEqual(anchor["tool"], {"commit": self.inputs.tool_commit, "files_sha256": telemetry_digest(rows),
                                          "artifact_policy_sha256": self.authority.policy_sha256,
                                          "packing_policy_sha256": PACKING_POLICY_SHA256,
                                          "record_policy_sha256": RECORD_POLICY_SHA256})
        self.assertEqual(witness["components"]["tool"], anchor["tool"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH=python timeout 1200 python3 -m unittest tests/test_review_witness.py tests/test_review_derivation.py 2>&1 | tail -3`
Expected: `FAILED (failures=3, errors=2)` over 39 tests (about 6 minutes). Errors: `test_authenticated_bundle_is_the_anchor_and_its_four_raw_members` and `test_malformed_sibling_beside_an_unavailable_outcome_is_invalid` (`WitnessError: component_mismatch`, the validator still wants `files`). Failures: `test_component_substitutions_under_trust_injection` (`'component_mismatch' != 'policy_mismatch'`), `test_tool_group_binds_the_closure_by_one_digest` [the rows in place of the digest] (`WitnessError not raised`), `test_tool_group_binds_the_tool_commits_rows_by_digest`.

- [ ] **Step 3: Write the minimal implementation**

`review_derivation.derive_bundle`: the `"tool"` entry of `components` becomes `{"commit": closure["commit"], "files_sha256": telemetry_digest(closure["files"]), "artifact_policy_sha256": authority.policy_sha256, "packing_policy_sha256": PACKING_POLICY_SHA256, "record_policy_sha256": RECORD_POLICY_SHA256}`, built in place where the closure is spread today (RP16: nothing else returns or holds the rows). `closure` still goes to `verify_running_closure` first, unchanged.

`review_witness._components`: the tool group's closed key tuple becomes `("commit", "files_sha256", "artifact_policy_sha256", "packing_policy_sha256", "record_policy_sha256")`, and `_digest(tool["files_sha256"])` joins the same `_require(..., "component_mismatch")` conjunction directly after `_hex(tool["commit"], 40)`, keeping lines within 120 columns. The second `_require` drops every `files` clause (the `_rows` row shape, the non-empty check, the 40- and 64-hex checks and the sorted-path check) and keeps only the `archive["shards"]` clauses, reading `shards = archive["shards"]`. `_rows` stays: the anchor envelope and the shards still use it.

Prose, verbatim. In the `review_witness` module docstring, the sentence that names `tool.files` becomes:

```text
Git, so it checks what the pins and the tables determine (RP7): `tool.commit`,
`tool.files_sha256` and `archive.shards` are checked for their closed shape
only, and are authentic only under the caller's anchor digest or by derivation
again. The tool group binds the whole package by `files_sha256`, the
`telemetry_digest` of `tool_closure`'s rows, so its size does not grow with the
package (issue 556).
```

Item 5 of `derive_bundle`'s docstring becomes:

```text
    5. the witness, held to the same bound, and then the anchor, held to `ANCHOR_MAX_BYTES` under the same
       code, are built over the five component groups, each assembled once (RP16); the tool group holds the
       tool commit, `files_sha256` (the `telemetry_digest` of the closure's rows) and the three policy
       digests, and the witness's tables are those of the two retained payloads' expansions and of the
       estimate table;
```

Append to the one paragraph of `python/README.md` § *Retained review evidence*, on the same line: ``The bundle's `tool` group binds the whole `agent_tools` package by the tool commit and `files_sha256`, the `telemetry_digest` of that commit's sorted `{path, blob, raw_sha256}` rows, so the bundle's size does not grow with the package (#556).`` In `tests/test_review_retained_full.py`, the comment above `GIT_FREE_SITES` names `` `tool.files_sha256` `` where it names `` `tool.files` ``; nothing else in that file changes.

- [ ] **Step 4: Verify the focused suites**

Run: `env PYTHONPATH=python timeout 1500 python3 -m unittest tests/test_review_witness.py tests/test_review_derivation.py tests/test_review_replay.py 2>&1 | tail -3`
Expected: `OK` over 52 tests (about 10 minutes), no failure, error or skip. `test_review_replay.py` derives through `derive_bundle` and must stay green unchanged.

Bounds unchanged (AC2), from the worktree root with `set -e`:

```bash
git diff --quiet e692c9685c3e4b08f55c327c5f2b8c699fc95bc4 -- python/agent_tools/review_expansion.py home/common/agent-skills/artifact-budget-policy.json
grep -c '^MEMBER_CAP, BUNDLE_CAP = 65536, 3 \* 65536$' tests/test_review_retained_full.py
grep -c '^ANCHOR_MAX_BYTES = 32768$' python/agent_tools/review_witness.py
if git diff --name-only e692c9685c3e4b08f55c327c5f2b8c699fc95bc4 -- tests/fixtures tests/retained_evidence_test_support.py | grep -q .; then exit 1; fi
```

- [ ] **Step 5: Commit**

Stage only the six Files, then `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(review): bind the tool closure by one digest (issue 556)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. `git status --porcelain -- python` must print nothing afterwards: the next step runs the package as `HEAD`'s.

- [ ] **Step 6: The issue's failing case, at the commit** (D9, D10)

Build a private quiescent retained root under your scratch root (D10). It takes seconds and about 42 MB:

```bash
set -euo pipefail
MAIN=/Users/anis/tmp/nix-config
ARCHIVE=.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f
make_root() {  # $1: a new path
  git clone -q --no-local --no-checkout "$MAIN" "$1"
  cp -R "$MAIN/.git/objects/." "$1/.git/objects/"   # the unreachable pins, e.g. fe85677c
  mkdir -p "$1/$(dirname "$ARCHIVE")"; cp -R "$MAIN/$ARCHIVE" "$1/$ARCHIVE"
}
ROOT="$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/root-556"
make_root "$ROOT"
```

Run: `env AGENT_RETAINED_ROOT="$ROOT" PYTHONPATH=python timeout 1800 python3 -m unittest tests.test_review_retained_full.RetainedFullTest.test_bundle_files_fit_the_whole_record_caps tests.test_review_retained_full.RetainedFullTest.test_two_derivations_are_byte_identical 2>&1 | tail -3`
Expected: `OK` over 2 tests (about 10 minutes). At this task's start commit the cap case fails with `AssertionError: 203078 not less than or equal to 196608` (confirmed while planning on such a root); after it the fresh bundle is about 166,257 B. Report the root path to the controller.

Then confirm the window D9 names, as an observation and not a repair: `env PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_evidence.py 2>&1 | grep -c 'component_mismatch'` prints a non-zero count (11 while planning, the suite ending `FAILED (failures=1, errors=4)`), because the committed bundle still holds the list. Do not touch `tests/fixtures/` or the literals: Task 2 re-derives them at `T`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"81d18511e95e7e7800e142c1c94e53e2c1184619","head":"7213928f0e3c91de247dc028fe95b95f6a9dcf88"}],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":16,"record_bytes":8192,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":6,"record_bytes":6144,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":9216,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":1,"owner":1,"path":"python/README.md"},{"bounds":[{"added_lines":45,"boundary":"all","deleted_lines":12,"record_bytes":15360,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":1,"owner":1,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":4,"record_bytes":6144,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":1,"owner":1,"path":"tests/test_review_derivation.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["r1f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1f","last_task":1,"owner":1,"path":"tests/test_review_retained_full.py"}]}}
```
