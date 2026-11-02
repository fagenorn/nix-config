# Boot report: project-mix reweighting, medians, reading vs first-unit work — issue 504

Design for https://github.com/fagenorn/nix-config/issues/504 (parent
https://github.com/fagenorn/nix-config/issues/448). Base: `328f08da`
(`origin/main`). A bare "Dn" cites this spec's ledger; "#448 Dn" cites
`2026-10-26-issue-448-slim-owner-boot-design.md` and "#503 Dn" cites
`2026-11-02-owner-report-fair-comparison-design.md`.

## Triage

input: {"signals": {"contract_change": {"value": "hit", "evidence": "the agent-boot-report JSON document (python/README.md: keys are exactly ...) gains reweighted means, medians and sub-totals, and --report boot gains a baseline-window option"}, "concurrency_or_persistence": {"value": "no", "evidence": "read-only transcript report; no locking, no persisted state"}, "open_design_questions": {"value": "doubt", "evidence": "baseline option shape, project derivation for a boot and empty-cell reweighting rule are phraseable and self-answerable from the owner report's --baseline precedent and agent_costs.project_name"}, "criteria_shape": {"value": "no", "evidence": "one acceptance criterion, verified by unit tests in tests/test_agent_boot_report.py"}}, "paths": ["python/agent_tools/agent_boot_report.py", "python/agent_tools/agent_costs.py", "python/README.md", "tests/test_agent_boot_report.py"]}
verdict: {"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

#448's restated AC3 asks whether the mean fresh-owner boot B without tool
schemas, reweighted to the 2026-10-26 baseline window's host × phase group ×
project mix, fell by at least 15k, with medians next to the means.
`just agent-costs --report boot` cannot answer that today:

- **It reads one window.** The 2026-11-01 reading ran the report twice and
  reweighted the phase mix by hand (0–5: 61,454; 6–7: 83,057).
- **It has no project.** nodocom went from 2 of 70 baseline boots to 13 of
  35. Its heavier harness (an 8.5k-character deferred-tool list, a
  10.8k-character skill listing, 10.2k characters of CLAUDE.md) hid about 3k
  of the fall. A boot row does not say which repository it worked in.
- **It prints only means.** One 66k plan read moves a mean of 35 boots by
  almost 2k.
- **Boot end mixes reading and work.** `boot_slice` ends at the registering
  call, or at the first dispatched child, so a boot also holds first-unit
  work: commands, fix waves, plan review (about 21.7k). Skill-text cuts reach
  only the reading.
- **It misses the commonest reread.** The reread key is tool + path + args.
  An owner that `cat`s a file, finds the output truncated, then `Read`s the
  same file is charged twice and neither read counts as a reread. A probe of
  847 owner-like transcripts on mbp (10 days, first 60 tool calls) found a
  whole-file `Read` after an absolute-path `cat` of the same file 30 times.

## Solution

`--report boot` gains `--baseline SINCE..BEFORE`, a second window beside the
event window. The event window is now the candidate (D1). Each boot carries
its lineage's `project` (D2). For every candidate group row, the report gives
B and B without tool schemas reweighted to the baseline's
host × phase group × project mix within that cohort. Weights are renormalised
over the strata both windows hold, and the baseline side is restated over the
same strata (D3). Every mean the report prints gets its median; the
reweighted median is a weighted median (D4). Each boot gets two sub-totals,
`boot_reading` and `first_unit_work`, with mean and median per group. A
reread now compares reads by file extent, so a whole-file `cat` followed by a
`Read` of the same file is a reread (D5). The document moves to `schema_version` 2 (D6). A new
rollup module holds the group statistics and the reweighting (D7).

## Decisions

### Windows and arms (D1)

- **Flag.** `--baseline SINCE..BEFORE` uses the owner report's range grammar
  (`agent_owner_report.parse_range`). The range is half-open, and each bound
  is a `YYYY-MM-DD` UTC day or an RFC3339 instant with an offset. With
  `--report boot` it needs `--events-since/--events-before`, whose window is
  the candidate. The two windows must not overlap; touching is allowed.
- **Arms.** Without `--baseline` every boot is in the arm `live`. With it, a
  boot is in `baseline` or `candidate`. The arm names are the owner report's
  constants, which have one home there.
- **Collection.** Each root is collected once per window, with the event
  window's rule: since and before are the window's bounds, and the mtime
  cutoff is its start. A boot belongs to a window only when `boot_facts`
  accepts it there. So each window's boots, cohorts and statistics are
  exactly what a lone run over that window prints. The recorded #448 baseline
  stays reproducible: B and B without schemas are unchanged, and only buckets
  move (D5). A boot that straddles the two windows is in neither.
- **Label.** With `--baseline`, `window` is the owner report's
  `start_window_label` over both windows, baseline first:
  `baseline <SINCE> → <BEFORE>; candidate <SINCE> → <BEFORE>`. Without it,
  `window` is today's label.

### Project of a boot (D2)

A boot's `project` is its lineage row's `project`, by the owner report's rule
(#503 D4): the basename of the repository root of the lineage's first absolute
registering `--repo-root`, else `project_name` over the owner transcripts'
cwds. The boot report reads it from the lineage that `collect` returns and
does not derive it again.

### Reweighting (D3)

- **Strata.** A stratum is `(host, phase_group, project)` inside one cohort,
  with `phase_group` the concrete `0-5` or `6-7`. Cohorts are never pooled,
  so `fresh` and `spawned` stay separate axes, as in the group rows.
- **Scope.** Each candidate group row (host label or `all`, cohort, phase
  group `0-5`, `6-7` or `all`) gets one reweighted row. Its strata are those
  that row pools: one host or every host, one phase group or both, and every
  project.
- **Common strata.** Let `n0(s)` and `n1(s)` be the baseline's and the
  candidate's boot counts in stratum `s` (an `unsplit` boot is in no
  stratum). `K` is the set of strata in scope with `n0(s) > 0` and
  `n1(s) > 0`, and `N0 = Σ_K n0(s)`.
- **Candidate side, reweighted.** For x in {B, B − tool_schemas}:
  - mean = `Σ_K n0(s) / N0 × mean of x over the candidate's boots in s`;
  - median = the weighted median (D4) of x over the candidate's boots in `K`,
    each boot weighted `n0(s) / n1(s)`;
  - `count = Σ_K n1(s)`.
- **Baseline side.** The plain mean and median of x over the baseline's boots
  in `K`, with `count = N0`. When the candidate holds every baseline stratum
  in scope, this is the baseline group row's own figure. Either way the fall
  is the baseline side minus the candidate side, over one support.
- **Strata in one window only** drop out. A candidate stratum the baseline
  lacks has no weight. A baseline stratum the candidate lacks has no mean to
  weight. The row reports `common_strata = |K|` and both counts, and the
  group rows give the full counts, so a reader sees how much each window
  covers. With `K` empty the counts and `common_strata` are 0 and every
  statistic is `null`.
- **Only B and B without tool schemas are reweighted**, as the issue asks.
  Buckets, sub-totals and top skills stay per window.
- No minimum boots per stratum. A close rule such as #448's "5 per stratum"
  belongs to the acceptance protocol that reads the report.

### Medians (D4)

- **Every mean gets a median.** The group rows already have the means of B, B
  without tool schemas and each bucket. They gain the medians of those, plus
  the mean and median of the two sub-totals. The text output's top-skills
  table gains the median per fresh boot, and the reweighted rows hold a
  median beside each mean (D3).
- **Definition.** The median of n values is the middle value, or the mean of
  the two middle values when n is even (`statistics.median`). A weighted
  median sorts the values and takes the first one whose cumulative weight
  reaches half the total weight. When the cumulative weight equals exactly
  half, it takes the mean of that value and the next. Weights are exact
  fractions, so the half test has no rounding. With equal weights this is the
  plain median. One function computes both.

### Sub-totals: boot reading and first-unit work

The keys are the issue's terms, because a bare `reading` would suggest it
holds `other_reads`, which is work.

- `boot_reading` = `skill_bodies + skill_files + plan_reads + resume_reads +
  rereads`.
- `first_unit_work` = `commands + assistant + other_reads`.
- `tool_schemas`, `harness`, `prompt` and `unexplained` are in neither. B
  and boot end stay `boot_slice`'s.
- Each boot row carries both sub-totals, and each group row carries their mean
  and median. The bucket tuples have one home in the boot report.

### Reread detection (D5)

- **Read key.** A read key is a path and an extent.
  - A whole-file read has its own extent. These are whole-file reads: a
    `Read` with none of `offset`, `limit` or `pages`, and each file operand
    of a `cat` whose standard output reaches the result. The output reaches
    the result only when the `cat` is at the command's top level (outside
    any `(`…`)` and backticks, so `$(cat X)` is not whole), is not followed
    by `|` or `|&`, and has none of the redirections `>`, `>>`, `>|`, `&>`
    or `&>>`, with or without a leading `1`.
  - Every other `Read` has the extent `(offset, limit, pages)`.
  - Every other reader operand has the words of its command, as today.
