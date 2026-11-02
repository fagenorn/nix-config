# Task 2: Rollup module, medians and the two sub-totals

**Files:**
- Create: `python/agent_tools/agent_boot_rollup.py`
- Modify: `python/agent_tools/agent_boot_report.py`
- Modify: `python/README.md`
- Test: `tests/test_agent_boot_report.py`

**Interfaces:**
- Consumes: from Task 1, the test helpers `bash(command)`, `read(path, **extent)` and `stepped_boot(session, agent, seconds, steps, *, issue=7)`. `stepped_boot` writes a fresh owner (launch 2, phase 6) whose call 0 is at 20,000 and splits into `tool_schemas` 19,800, `harness` 100 and `prompt` 100. Each `(tool, size)` step's result holds `size` characters, and the next call grows by `size + 40`, so the step's bucket gets `size` and `assistant` gets 40. The last call registers.
- Produces, in the new `agent_tools.agent_boot_rollup` (pure, no I/O, imports nothing from `agent_boot_report`, per D7 and D9):
  - `ALL = "all"`, `COHORTS = ("fresh", "spawned")`, `PHASE_GROUPS = ("0-5", "6-7", ALL)`, moved here from `agent_boot_report`, which now imports `ALL` from the rollup.
  - `median(values, weights=None) -> float | None`.
  - `group_rows(host: str, boots: list[dict], buckets: tuple[str, ...]) -> list[dict]`, which replaces `agent_boot_report._group_rows`.
- Produces, in `agent_tools.agent_boot_report`:
  - `BOOT_READING = ("skill_bodies", "skill_files", "plan_reads", "resume_reads", "rereads")` and `FIRST_UNIT_WORK = ("commands", "assistant", "other_reads")`.
  - Boot rows gain `boot_reading` and `first_unit_work` right after `b`.
  - `SCHEMA_VERSION = 2` (D6).

**Invariants:**
- Group row means are today's (`statistics.fmean` per boot). An `all` row pools the boots and is never a mean of means. A group with no boot has no row. Rows keep today's order.
- `median` follows D4. With no weights it equals `statistics.median`, and every median it returns is a float (D10). It returns `None` for no values.
- `b`, `start`, `buckets` and the boot's end are unchanged. `tool_schemas`, `harness`, `prompt` and `unexplained` are in neither sub-total.
- Every existing test passes unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_boot_report.py`, add `import re` to the imports. Add these tests to `BootReportTest`:

```python
    def test_group_rows_carry_medians_and_both_sub_totals(self):
        session = Session(self.root)
        sizes = ((1_000, 1_000, 1_000), (2_000, 3_000, 1_000), (4_000, 1_000, 2_000),
                 (9_000, 2_000, 6_000))  # result characters of (plan read, other read, command)
        for issue, (plan, other, command) in enumerate(sizes, start=7):
            stepped_boot(session, f"o{issue}", 100 * issue, [
                (read(f"{PLANS}/2026-10-26-x.md"), plan), (read("/r/src/app.py"), other),
                (bash("ls /r"), command)], issue=issue)
        session.write()
        document = report(self.root)
        for row in document["boots"]:
            self.assertEqual(row["boot_reading"], sum(row["buckets"][name] for name in (
                "skill_bodies", "skill_files", "plan_reads", "resume_reads", "rereads")))
            self.assertEqual(row["first_unit_work"], sum(row["buckets"][name] for name in (
                "commands", "assistant", "other_reads")))
        self.assertEqual(
            sorted((row["b"], row["boot_reading"], row["first_unit_work"])
                   for row in document["boots"]),
            [(23_120, 1_000, 2_120), (26_120, 2_000, 4_120), (27_120, 4_000, 3_120),
             (37_120, 9_000, 8_120)])
        pooled = next(g for g in document["groups"]
                      if (g["host"], g["cohort"], g["phase_group"]) == ("all", "fresh", "all"))
        # Four boots, so each median is the mean of the middle two (B: 23,120 26,120 27,120
        # 37,120; without schemas, B less 19,800).
        self.assertEqual(
            {name: pooled[name] for name in (
                "count", "b_mean", "b_median", "b_without_schemas_mean",
                "b_without_schemas_median", "boot_reading_mean", "boot_reading_median",
                "first_unit_work_mean", "first_unit_work_median")},
            {"count": 4, "b_mean": 28_370, "b_median": 26_620, "b_without_schemas_mean": 8_570,
             "b_without_schemas_median": 6_820, "boot_reading_mean": 4_000,
             "boot_reading_median": 3_000, "first_unit_work_mean": 4_370,
             "first_unit_work_median": 3_620})
        self.assertEqual(pooled["buckets"], buckets(
            tool_schemas=19_800, harness=100, prompt=100, plan_reads=4_000, other_reads=1_750,
            commands=2_500, assistant=120))
        self.assertEqual(pooled["bucket_medians"], buckets(
            tool_schemas=19_800, harness=100, prompt=100, plan_reads=3_000, other_reads=1_500,
            commands=1_500, assistant=120))
        self.assertEqual(document["schema_version"], 2)

    def test_text_output_prints_medians_beside_means_and_the_sub_total_rows(self):
        session = Session(self.root)
        stepped_boot(session, "o7", 0, [(read(f"{PLANS}/2026-10-26-x.md"), 1_000),
                                        (bash("ls /r"), 1_000)])
        session.write()
        completed = costs("--days", "0", "--projects-dir", str(self.root))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        self.assertRegex(out, r"(?m)fresh 6-7 +median +fresh all +median$")
        self.assertRegex(out, r"(?m)^kind +key +mean +median$")
        self.assertRegex(out, r"\bB +boot reading +first-unit work +tool_schemas\b")
        positions = [re.search(pattern, out, re.M).start() for pattern in (
            r"^unexplained ", r"^boot reading ", r"^first-unit work ", r"^B ",
            r"^B without tool schemas ")]
        self.assertEqual(positions, sorted(positions))
