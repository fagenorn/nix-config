# Owner report: fair before/after comparison of owner dollars per lineage — issue 503

Design for https://github.com/fagenorn/nix-config/issues/503 (parent
https://github.com/fagenorn/nix-config/issues/432). Base: `4e944cb4`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#432 Dn" cites
`2026-10-25-issue-432-owner-handoff-economics-design.md`.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "adds CLI flags (start-range windows, settle days, proxy log) and new fields/tables to the agent-owner-report JSON document whose contract lives in python/README.md"}, "concurrency_or_persistence": {"value": "no", "evidence": "read-only report over transcripts and proxy log lines; no locking or persisted state"}, "open_design_questions": {"value": "hit", "evidence": "project identity of a lineage, flag shapes for the two windows and settle period, and the ping-log source on Linux (journal) are open"}, "criteria_shape": {"value": "no", "evidence": "two acceptance criteria, both verified by unit tests in tests/test_agent_owner_report.py"}}, "paths": ["python/agent_tools/agent_owner_report.py", "python/agent_tools/agent_costs.py", "tests/test_agent_owner_report.py", "tests/owner_transcripts.py", "python/README.md"]}`
Verdict: `{"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

#432's restated AC6 asks one question: did owner dollars per lineage fall to
0.9× or less, comparing lineages started 2026-11-03..2026-11-17 (settled at
least 4 days) against the pooled baseline of lineages started
2026-10-12..2026-10-26, with no project's delivery rate falling by more than
10 points? `just agent-costs --report owners` cannot answer that fairly
today. Its 2026-11-01 reading on mbp ($61.42 → $70.19 per delivered issue)
went wrong in five ways:

- **It selects spend, not lineages.** `--events-since/--events-before` keeps
  the calls that start inside the window. A lineage that started before the
  window adds its tail, and one that started inside adds only its head.
- **Deliveries come from a different set.** `delivered` reads the finish
  replies of every call, clipped or not, so numerator and denominator
  disagree.
- **Young lineages count.** 17 unfinished lineages ($571) active in the last
  36 hours went into the numerator.
- **One pooled number hides the project mix.** nodocom fell from 52 lineages
  to 16 and jarbird rose from 20 to 38. Reweighting flips the sign.
- **Ping spend is invisible.** Keepalive pings (about $260 in the window)
  appear in no transcript, only in the cache proxy's log.

Owner $ per lineage exists only on lineage rows, so the like-for-like figure
($14.13 → $11.35) was computed by hand. The user wants a single command: give
it a baseline start range and a candidate start range, and it prints
per-project rows, ping spend and the owner $ per lineage ratio.

## Solution

`--report owners` gains a **start mode**. `--started SINCE..BEFORE` selects
lineages by when they started and counts each one's whole spend. Adding
`--baseline SINCE..BEFORE` makes it a two-window comparison (D1). A lineage
counts only once it has settled: it must have started at least
`--settle-days` (default 4) before the report's end (D2). Spend and
deliveries come from the same calls in every mode (D3). Each lineage gets a
project (D4). Keepalive pings come from one or more `--proxy-log` files: each
is matched to its conversation's transcript, priced, and added to its
lineage, or reported as unattributed (D5, D6). One aggregate builds the arm
rows, the new per-project rows and the comparison (D7). The JSON document
moves to schema version 2 (D8), and the text output gains a Projects table, a
Comparison table and a Pings line.

## Decisions

### Modes and windows

The owner report keeps its three existing modes: the mtime cutoff
(`--days`), the event window (`--events-since/--events-before`) and eval
grouping (`--eval-results/--eval`). It adds start mode, which `--started`
selects (D1).

- **Range grammar.** `SINCE..BEFORE` is a half-open interval
  `[SINCE, BEFORE)`. Each bound is either a `YYYY-MM-DD` date, meaning
  00:00:00Z of that UTC day, or an RFC3339 instant with an offset (the
  `--events-*` grammar). `SINCE` must be earlier than `BEFORE`. So
  `--started 2026-11-03..2026-11-17` covers exactly two weeks, and #432's
  windows can be pasted in as written.
- **Arms.** With `--started` alone, every lineage is in the arm `live`, as
  today. With `--baseline`, a lineage is in the arm `baseline` or
  `candidate` by the window its start falls in. The two windows must not
  overlap, so no lineage is in both.
- **Transcripts read.** Start mode reads every transcript under the root. The
  mtime cutoff does not apply, as in eval mode, because an earlier launch of a
  lineage can be older than the window (D1).
- **Replay.** `--policy` and `--sweep` work with `--started` alone. They are
  refused with `--baseline` (D7).

### Lineage start, settle and report end

- **Start.** A lineage's start is the earliest call start among its owner
  transcripts, over all of their calls, whatever the mode (D2). The lineage
  row carries it as `started`, an RFC3339 UTC instant. A lineage whose owner
  calls carry no timestamp is in no start window.
- **Report end.** The report end is the latest call end among the
  transcripts read.
- **Settled.** A lineage counts in a window when its start lies in the
  window and is at most `report_end − settle_days × 86,400 s`.
  `--settle-days` takes a non-negative integer, defaults to 4 and exists
  only in start mode. 0 turns the settle period off.
- **Unsettled.** A lineage that started inside a window but too late to be
  settled is left out of that window. The window reports how many there
  were and their spend.
- **Out-of-window lineages.** A lineage that started outside every window is
  left out completely, with its calls and its pings. It is never counted as
  unattributed spend.

### Spend and deliveries (D3)

- **Full spend.** In start mode a counted lineage counts every call of its
  member transcripts, including calls after the window ends.
- **Deliveries.** In every mode a lineage is delivered only when one of its
  *counted* calls got a `workflow-state finish` reply of kind
  `delivery_complete` for its run and issue (#432 D4's rule, now clipped).
  An event window therefore clips deliveries as well as spend. In start
  mode and the mtime mode every call is counted. Eval grouping still reads
  the `verdict`.
- **Unattributed spend in start mode.** A transcript that belongs to no
  lineage has no start time. Its calls count as unattributed spend when
  they start inside a start window. An unresolved owner counts when it has
  such a call.

### Project (D4)

A lineage's `project` is `agent_costs.project_name`, applied to the record
`cwd`s of its owner transcripts: the basename of the busiest repo
root, where `repo_root` trims a path at its first dot directory, so
`.worktrees/…` and `.claude/worktrees/…` fold into their repository. When no
cwd qualifies, it falls back to `project_name`'s directory-name rule, using
the first launch's session project directory. To supply the cwds,
`transcript_calls.Transcript` gains each record's `cwd` count. The project
name is the same one the per-issue report already uses, and the same
repository gets the same name on both hosts.

### Keepalive pings (D5, D6)

- **Input.** `--proxy-log PATH` is repeatable and has no default. It reads
  one cache-proxy log per value. On darwin that is
  `~/Library/Logs/claude-cache-proxy.log`. On anis-desktop it is a file
  exported with `journalctl --user -u claude-cache-proxy -o cat`. An
  unreadable path exits 1 with `cannot read proxy log: <error>`.
- **Lines read.** A ping line is a JSON object whose `event` is `ping`
  (the `cache-proxy` contract holds its fields). A line that is not a
  JSON object, or a ping line without an RFC3339 `ts` and a string
  `conversation`, is skipped and counted. Every other event is ignored.
- **Pricing.** A ping is priced by `model_pricing.usage_cost(model, usage)`.
  A ping without a `usage` object costs $0 and is counted as `unpriced`. An
  approximate price counts in `pricing.approximate_calls`.
- **Matching.** A ping belongs to the read transcript whose
  `cache_keepalive.conversation_handle(session, agent id)` equals its
  `conversation`, with the session and agent id the scan already reads (a
  root transcript has no agent id).
- **Attributed pings.** A ping whose transcript is a member of a counted
  lineage is attributed to that lineage. It counts wherever the lineage's
  calls count: always, except in an event window, where its `ts` must lie
  inside the window. An owner transcript's pings add to the lineage's
  `owner_ping_dollars` and `ping_dollars`; a descendant's pings add to
  `ping_dollars` only.
- **Unattributed pings.** A ping whose transcript belongs to no lineage, or
  which matches no transcript, is unattributed. It counts when its `ts`
  lies in the report's time scope: the event window, a start window, or
  after the mtime cutoff (all time for `--days 0`). Pings of a lineage that
  the report leaves out (out of window or unsettled) are neither attributed
  nor unattributed.
- **Eval mode.** `--proxy-log` is refused with `--eval-results`.

### Aggregates (D6, D7)

- **Lineage values.** The lineage row's `owner_dollars` and `total_dollars`
  stay calls-only. A lineage's *owner spend* is
  `owner_dollars + owner_ping_dollars`, and its *spend* is
  `total_dollars + ping_dollars`.
- **One aggregate.** A single aggregate over a set of lineage rows gives:
  - `n`
  - `delivered`
  - `delivery_rate` (delivered ÷ n)
  - `dollars_per_delivered` (Σ spend ÷ delivered)
  - `owner_dollars_per_lineage` (Σ owner spend ÷ n)
  - the sums `owner_dollars`, `owner_ping_dollars`, `total_dollars` and
    `ping_dollars`

  A quotient with a zero denominator is `null`.
- **Arm and project rows.** An arm row is the aggregate over one arm, of
  whose sums it keeps only `ping_dollars`. It also keeps `sd` (sample
  standard deviation of spend over delivered rows), `undelivered_dollars`
  (Σ spend of undelivered rows), `peak_p50` and `peak_p90`. A project row
  is the aggregate over one arm and one project. In comparison mode both
  arms always have a row, with `n` 0 when a window holds no lineage. With
  no ping log, `dollars_per_delivered`, `sd` and `undelivered_dollars`
  reduce to their v1 formulas.
- **Comparison.** `comparison` holds:
  - `owner_dollars_per_lineage_ratio` and `dollars_per_delivered_ratio`,
    each candidate ÷ baseline over the arm rows (the pooled baseline). Each
    is `null` when either side is `null` or the baseline is 0.
  - one `projects` entry per project that appears in either arm, sorted by
    name: `project`, `owner_dollars_per_lineage_ratio` and
    `delivery_rate_change`. The change is the candidate rate minus the
    baseline rate as a fraction, and is `null` unless both arms have the
    project.

  The report computes no verdict against #432's thresholds.
- **Pooling hosts.** The project rows' counts and sums are additive. Two
  hosts' documents pool by adding them and recomputing the quotients
  (D10).

### Document: `agent-owner-report`, `schema_version` 2 (D8)

- **Top-level keys.** Exactly `kind, schema_version, window, start_grouping,
  pricing, lineages, arms, projects, boots, simulated, calibration, pings,
  comparison, unattributed, interrupted, unmatched`.
- **`start_grouping`.** `null` outside start mode. In start mode it is
  `{settle_days, report_end, windows}`, and `windows` lists
  `{arm, since, before, unsettled: {lineages, dollars}}` with the baseline
  first.
- **Lineage rows.** The v1 keys plus `project, started, owner_ping_dollars,
  ping_dollars`.
- **Arm rows.** Exactly `arm, n, delivered, delivery_rate,
  dollars_per_delivered, owner_dollars_per_lineage, sd, undelivered_dollars,
  ping_dollars, peak_p50, peak_p90`.
- **Project rows.** Exactly `arm, project, n, delivered, delivery_rate,
  dollars_per_delivered, owner_dollars_per_lineage, owner_dollars,
  owner_ping_dollars, total_dollars, ping_dollars`, ordered by arm as in
  `arms`, then by project.
- **`pings`.** `null` without `--proxy-log`. Otherwise it is
  `{logs, lines, skipped_lines, unpriced, attributed: {pings, dollars,
  owner_dollars}, unattributed: {pings, dollars}}`:
  - `logs`: the paths as given
  - `lines`: the ping lines read
  - `unpriced`: counted pings without usage
- **`comparison`.** `null` unless `--baseline` is given.
- **Unchanged.** `boots` covers every lineage in the report. `unattributed`
  keeps its shape.

### Text output

- **Title.** It names the start windows, the settle days and the report
  end.
- **Lineages table.** Gains `project`, `started` and `ping $` columns.
- **Arms table.** Gains `rate`, `owner $ / lineage` and `ping $` columns.
- **Projects table.** New, after Arms: one row per arm and project.
- **Comparison table.** With `--baseline` only. An `all` row from the arm
  rows, then one row per project. Columns: both `n`s, both rates, the rate
  change in percentage points, both owner $ per lineage values and their
  ratio. A `$ / delivered` line with both values and the ratio follows.
- **Footer.**
  - It always adds a `Pings:` line: the ping lines read and the logs; the
    attributed dollars (owner share included); the unattributed pings and
    dollars; and the unpriced and skipped counts. Without a log it reads
    `Pings: not read (pass --proxy-log PATH)`, so ping spend is never
    silently missing.
  - Start mode adds an `Unsettled:` line per window.

### CLI rules

Each of these is a usage error (exit 2, nothing on stdout):

- `--started`, `--baseline`, `--settle-days` or `--proxy-log` without
  `--report owners`
- `--baseline` or `--settle-days` without `--started`
- `--started` with `--events-since/--events-before` or with
  `--eval-results/--eval`
- a range that does not parse, or whose `SINCE` is not before its `BEFORE`
- overlapping windows
- a negative `--settle-days`
- `--baseline` with `--policy` or `--sweep`
- `--proxy-log` with `--eval-results`

### Modules (D9)

- **`agent_tools.keepalive_pings` (new).** Reads ping lines from log files
  and prices them. It returns the pings (`ts`, `conversation`, dollars,
  priced, approximate) and the skipped-line count.
- **`agent_tools.agent_owner_rollup` (new).** Holds the one aggregate and
  builds the arm, project and comparison rows from lineage rows. The owner
  report's arm aggregation moves here.
- **`agent_tools.agent_owner_report`.** Keeps lineage assembly. It adds
  lineage start, project and ping attribution, start selection with
  settling, the range grammar, the v2 document and the tables. It takes
  `conversation_handle` from `cache_keepalive`, its single home.
- **`agent_tools.agent_costs`.** Adds the flags and their checks, and
  updates its docstring.
- **Unchanged callers.** `collect`'s existing callers, the boot report
  included, keep their behaviour.
- **Contract.** The package README's agent-costs "Owner report" section
  carries the new contract.

## Test seams

All new tests are in `tests/test_agent_owner_report.py` and use the
existing seam: `report(root, *extra)` runs `python -m agent_tools.agent_costs
--report owners --format json` as a subprocess (#432 D17, agent-helpers rule
5). Values are hand-computed with `owner_transcripts.cost` (D11).

- **Fixture.** `owner_transcripts.Session` writes a `cwd` on every record
  (default `/Users/me/repo`, overridable per session). A ping-log fixture
  holds:
  - `ping` lines in the real line's shape, with handles from
    `conversation_handle`
  - a `request` line
  - a non-JSON stderr line
  - a failed ping without `usage`
- **AC (a), start grouping.**
  - A lineage that started inside the window and spent after it counts all
    its calls.
  - A lineage that started an hour before the window and delivered inside
    it is in no arm and adds no delivery.
  - A lineage younger than the settle period is left out and appears in
    `unsettled`.
  - `report_end` is the fixture's latest call end.
- **AC (a), matched deliveries.** With an event window, a finish reply
  outside the window leaves the lineage undelivered.
- **AC (b), pings.**
  - An owner ping and a descendant ping are priced and attributed (owner
    share only on the owner's).
  - An unknown conversation inside the scope is unattributed.
  - One outside the scope is not counted.
  - The skipped and unpriced counts match.
- **AC (b), per-project and two-window comparison.**
  - Two projects, one of them through a `.worktrees/…` cwd that folds into
    its repo, across a baseline and a candidate window.
  - The project rows, the arm rows, both ratios and `delivery_rate_change`
    equal the hand-computed values.
  - A window with no lineage still has an arm row with `n` 0.
- **Usage errors.** Each rule in *CLI rules* returns exit 2, in the pattern
  of `test_owners_report_refuses_foreign_flags`.
- **Text.** The `Projects` and `Comparison` headings and the `Pings:` and
  `Unsettled:` lines print, in the pattern of
  `test_text_output_prints_the_six_tables`.

## Out of scope

- **Pooling two hosts in one run** (D10). Repeatable `--projects-dir` for
  the owner report is not added, and anis-desktop transcripts are not
  collected.
- **Changing the cache proxy's log format.** The Linux journal export is a
  documented command, not code.
- **Replay semantics.** `agent_owner_replay` is unchanged, and the replay is
  refused in comparison mode.
- **Running the #432 measurement** and judging its thresholds.
- **Transcript retention (risk for #432; the caller must route it).** Claude
  Code deletes transcripts older than 30 days by default. The oldest on mbp
  today is from 2026-10-02, and the generated settings set no
  `cleanupPeriodDays`. So the 2026-10-12..26 baseline starts disappearing
  around 2026-11-11, well before the 2026-11-21 measurement. This report
  cannot recover deleted transcripts. Raising `cleanupPeriodDays` in
  `home/common/claude-code/default.nix`, or keeping a synced copy of the
  transcript root, is a separate change that must land before then.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Start mode: `--started SINCE..BEFORE` selects lineages by start; `--baseline SINCE..BEFORE` adds a non-overlapping second window and turns on the comparison; bounds are `YYYY-MM-DD` (00:00Z) or RFC3339 instants, half-open; start mode refuses the event window and eval grouping and reads every transcript (no mtime cutoff) | issue bullets 1 and 7; #432 AC6 writes its windows as `2026-10-12..2026-10-26`, and only a half-open end keeps that baseline before the 2026-10-26T08:39Z switch; the-bar token economy; eval mode's precedent of dropping the mtime cutoff | four paired flags in the `--events-*` style (double the surface; half a window is expressible); an mtime cutoff at the earliest window start (drops an earlier launch, so a lineage that started before the window would look started inside it) |
| D2 | A lineage starts at the earliest call of its owner transcripts; it counts when that start is in the window and at least `--settle-days` (default 4; 0 disables; start mode only) before the report end, the latest call end among the transcripts read; unsettled lineages are reported per window with their spend | issue bullet 3; #432 AC6 "settled at least 4 days"; a descendant never starts before its owner; the-bar truthful terminal states | wall-clock now as the report end (a copied host root would count as settled lineages its data never saw finish, and the subprocess seam has no clock); an `--as-of` flag (a fourth flag for a value the data gives); the first counted call as the start (moves with the window) |
| D3 | Spend and deliveries share one call set: a lineage counted in a start window counts every call of its transcripts, and in every mode `delivered` reads only counted calls' finish replies, so an event window now clips deliveries too | issue bullets 1 and 2; #432 D4's finish-reply rule | clipping start-mode spend at the window end (the bias the issue removes); unclipped event-window deliveries (the mismatch the issue names) |
| D4 | A lineage's project is `agent_costs.project_name` over its owner transcripts' record `cwd`s, so dot-directory worktrees fold into their repo, falling back to the session's project directory; `transcript_calls` gains the cwd count | the per-issue report's naming (one home); #432's reading names projects by basename; a basename matches across hosts | the mangled project directory (worktree dirs differ, and the fallback turns `nix-config` into `config`); the full repo path (does not fold hosts) |
| D5 | Ping input is `--proxy-log PATH`, repeatable, with no default; a ping belongs to the transcript whose `conversation_handle(session, agent id)` equals its `conversation`; non-JSON and malformed ping lines are skipped and counted; a ping without usage is $0 and `unpriced`; refused with eval grouping | mbp check 2026-11-02: all 1,757 ping handles (17,048 pings) match a subagent transcript this way; the log path's home is the nix module and anis-desktop logs to the journal; launchd appends stderr to the same file | a built-in default path (a second home for it, and wrong on Linux); matching by time and model (ambiguous across concurrent subagents) |
| D6 | Owner-conversation pings add to `owner_ping_dollars` and `ping_dollars`, descendants' to `ping_dollars`; `owner_dollars`/`total_dollars` stay calls-only and the aggregates add the pings; a lineage's pings count where its calls count, and a ping of no lineage counts as unattributed when its `ts` is in the report's time scope | issue: "owner transcripts only, including attributed pings"; the replay calibration compares the identity replay with calls-only `total_dollars` (#432 D5) | folding pings into `owner_dollars`/`total_dollars` (breaks the identity check); counting descendants' pings as owner spend (contradicts "owner transcripts only") |
| D7 | The windows are the arms `baseline` and `candidate` (both always present); one aggregate builds arm and per-project rows; `comparison` holds candidate ÷ baseline ratios and each project's delivery-rate change (a fraction; text prints points); no #432 verdict is computed; `--policy`/`--sweep` are refused with `--baseline` | issue bullets 4, 6 and 7; #432 AC6's "pooled baseline" is the baseline arm; arms already group eval rows | a verdict in the report (the thresholds belong to #432's acceptance record); replaying a two-window corpus (its rows would pool before and after) |
| D8 | `agent-owner-report` moves to `schema_version` 2, with `start_grouping`, `projects`, `pings` and `comparison` always present, and new lineage-row and arm-row keys | python/README.md pins exact key sets; the always-present `simulated`/`calibration` precedent | v1 with optional keys (silently breaks the pinned sets); a separate comparison document kind (a second contract for the same rows) |
| D9 | New modules: `keepalive_pings` reads and prices ping lines; `agent_owner_rollup` holds the aggregate (the arm aggregation moves in). The owner report keeps lineage assembly, selection, grammar, document and tables; `agent_costs` only wires flags | the-bar single responsibility (a second input; the aggregate gains two more groupings); agent-helpers rules 1-2; `agent_owner_report` is already 912 lines | everything in `agent_owner_report`; the reader in `cache_keepalive` (the proxy's runtime module would gain pricing) |
| D10 | One transcript root per run: two hosts pool by adding the project rows' counts and sums; repeatable `--projects-dir LABEL=PATH` (the boot report's precedent) waits until the #432 measurement needs it | #503 names no host pooling; #432 AC6 adds anis-desktop only "when its transcripts are available"; the-bar YAGNI | multi-root now (a second contract shape for a run that may never happen) |
| D11 | Tests drive the command through `report(root, *extra)` on production-shaped fixtures: `Session` writes a `cwd` per record, and the ping log mixes real-shaped `ping`, `request` and stderr lines whose handles come from `conversation_handle` | #432 D17's seam; agent-helpers rule 5; the-bar tests that can fail | in-process calls (skip the flag wiring the issue's demo uses); hand-typed handles (the fixture can drift from the product's matching) |
