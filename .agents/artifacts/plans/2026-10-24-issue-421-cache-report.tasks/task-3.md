# Task 3: `--report cache` — flags, aggregation, the three tables and the contract docs

Spec § Command surface, § Module boundary, § Output and § Documentation, per D1, D2, D3, D13 and D14. `agent_costs.main` gains `--report {issues,cache}` and `--context-threshold`, lets the event bounds serve the cache report, validates the combinations, and in the cache branch imports `agent_cache_report`, which selects the transcripts, scans them through `scan_paths` with Task 2's scanner, and prints the header, the three tables, the totals line and the `NOTE:` footer.

**Files:**
- Modify: `python/agent_tools/agent_costs.py` (module docstring, new `_positive_int`, `main`)
- Modify: `python/agent_tools/agent_cache_report.py` (module docstring; new `transcript_jobs`, `scan_jobs`, `print_report`)
- Modify: `tests/test_agent_costs.py` (new `cache_tree`, `CacheReportCliTest`, after `CacheScanTest`)
- Modify: `python/README.md` (the `## agent-costs` section Task 1 added)

**Interfaces:**
- Consumes (Task 2): `scan_transcript(job, *, since, before, threshold)` and its result dict; `DEFAULT_CONTEXT_THRESHOLD`; `STARTUP_ATTACHMENTS`; the test helpers `write_root`, `write_subagent`, `handback_death_lines`, `user_prompt`, `cache_call`, `attachment`. From base: `run_main`, `find_sessions(root, cutoff)`, `scan_paths(items, executor_factory, scanner=None)`, `format_rfc3339_utc`, `percentile`, `human`, `print_table(rows, headers, aligns)`, `DISCLAIMER`.
- Produces:
  - `agent_cache_report.transcript_jobs(root: Path, mtime_cutoff: float | None) -> list[tuple[Path, bool]]` — for each session `find_sessions(root, mtime_cutoff)` yields, its root files as `(path, True)` then its subagent files as `(path, False)`.
  - `agent_cache_report.scan_jobs(jobs, *, since, before, threshold, executor_factory) -> list[dict]` — `scan_paths(jobs, executor_factory, scanner=functools.partial(scan_transcript, since=since, before=before, threshold=threshold))`, `None` results dropped, order kept.
  - `agent_cache_report.print_report(results, *, window: str, threshold: int, top: int) -> None` — prints the report to stdout.

**Invariants:**
- `--report` is `choices=("issues", "cache")`, default `"issues"`; `--context-threshold` takes `type=_positive_int`, `metavar="TOKENS"`, default `None`. `_positive_int(text)` returns `int(text)` when it is a positive integer and otherwise raises `argparse.ArgumentTypeError` (argparse turns both that and a non-integer into exit 2).
- Usage errors (exit 2 via `ap.error`, nothing on stdout), checked before anything is scanned: `--report cache` with `--format json`, with `--project`, or with `--artifacts`; `--context-threshold` without `--report cache`; event bounds with neither `--format json` nor `--report cache` (the existing message becomes `--events-since/--events-before are available only with --format json or --report cache`). The existing `--strata`, together, RFC3339 and `since < before` checks stay and so also cover the cache report.
- The cache branch runs right after `cutoff` is computed and returns before any issue-report work: no transcript root → the existing `sys.exit(f"no transcript root at {root}")`; `jobs = agent_cache_report.transcript_jobs(root, event_start.timestamp() if event_start else cutoff)`; no jobs → `sys.exit("no transcripts in window")`; `threshold = args.context_threshold or DEFAULT_CONTEXT_THRESHOLD`; scan with `since=event_start, before=event_end` and the injected `executor_factory`; no result with `calls > 0` → `sys.exit("no calls in window")`; `window` is `f"events {format_rfc3339_utc(event_start)} → {format_rfc3339_utc(event_end)}"` with bounds, else `f"last {args.days}d by file mtime"` when `cutoff` is set, else `"all time"`; then `print_report(results, window=window, threshold=threshold, top=args.top)`.
- `--report issues` output is byte-identical (golden unchanged).
- `print_report` prints, in order (D13):
  1. `f"Cache report ({window}, {T:,} transcripts, {C:,} calls)\n"` — `T` counts results with `calls > 0`, `C` sums `calls`.
  2. `"Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm read):\n"`, then the capped table with headers `["agent type", "cause", "deaths", "median gap", "premium"]`, aligns `l l r r r`: one row per `(agent_type, kind)` over every death — `f"{n:,}"`, `f"{percentile(gaps, 50) / 60:.1f}m"`, `f"${premium:,.0f}"` — sorted by premium descending, deaths descending, agent type, kind.
  3. `f"\nSubagent deaths {n:,} (${p:,.0f} premium); main-session deaths {m:,} (${q:,.0f})"` over every death, split by `is_root`.
  4. `f"\nReread above {human(threshold)} tokens of context (cache reads past that position at the read price; peak = largest single-call context per transcript):\n"`, then the capped table `["agent type", "transcripts", "reread above", "peak p50", "peak p90", "peak max"]`, aligns `l r r r r r`: one row per agent type over results with `calls > 0` — `f"{n:,}"`, `f"${sum:,.0f}"`, `human(percentile(peaks, 50))`, `human(percentile(peaks, 90))`, `human(max(peaks))` — sorted by the dollar sum descending, then agent type.
  5. `"\nSubagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):\n"`, then the capped table `["agent type", "subagents", "1st write", "1st read", "skill listing", "instructions", "MCP instructions", "deferred tools", "agent listing", "environment"]`, aligns `l` then nine `r`: one row per agent type over results whose `startup` is not `None` — `f"{n:,}"`, `human(percentile(writes, 50))`, `human(percentile(reads, 50))`, then for each type in `STARTUP_ATTACHMENTS` order `human(percentile(sizes, 50))`, or `"-"` when no subagent of that agent type carried it — sorted by subagents descending, then agent type.
  6. `f"\nNOTE: {DISCLAIMER}"`.