- **Reread.** A call is `rereads` when it reads something and an earlier read
  covers every one of its keys. An earlier read covers a key when it read the
  whole of the same path, or read the same path with the same extent.
- **Effect.**
  - `cat X` then `Read X`, or the reverse, is a reread.
  - A ranged `Read` after a whole read of the same file is a reread.
  - A whole read after ranged reads is not.
  - Different ranges never cover each other.
  - `cat X | head` is not a whole read.
- **Path identity is unchanged.** Operands are expanded with in-command
  `NAME=value` and joined to the in-command `cd`. A relative or `~` operand is
  compared as written. The probe found 2 whole-file `Read`s after a `~` cat
  and none after a relative cat, against 30 after an absolute one.
- The rule order, the `saved to:` read-back rule and the other buckets are
  unchanged.

### Document: `agent-boot-report`, `schema_version` 2 (D6)

- **Top-level keys.** Exactly `kind, schema_version, window, hosts,
  chars_per_token, observed_chars_per_token, unsplit, boots, groups,
  reweighted`.
- **`unsplit`.** Maps each arm, in arm order, to its `{host label: count}`
  map.
- **`observed_chars_per_token`.** Pools every boot of the document.
- **Boot rows.** Exactly `arm, host, transcript, run_id, issue, project,
  cohort, phase_group, calls, start, b, boot_reading, first_unit_work,
  buckets, skills, skill_files`. Arm order is `live`, or `baseline` then
  `candidate`, and within an arm the order is today's.
