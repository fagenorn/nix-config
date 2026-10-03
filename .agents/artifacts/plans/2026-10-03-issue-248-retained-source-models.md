# Issue 248 Retained Source Models Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Publish three authenticated retained-history models in `agent_tools` (`review_task7`, `review_issue121`, `review_issue100`), each with a `derive_*`/`validate_*` pair and a portable real-Git tier in `agent-workflow-tests`.

**Architecture:** Three domain modules sit on published CORE (parent D1, D11). Task 1 recovers the parent's Task-7 model by blob and fixes its findings; Tasks 2 and 3 author the issue-121 adapter and the issue-100 verifier. All Git facts come from CORE's original-history authority. The [spec](../specs/2026-10-03-issue-248-retained-source-models-design.md) owns S1–S15, the recovery manifest and every behavioral contract; it cites the parent design at `6e5224e` for the rest.

**Tech stack:** Python standard library, Git plumbing, canonical JSON, OpenSSH signing, unittest, Nix/Home Manager, just.

## Global Constraints

- Design identity `DP234-SOURCE`. The immutable `DELIVERY_BASE` is `5f865639eb669ac80ea66c50c9a20a0636fa1dde`. Every gate covers every later product and process commit.
- No retained module runs `git rev-list`, `git log` or `rev-parse <commit>^{tree}` for parents, membership, order or trees. Policy limits come only from `describe("review-package")`.
- Agent-helper standards 1–5: digests via `telemetry_digest` or CORE's `canonical_bytes`; no dynamic imports, `sys.path` edits or `__file__` inside the package; external commands by name on `PATH`.
- Every changed file stays one whole review record. No caps change, no generated-exemption change, no `lib/agent-tools.nix` edit (S12), no CLAUDE.md edit (parent D16), no command-table row (S1).
- Nothing writes retained worktrees, parent evidence, the primary object store, the issue-100 archive or lifecycle state, and no refs are added.
- Out of scope (REPLAY): command rows, both commands, witness/anchor and bundle writer, launcher tests, full-shape tier, `agent-retained-tests`.
- Commits are SSH-signed and end with the session's `Co-Authored-By`/`Claude-Session` lines. Every subject is at most 64 UTF-8 bytes. Code and docstrings describe verified behavior.

## Test seams

- Modules imported normally under the recipe `PYTHONPATH`; tests run as `PYTHONPATH=python python3 -m unittest tests.<module>`.
- Temporary real Git repositories and ephemeral SSH keys through the one shared `tests/retained_review_test_support.py` (parent D12), which may locate the source checkout from its own file.
- `source_budget_env` stages the source budget helper for `describe("review-package")`.
- Verification command IDs: `agent-workflow-tests` (`just agent-workflow-tests`) and `nix-build` (`just build`), both run in this worktree.

## Delivery estimate and boundaries

These are estimates (parent D15, S13, S14). Product: nine paths in three tasks, about 203 KB of forecast records; the support module and `justfile` carry three ordered cumulative contributions each. Process: the spec, this root and three members, about 101 KB. The growth risk sits in the three test modules and `review_task7.py`; an actual record above its bound needs a committed forecast revision and a renewed G0, never truncation or a lowered bound.

There is one boundary, `source`: the issue's three models are its smallest independently acceptable slice, and the decomposition already removed every command. Subject reserves are two 64-byte subjects per task (implementation plus one fix) and ten for process; a third fix needs a forecast revision.

## Task index

Task 1 — Recover and fix the Task-7 estimate and Task-8 effect — python/agent_tools/review_task7.py, tests/retained_review_test_support.py, tests/test_review_task7.py, justfile, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-1.md](2026-10-03-issue-248-retained-source-models.tasks/task-1.md)
Task 2 — Issue-121 adapter, raw-parent ancestry, outcomes and payload — python/agent_tools/review_issue121.py, tests/test_review_issue121.py, tests/retained_review_test_support.py, justfile — full — [task-2.md](2026-10-03-issue-248-retained-source-models.tasks/task-2.md)
Task 3 — Issue-100 verifier and byte domains — python/agent_tools/review_issue100.py, tests/test_review_issue100.py, tests/retained_review_test_support.py, justfile — full — [task-3.md](2026-10-03-issue-248-retained-source-models.tasks/task-3.md)

## Execution gates

Every gate runs in the matching gate environment: define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`) and use `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. The installed `artifact-budget` lacks `describe`, so never use an ambient checker. Keep outputs and logs outside the worktree.

**G0, projection (spec § Delivery gate), before any product commit.** Pin the committed plan head `HEAD`, a process-only tail of the evidence checkpoint below.
1. `core_gate source TREE PYTHON python3 -m agent_tools.review_feasibility project --plan <this root> --base DELIVERY_BASE --head HEAD --completed-through 0`; capture exit and canonical bytes.
2. `validate-result --input RESULT --producer-exit 0` on the same closure.
3. A second independent invocation must reproduce every closed v3 field: identities, digests, package name, counts, the four metrics, status, violations and the null recommendation.

