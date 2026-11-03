# Task 2: Record policy v2 pairs edited moves

The living record policy becomes `review-git-records/v2`: renames pair at 50%, one operation rule serves `_record_operations` and `edge_facts`, and a rename record never takes generated evidence (spec § Record policy v2, § Record shape, § One operation table; D1, D4, D5, D6, D15). This task also carries D11's proof that the retained domain stayed on v1 (D16).

Run every long command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with the timeout shown. `BASE` is `3be26be2878da02e4aa9417719f3388f08f0298c`.

**Files:**
- Modify: `python/agent_tools/review_actual.py`
- Modify: `python/agent_tools/review_forecast.py` (`edge_facts` parsing only)
- Modify: `python/README.md` (§ Review packaging and feasibility)
- Test: `home/common/agent-skills/tests/test_review_package.py`
- Test: `tests/test_review_record_view.py`, `tests/test_review_feasibility.py` (`RecordPolicyDomainTest` only), `tests/test_review_history.py`
- Test: `tests/retained_review_test_support.py`, `tests/test_review_issue121.py`, `tests/test_review_issue100.py`

**Interfaces:**
- Consumes (Task 1): `RECORD_POLICY_V1`, `_policies`, and the `record_policy` keyword of `git_diff`, `actual_inputs_from_trees`, `edge_facts` and `reconstruct_owned`.
- Produces in `agent_tools.review_actual`:
  - `RECORD_OPERATIONS = {"A": 1, "M": 1, "D": 1, "T": 1, "R": 2}`: names per operation letter (D15).
  - `record_operation(token: bytes, record_policy: Mapping = RECORD_POLICY) -> tuple[str, int]`: the decoded token and its name count.
  - `_record_operations(raw: bytes, paths: list[str], record_policy: Mapping) -> tuple[str, ...]`.
- Produces in `tests/retained_review_test_support.py`: `MOVE_LINES: bytes`, `linear_fixture(tmp, owners=…, touches=None, edited_move=None)` and `issue100_fixture(tmp, edited_move=False)`.

**Invariants:**
- The living `RECORD_POLICY` is its own literal (D14): Task 1's v1 content with `"kind": "review-git-records/v2"` and the first diff argument `"--find-renames=50%"`. Every other member is unchanged: `git_config` keeps `diff.renames=true`, `diff.renameLimit=0`, `core.quotePath=true`, and copies stay off. `PACKING_POLICY` keeps kind `review-packing/v1` and every rule; only its `record_policy_sha256` moves (D3).
- `record_operation` first calls `_policies(record_policy)`, so only the two policy objects pass. It decodes `token` as ASCII. `A`, `M`, `D` and `T` alone return `(token, 1)`. `R` plus exactly three digits returns `(token, 2)` when `floor <= score <= 100`; `floor` is the integer in the policy's one `--find-renames=<N>%` argument (50 for v2, 100 for v1). Everything else, non-ASCII included, raises `GenerationError("unsupported Git record operation")`.
- `_record_operations` reads each token through `record_operation(token, record_policy)` before it reads any name, then takes that many non-empty names. `actual_inputs_from_trees` passes its `record_policy`. Its other checks (framing, UTF-8, destinations equal to `paths`) are unchanged.
- `edge_facts` takes each token through `record_operation(token, record_policy)` before popping any name. A `GenerationError` from it becomes `ForecastError("unsupported Git record operation")`, with the cause chained, and a list too short for the name count raises `ForecastError("invalid Git status framing")`. A two-name record keeps today's `R100` shape: `operation` is the token, score included; `path` is the new path and `old_path` the old one; `before` is read at `old_path` and `after` at `path`.
- In `actual_inputs_from_trees`, a record whose operation starts with `R` is never replaced by generated evidence, however large (D5). Above the member limit it stays whole and the package exits 3 with `member_bytes`, never retried (`adaptive_violations` stays `["member_count", "aggregate_bytes"]`). `D`, `M`, `A` and `T` records keep today's evidence rules.
- No cap moves: `home/common/agent-skills/artifact-budget-policy.json` is byte-unchanged (AC2).