- **Group rows.** Exactly `arm, host, cohort, phase_group, count, b_mean,
  b_median, b_without_schemas_mean, b_without_schemas_median,
  boot_reading_mean, boot_reading_median, first_unit_work_mean,
  first_unit_work_median, buckets, bucket_medians`. Rows are in arm order,
  then today's order. `buckets` stays the bucket means, and `bucket_medians`
  has the same twelve keys.
- **`reweighted`.** `null` without `--baseline`. With it, a list with one row
  per candidate group row, in that row's order. Each row is exactly `host,
  cohort, phase_group, common_strata, baseline, candidate`, and each side is
  exactly `count, b_mean, b_median, b_without_schemas_mean,
  b_without_schemas_median`.

### Text output

- **Every run.** The sections and headings are as today, with these
  additions:
  - Each mean-table group column gets a `median` column beside it. The
    header says `median`, not the owner report's `p50`, which is a
    nearest-rank percentile (D4).
  - Two rows, `boot reading` and `first-unit work`, follow the twelve buckets
    and come before `B`.
  - The top-skills table gets a `median` column.
  - The boots table gets `project` after `issue`, and `boot reading` and
    `first-unit work` after `B`.
- **With `--baseline`, also:**
  - The header gives each arm's boot counts.
  - The mean tables, top skills and boots table print once per arm, baseline
    first, and each heading names its arm.
  - A `Reweighted to the baseline's host × phase group × project mix` table
    follows, one line per `reweighted` row. Its columns are host, cohort,
    phase, common strata, both counts, and for B and for B without tool
    schemas the baseline mean and median and the candidate mean and median.
    A `null` prints as `-`.
  - The footer's unsplit line prefixes each arm's counts with the arm.
