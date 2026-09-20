# Model/Effort Drift Telemetry Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Add a versioned, report-only observed-versus-declared routing and scheduling report whose only runtime evidence is the structured telemetry emitted by `scripts/agent-costs.py`.

**Architecture:** `agent-costs.py` remains the sole transcript/rollout reader and adds a separately versioned `execution_telemetry` projection selected by event timestamps without changing cost accounting. The consumer is split into bounded siblings: `agent-model-drift.py` owns CLI/I/O, `agent-model-drift-schema.py` strictly decodes the record/matrix/baseline, `agent-model-drift-routing.py` produces comparisons/findings, and `agent-model-drift-scheduling.py` projects scheduling plus context. The matrix declarations and issue-100-owned gates remain untouched (D1, D2, D5, D7, D8, D13).

**Tech stack:** Python 3 standard library (`argparse`, `datetime`, `hashlib`, `importlib`, `json`, `pathlib`), `unittest`, the existing model-matrix validator, Just, and Nix evaluation.

## Global Constraints

- The authoritative design is `.claude/specs/2026-09-20-issue-98-model-effort-drift-design.md`; cite D1–D13 and do not duplicate its decision-ledger rationale.
- The outer cost record stays `schema_version: 1`; `execution_telemetry.schema_version` is `1`; the drift report and baseline each use `schema_version: 1` and their design-specified `kind` values (D1).
- Only `scripts/agent-costs.py` may open Claude transcripts or Codex rollouts. `scripts/agent-model-drift.py` accepts exactly a structured cost record, a validated repository matrix, a strict baseline/catalog, and explicit `--now`; it never opens runtime sources (D1, D2).
- `--events-since` and `--events-before` are JSON-only, RFC 3339 UTC, paired options. Their half-open `[start, end)` cohort selects individual telemetry events across all source files. `--days` continues selecting cost-accounting files by mtime and continues accounting the whole selected file (D2, D7).
- Preserve PR 156 accounting: Claude message deduplication, Codex modern-response identity selection, legacy cumulative handling, cross-file deduplication, source precedence, cost basis, run attribution, accounting coverage, null projection, record digest coverage, and byte-identical text mode (D7).
- Requested and configured values are never observed execution evidence. Requested host comes only from an explicit launch field or the intrinsic target of the exact Claude `Agent`/`Task` or Codex `thread_spawn` transport; a missing/invalid or conflicting explicit host stays null with coverage loss and is never backfilled. Only an exact request/result/child pairing may produce a Claude observed model/effort. Codex `turn_context` remains configured-only; a rollout may prove host execution while leaving model and effort null (D2).
- Coverage states are exactly `full | partial | none`; reason codes are exactly `timestamp_missing | request_missing | request_host_missing | request_host_conflict | result_missing | child_missing | dispatch_missing | role_ambiguous | execution_model_missing | execution_effort_missing | runtime_version_missing | source_unsupported | cohort_incomplete`. Zero is available only with `full`; every metric with `partial` or `none` is `null`. Top-level coverage is the validated merge of run contributions plus explicit contributions for selected sources with no run (D2, D5).
- Baselines bind their canonical digest, capture time, `[valid_from, valid_before)`, matrix digest, producer schema version, harness/runtime versions, and model-catalog version. Host-specific model/effort `allowed` and `prohibited` sets are disjoint; host aliases and cross-provider ordering are forbidden (D3).
- Routing state precedence is exactly `drifted`, then `inconclusive`, then `conforming`; valid nonconformance exits `3`, conformance exits `0`, and input/tool failure exits `2` with no report on stdout (D4).
- Scheduling state is independently `measured | partial | unmeasured` and never changes routing state. Neither source nor report may emit a `waste`, `cheap`, `useful`, `savings`, billing, or utilization verdict (D5).
- Routing emits deterministic comparison rows with declaration, requested and observed host/model/effort, coverage, count, and escalation source/target/reason. Requested host is validated against the permitted dispatch host before observed values are classified (D10).
- Context reports only `cache_read / input_total` from structured accounting totals. A missing/null input or zero denominator yields null/unavailable; the ratio never changes routing, scheduling, findings, or exit status (D11).
- A valid legacy schema-v1 cost record without `execution_telemetry` remains accepted cost evidence and produces an inconclusive exit-3 drift report with missing coverage/identity and unmeasured scheduling (D12).
- Canonical role evidence is accepted only where the matrix makes it unambiguous. Reviewer-lite and escalation observations require an exact dispatch. A valid escalation is a new declared target dispatch with structured source-dispatch lineage and a baseline-allowed reason (D6).
- The closed inconclusive and drift finding codes are exactly those in the design. Findings contain only code, run id, dispatch, role, and count; they contain no prompt, source path, request id, response id, thread id, tool id, or agent id (D4).
- The complete implementation owns exactly eleven product/test files: `scripts/agent-costs.py`, `tests/test_agent_costs.py`, `scripts/agent-model-drift.py`, `scripts/agent-model-drift-schema.py`, `scripts/agent-model-drift-routing.py`, `scripts/agent-model-drift-scheduling.py`, `tests/agent_model_drift_test_support.py`, `tests/test_agent_model_drift_schema.py`, `tests/test_agent_model_drift_routing.py`, `tests/test_agent_model_drift_scheduling.py`, and `justfile` (D13). Do not modify `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/scripts/agent-model-matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, the legacy resolver test-runner reference, or release-evaluation gates (D8).
- Python standard library only. Closed schema and vocabulary dispatches fail loud; duplicate JSON keys, unknown fields, unsupported versions, wrong types, and malformed times exit `2` (the bar, *Fail loud*).
- Tests use production-shaped temporary files and assert observable CLI behavior. No test reaches transcript parser helpers or evaluator internals when the producer/reporter `main(argv)` seams expose the behavior (D9).
- At SDD entry, pin immutable `DELIVERY_BASE` to the full SHA from `git merge-base HEAD origin/main`; before the first implementer pin initial `DELIVERY_HEAD` to full `git rev-parse HEAD` and pass the cumulative gate. Before each implementer pin that task's `BASE` to full `git rev-parse HEAD`; after its commit/fixes pin task `HEAD`, and after acceptance repin cumulative `DELIVERY_HEAD`. Task review uses the complete `BASE..HEAD`; every cumulative gate and both final review axes use the complete `DELIVERY_BASE..DELIVERY_HEAD`.
- Review-package evidence is never path-filtered. A task's `Files:` block declares expected scope so unexpected files become review findings; it never removes changed lines from evidence.
- Before any reviewer dispatch: retain the review-package producer's exact stdout; pass it through `artifact-budget validate-report --boundary producer` before decoding; require `state: complete`; independently run `artifact-budget check --kind review-package --root <reported-root> --format json`; require all four metrics to agree; require manifest coverage complete over every changed file; and require full `range.base`/`range.head` to equal the intended full SHAs. Exit 2/3, malformed output, incomplete coverage, metric disagreement, or stale/ranged-short identity stops dispatch.
- After each task commit, run separate requirements/compliance and code-quality reviews of `BASE..HEAD`, plus the cumulative package gate over `DELIVERY_BASE..DELIVERY_HEAD`. After Task 5, run separate final conformance and final correctness reviews over `DELIVERY_BASE..DELIVERY_HEAD`; one result cannot stand in for the other.
- Every commit is signed and ends with `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- **S1 — producer `main(argv)` in process.** `tests/test_agent_costs.py` builds temporary Claude/Codex trees, captures stdout/stderr and exit status, and parses only the emitted `agent-cost-record` JSON. It also retains the existing text golden as the byte oracle (D9).
- **S2 — reporter `main(argv)` in process.** `tests/agent_model_drift_test_support.py` owns production-shaped temporary record, baseline, and canonical-layout matrix builders. `test_agent_model_drift_schema.py`, `test_agent_model_drift_routing.py`, and `test_agent_model_drift_scheduling.py` invoke only `main(argv)` and assert stdout plus exit status; malformed inputs assert exit `2` and empty stdout (D9, D13).
- **S3 — existing matrix validator CLI/module.** The reporter calls the repository validator; `test_agent_model_matrix.py` remains the declaration oracle and is run unchanged (D8, D9).
- **S4 — repository gates.** `just agent-workflow-tests` runs producer plus all three consumer suites and the unchanged matrix suite; `just build` checks Nix publication/evaluation. A `DELIVERY_BASE`-scoped path gate proves issue-100-owned files did not change.

