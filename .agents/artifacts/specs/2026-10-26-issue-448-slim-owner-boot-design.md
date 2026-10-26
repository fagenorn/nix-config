# Slim the fresh-owner boot: a boot-composition report, then the cuts that pay — issue 448

Design for https://github.com/fagenorn/nix-config/issues/448. A bare "Dn" cites this spec's
ledger. Base: `ca6ba1ae` (origin/main). Related: https://github.com/fagenorn/nix-config/issues/432
(boot definition, replay, threshold), https://github.com/fagenorn/nix-config/issues/447 (the
tool-schema share), https://github.com/fagenorn/nix-config/issues/425 and
https://github.com/fagenorn/nix-config/issues/265 (the resume pack).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds the `--report boot` CLI view and may change the resume pack shape and skill read contracts"}, "concurrency_or_persistence": {"value": "no", "evidence": "read-only transcript analysis and skill text; no locking or persisted state changes"}, "open_design_questions": {"value": "hit", "evidence": "which cuts pay and how the resume entry and task-file pointer are expressed are open"}, "criteria_shape": {"value": "hit", "evidence": "the evidence criterion (mean boot falls 25k on new transcripts) no deterministic code check verifies"}}, "paths": ["python/agent_tools/agent_costs.py", "python/agent_tools/agent_owner_report.py", "python/agent_tools/agent_boot_report.py", "tests/test_agent_boot_report.py", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/resume-pack.md", "home/common/agent-skills/skills/sdd/SKILL.md", "home/common/agent-skills/scripts/workflow-state.py"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

A fresh issue owner is an owner launch that takes over work another launch started: an owner
delegated at the Phase-5 rollover, a generic `delegate` owner, or one relaunched after a hand-off,
suspension or `fresh_start`. Before its first unit of work it holds about 94k tokens of context
(mean B over 43 fresh owners on 2026-10-26; about 100k in Phases 6–7). #432 showed what that
costs: a hand-off saves the read price on C − B for each later call and pays the write price on B
once, so at B ≈ 104k a hand-off pays only after 57 calls at a 150k threshold. That is why #432
moved the threshold to 200k. At B ≈ 51k, break-even would fall to about 13 calls.

The owner cannot see where the 94k goes, and nobody can check a cut against it:

- **No measuring view.** `agent-costs --report owners` reports each boot's B, start and
  "slimmable" tokens, but not what the boot read. The 2026-10-26 composition came from a scratch
  analysis that ported none of its logic into the package.
- **Whole-package plan reads.** 17 of 31 Phase 6–7 owners read several or all task files before
  Task 1. The cost sits almost entirely in owners that enter Phase 6 fresh (26.5k mean in 10 of
  14 delegated Phase-6 owners): sdd's initial validation reads the plan root and every member,
  although the Phase-5 reviewer has just read them all. In jarbird #45 the relay owner ran `cat`
  on all eight task files (≈51k). Claude Code persisted the oversized output, and the owner read
  the whole file back (≈17k more).
- **The whole skill on every relaunch.** Every relaunch prompt says "invoke the `from-issue`
  skill", so the 30k-character body (≈11k tokens) loads before the resume pack's checks. This
  happens although #265's resume pack already tells a verified owner to read only its phase's
  sections.
- **Support files read beyond need.** Owners in Phases 6–7 read AUTO.md's Phase 0/5 stop rules,
  all of `delegated-owner.md` when their route needs one section, and `ship-handoff.md` (16.5k
  characters) long before Phase 7.

## Solution

