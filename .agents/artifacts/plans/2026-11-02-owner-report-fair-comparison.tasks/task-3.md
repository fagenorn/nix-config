# Task 3: One aggregate for arm and project rows

Spec § Aggregates (*Lineage values*, *One aggregate*, *Arm and project rows*), § Document (*Arm rows*, *Project rows*) and § Modules. Rests on D6, D7, D8 and D9. After this task the new module `agent_tools.agent_owner_rollup` holds the one aggregate. The owner report's arm rows come from it and gain `delivery_rate`, `owner_dollars_per_lineage` and `ping_dollars`. The document gains `projects`, one row per arm and project, and lineage rows gain the ping fields, which stay 0 until Task 6 reads a proxy log.

**Files:**
- Create: `python/agent_tools/agent_owner_rollup.py`
- Modify: `python/agent_tools/agent_owner_report.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes: Task 1's lineage-row key `project`, `Session(..., cwd=...)` and `progress(..., repo_root=...)`. From `agent_tools.agent_costs` (present at base): `percentile(values, p)`, which gives 0 for no values.
- Produces, in `agent_tools.agent_owner_rollup`:
  - `spend(row: dict) -> float`, which is `row["total_dollars"] + row["ping_dollars"]`. `owner_spend(row: dict) -> float`, which is `row["owner_dollars"] + row["owner_ping_dollars"]`.
  - `aggregate(rows: list[dict]) -> dict` with exactly these keys, in order: `n`, `delivered`, `delivery_rate` (delivered ÷ n), `dollars_per_delivered` (Σ spend ÷ delivered), `owner_dollars_per_lineage` (Σ owner spend ÷ n), `owner_dollars`, `owner_ping_dollars`, `total_dollars`, `ping_dollars`. A quotient with a zero denominator is `None`, and every sum starts at `0.0`.
  - `arm_rows(rows: list[dict]) -> list[dict]`: one row per arm present, sorted by arm name, with exactly these keys in order: `arm, n, delivered, delivery_rate, dollars_per_delivered, owner_dollars_per_lineage, sd, undelivered_dollars, ping_dollars, peak_p50, peak_p90`. `sd` is `statistics.stdev` of the delivered rows' spend, or `None` below two. `undelivered_dollars` is Σ spend of the undelivered rows, from `0.0`. `peak_p50`/`peak_p90` are `percentile` of the rows' `peak_context`.
  - `project_rows(rows: list[dict], arms: list[str]) -> list[dict]`: for each arm in `arms`, in that order, one row per project of that arm's rows, sorted by project. Each row is `{"arm": …, "project": …, **aggregate(those rows)}`, so its keys are exactly `arm, project, n, delivered, delivery_rate, dollars_per_delivered, owner_dollars_per_lineage, owner_dollars, owner_ping_dollars, total_dollars, ping_dollars`.
- Produces, in `agent_owner_report`: `_lineage_row` appends `"owner_ping_dollars": 0.0` and `"ping_dollars": 0.0` after `started`. `build_document` emits `"arms": agent_owner_rollup.arm_rows(rows)` and, right after it, `"projects": agent_owner_rollup.project_rows(rows, [arm["arm"] for arm in arm_rows])`. `_arm_rows` is deleted, and so is the `statistics` import, whose only user it was.
- Produces, in the tests: `OwnerReportTest.assert_rows(self, actual, expected)` (Task 5 uses it).

**Invariants:**
- With every ping field 0, `dollars_per_delivered`, `sd` and `undelivered_dollars` equal their v1 values, so every existing test passes unchanged.
- `agent_owner_rollup` imports nothing from `agent_owner_report`, which imports it at module level.
- Lineage rows' `owner_dollars` and `total_dollars` stay calls-only (D6).

- [ ] **Step 1: Write the failing test**

Add to `OwnerReportTest` in `tests/test_agent_owner_report.py`:

```python
    def assert_rows(self, actual, expected):
        """`actual` equals `expected` row for row and key for key, in order; floats to 9 places."""
        self.assertEqual(len(actual), len(expected))
        for got, want in zip(actual, expected):
            self.assertEqual(list(got), list(want))
            for name, value in want.items():
                if isinstance(value, float):
                    self.assertAlmostEqual(got[name], value, places=9, msg=name)
                else:
                    self.assertEqual(got[name], value, name)

    def test_project_rows_and_owner_dollars_per_lineage(self):
        delivered = Session(self.root, session="s1")
        g = delivered.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        delivered.result(None, 5, g, gate_reply("continue"))
        keeper = delivered.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        delivered.child("k1", tool_use_id=keeper)
        f = delivered.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        delivered.result("k1", 25, f, finish_reply(7))
        delivered.write()
        other = Session(self.root, project="-Users-me-other", session="s2", cwd="/Users/me/other")
        g8 = other.call(None, 0, context=30_000, write=30_000, ttl="1h",
                        bash=progress(3, action_id="8:1:1", repo_root="/Users/me/other"))
        other.result(None, 5, g8, gate_reply("continue", issue=8))
        other.write()
        doc = report(self.root)
        owner7 = cost(20_000, 20_000, write_price=8.0) + cost(21_000, 1_000, write_price=8.0)
        total7 = owner7 + cost(15_000, 15_000)
        owner8 = cost(30_000, 30_000, write_price=8.0)
        self.assertEqual([(row["owner_ping_dollars"], row["ping_dollars"]) for row in doc["lineages"]],
                         [(0.0, 0.0), (0.0, 0.0)])
        self.assert_rows(doc["arms"], [{
            "arm": "live", "n": 2, "delivered": 1, "delivery_rate": 0.5,
            "dollars_per_delivered": total7 + owner8,
            "owner_dollars_per_lineage": (owner7 + owner8) / 2, "sd": None,
            "undelivered_dollars": owner8, "ping_dollars": 0.0, "peak_p50": 21_000,
            "peak_p90": 30_000}])
        self.assert_rows(doc["projects"], [
            {"arm": "live", "project": "other", "n": 1, "delivered": 0, "delivery_rate": 0.0,
             "dollars_per_delivered": None, "owner_dollars_per_lineage": owner8,
             "owner_dollars": owner8, "owner_ping_dollars": 0.0, "total_dollars": owner8,
             "ping_dollars": 0.0},
            {"arm": "live", "project": "repo", "n": 1, "delivered": 1, "delivery_rate": 1.0,
             "dollars_per_delivered": total7, "owner_dollars_per_lineage": owner7,
             "owner_dollars": owner7, "owner_ping_dollars": 0.0, "total_dollars": total7,
             "ping_dollars": 0.0}])