- [ ] **Step 1: Write the failing tests**

**1a. `home/common/agent-skills/tests/test_review_package.py`.** Add one independent argv constant after the `REPORT_VALIDATOR_STUB` block:

```python
# The review record argv, written out independently of `RECORD_POLICY` (issue 569: renames pair at 50%).
EXPECTED_DIFF = ("-c", "diff.renames=true", "-c", "diff.renameLimit=0", "-c", "core.quotePath=true", "diff",
                 "--find-renames=50%", "--no-ext-diff", "--no-textconv", "--full-index", "--no-relative",
                 "--src-prefix=a/", "--dst-prefix=b/", "--diff-algorithm=myers", "--no-indent-heuristic",
                 "--inter-hunk-context=0", "--no-color", "--line-prefix=", "--output-indicator-new=+",
                 "--output-indicator-old=-", "--output-indicator-context= ")
```

Replace the four spelled-out argv copies with `"git", "-C", str(repo), *EXPECTED_DIFF, …`, keeping each call's `--binary`, `-U<n>` and range arguments. The copies are in `test_source_path_workspace_and_every_fresh_context`, `test_small_range_has_one_complete_reconstructable_shard`, `test_fragmented_complete_diffs_use_bounded_adaptive_context_package` and `test_nine_complete_shards_stop_on_member_count_without_losing_coverage`. Afterwards `grep -c 'find-renames' home/common/agent-skills/tests/test_review_package.py` prints `1`.

In `test_exact_rename_of_an_oversized_file_keeps_its_rename_record`, add `self.assertNotIn(b"\n@@ ", packaged)` after its two `rename` assertions.

