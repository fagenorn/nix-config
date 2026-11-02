# Task 5: Baseline-against-candidate comparison

Spec § Modes and windows (*Arms*, *Replay*), § Aggregates (*Arm and project rows*, *Comparison*), § Document (`comparison`), § CLI rules (the `--baseline` rows) and § Test seams (*AC (b), per-project and two-window comparison*). Rests on D1, D4, D7 and D8. After this task, `--baseline SINCE..BEFORE` with `--started` makes the report a two-window comparison. The windows are the arms `baseline` and `candidate`, both always present, and `comparison` holds the candidate ÷ baseline ratios and each project's delivery-rate change. The report computes no verdict against #432's thresholds.

**Files:**
- Modify: `python/agent_tools/agent_owner_rollup.py`
- Modify: `python/agent_tools/agent_owner_report.py`
- Modify: `python/agent_tools/agent_costs.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes:
  - Task 1: `Session(..., cwd=...)`, `progress(..., repo_root=...)` and the lineage `project`.
  - Task 3: `agent_owner_rollup.aggregate`, `arm_rows(rows)`, `project_rows(rows, arms)` and `assert_rows`.
  - Task 4: `StartWindow`, `parse_range`, `start_window_label`, `collect(..., windows=..., settle_days=...)`, the footer's `start_grouping`, `run`, `assert_usage_errors`, `DAY` and `HOUR`.
- Produces, in `agent_owner_report`: `BASELINE_ARM = "baseline"` and `CANDIDATE_ARM = "candidate"`. `build_document` emits `"comparison"` right after `"calibration"` (Task 6 puts `pings` between them).
- Produces, in `agent_owner_rollup`:
  - `arm_rows(rows, required=())`: the `required` arms first, in their order, each with a row even when it has no lineage, then any other arm present, sorted. An empty arm's row is `n` 0, `delivered` 0, `delivery_rate`, `dollars_per_delivered`, `owner_dollars_per_lineage` and `sd` `None`, `undelivered_dollars` and `ping_dollars` `0.0`, and `peak_p50` and `peak_p90` 0.
  - `comparison(arms: list[dict], projects: list[dict], baseline: str, candidate: str) -> dict` with exactly these keys, in order:
    - `owner_dollars_per_lineage_ratio` and `dollars_per_delivered_ratio`: candidate ÷ baseline over the two arm rows;
    - `projects`: one entry per project in either arm's project rows, sorted by name, each exactly `{project, owner_dollars_per_lineage_ratio, delivery_rate_change}`.

    A ratio is `None` when either side is `None` or the baseline is 0. `delivery_rate_change` is the candidate rate minus the baseline rate, as a fraction, and `None` unless both arms have the project.
- Produces, in `agent_costs`: the flag `--baseline SINCE..BEFORE`.
- Produces, in the tests: `OwnerReportTest.two_windows(self) -> dict` (Task 7 uses it).

**Invariants:**
- Comparison mode is exactly "`start_grouping` has two windows". Then `build_document` passes `required=[BASELINE_ARM, CANDIDATE_ARM]` to `arm_rows`, and `comparison` is `agent_owner_rollup.comparison(arm_rows, project_rows, BASELINE_ARM, CANDIDATE_ARM)`. Otherwise `required` is empty and `comparison` is `None`.
- `_owners_report` with `--baseline` builds `windows = (StartWindow(BASELINE_ARM, *baseline), StartWindow(CANDIDATE_ARM, *started))`. A `parse_range` error is `ap.error(f"--baseline: {error}")`. Two windows overlap when `a.since < b.before and b.since < a.before`, which is `ap.error`; touching windows (one's `before` equals the other's `since`) are allowed.
- Usage errors (exit 2, nothing on stdout), checked in `main` before any report runs:
  - `--baseline` without `--report owners`;
  - `--baseline` without `--started`;
  - `--baseline` with `--policy` or `--sweep` (D7).
- `--policy`/`--sweep` with `--started` alone still work.
- The window label in comparison mode is Task 4's `start_window_label` over both windows, the baseline first.

- [ ] **Step 1: Write the failing tests**

Add to `OwnerReportTest` in `tests/test_agent_owner_report.py`:

```python
    def two_windows(self):
        """Baseline (2026-10-25): issue 7 (repo, delivered) and issue 8 (other, through an
        unexpanded "$R"); candidate (2026-10-26 from 15:00Z): issue 9 (repo, delivered by its
        keeper k9) and issue 10 (repo)."""
        s7 = Session(self.root, session="s7")
        g = s7.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, 5, g, gate_reply("continue"))
        f = s7.call(None, 60, context=21_000, write=1_000, ttl="1h", bash=FINISH)
        s7.result(None, 65, f, finish_reply(7))
        s7.write()
        s8 = Session(self.root, project="-Users-me-other--worktrees-worktree-issue-8", session="s8",
                     cwd="/Users/me/other/.worktrees/worktree-issue-8")
        g = s8.call(None, HOUR, context=30_000, write=30_000, ttl="1h",
                    bash=progress(3, action_id="8:1:1", repo_root='"$R"'))
        s8.result(None, HOUR + 5, g, gate_reply("continue", issue=8))
        s8.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 30 * HOUR, context=40_000, write=40_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 30 * HOUR + 5, g, gate_reply("continue", issue=9))
        keeper = s9.call(None, 30 * HOUR + 10, context=41_000, write=1_000, ttl="1h", agent_tool=True)
        s9.child("k9", tool_use_id=keeper)
        f = s9.call("k9", 30 * HOUR + 20, context=15_000, write=15_000, bash=FINISH)
        s9.result("k9", 30 * HOUR + 25, f, finish_reply(9))
        s9.write()
        s10 = Session(self.root, session="s10")
        g = s10.call(None, 31 * HOUR, context=50_000, write=50_000, ttl="1h",
                     bash=progress(3, action_id="10:1:1"))
        s10.result(None, 31 * HOUR + 5, g, gate_reply("continue", issue=10))
        s10.write()
        return {7: cost(20_000, 20_000, write_price=8.0) + cost(21_000, 1_000, write_price=8.0),
                8: cost(30_000, 30_000, write_price=8.0),
                9: cost(40_000, 40_000, write_price=8.0) + cost(41_000, 1_000, write_price=8.0),
                "k9": cost(15_000, 15_000), 10: cost(50_000, 50_000, write_price=8.0)}

    def test_a_two_window_comparison_by_arm_and_project(self):
        c = self.two_windows()
        doc = report(self.root, "--baseline", "2026-10-25..2026-10-26",
                     "--started", "2026-10-26..2026-10-28", "--settle-days", "0")
        self.assertEqual([(row["issue"], row["arm"], row["project"]) for row in doc["lineages"]],
                         [(7, "baseline", "repo"), (8, "baseline", "other"),
                          (9, "candidate", "repo"), (10, "candidate", "repo")])
        self.assertEqual(doc["window"], "baseline 2026-10-25T00:00:00Z → 2026-10-26T00:00:00Z; "
                                        "candidate 2026-10-26T00:00:00Z → 2026-10-28T00:00:00Z")
        self.assertEqual([window["arm"] for window in doc["start_grouping"]["windows"]],
                         ["baseline", "candidate"])
        base_owner, cand_owner = (c[7] + c[8]) / 2, (c[9] + c[10]) / 2
        cand_spend = c[9] + c["k9"] + c[10]
        self.assert_rows(doc["arms"], [
            {"arm": "baseline", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": c[7] + c[8], "owner_dollars_per_lineage": base_owner,
             "sd": None, "undelivered_dollars": c[8], "ping_dollars": 0.0, "peak_p50": 21_000,
             "peak_p90": 30_000},
            {"arm": "candidate", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": cand_spend, "owner_dollars_per_lineage": cand_owner,
             "sd": None, "undelivered_dollars": c[10], "ping_dollars": 0.0, "peak_p50": 41_000,
             "peak_p90": 50_000}])
        self.assert_rows(doc["projects"], [
            {"arm": "baseline", "project": "other", "n": 1, "delivered": 0, "delivery_rate": 0.0,
             "dollars_per_delivered": None, "owner_dollars_per_lineage": c[8],
             "owner_dollars": c[8], "owner_ping_dollars": 0.0, "total_dollars": c[8],
             "ping_dollars": 0.0},
            {"arm": "baseline", "project": "repo", "n": 1, "delivered": 1, "delivery_rate": 1.0,
             "dollars_per_delivered": c[7], "owner_dollars_per_lineage": c[7],
             "owner_dollars": c[7], "owner_ping_dollars": 0.0, "total_dollars": c[7],
             "ping_dollars": 0.0},
            {"arm": "candidate", "project": "repo", "n": 2, "delivered": 1, "delivery_rate": 0.5,
             "dollars_per_delivered": cand_spend, "owner_dollars_per_lineage": cand_owner,
             "owner_dollars": c[9] + c[10], "owner_ping_dollars": 0.0, "total_dollars": cand_spend,
             "ping_dollars": 0.0}])
        comparison = doc["comparison"]
        self.assertEqual(list(comparison),
                         ["owner_dollars_per_lineage_ratio", "dollars_per_delivered_ratio", "projects"])
        self.assertAlmostEqual(comparison["owner_dollars_per_lineage_ratio"], cand_owner / base_owner,
                               places=9)
        self.assertAlmostEqual(comparison["dollars_per_delivered_ratio"], cand_spend / (c[7] + c[8]),
                               places=9)
        self.assert_rows(comparison["projects"], [
            {"project": "other", "owner_dollars_per_lineage_ratio": None, "delivery_rate_change": None},
            {"project": "repo", "owner_dollars_per_lineage_ratio": cand_owner / c[7],
             "delivery_rate_change": -0.5}])

    def test_a_window_with_no_lineage_keeps_an_arm_row_with_n_0(self):
        self.two_windows()
        doc = report(self.root, "--baseline", "2026-10-25..2026-10-26",
                     "--started", "2026-11-01..2026-11-02", "--settle-days", "0")
        self.assertEqual([arm["arm"] for arm in doc["arms"]], ["baseline", "candidate"])
        self.assert_rows(doc["arms"][1:], [{
            "arm": "candidate", "n": 0, "delivered": 0, "delivery_rate": None,
            "dollars_per_delivered": None, "owner_dollars_per_lineage": None, "sd": None,
            "undelivered_dollars": 0.0, "ping_dollars": 0.0, "peak_p50": 0, "peak_p90": 0}])
        self.assertEqual([(row["arm"], row["project"]) for row in doc["projects"]],
                         [("baseline", "other"), ("baseline", "repo")])
        comparison = doc["comparison"]
        self.assertEqual((comparison["owner_dollars_per_lineage_ratio"],
                          comparison["dollars_per_delivered_ratio"]), (None, None))

    def test_the_replay_runs_over_one_start_window(self):
        self.two_windows()
        doc = report(self.root, "--started", "2026-10-25..2026-10-28", "--settle-days", "0",
                     "--policy", "slim=boot=slim")
        self.assertEqual((len(doc["lineages"]), doc["comparison"]), (4, None))
        self.assertTrue(doc["calibration"]["identity_matches"])

    def test_comparison_usage_errors(self):
        started = ["--report", "owners", "--started", "2026-10-26..2026-10-28"]
        self.assert_usage_errors(
            ["--report", "boot", "--baseline", "2026-10-25..2026-10-26"],
            ["--report", "owners", "--baseline", "2026-10-25..2026-10-26"],
            started + ["--baseline", "2026-10-27..2026-10-29"],
            started + ["--baseline", "2026-10-26..2026-10-28"],
            started + ["--baseline", "2026-10-25"],
            started + ["--baseline", "2026-10-25..2026-10-26", "--policy", "slim=boot=slim"],
            started + ["--baseline", "2026-10-25..2026-10-26", "--sweep"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Owner tests command with `-k two_window -k no_lineage_keeps -k one_start_window -k comparison_usage` (timeout 300 s). It selects the four new tests.
Expected: FAIL. The two comparison tests fail on `unrecognized arguments: --baseline`. The usage test fails its `assertNotIn` subtests. The replay test fails with `KeyError: 'comparison'`.

- [ ] **Step 3: Implement**

`agent_owner_rollup.py`: add `required` to `arm_rows` and add `comparison`, each with a one-line contract docstring. `agent_owner_report.py`: add the two arm constants and the comparison branch in `build_document`, per the invariants. `agent_costs.py`: add `--baseline` with the help text "a second start window, not overlapping --started, whose lineages form the baseline arm against the candidate arm of --started; --report owners only". Add the usage rules, `_owners_report`'s window pair and its overlap check. The module docstring's owner paragraph gains: "`--baseline SINCE..BEFORE` adds a second window and compares its lineages, the baseline arm, with those of `--started`, the candidate arm."

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 27 tests`, `OK`.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs:
- The **Owner report** paragraph's flag lists gain `--baseline` and its refusals: without `--started`, overlapping windows, and with `--policy` or `--sweep`.
- *Start mode (issue 503).* gains the comparison:
  - the two arms and that both always have a row;
  - that touching windows are allowed;
  - the label;
  - that the report computes no verdict against issue 432's thresholds.
- In *Document.*, add `comparison`: `null` unless `--baseline` is given, else its keys and the ratio and change rules above, with `delivery_rate_change` a fraction.

Run: `rg -c 'delivery_rate_change' python/README.md` — expected at least `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_rollup.py python/agent_tools/agent_owner_report.py python/agent_tools/agent_costs.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): compare a baseline and a candidate start window (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"723025cddb13af5ea7e97b8982f7432fa02453fb","head":"4339eb57da0b262d6291668d9a88aaec8a4b7089"}],"commit_subject_bytes":[64,64],"id":5,"records":[{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["r3a","r5a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r5a","last_task":5,"owner":5,"path":"python/agent_tools/agent_owner_rollup.py"},{"bounds":[{"added_lines":270,"boundary":"all","deleted_lines":46,"record_bytes":43008,"support":{"covers":["r1b","r2a","r3b","r4a","r5b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5b","last_task":7,"owner":5,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":55,"boundary":"all","deleted_lines":12,"record_bytes":10240,"support":{"covers":["r4b","r5c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5c","last_task":7,"owner":5,"path":"python/agent_tools/agent_costs.py"},{"bounds":[{"added_lines":480,"boundary":"all","deleted_lines":14,"record_bytes":34816,"support":{"covers":["r1d","r2b","r3c","r4c","r5d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5d","last_task":7,"owner":5,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":22,"boundary":"all","deleted_lines":9,"record_bytes":49152,"support":{"covers":["r1e","r2c","r3d","r4d","r5e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5e","last_task":7,"owner":5,"path":"python/README.md"}]}}
```
