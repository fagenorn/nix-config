# Model/Effort Drift Telemetry Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Add a versioned, report-only observed-versus-declared routing and scheduling report whose only runtime evidence is the structured telemetry emitted by `scripts/agent-costs.py`.

**Architecture:** `agent-costs.py` remains the sole transcript/rollout reader and adds a separately versioned `execution_telemetry` projection selected by event timestamps without changing cost accounting. A new sibling `agent-model-drift.py` validates the existing model matrix through `agent-model-matrix.py`, strictly decodes the cost record and baseline/catalog, and emits a deterministic report with independent routing and scheduling states. The matrix declarations and issue-100-owned gates remain untouched (D1, D2, D5, D7, D8).

**Tech stack:** Python 3 standard library (`argparse`, `datetime`, `hashlib`, `importlib`, `json`, `pathlib`), `unittest`, the existing model-matrix validator, Just, and Nix evaluation.

## Global Constraints

- The authoritative design is `.claude/specs/2026-09-20-issue-98-model-effort-drift-design.md`; cite D1–D9 and do not duplicate its decision-ledger rationale.
- The outer cost record stays `schema_version: 1`; `execution_telemetry.schema_version` is `1`; the drift report and baseline each use `schema_version: 1` and their design-specified `kind` values (D1).
- Only `scripts/agent-costs.py` may open Claude transcripts or Codex rollouts. `scripts/agent-model-drift.py` accepts exactly a structured cost record, a validated repository matrix, a strict baseline/catalog, and explicit `--now`; it never opens runtime sources (D1, D2).
- `--events-since` and `--events-before` are JSON-only, RFC 3339 UTC, paired options. Their half-open `[start, end)` cohort selects individual telemetry events across all source files. `--days` continues selecting cost-accounting files by mtime and continues accounting the whole selected file (D2, D7).
- Preserve PR 156 accounting: Claude message deduplication, Codex modern-response identity selection, legacy cumulative handling, cross-file deduplication, source precedence, cost basis, run attribution, accounting coverage, null projection, record digest coverage, and byte-identical text mode (D7).
- Requested and configured values are never observed execution evidence. Only an exact request/result/child pairing may produce a Claude observed model/effort. Codex `turn_context` remains configured-only; a rollout may prove host execution while leaving model and effort null (D2).
- Coverage states are exactly `full | partial | none`; reason codes are exactly `timestamp_missing | request_missing | result_missing | child_missing | dispatch_missing | role_ambiguous | execution_model_missing | execution_effort_missing | runtime_version_missing | source_unsupported | cohort_incomplete`. Zero is available only with `full`; every metric with `partial` or `none` is `null` (D2, D5).
- Baselines bind their canonical digest, capture time, `[valid_from, valid_before)`, matrix digest, producer schema version, harness/runtime versions, and model-catalog version. Host-specific model/effort `allowed` and `prohibited` sets are disjoint; host aliases and cross-provider ordering are forbidden (D3).
- Routing state precedence is exactly `drifted`, then `inconclusive`, then `conforming`; valid nonconformance exits `3`, conformance exits `0`, and input/tool failure exits `2` with no report on stdout (D4).
- Scheduling state is independently `measured | partial | unmeasured` and never changes routing state. Neither source nor report may emit a `waste`, `cheap`, `useful`, `savings`, billing, or utilization verdict (D5).
- Canonical role evidence is accepted only where the matrix makes it unambiguous. Reviewer-lite and escalation observations require an exact dispatch. A valid escalation is a new declared target dispatch with structured source-dispatch lineage and a baseline-allowed reason (D6).
- The closed inconclusive and drift finding codes are exactly those in the design. Findings contain only code, run id, dispatch, role, and count; they contain no prompt, source path, request id, response id, thread id, tool id, or agent id (D4).
- The complete implementation owns exactly five product/test files: `scripts/agent-costs.py`, `tests/test_agent_costs.py`, `scripts/agent-model-drift.py`, `tests/test_agent_model_drift.py`, and `justfile`. Do not modify `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/scripts/agent-model-matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, the legacy resolver test-runner reference, or release-evaluation gates (D8).
- Python standard library only. Closed schema and vocabulary dispatches fail loud; duplicate JSON keys, unknown fields, unsupported versions, wrong types, and malformed times exit `2` (the bar, *Fail loud*).
- Tests use production-shaped temporary files and assert observable CLI behavior. No test reaches transcript parser helpers or evaluator internals when the producer/reporter `main(argv)` seams expose the behavior (D9).
- The execution owner supplies immutable full SHAs `BASE` (original task base) and `DELIVERY_BASE` (cumulative accepted delivery before the current task). Every review package is scoped to the current task's `Files:` paths and decoded only after package validation.
- After each task commit, the execution owner validates the scoped review package before decoding it, then runs separate requirements/compliance and code-quality reviews. After Task 5, run separate final conformance and final correctness reviews over `BASE..HEAD`; one review result cannot stand in for the other.
- Every commit is signed and ends with `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- **S1 — producer `main(argv)` in process.** `tests/test_agent_costs.py` builds temporary Claude/Codex trees, captures stdout/stderr and exit status, and parses only the emitted `agent-cost-record` JSON. It also retains the existing text golden as the byte oracle (D9).
- **S2 — reporter `main(argv)` in process.** `tests/test_agent_model_drift.py` writes strict temporary record, baseline, and canonical-layout matrix documents, invokes `main(argv)`, and asserts stdout shape plus exit status. Malformed inputs assert exit `2` and empty stdout (D9).
- **S3 — existing matrix validator CLI/module.** The reporter calls the repository validator; `test_agent_model_matrix.py` remains the declaration oracle and is run unchanged (D8, D9).
- **S4 — repository gates.** `just agent-workflow-tests` runs both suites plus the unchanged matrix suite; `just build` checks Nix publication/evaluation. A BASE-scoped path gate proves issue-100-owned files did not change.