Measure first, then cut (the issue's order):

1. **`just agent-costs --report boot`.** Each fresh owner's boot, exactly #432's `boot_slice`, is
   split into a closed set of composition buckets that sum to B (D2, D3). The report gives
   per-owner rows and cohort-by-phase means as text or JSON, and records the 2026-10-26 baseline
   from the tool itself (D12).
2. **The cuts that pay**, each judged by one keep rule (D5) and committed with its own contract
   pin:
   - **Cut 1, one task file:** sdd reads the whole package only for an unreviewed first entry
     (D6).
   - **Cut 2, the resume entry:** a relaunch prompt that carries a resume pack names from-issue's
     `resume-pack.md` by absolute path in place of the skill invocation, and a verified owner
     reads only the sections the index names for its phase (D7).
   - **Cut 3, support-file sections:** the index's read rules stop the three over-reads above
     (D8).
   - Cut 4 (sdd's resume section) and cut 5 (a re-read rule) do not pay or cannot be pinned, so
     they do not ship (D9, D10).
3. **Evidence and threshold.** The PR re-runs #432's sweep on the transcripts available and states
   the threshold it chooses (D13). The issue is then held for the post-deploy boot measurement
   (D12). The projected fall is about 15.5k, short of the issue's 25k, and the measurement decides
   (D11).

## Decisions

### The boot report (per D1–D4, D14)

**Module and seam.** A new `agent_tools.agent_boot_report` builds the report; `agent_costs.main`
dispatches `--report boot` to it as it dispatches `--report owners` (a thin shell, policy in
importable functions). It collects lineages through `agent_owner_report.collect` and takes each
launch that `boot_facts` accepts, with `boot_slice` unchanged. Then it makes one more pass over
that launch's transcript to attribute the boot's calls. It takes the calls from the shared
reader `transcript_calls.read_transcript`, which is unchanged. The boot module reads the records
that reader skips itself: the `api-request-shape`, `api-request` and `api-request-blob` records
Claude Code writes, and the content of tool results, Skill bodies and request tails. A boot's
calls are the first `len(boot_slice(launch))` of those calls. `boot_facts` accepts only a boot whose calls are
all inside the window, so the launch's kept calls and the transcript's calls coincide there.

**Cohorts (D4).** A boot is `fresh` when its launch is not the first launch of its lineage, or
when the launch ordinal its identity carries is 2 or more. Otherwise it is `spawned`. Its phase
group is `boot_facts`' group (`0-5` or `6-7`, by the registering call's phase). Means are
reported for each cohort in each phase group and for `all`. The issue's measure is `fresh`/`all`.

**Attribution (D3).** For call 0, the start context is split between text and tool schemas. The
text is the system prompt, the reminders and listings, and the prompt, each converted at the fixed
`CHARS_PER_TOKEN = 2.44` (the 2026-10-26 aggregate over 678 calls). `tool_schemas` takes the
remainder of the start context. The prefix comes from the request-shape record and from the
message blobs of the first request's tail. For each later boot call *i*, the growth over call *i−1*
is first charged to `assistant`, up to call *i−1*'s output tokens. The rest is split across the
content added between the two calls by character share: tool results, Skill bodies, request-tail
blobs (reminders, listings, hook context, tool additions) and tool-schema changes. Growth with no
added content to carry it is `unexplained`. A boot's buckets therefore sum to B exactly, and only
call 0 depends on the ratio.
The report also prints the observed ratio: added characters over attributed tokens, for the boot
calls that added more than 2,000 characters. A reader can see the constant drift that way. A
transcript without request records cannot split its call 0. That boot is left out of every row
and mean and counted in `unsplit`.

**Buckets (D2), a closed partition of B, in report order:**

| Bucket | What it holds |
|---|---|
| `tool_schemas` | call-0 tool definitions, inline tool additions, later schema changes (#447's share) |
| `harness` | system prompt, system reminders, skill/agent/deferred-tool/MCP listings, hook context |
| `prompt` | the launch prompt |
| `skill_bodies` | Skill-tool loads, with a per-skill sub-map |
| `skill_files` | reads of files in a skill directory, with a per-`<skill>/<file>` sub-map |
| `plan_reads` | the plan root, its task members, the SDD ledger |
| `resume_reads` | the resume pack and the owner object |
| `rereads` | a read repeating an earlier read of the same file and range in this boot |
| `other_reads` | every other file read (spec, handoff, acceptance record, source, docs) |
| `commands` | other tool output (non-reading Bash, search, ToolSearch, other tools) |
| `assistant` | output tokens kept in context |
| `unexplained` | growth with no added content |

A result's bucket is decided in this order:

1. `rereads`: a repeat of the same path with the same range (a Read's offset and limit, or a
   reader command's arguments).
2. `resume_reads`: a result that holds a resume pack (`kind: resume_pack`) or an interface-2
   owner object, recognised by its content and never by a dispatcher-chosen file name.
3. The class of the paths it reads.

A Read of a persisted tool output, named after `saved to:` in an earlier result, takes that
result's bucket and is never a re-read. A Bash call's reads are the file operands of its reader
commands (`cat`, `sed`, `head`, `tail`, `nl`, `awk`, `jq`, `less`), resolved against its `cd`s and
simple `NAME=value` assignments, with heredoc bodies skipped. A call that reads files of several
classes takes the first of skill file, plan, other. A call that reads none is `commands`.

**Document (D14).** `--format json` prints one `agent-boot-report` (`schema_version` 1). It holds
`window`, `chars_per_token`, `observed_chars_per_token` and `unsplit` (a count). It also holds:

- `boots`: one row per boot, with `transcript`, `run_id`, `issue`, `cohort`, `phase_group`,
  `calls`, `start`, `b`, `buckets` (all twelve keys), `skills` and `skill_files`;
- `groups`: one row per cohort and phase group, with `cohort`, `phase_group`, `count`, `b_mean`,
  `b_without_schemas_mean` and `buckets` (means).

The text output prints four things in order:

1. A header naming the window, the boot counts and the ratio.
2. The bucket-by-group table of means, with B and B without tool schemas.
3. The top skill bodies and skill files by mean per fresh boot.
4. The per-boot table, sorted by B and capped at `--top` with the dropped count.

A footer then gives the observed ratio, the `unsplit` count and the comparative-telemetry
`NOTE:`. The flags are `--days`, `--events-since/--events-before` (the owner report's semantics),
`--projects-dir`, `--top` and `--format`. `--project`, `--artifacts`, `--strata` other than
`claude`, `--policy`, `--sweep`, `--eval-results`/`--eval` and `--context-threshold` are each a
usage error (exit 2, nothing on stdout). The package README's agent-costs section gains the
contract paragraph.

### The keep rule (per D5)

A cut ships only when all three of these hold:

1. **It pays.** The baseline boot report's per-boot rows show at least 1,000 tokens per fresh boot
   (mean) that the cut's reading rule removes. The projection is that rule applied to the rows:
   the target bucket or sub-map entry, times the share of its bytes the rule skips, at the report's
   ratio. Each projection is recorded in the acceptance record.
2. **It lowers instruction load.** Its text is net-negative in corpus bytes, and no profile ceiling
   rises. Growth in one member is offset within the same profile's members. When the cut takes a
   profile more than 5% below its ceiling, `tighten` lowers that ceiling (the only model change
   allowed without the raise label).
3. **It can be pinned.** A contract test pins it under the agent-helpers rule 6: the identifiers a
   subagent consumes (file names, headings, literal tokens, the owner-prompt template), never an
   English phrase.

Each kept cut is its own commit.

| Cut | Shape | Projection (mean per fresh boot) | Verdict |
|---|---|---|---|
| 1 | one task file per dispatch (D6) | ≈10.6k (plan reads 15.3k) | keep |
| 2 | resume entry instead of the whole from-issue skill (D7) | ≈2.9k (≈7.2k bytes skipped of 30.5k, in ≈40/43 boots) | keep |
| 3 | support-file sections (D8) | ≈2.1k (AUTO 0.6k, delegated-owner 0.4k, ship-handoff 1.1k) | keep |
| 4 | sdd resume section (D9) | ≈0.7k | reject |
| 5 | re-read rule (D10) | not pinnable; sources removed by 1–3 | reject |

The issue's estimates (8.7k for cut 2, 5.5k for cut 3, 2.7k for cut 4) assumed a 2.5k-token resume
entry and a two-thirds cut of support reads. The section sizes above are what a resumed owner
must still read (D11). The plan re-derives every projection from the tool's own baseline report
before keeping a cut.

### Cut 1 — one task file per dispatch (per D6)

sdd's whole-package read and its conflict scan run only for a plan's first, unreviewed entry. They
are skipped in two cases:

- **A reviewed plan.** The invocation carries the literal token `--reviewed`. from-issue's Phase 6
  passes it on every route, because Phase 5's reviewer read the root and every member.
- **A resume.** The workspace ledger already names the plan.

A reviewed or resumed run reads the plan root's header sections and its checker metrics. Before
each dispatch it reads only the current task's member, `<plan stem>.tasks/task-<N>.md`. Any other
caller (a user, or sdd outside from-issue) passes no token and keeps today's validation. The resume
pack keeps its shape and bound. Its `sdd.plan` and its `resume_task` number already name the
member through the package layout, so no `task_file` field and no change to the risk path are
needed.

### Cut 2 — the resume entry (per D7)

- **Entry.** Some dispatchers put a resume pack in a fresh owner's prompt: orchestrate-issues'
  owner-prompt template, from-issue's `delegate` action and its rollover. Each of them names
  `<from-issue directory>/resume-pack.md` by absolute path as the owner's entry, in place of the
  Skill-tool invocation. The prompt keeps the invocation's arguments (`from-issue <num> --auto`),
  so `--auto` is still visible. The dispatcher knows the directory: from-issue's own base
  directory, or for orchestrate-issues the `from-issue` directory beside its own. Both trees
  install into one skills directory. For from-issue's own composers the rule lives once, in its
  `### Resume pack`, which every composing owner reads. orchestrate-issues loads no from-issue
  text, so its verbatim template carries the rule in its own words. A prompt without a pack is
  unchanged.
- **Verified pack.** The owner runs the pack's existing checks. It then reads SKILL.md's
  `## Files beside this one` and only the sections that index names for its phase. Everything the
  pack does not replace still runs.
- **Failed check or refused pack.** The owner loads the whole `from-issue` skill with the prompt's
  arguments and re-orients in full, as today.
- **Where the read list lives.** The per-phase read list stays in SKILL.md's index (hot), where
  #265 put it. It is refined in place for cut 3, so the resume entry adds only its entry and
  fallback sentences, offset within `resume-pack.md`.
- **Scope.** Only from-issue's own body is read by sections. Sub-skills (`sdd` in Phase 6) still
  load through the Skill tool, so the Skill-tool rule needs no exception. ship-issue gets no resume
  entry: one of 43 baseline boots loaded it (269 tokens per boot).

### Cut 3 — support-file sections (per D8)

The index's read rules for a verified pack become:

- **AUTO.md.** In Phases 6–7, read only the opening, `The self-answer pattern`,
  `Interface_version 2 delivery relay` and `Other Phase 5–7 routes`. `When *not* to
  auto-resolve` governs Phases 0 and 5 and is not read.
- **delegated-owner.md.** Read only the section the route selects: `## Checks and Phases 6–7` for
  the rollover owner, `## Generic delegate` for a generic delegate.
- **ship-handoff.md.** Read only once Phase 7 starts, or when a generic delegate builds its
  handoff after Phase 6's gates, never during the boot.

These are rewordings of index lines that already exist, net-negative in bytes. The pack's JSON
carries no section names or text: it reports facts only (#265), and 4,096 bytes could hold no
section anyway.

### Evidence and threshold (per D11–D13)

- **Baseline.** Before deploy, run `--report boot` over the window of the four 2026-10-26 baseline
  sessions. Record its `fresh`/`all` and per-group means of B without tool schemas. The scratch
  analysis gave 93,999 B and 16,709 schemas over 43 owners, and the tool's own figure is the
  reference.
- **Sweep.** Before merge, re-run `--report owners --sweep` on the available transcripts and state
  the chosen threshold with its reasons in the acceptance record. The observed boots are not yet
  cut, so 200k is expected to stand. The sweep's `boot=slim` arm already models the stale
  task-file reads.
- **Hold.** The `[evidence]` row is pending at ship, so the issue is held with `needs-verification`,
  as #432 is. The hold comment names the protocol:
  - The post-deploy window starts at the `just switch` that deploys the merge. It closes once it
    holds at least 20 fresh boots, at least 5 of them in each phase group.
  - The criterion is met when the baseline's `fresh`/`all` mean of B without tool schemas, minus
    the post-deploy group means reweighted to the baseline's phase-group mix, is at least 25,000.
    The reweighting keeps a window with fewer Phase 6–7 owners from passing by mix alone.
  - The same session re-runs the sweep over the post-deploy window. A lower threshold that keeps
    against 200k is set in a follow-up commit that cites #448. Otherwise 200k stands, with reasons.

## Test seams

1. **The CLI.** `python -m agent_tools.agent_costs --report boot --format json --days 0
   --projects-dir <tmp>` runs over fixture transcripts. It follows `tests/test_agent_owner_report.py`'s
   `report()` helper and the `owner_transcripts.Session` builder, extended to write request-shape,
   request and blob records, Skill meta messages and file-reading tool results. Tests assert:
   - the per-boot bucket sum equals B, and the call-0 split equals start minus text at 2.44;
   - a persisted read-back lands in its origin's bucket, a same-range re-read is `rereads`, a pack
     or owner object is `resume_reads` whatever its file name, and the skill and skill-file
     sub-maps are filled;
   - the fresh/spawned cohorts follow lineage position and launch ordinal, and a transcript without
     request records counts only in `unsplit`;
   - refused flags exit 2, and the text output prints its four sections.
2. **The skill-text contracts.** `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
   (prior art `ResumePackContractsTest`) gets identifier-only pins under rule 6:
   - every heading and document the index's verified-pack read list names exists;
   - the Phases 6–7 list names neither `When *not* to auto-resolve` nor `ship-handoff.md` before
     Phase 7;
   - the owner-prompt template and from-issue's `### Resume pack` name `resume-pack.md` as the
     entry;
   - `--reviewed` appears in from-issue's Phase 6 and in sdd's Setup.
3. **The Instruction Budget gate.** `just agent-instruction-budget` passes without the raise label,
   so every profile stays within its ceiling.
4. **Evidence.** Acceptance-record rows hold the baseline report, each cut's projection, the
   pre-merge sweep and the post-deploy protocol (D12). `just agent-workflow-tests` and `just build`
   pass.

## Out of scope

- The tool-schema share and the issue-owner agent type (#447); `--help` (#432).
- Any instruction-budget raise, new skill document or profile-membership change.
- Changing `boot_slice`, `boot_facts` or #432's replay model beyond re-running it.
- The resume pack's schema or byte bound, and any change to `workflow-state` (no risk-path edit).
- The harness listings and reminders (`harness`, ≈10.8k), the owner object's size, and a
  ship-issue resume entry.
- sdd section reads (cut 4) and a re-read rule (cut 5).
- Measuring before merge through eval trials.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D0 | The orchestrator's first Phase-0 `workflow-state progress` call passed `--next-needs-context false` by mistake and got `handoff`. It re-recorded Phase 0 with the truthful `true` and got `continue`. | from-issue SKILL.md "booleans truthful": the Phase-2 dispatch needs the Phase-0 summary held in the owner's context | Obeying a gate computed from an untruthful input, which would have relaunched a fresh owner (≈90k boot) for no benefit |
| D1 | The boot report is a new `agent_tools.agent_boot_report`. It takes lineages from `agent_owner_report.collect` and boots from `boot_facts`/`boot_slice` unchanged, and makes its own second transcript pass. The shared reader is unchanged. | Issue decision "boot end is the replay's `boot_slice`"; agent-helpers rules 1–2; `OwnerCall` keeps only token counts | Extending `read_transcript` with request records: every report would pay for them and the shared reader's contract would change. Redefining the boot: the issue forbids it |
| D2 | Twelve closed buckets that partition B, with per-skill and per-skill-file sub-maps. A bucket is decided by re-read (same path and range) first, then content (resume pack or owner object), then path class. A persisted read-back takes its origin's bucket. | The issue's composition table and cut targets; the-bar "tests that can fail" (a sum-to-B invariant); #432's `saved to:` rule | Porting the scratch analysis's ~30 labels: they key on dispatcher-chosen scratch names (`owner-*.json`, `t<N>.md`) |
| D3 | Each call's growth is split by character share after charging the previous call's output. Call 0's text uses a fixed 2.44 chars per token, and tool schemas take the remainder. The observed ratio is reported. A transcript without request records is `unsplit` and kept out of the means. | 2026-10-26 calibration (aggregate 2.44 over 678 calls); the issue's "about 2.5, not 4"; usage deltas make every later call exact | A per-run calibrated ratio: the baseline and post-deploy windows would split call 0 differently, and small windows are noisy. 4 chars per token: refuted by the calibration |
| D4 | `fresh` means not its lineage's first launch, or a launch ordinal of 2 or more. Every other boot is `spawned`. Means are reported per cohort per phase group and for `all`. | Lifecycle identity (lineage order, custody launch); the issue measures fresh owners | Classifying by prompt text (the scratch analysis): fragile. Launch ordinal alone: 10 of 43 baseline delegated owners inherit ordinal 1 |
| D5 | Keep rule: at least 1,000 tokens per fresh boot (mean) projected from the baseline report, text net-negative with no ceiling raised (offset within the profile, `tighten` when more than 5% below), and pinnable under rule 6. One commit per kept cut. | Issue "each cut ships only if the boot report shows it pays … reducing instruction load"; the gate's raise control (only lowering is unlabelled); agent-helpers rule 6; #432 D9 | Shipping all five as listed. Judging only after deploy: a cut would ship before anyone knew whether it pays |
| D6 | Cut 1: the whole-package read only for an unreviewed first entry. from-issue's Phase 6 passes sdd the literal token `--reviewed`. A reviewed or resumed run reads the root's header and the current `<plan stem>.tasks/task-<N>.md` before each dispatch. No pack field. | REVIEW-CONTRACT: the Phase-5 reviewer reads the root and every member; baseline cost is 26.5k mean in delegated Phase-6 entries; the `--auto` literal-token precedent; the pack already names the plan and the task | A pack `task_file` field: a risk-path change for a path the layout already derives. Keeping the scan on first entry: that scan is the cost |
| D7 | Cut 2: dispatchers that carry a pack name from-issue's `resume-pack.md` by absolute path as the entry, in place of the Skill invocation, with the rule stated once in `### Resume pack`. Verified: read the index and its phase's sections. Failed: load the whole skill. The read list stays in SKILL.md's index. | #265's design (a verified pack reads only its phase's sections); REVIEW-CONTRACT's by-path hand-over precedent; zero-headroom ceilings (controller conditional 144 bytes); closure and raise rules forbid a new document | A new RESUME.md or a split SKILL.md: a model change needing the raise label. Moving the read list into `resume-pack.md`: breaches the controller's conditional ceiling. A pack-carried section map: a risk-path change against #265's facts-only pack. A ship-issue entry: 1 of 43 boots |
| D8 | Cut 3: the index's verified-pack reads skip AUTO.md's `When *not* to auto-resolve` in Phases 6–7, read only the route's section of `delegated-owner.md`, and read `ship-handoff.md` only once Phase 7 (or a generic delegate's handoff build) starts. | AUTO.md: `When *not*` covers Phase 0 stops, the fog gate and Phase 5 findings; delegated-owner.md's prompt line selects one section; ship-handoff.md is Phase 7's; baseline ≈2.1k per boot | Section text inside the pack: the 4,096-byte bound, and it would duplicate skill text |
| D9 | Cut 4 is not built. A `resume_task` resume (19 of 43) could skip only Setup's gate subsections (≈1.5k tokens), and `finish_phase` is 2 of 43, so the projection is ≈0.7k, under the floor. | D5's floor; the 2026-10-26 `next_action` mix; sdd's task loop, tiers and finish are needed by every resume | Reading sdd by sections: a second Skill-tool bypass for under 1k |
| D10 | Cut 5 ships no re-read rule. An English rule cannot be pinned, and its main sources (persisted read-backs of whole-package reads, repeated skill-file navigation) go with cuts 1–3. The `rereads` bucket measures what remains. `--help` stays #432's. | agent-helpers rule 6 (no new phrase pins); the issue's "kept cuts are pinned"; baseline re-reads are a long tail at ≈2.3k | A global or resume-entry "read once" sentence: unverifiable, and it costs bytes in zero-headroom files |
| D11 | Projected fall ≈15.5k (cut 1 ≈10.6k, cut 2 ≈2.9k, cut 3 ≈2.1k), below the issue's 25k. Each cut ships because it pays, and the post-deploy evidence decides the criterion. No cut beyond the issue's five. | Section sizes a resumed owner must still read (from-issue's common procedures ≈20k characters); the issue's estimate assumed a 2.5k-token entry | Widening scope to harness listings or the owner object, or raising the budget to cut deeper: outside the issue and against its no-raise decision |
| D12 | The evidence hold, like #432's. The tool's own baseline report is recorded before deploy. The window runs from the deploy until 20 or more fresh boots, 5 or more per phase group. Met means the baseline mean of B without schemas, minus the post-deploy group means reweighted to the baseline mix, is at least 25,000. | #432 held with `needs-verification`; ship-issue's hold path for `unmet`/`human_pending` rows; B differs by phase group (≈79k vs ≈100k), so mix shifts bias a raw mean | Pre-merge eval-8 trials: $40 a trial for 1–2 fresh boots. Closing on merge: the criterion would go unmeasured |
| D13 | The sweep is re-run before merge and its threshold stated (200k expected, since boots are not yet cut). It is re-run at the post-deploy measurement, and only a lower arm that keeps against 200k is set, in a follow-up commit that cites #448. | Issue "re-run #432's replay sweep and retune … if a lower value now wins"; #432 D8 keep rule; the sweep's `boot=slim` arm | Modelling the new B inside the replay: changes #432's model, out of scope |
| D14 | `--report boot` takes the owner report's window flags plus `--projects-dir`, `--top` and `--format`, and refuses `--project`, `--artifacts`, non-claude `--strata`, `--policy`, `--sweep`, `--eval-results`/`--eval` and `--context-threshold` (exit 2). JSON is `agent-boot-report` v1. | The `--report owners` and `--report cache` flag-gating precedent | Eval-trial grouping for boots: no caller needs it (YAGNI) |
