# Task 2: Record projection, JSON/strata CLI, and the byte-identity guard

**Files:**
- Modify: `scripts/agent-costs.py`
- Modify: `justfile` (recipe comment only, per D40)
- Create: `tests/fixtures/agent_costs_text_golden.txt` (per D33)
- Test: `tests/test_agent_costs.py`

**Interfaces:**
- Consumes, from Task 1: `scan_codex_file(path) -> dict | None`, whose success dict has the keys
  `session_id`, `rollout_id`, `is_root`, `cwd`, `fresh`, `cache_create`, `cache_read`, `output`,
  `reasoning`, `input_total`, `peak_ctx`, `turns`, `models`, `efforts`.
  From the existing module: `new_group()`, `build_groups`, `group_outcome`, `percentile`,
  `project_name(dir_name, root_cwds)`, `issue_key(dir_name, root_cwds)`, `MULTI_ISSUE`,
  `scan_paths(paths, executor_factory)`, `find_sessions`, `total_tokens`, `human`.
- Produces, for Tasks 3–5: nothing is imported across scripts. This task fixes the *wire shape*
  Task 3's loader parses: a record document with top-level `schema_version`, `kind`,
  `record_id`, `generated_at`, `window`, `strata`, `fleet`, `notes`, where
  `strata.<name>.runs` is a list of run objects each carrying `run_id`, `stratum`, `project`,
  `issue`, `outcome`, `tokens.input_total`, `peak_ctx` and the remaining fields listed below.
- New module surface: `SCHEMA_VERSION = 1`, `RECORD_KIND = "agent-cost-record"`,
  `DISCLAIMER` (str), `canonical_digest(body) -> str`,
  `build_record(groups_by_stratum, window) -> dict`, and `scan_paths(paths, executor_factory,
  scanner=None)` — `None`, **not** `scan_file`: a captured default binds once at `def` time and
  would silently bypass the existing `mock.patch.object(agent_costs, "scan_file", ...)` fallback
  tests (per D41).
- `scan_file` gains one key, `cost_by_family`, and `COUNTER_FIELDS` gains the same name, so the
  per-family cost rides the one existing deduplicated derivation (per D32).

**Invariants:**
- Text mode's stdout bytes are byte-identical to the pre-task bytes for every invocation that
  passes no new flag (D2, D15). The text printer's statements are not edited; the only change on
  the text path is that the footer's literal moves into `DISCLAIMER` and is printed as
  `print(f"\nNOTE: {DISCLAIMER}")` (D18).
- `--strata` with any value other than `claude` in text mode is an argparse usage error, exit 2,
  empty stdout (D15). `--artifacts` combined with `--format json` is likewise exit 2 (D29).
- The Claude transcript root is required, and scanned, only when the `claude` stratum is
  selected; the Codex session root only when `codex` is (D15). A *missing* root directory stays
  fatal in both modes; an *empty* window is fatal only in text mode (D29).
- `build_record` is pure apart from reading the clock for `generated_at`. It performs no I/O,
  reads no `argparse` namespace, and mutates none of the groups it is given.
- The null-vs-zero rule is one rule: a key **absent** from a group projects as JSON `null`; a key
  present projects its value, including a truthful `0` (D6). Codex groups carry only the keys
  Codex measures, which is what makes `outcome`, `cost_usd`, `phase_turns`, `skill_loads` and the
  byte distributions `null` for that stratum without a per-field exception list.
- `strata.<s>.runs` is sorted by `run_id` ascending, and every counter is emitted as a plain
  `dict`, so `record_id` does not depend on filesystem iteration order (D28).
- `record_id` equals `canonical_digest(body)` where `body` is the document minus `record_id` and
  `generated_at`; every other field is inside the digest (D9).
- `fleet` carries `informative: true` and token fields only — no cost of either shape, under any
  `--strata` (D8).
