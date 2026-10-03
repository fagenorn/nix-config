# Issue 234 Retained Review Derivation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Publish `derive-review-feasibility-fixtures` and `replay-retained`. Derivation authenticates retained issue-121/issue-100 history from raw parents, builds a deterministic five-file bundle, and replay checks it without Git.

**Architecture:** Six domain modules and two thin command modules sit on published CORE (D1, D11). Each domain derives its payload and validates it. The witness and anchor bind the payloads acyclically (D3). Replay composes the validators. The [spec](../specs/2026-10-03-issue-234-retained-review-derivation-design.md) owns D1–D15, R1–R4 and every behavioral contract.

**Tech stack:** Python standard library, Git plumbing, canonical JSON, OpenSSH signing, unittest, Nix/Home Manager, just.

## Global Constraints

- Design identity `DP226-DERIVE`. The immutable `DELIVERY_BASE` is `93e6059a6fece769a621657c5889278b9cb9e0d7`. Every gate covers every later product and process commit.
- Git facts come only from CORE's original-history authority. No retained module runs `git rev-list`, `git log` or `rev-parse <commit>^{tree}` for parents, membership, order or trees (D2). Policy limits come only from `describe("review-package")`.
- Digests and strict loads use `agent_tools.canonical` or CORE's `canonical_bytes`/`strict_json`. There are no dynamic imports, no `sys.path` edits and no `__file__` lookups. External commands run by name on `PATH` (agent-helper standards 1–5).
- Every changed file stays one whole review record, well under 65,536 B. Caps never change, records never split, and generated exemptions never grow.
- Nothing mutates retained worktrees, parent evidence, lifecycle state or the object store, and no refs are added. An absent retained object fails closed.
- Out of scope: committing the five concrete outputs (that is EVIDENCE), `just switch`, caller adoption, lifecycle rollout, executing Task 7 or 8, and registration.
- Commits are SSH-signed and end with the session's `Co-Authored-By`/`Claude-Session` lines. Code, docstrings and living docs describe verified behavior.

## Test seams

- Portable tier (D8, D12): source modules imported normally; commands as `python -m agent_tools.<module>` under the recipe `PYTHONPATH`; real temporary Git repositories and ephemeral SSH keys through `tests/retained_review_test_support.py`; `agent-workflow-tests` lists every portable module.
- Installed seam: `tests/test_agent_tools_launchers.py` through `just agent-installed-skill-tests`.
- Full-shape tier: `just agent-retained-tests <root>` (D14). Outside its recipe it skips; inside it, a missing input fails.
- Verification command IDs: `agent-workflow-tests` (`just agent-workflow-tests`) and `nix-build` (`just build`), both run in this worktree.

## Delivery estimate and boundaries

These are estimates, not measurements (D15). The delivery changes 21 product paths across 8 tasks; `justfile` (seven contributions), the support module (four) and the launcher test (two) carry cumulative support. The product forecast is about 354 KB, and the process forecast covers the spec, this root and eight members.

The aggregate-growth risk sits in tests and the Task-7 model. If an actual gate shows that a contribution exceeds its bound, the committed forecast must be revised and re-projected; truncating or lowering a bound is not allowed.

There is one boundary, `derive`, because DERIVE is the smallest independently acceptable slice. CORE's projection decides whether it fits (D9). An exit 3 stops for decomposition and does not start a new bootstrap.

Subject reserves are three 120-byte subjects per task and ten for process.

## Task index

Task 1 — Task-7 estimate model and Task-8 effect — python/agent_tools/review_task7.py, tests/retained_review_test_support.py, tests/test_review_task7.py, justfile — full — [task-1.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-1.md)
Task 2 — Issue-121 adapter, raw-parent ancestry, outcomes and payload — python/agent_tools/review_issue121.py, tests/test_review_issue121.py, tests/retained_review_test_support.py, justfile — full — [task-2.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-2.md)
Task 3 — Issue-100 verifier and byte domains — python/agent_tools/review_issue100.py, tests/test_review_issue100.py, tests/retained_review_test_support.py, justfile — full — [task-3.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-3.md)
Task 4 — Witness, anchor and tool closure — python/agent_tools/review_witness.py, tests/test_review_witness.py, justfile — full — [task-4.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-4.md)
Task 5 — Derivation and the derive command — python/agent_tools/review_derivation.py, python/agent_tools/derive_review_feasibility_fixtures.py, tests/test_review_derivation.py, tests/retained_review_test_support.py, justfile — full — [task-5.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-5.md)
Task 6 — Portable replay and the replay command — python/agent_tools/review_replay.py, python/agent_tools/replay_retained.py, tests/test_review_replay.py, justfile — full — [task-6.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-6.md)
Task 7 — Publish both commands and verify installed parity — lib/agent-tools.nix, tests/test_agent_tools_launchers.py, CLAUDE.md — full — [task-7.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-7.md)
Task 8 — Full-shape retained tier — justfile, tests/test_review_retained_full.py, tests/test_agent_tools_launchers.py — full — [task-8.md](2026-10-03-issue-234-retained-review-derivation.tasks/task-8.md)

## Execution gates

All gates run in the matching gate environment. Define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`), and use the `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. Never use an ambient installed `artifact-budget` or `review-package`. Keep all outputs and logs outside the worktree.

