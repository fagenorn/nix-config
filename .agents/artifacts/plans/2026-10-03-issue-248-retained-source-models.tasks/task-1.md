# Task 1: Recover and fix the Task-7 estimate model and Task-8 effect

**Files:**
- Create: `python/agent_tools/review_task7.py` (recovered from blob `fc721644`, then fixed)
- Create: `tests/retained_review_test_support.py` (recovered from blob `15e28b21`; first of three contributions)
- Create: `tests/test_review_task7.py` (recovered from blob `b49b3af9`, then extended)
- Modify: `justfile` (add `tests/test_review_task7.py \` after `tests/test_review_history.py \` in `agent-workflow-tests`; first of three contributions)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (the two `LEGACY_MIGRATION_INPUTS` lines from `92a0c79c`)

**Recovery:** manifest row S-R1. Restore with `git cat-file -p <blob> > <path>` from the shared object store; take the `justfile` and contracts-test lines from `git diff 5f865639 92a0c79c -- justfile home/common/agent-skills/tests/test_workflow_skill_contracts.py`. The recovered bytes are input only: fix N1, N2, M2, M5 and M6, disposition M4, and remove the skipping real-table test (S3–S7). Land everything as one implementation commit; the task report carries `git diff` from each recovered blob to the committed file (S8).

**Interfaces:**
- Consumes (CORE at `DELIVERY_BASE`): `review_actual.RECORD_POLICY`, `PACKING_POLICY`, `PACKING_POLICY_SHA256`, `GenerationError`, `git_diff(repo, base_tree, head_tree, *view)` (views include `("--numstat", "-z")` and `("--binary", f"-U{c}")` for every policy context), `actual_inputs_from_trees(repo, base_tree, head_tree, *, base, head, commits, package_name, limits)`; `review_forecast.history_commit`, `ForecastError`, `canonical_bytes`; `review_budget.describe("review-package")`; `agent_tools.canonical.telemetry_digest`.
- Produces, unchanged from the recovered module (parent D12, D18): `EstimateError(code)` with codes `unsupported_estimate`, `unsupported_composition`, `invalid_table`, `inventory_mismatch`; `RendererSpec`; `Task7Pins`; `TASK7_PINS`; `TASK8_EFFECT`; `derive_task7(repo, pins) -> dict`; `validate_task7(table, pins) -> None`; `compose(repo, table, pins, *, base_tree, final_tree, limits) -> tuple[dict, ...]` with rows `{path, record_bytes, added_lines, deleted_lines}`.
- Produces (support, for Tasks 2–3): `SOURCE`, `git`, `init_repo`, `commit_files`, `ssh_signer`, `HOSTILE_GIT_ENV`, `snapshot`, `source_budget_env`, exactly as recovered.

**Invariants:**
- **Pin faults vs table faults (S3, S14).** `validate_task7` first runs the pin checks (`_pins`, `_renderers`) outside its translation, so a bad pin set raises `unsupported_estimate` from `derive_task7` and `validate_task7` alike. After that, every table fault raises `invalid_table`. Before any member is used as a key, index or set member, it is type-checked: a row is a `dict`; `operation` is a `str` in `RULES`; `new_path` is a `str`; `input` is `None` (adds only) or exactly `{blob, mode, bytes, lines}` with `blob` lowercase hex of the pinned length, `mode` a `str` in the closed Git blob-mode set `{"100644", "100755", "120000"}` and both counts non-Boolean `int`s (S18). No `except Exception`, `except TypeError` or other broad catch exists in the module.
- **One move-root resolver (S4).** `_pins` raises `unsupported_estimate` when two old prefixes or two new prefixes are equal, or one is a path prefix of the other (`a` and `a/b`; `a` and `ab` do not overlap). Derive, validate and `compose` all map paths through one resolver function; after that check every path has at most one root on each side, so they cannot disagree.
- **M2 (S5).** `compose` takes every record's `added_lines`/`deleted_lines` from `git_diff(scratch, base_tree, tree, "--numstat", "-z")` over the same trees it measures, never from payload parsing. A measured record without a numstat row raises `unsupported_composition`. A binary row (`-\t-`) counts 0 and 0.
- **M5 (S5, S15).** A `write` row's `record_bytes` is the full delete/add record (unchanged `_record`) plus the multi-hunk allowance below. `add` and `move` bounds are unchanged. `compose`'s own write bound (measured removal plus the `_record` add, used when the base tree holds the target) adds the same allowance from the removed and output line counts (S19). The admitted contexts are read from `PACKING_POLICY` (`initial` and every `adaptive` entry), never copied. With `n = min(input.lines, output.lines)` and `w` the decimal width of `max(input.lines, output.lines) + 1`:
  - `HUNK_HEADER_MAX = len("@@ -, +, @@ ") + 4 * w + FUNCNAME_MAX_BYTES + len("\n")`, where `FUNCNAME_MAX_BYTES = 80` is Git's function-context truncation width (xdiff's `struct func_line` buffer);
  - `allowance = (HUNK_HEADER_MAX - first) + max over admitted contexts c of (n // (2*c + 1)) * max(0, HUNK_HEADER_MAX - 2 * (2*c + 1))`, where `first` is the hunk-header length `_record` already charges.
  - Rationale (put it in the docstring once the code is verified): under `--inter-hunk-context=0` two hunks stay separate only across more than `2c` unchanged lines; a full delete/add record charges each unchanged line at least 2 bytes more than any hunk shows it; every hunk header is at most `HUNK_HEADER_MAX`.
- **M4 (S6).** `validate_task7` stays Git-free. The module docstring states that it proves a table is the exact rebuild of its own input facts plus the pins, that authenticity is `derive_task7` equality against the pinned tree, and that REPLAY's derivation runs that equality before writing its anchor.
- The real roots are disjoint, so the real table is unchanged except for the M5 write allowance; it still has counts 173/165/54/108/3/5/3 and at most 49,152 canonical bytes (proved by the S7 final-gate step, not here).
- No module code runs `git rev-list`, `git log` or `rev-parse <commit>^{tree}`. Tests and support may use `rev-parse` for fixtures.

- [ ] **Step 1: Restore the recovered blobs and lines.** Restore the three files and the two edits listed above. Delete `test_real_table_fits_one_review_record` and every import that only it used (S7). Do not stage yet.

- [ ] **Step 2: Add the failing tests.** Add to `tests/test_review_task7.py` (module scope, then inside `Task7ModelTest`). Extend `fixture_pins(tmp, agents=None)` so `agents`, when given, replaces the `AGENTS.md` bytes; add `PACKING_POLICY` to the `review_actual` import.

```python
KINDS = ({"k": 1}, [1], "s", 7, True, None)


def same(a, b):
    return type(a) is type(b) and a == b


def interleaved(tag, count=40):
    """Even lines are empty and shared; odd lines are long function-context lines that differ.

    At context 0 every change is its own hunk, and each header carries a truncated
    function line, so the record outgrows a single-hunk delete/add bound.
    """
    return b"".join((b"" if n % 2 == 0 else b"func_%d_%s_" % (n, tag) + b"f" * 200) + b"\n"
                    for n in range(count))

    # --- inside Task7ModelTest ---
    def test_every_malformed_member_is_invalid_table(self):
        table = derive_task7(self.repo, self.pins)
        def with_row(n, row):
            rows = list(table["rows"]); rows[n] = row
            return rehash(table, rows)
        variants = []
        for key, value in table.items():
            variants += [{**table, key: kind} for kind in KINDS if not same(kind, value)]
            variants.append({k: v for k, v in table.items() if k != key})
        for n, row in enumerate(table["rows"]):
            variants += [with_row(n, kind) for kind in KINDS]
            for key, value in row.items():
                variants += [with_row(n, {**row, key: kind}) for kind in KINDS if not same(kind, value)]
                variants.append(with_row(n, {k: v for k, v in row.items() if k != key}))
            for key, value in (row["input"] or {}).items():
                # S18: a move row's counts feed no rebuilt member; derive_task7 equality owns them.
                variants += [with_row(n, {**row, "input": {**row["input"], key: kind}})
                             for kind in KINDS if not same(kind, value)
                             and not (row["operation"] == "move" and key in ("bytes", "lines")
                                      and type(kind) is int)]
        self.assertGreater(len(variants), 500)
        for variant in variants:
            with self.subTest(variant=repr(variant)[:160]):
                with self.assertRaises(EstimateError) as caught:
                    validate_task7(variant, self.pins)
                self.assertEqual(caught.exception.code, "invalid_table")

    def test_overlapping_move_roots_are_unsupported_everywhere(self):
        table = derive_task7(self.repo, self.pins)
        for extra in ((".claude/specs/x", ".agents/other", "spec"),
                      (".claude/other", ".agents/artifacts/specs/x", "plan"),
                      (".claude/specs", ".agents/elsewhere", "plan"),
                      (".claude/other", ".agents/artifacts/specs", "plan")):
            broken = replace(self.pins, move_roots=ROOTS + (extra,))
            for call in (lambda: derive_task7(self.repo, broken), lambda: validate_task7(table, broken)):
                with self.subTest(extra=extra), self.assertRaises(EstimateError) as caught:
                    call()
                self.assertEqual(caught.exception.code, "unsupported_estimate")

    def test_real_pins_name_three_disjoint_roots(self):
        self.assertEqual(TASK7_PINS.prerequisite_commit, "fe85677c8bd26c808ac69c2ee21b17ff6e262923")
        self.assertEqual(TASK7_PINS.move_roots, ROOTS)

    def test_multi_hunk_write_stays_within_bound_at_every_policy_context(self):
        output = interleaved(b"new")
        repo, pins = fixture_pins(Path(tempfile.mkdtemp(dir=self.tmp)), agents=interleaved(b"old"))
        pins = replace(pins, renderers=tuple(
            replace(s, fixed_bytes=len(output), fixed_lines=output.count(b"\n")) if s.target == "AGENTS.md"
            else s for s in pins.renderers))
        bound = next(r["record_bytes"] for r in derive_task7(repo, pins)["rows"] if r["new_path"] == "AGENTS.md")
        base = pins.prerequisite_tree
        head = tree_with(repo, base, b"AGENTS.md", output)
        records = [next(r for r in item.records if r.path == "AGENTS.md")
                   for item in actual_inputs_from_trees(repo, base, head, base=base, head=head, commits=(),
                                                        package_name="review.json", limits=limits())]
        self.assertEqual(len(records), 1 + len(PACKING_POLICY["adaptive"]))
        headers = [l for l in records[-1].payload.splitlines() if l.startswith(b"@@ ")]
        self.assertGreater(len(headers), 10)
        self.assertTrue(any(b" func_" in h for h in headers))
        for record in records:
            self.assertLessEqual(record.source_bytes, bound)

    def test_compose_counts_generated_evidence_lines_from_numstat(self):
        table = derive_task7(self.repo, self.pins)
        # CORE builds generated evidence only for a chunk above member_max_bytes, so oversize it.
        entity = b'        b.Entity("W", e => { e.Property<int>("Id"); e.HasIndex("Id"); });\n'
        designer = (b"// <auto-generated />\n[Migration(\"20260101_Init\")]\npartial class Init\n{\n"
                    b"    void BuildTargetModel(object b)\n    {\n"
                    + entity * (limits().member_max_bytes // len(entity) + 1) + b"    }\n}\n")
        path = "src/Migrations/Init.Designer.cs"
        base = self.pins.prerequisite_tree
        final = tree_with(self.repo, base, path.encode(), designer)
        item = next(actual_inputs_from_trees(self.repo, base, final, base=base, head=final, commits=(),
                                             package_name="review.json", limits=limits()))
        self.assertIsNotNone(next(r for r in item.records if r.path == path).generated_evidence)
        before = snapshot(self.repo)
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                                              final_tree=final, limits=limits())}
        self.assertEqual((rows[path]["added_lines"], rows[path]["deleted_lines"]), (designer.count(b"\n"), 0))
        self.assertEqual(snapshot(self.repo), before)

    def test_compose_refuses_rename_into_target_and_non_blob_target(self):
        table = derive_task7(self.repo, self.pins)
        into = commit_files(self.repo, {"src/app.txt": None, ".agents/runtime/.gitignore": b"app\n"}, "into")
        gitlink = tree_with(self.repo, self.pins.prerequisite_tree, b"AGENTS.md", b"x\n", "160000")
        for final in (git(self.repo, "rev-parse", into + "^{tree}"), gitlink):
            before = snapshot(self.repo)
            with self.assertRaises(EstimateError) as caught:
                compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                        final_tree=final, limits=limits())
            self.assertEqual(caught.exception.code, "unsupported_composition")
            self.assertEqual(snapshot(self.repo), before)

    def test_compose_write_takes_larger_observed_record(self):
        table = derive_task7(self.repo, self.pins)
        bound = next(r for r in table["rows"] if r["new_path"] == ".gitignore")
        final = commit_files(self.repo, {".gitignore": lines("big", 200)}, "big write")
        observed = measured_records(self.repo, self.pins.prerequisite_commit, final)[".gitignore"]
        self.assertGreater(observed, bound["record_bytes"])
        before = snapshot(self.repo)
        rows = {r["path"]: r for r in compose(self.repo, table, self.pins, base_tree=self.pins.prerequisite_tree,
                                              final_tree=git(self.repo, "rev-parse", final + "^{tree}"),
                                              limits=limits())}
        self.assertEqual(rows[".gitignore"]["record_bytes"], observed)
        self.assertEqual(rows[".gitignore"]["added_lines"], 200)
        self.assertEqual(snapshot(self.repo), before)
```

  The `same` guard keeps a variant from equalling the original (`True == 1`). With the recovered `rendered()` helper, the hostile-producer test now also exercises M5; keep it. A recovered test asserting a write row's exact old value must be updated to the M5 value, with the change noted in the report.

- [ ] **Step 3: Run the tests and watch them fail.** Run `PYTHONPATH=python python3 -m unittest tests.test_review_task7 2>&1 | tail -5`. Expected: failures or errors in the matrix (a raw `TypeError` escapes for a list `operation`), the overlap test (no `unsupported_estimate`), the multi-hunk test (`source_bytes` above the single-hunk bound at context 0) and the generated-evidence test (`added_lines` is 0).

- [ ] **Step 4: Implement the fixes.** Apply the invariants above to `review_task7.py`. Keep every recovered interface name. Put the M5 rationale in a docstring written from the verified code, and the M4 contract in the module docstring; describe only behavior the tests prove.

- [ ] **Step 5: Verify.**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest tests.test_review_task7 2>&1 | tail -3   # OK, no skips
if grep -q skipTest tests/test_review_task7.py; then exit 1; fi
if rg -q 'rev-list|"log"|\^\{tree\}' python/agent_tools/review_task7.py; then exit 1; fi
if rg -q 'except (Exception|TypeError|KeyError|AttributeError)\b' python/agent_tools/review_task7.py; then exit 1; fi
grep -q 'tests/test_review_task7.py' justfile
just agent-workflow-tests 2>&1 | tail -3   # zero failures
just build 2>&1 | tail -3                  # S12: import check covers the new module
```

  At `DELIVERY_BASE`, `grep -q tests/test_review_task7.py justfile` fails and the module import fails, so this gate can fail.

- [ ] **Step 6: Commit.** Stage only the five Files and commit `feat(review): recover and fix the Task-7 estimate (#248)`.

## Forecast basis

Priced per parent D15 (bytes + lines + 512) from the measured recovered blobs plus the fix deltas (S13):

| Path | Measured blob | Fix delta | Bound |
|---|---|---|---|
| `review_task7.py` | 26,018 B / 477 | measured about 30,584 B / +550, plus the S19 `compose` write allowance and a fix-round reserve | 32,768 B / +600 |
| `tests/test_review_task7.py` | 20,807 B / 352 | measured 28,478 B / +466 with the briefed tests, plus a fix-round reserve (S18) | 31,744 B / +560 |
| `tests/retained_review_test_support.py` | 5,144 B / 115 | reserve +1,024 B / +15 | 6,912 B / +130 |

`justfile` contribution 1 of 3: 2,048 B / +2. Contracts test: 2,560 B / +4 (the recovered record measured 1,763 B).

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"90d55b0d4016fdf83391bec197794d3b31dd6e2c","head":"5d458f8e8c8b856cd8831be0c7519e942955de59"},{"base":"aafad61bae40f115da78bc34b3b939df5d552135","head":"04593449322a12106bb4df509f9162b0f00386c2"}],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":600,"boundary":"source","deleted_lines":0,"record_bytes":32768,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_task7.py"},{"bounds":[{"added_lines":130,"boundary":"source","deleted_lines":0,"record_bytes":6912,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-2","last_task":3,"owner":1,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":560,"boundary":"source","deleted_lines":0,"record_bytes":31744,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-3","last_task":1,"owner":1,"path":"tests/test_review_task7.py"},{"bounds":[{"added_lines":2,"boundary":"source","deleted_lines":0,"record_bytes":2048,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-4","last_task":3,"owner":1,"path":"justfile"},{"bounds":[{"added_lines":4,"boundary":"source","deleted_lines":0,"record_bytes":2560,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-5","last_task":3,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