- Every run and stratum total carries `cost_by_family`; for the Claude stratum
  `sum(run["cost_by_family"].values())` equals `run["cost_usd"]` to float rounding, because both
  come from the same accumulator loop. It is `null` for Codex (per D32, D7).
- Byte-identity is asserted against `tests/fixtures/agent_costs_text_golden.txt`, captured from
  the script **as it stands at this task's base commit** — the only oracle that predates the
  change (per D33).

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_costs.py`. It reuses Task 1's `codex_meta` / `codex_usage` /
`codex_turn_context` helpers, the existing `assistant` / `record` helpers, and the existing
`EndToEndTest.DeterministicExecutor` (a serial stand-in for the process pool). Every import it
needs — `contextlib`, `io`, `json`, `tempfile`, `unittest`, `Path` — is already in the header.

```python
def claude_tree(tmp, dir_name="-Users-me-repo-issue-120-x", session="s1"):
    """A one-session Claude fixture: 2 assistant turns, one deduped message id."""
    proj = tmp / dir_name
    proj.mkdir(parents=True)
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 200,
             "cache_read_input_tokens": 3000, "output_tokens": 40}
    (proj / f"{session}.jsonl").write_text(
        assistant("m1", usage, cwd="/Users/me/repo")
        + assistant("m1", usage, cwd="/Users/me/repo")   # duplicate id: deduped
        + assistant("m2", usage, cwd="/Users/me/repo"),
        encoding="utf-8")
    return proj


def codex_tree(tmp, cwd="/Users/me/repo/.claude/worktrees/issue-120-x"):
    day = tmp / "2026" / "08" / "04"
    day.mkdir(parents=True)
    (day / "rollout-root.jsonl").write_text(
        codex_meta("s1", cwd=cwd) + codex_turn_context() + codex_usage(
            1000, cached=600, out=50, reasoning=20),
        encoding="utf-8")
    (day / "rollout-sub.jsonl").write_text(
        codex_meta("s1", rollout_id="r2", thread_source="subagent", cwd=cwd)
        + codex_usage(500, cached=100, out=10, reasoning=5),
        encoding="utf-8")
    return tmp


def run_main(*argv):
    """main() with stdout captured; returns (stdout, SystemExit code or None)."""
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            agent_costs.main(list(argv),
                             executor_factory=EndToEndTest.DeterministicExecutor)
        except SystemExit as exit_error:
            code = exit_error.code
    return buf.getvalue(), code


