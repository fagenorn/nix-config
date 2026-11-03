# Rename Records Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Review packaging pairs an edited move as one rename record keyed by its new path under a new record policy, `review-git-records/v2`, and a plan can forecast a move as `change: rename` with `old_path`. The retained evidence keeps measuring under a frozen v1, and no cap moves.

**Architecture:** Task 1 freezes v1 beside the living policy and binds every retained call site and identity to it while the living content is still v1, so no byte changes. Task 2 flips the living policy to v2 with one operation rule for `_record_operations` and `edge_facts`. Task 3 extends the forecast contract and the completed-effect rules. Task 4 measures the evidence criteria at the final code head.

**Tech stack:** Python 3 standard library, `unittest`, Git 2.51.2 (flake-pinned), canonical JSON digests, just, Nix.

Spec: `.agents/artifacts/specs/2026-11-03-issue-569-rename-records-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/569.

## Global Constraints

- Delivery base `3be26be2878da02e4aa9417719f3388f08f0298c` (`origin/main`, tree `7cb60ea72131b44d46c73f15904166312f77b2ad`). Spec commits `e28a737d` and `4992438e`, then this plan's commit.
- Standard library only. No new module, command, option or recipe. The only new public names are `RECORD_POLICY_V1`, `RECORD_POLICY_V1_SHA256`, `PACKING_POLICY_V1`, `PACKING_POLICY_V1_SHA256` and `record_operation` in `review_actual`, and the `record_policy` keyword (D2, D15).
- No cap moves: `home/common/agent-skills/artifact-budget-policy.json`, the adaptive-violation set and the `member_bytes` no-retry rule stay as they are (AC2).
- Not edited: `tests/fixtures/retained-review-evidence/`, `tests/retained_evidence_test_support.py` (`ANCHOR_SHA256`, `TOOL_COMMIT`), point-in-time specs and plans, `review_budget.py`, `review_feasibility.py`, `adopt_apply.py`, `diff_scope.py`, `verified_tree`, reviewer prompts (D10, D12).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit. No `TODO` or `FIXME`. Code prose cites the issue as "issue 569" or "#569", never a bare `Dn`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under the root `launch-scope scratch` prints. Commit through `launch-commit` with the same three values. Commits are SSH-signed, with subjects of at most 64 bytes, and end with the session's trailer. No gate command or commit message pairs `git` with `push`; never `just switch`, never push.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each.

## Test seams

The spec's § Test seams, unchanged (no new seam):
- `review-package` CLI: `home/common/agent-skills/tests/test_review_package.py` (the issue-439 seam).
- Record view: `tests/test_review_record_view.py`.
- Policy identities and the operation rule: `RecordPolicyDomainTest` in `tests/test_review_feasibility.py`.
- Forecast loader and projection: `tests/test_review_feasibility.py` (refusal table) and `tests/test_review_projection_cases.py`.
- History edges: `tests/test_review_history.py`.
- Retained domain: `tests/test_review_issue121.py` and `tests/test_review_issue100.py` over their fixtures' opt-in `edited_move`, `tests/test_review_evidence.py`, and `just agent-retained-tests` on a quiescent root.
- Suites run as `PYTHONPATH=python python3 -m unittest <path>`, commands as `python -m agent_tools.<module>`. Verification ids: `nix-build`, `agent-workflow-tests`.

## Delivery estimate and boundaries

Figures come from a scratch prototype of Tasks 1–3 at the spec head, under git 2.51.2.
- The retained unit suites, the review suites and `just agent-workflow-tests` (125 members, 918 s at `--jobs 6`) passed there.
- Every new test failed at its predecessor's head as each task's Step 2 lists.
- Edge records at 10 lines of context totalled about 137 KB over 18 product paths, and `python/README.md` adds about 26 KB.
- The forecast adds 30–60 % per path for fix rounds and prose.

One boundary, `all`. The issue ships as one PR: it unblocks #178, and Task 4 measures at the final code head.

## Task index

Task 1 — Freeze record policy v1 and bind the retained domain to it — `python/agent_tools/review_actual.py`, `python/agent_tools/review_forecast.py`, `python/agent_tools/review_projection.py`, `python/agent_tools/review_issue100.py`, `python/agent_tools/review_issue121.py`, `python/agent_tools/review_task7.py`, `python/agent_tools/review_derivation.py`, `python/agent_tools/review_witness.py`, `python/README.md`, `tests/test_review_feasibility.py`, `tests/retained_review_test_support.py`, `tests/test_review_derivation.py`, `tests/test_review_witness.py`, `tests/test_review_issue100.py` — full — [task-1.md](2026-11-03-issue-569-rename-records.tasks/task-1.md)

Task 2 — Record policy v2 pairs edited moves — `python/agent_tools/review_actual.py`, `python/agent_tools/review_forecast.py`, `python/README.md`, `home/common/agent-skills/tests/test_review_package.py`, `tests/test_review_record_view.py`, `tests/test_review_feasibility.py`, `tests/test_review_history.py`, `tests/retained_review_test_support.py`, `tests/test_review_issue121.py`, `tests/test_review_issue100.py` — full — [task-2.md](2026-11-03-issue-569-rename-records.tasks/task-2.md)

Task 3 — Forecasts accept `rename` with `old_path` — `python/agent_tools/review_forecast.py`, `python/agent_tools/review_projection.py`, `python/README.md`, `tests/test_review_feasibility.py`, `tests/test_review_projection_cases.py` — full — [task-3.md](2026-11-03-issue-569-rename-records.tasks/task-3.md)

Task 4 — Acceptance evidence: the ten #178 moves and the retained tier — `.agents/artifacts/plans/2026-11-03-issue-569-rename-records.acceptance.md` — full — [task-4.md](2026-11-03-issue-569-rename-records.tasks/task-4.md)

## Acceptance map

The criteria are untagged; each kind below is classified.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `test_review_package.py::test_edited_move_is_one_rename_record_keyed_by_its_new_path`. One record at the new path, coverage complete, `stat` equal to v2 `--numstat` (3/3), the bytes equal to Git's v2 diff, and exactly 3 `+` and 3 `-` lines |
| AC2 | code (classified) | Task 2 | `RecordPolicyDomainTest::test_living_policy_is_v1_with_a_fifty_percent_rename_threshold` (`adaptive_violations`), `test_oversized_rename_record_stays_whole_and_stops` (exit 3, `member_bytes`, initial candidate) and Task 2 Step 4's `git diff --quiet` of `artifact-budget-policy.json` against the base |
| AC3 | code (classified) | Task 2 | `test_review_package.py::test_ambiguous_pairing_is_deterministic`: three identical runs per fixture, git's pairing, the unpaired oversized `D` with `whole-file-deletion` evidence, coverage complete |
| AC4 | code (classified) | Task 2 | `test_review_package.py::test_move_below_the_threshold_is_a_delete_and_an_add`: `D`+`A`, exit 3, `member_bytes` |
| AC5 | code (classified) | Task 3 | `test_review_projection_cases.py::RenameForecastCases::test_future_rename_projects_and_bounds_the_measured_record`. Exit 0 at `completed_through` 0; the measured rename record is within its bound and the measured total within the projection |
| AC6 | evidence (classified) | Task 4 | Task 4 Step 2: the ten `git mv`s on a clone of the base, measured at `T` under v1 and v2. Threshold: 10 records, 2,618 B, every record header-only `R100`, under both policies. Row `AC6` |
| AC7 | code (classified) | Task 1 | `tests/test_review_evidence.py` (the committed bundle replays to its historical refusal under `ANCHOR_SHA256`) and Task 1 Step 4's `git diff --quiet` of the bundle and `tests/retained_evidence_test_support.py` (`TOOL_COMMIT`) against the base |
| AC8 | evidence (classified) | Task 4 | Task 4 Step 3: `timeout 14400 just agent-retained-tests "$ROOT"` on a private root from `make_root`, `basis` empty and root digest unchanged. Threshold: exit 0, last line `OK`, no skip. `just build` and `just agent-workflow-tests` in sdd's final verification. Row `AC8` |

## Decisions

- Record policy and pairing: D1, D3, D4 (Task 2); rename records and generated evidence: D5 (Task 2); one operation rule: D6, D15 (Task 2).
- Two domains: D2, D11, D14 (Task 1), and the retained proof's placement and fixture, D16 (Task 2).
- Forecast and completed effects: D7, D8, D9, D13 (Task 3).
- Scope: D10, D12, with D17 keeping clear of #559's test hunks (Tasks 1–3).
- Evidence: D18 (Task 4).
- Planning appended D14–D18.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"3be26be2878da02e4aa9417719f3388f08f0298c","kind":"git-range-ownership/v1","process_ranges":[],"tree":"7cb60ea72131b44d46c73f15904166312f77b2ad"},"boundaries":[{"acceptance":"Issue 569 complete: AC1-AC8 green under the focused suites, Task 4's evidence (the ten #178 moves and the retained tier on a private quiescent root), just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.md","spec":".agents/artifacts/specs/2026-11-03-issue-569-rename-records-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-2.md",".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-3.md",".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-4.md"]},"tasks":[1,2,3,4]}],"delivery_base":"3be26be2878da02e4aa9417719f3388f08f0298c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":436,"boundary":"all","deleted_lines":0,"record_bytes":35840,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":4,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-569-rename-records-design.md"},{"bounds":[{"added_lines":128,"boundary":"all","deleted_lines":0,"record_bytes":17408,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.md"},{"bounds":[{"added_lines":180,"boundary":"all","deleted_lines":0,"record_bytes":21504,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-1.md"},{"bounds":[{"added_lines":432,"boundary":"all","deleted_lines":0,"record_bytes":38912,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-2.md"},{"bounds":[{"added_lines":203,"boundary":"all","deleted_lines":0,"record_bytes":17408,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-3.md"},{"bounds":[{"added_lines":187,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.tasks/task-4.md"}],"proposed_boundary":"all","schema_version":3}
```
