# Task 7: Document version 2 and text output

Spec § Document (*Top-level keys*, *Unchanged*), § Text output and § Test seams (*Text*). Rests on D7, D8 and D13. After this task the `agent-owner-report` document is `schema_version` 2 with its exact top-level and lineage key lists pinned. The text output shows the new columns, the Projects and Comparison tables and the `Pings:` and `Unsettled:` footer lines.

**Files:**
- Modify: `python/agent_tools/agent_owner_report.py`
- Modify: `python/agent_tools/agent_costs.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes:
  - the document as Tasks 1–6 leave it: lineage keys `project`, `started`, `owner_ping_dollars` and `ping_dollars`; `arms` and `projects` (Task 3); `start_grouping` (Task 4); `comparison` (Task 5); `pings` (Task 6);
  - from the tests: Task 5's `two_windows()`, Task 6's `ping_line`, Task 4's `HOUR`, and `chain` (present at base);
  - present at base: `print_table`, `human`, `_money` and `_print_capped`.
- Produces:
  - `SCHEMA_VERSION = 2`;
  - `print_document(doc: dict, *, top: int, eval_grouping: bool = False) -> None`;
  - `agent_costs._owners_report` calls it with `eval_grouping=eval_rows is not None`;
  - in the tests: the module constants `TOP_KEYS` and `LINEAGE_KEYS` and the module function `text(root, *extra)`.

**Invariants:**
- The document's keys are exactly, in order: `kind, schema_version, window, start_grouping, pricing, lineages, arms, projects, boots, simulated, calibration, pings, comparison, unattributed, interrupted, unmatched`.
- Text output, each table through `_print_capped`; `_rate(value)` is `f"{value:.0%}"`, or `-` for `None`:
  - **Title.** Outside start mode it stays `Owner report (<window>, <n> lineages)`. In start mode it is `Owner report (<window>; settled <settle_days>d before <report_end or ->, <n> lineages)`.
  - **Lineages table.** It gains `project`, `started` (the first 16 characters of `started`, else `-`) and `ping $` (`_money(ping_dollars)`). Its columns, in order: lineage, arm, project, started, launches, hand-offs, boots, deaths, child waits, peak, owner $, total $, ping $, delivered.
  - **Arms table.** Its columns, in order: arm, n, delivered, rate, $ / delivered, owner $ / lineage, sd, undelivered $, ping $, peak p50, peak p90. Rate is `_rate(delivery_rate)`.
  - **Projects table.** It follows Arms under the heading line `Projects (one row per arm and project; owner $ / lineage counts owner calls and owner pings):`, with the columns arm, project, n, delivered, rate, $ / delivered, owner $ / lineage and ping $.
  - **Comparison table.** Only when `doc["comparison"]` is not `None`, it follows Projects under `Comparison (candidate against the pooled baseline; rate change in percentage points):`. Its columns: project, baseline n, candidate n, baseline rate, candidate rate, rate change, baseline owner $ / lineage, candidate owner $ / lineage, ratio.
    - The first row, `all`, comes from the two arm rows. One row per `comparison["projects"]` entry follows, taking each side's values from that arm's project row, or `0` and `-` when the arm lacks the project.
    - Rate change is `f"{change * 100:+.1f}"` of the candidate rate minus the baseline rate, or `-` when either is `None`.
    - Ratio is `f"{ratio:.2f}"`, or `-`.
    - After the table: `$ / delivered: baseline <money>, candidate <money>, ratio <ratio or ->`.
  - **Footer.** After the `Unattributed:` line:
    - Unless `eval_grouping`: `Pings: <lines> ping lines read from <log>; attributed <money> (owner <money>); unattributed <n> pings, <money>; <unpriced> unpriced; <skipped_lines> lines skipped`. Without a log it reads `Pings: not read (pass --proxy-log PATH)`.
    - In start mode, one line per window: `Unsettled: <lineages> <arm> lineages, <money> (started within <settle_days>d of the report end)`.
- The six base tables and the base footer lines keep printing; `test_text_output_prints_the_six_tables` passes unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_owner_report.py`, add after `run`:

```python
TOP_KEYS = ["kind", "schema_version", "window", "start_grouping", "pricing", "lineages", "arms",
            "projects", "boots", "simulated", "calibration", "pings", "comparison", "unattributed",
            "interrupted", "unmatched"]
LINEAGE_KEYS = ["key", "run_id", "issue", "arm", "trial", "verdict", "direct", "launches",
                "handoffs", "boots", "deaths", "long_child_waits", "peak_context", "owner_dollars",
                "total_dollars", "delivered", "phase_reached", "phase7_entered", "gate_calls",
                "measured_gate_calls", "help_calls", "absolute_path_calls", "project", "started",
                "owner_ping_dollars", "ping_dollars"]


def text(root, *extra):
    """The owner report's text output over `root` (all time), which must exit 0."""
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--days", "0",
         "--projects-dir", str(root), *extra], capture_output=True, text=True, check=True).stdout
```

