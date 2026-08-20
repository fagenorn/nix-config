# Certify the deployed direct autonomous controller budget

Issue: https://github.com/fagenorn/nix-config/issues/75

This design records the evidence protocol for the representative direct run
`direct-75-000002`. It relies on the deployed issue-74 lifecycle contract and does
not change that contract.

## Problem

The issue-74 rollover is merged and activated, but deterministic tests do not prove
that a newly started Codex process actually used the installed direct-owner route,
persisted `delegate` at Phase 5, transferred implementation to a fresh owner, and
kept each lifecycle controller at or below 150,000 input tokens. Certification must bind
those claims to immutable deployment, session, Git, and ledger identities without
turning mutable transcripts or cumulative token totals into evidence.

This run also has a sequencing constraint. Its terminal result is written only
after shipping, and the issue-74 contract then requires the fresh owner and earlier
controller to relay and stop. Neither may edit a report after the terminal write.
A report committed before shipping can therefore be truthful only as pending; a
separate post-terminal writer must seal the same report after both controller trace
prefixes and the ledger are final.

## Solution

Create one compact report at
`.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`.
The fresh implementation owner creates its first committed version after the
Phase-5 rollover. That version records only facts already observed and declares
the verdict `pending`, naming terminal ledger state and sealed controller metrics
as the remaining evidence. It must not predict a merge SHA, terminal result, or
final token maximum.

After the representative run reaches its durable terminal state and both
controller trace prefixes end, a narrow post-terminal certifier updates that same
file on a follow-up branch. The certifier does not reacquire the run, invoke SDD,
or call lifecycle commands that mutate state. It extracts the final facts,
re-runs every check, records immutable hashes and compact results, changes the
verdict to `certified` only when every required check passes, and commits the
final report. Missing required counters or any failed invariant produces
`unknown` or `not certified`; the issue remains unsuccessful and open.

The final report has these compact sections:

1. **Verdict and scope** — `certified`, `not certified`, or `unknown`; one-run
   claim only; the exact run, attempt, owner, worktree, ceiling, and report commit.
2. **Deployment freshness** — merged revision, base revision, merge/activation/
   process/session times, activated system store path, installed-file identities,
   and the post-activation ordering result.
3. **Lifecycle trace** — direct-owner identity, reviewed HEAD, persisted Phase-5
   `delegate`, fresh-owner identity, terminal ledger result, and role inventory.
4. **Controller input** — one row per required lifecycle controller with session
   ID, sealed rollout-log path and digest, maximum logical single-turn input,
   cached input from that same record, derived fresh input, and ceiling verdict.
5. **Pre-rollover boundary** — the reviewed Git range and structured dispatch
   inventory proving that only spec/plan artifacts changed and SDD began under
   the fresh owner.
6. **Historical comparison** — the two issue-49-era root-controller observations,
   described as context rather than a percentage or causal estimate.
7. **Reproduction matrix** — each claim, its immutable anchor, exact command or
   query, compact observed result, and pass/unknown/fail disposition.

## Decisions

### Certification states and finalization

The report uses three closed verdicts. `certified` means every required fact is
available and passes. `not certified` means an observed fact violates the contract,
including a controller above the ceiling. `unknown` means a required fact
cannot be measured, including a required controller without a usable token counter.
`pending` is permitted only in the pre-terminal committed version and is never a
final certification state.

The post-terminal certifier is an evidence writer, not another lifecycle owner. It
must begin from the merged representative-run commit, preserve the direct run's
terminal ledger bytes, and use an ordinary follow-up branch/PR. This separates the
one trace being measured from the later act of making its completed facts durable
in Git. The report identifies both commits so readers can distinguish the trace
content from its post-terminal seal.

### Controller boundary

A required lifecycle controller is a Codex session that owns the issue-level
lifecycle envelope and selects or persists phase progression for the representative
run. There are exactly two expected controllers:

- the pre-rollover direct controller, which acquires `direct-owner` and owns
  Phases 0–5; and
- the distinct delegated implementation controller, which adopts the unchanged
  envelope and owns Phases 6–7 through terminal relay.

Design/planning helpers, SDD task agents and reviewers, the fresh ship owner, and
the ledger-only bookkeeper are subordinate phase workers: they neither acquire the
direct owner nor select the issue-level continuation. The post-terminal certifier
acts after the lifecycle is terminal. The report inventories every observed session
associated with the run and states its role and inclusion decision, so an unexpected
session with controller authority cannot disappear through naming. Any third session
that actually acquires/adopts the envelope or persists phase progression becomes a
required controller and must have counters or force `unknown`.

### Per-controller input contract

Codex rollout JSONL is the counter source. For each required controller, select the
completed `token_count` record whose `last_token_usage.input_tokens` is greatest;
break a tie by the later record timestamp. That logical single-turn input is the
only value compared with the inclusive `<= 150000` ceiling. From the same record,
retain `cached_input_tokens` and derive `fresh_input_tokens = input_tokens -
cached_input_tokens`. Validate that both source fields are integers and that
`0 <= cached <= logical`; otherwise the controller is unmeasurable and certification
is `unknown`.

