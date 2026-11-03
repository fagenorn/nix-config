# Task 4: Start mode with a settle period

Spec § Modes and windows, § Lineage start, settle and report end, § Spend and deliveries (*Full spend*, *Unattributed spend in start mode*), § Document (`start_grouping`), § CLI rules (the `--started` and `--settle-days` rows) and § Test seams (*AC (a), start grouping*). Rests on D1, D2, D3 and D13. After this task `--started SINCE..BEFORE` selects lineages by start and counts each one's whole spend. A lineage counts only once it is settled, and an unsettled one is reported per window. This task owns AC1.

**Files:**
- Modify: `python/agent_tools/agent_owner_report.py`
- Modify: `python/agent_tools/agent_costs.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes: Task 1's `Lineage.started` (epoch seconds), `_instant(epoch)` and `_lineages(scans, homes)`, and the scan key `"last_end"` (present at base: epoch of the transcript's latest call end). From `agent_costs` (present at base): `parse_rfc3339_utc`, `format_rfc3339_utc`, `_positive_int`, `main`, `_owners_report` and `_window_label`.
- Produces, in `agent_owner_report`:
  - `StartWindow(NamedTuple)` with fields `arm: str`, `since: datetime` and `before: datetime` (aware UTC), and `DEFAULT_SETTLE_DAYS = 4`.
  - `parse_range(text: str) -> tuple[datetime, datetime]` (D1). `text` splits at its first `..`. Each bound that fullmatches `\d{4}-\d{2}-\d{2}` is 00:00:00Z of that UTC day, parsed with `datetime.strptime(…, "%Y-%m-%d")` (so `2026-10-32` fails). Any other bound goes through `parse_rfc3339_utc`. It raises `ValueError` without `..`, on a bad bound, or when `since >= before`.
  - `start_window_label(windows) -> str`: `"; ".join` over the windows of `"<name> <since> → <before>"`, where `<name>` is `started` for the arm `live` and the arm otherwise, and the bounds go through `format_rfc3339_utc`. Example: `started 2026-10-25T00:00:00Z → 2026-10-28T00:00:00Z`.
  - `scan_owner_transcript(job, *, since, before, windows=())`. `windows` holds `(since, before)` datetime pairs. The scan gains `"window_calls"` and `"window_dollars"`: the count and dollars of the calls whose start lies in any of the pairs (by `_counted`), or `0` and `0.0` with no pairs.
  - `_lineages(scans, homes, *, start_mode=False)`.
  - `_select_started(lineages, windows, settle_days, report_end) -> tuple[list, list, dict]`, which returns the kept lineages, the left-out lineages and the `start_grouping` dict.
  - `collect(root, *, cutoff, since, before, eval_rows, executor_factory, windows=(), settle_days=0)` (D13). Its footer gains `"start_grouping"`, which is `None` unless `windows` is given. `windows` is a sequence of `StartWindow` and is never combined with `eval_rows`.
  - `build_document` emits `"start_grouping": footer["start_grouping"]` right after `"window"`.
- Produces, in `agent_costs`: the flags `--started SINCE..BEFORE` and `--settle-days DAYS` (type `_non_negative_int`, default `None`), and `_non_negative_int(text)` beside `_positive_int`.
- Produces, in the tests: module constants `DAY = 86_400` and `HOUR = 3_600`, the module function `run(root, *argv)`, and the `OwnerReportTest` methods `assert_usage_errors(self, *argvs)` and `started_corpus(self) -> dict`. Tasks 5 and 6 use all of them.

**Invariants:**
- Start mode reads every transcript under the root: `find_sessions(root, None)`, whatever `--days` says (D1).
- With windows, `collect` scans with `since=None, before=None`, so every call is counted. A counted lineage's spend runs past the window end (D3).
- Report end is the maximum `"last_end"` over all scans, or `None` with none (D2).
- `_select_started`, for each lineage in order:
  - A lineage whose `started` is `None` or lies in no window `[since, before)` is left out.
  - A lineage in a window but with `started > report_end − settle_days × 86_400` is left out as unsettled. Its window's `unsettled` gains 1 lineage and its `total_dollars` (D12).
  - Any other lineage is kept, with `facts["arm"]` set to its window's arm.
- `start_grouping` is `{"settle_days", "report_end", "windows"}`. `report_end` is `_instant(report_end)`. `windows` lists, in the given order, `{"arm", "since", "before", "unsettled": {"lineages", "dollars"}}`, with `since` and `before` through `format_rfc3339_utc` and `dollars` from `0.0`.
- With `start_mode`, a transcript that reaches no lineage adds its `window_calls` and `window_dollars` to `unattributed`, not its counted ones. An unresolved owner counts in `unresolved_owners` only when its `window_calls` is above 0. Outside start mode `unattributed` is computed exactly as before. A left-out lineage's transcripts are never unattributed.
- Usage errors (exit 2, nothing on stdout), each checked in `main` before any report runs:
  - `--started` or `--settle-days` without `--report owners`;
  - `--settle-days` without `--started`;
  - `--started` with `--events-since`/`--events-before`, or with `--eval-results`/`--eval`;
  - a negative `--settle-days`, through argparse.
  `_owners_report` turns a `parse_range` `ValueError` into `ap.error(f"--started: {error}")` before it reads any transcript.
- `_owners_report` passes `windows=(StartWindow(LIVE_ARM, since, before),)` and `settle_days=DEFAULT_SETTLE_DAYS if args.settle_days is None else args.settle_days`. Its window label is `start_window_label(windows)`.
- `boots` covers exactly the kept lineages, and `--policy`/`--sweep` replay them.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_owner_report.py`, add `DAY, HOUR = 86_400, 3_600` after the imports and this function after `report`:

```python
def run(root, *argv):
    """agent-costs over `root` with `argv`; the completed process, its exit status unchecked."""
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--projects-dir", str(root), *argv],
        capture_output=True, text=True, check=False)
```

Add to `OwnerReportTest`:

```python
    def assert_usage_errors(self, *argvs):
        """Each argv is refused by a rule of agent-costs: exit 2 and nothing on stdout."""
        for argv in argvs:
            with self.subTest(argv=argv):
                completed = run(self.root, *argv)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""), completed.stderr)
                self.assertNotIn("unrecognized arguments", completed.stderr)

    def started_corpus(self):
        """Issue 7 starts on day 1 (2026-10-26T09:00Z) and spends until day 6, the report end;
        issue 8 starts the evening before 2026-10-25 and delivers on day 1; issue 9 starts on
        day 2.5; s4 is no owner's and calls on days 1 and 5."""
        s7 = Session(self.root, session="s7")
        g = s7.call(None, DAY, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, DAY + 5, g, gate_reply("continue"))
        s7.call(None, 3 * DAY + 12 * HOUR, context=21_000, write=21_000, ttl="1h")
        s7.call(None, 6 * DAY, context=22_000, write=22_000, ttl="1h")
        s7.write()
        s8 = Session(self.root, session="s8")
        g = s8.call(None, -10 * HOUR, context=20_000, write=20_000, ttl="1h",
                    bash=progress(3, action_id="8:1:1"))
        s8.result(None, -10 * HOUR + 5, g, gate_reply("continue", issue=8))
        f = s8.call(None, DAY, context=21_000, write=1_000, ttl="1h", bash=FINISH)
        s8.result(None, DAY + 5, f, finish_reply(8))
        s8.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 2 * DAY + 12 * HOUR, context=25_000, write=25_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 2 * DAY + 12 * HOUR + 5, g, gate_reply("continue", issue=9))
        s9.write()
        s4 = Session(self.root, session="s4")
        s4.call(None, DAY, context=10_000, write=10_000, ttl="1h")
        s4.call(None, 5 * DAY, context=11_000, write=1_000, ttl="1h")
        s4.write()
        return {7: cost(20_000, 20_000, write_price=8.0) + cost(21_000, 21_000, write_price=8.0)
                + cost(22_000, 22_000, write_price=8.0),
                9: cost(25_000, 25_000, write_price=8.0),
                "s4": cost(10_000, 10_000, write_price=8.0)}

    def test_a_start_window_counts_whole_settled_lineages_that_started_inside_it(self):
        costs = self.started_corpus()
        doc = report(self.root, "--started", "2026-10-25..2026-10-28")
        [row] = doc["lineages"]
        self.assertEqual((row["issue"], row["arm"], row["started"]),
                         (7, "live", "2026-10-26T09:00:00Z"))
        self.assertAlmostEqual(row["owner_dollars"], costs[7], places=9)   # days 3.5 and 6 too
        [arm] = doc["arms"]
        self.assertEqual((arm["n"], arm["delivered"]), (1, 0))   # issue 8's delivery is out
        self.assertEqual(doc["window"], "started 2026-10-25T00:00:00Z → 2026-10-28T00:00:00Z")
        grouping = doc["start_grouping"]
        self.assertEqual((grouping["settle_days"], grouping["report_end"]),
                         (4, "2026-10-31T09:00:00Z"))
        [window] = grouping["windows"]
        self.assertEqual((window["arm"], window["since"], window["before"],
                          window["unsettled"]["lineages"]),
                         ("live", "2026-10-25T00:00:00Z", "2026-10-28T00:00:00Z", 1))
        self.assertAlmostEqual(window["unsettled"]["dollars"], costs[9], places=9)
        lost = doc["unattributed"]
        self.assertEqual((lost["transcripts"], lost["unresolved_owners"]), (1, 0))
        self.assertAlmostEqual(lost["dollars"], costs["s4"], places=9)   # its day-5 call is out

    def test_settle_days_zero_counts_the_young_lineage_too(self):
        self.started_corpus()
        doc = report(self.root, "--started", "2026-10-25T00:00:00+00:00..2026-10-28T00:00:00Z",
                     "--settle-days", "0")
        self.assertEqual([(row["issue"], row["arm"]) for row in doc["lineages"]],
                         [(7, "live"), (9, "live")])
        self.assertEqual(doc["start_grouping"]["windows"][0]["unsettled"],
                         {"lineages": 0, "dollars": 0.0})

    def test_start_mode_usage_errors(self):
        window = "2026-10-25..2026-10-28"
        self.assert_usage_errors(
            ["--report", "boot", "--started", window],
            ["--settle-days", "4"],
            ["--report", "owners", "--settle-days", "4"],
            ["--report", "owners", "--started", window, "--events-since", at(0),
             "--events-before", at(60)],
            ["--report", "owners", "--started", window, "--eval-results", "r.jsonl",
             "--eval", "from-issue:8"],
            ["--report", "owners", "--started", window, "--settle-days", "-1"],
            ["--report", "owners", "--started", "2026-10-25"],
            ["--report", "owners", "--started", "2026-10-28..2026-10-25"],
            ["--report", "owners", "--started", "2026-10-25..2026-10-25"],
            ["--report", "owners", "--started", "2026-10-25..2026-10-32"],
            ["--report", "owners", "--started", "2026-10-25T00:00:00..2026-10-28"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Owner tests command with `-k settled_lineages -k settle_days_zero -k start_mode_usage` (timeout 300 s). It selects the three new tests and no other.
Expected: FAIL. The two report tests fail on `unrecognized arguments: --started` in `report`'s assertion. The usage test fails its `assertNotIn("unrecognized arguments", …)` subtests.

- [ ] **Step 3: Implement**

`agent_owner_report.py`: add `StartWindow`, `DEFAULT_SETTLE_DAYS`, `parse_range`, `start_window_label`, the scan's window fields, `_lineages`' `start_mode` and `_select_started`. In `collect`, set `start_mode = bool(windows)` and drop the mtime cutoff in start mode. Pass `tuple((w.since, w.before) for w in windows)` through `_scan_all` (it gains the argument), and pass `start_mode` to `_lineages`. Without `eval_rows` and in start mode, compute the report end and call `_select_started`; then add `"start_grouping"` to the footer. In `_lineages`, `lose(scan)` reads `window_calls`/`window_dollars` in start mode and `counted_calls`/`dollars` otherwise. The unresolved-owner count follows the invariant. The module docstring gains one sentence: with start windows, `collect` keeps the settled lineages that started in a window and counts their whole spend.

`agent_costs.py`:
- Add the two arguments. Help texts:
  - `--started`: "select the lineages that started in [SINCE, BEFORE) (YYYY-MM-DD or RFC3339 bounds) and count their whole spend; --report owners only"
  - `--settle-days`: "count a lineage only when it started at least DAYS days before the report end (default 4, 0 = off); needs --started"
- Add the usage rules and `_owners_report`'s parsing, window and label, per the invariants.
- Its module docstring's owner paragraph gains: "`--started SINCE..BEFORE` instead selects the lineages that started in that window and counts each one's whole spend once it has settled `--settle-days` (default 4) before the report end."

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 23 tests`, `OK`.
Run the Neighbour tests command (timeout 300 s). Expected: `Ran 48 tests`, `OK`.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs:
- The **Owner report (issue 432)** paragraph's lists of flags taken and refused gain `--started` and `--settle-days` and their refusals.
- After *Eval grouping.*, add *Start mode (issue 503).* State, as the code does:
  - the range grammar and half-open window;
  - that every transcript is read and `--days` ignored;
  - the lineage start (*Project and start*), the report end and the settle rule with its default and 0;
  - that a counted lineage counts every call, and that left-out and unsettled lineages are handled as above;
  - the start-mode unattributed rule;
  - that the arm is `live`;
  - that `--policy` and `--sweep` replay the kept lineages.
- In *Document.*, add `start_grouping` (`null` outside start mode, else its shape, with D12's `unsettled.dollars`) and the window label of start mode.

Run: `rg -c 'Start mode \(issue 503\)' python/README.md` — expected `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_report.py python/agent_tools/agent_costs.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): select owner lineages by start with a settle period (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"adda18c0bca726bc4c3e95589a226e9b83c69a04","head":"782ff7d490cdaaefc0e878259a5f54a4b4bc4e17"}],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":220,"boundary":"all","deleted_lines":40,"record_bytes":36864,"support":{"covers":["r1b","r2a","r3b","r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":7,"owner":4,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":8,"record_bytes":6144,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":7,"owner":4,"path":"python/agent_tools/agent_costs.py"},{"bounds":[{"added_lines":370,"boundary":"all","deleted_lines":12,"record_bytes":26624,"support":{"covers":["r1d","r2b","r3c","r4c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4c","last_task":7,"owner":4,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":18,"boundary":"all","deleted_lines":7,"record_bytes":45056,"support":{"covers":["r1e","r2c","r3d","r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":7,"owner":4,"path":"python/README.md"}]}}
```