Add to `OwnerReportTest`:

```python
    def test_the_version_2_document_keys(self):
        self.chain(Session(self.root)).write()
        doc = report(self.root)
        self.assertEqual((list(doc), doc["schema_version"]), (TOP_KEYS, 2))
        self.assertEqual(list(doc["lineages"][0]), LINEAGE_KEYS)
        self.assertEqual((doc["start_grouping"], doc["pings"], doc["comparison"]), (None, None, None))

    def test_text_output_prints_projects_comparison_pings_and_unsettled(self):
        self.two_windows()
        log = self.root / "proxy.log"
        log.write_text(ping_line(30 * HOUR + 300, "s9", "k9", read=15_000), encoding="utf-8")
        out = text(self.root, "--baseline", "2026-10-25..2026-10-26", "--started",
                   "2026-10-26..2026-10-28", "--settle-days", "0", "--proxy-log", str(log))
        for line in ("Owner report (baseline ", "; settled 0d before ", "\nProjects (",
                     "\nComparison (", "\n$ / delivered: baseline ",
                     f"\nPings: 1 ping lines read from {log}; attributed ",
                     "\nUnsettled: 0 baseline lineages", "\nUnsettled: 0 candidate lineages"):
            self.assertIn(line, out)
        plain = text(self.root)
        self.assertIn("\nPings: not read (pass --proxy-log PATH)", plain)
        self.assertIn("\nProjects (", plain)
        for absent in ("\nComparison (", "\nUnsettled: "):
            self.assertNotIn(absent, plain)

    def test_eval_text_prints_no_pings_line(self):
        session = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo")
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()
        results = self.root / "results.jsonl"
        results.write_text(json.dumps({
            "skill": "from-issue", "id": 8, "trial": 1, "verdict": "PASS",
            "workdir": "/private/tmp/eval-from-issue-8.T1", "tree_rev": "a" * 40, "policy": None,
            "claude_exit": 0}) + "\n", encoding="utf-8")
        out = text(self.root, "--eval-results", str(results), "--eval", "from-issue:8")
        self.assertIn("\nProjects (", out)
        self.assertNotIn("Pings:", out)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Owner tests command with `-k version_2 -k projects_comparison -k eval_text` (timeout 300 s). It selects the three new tests.
Expected: FAIL. The keys test fails on `schema_version` 1 against 2. The two text tests fail their first `assertIn` (no `Projects (` or `Owner report (baseline … settled` text yet).

- [ ] **Step 3: Implement**

In `agent_owner_report.py`, set `SCHEMA_VERSION = 2`, make sure `build_document`'s literal lists the keys in `TOP_KEYS` order, and extend `print_document` per the invariants. Keep its docstring true: it prints the owner report's tables for `doc`, plus the comparison table when there is one. Split the comparison table into a helper `_print_comparison(doc, top)` beside `_print_simulated`. In `agent_costs._owners_report`, pass `eval_grouping`.

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 33 tests`, `OK`.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs:
- The **Owner report** paragraph's document becomes `schema_version` 2. Say that a v1 reader must update, because version 2 adds keys to every pinned key list (issue 503 D8).
- *Document.* gains the exact top-level key list above. Its text-output sentence says what the code prints:
  - the start-mode title;
  - the new Lineages and Arms columns;
  - the Projects table;
  - the Comparison table with its `all` row, its points and its `$ / delivered` line;
  - the `Pings:` line, including its no-log form and its absence in eval grouping;
  - the `Unsettled:` lines.

Run this gate. It exits 1 at the task's start commit, because the README still says version 1, and 0 once the README is updated:

```bash
if rg -q 'agent-owner-report. document \(.schema_version. 1\)' python/README.md; then exit 1; fi
```

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_report.py python/agent_tools/agent_costs.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): owner report schema 2 with project, comparison and ping text (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"6f29f9e37ed500515b8c9803f039dd90d69f8977","head":"584588bedafa4cecebdd5c11eb73ec613fd52973"}],"commit_subject_bytes":[64,64],"id":7,"records":[{"bounds":[{"added_lines":360,"boundary":"all","deleted_lines":60,"record_bytes":53248,"support":{"covers":["r1b","r2a","r3b","r4a","r5b","r6b","r7a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7a","last_task":7,"owner":7,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":20,"record_bytes":16384,"support":{"covers":["r4b","r5c","r6c","r7b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7b","last_task":7,"owner":7,"path":"python/agent_tools/agent_costs.py"},{"bounds":[{"added_lines":720,"boundary":"all","deleted_lines":20,"record_bytes":57344,"support":{"covers":["r1d","r2b","r3c","r4c","r5d","r6e","r7c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7c","last_task":7,"owner":7,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":12,"record_bytes":57344,"support":{"covers":["r1e","r2c","r3d","r4d","r5e","r6f","r7d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7d","last_task":7,"owner":7,"path":"python/README.md"}]}}
```
