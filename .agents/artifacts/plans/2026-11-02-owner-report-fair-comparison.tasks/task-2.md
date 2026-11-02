# Task 2: Deliveries come from counted calls

Spec § Spend and deliveries (*Deliveries*) and § Test seams (*AC (a), matched deliveries*). Rests on D3. Today an event window clips a lineage's spend to the calls that start inside it, but reads its delivery from every call. After this task a lineage is delivered only when one of its *counted* calls got a `workflow-state finish` reply of kind `delivery_complete` for its run and issue. In mtime mode, eval grouping and (from Task 4) start mode every call is counted, so only the event window changes.

**Files:**
- Modify: `python/agent_tools/agent_owner_report.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes (present at base): in `tests/owner_transcripts.py`, `FINISH`, `finish_reply(issue)`, `Session`, `progress`, `gate_reply` and `at`. In `agent_owner_report`, `scan_owner_transcript`, whose `counted` list (from `_counted(calls, since, before)`) flags each call, and the scan key `"finishes"` that `_lineage` reads.
- Produces: the scan key `"finishes"` holds only the `(run_id, issue)` pairs read from counted calls. No signature changes.

**Invariants:**
- `"directs"` keeps reading every call: the spec clips deliveries only.
- Eval grouping still reads the trial's `verdict` (`_merge_trial` is unchanged).
- Spend, launches, boots and every other lineage fact are unchanged in every mode.

- [ ] **Step 1: Write the failing test**

Add to `OwnerReportTest` in `tests/test_agent_owner_report.py`:

```python
    def test_an_event_window_clips_deliveries_with_the_spend(self):
        # the keeper's finish reply comes at t = 20, before a window opening at t = 50; the
        # owner's call at t = 100 keeps the lineage in that window
        session = Session(self.root)
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        session.result(None, 5, g, gate_reply("continue"))
        keeper = session.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("k1", tool_use_id=keeper)
        f = session.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        session.result("k1", 25, f, finish_reply(7))
        session.call(None, 100, context=22_000, write=1_000, ttl="1h")
        session.write()
        for since, delivered in ((0, True), (50, False)):
            with self.subTest(since=since):
                doc = report(self.root, "--events-since", at(since), "--events-before", at(1_000))
                [row] = doc["lineages"]
                self.assertEqual((row["delivered"], doc["arms"][0]["delivered"]),
                                 (delivered, int(delivered)))
```

- [ ] **Step 2: Run the test and watch it fail**

Run the Owner tests command with `-k clips_deliveries` (timeout 300 s).
Expected: FAIL in the `since=50` subtest, `(True, 1) != (False, 0)`. The base code reads the finish reply of a call outside the window.

- [ ] **Step 3: Implement**

In `scan_owner_transcript`, build `"finishes"` from the reads whose `counted` flag is true, zipping `reads` with `counted` as the `priced` list already does. Nothing else changes.

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 19 tests`, `OK` (18 after Task 1, plus this one).

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs, *Delivered.*: a live lineage is delivered when the finish reply came in a call the report counts. In an event window that is a call starting inside it, so the window clips deliveries with the spend (issue 503 D3).

Run: `rg -c 'issue 503 D3' python/README.md` — expected `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_report.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(agent-costs): read owner deliveries from counted calls only (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":90,"boundary":"all","deleted_lines":16,"record_bytes":18432,"support":{"covers":["r1b","r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":7,"owner":2,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":6,"record_bytes":12288,"support":{"covers":["r1d","r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":7,"owner":2,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":9,"boundary":"all","deleted_lines":4,"record_bytes":36864,"support":{"covers":["r1e","r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":7,"owner":2,"path":"python/README.md"}]}}
```
