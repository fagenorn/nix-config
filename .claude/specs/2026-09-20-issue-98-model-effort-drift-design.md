# Issue 98 — model/effort drift and scheduling telemetry design

## Problem

The model matrix declares which role, model tier, effort tier, and prerequisites each dispatch should use. The cost reporter records model, effort, and agent-type counters, but those aggregates do not prove which request produced which execution. Joining them would manufacture role-level evidence. Codex `turn_context` says how a turn was configured; it is not per-turn proof of the model and effort that executed. The app-server thread model and effort have the same limitation.

The reporter's time window is also unsuitable for drift claims. `--days` selects files by modification time and accounts every usage record in each selected file. Calling that an event-time cohort would misstate the existing contract. Scheduling has still less coverage: the current record has no authoritative worker-slot claims, spawn-capacity rejections, waits, follow-ups, or wait-token cohort.

Operators need a machine-readable answer that separates three conclusions:

- a fully covered execution conformed to its declaration;
- authoritative execution evidence proves routing drift;
- the sources, baseline, or catalog cannot support either conclusion.

They also need scheduling observations without turning cache reads, synthetic fixtures, or missing host events into claims about waste, billing, savings, or utilization.

## Solution

Extend the existing `agent-cost-record` with an independently versioned `execution_telemetry` subdocument and add a pure drift reporter. The revised producer always emits the subdocument; legacy schema-v1 records without it remain valid cost evidence but are inconclusive drift evidence. The outer cost record remains schema version 1, so the gate-bundle consumer and #97 fixtures continue to work. The existing record digest covers the new subdocument.

The producer remains the only component that reads transcript or rollout sources. It correlates exact request/result/child identities where the source supplies them, reduces raw events to bounded aggregate observations, records why any required link is missing, and applies a separate half-open event-time cohort. It does not promote run-level counters into role observations.

The reporter consumes three structured documents: one cost record, one validated model matrix, and one strict baseline/catalog. It never opens source transcripts. It validates requested routing against the matrix, concrete host/model/effort observations against the catalog, and identity/freshness against the baseline. It emits one deterministic `agent-model-drift-report` JSON document.

Terms in this design have narrow meanings:

- **Declaration** is a role or dispatch contract in the validated matrix.
- **Requested** is a value carried by the exact launch request paired to an execution.
- **Configured** is source metadata such as Codex `turn_context`; it may explain a request but never satisfies observed-execution coverage.
- **Observed** is host/model/effort carried by an execution record and paired to the exact request. Source location or aggregate equality is insufficient.
- **Baseline** is a time-bounded declaration snapshot and concrete model catalog, not an empirical performance average.
- **Routing drift** is a proven violation of a declaration. **Scheduling telemetry** describes admission and waiting independently and has no routing effect.

## Decisions

### Producer contract

`execution_telemetry` has `schema_version: 1`, a producer identity, an event window, source coverage, and run entries keyed by the existing `run_id`. The producer identity names its collector version and every harness/runtime version actually supported by source evidence; absent version evidence is explicit. The event window is `[start, end)` in RFC 3339 UTC.

Two JSON-only CLI options, `--events-since` and `--events-before`, must appear together. With them, telemetry discovery examines all source files and selects individual routing and scheduling events by their timestamps; the accounting path still uses `--days`, file mtime, and whole selected files unchanged. Without the pair, the additive subdocument is emitted with an unbounded event window and cannot support a conforming drift verdict. Invalid bounds or `start >= end` are usage errors.

Each run contains `routing` and `scheduling` objects. Routing observations are sorted aggregates over the exact tuple below; `count`, first event time, and last event time bound their size without exposing request, response, thread, or agent identifiers.

```json
{
  "declaration": {
    "dispatch_id": "sdd-scoped-task-rereview",
    "role": "reviewer-lite",
    "authority": "structured-dispatch|runtime-agent-type|unknown"
  },
  "requested": {"host": "claude", "model": "sonnet", "effort": "medium"},
  "configured": {"host": null, "model": null, "effort": null},
  "observed": {
    "host": "claude",
    "model": "claude-sonnet-5-20260901",
    "effort": "medium",
    "authority": "assistant-execution"
  },
  "escalation": null,
  "count": 2,
  "first_event_at": "2026-09-20T10:00:00Z",
  "last_event_at": "2026-09-20T10:03:00Z"
}
```

