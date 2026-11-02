# Task 4: Reweighting to the baseline's host × phase group × project mix

**Files:**
- Modify: `python/agent_tools/agent_boot_rollup.py`
- Modify: `python/agent_tools/agent_boot_report.py`
- Modify: `python/README.md`
- Test: `tests/test_agent_boot_report.py`

**Interfaces:**
- Consumes:
  - From Task 2: `agent_boot_rollup.median(values, weights=None) -> float | None`. Weights are positive ints or `fractions.Fraction`s. The result is the first sorted value whose cumulative weight reaches half the total, or the mean of it and the next at exactly half (D4).
  - From Task 3: boot rows with `arm, host, …, project, cohort, phase_group, …, b, …, buckets`; group rows from `group_rows(arm, host, boots, buckets)`, starting `arm, host, cohort, phase_group, count, b_mean, b_median, b_without_schemas_mean, b_without_schemas_median`, in arm order; and `build_document(collected, *, window)` with `reweighted` `None`.
  - Task 3's test fixtures in `tests/test_agent_boot_report.py`: `BASELINE` (`2026-10-25T09:00:00Z..2026-10-25T10:00:00Z`), `EVENTS` (`--events-since 2026-10-25T10:00:00Z --events-before 2026-10-25T11:00:00Z`), and `WindowsTest.write_boots(boots)`. `write_boots` writes one fresh owner (launch 2) per `(seconds after T0, issue, project, phase, start, end)` through `two_call_boot`, registering with `--repo-root /Users/me/<project>`. Such a boot has `b = end`, `tool_schemas = start - 200` and so B without tool schemas `end - start + 200`.
  - `WINDOW_BOOTS`. Baseline window: (100, 11, alpha, 6, 24,000, 40,000), (200, 12, beta, 6, 28,000, 52,000), (300, 13, beta, 6, 28,000, 54,000), (400, 14, beta, 6, 28,000, 56,000). Event window: (3,700, 21, alpha, 6, 20,000, 30,000), (3,800, 22, alpha, 6, 21,000, 32,000), (3,900, 23, alpha, 6, 22,000, 34,000), (4,000, 24, beta, 6, 26,000, 50,000). After both windows: (7,300, 31, alpha, 6, 20,000, 99,000).
- Produces: `agent_boot_rollup.reweighted_rows(groups, baseline, candidate) -> list[dict]`, and the document's `reweighted` list with `--baseline`.

**Invariants:**
- One reweighted row per candidate group row, in that row's order (D3). Each row is exactly `host, cohort, phase_group, common_strata, baseline, candidate`, and each side exactly `count, b_mean, b_median, b_without_schemas_mean, b_without_schemas_median`.
- A stratum is `(host, phase_group, project)` within one cohort. A row's strata are those it pools: its host, or every host for `all`; its phase group, or both for `all`; and every project. `K` is the strata in which both arms have boots. Strata in one arm only drop out. With `K` empty, both counts and `common_strata` are 0 and every statistic is `None`.
- Candidate side: `count = Σ_K n1(s)`. The means are the weighted mean `Σ w·x / Σ w` over the candidate's boots in `K` with `w = Fraction(n0(s), n1(s))`, computed exactly and rounded to float once (D10). The medians are `median(values, weights)` with the same weights.
- Baseline side: `count = N0`, with the same mean function at weight 1 and the plain `median`. When the candidate holds every baseline stratum in scope, it equals the baseline group row's figures.
- Only B and B without tool schemas are reweighted. Buckets, sub-totals and top skills stay per arm. Without `--baseline`, `reweighted` stays `None`.

- [ ] **Step 1: Write the failing tests**

Extend Task 3's `WindowsTest.write_boots(boots, root=None)`: it writes under `root` (default `self.root`), and a boot tuple may carry a seventh element, its launch (default 2; launch 1 alone in its lineage is `spawned`). In `tests/test_agent_boot_report.py`, add after `WINDOW_BOOTS`:

```python
COVERAGE_BOOTS = (  # baseline: alpha and delta in 6-7; event window: alpha and gamma in 6-7, alpha in 0-5
    (100, 11, "alpha", 6, 24_000, 40_000), (200, 12, "delta", 6, 28_000, 60_000),
    (3_700, 21, "alpha", 6, 20_000, 30_000), (3_800, 22, "gamma", 6, 22_000, 44_000),
    (3_900, 23, "alpha", 3, 21_000, 35_000))
SIDE_KEYS = ["count", "b_mean", "b_median", "b_without_schemas_mean", "b_without_schemas_median"]
```

Add to `WindowsTest`:

```python
    def test_the_candidate_is_reweighted_to_the_baseline_project_mix(self):
        """AC: baseline alpha x1 and beta x3, candidate alpha x3 and beta x1; one host, fresh, 6-7."""
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        rows = document["reweighted"]
        self.assertEqual([(row["host"], row["cohort"], row["phase_group"]) for row in rows],
                         [(HOST, "fresh", "6-7"), (HOST, "fresh", "all"), ("all", "fresh", "6-7"),
                          ("all", "fresh", "all")])
        # Candidate weights n0/n1: 1/3 for each alpha boot, 3 for the beta boot (total 4).
        # B: alpha 30,000 32,000 34,000, beta 50,000. The mean is 1/4 x 32,000 + 3/4 x 50,000 =
        # 45,500. The weighted median is 50,000: cumulative 1/3, 2/3, 1, 4 first reaches 2 there,
        # while the plain median is 33,000. Without schemas (end - start + 200): alpha 10,200
        # 11,200 12,200, beta 24,200, so 1/4 x 11,200 + 3/4 x 24,200 = 20,950, median 24,200.
        candidate = {"count": 4, "b_mean": 45_500, "b_median": 50_000,
                     "b_without_schemas_mean": 20_950, "b_without_schemas_median": 24_200}
        # Every baseline stratum is common, so the baseline side is the baseline group row:
        # B 40,000 52,000 54,000 56,000; without schemas 16,200 24,200 26,200 28,200.
        baseline = {"count": 4, "b_mean": 50_500, "b_median": 53_000,
                    "b_without_schemas_mean": 23_700, "b_without_schemas_median": 25_200}
        for row in rows:
            with self.subTest(host=row["host"], phase_group=row["phase_group"]):
                self.assertEqual(list(row), ["host", "cohort", "phase_group", "common_strata",
                                             "baseline", "candidate"])
                self.assertEqual((list(row["baseline"]), list(row["candidate"])),
                                 (SIDE_KEYS, SIDE_KEYS))
                self.assertEqual((row["common_strata"], row["baseline"], row["candidate"]),
                                 (2, baseline, candidate))
                group = {g["arm"]: g for g in document["groups"] if (g["host"], g["cohort"],
                         g["phase_group"]) == (row["host"], row["cohort"], row["phase_group"])}
                self.assertEqual({key: group["baseline"][key] for key in SIDE_KEYS}, baseline)
                self.assertEqual((group["candidate"]["b_mean"], group["candidate"]["b_median"]),
                                 (36_500, 33_000))

    def test_strata_in_one_window_drop_out_and_a_scope_with_none_in_common_is_null(self):
        self.write_boots(COVERAGE_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        empty = dict.fromkeys(SIDE_KEYS, None) | {"count": 0}
        alpha_baseline = {"count": 1, "b_mean": 40_000, "b_median": 40_000,
                          "b_without_schemas_mean": 16_200, "b_without_schemas_median": 16_200}
        alpha_candidate = {"count": 1, "b_mean": 30_000, "b_median": 30_000,
                           "b_without_schemas_mean": 10_200, "b_without_schemas_median": 10_200}
        self.assertEqual(
            [(row["host"], row["cohort"], row["phase_group"], row["common_strata"],
              row["baseline"], row["candidate"]) for row in document["reweighted"]],
            [(host, "fresh", group, *sides) for host in (HOST, "all") for group, sides in (
                ("0-5", (0, empty, empty)), ("6-7", (1, alpha_baseline, alpha_candidate)),
                ("all", (1, alpha_baseline, alpha_candidate)))])

    def test_reweighted_strata_keep_hosts_and_cohorts_apart(self):
        """WINDOW_BOOTS with beta's boots on host b, every boot project alpha, plus a spawned
        candidate boot on a: pooling hosts (common 1, mean 36,500) or cohorts fails (D13)."""
        roots = {label: self.root / label for label in ("a", "b")}
        for label, project in (("a", "alpha"), ("b", "beta")):
            spawned = [(4_100, 25, "alpha", 6, 20_000, 90_000, 1)] if label == "a" else []
            self.write_boots([(*boot[:2], "alpha", *boot[3:]) for boot in WINDOW_BOOTS
                              if boot[2] == project] + spawned, root=roots[label])
        document = report(*(f"{label}={root}" for label, root in roots.items()),
                          extra=(*EVENTS, "--baseline", BASELINE))
        rows = {(r["host"], r["cohort"], r["phase_group"]): (r["common_strata"], *(
            r["candidate"][key] for key in ("count", "b_mean", "b_median")))
            for r in document["reweighted"]}
        self.assertEqual((rows[("all", "fresh", "all")], rows[("a", "fresh", "6-7")],
                          rows[("all", "spawned", "all")]),
                         ((2, 4, 45_500, 50_000), (1, 3, 32_000, 32_000), (0, 0, None, None)))

    def test_text_output_prints_the_reweighted_table_after_both_arms(self):
        self.write_boots(COVERAGE_BOOTS)
        completed = costs("--projects-dir", str(self.root), *EVENTS, "--baseline", BASELINE)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        positions = [out.find(heading) for heading in (
            "Boots by B, candidate",
            "Reweighted to the baseline's host × phase group × project mix",
            "Observed characters per token")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertRegex(out, rf"(?m)^{re.escape(HOST)} +fresh +0-5 +0 +0 +0( +-){{8}}$")
        live = costs("--projects-dir", str(self.root), *EVENTS)
        self.assertNotIn("Reweighted to", live.stdout)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Boot tests (Global Constraints) with `-k reweighted -k strata_in_one_window`.
Expected: FAIL. `reweighted` is `None`, so the first test fails its first `assertEqual` and the second and the hosts-and-cohorts test raise `TypeError: 'NoneType' object is not iterable`. The text test does not find the `Reweighted to` heading.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/agent_boot_rollup.py`:
- Import `Fraction` from `fractions` and `defaultdict` from `collections`.
- `_mean(values, weights)`: `None` when `sum(weights)` is 0, else `float(sum(Fraction(value) * weight for …) / sum(weights, Fraction(0)))`.
- `_side(boots, weights)` returns `{"count": len(boots), "b_mean": …, "b_median": …, "b_without_schemas_mean": …, "b_without_schemas_median": …}`, in that order. The values are `_mean` and `median` over `b` and over `b - buckets["tool_schemas"]`, each value with its weight.
- `_strata(boots, group)` maps `(host, phase_group, project)` to the boots that the group row pools. A boot is pooled when `boot["cohort"] == group["cohort"]`, `group["host"] in (ALL, boot["host"])` and `group["phase_group"] in (ALL, boot["phase_group"])`.
- `reweighted_rows(groups, baseline, candidate)`. For each group row:
  - `before, after = _strata(baseline, group), _strata(candidate, group)`;
  - `common = [s for s in before if s in after]`;
  - the baseline side is `_side` over the boots of `before[s]` for `s` in `common`, at weight 1 each;
  - the candidate side is `_side` over the boots of `after[s]`, each weighted `Fraction(len(before[s]), len(after[s]))`.

  The row is `{"host", "cohort", "phase_group"}` from the group row, then `"common_strata": len(common)`, `"baseline"`, `"candidate"`. Docstring: "One row per row of `groups` (the candidate arm's group rows, in order): B and B without tool schemas over the strata (host, phase group, project) the row pools that both arms hold. The candidate's boots are weighted n0(s)/n1(s), which is the candidate's stratum means at the baseline's mix, and the baseline's figures are plain (issue 504 D3, D10)." Extend the module docstring to name the reweighting.