## Delivery estimate and boundaries

- Active review-package caps are 65,536 bytes per handwritten member/file diff and 524,288 bytes aggregate. Estimated cumulative handwritten diffs: `scripts/agent-costs.py` 30–45 KiB; `tests/test_agent_costs.py` 35–50 KiB; CLI 12–20 KiB; schema module 28–42 KiB; routing module 22–34 KiB; scheduling/context module 16–26 KiB; shared test support 16–24 KiB; each of the three consumer test files 20–38 KiB; `justfile` under 2 KiB. Every estimate is below the member cap.
- Estimated implementation aggregate is 250–360 KiB. Tracked design/plan overhead is about 129 KiB; generated manifest/index/shard overhead adds 10–20 KiB. The complete estimate is 389–509 KiB across about 18 files, below the 524,288-byte cap. Estimates do not permit either cap to be exceeded.
- Task 1 is an independently reviewable producer-routing slice. Task 2 is the independent scheduling/range-agreement slice and must land before consumer review begins.
- Tasks 3–5 are cumulative consumer slices in separate module/test files: strict inputs/baseline lifecycle, routing comparisons/verdicts, then scheduling/context/report integration. Each receives its own full-lane complete-range package and test cycle; no slice raises a cap, path-filters evidence, or grows a later concern into an earlier file.
- Before dispatching each task, compare current cumulative per-file and aggregate review-package metrics with these caps. If `member_bytes` would exceed 65,536, stop with `decompose_required` and split that implementation or test responsibility into another cohesive sibling file before adding code; splitting commits or test classes inside the same file is not remediation. If `aggregate_bytes` would exceed 524,288, preserve completed work, stop further dispatch, and revise the remaining task boundary into an independently deliverable range whose complete cumulative review package fits before resuming; adding files or splitting commits cannot reduce cumulative aggregate bytes.
- Issue 100 reconciliation is a later delivery after its approval and merge. This plan adds no deletion or correction from that issue.