Every nullable field has coverage alongside the observations. Coverage uses `full`, `partial`, or `none`, counts eligible and paired events, and carries sorted reason counts from this closed set: `timestamp_missing`, `request_missing`, `result_missing`, `child_missing`, `dispatch_missing`, `role_ambiguous`, `execution_model_missing`, `execution_effort_missing`, `runtime_version_missing`, `source_unsupported`, and `cohort_incomplete`. Zero is legal only under `full`; `partial` and `none` project an unavailable metric as `null`. A runtime agent type may name a role only when the source value is itself that canonical role and maps to one matrix role. Shared types such as `general-purpose`, `reviewer`, and `mechanic` do not resolve ambiguous roles. A structured dispatch id is authoritative only when the runtime carried it on that exact request; the producer does not scrape prose prompts to invent one. Historical aggregate counters remain outside routing observations.

Claude assistant execution records may supply observed model/effort after exact launch-to-child correlation. Codex `turn_context` populates `configured` only. A Codex rollout proves the host executed and can retain its requested/configured values, but model and effort stay unobserved until an execution source carries them. App-server thread fields are not ingested as observed values.

Scheduling has independent per-metric coverage and nullable values for spawn attempts, capacity rejections, waits, follow-ups, wait input tokens, covered input tokens, slot capacity-seconds, and claimed slot-seconds. The producer emits numerators and denominators, not conclusions. A wait-token share is derivable only when both token counts are fully measured over the same response cohort; occupancy is derivable only when both slot values cover the complete event window. Current sources may legitimately report unsupported fields as `null` with named reasons. Synthetic scheduler fixtures prove behavior only; they are never cited by the design or report as production measurements.

PR 156's Claude message deduplication, Codex modern-response identity selection, legacy cumulative handling, cross-file deduplication, accounting coverage, source precedence, cost basis, run attribution, and null projection remain unchanged. Routing correlation is an additional pass and must not alter token totals, cost totals, existing counters, or text-mode bytes.

### Declaration baseline and catalog

The drift reporter loads the existing matrix through its validator module rather than reimplementing its closed roles, dispatches, reviewer-lite prerequisites, or explicit model/effort checks. A baseline document has `schema_version: 1`, `kind: "agent-model-baseline"`, a canonical content digest, capture time, `[valid_from, valid_before)`, the exact matrix digest, producer schema version, harness/runtime versions, and `model_catalog_version`.

The baseline maps every matrix dispatch to its permitted execution host and maps each declared model and effort tier, per host, to disjoint `allowed` and `prohibited` concrete values. It does not duplicate role or dispatch selections. Every concrete model or effort present in the input observations must occur in exactly one classification. An unclassified value makes the report inconclusive; a prohibited value proves drift. Host aliases and cross-host model ordering are forbidden.

The report takes an explicit `--now` RFC 3339 UTC value. A baseline captured in the future, expired at `--now`, whose validity does not contain the telemetry window, or whose matrix/producer/harness/runtime/catalog identity does not match is inconclusive and suppresses conformance. A mismatched concrete host, explicitly prohibited model, or explicitly prohibited effort is drift. Missing identity evidence is inconclusive rather than a mismatch.

Requested role, model, and effort are checked against the matrix before observed values are checked against the catalog. An authoritative canonical role is sufficient for role-level conformance when its charter has no prerequisite-sensitive ambiguity; a carried dispatch id must also match its matrix row. Dispatch evidence is mandatory for reviewer-lite and escalation observations because their legality depends on prerequisites or lineage. A same-request hot-model substitution is drift even when described as an escalation. A valid escalation is a new declared target dispatch plus structured lineage containing its source dispatch and a baseline-allowed reason code. Missing, unknown, or out-of-scope escalation lineage is drift. Cheap re-review and bounded lane verification therefore remain `reviewer-lite`; first-pass and whole-branch work remain their declared reviewer roles, regardless of diff size.

### Report, findings, and exits

The report contains `schema_version: 1`, `kind: "agent-model-drift-report"`, evaluated time, input digests, `state`, `routing`, `scheduling`, and `context`. Routing carries deterministic comparison rows as well as findings. Each row retains its declaration, requested and observed host/model/effort, coverage, count, and structured escalation source/target/reason so a conforming execution is inspectable without exposing correlation identifiers. Requested host is checked against the same baseline dispatch-host declaration as observed host.

Findings are sorted objects with a closed code, run id, dispatch/role when known, and count; they contain no prompts or source identifiers. The closed inconclusive codes are `WINDOW_UNBOUNDED`, `WINDOW_OUTSIDE_BASELINE`, `BASELINE_FUTURE`, `BASELINE_STALE`, `IDENTITY_MISSING`, `IDENTITY_MISMATCH`, `ROUTING_COVERAGE_MISSING`, `DISPATCH_REQUIRED`, `ROLE_AMBIGUOUS`, `EXECUTION_MODEL_MISSING`, `EXECUTION_EFFORT_MISSING`, `MODEL_UNCLASSIFIED`, and `EFFORT_UNCLASSIFIED`. The closed drift codes are `REQUEST_DECLARATION_MISMATCH`, `OBSERVED_HOST_PROHIBITED`, `OBSERVED_MODEL_PROHIBITED`, `OBSERVED_EFFORT_PROHIBITED`, and `ESCALATION_INVALID`. Baseline validity and coverage findings are therefore distinct from proven drift findings.