Do not use cumulative `total_token_usage`, independently maximize the cached or
fresh columns, add turns together, or combine controllers. Keeping the three values
from one record makes the decomposition reproducible and prevents a cached amount
from one turn being subtracted from the logical amount of another.

### Evidence anchors

The report's Git anchors are full object IDs: post-issue-74 merge
`f3fac9554761d0c3085d70bf4526cf3e7486de3e`, its base
`c780b38f613c59a7d6674dc081d9f67666054ebf`, the Phase-5 reviewed HEAD, the
representative-run merge, and the final evidence commit. Deployment is anchored by
the `/run/current-system` target and activation timestamp plus byte equality between
the installed `SKILL.md`, `AUTO.md`, and workflow-state executable and the three
tracked files at the merged revision. The base comparison must show those deployed
definitions differ from the base; it cannot claim that a historical Git tree itself
contains or lacks runtime traces.

Each controller log is named by absolute rollout path, `session_meta.id`, start
timestamp, and a byte count plus SHA-256 for the exact prefix ending with that
controller's terminal relay/task-complete record. Later conversation reuse may
append to the file but cannot change the sealed prefix. The report records the
timestamp and values of the selected token record within that prefix, not transcript
prose. The lifecycle anchor is the absolute canonical ledger state path plus its
post-terminal SHA-256 and compact run/attempt/result fields. Because
later phase progress overwrites the attempt's current `phase_action`, the Phase-5
`delegate` proof comes from the pre-rollover controller's sealed structured log and
the exact compact progress observation captured while Phase 5 was current; the final
ledger proves the same run and attempt reached terminal state.

The fresh-owner proof requires distinct session IDs, its start after the Phase-5
delegate observation, and the unchanged run/attempt/owner/worktree envelope. The
pre-rollover boundary requires the reviewed-head Git range to contain only this
design and its plan, plus a structured dispatch inventory with no SDD launch before
delegation. The pending evidence artifact is created only afterward by the fresh
owner. Product-path changes or an SDD launch under the earlier controller fail
certification.

### Historical comparison

The report rechecks the two historical rollout logs behind the issue-49-era
description and records their approximately 183k and 213k maximum logical
single-turn inputs with session IDs and hashes. It then says only whether each
observed issue-75 controller is at or below 150k and descriptively lower than those
two observations. It states that the runs differ in issue scope, runtime, and workflow,
so one trace cannot establish a universal reduction or attribute native
collaboration-wait cost. No percentage, average, aggregate, or counterfactual is
reported.

### Reproduction commands

The finalizer uses standard read-only tools and records their literal invocations
with resolved paths and SHAs in the report. The command set must cover:

- `git show`, `git diff --name-only`, `git rev-parse`, and `git cat-file` for
  revision, base, reviewed range, tracked report, and content identity;
- `readlink`, platform `stat`, `realpath`, `cmp`, and `shasum -a 256` for the
  activated generation and installed definitions;
- `jq` over `session_meta`, structured dispatch/task records, terminal task
  records, and `last_token_usage` records within each sealed rollout prefix;
- `jq` over the canonical workflow ledger for run, attempt, and terminal result,
  with the sealed controller record supplying the Phase-5 capture; and
- `git diff --name-only` plus the dispatch inventory for the pre-rollover no-SDD/
  no-product-edit boundary.

Every command is locale-independent where ordering matters and uses exact absolute
runtime paths or full Git IDs. A path alone is not an immutable claim: mutable
runtime files also carry a digest and exact covered size, while Git-contained
evidence names the containing commit.

## Test seams

1. **Deployment seam.** Re-run the installed-file comparisons, resolve the activated
   store path, and assert `merge_time <= activation_time < process/session_start`.
   Assert the base differs at the issue-74 definitions.
2. **Lifecycle seam.** Read the sealed Phase-5 observation and terminal ledger,
   require run `direct-75-000002`, attempt `1`, owner `75:1`, action `delegate` at
   Phase 5, a distinct fresh owner session, and one durable terminal result.
3. **Controller seam.** Build the complete role inventory, apply the authority rule,
   extract one maximum-logical record per required controller, validate its paired
   counters, and require every logical value not to exceed 150,000.
4. **Ownership seam.** Diff deployment merge to reviewed HEAD and inspect structured
   dispatches: before rollover, only process spec/plan paths may change and no SDD
   task may launch; the first SDD launch belongs to the fresh owner.
5. **Report seam.** From a clean checkout at the final evidence commit, run every
   reproduction row and compare the compact output. Any absent/mismatched required
   value changes the final verdict away from `certified`.

These are semantic evidence checks, not new product tests. The already-passing
`just agent-workflow-tests` result remains supporting deployment evidence; it does
not substitute for the live seams above.