- The observed-ratio line and the `NOTE:` stay last.

### CLI rules

- **Usage errors.** Each of these exits 2 with nothing on stdout:
  - `--baseline` with a report other than `owners` or `boot`;
  - `--report boot --baseline` without `--events-since/--events-before`;
  - a `--baseline` range that does not parse, or whose `SINCE` is not before
    its `BEFORE`;
  - a `--baseline` window that overlaps the event window.
- **Unchanged.** The owner report's `--baseline` rules stay as they are, and
  so do `--started`, `--settle-days` and `--proxy-log`, which remain
  owners-only. Every usage error is raised before any root is read, and a
  missing root still exits 1.

### Modules (D7)

- **`agent_tools.agent_boot_rollup` (new).** Builds the group rows from boot
  rows; `_group_rows` moves here. It also holds the one median function and
  builds the reweighted rows from both arms' boot rows. It is pure and has no
  I/O.
- **`agent_tools.agent_boot_report`.**
  - Collection now takes an arm and adds `project` to each boot.
  - It owns the sub-total tuples and the extent-aware read keys and reread
    rule.
  - It assembles the v2 document from the rollup's rows, and prints the text.
- **`agent_tools.agent_costs`.** `_boot_report` parses `--baseline`, checks
  the overlap and collects each root once per window. The flag checks and the
  docstring name the boot report's `--baseline`.
- **Contract.** The package README's *Boot report* paragraphs carry the new
  rules: windows, project, reweighting, medians, sub-totals, read keys and
  the v2 document.

## Test seams