Replace `test_oversized_rename_with_edit_still_stops` with these six tests (AC1, AC2, AC3, AC4; the fixture fractions were probed with git 2.51.2: one-line-per-hunk edits score R099, every third line rewritten R066 with a 109,126 B record, every line rewritten no pair; the EF designer with every third line's table renamed scores R083 with a 188,435 B record). `test_oversized_ef_designer_rename_keeps_its_rename_section` is the one case that fails without the rename guard, because the EF designer contract holds at the new path (Standards review PR569-01):

```python
    def test_edited_move_is_one_rename_record_keyed_by_its_new_path(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env, page, base = self.page_repo(repo)
            page.unlink()
            moved = page.with_name("page-old.tsx")
            moved.write_text(page_text().replace("row0100", "moved0100").replace(
                "issue-439-distinctive-line", "issue-439-moved-line").replace("row0900", "moved0900"),
                encoding="utf-8")
            head = self.commit(repo, "move and edit page", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["coverage"], {"complete": True, "file_diff_count": 1})
            numstat = self.run_git(repo, *EXPECTED_DIFF, "--numstat", base, head)
            self.assertEqual(numstat, "3\t3\tlanding/src/app/app/{page.tsx => page-old.tsx}\n")
            self.assertEqual(manifest["stat"], {"files_changed": 1, "insertions": 3, "deletions": 3})
            packaged = self.shard_bytes(out, manifest)
            expected = subprocess.run(["git", "-C", str(repo), *EXPECTED_DIFF, "--binary", "-U10", base, head],
                                      capture_output=True, check=True).stdout
            self.assertEqual(packaged, expected)
            new = moved.relative_to(repo).as_posix()
            self.assertTrue(packaged.startswith(
                f"diff --git a/{PAGE} b/{new}\nsimilarity index 99%\nrename from {PAGE}\nrename to {new}\nindex "
                .encode()))
            lines = packaged.splitlines()
            body = lines[lines.index(f"+++ b/{new}".encode()) + 1:]
            self.assertEqual(sum(line.startswith(b"@@ ") for line in body), 3)
            self.assertEqual(sum(line.startswith(b"+") for line in body), 3)
            self.assertEqual(sum(line.startswith(b"-") for line in body), 3)
            self.assertNotIn(b"deleted file mode", packaged)
            self.assertNotIn(b"new file mode", packaged)

    def test_oversized_rename_record_stays_whole_and_stops(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env, page, base = self.page_repo(repo)
            page.unlink()
            page.with_name("page-old.tsx").write_text("\n".join(
                line.replace("export const", "export let") if number % 3 == 0 else line
                for number, line in enumerate(page_text().split("\n"))), encoding="utf-8")
            head = self.commit(repo, "move and rewrite a third of page", env)
            self.assertEqual(self.run_git(repo, *EXPECTED_DIFF, "--name-status", base, head).split("\t")[0], "R066")
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "decompose_required")
            self.assertIn("member_bytes", report["artifact"]["violations"])
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["interface_version"], 1)
            self.assertNotIn("generated_evidence", manifest)
            self.assertEqual(manifest["coverage"], {"complete": True, "file_diff_count": 1})
            packaged = self.shard_bytes(out, manifest)
            self.assertIn(f"rename from {PAGE}\n".encode(), packaged)
            self.assertGreater(len(packaged), 65_536)

    def test_oversized_ef_designer_rename_keeps_its_rename_section(self):
        # The EF designer contract holds at the new path, so only the rename guard keeps evidence out (D5).
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            old = repo / "src/App/Migrations/20260826010101_AddWidgets.Designer.cs"
            old.parent.mkdir(parents=True)
            old.write_text(EF_DESIGNER_TEXT, encoding="utf-8")
            base = self.commit(repo, "base", env)
            old.unlink()
            new = old.with_name("20260826010101_AddGadgets.Designer.cs")
            new.write_text("\n".join(
                line.replace('"widgets"', '"gadgets"') if number % 3 == 0 else line
                for number, line in enumerate(EF_DESIGNER_TEXT.split("\n"))), encoding="utf-8")
            head = self.commit(repo, "move and edit generated designer", env)
            self.assertTrue(self.run_git(repo, *EXPECTED_DIFF, "--name-status", base, head).startswith("R"))
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "decompose_required")
            self.assertIn("member_bytes", report["artifact"]["violations"])
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("generated_evidence", manifest)
            self.assertEqual(manifest["coverage"], {"complete": True, "file_diff_count": 1})
            packaged = self.shard_bytes(out, manifest)
            source, moved = (path.relative_to(repo).as_posix() for path in (old, new))
            self.assertTrue(packaged.startswith(f"diff --git a/{source} b/{moved}\n".encode()))
            self.assertIn(f"rename from {source}\nrename to {moved}\n".encode(), packaged)
            self.assertNotIn(b"review-package-generated-evidence", packaged)
            self.assertGreater(len(packaged), 65_536)

    def test_move_below_the_threshold_is_a_delete_and_an_add(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env, page, base = self.page_repo(repo)
            page.unlink()
            page.with_name("page-old.tsx").write_text(
                page_text().replace("export const", "export let"), encoding="utf-8")
            head = self.commit(repo, "move and rewrite every line of page", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 3, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "decompose_required")
            self.assertIn("member_bytes", report["artifact"]["violations"])
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["coverage"], {"complete": True, "file_diff_count": 2,
                                                    "byte_complete_file_count": 1, "generated_evidence_file_count": 1})
            self.assertEqual([(item["path"], item["kind"]) for item in manifest["generated_evidence"]],
                             [(PAGE, "whole-file-deletion")])
            self.assertGreater(max(item["bytes"] for item in manifest["shards"]), 65_536)

    def test_ambiguous_pairing_is_deterministic(self):
        body = "".join(f"shared line {n}\n" for n in range(30))
        moved = page_text().replace("issue-439-distinctive-line", "issue-439-moved-line")
        cases = (
            # One source, two equally similar destinations: the first destination path pairs.
            ({"a.txt": body}, {"a.txt": None, "b.txt": body + "b extra\n", "c.txt": body + "c extra\n"},
             [("b.txt", b"diff --git a/a.txt b/b.txt\nsimilarity index "),
              ("c.txt", b"diff --git a/c.txt b/c.txt\nnew file mode ")], 0),
            # Two identical oversized sources, one destination: the first source path pairs, and the unpaired
            # source keeps its whole-file deletion evidence.
            ({"p1.tsx": page_text(), "p2.tsx": page_text()}, {"p1.tsx": None, "p2.tsx": None, "q.tsx": moved},
             [("p2.tsx", b'{"review-package-generated-evidence":'),
              ("q.tsx", b"diff --git a/p1.tsx b/q.tsx\nsimilarity index 99%\n")], 1),
        )
        limits = ReviewLimits(16384, 65536, 8, 524288)
        for before, after, expected, generated in cases:
            with self.subTest(paths=sorted(after)), tempfile.TemporaryDirectory() as raw:
                repo = Path(raw)
                plan, env = self.setup_repo(repo)
                for name, text in before.items():
                    (repo / name).write_text(text, encoding="utf-8")
                base = self.commit(repo, "base", env)
                for name, text in after.items():
                    if text is None:
                        (repo / name).unlink()
                    else:
                        (repo / name).write_text(text, encoding="utf-8")
                head = self.commit(repo, "ambiguous move", env)
                runs = []
                for number in range(3):
                    destination = repo / f"output-{number}"
                    destination.mkdir()
                    out = destination / "review.json"
                    result = self.invoke(repo, plan, base, head, out, env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    runs.append((out.read_bytes(), self.shard_bytes(out, json.loads(out.read_bytes()))))
                self.assertTrue(all(run == runs[0] for run in runs))
                manifest = json.loads(runs[0][0])
                self.assertEqual((manifest["coverage"]["complete"], manifest["coverage"]["file_diff_count"]),
                                 (True, 2))
                self.assertEqual(len(manifest.get("generated_evidence", [])), generated)
                trees = [self.run_git(repo, "rev-parse", f"{sha}^{{tree}}").strip() for sha in (base, head)]
                initial = next(actual_inputs_from_trees(repo, *trees, base=base, head=head, commits=(),
                                                        package_name="review.json", limits=limits))
                self.assertEqual([record.path for record in initial.records], [path for path, _ in expected])
                for record, (_, prefix) in zip(initial.records, expected):
                    self.assertTrue(record.payload.startswith(prefix), record.payload[:80])

    def test_exact_rename_with_a_mode_change_stays_header_only(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            plan, env = self.setup_repo(repo)
            script = repo / "x.sh"
            script.write_text("#!/bin/sh\necho moved\n" * 5, encoding="utf-8")
            script.chmod(0o755)
            base = self.commit(repo, "base", env)
            script.rename(repo / "y.sh")
            (repo / "y.sh").chmod(0o644)
            head = self.commit(repo, "move and drop the executable bit", env)
            out = repo / "review.json"

            result = self.invoke(repo, plan, base, head, out, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stat"], {"files_changed": 1, "insertions": 0, "deletions": 0})
            self.assertEqual(self.shard_bytes(out, manifest),
                             b"diff --git a/x.sh b/y.sh\nold mode 100755\nnew mode 100644\n"
                             b"similarity index 100%\nrename from x.sh\nrename to y.sh\n")
```

**1b. `tests/test_review_record_view.py`.** In `NEUTRALISED_BY`, the `diff.renames` and `diff.renameLimit` rows name `"--find-renames=50%"` instead of `"--find-renames=100%"`. The `RENAMED` comment becomes `# Two deleted files and one added near-copy of the first: an inexact rename that the policy pairs and that a rename limit of 1 or \`diff.renames=false\` would split.` (two comment lines). Add before `test_every_hostile_source_at_once`:

```python
    def test_the_inexact_rename_is_one_record_keyed_by_its_new_path(self):
        """Issue 569: the near-copy pairs with `r1.txt` under the policy's threshold; `r2.txt` stays a deletion."""
        inputs, _, _ = self.clean
        records = {record.path: record.payload for record in inputs[0].records}
        self.assertNotIn("r1.txt", records)
        self.assertTrue(records["r3.txt"].startswith(
            b"diff --git a/r1.txt b/r3.txt\nsimilarity index 96%\nrename from r1.txt\nrename to r3.txt\n"),
            records["r3.txt"][:120])
        self.assertIn(b"\n+extra\n", records["r3.txt"])
        self.assertIn(b"deleted file mode 100644\n", records["r2.txt"])
```

The hostile `diff.renames` and `diff.renameLimit` cases then prove that the policy keeps that pair.

**1c. `tests/test_review_feasibility.py`.** Add to `RecordPolicyDomainTest` (Task 1):

```python
    def test_living_policy_is_v2_with_a_fifty_percent_rename_threshold(self):
        from agent_tools.review_actual import (PACKING_POLICY, PACKING_POLICY_SHA256, PACKING_POLICY_V1_SHA256,
            RECORD_POLICY, RECORD_POLICY_SHA256, RECORD_POLICY_V1)
        self.assertEqual(RECORD_POLICY, {**RECORD_POLICY_V1, 'kind': 'review-git-records/v2',
                                         'diff_args': ['--find-renames=50%', *RECORD_POLICY_V1['diff_args'][1:]]})
        self.assertEqual(RECORD_POLICY_V1['diff_args'][0], '--find-renames=100%')
        self.assertEqual(RECORD_POLICY['git_config'], ['-c', 'diff.renames=true', '-c', 'diff.renameLimit=0',
                                                       '-c', 'core.quotePath=true'])
        self.assertEqual((PACKING_POLICY['kind'], PACKING_POLICY['record_policy_sha256']),
                         ('review-packing/v1', RECORD_POLICY_SHA256))
        self.assertNotEqual(PACKING_POLICY_SHA256, PACKING_POLICY_V1_SHA256)
        self.assertEqual(PACKING_POLICY['adaptive_violations'], ['member_count', 'aggregate_bytes'])

    def test_operation_rule_follows_each_policy_threshold(self):
        from agent_tools.review_actual import RECORD_POLICY, RECORD_POLICY_V1, GenerationError, _record_operations
        accepted = ((RECORD_POLICY, b'R050\0old\0new\0', ['new'], ('R050',)),
                    (RECORD_POLICY, b'R100\0old\0new\0M\0kept\0', ['new', 'kept'], ('R100', 'M')),
                    (RECORD_POLICY_V1, b'R100\0old\0new\0', ['new'], ('R100',)),
                    (RECORD_POLICY_V1, b'A\0a\0D\0d\0T\0t\0', ['a', 'd', 't'], ('A', 'D', 'T')))
        for policy, raw, paths, expected in accepted:
            with self.subTest(raw=raw, policy=policy['kind']):
                self.assertEqual(_record_operations(raw, paths, policy), expected)
        refused = ((RECORD_POLICY, b'R049\0old\0new\0', ['new']),
                   (RECORD_POLICY_V1, b'R099\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R101\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R50\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'C100\0old\0new\0', ['new']),
                   (RECORD_POLICY, b'R100\0old\0new\0extra\0', ['new', 'extra']),
                   (RECORD_POLICY, b'R100\0old\0', ['old']))
        for policy, raw, paths in refused:
            with self.subTest(raw=raw, policy=policy['kind']), self.assertRaises(GenerationError):
                _record_operations(raw, paths, policy)
```

**1d. `tests/test_review_history.py`.** In `test_rehashed_original_edge_mutation_is_invalid_at_prerequisite_boundary`, import `record_operation` beside `git_diff`. The local status loop then reads `operation, count = record_operation(names.pop(0))` and `new = names.pop(0).decode('utf-8') if count == 2 else old`, and drops its own `assertIn(operation, ('A', 'M', 'D', 'T', 'R100'))`.

**1e. Retained proof (D11, D16).** In `tests/retained_review_test_support.py`:
- Add `MOVE_LINES = b"".join(b"move %d\n" % n for n in range(40))` after `PLAN_PREFIX`.
- Give `linear_fixture` the keyword `edited_move=None`. When it is an index `k`, the signed base commit also writes `src/move.txt` = `MOVE_LINES`. Commit `k` also deletes `src/move.txt` and writes `src/moved.txt` = `MOVE_LINES.replace(b"move 20\n", b"moved 20\n")`.
- Extend the docstring: `With \`edited_move=k\`, the base also writes \`src/move.txt\` (\`MOVE_LINES\`) and commit \`k\` moves it to \`src/moved.txt\` with one line edited: an inexact rename that only a pairing threshold below 100% joins.`
- With the default `None` the repository is byte-identical to today's.

In `tests/test_review_issue121.py`, import `edge_facts` beside `ForecastError`. Add, before `class AncestryTest`:

```python
class RetainedDomainTest(Fixture, unittest.TestCase):
    def test_edited_move_measures_as_a_v1_delete_and_add(self):
        """Issue 569: every retained measurement runs under the frozen `review-git-records/v1`, so an edited move
        is a deletion and an addition that the retained validators accept. The living policy pairs the same edge
        as an inexact rename, which they refuse."""
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp)
        repo, pins, task7_pins, table, authority = self.build(tmp, edited_move=2)
        mover = pins.assignments[2][0]
        model = model_121(repo, pins, task7_pins, authority)
        self.assertEqual(validated(model, pins, table), model)
        edge = next(e for e in model["edges"] if e["commit"] == mover)
        self.assertEqual([(r["operation"], r["path"]) for r in edge["records"]],
                         [("A", "src/c2.txt"), ("D", "src/move.txt"), ("A", "src/moved.txt")])
        self.assertEqual([(o["boundary"], o["state"]) for o in outcomes(model)],
                         [(label, "measured") for label in LABELS])
        for scope in ("aggregate.actual", "aggregate.projected", "tasks-1-3"):
            paths = {r["path"] for r in model["records"] if r["scope"] == scope}
            self.assertLessEqual({"src/move.txt", "src/moved.txt"}, paths, scope)
        living = edge_facts(repo, edge["parent"], mover, 1)
        self.assertEqual([(r["operation"], r["old_path"], r["path"]) for r in living["records"]],
                         [("A", "src/c2.txt", "src/c2.txt"), ("R097", "src/move.txt", "src/moved.txt")])
```

In `test_rehashed_malformed_edge_fact_is_invalid`, add the case `"living_policy_rename": {"operation": "R097", "old_path": "src/elsewhere.txt", "before": entry},` after `"rename_under_an_add"`.

**1f. The issue-100 call sites (D16).** Give `issue100_fixture` the keyword `edited_move=False`. When true:
- the base commit also writes `src/move.txt` = `b"".join(b"move %d\n" % n for n in range(40))`;
- `c2` also deletes it and writes `src/moved.txt` = that content with `b"move 20\n"` replaced by `b"moved 20\n"`;
- the counts take `counts.update(edge_records=24, contributions=10, candidate=8, candidate_ordinary=6)`, with the comment `# c2's edge and the merge's second-parent edge each gain D and A; two more candidates`.

Add to the docstring: `With \`edited_move\`, the base also writes \`src/move.txt\` and c2 moves it to \`src/moved.txt\` with one line edited.` The default is byte-identical to today's fixture. In `tests/test_review_issue100.py`, import `edge_facts` beside `ForecastError` and add to `Issue100Test`:

```python
    def test_edited_move_measures_as_a_v1_delete_and_add(self):
        """Issue 569: the fresh domain and the raw edges measure under the frozen `review-git-records/v1`, so an
        edited move is a deletion and an addition; the historical recipe and the living policy pair it."""
        tmp = Path(tempfile.mkdtemp(dir=self.tmp))
        repo, live, archive, pins = issue100_fixture(tmp, edited_move=True)
        payload = model_100(repo, live, archive, pins, self.limits)
        self.assertEqual(validated(payload, pins), payload)
        fresh = [record["path"] for record in fresh_records(repo, pins, self.limits)]
        self.assertLessEqual({"src/move.txt", "src/moved.txt"}, set(fresh))
        self.assertEqual((pins.historical.records, pins.fresh.records), (len(fresh) - 1, len(fresh)))
        mover = git(repo, "rev-list", "-1", "main", "--", "src/moved.txt")
        edge = next(e for e in payload["edges"]
                    if e["commit"] == mover and any(r["path"] == "src/moved.txt" for r in e["records"]))
        self.assertEqual([(r["operation"], r["path"]) for r in edge["records"] if "move" in r["path"]],
                         [("D", "src/move.txt"), ("A", "src/moved.txt")])
        living = edge_facts(repo, edge["parent"], mover, 1)
        self.assertEqual([(r["operation"], r["old_path"]) for r in living["records"] if r["path"] == "src/moved.txt"],
                         [("R097", "src/move.txt")])
```

While planning, each of two mutations made this case error: leaving `fresh_records` on the living policy (`domain_mismatch`), and leaving `model_100`'s `edge_facts` on it (`invalid_payload`). Dropping v1 from `contribution_edges` made the issue-121 case error (`edge_record_mismatch`).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH=python timeout 900 python3 -m unittest -k rename -k move -k ambiguous -k threshold home/common/agent-skills/tests/test_review_package.py tests/test_review_record_view.py tests/test_review_feasibility.py tests/test_review_issue121.py tests/test_review_issue100.py 2>&1 | grep -E '^(FAIL|ERROR):' | sed 's/ (.*//' | sort -u`
Expected, at Task 1's head:
- `test_ambiguous_pairing_is_deterministic`, `test_edited_move_is_one_rename_record_keyed_by_its_new_path`, `test_oversized_rename_record_stays_whole_and_stops`, `test_oversized_ef_designer_rename_keeps_its_rename_section`, `test_the_inexact_rename_is_one_record_keyed_by_its_new_path` and `test_living_policy_is_v2_with_a_fifty_percent_rename_threshold` all fail.
- Both `test_edited_move_measures_as_a_v1_delete_and_add` cases fail too: their living-policy control still reads `D`/`A`.
- `test_operation_rule_follows_each_policy_threshold` errors on `_record_operations`' arity.
- `test_move_below_the_threshold_is_a_delete_and_an_add` and `test_exact_rename_with_a_mode_change_stays_header_only` pass both before and after: they guard what must not change.

- [ ] **Step 3: Implement**

1. `review_actual.py`: rewrite the `RECORD_POLICY` literal per the invariants. Replace the `RECORD_OPERATIONS` tuple with the table. Add `record_operation` after `_packing_choices`, with this docstring: `"""\`token\`, one \`--name-status -z\` operation field, under \`record_policy\`, and how many names follow it. \`A\`, \`M\`, \`D\` and \`T\` take one name. \`R<score>\` takes two, old then new, when its three-digit score is at least the floor in the policy's \`--find-renames=<N>%\` argument and at most 100. Anything else is refused (issue 569)."""`. `_record_operations` takes `record_policy` and calls `record_operation`; `actual_inputs_from_trees` passes it. Guard the generated-evidence branch with `and not operation.startswith("R")` and the comment `# A rename record keeps its whole section: generated evidence reads one path's sides (issue 569).`
2. `review_forecast.py`: import `GenerationError` and `record_operation`, and rework `edge_facts`' loop per the invariants.
3. `python/README.md`, § Review packaging and feasibility:
   - After the paragraph that starts `Actual production and generic projection share packing`, add: `Fresh measurement (\`review-package\`, the \`review-feasibility\` \`project\`, \`gate\` and \`confirm\` commands, and the forecast's ownership evidence) runs Git under the record policy \`review-git-records/v2\`, in a view of the repository's objects that no configuration, attribute or environment source reaches (#255, #569). The policy pairs a deleted path with an added one at an explicit \`--find-renames=50%\`, with copy detection off and an unlimited rename search (\`diff.renameLimit=0\`). The pairing is Git's own: the best score wins, a tie goes to Git's own order, and each source pairs at most once, so one Git version always pairs the same way. A paired move is one record keyed by its new path. It is Git's \`diff --git a/<old> b/<new>\` section: any mode lines, \`similarity index\`, \`rename from\`, \`rename to\` and every hunk of the old blob against the new one, or that header alone for an exact move. The old path has no record of its own. An unpaired source stays a deletion and an unpaired destination an addition, so a move below 50% similarity is a deletion plus a whole-file addition. A feasibility summary saved under an earlier policy no longer confirms, because its \`packing_policy_sha256\` differs.`
   - In the next paragraph, replace `; any other oversized file diff stays whole, and the package is \`decompose_required\`.` with `. A rename record never takes generated evidence. Any other oversized file diff stays whole, and the package is \`decompose_required\`.`

- [ ] **Step 4: Verify**

Run Step 2's command: no `FAIL`/`ERROR` line.

Run: `env PYTHONPATH=python timeout 1800 python3 -m agent_tools.suite_runner --jobs 4 home/common/agent-skills/tests/test_review_package.py tests/test_review_record_view.py tests/test_review_feasibility.py tests/test_review_projection_cases.py tests/test_review_history.py tests/test_review_evidence.py tests/test_review_witness.py tests/test_review_derivation.py tests/test_review_issue100.py tests/test_review_issue121.py tests/test_review_task7.py tests/test_review_compact100.py tests/test_review_compact121.py tests/test_review_replay.py 2>&1 | grep -E 'suite-runner: (failed|summary)'`
Expected: `suite-runner: summary members=14 passed=14 failed=0 …`.

```bash
git diff --quiet 3be26be2878da02e4aa9417719f3388f08f0298c -- home/common/agent-skills/artifact-budget-policy.json tests/fixtures/retained-review-evidence tests/retained_evidence_test_support.py
test "$(grep -c 'find-renames' home/common/agent-skills/tests/test_review_package.py)" = 1
if grep -n 'R100' python/agent_tools/review_actual.py python/agent_tools/review_forecast.py; then exit 1; fi
```

Expected: exit 0 and no output. Neither module names a rename token any more: the floor comes from the policy.

- [ ] **Step 5: Commit**

Stage exactly the Files above, then `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(review): pair edited moves as rename records (v2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"d4d4d0801a04a8befe222aa327fa315e1decf639","head":"7b61ee2888686f38974ec111ac2a11cc8780622e"}],"commit_subject_bytes":[64,64,64,64],"id":2,"records":[{"bounds":[{"added_lines":100,"boundary":"all","deleted_lines":45,"record_bytes":22528,"support":{"covers":["r1a","r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"python/agent_tools/review_actual.py"},{"bounds":[{"added_lines":18,"boundary":"all","deleted_lines":10,"record_bytes":9216,"support":{"covers":["r1b","r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":3,"owner":2,"path":"python/agent_tools/review_forecast.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":22528,"support":{"covers":["r1i","r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":3,"owner":2,"path":"python/README.md"},{"bounds":[{"added_lines":165,"boundary":"all","deleted_lines":50,"record_bytes":30720,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_review_package.py"},{"bounds":[{"added_lines":16,"boundary":"all","deleted_lines":4,"record_bytes":7168,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"tests/test_review_record_view.py"},{"bounds":[{"added_lines":75,"boundary":"all","deleted_lines":0,"record_bytes":13312,"support":{"covers":["r1j","r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":3,"owner":2,"path":"tests/test_review_feasibility.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":4,"record_bytes":5120,"support":{"covers":["r2g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2g","last_task":2,"owner":2,"path":"tests/test_review_history.py"},{"bounds":[{"added_lines":25,"boundary":"all","deleted_lines":6,"record_bytes":14336,"support":{"covers":["r1k","r2h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2h","last_task":2,"owner":2,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":26,"boundary":"all","deleted_lines":2,"record_bytes":7168,"support":{"covers":["r2i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2i","last_task":2,"owner":2,"path":"tests/test_review_issue121.py"},{"bounds":[{"added_lines":24,"boundary":"all","deleted_lines":3,"record_bytes":9216,"support":{"covers":["r1n","r2j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2j","last_task":2,"owner":2,"path":"tests/test_review_issue100.py"}]}}
```