## Out of scope

- Changing lifecycle code, skills, workflow-state schema, token logging, or report
  validators.
- Running another direct lifecycle trace, reacquiring the terminal run, rerunning
  activation, or letting either lifecycle controller edit after terminal relay.
- Treating phase helpers, SDD agents, ship owners, bookkeepers, or the certifier as
  controllers without evidence that they acquired/adopted the envelope or persisted
  issue-level progression.
- Copying transcripts, publishing prompt contents, retaining mutable-path claims
  without hashes, or fabricating unavailable counters.
- Combining logical, cached, and fresh input; summing controllers; reporting a
  universal percentage; or attributing native wait-loop overhead.
- Generalizing the result beyond this one direct run or retroactively certifying
  historical Markdown evidence.
- Creating a glossary, context map, or ADR tree; accepted issue-74 precedent keeps
  these lifecycle decisions in `.claude/specs`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Use one Markdown report with a truthful pre-terminal `pending` commit and a narrow post-terminal finalizer that seals the same file on a follow-up branch. | Issue 75 requires terminal and controller evidence; issue 74 requires both lifecycle owners to relay and stop after terminal; The Bar forbids future facts presented as current. | Predict terminal facts or let a lifecycle owner edit after `finish` — either fabricates evidence or violates the deployed contract; omit the pre-terminal report — leaves Phase 6 with no evidence work and no durable capture of Phase 5. |
| D2 | Count sessions by issue-level lifecycle authority: the pre-rollover direct controller and delegated implementation controller are required; inventory all associated workers and promote any unexpected session that acquires/adopts the envelope or persists progression. | Issue 74 assigns Phases 0–5 and 6–7 to exactly two owners while SDD, ship, and bookkeeper routes are subordinate; issue 75 asks for every observed controller, not every helper. | Count every helper as a controller — confuses bounded task workers with lifecycle ownership; hard-code two rows without an inventory — can hide unexpected controller churn. |
| D3 | Compare the maximum `last_token_usage.input_tokens` per controller at or below 150,000, pairing cached input from that record and deriving fresh input by subtraction; missing or invalid required counters make certification `unknown`. | Issue 75 and Phase-0 grounding define logical single-turn input as the ceiling measure, say none may exceed 150,000, and require logical/fresh/cached separation; truthful terminal states forbid treating absence as success. | Use cumulative totals, independently selected maxima, combined values, or a fallback estimate — changes the unit, breaks the decomposition, or fabricates measurement. |
| D4 | Bind deployment, sessions, and lifecycle to full Git/store/session/run identities; seal mutable log prefixes and the terminal ledger with covered size plus SHA-256; prove Phase-5 delegate from its structured log observation because later progress overwrites the current action. | Issue 16 requires deployed-path freshness; issue 74's ledger stores current progression rather than phase history; prior evidence reports use compact facts and durable paths. | Cite mutable paths alone, copy transcripts, or infer Phase 5 from the final action — weakens reproducibility, expands the report, or reads an overwritten field as history. |
| D5 | Compare descriptively with the two rechecked issue-49-era root-controller observations (~183k/~213k), with no percentage, aggregation, universal claim, or native-wait attribution. | Issue 75 expressly limits the effectiveness claim to one trace and identifies those approximate baselines; controller logs expose usage but not a causal wait-cost decomposition. | Report a percentage reduction or combined efficiency score — generalizes across unlike runs and attributes costs the evidence cannot isolate. |
| D6 | Split plan execution at the terminal boundary: the representative run's fresh owner executes and ships only the pending-report task, while a separate post-terminal certifier executes the sealing task without SDD or lifecycle commands. | D1 requires two writers separated by durable terminal state; issue 74 requires both lifecycle controllers to relay and stop after terminal; the finalizer is expressly not a lifecycle owner. | Let the representative run's SDD execute both tasks or let either controller finalize later — the former asks for evidence that cannot exist yet and the latter violates the stop contract. |
| D7 | Identify the final evidence commit from a clean checkout with a literal path-scoped Git query, while embedding the representative-run merge and all other already-existing object IDs as full values. | The report must distinguish the representative merge from its post-terminal seal, but a commit cannot embed its own object ID because that ID hashes the file bytes; D4 requires reproducible immutable anchors. | Embed a predicted or predecessor commit as the report's own commit — creates a false identity; amend repeatedly to insert the new commit — recreates the same self-reference indefinitely. |
| D8 | Resolve the final verdict in fail-first order: any observed contract violation is `not certified`; otherwise any unavailable or unmeasurable required fact is `unknown`; only a complete all-pass matrix is `certified`. | The three closed states distinguish disproven, unmeasurable, and proven claims; truthful terminal states must not hide a known breach behind a separate missing value. | Give `unknown` precedence over an observed failure — loses the stronger fact that the representative trace already violated the contract. |