**G0, the projection gate (D9), runs before any product commit.** Pin the committed plan head, `HEAD`, which is a process-only tail of the evidence checkpoint below. Then:

1. Run `core_gate source TREE PYTHON python3 -m agent_tools.review_feasibility project --plan <this root> --base DELIVERY_BASE --head HEAD --completed-through 0`, and capture the exit code and the canonical bytes.
2. Run `validate-result --input RESULT --producer-exit 0` on the same closure.
3. In an independent second invocation, re-project and compare every closed v3 field: identities and digests, the package name, counts, all four metrics, status, violations and the null recommendation.

Only exit 0 with `complete/within_budget` clears the gate. Exit 2 or 3 stops: no Task 1 and no new bootstrap. Any plan or spec change needs a newly committed package and a renewed G0.

**G1, the actual gate, runs after every task and fix and at the final head.** Pin the full `HEAD` and run `core_gate source ... python3 -m agent_tools.review_package <this root> DELIVERY_BASE HEAD`. Validate the result with `artifact-budget validate-report --boundary producer`, then independently run `artifact-budget check --kind review-package`. Both must show `complete/within_budget` and identical four integer metrics. Exit 2 or 3 stops. Before each product projection, refresh `actual_evidence` (checkpoint head and tree, task `actual_ranges`, process ranges) as a process-only metadata commit, as CORE did.

**G2, the source pin (D13).** After Task 6, an independent reviewer reviews the complete `python/` source at a pinned commit. That commit is the `--tool-commit` for every authoritative full-shape run. A fresh adversarial reviewer repeats the graft and rehash reproduction on disposable clones. Any later `python/` change repeats G2 and G0.

**G3, the final gate.** Run the focused tests, the full `agent-workflow-tests`, the managed `just build`, `just agent-installed-skill-tests` and `just agent-retained-tests /Users/anis/tmp/nix-config`, with no skip counted as acceptance. Separate, authorship-independent conformance and correctness reviews then cover the complete fixed-base delivery. Required CI remains the merge gate. Nothing is activated.

## Decisions

D1–D10 govern the behavioral contracts. D11 fixes the module and validator layout. D12 is the pin-injection test seam. D13 fixes the order and the source pin. D14 fixes the full-shape recipe. D15 fixes the forecast method. Members cite the rows they rest on. Each task report names the recovery rows (R1–R4) it consumes.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"df2d764cc14d5361298b6948350fa45bf6205e4b","kind":"git-range-ownership/v1","process_ranges":[{"base":"93e6059a6fece769a621657c5889278b9cb9e0d7","boundaries":["derive"],"head":"df2d764cc14d5361298b6948350fa45bf6205e4b"}],"tree":"a79a4f970f4ba518074f6e2fffb86e00d74e57b8"},"boundaries":[{"acceptance":"Complete DERIVE: authenticated retained derivation and Git-free replay, published source and built commands, portable and full-shape tiers, G0-G3 gates and independent reviews.","depends_on":[],"id":"derive","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[120,120,120,120,120,120,120,120,120,120],"process_forecast_ids":["p1","p2","p3","p4","p5","p6","p7","p8","p9","p10"],"process_package":{"plan":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.md","spec":".agents/artifacts/specs/2026-10-03-issue-234-retained-review-derivation-design.md","tasks":[".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-1.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-2.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-3.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-4.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-5.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-6.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-7.md",".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-8.md"]},"tasks":[1,2,3,4,5,6,7,8]}],"delivery_base":"93e6059a6fece769a621657c5889278b9cb9e0d7","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":455,"boundary":"derive","deleted_lines":0,"record_bytes":36096,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":8,"owner":0,"path":".agents/artifacts/specs/2026-10-03-issue-234-retained-review-derivation-design.md"},{"bounds":[{"added_lines":95,"boundary":"derive","deleted_lines":0,"record_bytes":15360,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.md"},{"bounds":[{"added_lines":120,"boundary":"derive","deleted_lines":0,"record_bytes":12800,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-1.md"},{"bounds":[{"added_lines":115,"boundary":"derive","deleted_lines":0,"record_bytes":12544,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-2.md"},{"bounds":[{"added_lines":105,"boundary":"derive","deleted_lines":0,"record_bytes":10496,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-3.md"},{"bounds":[{"added_lines":103,"boundary":"derive","deleted_lines":0,"record_bytes":8704,"support":{"covers":["p6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p6","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-4.md"},{"bounds":[{"added_lines":114,"boundary":"derive","deleted_lines":0,"record_bytes":10752,"support":{"covers":["p7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p7","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-5.md"},{"bounds":[{"added_lines":114,"boundary":"derive","deleted_lines":0,"record_bytes":9472,"support":{"covers":["p8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p8","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-6.md"},{"bounds":[{"added_lines":80,"boundary":"derive","deleted_lines":0,"record_bytes":8960,"support":{"covers":["p9"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p9","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-7.md"},{"bounds":[{"added_lines":104,"boundary":"derive","deleted_lines":0,"record_bytes":9984,"support":{"covers":["p10"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p10","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-03-issue-234-retained-review-derivation.tasks/task-8.md"}],"proposed_boundary":"derive","schema_version":3}
```
