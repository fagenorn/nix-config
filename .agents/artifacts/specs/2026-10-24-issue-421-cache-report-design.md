# agent-costs: a cache report (deaths, context above a threshold, subagent start-up) and the Opus price fix — issue 421

Design for https://github.com/fagenorn/nix-config/issues/421. "2026-09-02 Dn" cites
`.agents/artifacts/specs/2026-09-02-agent-cost-telemetry-design.md`; a bare "Dn" cites
this spec's ledger. Base: `7601d318` (origin/main).

## Triage

Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "agent-costs gains a new report mode/CLI flags and the Opus price row changes the est $ figures every existing agent-cost-record carries"}, "concurrency_or_persistence": {"value": "no", "evidence": "read-only transcript scan; no locking or persisted state"}, "open_design_questions": {"value": "hit", "evidence": "module placement (agent_costs.py is ~2000 lines), gap-cause classification and attachment detection from transcripts are open"}, "criteria_shape": {"value": "hit", "evidence": "the fourth criterion is real-transcript evidence within +-15%, not a deterministic code check"}}, "paths": ["python/agent_tools/agent_costs.py", "python/agent_tools/agent_cache_report.py", "tests/test_agent_costs.py", "justfile"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every token-optimization slice needs to prove its effect with before/after numbers,
and `agent-costs` cannot show where cache spend is lost. Its tables total tokens and
list-price dollars per issue, but they do not say:

- how often an agent sat idle past the prompt-cache TTL and then paid to rewrite its
  whole context, what it was waiting for at the time, and what that cost;
- how much is spent rereading context beyond a size worth trimming, per agent type;
- what each subagent pays before doing any work: its first request's cache write and
  read, and the size of each attachment the harness injects at start-up.

There is also no way to cut the same report at two instants for a before/after
comparison. And the Opus-class price row is stale ($15/$75 against today's $5/$25), so
every dollar figure overstates Opus spend threefold.

## Solution

`agent-costs` gains a second report, selected with `--report cache` (the per-issue
report stays the default and its output is byte-for-byte unchanged). Over the same
`~/.claude/projects` transcripts it prints three tables — cache deaths by agent type
and cause, reread cost above a context threshold with peak-context percentiles, and
subagent start-up overhead — between a header naming the window and the existing
comparative-telemetry footer. The existing `--events-since/--events-before` bounds
select the calls a run counts, so a before run and an after run are two invocations
with adjacent windows. The Opus-class row becomes $5 input / $25 output per Mtok with
the standard cache multipliers.

Demo: `just agent-costs --report cache --days 14`.

## Decisions

### Command surface

Per D1:

- `--report {issues,cache}`, default `issues`. `issues` is today's behaviour, unchanged.
- `--context-threshold TOKENS` (positive integer) sets the reread threshold; it is
  valid only with `--report cache`, where it defaults to 120,000.
- `--report cache` is text only. It is a usage error (exit 2, nothing on stdout) with
  `--format json`, `--project`, `--artifacts`, `--strata` other than `claude`, or with
  only one event bound or an inverted range; `--context-threshold` with the issues
  report is a usage error too. `--top` caps the rows of each cache table, and a table
  that drops rows says how many, as the issue table does.
- `--events-since/--events-before` become available with `--report cache` as well as
  with `--format json`; their existing rules hold (given together, RFC3339 with an
  offset, since before before).

The justfile recipe is unchanged.

### Module boundary

Per D2, a new module `agent_tools.agent_cache_report` owns the report: the
per-transcript scanner, the aggregation into the three tables and their rendering. It
reuses, by import, what `agent_costs` already owns — `PRICING` and `model_family`,
`find_sessions`, `scan_paths` (with the new scanner as its `scanner` argument),
`event_in_window`/`parse_rfc3339_utc`, `percentile`, `human`, `print_table` and
`DISCLAIMER` — and adds no copy of any of them. The write-split rule ("no TTL
breakdown recorded means 5-minute writes") moves from inline code in `scan_file` into
one `agent_costs` function that both scanners call. `agent_costs.main` parses argv,
validates the combinations above, and for `--report cache` imports
`agent_cache_report` inside that branch and hands it the parsed window, threshold,
row cap, transcript root and executor factory. The scanner takes one job,
`(path, is_root)`, plus the window and threshold bound with `functools.partial` so the
process pool can pickle it; an unreadable transcript yields `None` and is skipped, as
`scan_file` does.

### Transcript model

Per D3 (the window) and D4 (the rest):

- **Transcripts.** `find_sessions` supplies root transcripts (main sessions) and
  subagent transcripts. A transcript's agent type is `main` for a root transcript, the
  `agentType` of the sibling `agent-<id>.meta.json` for a subagent, and `unknown` when
  that file is missing or unreadable.
- **TTL.** By location, as the issue decides: 3,600 s for a root transcript, 300 s for
  a subagent transcript. The recorded write splits agree (main sessions write 1-hour
  cache, subagents 5-minute).
- **Calls.** Assistant records are grouped by `message.id` (falling back to
  `requestId`, then `uuid`, as `scan_file` does). A call's usage is the per-field
  maximum over its records; its start and end are its earliest and latest record
  timestamps. A group whose input-side usage (`input_tokens + cache_read_input_tokens +
  cache_creation_input_tokens`) is zero is not a call: synthetic error messages carry
  zero usage and would otherwise break the pairing of real calls. A call's
  **context** is that input-side sum, the quantity the existing report's `peak_ctx`
  already uses.
- **Window.** With event bounds, a call counts when its start lies in
  `[since, before)` (`event_in_window`; a call without a parsable timestamp is outside),
  and files are prefiltered by mtime ≥ since (`find_sessions(root, since)`). `--days`
  is not consulted then: a file last written before `since` holds no counting call,
  and any narrower mtime cut could only drop files that do. Without bounds, `--days`
  selects files by mtime and every call in a selected file counts, the issue report's
  rule.

### Cache deaths

Per the issue's rule: a call is a **death** when it counts (window above), its
predecessor in the same transcript has context > 5,000, the idle gap
`start(call) − end(predecessor)` exceeds TTL − 10 s, and the call's
`cache_creation_input_tokens` exceed half the predecessor's context. A call without
timestamps on either side of the gap is never a death. The gap runs from record to
record, so it includes the dying call's time to its first record; the prototype
counted identical deaths with 0 s and 10 s of slack, so that borderline does not move
the counts.

**Cause.** Per D5, a death is classified from the `user` records between the two
calls, in two steps. A **tool wait** comes first: when a result of one of the
predecessor's own tool uses lies between the calls — a result whose record carries
`toolEndsTurn: true` (the subagent's own `SubagentHandback`) does not count — the
death is classified by the tool of the last such result. Otherwise the turn ended,
and the death is classified by the first `user` record after the predecessor that is
not a tool result (the one that woke the agent). The kinds form a closed set and
print verbatim:

| Kind | Deciding record |
|---|---|
| `child dispatch` | tool wait; the tool is `Agent` or `Task` |
| `long foreground command` | tool wait; the tool is `Bash` |
| `other tool` | tool wait; any other tool |
| `hand-back after end of turn` | waker whose `origin.kind` is `peer` and `origin.handback` is `true` |
| `task notification after end of turn` | waker whose `origin.kind` is `task-notification` |
| `message after end of turn` | waker with any other origin (human prompt, parent message, coordinator, none) |
| `unclassified` | no tool wait and no waker |

A background tool returns its result at once, so a long gap closed by a tool result
is time spent in the foreground. The tool wait wins over a waker because a message
that arrives during a foreground tool is delivered after its result, and the gap
belongs to the tool.

**Premium.** Per D6, a death's rewrite premium is what the rewrite cost beyond a
warm-cache read of the same prefix: `r × (w − p_read)`, where
`r = min(cache_creation, predecessor context)`, `p_read` is the call's family read
price and `w` is its write price weighted by the call's own TTL split
(`(cw_1h × p_1h + cw_5m × p_5m) / (cw_1h + cw_5m)`, the shared write-split rule
applied). Dollars are list price per `PRICING`.

**Table.** One row per (agent type, kind) with deaths, median gap (minutes, one
decimal) and premium (whole dollars), ordered by premium then deaths, descending;
then one totals line, `Subagent deaths <n> ($<premium> premium); main-session deaths
<n> ($<premium>)`, which counts every row, shown or not.

### Context above the threshold

Per D7, for each counting call the reread above the threshold `T` is
`max(0, cache_read_input_tokens − T) × p_read`: the cached prefix comes first in the
request, so read tokens beyond position `T` are exactly the reads past the threshold.
Per agent type the table shows transcripts with a counting call, the summed reread
above `T` in dollars, and the median, p90 and maximum of each transcript's peak
context over its counting calls. Every median and p90 in the report is `percentile`
(nearest rank), as the existing report's distributions are. Rows are ordered by the
dollar column, descending.

### Subagent start-up overhead

Per D8, for each subagent transcript whose first call counts:

- the first call's `cache_creation_input_tokens` and `cache_read_input_tokens`;
- the size of each start-up attachment: the first `type: "attachment"` record of each
  of six types recorded before the transcript's second call — `skill_listing` (skill
  listing), `instructions`, `mcp_instructions_delta` (MCP instructions),
  `deferred_tools_delta` (deferred tools), `agent_listing_delta` (agent listing) and
  `environment`. Its size is the character count of its `rendered` content (the sum of
  `len(content)` over the `rendered` list), what the model is sent. The MCP
  instructions and agent listing arrive after the first call and ride the second
  request, which is why the cut-off is the second call. An attachment record without
  a `rendered` list is not measured and enters no median.

Per agent type the table shows subagents counted, the median first write and first
read, and the median size of each attachment over the transcripts that carried it
(`-` when none did). Main sessions are not in this table.

### Output

Header `Cache report (<window>, <n> transcripts, <n> calls)`, where `<window>` is
`events <since> → <before>`, `last <N>d by file mtime` or `all time`; the three tables
in the order above, each under a one-line caption naming its rule (the threshold
caption prints `T` with `human`); then the existing `NOTE:` footer from `DISCLAIMER`.
When no transcript is selected the existing `no transcripts in window` exit applies;
when transcripts are selected but no call counts, the run exits `no calls in window`,
so an empty run is never printed as a report of zeros.

### Pricing correction

Per D9, the Opus-class row becomes `(5.0, 25.0, 10.0, 6.25, 0.50)` — $5 input, $25
output, 2× for 1-hour writes, 1.25× for 5-minute writes, 0.1× for reads. The comment
above `PRICING` and the module docstring stop claiming comparability with the 35-day
baseline; the comment states what the row is. `SCHEMA_VERSION` stays 1: the record's
shape does not change, and gates are token-based (2026-09-02 D7). Dollar figures from
before and after the change are not comparable, which the docs state.

### Documentation

The module docstring, which is the `--help` text, names the cache report in one
paragraph. `python/README.md` gains an `agent-costs` section holding the cache report's contract:
the flags and their combinations, the window rule, the death rule, the cause kinds,
the premium, reread and start-up definitions, and the pricing note (the change's
non-comparability; that the Opus-class row also prices Opus 5.5 and Fable, whose own
list prices differ). `CLAUDE.md` is unchanged.

### Evidence run

Per D11, on mbp:
`just agent-costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z`.
The end bound is the issue's creation instant (21:39:50Z): the reference analysis could
not have seen a later transcript. A throwaway prototype of this design over the same
store found 3,003 subagent deaths (+13.5 % of 2,646) and $2,156 of general-purpose
reread above 120k (−2 % of $2.2k) for that window, and 2,909 (+9.9 %) and $1,965
(−10.7 %) when the window ends at 2026-10-24T00:00:00Z; the median skill listing was
23,826 characters (the issue's ≈24k) and every death classified (no `unclassified`).
The PR pastes the run's totals line and the general-purpose rows. The rule is the
issue's: a result outside ±15 % is reported as such, never tuned toward the target.

## Test seams

All cases live in `tests/test_agent_costs.py`, run by `just agent-workflow-tests`,
with fixtures built in a temp dir in the shape production records carry (attachment
records with `rendered` lists, `origin` objects with `handback: true`, sibling
`.meta.json` files), per the-bar's "shape fixtures like production". Per D10:

1. **The per-transcript scanner** (the new module's function that `scan_paths` maps),
   called directly on a fixture file: the hand-back death — a `general-purpose`
   *subagent* transcript (5-minute TTL; a root transcript's 1-hour TTL would make a
   9-minute gap no death) that ends its turn, is woken by a peer hand-back 9 minutes
   later and rewrites its context — yields exactly one death of kind
   `hand-back after end of turn` whose premium equals `r × (6.25 − 0.50) / 1e6` for an
   Opus call; a threshold fixture whose calls sit below, at and above `T` yields only
   the above-threshold reread; a subagent's first call yields its write/read and each
   attachment's character count, with the second-call cut-off excluding a later
   attachment. Neighbouring cases pin each cause kind (including a tool wait that a
   hand-back arrives during), the TTL − 10 s and 5k/50 % boundaries, and the window
   filter.
2. **The command**, `agent_costs.main` through the existing `run_main` helper over a
   fixture tree: `--report cache` prints the three tables with the hand-back death's
   row (kind and count; the exact premium is pinned at seam 1, since the table prints
   whole dollars) and the totals line; the usage errors exit 2 with nothing on stdout
   (the `StrataCliTest` pattern).
3. **Pricing**, through `scan_file` like `test_cost_uses_model_family_pricing`: an
   Opus call's cost equals the $5/$25 arithmetic, which fails against the $15 row; the
   end-to-end cost assertion moves with it.
4. **Unchanged default output**: `TextByteIdentityTest` stays green unmodified — the
   golden prints `$0` rows, so the price change does not move it.

## Out of scope

- The per-issue report's semantics beyond the price row: `scan_file` keeps its
  first-copy usage dedup (copies differ only in `output_tokens`, which no cache
  measure reads), its tables and the JSON record.
- Cache-report JSON or new `agent-cost-record` fields; the record's closed key sets
  (`agent_model_drift_schema`) stay as they are.
- A per-model price table (Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Fable $10/$50): the
  issue pins the Opus-class row, and its reference numbers were computed at $5.
- `--project` filtering and Codex strata for the cache report.
- Attachment types beyond the six named, and any token-optimization slice itself.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The report is `agent-costs --report cache` (closed choice, default `issues`, default bytes unchanged), text only, with `--context-threshold` (default 120,000, cache only), `--top` capping each table, and usage errors for json/`--project`/`--artifacts` | Issue AC measures with `just agent-costs` "with the new report"; `--format`/`--strata` precedent for closed choices; the `--artifacts`-with-json usage-error precedent; byte-identity golden | A separate `agent-cache-report` command — the AC names `agent-costs`; a boolean `--cache` — a second report mode is a closed choice like `--format`; silently ignoring issue-only flags — hides a wrong invocation |
| D2 | New module `agent_tools.agent_cache_report` owns scanner, aggregation and rendering and imports `agent_costs`' primitives; `agent_costs.main` imports it inside the `--report cache` branch; the write-split rule becomes one shared function | the-bar: split when the second concern arrives, DRY on knowledge; agent-helpers rule 2 (policy in importable functions); `scan_paths` keeps its D41 call-time default | Growing `agent_costs` past 2.5k lines — a second concern in one file; a top-level mutual import — fragile, and `-m` loads a second copy; moving the primitives to a new module — churns the D41 patch seam and every test reference for no behaviour |
| D3 | The window reuses `--events-since/--events-before` (together, RFC3339, half-open) and filters calls by start time, prefiltering files by mtime ≥ since in place of `--days`; without bounds `--days` selects files and all their calls count | Existing event-bound flags and `event_in_window`; the-bar token economy (few parameters); the issue report's `whole_selected_file_usage` rule | New `--since/--until` date flags — a second spelling of the same bounds; `--days` as a call-time bound — diverges from the issue report's meaning of the same flag |
| D4 | Calls are message-id groups with per-field max usage and zero-input-usage groups dropped; TTL by location (root 1 h, subagent 5 min); agent type from the sibling `.meta.json` (`main` for roots, `unknown` when absent); gap = start − predecessor's end | Issue decisions (dedup max per field, 5 min/1 h); real store: 5,437 of 5,442 subagent transcripts carry `.meta.json`, write splits match the location rule, 273 synthetic zero-usage messages | TTL from each call's write split — the issue fixed the rule by location and the data agrees; agent type from the parent's `Agent` tool use — needs a cross-file join the meta file makes unnecessary |
| D5 | Cause = a tool wait first (the last non-turn-ending result of the predecessor's own tool uses, by tool name), else the first non-tool-result `user` record after the predecessor (the waker, by `origin`), on a closed seven-kind set (child dispatch, long foreground command, other tool, hand-back / task notification / message after end of turn, unclassified) | Real store: `stop_reason` is null on most per-block records; hand-backs are `origin.kind: peer` with `handback: true`, background events `origin.kind: task-notification`; a message arriving mid-tool is delivered after the result; the prototype classified every death | Classifying by `stop_reason` — unreliable in transcripts; by the last record alone — a hand-back delivered after a long tool's result would steal the tool's gap; folding task notifications and parent messages into "hand-back" — the issue names the hand-back case, and the others have different fixes |
| D6 | Premium = `min(cache_creation, predecessor context) × (TTL-weighted write price − read price)` | The issue's "rewrite premium": only the previously cached prefix is a rewrite, and a warm cache would have read it; prototype ≈ $2.4–2.6k against the issue's ≈ $2.5k | Full write price of all creation tokens — counts new content written anyway and the read a warm cache pays too |
| D7 | Reread above `T` = `max(0, cache_read − T) × read price` per call; peaks per transcript over counting calls, nearest-rank percentiles | The cached prefix precedes new tokens in a request; existing `percentile`; prototype general-purpose $1,965–$2,184 against the issue's $2.2k | `max(0, context − T)` — would price written and fresh tokens as reads |
| D8 | Start-up attachments = first record of each of six types before the second call, sized in characters of `rendered` content; medians over the transcripts that carried each | Real store: MCP instructions and agent listing land after the first call; `rendered` is what is sent; skill listing median 23,826 chars against the issue's ≈24k | Only attachments before the first call — would drop two of the six the issue names; JSON size of the attachment object — measures metadata, not what the model reads |
| D9 | Opus-class row `(5.0, 25.0, 10.0, 6.25, 0.50)`; no `SCHEMA_VERSION` bump; docs state the before/after non-comparability and the Opus 5.5/Fable price gap | Issue decision and AC; 2026-09-02 D7 (gates are token-based); `agent_model_drift_schema` validates shape, not prices; the-bar: limitations in docs, not source | A record version bump — the shape is unchanged and no consumer reads the price; per-model prices now — outside the issue's pinned row and its reference basis |
| D10 | Tests at three seams in `tests/test_agent_costs.py`: the per-transcript scanner on production-shaped fixtures, `agent_costs.main` via `run_main`, and `scan_file` cost; the hand-back fixture is a subagent transcript | Issue ACs name the module; existing `run_main`/`StrataCliTest`/pricing-test prior art; agent-helpers rule 5 | A separate test module — the AC names `tests/test_agent_costs.py`; a root-transcript fixture — its 1-hour TTL makes 9 minutes no death |
| D11 | The evidence window is `2026-10-10T00:00:00Z` to the issue's creation instant `2026-10-24T21:40:00Z`, and the rule is never tuned to hit the reference | The reference analysis predates the issue; the-bar: truthful terminal states; the prototype band (+9.9 % to +13.5 % deaths across the two window ends) sits inside ±15 % | An end of 2026-10-25T00:00Z — admits transcripts the reference never saw |
| D12 | (plan) The scanner reads a transcript once by line position: calls in first-seen order; a death's cause reads only the `user` records after the predecessor's first record and before the dying call's first record; a call's window test is `event_in_window` on its earliest parsable record timestamp, and an unbounded run counts untimed calls too; a start-up attachment is the first record of its type, kept only when it lies before the second call's first record | Transcripts append records in order; scan_file's open/skip conventions; the Transcript model, Cache deaths and Start-up sections above | Ordering calls by timestamp — a replayed copy could reorder them; starting the span at the predecessor's last record — a tool result written between a message's block records would fall outside it |
| D13 | (plan) `scan_transcript` returns one plain dict per transcript (`agent_type`, `is_root`, `calls`, `deaths`, `reread_above`, `peak_ctx`, `startup`); `agent_costs.main` owns both empty-run exits and `print_report` prints; the header counts transcripts holding a counting call; tables sort by premium then deaths, by reread dollars, and by subagents, each descending then by name; a median over nothing prints `-`; a capped table prints `... <k> more rows not shown (--top <n> for all)` | agent-helpers rule 2 (the argv shell maps exits); the issue table's drop note; the Output section above | Counting every selected file in the header — a file written after `since` with no counting call would inflate it; returning dataclasses — a pooled worker's result needs nothing richer than a dict |
| D14 | (plan) The command seam also runs `python -m agent_tools.agent_costs --report cache` once, so the real process pool pickles the bound scanner under `-m`; the AC4 run is recorded on mbp at the final code head in the plan's acceptance record (`<plan stem>.acceptance.md`, row AC4) with the run's full stdout beneath the table | agent-helpers rule 5; `ModuleEntryPointTest` precedent; sdd's acceptance-record schema; the 2026-10-22 gh-token plan's evidence task | Only in-process runs with the deterministic executor — never pickles the partial; a separate evidence file — the acceptance record is where sdd and ship-issue read evidence |
