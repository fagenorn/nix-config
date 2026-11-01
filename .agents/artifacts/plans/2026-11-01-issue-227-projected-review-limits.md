# Issue 227 Projected Review Limits Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Adopt the accepted `review-feasibility` projection as a planning gate and an SDD post-task gate, carried by one closed summary every receiver recomputes.

**Architecture:** `review-feasibility gate`/`confirm` summarize and recompute projections; `artifact-budget` validates the summary; `sdd-gate` gains `record`, `evidence` and `projection`; skills call them. The [spec](../specs/2026-11-01-issue-227-projected-review-limits-design.md) owns contracts and D1–D17.

**Tech stack:** Python 3 standard library, unittest, Git, canonical JSON, Markdown skills, Nix, just.

## Global Constraints

- Delivery base `8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc`, fixed for every gate (D11).
- Unchanged: `project`, `validate-result`, the v3 format, packer, limits, policy (spec § Out of scope). New helpers go in `python/agent_tools`; `artifact_budget.py` imports no `agent_tools`.
- D12: a task changes every path its `Files:` lists (the loader refuses a completed record with no owned effect) and never edits a `## Review feasibility` block; an unlisted path counts as actual.
- D14: never apply or name the user-only raise label or edit `instruction-load.json`; each edited instruction document ends no larger in bytes than at the base.
- Signed commits, subjects ≤ 64 bytes, session trailer; full tracker URLs; issue 152 stays open; long commands carry a `timeout`.

## Test seams

`PYTHONPATH=python python3 -m unittest <file>`; each task names its seam (spec § Test seams, D10, D15).

## Execution gates

Installed tools gate this delivery; in-flight source never gates itself (D11, D16, D21). G0, one `bash` script with `N` set:

```sh
PLAN=$(git rev-parse --show-toplevel)/.agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.md
BASE=8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc; H=$(git rev-parse HEAD); EV=$(sdd-workspace "$PLAN")
g0() { timeout 900 review-feasibility project --plan "$PLAN" --base "$BASE" --head "$H" --completed-through "$N" > "$1"; }
g0 "$EV/g0-$N.json"; X=$?; g0 "$EV/g0-$N.again"; Y=$?
[ "$X" = "$Y" ] && { [ "$X" = 0 ] || [ "$X" = 3 ]; } && cmp -s "$EV/g0-$N.json" "$EV/g0-$N.again" \
  && review-feasibility validate-result --input "$EV/g0-$N.json" --producer-exit "$X" > /dev/null \
  && echo "G0 exit=$X" || echo "G0 failed (exits $X/$Y)"
```

G0 clears only on `G0 exit=0`; `G0 exit=3` ends SDD `decompose_required`; `G0 failed` (exit 2, a disagreeing rerun or an invalid result) ends it `failed`. G0 at 0 precedes `sdd-gate next --task 1`. After task N's clean review: a hand recording commit `plan: record task N evidence` (this root and `task-N.md`, D2's four changes), `sdd-gate next --completed N` (G1), G0 at N, `sdd-gate next --task N+1`. Task 5 ends at G1. Phase-5 G0 at 0 (D21 recipe), head `973b24d`: exit 0 `complete/within_budget`, reproduced and validated; root 14,940 of 16,384 B, total 470,620 of 524,288 B, all eight members (largest 63,488 B), so a forecast revision has no spare member.

## Delivery estimate and boundaries

Estimates: 23 product records on 20 paths, plus the spec, root and members. `c1` [1–2] gate and validators; `c2` [3] recording and SDD order; `c3` [4–5] callers and replay. Five tasks, not seven: each future commit reserves 384 B of review root, so planning G0 first refused seven tasks on `root_bytes` (D17). Long README and from-issue lines inflate records; the acceptance record lands after the last projection (keep 32 KB headroom).

## Task index