All tests are in `tests/test_agent_boot_report.py` and use its existing seam:
`report(*roots, extra=...)` runs `python -m agent_tools.agent_costs --report
boot --format json` as a subprocess on `owner_transcripts.Session` fixtures
(#448 test seam 1, agent-helpers rule 5). Projects come from `progress(...,
repo_root=...)`. Windows are bounds around the fixture's `at()` instants (D8).

- **AC, reweighting.** Two projects in different proportions across a
  baseline and a candidate window, one host and one phase group: for example
  baseline A×1, B×3 and candidate A×3, B×1.
  - The candidate side's mean and weighted median of B and B without tool
    schemas equal hand-computed values.
  - The baseline side's figures equal the baseline group row's.
  - The weighted median differs from the candidate's plain median, so the
    test fails if the weights are dropped.
- **Coverage.** A candidate-only project and a baseline-only project are left
  out of `K`, as `common_strata` and both counts show. A scope with no common
  stratum gives zero counts and `null` statistics.
- **Medians and split.** Group rows' `b_median`, `bucket_medians`,
  `boot_reading_*` and `first_unit_work_*` equal hand values on an even
  count, which tests the averaged middle. Each boot row's two sub-totals
  equal the sums of their named buckets.
- **Rereads.**
  - `cat X` then `Read X` with no range moves the `Read`'s tokens to
    `rereads`.
  - `cat X | head` then `Read X` does not, and neither does `V=$(cat X)`
    then `Read X`.
  - The existing read-backs test stays green: its whole `cat` after two
    ranged `Read`s stays `other_reads`.
- **Arms and keys.** Without `--baseline`, rows carry `arm` `live` and
  `reweighted` is `null`. With it, a boot outside both windows is in neither,
  and the v2 key sets hold exactly.
- **Usage errors.** Each *CLI rules* case exits 2 with empty stdout, in the
  pattern of `test_foreign_flags_are_usage_errors`.
- **Text.** The `median` columns, the `boot reading` and
  `first-unit work` rows, the per-arm headings and the `Reweighted` table
  print in order, in the pattern of
  `test_text_output_prints_its_four_sections_and_footer`.

## Out of scope

- `boot_slice`, `boot_facts` and boot end; the owner report and its
  `--baseline`; host collection mechanics and copying another host's root.
- Resolving relative or `~` read operands against a record cwd or a home
  directory (D5). Also not modelled: the cut-off of a `Read` past 2,000
  lines (such a `Read` counts as whole) and a brace group piped as a whole
  (`{ cat X; } | head` counts as whole).
- Reweighting buckets, sub-totals or top skills; a per-stratum mix table; a
  minimum-stratum close rule (D3).
- Running #448's AC3 measurement and judging its 15k threshold.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `--report boot --baseline SINCE..BEFORE` (owner grammar, half-open, no overlap) makes the event window the candidate; arms `live` or `baseline`/`candidate` (the owner report's constants); each root is collected once per window by the event-window rule, so each window equals its lone run; the label is `start_window_label` | #503 D1/D7 (one range grammar, baseline first); #448 acceptance § Post-deploy protocol ran the baseline and the window as event windows; the-bar DRY | selecting boots by lineage start (`--started`): a boot is placed by its own calls, and the #448 baseline was an event window. One collect over the hull split by boot time: it changes launch membership and cohorts against a lone run. A new flag name: a second grammar for one concept |
| D2 | A boot's `project` is its lineage row's `project` (#503 D4), read from `collect`'s lineage | #503 D4's mbp probe (every owner passes `--repo-root`); one home for project naming | deriving it again from the transcript directory or cwd: worktree directories differ, and a cross-project owner would be misnamed |
| D3 | Stratum = host × phase group × project within one cohort. Each candidate group row gets a reweighted row over the strata it pools: candidate stratum means weighted by baseline counts, renormalised over the strata both windows hold, beside the baseline's plain figures over those strata. Strata in one window only drop out, shown by `common_strata` and counts. `null` when none are common. Only B and B without tool schemas are reweighted | #448 acceptance `M1 = Σ n0/N0 × m1`; restated AC3; issue bullet 1; #448 D12 (per-host falls reported too) | `null` unless every baseline stratum is covered: with project as a dimension, one rare baseline project blocks the figure for good. Filling gaps from a coarser cell: an imputation the reader cannot see. Comparing with the full baseline mean: two different supports |
| D4 | Medians beside every mean, the reweighted ones included. Median = `statistics.median`. The weighted median uses exact-fraction weights `n0(s)/n1(s)`, averaging at an exact half, so it reduces to the plain median. (grill) The text calls the column `median`, never `p50` | issue bullet 2 and restated AC3 "medians reported next to means"; the-bar tests that can fail (exact ties); the owner report's `p50` keys name `percentile` | an unweighted candidate median beside a reweighted mean: it keeps the mix bias the issue removes. `agent_costs.percentile(…, 50)` (the owner report's `p50`): a nearest-rank element whose even-count side flips with n. Float weights: the half test would depend on rounding |
| D5 | Extent-aware read keys. A whole-file read is a `Read` with none of `offset`, `limit` or `pages`, or a `cat` operand whose stdout reaches the result. (grill) That means a top-level `cat`, outside `(`…`)` and backticks, neither piped on nor redirected to a file. A key is covered by an earlier whole read of the path or the same extent. Path identity stays in-command only | issue bullet 4; mbp probe 2026-11-02 (whole `Read` after an absolute `cat` 30, after a `~` cat 2, after a relative one 0); #448 D1 (shared reader unchanged); the lexer emits `(`, `)` and backticks as separators, so `V=$(cat X)` would otherwise look whole | path-only identity: paging through ranges, and `cat X \| head` then `Read X`, would count as rereads. Joining operands to a per-call cwd or home: about 2 of 32 cases, and it needs a per-call cwd from the shared reader. `nl`/`less` as whole reads: `nl` is usually piped into `sed` for a range |
| D6 | `agent-boot-report` moves to `schema_version` 2 with the key sets of § Document: `arm`, `project`, `boot_reading`, `first_unit_work` on boots; medians and sub-totals on groups; `unsplit` keyed by arm; `reweighted` always present, `null` without `--baseline`, with symmetric `baseline`/`candidate` sides. (grill) The sub-totals carry the issue's names, and the stratum count is `common_strata` | the README pins exact key sets; #503 D8 (version bump, always-present `comparison`); `agent-costs --strata` already means the claude/codex sources, and a bare `reading` would seem to hold `other_reads` | v1 with optional keys: silently breaks the pinned sets. One document per window: the reweighting needs both windows' boots in one place. Renaming `b_mean`/`buckets` into nested objects: churn for no consumer |
| D7 | New `agent_tools.agent_boot_rollup` holds the group rows (moved), the median function and the reweighting, as pure functions over boot rows. The boot report keeps collection, attribution, read keys, document and text. `agent_costs` wires the flag | the-bar single responsibility (statistics over rows is a second concern); #503 D9's `agent_owner_rollup` precedent; agent-helpers rules 1–2 | everything in `agent_boot_report` (about 800 lines with two concerns); reusing `agent_owner_rollup` (a lineage-dollar aggregate over different rows) |
| D8 | Tests drive the CLI only, through `report()` on `Session` fixtures, with projects from `progress(repo_root=)` and windows around `at()` instants. The AC fixture's weighted median differs from the plain one | #448 test seam 1; agent-helpers rule 5; the AC's "unit tests in `tests/test_agent_boot_report.py`" | in-process rollup tests alone: they skip the flag wiring the demo uses. A fixture whose weighted and plain medians agree: a dropped weight would stay green |
| D9 | (plan) `agent_boot_rollup` owns the grouping axes `ALL`, `COHORTS` and `PHASE_GROUPS`, moved from the boot report, which imports them. It takes the bucket names as an argument. The bucket and sub-total tuples stay in the boot report | D7; the-bar DRY (one home); the boot report imports the rollup when it loads, so the rollup cannot import `BUCKETS` back | the rollup importing `BUCKETS` (a circular import that fails at load). Reading the names from the first boot's `buckets` map: an implicit contract, and a group with no boot has no names |
| D10 | (plan) Every statistic is a float or `null`. The reweighted mean is the weighted mean `Σ w·x / Σ w` over the candidate's boots in `K`, with D4's `w = n0(s)/n1(s)`, which equals D3's `Σ_K n0(s)/N0 × stratum mean`. It is computed exactly and rounded once. The baseline side uses the same function with weight 1, so for integer B it equals the group row's `statistics.fmean` | D3, D4 (exact weights); the-bar tests that can fail (hand values compared with `assertEqual`) | summing rounded per-stratum float means: the second rounding can move the last bit, so the AC's hand value, or the baseline group row, could differ by one ulp |
| D11 | (plan) Without `--baseline` every heading is today's. With it, each per-arm heading adds `, <arm>` after its section name (`Mean boot buckets, baseline, host mbp`, `Boots by B, candidate`), the header gives `<arm> <n> boots: …` per arm, and the unsplit footer joins the arms with `; `. A mean table's `boots` row leaves its `median` cells empty | § Text output ("each heading names its arm"); the existing text tests find today's headings as substrings | a title line per arm: a section the existing order test cannot place. Repeating the count under `median`: noise |