Only exit 0 with `complete/within_budget` clears G0. Exit 2 or 3 stops with no Task 1 and no bootstrap; exit 3 stops for decomposition. Any plan or spec change needs a new committed package and a renewed G0.

**G1, the complete fixed-base actual gate, after every task and fix and at the final head.** Pin the full `HEAD`; run `core_gate source ... python3 -m agent_tools.review_package <this root> DELIVERY_BASE HEAD`, validate through `artifact-budget validate-report --boundary producer`, then independently run `artifact-budget check --kind review-package`. Both must show `complete/within_budget` with identical integer metrics. Exit 2 or 3 stops. After each task, record its `actual_ranges` and refresh `actual_evidence` (head, tree, process ranges) in a process-only metadata commit, as CORE did.

**G2, the real-object proof (S7), after Task 3.** In disposable clones whose `objects/info/alternates` names the primary store read-only, the controller and a fresh adversarial reviewer run the library entry points: the I1 graft and rehashed-table refusals at both entry points, a clean control of exactly 30 edges, the real Task-7 table at 173 rows and at most 49,152 canonical bytes, and both issue-100 domains against the explicit archive directory `/Users/anis/tmp/nix-config/.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f`. Grafts and replace refs are written only in those clones. Record the evidence in this child's SDD workspace, with before/after digests proving the primary checkout's refs, index and objects and the archive unchanged.

**G3, final.** Focused tests, full `just agent-workflow-tests`, `just build`, then separate authorship-independent conformance and correctness reviews over the complete fixed-base delivery. The final review dispositions M2, M4, M5 and M6 explicitly. Required CI remains the merge gate. Nothing is activated.

## Decisions

S1, S12 and parent D16 bound the file set. S3–S8 and S15 govern Task 1; S9 governs Task 2; S10 and S11 govern Task 3; S7 and S13 govern G2 and the forecasts; S14 governs the forecast prices, the evidence checkpoint and the pin/table error split; S16 governs Task 2's final-record table, S17 governs its forcing fixtures, Task 1's generated-evidence fixture and the support ceiling, S18 governs Task 1's blob-mode set, matrix scope and test bound, and S19 governs `compose`'s write allowance and module bound. Each task report names the recovery rows it consumes.

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh effort), in isolated read-only mode over base `5f865639eb669ac80ea66c50c9a20a0636fa1dde`, with no fallback reviewer. Of four findings, four were accepted (B1 → S16; B2, B3 and S1 → S17), none rejected and none deferred. Each was verified against the live plan, the parent spec and CORE before it was applied. The raw reviewer text is not kept in the repository.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"04593449322a12106bb4df509f9162b0f00386c2","kind":"git-range-ownership/v1","process_ranges":[{"base":"5f865639eb669ac80ea66c50c9a20a0636fa1dde","boundaries":["source"],"head":"90d55b0d4016fdf83391bec197794d3b31dd6e2c"},{"base":"5d458f8e8c8b856cd8831be0c7519e942955de59","boundaries":["source"],"head":"aafad61bae40f115da78bc34b3b939df5d552135"}],"tree":"99e6048e9cb3a6fb4f843a22d30a5e31671fa63d"},"boundaries":[{"acceptance":"Complete SOURCE: the Task-7, issue-121 and issue-100 models with derive/validate pairs and portable real-Git tiers; G0-G3 gates, the real-object proof and independent reviews.","depends_on":[],"id":"source","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["p1","p2","p3","p4","p5"],"process_package":{"plan":".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.md","spec":".agents/artifacts/specs/2026-10-03-issue-248-retained-source-models-design.md","tasks":[".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-1.md",".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-2.md",".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-3.md"]},"tasks":[1,2,3]}],"delivery_base":"5f865639eb669ac80ea66c50c9a20a0636fa1dde","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":360,"boundary":"source","deleted_lines":0,"record_bytes":31744,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":3,"owner":0,"path":".agents/artifacts/specs/2026-10-03-issue-248-retained-source-models-design.md"},{"bounds":[{"added_lines":85,"boundary":"source","deleted_lines":0,"record_bytes":13312,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.md"},{"bounds":[{"added_lines":208,"boundary":"source","deleted_lines":0,"record_bytes":19456,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-1.md"},{"bounds":[{"added_lines":190,"boundary":"source","deleted_lines":0,"record_bytes":20992,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-2.md"},{"bounds":[{"added_lines":158,"boundary":"source","deleted_lines":0,"record_bytes":15104,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-248-retained-source-models.tasks/task-3.md"}],"proposed_boundary":"source","schema_version":3}
```