Task 1 — Summary, capture, gate and confirm — python/agent_tools/review_gate.py, python/agent_tools/review_feasibility.py, tests/test_review_gate.py, tests/test_agent_tools_launchers.py, python/README.md, justfile — full — [task-1.md](2026-11-01-issue-227-projected-review-limits.tasks/task-1.md)
Task 2 — Transport validators — home/common/agent-skills/scripts/artifact_budget.py, home/common/agent-skills/tests/test_artifact_budget.py, tests/test_review_gate.py — full — [task-2.md](2026-11-01-issue-227-projected-review-limits.tasks/task-2.md)
Task 3 — Recording and sdd-gate next projection — python/agent_tools/review_record.py, python/agent_tools/sdd_gate.py, tests/test_sdd_gate.py, python/README.md — full — [task-3.md](2026-11-01-issue-227-projected-review-limits.tasks/task-3.md)
Task 4 — Skill callers — writing-plans/SKILL.md, sdd/SKILL.md, from-issue/{AUTO.md, standards-review.md, REVIEW-CONTRACT.md, SKILL.md, delegated-owner.md}, test_workflow_skill_contracts.py — full — [task-4.md](2026-11-01-issue-227-projected-review-limits.tasks/task-4.md)
Task 5 — End-to-end replay — tests/test_review_limits_replay.py, justfile — full — [task-5.md](2026-11-01-issue-227-projected-review-limits.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 5 | `ReplayTest`'s oversized-plan case |
| AC2 | code (classified) | Task 3 | `NextProjectionTest` |
| AC3 | code (classified) | Task 1 | `ConfirmTest`, `GateTest`'s capture case |
| AC4 | code (classified) | Task 5 | `ReplayTest`'s growing-plan case |
| AC5 | code (classified) | Task 2 | the producer and SDD projection rows in `test_artifact_budget.py` |
| AC6 | code (classified) | Task 5 | the growing-plan replay |
| AC7 | evidence (classified) | Task 5 | row AC7: `g0-<N>.json`, N = 0..4, each exit 0 `complete/within_budget`, validated; every `Delivery gate:` line; the final gate's `just agent-workflow-tests` and `just build` pass |
| AC8 | code (classified) | Task 5 | Task 5 Step 4's run of `test_review_gate.py`, `NextProjectionTest`, `RecordTest` and the replay |

## Decisions

Task 1: D3, D4, D10, D14, D18, D20. Task 2: D3, D5, D18. Task 3: D2, D8, D9, D12, D15, D19, D20. Task 4: D2, D5–D9, D12–D14, D20, D22. Task 5: D6, D10, D23. Gates and shape: D11, D16, D17, D21.

## Standards review provenance

Reviewer `Codex` (gpt-6-astra, xhigh), isolated read-only, no fallback; base `8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc`, reviewed head `6ed6d3f7`. 8 accepted, 0 rejected, 0 deferred, each verified at its cited live lines.

- B1 accepted: an overflow may carry a null recommendation (D18).
- B2 accepted: `evidence` precedes `ledger-complete` and guards a fresh `--task` (D19).
- B3 accepted: replay horizons follow the task count (D23).
- B4 accepted: `gate --save-dir` keeps the planning result (D20).
- B5 accepted: G0 keeps the real exit and reproduces by rerun (D21).
- B6 accepted: skill-text pins are machine text only (D22).
- S1 accepted: Task 3 tampers the task member and asserts the change.
- S2 accepted: the replay snapshots saved-result bytes (D23).

## Review feasibility delivery

```json
{"actual_evidence":{"head":"5846bbc35ec64119966bf9b78cb3410028328f8a","kind":"git-range-ownership/v1","process_ranges":[{"base":"8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc","boundaries":["all"],"head":"03a37a9188e60a2659b5091202ae6cb4707423df"}],"tree":"e310f3f0d2c811ad86546172f94fcaef2f45fcdb"},"boundaries":[{"acceptance":"Issue 227 complete","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5"],"process_package":{"plan":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.md","spec":".agents/artifacts/specs/2026-11-01-issue-227-projected-review-limits-design.md","tasks":[".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-1.md",".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-2.md",".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-3.md",".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-4.md",".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-5.md"]},"tasks":[1,2,3,4,5]},{"acceptance":"Gate, confirm and transport validators","depends_on":[],"id":"c1","parent":"all","prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64],"process_forecast_ids":["c1s","c1p","c1t1","c1t2"],"process_package":{"plan":".agents/artifacts/plans/i227-c1.md","spec":".agents/artifacts/specs/i227-c1-design.md","tasks":[".agents/artifacts/plans/i227-c1.tasks/task-1.md",".agents/artifacts/plans/i227-c1.tasks/task-2.md"]},"tasks":[1,2]},{"acceptance":"Ownership recording and SDD projection steps","depends_on":["c1"],"id":"c2","parent":"all","prerequisite":{"commit":null,"kind":"completed-tasks","tasks":[1,2],"tree":null},"process_commit_subject_bytes":[64,64,64,64],"process_forecast_ids":["c2s","c2p","c2t1"],"process_package":{"plan":".agents/artifacts/plans/i227-c2.md","spec":".agents/artifacts/specs/i227-c2-design.md","tasks":[".agents/artifacts/plans/i227-c2.tasks/task-1.md"]},"tasks":[3]},{"acceptance":"Skill callers and the end-to-end replay","depends_on":["c2"],"id":"c3","parent":"all","prerequisite":{"commit":null,"kind":"completed-tasks","tasks":[1,2,3],"tree":null},"process_commit_subject_bytes":[64,64,64,64],"process_forecast_ids":["c3s","c3p","c3t1","c3t2"],"process_package":{"plan":".agents/artifacts/plans/i227-c3.md","spec":".agents/artifacts/specs/i227-c3-design.md","tasks":[".agents/artifacts/plans/i227-c3.tasks/task-1.md",".agents/artifacts/plans/i227-c3.tasks/task-2.md"]},"tasks":[4,5]}],"delivery_base":"8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":449,"boundary":"all","deleted_lines":0,"record_bytes":41984,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":5,"owner":0,"path":".agents/artifacts/specs/2026-11-01-issue-227-projected-review-limits-design.md"},{"bounds":[{"added_lines":101,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.md"},{"bounds":[{"added_lines":253,"boundary":"all","deleted_lines":0,"record_bytes":21504,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-1.md"},{"bounds":[{"added_lines":208,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-2.md"},{"bounds":[{"added_lines":351,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-3.md"},{"bounds":[{"added_lines":183,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-4.md"},{"bounds":[{"added_lines":257,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":5,"owner":0,"path":".agents/artifacts/plans/2026-11-01-issue-227-projected-review-limits.tasks/task-5.md"},{"bounds":[{"added_lines":614,"boundary":"c1","deleted_lines":0,"record_bytes":24576,"support":{"covers":["c1s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c1s","last_task":5,"owner":0,"path":".agents/artifacts/specs/i227-c1-design.md"},{"bounds":[{"added_lines":409,"boundary":"c1","deleted_lines":0,"record_bytes":16384,"support":{"covers":["c1p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c1p","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c1.md"},{"bounds":[{"added_lines":307,"boundary":"c1","deleted_lines":0,"record_bytes":12288,"support":{"covers":["c1t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c1t1","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c1.tasks/task-1.md"},{"bounds":[{"added_lines":307,"boundary":"c1","deleted_lines":0,"record_bytes":12288,"support":{"covers":["c1t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c1t2","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c1.tasks/task-2.md"},{"bounds":[{"added_lines":614,"boundary":"c2","deleted_lines":0,"record_bytes":24576,"support":{"covers":["c2s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c2s","last_task":5,"owner":0,"path":".agents/artifacts/specs/i227-c2-design.md"},{"bounds":[{"added_lines":409,"boundary":"c2","deleted_lines":0,"record_bytes":16384,"support":{"covers":["c2p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c2p","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c2.md"},{"bounds":[{"added_lines":307,"boundary":"c2","deleted_lines":0,"record_bytes":12288,"support":{"covers":["c2t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c2t1","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c2.tasks/task-1.md"},{"bounds":[{"added_lines":614,"boundary":"c3","deleted_lines":0,"record_bytes":24576,"support":{"covers":["c3s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c3s","last_task":5,"owner":0,"path":".agents/artifacts/specs/i227-c3-design.md"},{"bounds":[{"added_lines":409,"boundary":"c3","deleted_lines":0,"record_bytes":16384,"support":{"covers":["c3p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c3p","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c3.md"},{"bounds":[{"added_lines":307,"boundary":"c3","deleted_lines":0,"record_bytes":12288,"support":{"covers":["c3t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c3t1","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c3.tasks/task-1.md"},{"bounds":[{"added_lines":307,"boundary":"c3","deleted_lines":0,"record_bytes":12288,"support":{"covers":["c3t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"c3t2","last_task":5,"owner":0,"path":".agents/artifacts/plans/i227-c3.tasks/task-2.md"}],"proposed_boundary":"all","schema_version":3}
```
