# Task 3: Baseline window, arms and the boot's project

**Files:**
- Modify: `python/agent_tools/agent_costs.py`
- Modify: `python/agent_tools/agent_boot_report.py`
- Modify: `python/agent_tools/agent_boot_rollup.py`
- Modify: `python/README.md`
- Test: `tests/test_agent_boot_report.py`

**Interfaces:**
- Consumes:
  - From Task 2: `agent_boot_rollup.group_rows(host, boots, buckets)`, `ALL`, and the v2 boot rows (`boot_reading`, `first_unit_work` after `b`) and group rows (`b_median`, …, `bucket_medians`). `SCHEMA_VERSION` is 2.
  - From `agent_owner_report`, unchanged: `parse_range(text) -> (since, before)` (ValueError on a bad range, or when SINCE is not before BEFORE), `StartWindow(arm, since, before)`, `start_window_label(windows)`, `LIVE_ARM`, `BASELINE_ARM`, `CANDIDATE_ARM`, and `Lineage.facts["project"]` (#503 D4).
- Produces:
  - `agent_boot_rollup.group_rows(arm, host, boots, buckets)`. Its rows start with `"arm": arm`; the rest is as in Task 2.
  - `agent_boot_report.collect_host(label, root, *, arm, cutoff, since, before, executor_factory) -> dict`. The host dict is as today, and each boot row holds exactly `arm, host, transcript, run_id, issue, project, cohort, phase_group, calls, start, b, boot_reading, first_unit_work, buckets, skills, skill_files`.
  - `agent_boot_report.build_document(collected, *, window) -> dict`. `collected` is a list of `(arm, hosts)` pairs in arm order, each `hosts` being `collect_host` results in argument order. The top-level keys are exactly `kind, schema_version, window, hosts, chars_per_token, observed_chars_per_token, unsplit, boots, groups, reweighted`, and `reweighted` is `None` (Task 4 fills it).
  - Test fixtures that Task 4 reuses: `two_call_boot(..., repo_root="/Users/me/repo")`, `BASELINE`, `BASELINE_EVENTS`, `EVENTS`, `WINDOW_BOOTS`, and the class `WindowsTest` with `write_boots(boots)`.

**Invariants:**
- Without `--baseline`, every boot and group row has the arm `live` (`LIVE_ARM`), and the window label and text headings are today's (D11).
- With `--baseline`, each root is collected once per window by the event-window rule: since and before are that window's bounds, and the mtime cutoff is its start. So each arm's boot and group rows, less `arm`, equal those of a lone run over that window (D1). A boot that is not whole in a window is in no arm.
- A boot's `project` is read from `lineage.facts["project"]` and never derived again (D2).
- The owner report's flags and its `--baseline` rules are unchanged, and so are `--started`, `--settle-days` and `--proxy-log`, which stay owners-only. Every usage error exits 2 before any root is read, and a missing root still exits 1.
- Owner tests stay green: `tests/test_agent_owner_report.py::test_comparison_usage_errors` still sees `--report boot --baseline R`, with no event window, as exit 2.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_boot_report.py`:
- `two_call_boot` gains the keyword `repo_root="/Users/me/repo"` and passes it on as `progress(phase, action_id=..., repo_root=repo_root)`.
- The three `unsplit` assertions become arm-keyed (D6). In `test_negative_or_unexplained_growth_and_a_boot_without_request_records`, `{HOST: 1}` becomes `{"live": {HOST: 1}}`. In `test_cohorts_follow_lineage_position_and_launch_ordinal_and_groups_pool_them`, `{HOST: 0}` becomes `{"live": {HOST: 0}}`. In `test_each_root_is_its_own_host_and_all_pools_every_boot`, `{"alpha": 0, "beta": 0}` becomes `{"live": {"alpha": 0, "beta": 0}}`.

Add these constants after `BUCKETS`:

```python
BASELINE = "2026-10-25T09:00:00Z..2026-10-25T10:00:00Z"
BASELINE_EVENTS = ("--events-since", "2026-10-25T09:00:00Z",
                   "--events-before", "2026-10-25T10:00:00Z")
EVENTS = ("--events-since", "2026-10-25T10:00:00Z", "--events-before", "2026-10-25T11:00:00Z")
WINDOW_BOOTS = (  # (seconds after T0, issue, project, phase, start, end): four boots in the
                  # baseline window, four in the event window and one after both
    (100, 11, "alpha", 6, 24_000, 40_000), (200, 12, "beta", 6, 28_000, 52_000),
    (300, 13, "beta", 6, 28_000, 54_000), (400, 14, "beta", 6, 28_000, 56_000),
    (3_700, 21, "alpha", 6, 20_000, 30_000), (3_800, 22, "alpha", 6, 21_000, 32_000),
    (3_900, 23, "alpha", 6, 22_000, 34_000), (4_000, 24, "beta", 6, 26_000, 50_000),
    (7_300, 31, "alpha", 6, 20_000, 99_000))
TOP_KEYS = ["kind", "schema_version", "window", "hosts", "chars_per_token",
            "observed_chars_per_token", "unsplit", "boots", "groups", "reweighted"]
BOOT_KEYS = ["arm", "host", "transcript", "run_id", "issue", "project", "cohort", "phase_group",
             "calls", "start", "b", "boot_reading", "first_unit_work", "buckets", "skills",
             "skill_files"]
GROUP_KEYS = ["arm", "host", "cohort", "phase_group", "count", "b_mean", "b_median",
              "b_without_schemas_mean", "b_without_schemas_median", "boot_reading_mean",
              "boot_reading_median", "first_unit_work_mean", "first_unit_work_median", "buckets",
              "bucket_medians"]
```

Add this class before `if __name__ == "__main__":`:

```python
class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_boots(self, boots):
        """One session holding a fresh owner (launch 2) per `(seconds, issue, project, phase,
        start, end)`, registering with `--repo-root /Users/me/<project>`."""
        session = Session(self.root)
        for seconds, issue, project, phase, start, end in boots:
            two_call_boot(session, f"o{issue}", seconds, issue=issue, launch=2, phase=phase,
                          start=start, end=end, repo_root=f"/Users/me/{project}")
        session.write()

    def test_without_a_baseline_every_row_is_live_and_reweighted_is_null(self):
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=EVENTS)
        self.assertEqual(list(document), TOP_KEYS)
        self.assertEqual(document["window"], "events 2026-10-25T10:00:00Z → 2026-10-25T11:00:00Z")
        self.assertEqual(
            [(row["arm"], row["issue"], row["project"]) for row in document["boots"]],
            [("live", 21, "alpha"), ("live", 22, "alpha"), ("live", 23, "alpha"),
             ("live", 24, "beta")])
        for row in document["boots"]:
            self.assertEqual(list(row), BOOT_KEYS)
        for row in document["groups"]:
            self.assertEqual((list(row), row["arm"]), (GROUP_KEYS, "live"))
        self.assertEqual((document["unsplit"], document["reweighted"]), ({"live": {HOST: 0}}, None))

    def test_a_baseline_collects_each_window_as_its_lone_run_does(self):
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        self.assertEqual(list(document), TOP_KEYS)
        self.assertEqual(document["window"],
                         "baseline 2026-10-25T09:00:00Z → 2026-10-25T10:00:00Z; "
                         "candidate 2026-10-25T10:00:00Z → 2026-10-25T11:00:00Z")
        self.assertEqual(
            [(row["arm"], row["issue"], row["project"]) for row in document["boots"]],
            [("baseline", 11, "alpha"), ("baseline", 12, "beta"), ("baseline", 13, "beta"),
             ("baseline", 14, "beta"), ("candidate", 21, "alpha"), ("candidate", 22, "alpha"),
             ("candidate", 23, "alpha"), ("candidate", 24, "beta")])
        self.assertEqual([row["arm"] for row in document["groups"]],
                         ["baseline"] * 4 + ["candidate"] * 4)
        self.assertEqual(document["unsplit"], {"baseline": {HOST: 0}, "candidate": {HOST: 0}})

        def without_arm(rows, arm):
            return [{key: value for key, value in row.items() if key != "arm"}
                    for row in rows if row["arm"] == arm]

        for arm, window in (("baseline", BASELINE_EVENTS), ("candidate", EVENTS)):
            with self.subTest(arm=arm):
                alone = report(self.root, extra=window)
                self.assertEqual(without_arm(document["boots"], arm),
                                 without_arm(alone["boots"], "live"))
                self.assertEqual(without_arm(document["groups"], arm),
                                 without_arm(alone["groups"], "live"))

    def test_baseline_usage_errors_come_before_any_root_is_read(self):
        missing = str(self.root / "missing")
        for extra in (["--baseline", BASELINE],
                      [*EVENTS, "--baseline", "2026-10-25T09:00:00Z"],
                      [*EVENTS, "--baseline", "2026-10-25T10:00:00Z..2026-10-25T09:00:00Z"],
                      [*EVENTS, "--baseline", "2026-10-25T09:30:00Z..2026-10-25T10:30:00Z"]):
            with self.subTest(extra=extra):
                completed = costs("--format", "json", "--projects-dir", missing, *extra)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        for name in ("issues", "cache"):
            with self.subTest(report=name):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", name,
                     "--projects-dir", missing, "--baseline", BASELINE],
                    capture_output=True, text=True, check=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        touching = costs("--format", "json", "--projects-dir", missing, *EVENTS,
                         "--baseline", "2026-10-25..2026-10-25T10:00:00Z")
        self.assertEqual(touching.returncode, 1, touching.stderr)   # parsed; the root is missing

    def test_text_output_with_a_baseline_prints_each_arm_in_turn(self):
        self.write_boots(WINDOW_BOOTS)
        completed = costs("--projects-dir", str(self.root), *EVENTS, "--baseline", BASELINE)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        self.assertIn("; baseline 4 boots: 4 fresh, 0 spawned; "
                      "candidate 4 boots: 4 fresh, 0 spawned;", out)
        self.assertRegex(out, r"\bissue +project +cohort\b")
        positions = [out.find(heading) for heading in (
            "Boot composition (", f"Mean boot buckets, baseline, host {HOST} ",
            "Mean boot buckets, baseline, all hosts", "Top skill bodies and skill files, baseline",
            "Boots by B, baseline", f"Mean boot buckets, candidate, host {HOST} ",
            "Mean boot buckets, candidate, all hosts",
            "Top skill bodies and skill files, candidate", "Boots by B, candidate",
            "Observed characters per token",
            f"Unsplit boots (no request records, left out): baseline {HOST} 0; candidate {HOST} 0\n",
            "NOTE: ")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
```

Planning ran `WINDOW_BOOTS` through the base report, once per window as an event window. The windows select issues 11–14 (baseline; projects alpha, beta, beta, beta) and 21–24 (candidate; alpha, alpha, alpha, beta), all `fresh`, `6-7`, and issue 31 is in neither.

- [ ] **Step 2: Run the tests and watch them fail**

Run the Boot tests (Global Constraints), whole module.
Expected: FAIL. The three edited `unsplit` assertions fail. `test_without_a_baseline…` fails on its key list. The baseline, text and touching-window checks fail because today `--baseline` with `--report boot` exits 2.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/agent_boot_rollup.py`: `group_rows(arm, host, boots, buckets)` puts `"arm": arm` first in each row. Docstring: name the arm.

`python/agent_tools/agent_boot_report.py`:
- Import `LIVE_ARM` from `agent_owner_report`.
- `collect_host` gains the keyword `arm`. Each boot's identity is built in the order `arm, host, transcript, run_id, issue, project, cohort, phase_group`, where `project` is `lineage.facts["project"]`. The rest of the row is as in Task 2.
- `build_document(collected, *, window)`:
  - `hosts` is `{label, root}` of the first arm's hosts.
  - `boots` is every boot, arm by arm and host by host.
  - `groups`: for each arm, `group_rows(arm, label, host boots, BUCKETS)` per host, then `group_rows(arm, ALL, the arm's boots, BUCKETS)`.
  - `observed_chars_per_token` pools every host dict of every arm (D6).
  - `unsplit` is `{arm: {label: unsplit} for each arm}` in arm order.
  - `reweighted` is `None`.

  Docstring: "The `agent-boot-report` document of `collected`: `(arm, hosts)` pairs in arm order, each `hosts` being collect_host's results in argument order."
- `print_document`, per D11. The arms are `list(doc["unsplit"])`. Each arm's prefix is `""` when the arms are `[LIVE_ARM]`, else `f"{arm} "`, and each heading's tag is `""` or `f", {arm}"` likewise.
  - Header: `Boot composition ({window}; hosts: {hosts}; {counts}; call 0 at {cpt} characters per token)`. `counts` joins with `"; "`, per arm, `f"{prefix}{n:,} boots: {fresh:,} fresh, {n - fresh:,} spawned"` over that arm's boots.
  - Then for each arm in turn:
    - the mean tables, each headed `\nMean boot buckets{tag}, {title} (tokens per boot):\n` and filtered to the arm and the host;
    - `\nTop skill bodies and skill files{tag} (mean and median tokens per fresh boot, all hosts):\n` over the arm's boots;
    - `\nBoots by B{tag} (host, issue, project, cohort, phase, calls, start, B, boot reading, first-unit work, then each bucket):\n` over the arm's boots, with a left-aligned `project` column after `issue`.
  - Observed-ratio line as today.
  - `Unsplit boots (no request records, left out): ` plus, joined with `"; "`, `prefix + ", ".join(f"{label} {count:,}" …)` per arm.
  - The `NOTE:` line last.
- Module docstring: collection is once per arm and window. Name `--baseline`.

`python/agent_tools/agent_costs.py`:
- In `main`, replace the check `--baseline is available only with --report owners` with three checks, in this order:
  - `ap.error("--baseline is available only with --report owners or boot")` when it is neither;
  - `--baseline needs --started` for owners only;
  - `ap.error("--report boot --baseline needs --events-since/--events-before")` when `boot_report and not args.events_since`.

  Leave every other check as it is.
- `_boot_report(ap, args, cutoff, event_start, event_end, executor_factory)`. After `parse_roots` and before the `is_dir` loop:
  - `windows = [(LIVE_ARM, event_start, event_end)]` and `window = _window_label(args, cutoff, event_start, event_end)`.
  - With `args.baseline`:
    - `since, before = agent_owner_report.parse_range(args.baseline)`, mapping ValueError to `ap.error(f"--baseline: {error}")`;
    - `if since < event_end and event_start < before: ap.error("--baseline must not overlap --events-since/--events-before")`;
    - `windows = (StartWindow(BASELINE_ARM, since, before), StartWindow(CANDIDATE_ARM, event_start, event_end))` and `window = start_window_label(windows)`.

  Then `collected = [(arm, [collect_host(label, root, arm=arm, cutoff=since.timestamp() if since else cutoff, since=since, before=before, executor_factory=executor_factory) for label, root in roots]) for arm, since, before in windows]` and `build_document(collected, window=window)`. Import `agent_owner_report` lazily beside `agent_boot_report`.
- `--baseline` help: "a second, non-overlapping window whose lineages (--report owners, beside --started) or boots (--report boot, beside --events-since/--events-before) form the baseline arm against the candidate arm". Add to the module docstring, after the owner report's paragraph: "`--report boot` prints the boot report (issue 448, agent_tools.agent_boot_report); `--baseline SINCE..BEFORE` beside `--events-since/--events-before` splits its boots into a baseline and a candidate arm (issue 504)."

`python/README.md`:
- **Owner report** paragraph: replace `` `--baseline` with any other `--report`, `` with `` `--baseline` with a `--report` other than `owners` or `boot` (see *Windows and arms*), ``.
- **Boot report** paragraph:
  - In the version note, `adds the boot row keys \`boot_reading\` and \`first_unit_work\` and the group row medians and sub-totals` becomes `adds the boot row keys \`arm\`, \`project\`, \`boot_reading\` and \`first_unit_work\`, the group row key \`arm\` and the group row medians and sub-totals, keys \`unsplit\` by arm and adds the top-level \`reweighted\``.
  - In the takes list, `and \`--events-since/--events-before\` (with the owner report's window rule)` becomes `, \`--events-since/--events-before\` (with the owner report's window rule) and \`--baseline SINCE..BEFORE\` (see *Windows and arms*)`.
  - Its refusal list gains, before `each as a usage error`: `and \`--baseline\` without \`--events-since/--events-before\`, with a range that does not parse or whose \`SINCE\` is not before its \`BEFORE\`, or with a window that overlaps the event window`. That sentence ends `…with nothing on stdout, raised before any root is read.`
- Add after that paragraph:

  > *Windows and arms (issue 504).* `--baseline SINCE..BEFORE` takes the owner report's range grammar (see *Start mode*): a half-open window whose bounds are each a `YYYY-MM-DD` UTC day or an RFC3339 instant with an offset. Here it needs `--events-since/--events-before`, whose window becomes the candidate's. The two windows must not overlap; windows that touch are allowed (issue 504 D1). Without `--baseline` every boot and group row has the arm `live`. With it, each row has the arm `baseline` or `candidate`, and the baseline comes first. Each root is collected once per window by the event-window rule: the window's bounds, with the mtime cutoff at its start. So an arm's boots, cohorts and statistics are exactly those of a lone run over its window. A boot is in an arm only when the owner report keeps it whole in that arm's window, so a boot that straddles the two windows is in neither. With `--baseline`, `window` is `baseline <SINCE> → <BEFORE>; candidate <SINCE> → <BEFORE>`, with the bounds as RFC3339 UTC instants.

- *Boots and cohorts.*: after `its \`phase_group\` is the owner report's (\`0-5\` or \`6-7\`)`, add `, and its \`project\` is its lineage row's (see *Project and start*, issue 504 D2)`. After `the groups table has one set of rows per host label`, add `within each arm, in arm order,`.
- *Document.*:
  - The key list gains `reweighted` after `groups`.
  - `` `unsplit` maps a host label to its count `` becomes `` `unsplit` maps each arm, in arm order, to its map of host label to count ``.
  - The boot row list becomes the `BOOT_KEYS` order above, and the group row list starts `arm, host,`.
  - Add the sentence: "Boot and group rows are ordered by arm, then as before, and `reweighted` is `null`."

Check each README clause against the code you wrote, and correct the README wherever they differ.

- [ ] **Step 4: Verify**

Run the Boot tests (Global Constraints), whole module.
Expected: `Ran 21 tests`, `OK`.

Run the Owner tests (Global Constraints).
Expected: `Ran 70 tests`, `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py python/agent_tools/agent_boot_report.py \
  python/agent_tools/agent_boot_rollup.py python/README.md tests/test_agent_boot_report.py
launch-commit --repo-root <ledger repo root> --run-id <run id> --worker-id <worker id> -- \
  -m "feat(boot-report): add a baseline window, arms and each boot's project" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"0a5dc9ccf8df4c41c11751ce67abc705fd599e59","head":"f44a13d2fa8828f559f5d065c8aa0a1e9d464080"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":10,"record_bytes":12288,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/agent_costs.py"},{"bounds":[{"added_lines":160,"boundary":"all","deleted_lines":80,"record_bytes":36864,"support":{"covers":["r1a","r2b","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":4,"owner":3,"path":"python/agent_tools/agent_boot_report.py"},{"bounds":[{"added_lines":85,"boundary":"all","deleted_lines":0,"record_bytes":9216,"support":{"covers":["r2a","r3c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r3c","last_task":4,"owner":3,"path":"python/agent_tools/agent_boot_rollup.py"},{"bounds":[{"added_lines":9,"boundary":"all","deleted_lines":5,"record_bytes":49152,"support":{"covers":["r1c","r2d","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":4,"owner":3,"path":"python/README.md"},{"bounds":[{"added_lines":280,"boundary":"all","deleted_lines":5,"record_bytes":32768,"support":{"covers":["r1b","r2c","r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":4,"owner":3,"path":"tests/test_agent_boot_report.py"}]}}
```