## Task index

Task 1 — Emit event-time routing telemetry while preserving accounting — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-1.md](2026-09-20-issue-98-model-effort-drift.tasks/task-1.md)

Task 2 — Add independent scheduling metrics and producer regression gates — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-2.md](2026-09-20-issue-98-model-effort-drift.tasks/task-2.md)

Task 3 — Strictly decode current/legacy records, validate baselines, and report lifecycle incompatibility — `scripts/agent-model-drift.py`, `scripts/agent-model-drift-schema.py`, `tests/agent_model_drift_test_support.py`, `tests/test_agent_model_drift_schema.py` — full — [task-3.md](2026-09-20-issue-98-model-effort-drift.tasks/task-3.md)

Task 4 — Emit comparisons and evaluate declarations, execution, and escalation — `scripts/agent-model-drift.py`, `scripts/agent-model-drift-routing.py`, `tests/test_agent_model_drift_routing.py` — full — [task-4.md](2026-09-20-issue-98-model-effort-drift.tasks/task-4.md)

Task 5 — Project scheduling/context, wire repository gates, and prove the complete boundary — `scripts/agent-model-drift.py`, `scripts/agent-model-drift-scheduling.py`, `tests/test_agent_model_drift_scheduling.py`, `justfile` — full — [task-5.md](2026-09-20-issue-98-model-effort-drift.tasks/task-5.md)

## Decisions

- D1, D2, and D7 govern Tasks 1–2: additive versioning, producer-owned evidence, separate event-time selection, and unchanged accounting.
- D5 governs Tasks 2 and 5: scheduling coverage, compatible numerators/denominators, and no waste or savings verdict.
- D3 governs Task 3: strict baseline identity, validity, freshness, catalog classification, and host-specific values.
- D4 governs Tasks 3–5: finding vocabularies, deterministic precedence, report output, and exits.
- D6 governs Task 4: strongest authoritative declaration and structured escalation lineage.
- D8 governs every task's closed path set and deferred issue-100 reconciliation.
- D9 governs every task's CLI-level, production-shaped test contract.
- D10 governs Task 4's inspectable comparison rows and requested-host validation.
- D11 governs Task 5's context-only cache-read ratio and null denominator behavior.
- D12 governs Task 3's legacy schema-v1 compatibility path.
- D13 governs Tasks 3–5's bounded consumer/module and test-file decomposition.

## Plan review provenance

Independent Phase-5 reviewer `/root/issue_98/issue98_plan_review`, requested `gpt-5.6-sol` / `high`, observed execution telemetry `unknown`, reviewed the complete six-member package from `6d4b7a49dd3a44c079c8310e902a86665a6805f0` through `afa1d975b2400c930fd325519fe008bf46a9ce91`.

**7 accepted / 0 rejected / 0 deferred.** Accepted: correct task/delivery SHA identities; forbid path-filtered evidence and spell the producer/validator/checker/range gate; pre-decompose cumulative files for review caps; add comparison rows and requested-host validation (D10); add context-only cache-read ratio (D11); accept legacy v1 without telemetry as inconclusive (D12); and expand malformed/incompatible CLI fixtures. The module/test split is D13.

Independent scoped re-reviewer `/root/issue_98/issue98_plan_rereview`, requested `gpt-5.6-sol` / `high`, observed execution telemetry `unknown`, reviewed all six members from `afa1d975b2400c930fd325519fe008bf46a9ce91` through `d9f941c0af1047defc2e7adbe07a13efeb2f3c0b` and confirmed all seven original findings resolved.

**3 accepted / 0 rejected / 0 deferred.** Accepted: restore exact report identity/time/input-digest assertions plus corrupted record/baseline-id cases; construct current and legacy consumer fixtures through the real producer projection and preserve complete accounting members when varying cache counters; and align the design boundary with the five task slices. These restore already-decided contracts and introduce no new decision-ledger row.

Final scoped reviewer `/root/issue_98/issue98_plan_final_review` (`gpt-5.6-sol` / `high`; observed telemetry `unknown`) read all six members over `afa1d975b2400c930fd325519fe008bf46a9ce91..4aaaff6f7763c122fb02a5630c752d4314c2dafc` and confirmed all nine prior findings resolved.

**4 accepted / 0 rejected / 0 deferred.** Revised D2 for request-host provenance and D5 for zero-run source coverage; made cache fixtures component-derived; separated `member_bytes` file splitting from the `aggregate_bytes` independent-delivery stop.

---