```

Planning ran the first fixture through the base report: `b` 23,120, 26,120, 27,120 and 37,120, with the bucket values above.

- [ ] **Step 2: Run the tests and watch them fail**

Run the Boot tests (Global Constraints) with `-k medians`.
Expected: FAIL. The first test hits `KeyError: 'boot_reading'`. The second fails its first `assertRegex`, because there is no `median` column.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/agent_boot_rollup.py`, new. Its module docstring: "The boot report's group rows, built from boot rows (issues 448, 504). Pure statistics over the boot rows agent_tools.agent_boot_report collects: per host, cohort and phase group, the count and the mean and median per boot. python/README.md (agent-costs) holds the contract." It imports `statistics` only.
- `median(values, weights=None)`. Make `values` a list. Pair each value with its weight (each weight is 1 without `weights`) and sort the pairs. `total` is the sum of the weights. Walk the pairs adding to `cumulative`:
  - when `2 * cumulative == total`, return `(value + next value) / 2`;
  - when `2 * cumulative > total`, return `float(value)`.

  Return `None` when there are no values. The doubled comparison keeps the half test exact for int and `fractions.Fraction` weights (D4). Docstring: "The median of `values`, a float, or None when there are none. Each value has its weight in `weights` (1 each without), and weights are positive ints or Fractions. It is the first value in sorted order whose cumulative weight reaches half the total, or the mean of that value and the next when the cumulative weight is exactly half. With equal weights that is `statistics.median` (issue 504 D4)."
- `group_rows(host, boots, buckets)` is today's `_group_rows` with the same member selection, order and skipping. Each row is built in this exact key order: `host, cohort, phase_group, count, b_mean, b_median, b_without_schemas_mean, b_without_schemas_median, boot_reading_mean, boot_reading_median, first_unit_work_mean, first_unit_work_median, buckets, bucket_medians`.
  - Each `*_mean` is `statistics.fmean` and each `*_median` is `median`, over the members' `b`, `b - buckets["tool_schemas"]`, `boot_reading` and `first_unit_work`.
  - `buckets` maps each name of the `buckets` argument to the members' mean, and `bucket_medians` maps the same names to the median.

  Docstring: "The group rows of one host's `boots` (`host` is a label or ALL). There is one row per cohort and phase group (ALL pools both) that has a boot, in COHORTS × PHASE_GROUPS order. A row holds the count and the per-boot mean and median of B, B without tool schemas, both sub-totals and each of `buckets`."

`python/agent_tools/agent_boot_report.py`:
- Delete `ALL`, `COHORTS`, `PHASE_GROUPS` and `_group_rows`. Import `ALL`, `group_rows` and `median` from `agent_tools.agent_boot_rollup`.
- Add `BOOT_READING` and `FIRST_UNIT_WORK` after `BUCKETS`. In `collect_host`, the boot row gets `"boot_reading": sum(result["buckets"][name] for name in BOOT_READING)` and `"first_unit_work"` (the same over `FIRST_UNIT_WORK`), right after `"b"`.
- `build_document` calls `group_rows(label, boots, BUCKETS)`. Set `SCHEMA_VERSION = 2`.
- Add `_tokens(value)`, which returns `"-"` for `None`, else `human(round(value))`. Use it for every token cell below.
- `_mean_table`:
  - Headers: `""`, then for each group `f"{cohort} {phase_group}"` and `"median"`. Alignment: `"l"`, then `"r"` for every other column.
  - The `boots` row puts the count under the group's column and `""` under `median` (D11).
  - Then one row per bucket: the mean from `buckets`, the median from `bucket_medians`.
  - Then `boot reading` (`boot_reading_mean`, `boot_reading_median`), `first-unit work` (`first_unit_work_mean`, `first_unit_work_median`), `B` (`b_mean`, `b_median`) and `B without tool schemas` (`b_without_schemas_mean`, `b_without_schemas_median`).