## Delivery estimate and boundaries

- Estimate: five changed files, about 1,900–2,700 net new Python/test lines, and roughly 75–115 KiB aggregate diff. These are planning estimates, not byte promises.
- Task 1 is an independently reviewable producer-routing slice. Task 2 is the independent scheduling/range-agreement slice and must land before consumer review begins.
- Tasks 3–5 are cumulative consumer slices: strict inputs/baseline lifecycle, routing verdicts, then independent scheduling/report integration. Each receives its own full-lane review package and test cycle; no slice raises a package cap or omits an owned file to claim fit.
- If Task 1 or Task 4 exceeds the active review-package boundary, split only along its already named test classes after both halves independently pass their scoped CLI tests; do not change the public schema or combine it with a neighboring task.
- Issue 100 reconciliation is a later delivery after its approval and merge. This plan adds no deletion or correction from that issue.

## Task index

Task 1 — Emit event-time routing telemetry while preserving accounting — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-1.md](2026-09-20-issue-98-model-effort-drift.tasks/task-1.md)

Task 2 — Add independent scheduling metrics and producer regression gates — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-2.md](2026-09-20-issue-98-model-effort-drift.tasks/task-2.md)

Task 3 — Strictly decode records, validate baselines, and report lifecycle incompatibility — `scripts/agent-model-drift.py`, `tests/test_agent_model_drift.py` — full — [task-3.md](2026-09-20-issue-98-model-effort-drift.tasks/task-3.md)

Task 4 — Evaluate declarations, concrete execution, and escalation lineage — `scripts/agent-model-drift.py`, `tests/test_agent_model_drift.py` — full — [task-4.md](2026-09-20-issue-98-model-effort-drift.tasks/task-4.md)

Task 5 — Project scheduling, wire repository gates, and prove the complete boundary — `scripts/agent-model-drift.py`, `tests/test_agent_model_drift.py`, `justfile` — full — [task-5.md](2026-09-20-issue-98-model-effort-drift.tasks/task-5.md)

## Decisions

- D1, D2, and D7 govern Tasks 1–2: additive versioning, producer-owned evidence, separate event-time selection, and unchanged accounting.
- D5 governs Tasks 2 and 5: scheduling coverage, compatible numerators/denominators, and no waste or savings verdict.
- D3 governs Task 3: strict baseline identity, validity, freshness, catalog classification, and host-specific values.
- D4 governs Tasks 3–5: finding vocabularies, deterministic precedence, report output, and exits.
- D6 governs Task 4: strongest authoritative declaration and structured escalation lineage.
- D8 governs every task's closed path set and deferred issue-100 reconciliation.
- D9 governs every task's CLI-level, production-shaped test contract.

---