Routing state precedence is:

1. `drifted` when any authoritative observation violates its request, matrix declaration, host permission, catalog prohibition, or escalation contract, even if other observations lack coverage;
2. `inconclusive` when there is no proven drift but the event window, baseline identity/freshness, dispatch/role pairing, execution model/effort, or catalog classification is incomplete;
3. `conforming` only when the baseline is valid and fresh and every eligible routing event is fully paired and allowed.

Scheduling reports `measured`, `partial`, or `unmeasured` separately. Context reports cache-read share only when the structured accounting totals provide non-null `cache_read` and positive `input_total`, using `cache_read / input_total`; otherwise the ratio is null with unavailable coverage. Neither section changes routing state, and neither has a `waste`, `cheap`, `useful`, `savings`, or billing verdict. The CLI exits 0 only for `conforming`, 3 for `drifted` or `inconclusive`, and 2 for unreadable, malformed, duplicate-key, unsupported-version, unknown-field, or wrong-type input. A valid legacy schema-v1 cost record without `execution_telemetry` exits 3 with missing-coverage and missing-identity findings, unmeasured scheduling, and any independently available context. Valid states always emit one report on stdout; tool failures emit diagnostics on stderr and no report.

### Change boundary

The implementation is five task-aligned, independently reviewable slices:

1. additive producer routing telemetry and event-time extraction, preserving the accounting projection;
2. producer scheduling metrics plus range-agreement and accounting regression gates;
3. the strict current/legacy record decoder, baseline loader, and lifecycle report shell;
4. routing comparison rows and declaration, execution, classification, and escalation evaluation;
5. scheduling/context projection, final report integration, and repository gate wiring.

Production-shaped CLI fixtures live with the slice they prove. The first two slices exercise the producer boundary; the last three exercise the reporter boundary and retain the existing matrix validator as the declaration oracle.

The consumer and its tests are new siblings. The current matrix declarations and current validator assertions stay intact. In particular, issue 98 does not remove retired bridge entries, legacy resolver references, or release-evaluation gates covered by issue 100's pending approval; any later overlap is reconciled after issue 100 lands.

## Test seams

The producer is tested at its existing `main(argv)` JSON boundary with temporary Claude/Codex trees. One fixture proves a fully paired conforming execution and one a hotter-than-declared execution; other fixtures prove event-time exclusion despite recent file mtime, configuration-only Codex evidence, missing role pairing, runtime/model mismatch, missing timestamps, and null-versus-zero scheduling coverage. Existing duplicate-response, legacy-reset, attribution, cost, digest, empty-window, and text-byte tests remain the accounting oracle.

The consumer is tested only at its `main(argv)` boundary with strict temporary matrix, baseline, and record documents. Required cases are conforming, requested/observed drift, prohibited and unclassified effort, stale/future/incompatible baseline, missing coverage from aggregate-only records, host/model mismatch, valid escalation, missing/out-of-scope escalation reason, scheduling absent versus measured zero, and deterministic sorted findings. Each case asserts both stdout shape and exit code; malformed documents assert exit 2 and empty stdout.

The existing matrix validator CLI remains the declaration seam. Its tests continue proving every dispatch carries explicit model/effort and that reviewer-lite prerequisites cannot stand in for first-pass or whole-branch review. No test reaches transcript parser helpers or evaluator internals when the two CLI seams expose the behavior.

## Out of scope