```

- [ ] **Step 2: Run the test and watch it fail**

Run the Owner tests command with `-k project_rows` (timeout 300 s).
Expected: FAIL, `KeyError: 'owner_ping_dollars'`.

- [ ] **Step 3: Implement**

Create `python/agent_tools/agent_owner_rollup.py` with the interfaces above. Its module docstring says that it builds the owner report's arm and project rows from lineage rows through one aggregate (issue 503), defines a row's spend and owner spend as above, and points to python/README.md (agent-costs) for the contract. Each public function carries a one-line contract docstring stating the formula it implements. In `agent_owner_report.py`, import the module as `from agent_tools import agent_owner_rollup`, delete `_arm_rows` and `import statistics`, and make the `_lineage_row` and `build_document` changes. Extend the module docstring's "build_document projects them" clause to say that the arm and project rows come from agent_tools.agent_owner_rollup.

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 20 tests`, `OK`.
Run the Neighbour tests command (timeout 300 s). Expected: `Ran 48 tests`, `OK`.
Run: `if rg -q '_arm_rows|^import statistics' python/agent_tools/agent_owner_report.py; then exit 1; fi` — expected exit 0.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs, *Document.*:
- The `lineages` key list ends `…, project, started, owner_ping_dollars, ping_dollars`. The two new keys are the lineage's keepalive ping dollars (its owner transcripts' and all its transcripts'), 0 without a proxy log. `owner_dollars` and `total_dollars` stay calls-only.
- `arms` rows hold exactly the eleven keys above. Say that a row's spend is `total_dollars + ping_dollars` and its owner spend `owner_dollars + owner_ping_dollars`. Then define `delivery_rate`, `dollars_per_delivered` (all spend of the arm, undelivered included, ÷ delivered), `owner_dollars_per_lineage` (owner spend ÷ n), `sd` (over the delivered rows' spend), `undelivered_dollars` and `ping_dollars`, with `null` for a zero denominator.
- Add `projects`: rows ordered by arm as in `arms`, then by project, with exactly the eleven keys above. They are the same aggregate over one arm and one project, and their counts and sums are additive, so two hosts' documents pool by adding them and recomputing the quotients (issue 503 D10).

Run: `rg -c 'owner_dollars_per_lineage' python/README.md` — expected at least `2`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_rollup.py python/agent_tools/agent_owner_report.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): build owner arm and project rows from one aggregate (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"5c401bcfadcd0dab9353d2e532d2ce9dbcf5e31f","head":"9b7ac11e6cb9026cbf96e1fecb5128dc134f8f72"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r3a","last_task":5,"owner":3,"path":"python/agent_tools/agent_owner_rollup.py"},{"bounds":[{"added_lines":140,"boundary":"all","deleted_lines":30,"record_bytes":26624,"support":{"covers":["r1b","r2a","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":7,"owner":3,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":250,"boundary":"all","deleted_lines":8,"record_bytes":18432,"support":{"covers":["r1d","r2b","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":7,"owner":3,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":5,"record_bytes":40960,"support":{"covers":["r1e","r2c","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":7,"owner":3,"path":"python/README.md"}]}}
```