class BuildRecordTest(unittest.TestCase):
    def strata(self):
        claude = agent_costs.new_group()
        claude.update(fresh=100, cache_create=200, cache_read=3000, output=40,
                      cost=1.5, turns=2, sessions=1, peak_ctx=3300)
        claude["models"].update({"claude-opus-5": 2})
        claude["cost_by_family"].update({"opus": 1.2, "sonnet": 0.3})
        claude["outcomes"].append("completed")
        claude["agent_prompt_bytes"].extend([10, 20, 30])
        codex = {"fresh": 300, "cache_create": 0, "cache_read": 700, "output": 60,
                 "reasoning": 25, "turns": 2, "sessions": 1, "subagents": 1,
                 "peak_ctx": 1000, "models": {"gpt-5.6-sol": 1}, "efforts": {}}
        return {"claude": {"cost_basis": "list-price",
                           "groups": {("repo", "120"): claude}},
                "codex": {"cost_basis": "subscription",
                          "groups": {("repo", "120"): codex}}}

    def window(self):
        return {"days": 7, "cutoff_epoch": 1785852530,
                "strata": ["claude", "codex"],
                "sources": {"claude": "/p", "codex": "/c"}}

    def test_input_total_is_the_sum_of_the_three_input_categories(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["claude"]["runs"][0]
        self.assertEqual(run["tokens"]["input_total"], 3300)
        self.assertEqual(run["tokens"]["fresh"], 100)
        self.assertEqual(run["tokens"]["cache_create"], 200)
        self.assertEqual(run["tokens"]["cache_read"], 3000)
        self.assertEqual(run["run_id"], "claude:repo:120")
        self.assertEqual(run["outcome"], "completed")
        self.assertEqual(run["agent_prompt_bytes"],
                         {"n": 3, "p50": 20, "p90": 30, "max": 30})

    def test_cost_is_carried_per_model_family(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["claude"]["runs"][0]
        self.assertEqual(run["cost_by_family"], {"opus": 1.2, "sonnet": 0.3})
        self.assertAlmostEqual(sum(run["cost_by_family"].values()), run["cost_usd"])
        self.assertEqual(rec["strata"]["claude"]["totals"]["cost_by_family"],
                         {"opus": 1.2, "sonnet": 0.3})
        self.assertIsNone(rec["strata"]["codex"]["runs"][0]["cost_by_family"])
        self.assertIsNone(rec["strata"]["codex"]["totals"]["cost_by_family"])
        self.assertNotIn("cost_by_family", rec["fleet"]["totals"])

    def test_absent_measurements_are_null_not_zero(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["codex"]["runs"][0]
        for field in ("outcome", "cost_usd", "cost_by_family", "phase_turns", "attr_turns",
                      "stop_reasons", "agents_by_type", "agent_statuses",
                      "skill_loads", "repeats", "agents_killed", "interventions",
                      "agent_prompt_bytes", "agent_result_bytes"):
            self.assertIsNone(run[field], field)
        self.assertEqual(run["tokens"]["reasoning"], 25)
        self.assertIsNone(rec["strata"]["claude"]["runs"][0]["tokens"]["reasoning"])
        self.assertEqual(rec["strata"]["codex"]["cost_basis"], "subscription")
        self.assertIsNone(rec["strata"]["codex"]["totals"]["cost_usd"])

    def test_fleet_is_informative_and_carries_no_cost(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        self.assertTrue(rec["fleet"]["informative"])
        self.assertEqual(rec["fleet"]["totals"]["input_total"], 3300 + 1000)
        self.assertNotIn("cost_usd", rec["fleet"]["totals"])
        self.assertNotIn("cost", rec["fleet"]["totals"])
        self.assertIsNone(rec["fleet"]["totals"]["reasoning"])  # claude side is null

    def test_record_id_digests_the_body_and_excludes_generated_at(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        body = {k: v for k, v in rec.items()
                if k not in ("record_id", "generated_at")}
        self.assertEqual(rec["record_id"], agent_costs.canonical_digest(body))
        self.assertTrue(rec["record_id"].startswith("sha256:"))
        self.assertEqual(len(rec["record_id"]), 71)
        again = agent_costs.build_record(self.strata(), self.window())
        self.assertEqual(rec["record_id"], again["record_id"])
        mutated = self.strata()
        mutated["claude"]["groups"][("repo", "120")]["fresh"] = 101
        self.assertNotEqual(
            rec["record_id"],
            agent_costs.build_record(mutated, self.window())["record_id"])

    def test_runs_are_sorted_by_run_id(self):
        strata = self.strata()
        groups = strata["claude"]["groups"]
        for key in (("repo", None), ("repo", agent_costs.MULTI_ISSUE), ("aaa", "9")):
            groups[key] = agent_costs.new_group()
        ids = [r["run_id"] for r in
               agent_costs.build_record(strata, self.window())["strata"]["claude"]["runs"]]
        self.assertEqual(ids, sorted(ids))
        self.assertIn("claude:repo:none", ids)
        self.assertIn("claude:repo:multi", ids)


GOLDEN = Path(__file__).resolve().parent / "fixtures" / "agent_costs_text_golden.txt"


class TextByteIdentityTest(unittest.TestCase):
    def test_default_stdout_is_byte_for_byte_the_pre_change_golden(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        bare, code = run_main("--projects-dir", str(tmp), "--days", "0")
        self.assertIsNone(code)
        self.assertEqual(bare, GOLDEN.read_text(encoding="utf-8"))

    def test_explicit_defaults_reproduce_the_no_flag_bytes(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        bare, code_a = run_main("--projects-dir", str(tmp), "--days", "0")
        explicit, code_b = run_main("--projects-dir", str(tmp), "--days", "0",
                                    "--format", "text", "--strata", "claude")
        self.assertIsNone(code_a)
        self.assertIsNone(code_b)
        self.assertEqual(bare, explicit)
        self.assertIn("NOTE: cache reads measure logical context re-processing", bare)

    def test_json_reports_the_same_numbers_the_table_prints(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        text, _ = run_main("--projects-dir", str(tmp), "--days", "0")
        raw, _ = run_main("--projects-dir", str(tmp), "--days", "0",
                          "--format", "json")
        record = json.loads(raw)
        totals = record["strata"]["claude"]["totals"]
        run = record["strata"]["claude"]["runs"][0]
        printed = agent_costs.human(totals["input_total"] + totals["output"])
        self.assertIn(f"TOTAL  {printed} tokens", text)
        # every shared group/total quantity, not one substring
        self.assertEqual(totals["fresh"], run["tokens"]["fresh"])
        self.assertEqual(totals["cache_create"], run["tokens"]["cache_create"])
        self.assertEqual(totals["cache_read"], run["tokens"]["cache_read"])
        self.assertEqual(totals["output"], run["tokens"]["output"])
        self.assertEqual(totals["input_total"], run["tokens"]["input_total"])
        self.assertEqual(totals["cost_usd"], run["cost_usd"])
        self.assertEqual(totals["cost_by_family"], run["cost_by_family"])
        self.assertAlmostEqual(sum(run["cost_by_family"].values()), run["cost_usd"])
        for value in (agent_costs.human(run["tokens"]["fresh"]),
                      agent_costs.human(run["tokens"]["cache_create"]),
                      agent_costs.human(run["tokens"]["cache_read"]),
                      agent_costs.human(run["tokens"]["output"]),
                      agent_costs.human(run["peak_ctx"]),
                      f"{run['cost_usd']:,.2f}"):
            self.assertIn(value, text)


class StrataCliTest(unittest.TestCase):
    def test_non_claude_strata_in_text_mode_is_a_usage_error(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(tmp), "--strata", "both")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_artifacts_with_json_is_a_usage_error(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(tmp), "--format", "json",
                                 "--artifacts", str(tmp))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_codex_only_run_never_touches_the_claude_root(self):
        tmp = Path(tempfile.mkdtemp())
        codex_tree(tmp)
        raw, code = run_main("--projects-dir", "/nonexistent/claude/root",
                             "--codex-sessions", str(tmp), "--days", "0",
                             "--format", "json", "--strata", "codex")
        self.assertIsNone(code)
        rec = json.loads(raw)
        self.assertEqual(rec["kind"], "agent-cost-record")
        self.assertEqual(rec["schema_version"], 1)
        self.assertEqual(rec["window"]["strata"], ["codex"])
        self.assertNotIn("claude", rec["strata"])
        runs = rec["strata"]["codex"]["runs"]
        self.assertEqual([r["run_id"] for r in runs], ["codex:repo:120"])
        self.assertEqual(runs[0]["tokens"]["input_total"], 1500)
        self.assertEqual(runs[0]["sessions"], 1)
        self.assertEqual(runs[0]["subagents"], 1)
        self.assertEqual(runs[0]["turns"], 2)
        self.assertIsNone(runs[0]["cost_usd"])

    def test_empty_window_in_json_mode_emits_a_record_with_no_runs(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "empty-project").mkdir()
        raw, code = run_main("--projects-dir", str(tmp), "--days", "0",
                             "--format", "json")
        self.assertIsNone(code)
        self.assertEqual(json.loads(raw)["strata"]["claude"]["runs"], [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v tests/test_agent_costs.py -k "BuildRecord or TextByteIdentity or StrataCli" 2>&1 | tail -8`
Expected: FAIL — `AttributeError: module 'agent_costs' has no attribute 'build_record'` and, in
the CLI tests, `SystemExit: 2` from argparse rejecting the unknown `--format` option (code `2`
but non-empty stderr and a failing assertion on the parsed record).

- [ ] **Step 3: Write the minimal implementation**

**3a. Module constants.** Add `import hashlib` to the header. Below `PRICING` add:

```python
SCHEMA_VERSION = 1
RECORD_KIND = "agent-cost-record"
# The one authoritative home for the comparative-telemetry caveat (D18): the
# text footer prints it behind "NOTE: " and the record carries it as `notes`.
DISCLAIMER = (
    "cache reads measure logical context re-processing (tokens the model"
    "\nattended to via prompt cache), and est $ applies public list prices — this is"
    "\ncomparative telemetry for run-over-run analysis, NOT billing data."
)
```

Replace the final `print(...)` of `main` with `print(f"\nNOTE: {DISCLAIMER}")`. The resulting
bytes must be identical; `TextByteIdentityTest` and the untouched existing `EndToEndTest` are
what prove it.

**3a-bis. Per-family cost (per D32).** In `scan_file`, initialise
`cost_by_family = Counter()` beside `cost` and, in the same pricing block that already computes a
message's cost, add that cost to `cost_by_family[model_family(model)]`. Return it as
`"cost_by_family": dict(cost_by_family)`. Add `"cost_by_family"` to `COUNTER_FIELDS`, so
`new_group` seeds it and `build_groups` merges it beside the other counters — no new loop and no
second derivation (D2). `SUM_FIELDS` is untouched, so `fold_scan_totals` and every text-path
statement are unchanged.

**3b. `canonical_digest`.**

```python
def canonical_digest(body):
    """Contract: 'sha256:' + sha256 over canonical JSON of `body` (D9)."""
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

**3c. `build_record(groups_by_stratum, window)`.** `groups_by_stratum` maps a stratum name to
`{"cost_basis": str, "groups": {(project, issue): group_dict}}`. Steps, in order:

1. For each stratum name in `sorted(groups_by_stratum)`, project every group into a run dict:
   - `run_id = f"{name}:{project}:{segment}"` where `segment` is `"none"` for `issue is None`,
     `"multi"` for `MULTI_ISSUE`, else the issue string. `issue` in the run keeps the raw value
     (`None`, `"*"`, or the number).
   - `outcome = group_outcome(g) if "outcomes" in g else None`.
   - `tokens = {"input_total": fresh + cache_create + cache_read, "fresh": …,
     "cache_create": …, "cache_read": …, "output": …, "reasoning": g.get("reasoning")}`,
     each of the four categories read with `g.get(field)`.
   - `cost_usd = g.get("cost")`; `cost_by_family = dict(g["cost_by_family"])` when the key is
     present, else `None` (D6, D32); `peak_ctx`, `turns`, `sessions`, `subagents`, `skill_loads`,
     `repeats`, `agents_killed`, `interventions` each `g.get(field)`.
   - each of `models`, `efforts`, `stop_reasons`, `phase_turns`, `attr_turns`,
     `agents_by_type`, `agent_statuses`: `dict(g[field])` when the key is present, else `None`.
   - each of `agent_prompt_bytes`, `agent_result_bytes`: `None` when the key is absent, else
     `{"n": len(v), "p50": percentile(v, 50), "p90": percentile(v, 90),
     "max": max(v, default=0)}` (D2 — the same percentiles the table prints).
2. `runs = sorted(projected, key=lambda run: run["run_id"])` (D28).
3. `totals` for the stratum: `{"runs": len(runs)}` plus, for each of `input_total`, `fresh`,
   `cache_create`, `cache_read`, `output`, `reasoning`, `cost_usd`, the sum of that field over
   the runs — or `None` when **any** run's value is `None` (D6). Token fields come from
   `run["tokens"]`, `cost_usd` from the run's top level. `cost_by_family` totals as a
   family-keyed sum across the runs, `None` when any run's is `None`.
4. `strata[name] = {"cost_basis": …, "totals": totals, "runs": runs}`.
5. `fleet = {"informative": True, "totals": {field: sum over strata totals, or None when any
   stratum's is None}}` for the six token fields only — no `cost_usd` key at all (D8).
6. `body = {"schema_version": SCHEMA_VERSION, "kind": RECORD_KIND, "window": window,
   "strata": strata, "fleet": fleet, "notes": DISCLAIMER}`; return
   `dict(body, record_id=canonical_digest(body), generated_at=<RFC3339 UTC now>)`, the timestamp
   built as `datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")`
   (`from datetime import datetime, timezone` in the header).

**3d. `scan_paths` gains a scanner.** Change the signature to
`scan_paths(paths, executor_factory=ProcessPoolExecutor, scanner=None)` and, as the **first**
statement of the body, `if scanner is None: scanner = scan_file`. Then use `scanner` in both the
`pool.map` call and the sequential fallback. Writing `scanner=scan_file` in the signature would
capture the function object at `def` time and bypass
`mock.patch.object(agent_costs, "scan_file", ...)`, silently breaking the two existing fallback
tests in `ScanPathsTest` — which stay as the regression gate for this (per D41).

**3e. Codex collection.** Add, next to `scan_codex_file`:

`collect_codex_groups(root, cutoff, project_filter, executor_factory)` →
`{(project, issue): group}` where a group holds **only** the measured keys
`fresh`, `cache_create`, `cache_read`, `output`, `reasoning`, `turns`, `sessions`,
`subagents`, `peak_ctx`, `models`, `efforts`. Algorithm:

1. `sys.exit(f"no Codex session root at {root}")` when `root` is not a directory.
2. `paths = sorted(p for p in root.rglob("*.jsonl")
   if cutoff is None or p.stat().st_mtime >= cutoff)` (D26).
3. `results = [r for r in scan_paths(paths, executor_factory, scanner=scan_codex_file) if r]`.
4. Bucket by `r["session_id"]` — every subagent rollout joins its root thread's bucket
   unconditionally (D5).
5. Per bucket, in sorted session-id order: `root_cwds = Counter(r["cwd"] for r in bucket
   if r["is_root"] and r["cwd"])`, falling back to every non-empty `cwd` in the bucket when that
   is empty. `project = project_name("codex", root_cwds)` and
   `issue = issue_key("codex", root_cwds)` — the literal `"codex"` stands in for Claude's
   encoded project-dir name, which Codex has no analogue of, and matches neither `ISSUE_RE`
   nor a real project name, so both helpers fall through to the cwd evidence D4 names.
6. Skip the bucket when `project_filter` is set and is not a case-insensitive substring of
   `project`.
7. Accumulate into the group: sum `fresh`/`cache_create`/`cache_read`/`output`/`reasoning`/
   `turns`; `peak_ctx = max(...)`; `models`/`efforts` merged as `Counter`s and stored as `dict`s;
   `sessions += 1` per root rollout and `subagents += 1` per non-root rollout (D27).

**3e-bis. Operator-facing prose (per D40).** Two descriptions go false the moment this task
lands; both are edited here, and neither touches stdout:

- `scripts/agent-costs.py`'s module docstring — its first line becomes
  `Per-issue agent-cost telemetry for Claude Code and Codex sessions.`, and its body gains one
  sentence naming `~/.codex/sessions` as the Codex source and `--format json` as the
  `agent-cost-record` projection. The disclaimer literal is not duplicated here (D18).
- the `justfile` `agent-costs` recipe comment becomes
  `# Report agent token spend per issue from the local Claude Code and Codex sessions`.

**3f. `main` wiring.** Add three arguments after `--artifacts`:

```python
ap.add_argument("--format", choices=("text", "json"), default="text",
                help="text tables (default) or one agent-cost-record JSON document")
ap.add_argument("--strata", choices=("claude", "codex", "both"), default="claude",
                help="which strata to scan; meaningful only with --format json")
ap.add_argument("--codex-sessions", default=os.path.expanduser("~/.codex/sessions"),
                help="Codex rollout root")
```

Immediately after `parse_args`:

```python
json_mode = args.format == "json"
if not json_mode and args.strata != "claude":
    ap.error("--strata is meaningful only with --format json")
if json_mode and args.artifacts:
    ap.error("--artifacts is not available with --format json")
selected = ("claude", "codex") if args.strata == "both" else (args.strata,)
```

Then, keeping today's statements in today's order on the text path:

- Compute `cutoff` exactly as today.
- The existing block from `root = Path(args.projects_dir)` through `build_groups(...)` runs only
  when `"claude" in selected`. Its `sys.exit(f"no transcript root at {root}")` stays
  unconditional within that block; its `sys.exit("no transcripts in window")` and the later
  `if not groups: sys.exit("no sessions matched the filters")` fire only when `not json_mode`
  (D29). In JSON mode those two cases yield an empty `groups` dict.
- When `"codex" in selected`, call `collect_codex_groups(...)` with
  `Path(os.path.expanduser(args.codex_sessions))`.
- When `json_mode`: build
  `window = {"days": args.days, "cutoff_epoch": int(cutoff) if cutoff else None,
  "strata": sorted(selected), "sources": {…}}` — `sources` holds `"claude": str(projects_root)`
  and/or `"codex": str(codex_root)` for the selected strata only — assemble
  `groups_by_stratum` with `cost_basis` `"list-price"` for Claude and `"subscription"` for
  Codex (D7), then
  `json.dump(build_record(groups_by_stratum, window), sys.stdout, sort_keys=True,
  separators=(",", ":"))`, `print()`, and `return`. Nothing on the text path executes.
- Everything from `ordered = sorted(groups.items(), …)` onward is unchanged and unreachable in
  JSON mode.

- [ ] **Step 4: Verify**

First capture the pre-change oracle, **before** editing `scripts/agent-costs.py` (per D33):

```sh
mkdir -p tests/fixtures
git show HEAD:scripts/agent-costs.py > /tmp/agent-costs-base.py
python3 - <<'PY' > tests/fixtures/agent_costs_text_golden.txt
import importlib.util, sys
spec = importlib.util.spec_from_file_location("base", "/tmp/agent-costs-base.py")
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
# build the same claude_tree() fixture the test builds, then call
#   base.main(["--projects-dir", str(tmp), "--days", "0"],
#             executor_factory=DeterministicExecutor)
PY
```

The fixture passes no `--artifacts`, and that is the only path on which the tool prints an
absolute path, so the captured bytes are location-independent and commit cleanly. Then:

```sh
python3 -m unittest -v tests/test_agent_costs.py
just agent-costs --days 1 --format json --strata claude | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["kind"], d["record_id"][:14], len(d["strata"]["claude"]["runs"]))'
test "$(grep -c 'comparative telemetry for run-over-run analysis' scripts/agent-costs.py)" -eq 1
```
Expected: the suite prints `OK` with every pre-existing test still passing; the live JSON run
prints `agent-cost-record sha256:…` and a run count; the last line exits 0, proving the
disclaimer literal exists exactly once in the file (D18) — it fails with exit 1 if a second copy
was left in the footer.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py \
        tests/fixtures/agent_costs_text_golden.txt justfile
git commit -m "feat(agent-costs): emit an agent-cost-record with a Codex stratum

--format json projects the same groups the tables print (D2); --strata
opts the Codex scan in and is a usage error in text mode (D15).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