- Rejecting or rewriting a dispatch at launch time, or enforcing scheduler admission.
- Parsing transcripts, prompts, or app-server state in the drift consumer.
- Backfilling role, dispatch, model, effort, or scheduling facts from separate aggregate counters.
- Treating Codex turn/thread configuration as observed execution telemetry.
- Changing cost accounting, pricing, billing interpretation, token deduplication, text output, cache semantics, or claiming savings.
- Calling cache-read share evidence that polling is cheap or useful.
- Treating fixture replay as production utilization or historical source coverage.
- Defining a cross-provider quality or price ordering for model names.
- Removing or rewriting matrix declarations and gates owned by issue 100.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Keep `agent-cost-record` at v1 and add a versioned `execution_telemetry` subdocument; make the new reporter a pure consumer of the record, matrix, and baseline. | #97 consumers require schema v1; issue 98 and the preparation require a versioned producer extension with no consumer transcript mining. | Bump or replace the outer record, or let the consumer reopen transcripts; either breaks existing evidence or creates a second parser. |
| D2 | Treat only exact request-to-execution evidence as observed, retain Codex turn/thread values as configured, and select telemetry by an explicit event-time window independent of `--days`. | Current counters are unpaired; current `--days` is file-mtime/whole-file; the truthful-states rule forbids relabelling either. | Join run aggregates or rename the existing window; both claim evidence the sources do not carry. |
| D3 | Bind a baseline to matrix, producer, harness/runtime, catalog version, and validity interval; classify every encountered concrete model/effort as allowed or prohibited per host. | The issue requires versioned fresh baselines and every observed effort to be declared or prohibited; model names are not cross-host ordered. | Accept stale baselines, wildcard unknown tiers, or compare provider names by a global hotness order; all can silently certify drift or conformance. |
| D4 | Use `drifted` over `inconclusive` over `conforming`, with exits 0/3/2 for conforming/nonconforming/tool-failure. | Proven violations remain true despite unrelated gaps; artifact and evidence tools already distinguish a valid negative outcome from tool failure. | Let missing coverage erase proven drift, or collapse malformed input and measured nonconformance into one exit. |
| D5 | Report scheduling coverage and raw cohort-compatible numerators separately from routing; null unsupported metrics and derive no waste/savings verdict. | The audit separates scheduling waste from routing drift and rejects cache-read usefulness claims; current sources lack authoritative occupancy. | Convert missing events to zero or use cache reads as a waiting proxy; both create production claims from absence or unrelated counters. |
| D6 | Validate each execution at its strongest authoritative declaration: canonical role, plus exact dispatch where carried or prerequisite-sensitive; represent escalation as a new declared dispatch with reasoned lineage. | The matrix keeps reviewer-lite bounded and requires explicit effort at every dispatch; cheap roles must not absorb first-pass or whole-branch work. | Infer a cheap role from diff size or bless an in-place hot-model substitution as escalation; either bypasses the declared charter. |
| D7 | Preserve PR 156 accounting, source precedence, deduplication, attribution, nulls, and text bytes while adding a separate correlation pass. | The accepted #97 design and tests are the accounting authority; issue 98 is report-only telemetry. | Rebuild token collection around routing events; it risks reopening settled accounting defects without helping drift semantics. |
| D8 | Add new producer/report seams and retain the current matrix and gates until issue 100 is approved and merged. | The caller's coordination constraint identifies issue 100's denied, unmerged deletion and release-eval scope. | Fold those removals into issue 98; that bypasses their approval and creates a conflict-prone mixed change. |
| D9 | Test the producer and consumer at their CLI/main boundaries and retain the matrix validator as the declaration seam. | The bar requires observable, production-shaped tests; both public seams expose schema, behavior, and exits without freezing helpers. | Unit-test parser/evaluator helpers as the primary contract; those tests can stay green while the emitted report or exit behavior breaks. |
| D10 | Emit deterministic routing comparison rows containing declaration, requested and observed host/model/effort, coverage, count, and escalation lineage/reason; validate requested host as part of request-to-declaration conformance. | Issue 98 requires an inspectable observed-versus-declared report, including conforming and valid-escalation cases that produce no finding. | Emit findings only or validate only observed host; either hides compliant evidence or lets an invalid request escape. |
| D11 | Add context-only cache-read share as `cache_read / input_total`, null when either input is unavailable or the denominator is zero, with no effect on routing, scheduling, or exit status. | The issue requires high cache-read ratio as context while rejecting cheapness/usefulness and savings claims; the cost record already supplies structured totals. | Omit the ratio or infer a scheduling verdict from it; the first misses the acceptance criterion and the second overstates the evidence. |
| D12 | Accept a valid legacy schema-v1 cost record without `execution_telemetry` as inconclusive drift evidence with missing coverage/identity and unmeasured scheduling. | The additive producer contract preserves historical v1 validity and unsupported historical facts remain unknown. | Treat the missing additive member as malformed input; that retroactively invalidates accepted cost evidence. |
| D13 | Split the consumer into CLI, strict-schema, routing, and scheduling/context sibling modules with parallel bounded test files. | Cumulative SDD review packages preserve each handwritten file diff whole and cap a member at 65,536 bytes, so reviewability must be designed before implementation. | Grow one reporter and one test file across later tasks or path-filter evidence; neither can repair an oversized cumulative file diff. |