- `_top_skills` keeps each key's per-fresh-boot values (0 for a boot without the key). Its rows are `[kind, key, _tokens(mean), _tokens(median(values))]`, sorted by mean as today. Its heading becomes `Top skill bodies and skill files (mean and median tokens per fresh boot, all hosts):`, its headers `["kind", "key", "mean", "median"]` and its alignment `["l", "l", "r", "r"]` (`print_table` takes one alignment per header).
- The boots table adds `human(boot["boot_reading"])` and `human(boot["first_unit_work"])` after `B`, with headers `boot reading` and `first-unit work` (alignment `"r"`). Its heading becomes `Boots by B (host, issue, cohort, phase, calls, start, B, boot reading, first-unit work, then each bucket):`.
- Module docstring: add that `agent_tools.agent_boot_rollup` builds the group rows.

`python/README.md`, **Boot report (issue 448)** paragraph and its sub-paragraphs:
- Replace `` (`schema_version` 1) `` with `` (`schema_version` 2; version 2 adds the boot row keys `boot_reading` and `first_unit_work` and the group row medians and sub-totals, so the key sets a version 1 reader pins no longer match, issue 504 D6) ``.
- Add a paragraph between *Buckets.* and *Document.*:

  > *Sub-totals and medians (issue 504).* A boot's `boot_reading` is the sum of its `skill_bodies`, `skill_files`, `plan_reads`, `resume_reads` and `rereads`, and its `first_unit_work` the sum of its `commands`, `assistant` and `other_reads`. `tool_schemas`, `harness`, `prompt` and `unexplained` are in neither, and `b` is unchanged. A median is `statistics.median`'s: the middle value, or the mean of the two middle values for an even count. Every mean and median in the document is a float.

- *Document.*:
  - The boot row list gains `boot_reading, first_unit_work` after `b`.
  - Replace the group row sentence with: "A group row holds exactly `host, cohort, phase_group, count, b_mean, b_median, b_without_schemas_mean, b_without_schemas_median, boot_reading_mean, boot_reading_median, first_unit_work_mean, first_unit_work_median, buckets, bucket_medians`, the means and medians being per boot. `buckets` holds the twelve bucket means and `bucket_medians` their medians."

Check each README clause against the code you wrote, and correct the README wherever they differ.

- [ ] **Step 4: Verify**

Run the Boot tests (Global Constraints), whole module.
Expected: `Ran 17 tests`, `OK`.

Run: `if grep -nE "^(ALL|COHORTS|PHASE_GROUPS) =|def _group_rows" python/agent_tools/agent_boot_report.py; then exit 1; fi; if grep -nE "^ *(from|import) .*agent_boot_report" python/agent_tools/agent_boot_rollup.py; then exit 1; fi`
Expected: exit 0, with no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_boot_rollup.py python/agent_tools/agent_boot_report.py \
  python/README.md tests/test_agent_boot_report.py
launch-commit --repo-root <ledger repo root> --run-id <run id> --worker-id <worker id> -- \
  -m "feat(boot-report): add medians and the reading and first-unit sub-totals" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"47bcd47c928919ef505df67fde2638d7f1bfd535","head":"6ba26ce0b972a08994f9ab95dfea00f933e4323e"}],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2a","last_task":4,"owner":2,"path":"python/agent_tools/agent_boot_rollup.py"},{"bounds":[{"added_lines":100,"boundary":"all","deleted_lines":55,"record_bytes":28672,"support":{"covers":["r1a","r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":4,"owner":2,"path":"python/agent_tools/agent_boot_report.py"},{"bounds":[{"added_lines":135,"boundary":"all","deleted_lines":1,"record_bytes":16384,"support":{"covers":["r1b","r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":4,"owner":2,"path":"tests/test_agent_boot_report.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":3,"record_bytes":32768,"support":{"covers":["r1c","r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":4,"owner":2,"path":"python/README.md"}]}}
```