- A capped table prints `print_table(rows[:top], headers, aligns)` and, when `len(rows) > top`, `f"\n... {len(rows) - top} more rows not shown (--top {len(rows)} for all)"`.

- [ ] **Step 1: Write the failing tests**

Add, directly after `class CacheScanTest`:

```python
def cache_tree(root):
    """A main session, the hand-back parent and an Explore subagent with a skill listing."""
    write_root(root, [user_prompt(0), cache_call("r1", 1, 0, 20_000, ttl="1h"),
                      cache_call("r2", 30, 20_000, 500, ttl="1h")])
    write_subagent(root, handback_death_lines(), name="agent-a1")
    write_subagent(root, [user_prompt(0), attachment("skill_listing", 24_000, 0),
                          cache_call("e1", 2, 3_323, 12_907), cache_call("e2", 4, 16_230, 900)],
                   agent_type="Explore", name="agent-a2")
    return root


DEATH_ROW = r"(?m)^general-purpose\s+hand-back after end of turn\s+1\s+9\.0m\s+\$0$"


class CacheReportCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = cache_tree(Path(self.tmp.name))

    def report(self, *argv):
        return run_main("--projects-dir", str(self.root), "--report", "cache", *argv)

    def test_the_cache_report_prints_three_tables_and_the_totals(self):
        out, code = self.report("--days", "0")
        self.assertIsNone(code)
        self.assertTrue(out.startswith("Cache report (all time, 3 transcripts, 7 calls)\n\n"),
                        out[:200])
        self.assertRegex(out, r"(?m)^agent type\s+cause\s+deaths\s+median gap\s+premium$")
        self.assertRegex(out, DEATH_ROW)
        self.assertIn("\nSubagent deaths 1 ($0 premium); main-session deaths 0 ($0)\n", out)
        self.assertIn("\nReread above 120.00k tokens of context", out)
        self.assertRegex(out, r"(?m)^agent type\s+transcripts\s+reread above\s+peak p50"
                              r"\s+peak p90\s+peak max$")
        self.assertRegex(out, r"(?m)^main\s+1\s+\$0\s+20\.50k\s+20\.50k\s+20\.50k$")
        self.assertRegex(out, r"(?m)^agent type\s+subagents\s+1st write\s+1st read\s+skill listing"
                              r"\s+instructions\s+MCP instructions\s+deferred tools"
                              r"\s+agent listing\s+environment$")
        self.assertRegex(out, r"(?m)^Explore\s+1\s+12\.91k\s+3\.32k\s+24\.00k(\s+-){5}$")
        self.assertRegex(out, r"(?m)^general-purpose\s+1\s+30\.00k\s+0(\s+-){6}$")
        self.assertTrue(out.endswith(f"\nNOTE: {agent_costs.DISCLAIMER}\n"))

    def test_event_bounds_select_calls_by_start_and_name_the_window(self):
        out, code = self.report("--events-since", "2026-10-12T09:05:00Z",
                                "--events-before", "2026-10-12T09:10:00Z")
        self.assertIsNone(code)
        self.assertTrue(out.startswith(
            "Cache report (events 2026-10-12T09:05:00Z → 2026-10-12T09:10:00Z, "
            "1 transcripts, 1 calls)\n"), out[:200])
        self.assertRegex(out, DEATH_ROW)

    def test_an_empty_selection_exits_instead_of_printing_zeros(self):
        out, code = self.report("--events-since", "2026-10-13T00:00:00Z",
                                "--events-before", "2026-10-14T00:00:00Z")
        self.assertEqual((out, code), ("", "no calls in window"))
        with tempfile.TemporaryDirectory() as empty:
            (Path(empty) / "-Users-me-empty").mkdir()
            out, code = run_main("--projects-dir", empty, "--report", "cache", "--days", "0")
        self.assertEqual((out, code), ("", "no transcripts in window"))

    def test_top_caps_each_table_and_says_how_many_rows_it_dropped(self):
        out, code = self.report("--days", "0", "--top", "1")
        self.assertIsNone(code)
        self.assertIn("\n... 2 more rows not shown (--top 3 for all)\n", out)  # reread
        self.assertIn("\n... 1 more rows not shown (--top 2 for all)\n", out)  # start-up
        self.assertRegex(out, DEATH_ROW)

    def test_the_threshold_flag_reaches_the_scanner_and_the_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_root(Path(tmp), [user_prompt(0)] + [
                cache_call(f"r{i}", 10 * i, 900_000, 1_000, ttl="1h") for i in range(1, 11)])
            default, _ = run_main("--projects-dir", tmp, "--report", "cache", "--days", "0")
            raised, _ = run_main("--projects-dir", tmp, "--report", "cache", "--days", "0",
                                 "--context-threshold", "500000")
        # ten Opus reads of 900k: 10 x 780k x $0.50 / 1e6 = $3.90; above 500k, $2.00
        self.assertRegex(default, r"(?m)^main\s+1\s+\$4\s+")
        self.assertIn("\nReread above 120.00k tokens of context", default)
        self.assertRegex(raised, r"(?m)^main\s+1\s+\$2\s+")
        self.assertIn("\nReread above 500.00k tokens of context", raised)

    def test_cache_report_usage_errors_exit_2_with_nothing_on_stdout(self):
        cases = {
            "json": ("--report", "cache", "--format", "json"),
            "project": ("--report", "cache", "--project", "repo"),
            "artifacts": ("--report", "cache", "--artifacts", str(self.root)),
            "strata": ("--report", "cache", "--strata", "both"),
            "one bound": ("--report", "cache", "--events-since", "2026-10-12T09:00:00Z"),
            "inverted": ("--report", "cache", "--events-since", "2026-10-12T10:00:00Z",
                         "--events-before", "2026-10-12T09:00:00Z"),
            "no offset": ("--report", "cache", "--events-since", "2026-10-12T09:00:00",
                          "--events-before", "2026-10-12T10:00:00Z"),
            "zero threshold": ("--report", "cache", "--context-threshold", "0"),
            "threshold on the issue report": ("--context-threshold", "120000"),
            "bounds on the issue tables": ("--events-since", "2026-10-12T09:00:00Z",
                                           "--events-before", "2026-10-12T10:00:00Z"),
            "unknown report": ("--report", "deaths"),
        }
        for name, argv in cases.items():
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_main("--projects-dir", str(self.root), *argv), ("", 2))

    def test_the_module_run_reports_through_a_real_process_pool(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--projects-dir", str(self.root),
             "--report", "cache", "--days", "0"],
            capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertRegex(completed.stdout, DEATH_ROW)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (focused test run, timeout 600 s): `-k CacheReportCliTest`
Expected: `FAILED (failures=6)` — argparse rejects `--report` (exit 2, empty stdout); `test_cache_report_usage_errors_exit_2_with_nothing_on_stdout` already passes, since every case is exit 2 while the flag is unknown.

- [ ] **Step 3: Implement**

`agent_cache_report`: add `transcript_jobs`, `scan_jobs` and `print_report` per Interfaces and Invariants, importing `functools`, `find_sessions`, `scan_paths`, `human`, `percentile`, `print_table` and `DISCLAIMER` from `agent_costs` (no copies). Replace the module docstring's first line and add its last sentences so it reads exactly:

```python
"""The agent-costs cache report (issue 421).

scan_transcript reads one Claude Code transcript and returns its calls in the
window, its cache deaths with their cause and premium, its cache-read cost above
a context threshold, its peak context and, for a subagent, its start-up overhead.
agent_costs.main runs the report for `--report cache`: transcript_jobs selects the
transcripts, scan_jobs scans them through agent_costs.scan_paths and print_report
prints the three tables. python/README.md (agent-costs) holds the contract.
"""
```

`agent_costs`: add `_positive_int` above `main`; add the two arguments; make the help of `--events-since`/`--events-before` read `RFC3339 event-time lower bound (JSON or --report cache)` / `… upper bound …`; add the checks and the branch per Invariants, with the import inside the branch carrying the comment `# imported only for the cache report (issue 421 D2)`. Append this paragraph to the module docstring, after its last paragraph:

```
`--report cache` prints the cache report instead of the per-issue tables (issue
421, agent_tools.agent_cache_report): cache deaths by agent type and cause, the
cache-read cost of context above `--context-threshold` tokens (default 120,000)
with peak-context percentiles, and subagent start-up overhead, over the calls
whose start lies between `--events-since` and `--events-before` when both are
given. python/README.md (agent-costs) holds its contract.
```

`python/README.md`: append these three paragraphs to the end of the `## agent-costs` section, exactly:

```markdown
`--report cache` (issue 421; `agent_tools.agent_cache_report`) prints a cache report in place of the per-issue tables, which the default `--report issues` prints unchanged. It is text only: `--format json`, `--project`, `--artifacts`, `--strata` other than `claude`, one event bound without the other, a bound without an offset, or an `--events-since` not before `--events-before` is a usage error (exit 2, nothing on stdout), as is `--context-threshold` with the per-issue report. With `--events-since/--events-before` a call counts when its earliest record timestamp lies in `[since, before)`, transcripts last modified before `since` are skipped and `--days` is ignored; without them `--days` selects transcripts by file mtime and every call in them counts. The report prints a header naming the window, three tables each capped at `--top` rows with a line saying how many it dropped, and the comparative-telemetry note; a run that selects no transcript exits `no transcripts in window`, and one whose transcripts hold no counting call exits `no calls in window`.

A call is one `message.id` of a transcript (else `requestId`, else `uuid`), each usage field taken as its maximum over the call's records; its context is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, and a message whose context is 0 is no call. A cache death is a counting call that started more than the TTL less 10 s after its predecessor's last record (1 h for a main session's transcript, 5 min for a subagent's), whose predecessor's context exceeded 5,000 tokens, and whose cache creation exceeds half that context. Its cause is the tool of the last result, between the two calls, of one of the predecessor's own tool uses (`child dispatch` for `Agent` or `Task`, `long foreground command` for `Bash`, `other tool` otherwise), a result marked `toolEndsTurn` excepted; without one, the first other user record between them decides (`hand-back after end of turn` for a `peer` origin with `handback: true`, `task notification after end of turn` for a `task-notification` origin, `message after end of turn` for any other), and with neither it is `unclassified`. The deaths table shows each agent type and cause with its count, median gap and premium, `min(cache creation, predecessor context)` at the call's write price, weighted by its own 1-hour/5-minute split, less the read price; a totals line splits subagent and main-session deaths.

The reread table shows, per agent type, the transcripts with a counting call, the summed `max(0, cache_read_input_tokens − T)` of their counting calls at the read price, where `T` is `--context-threshold` (default 120,000), and the median, p90 and maximum of each transcript's largest counting-call context; every median and p90 is nearest-rank. The start-up table shows, per subagent type, the subagents whose first call counts, the median cache write and read of that call, and the median character count of the `rendered` content of the first `skill_listing`, `instructions`, `mcp_instructions_delta`, `deferred_tools_delta`, `agent_listing_delta` and `environment` attachment recorded before the second call, over the subagents that carried one (`-` when none did). A subagent's agent type is the `agentType` of its sibling `.meta.json` (`unknown` without one), and a main session's is `main`.
```

- [ ] **Step 4: Verify**

Run (focused test run, timeout 600 s): `-k CacheReportCliTest`
Expected: `Ran 7 tests` … `OK`.

Run (focused test run, timeout 600 s) with no `-k`.
Expected: `Ran 109 tests` … `OK` (`TextByteIdentityTest` and `ModuleEntryPointTest` green unmodified).

Run: `bash -c 'set -e; if grep -n "^from agent_tools import agent_cache_report\|^import agent_tools.agent_cache_report" python/agent_tools/agent_costs.py; then exit 1; fi; grep -c "from agent_tools import agent_cache_report" python/agent_tools/agent_costs.py; git diff --stat 7601d318 -- tests/fixtures justfile lib CLAUDE.md'`
Expected: exit 0 printing `1` (the import sits indented inside the branch, never at module level) and no diffstat line.

Run (build, timeout 3600 s).
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py python/agent_tools/agent_cache_report.py tests/test_agent_costs.py python/README.md
launch-commit … -- -m "feat(agent-costs): --report cache prints deaths, reread and start-up tables (issue 421)" \
  -m "--context-threshold sets the reread threshold; --events-since/--events-before select the calls. python/README.md holds the contract." \
  -m "<session trailers>"
```