`python/agent_tools/agent_boot_report.py`:
- Import `BASELINE_ARM` and `CANDIDATE_ARM` from `agent_owner_report`, and `reweighted_rows` from the rollup.
- `build_document`: when the arms of `collected` are `[BASELINE_ARM, CANDIDATE_ARM]`, `reweighted = reweighted_rows([g for g in groups if g["arm"] == CANDIDATE_ARM], baseline boots, candidate boots)`. Otherwise it stays `None`.
- `print_document`: when `doc["reweighted"]` is not `None`, after the last arm's boots table and before the observed-ratio line, print `\nReweighted to the baseline's host × phase group × project mix (tokens per boot):\n`, then `print_table` with one row per `reweighted` row:
  - headers `["host", "cohort", "phase", "common strata", "baseline n", "candidate n", "baseline B", "median", "candidate B", "median", "baseline B w/o schemas", "median", "candidate B w/o schemas", "median"]`;
  - alignment `["l", "l", "l"]` then `"r"` for the rest;
  - counts as `f"{n:,}"` and every statistic through Task 2's `_tokens` (`-` for `None`).

`python/README.md`, **Boot report** section:
- *Document.*: replace Task 3's ", and `reweighted` is `null`." with: ". `reweighted` is `null` without `--baseline`. With it, `reweighted` is a list of one row per candidate group row, in that order. Each row holds exactly `host, cohort, phase_group, common_strata, baseline, candidate`, and each side exactly `count, b_mean, b_median, b_without_schemas_mean, b_without_schemas_median`."
- Add after *Sub-totals and medians*:

  > *Reweighting (issue 504).* With `--baseline` each candidate group row gets a reweighted row (issue 504 D3, D4, D10). A stratum is a host, a phase group (`0-5` or `6-7`) and a project within one cohort. A row's strata are those it pools: its host or every host for `all`, its phase group or both for `all`, and every project. With `n0(s)` and `n1(s)` the baseline's and the candidate's boots in stratum `s`, `K` is the set of strata where both are above 0 and `common_strata` is its size. The `candidate` side's `count` is the candidate's boots in `K`. Its `b_mean` and `b_without_schemas_mean` weight each such boot `n0(s)/n1(s)`, which gives the candidate's stratum means weighted by the baseline's counts, `Σ n0(s)/N0 × mean(s)`. Its medians are weighted medians with the same weights: sort the values and take the first whose cumulative weight reaches half the total, or the mean of that value and the next when the cumulative weight is exactly half. The weights are exact fractions, and a mean is computed exactly and rounded once. The `baseline` side holds the plain count, means and medians over the baseline's boots in `K`; when the candidate holds every baseline stratum in scope, it equals the baseline group row. Strata in one arm only drop out. With `K` empty, both counts and `common_strata` are 0 and every statistic is `null`. Buckets, sub-totals and top skills are not reweighted, and the text output prints the rows as a `Reweighted to the baseline's host × phase group × project mix` table after both arms, with `-` for `null`.

Check each README clause against the code you wrote, and correct the README wherever they differ.

- [ ] **Step 4: Verify**

Run the Boot tests (Global Constraints), whole module.
Expected: `Ran 25 tests`, `OK`.

Run: `if grep -nE "^ *(from|import) .*agent_boot_report" python/agent_tools/agent_boot_rollup.py; then exit 1; fi`
Expected: exit 0, with no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_boot_rollup.py python/agent_tools/agent_boot_report.py \
  python/README.md tests/test_agent_boot_report.py
launch-commit --repo-root <ledger repo root> --run-id <run id> --worker-id <worker id> -- \
  -m "feat(boot-report): reweight B to the baseline's host, phase and project mix" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"f982c6a2653c56cf0820337e2a7aa01ef0598c6f","head":"5ecb2ce4b467feb10e3608425412d0e8bf5b6f46"}],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":145,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["r2a","r3c","r4a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r4a","last_task":4,"owner":4,"path":"python/agent_tools/agent_boot_rollup.py"},{"bounds":[{"added_lines":185,"boundary":"all","deleted_lines":80,"record_bytes":40960,"support":{"covers":["r1a","r2b","r3b","r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":4,"owner":4,"path":"python/agent_tools/agent_boot_report.py"},{"bounds":[{"added_lines":11,"boundary":"all","deleted_lines":5,"record_bytes":53248,"support":{"covers":["r1c","r2d","r3d","r4c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4c","last_task":4,"owner":4,"path":"python/README.md"},{"bounds":[{"added_lines":380,"boundary":"all","deleted_lines":5,"record_bytes":40960,"support":{"covers":["r1b","r2c","r3e","r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":4,"owner":4,"path":"tests/test_agent_boot_report.py"}]}}
```
