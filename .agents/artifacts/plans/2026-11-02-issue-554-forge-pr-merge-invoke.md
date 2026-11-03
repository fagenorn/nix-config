# Forge `pr_merge` Invoke Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A two-branch project releases through `release transaction` with the forge's `pr_merge` as its materialize action ahead of `tag` and `github-release`, under the owner-accepted strict-protection merge, with native certification evidence (issue 554 AC1–AC5).

**Architecture:** The driver observes `merge: {pr, base_tip}` at preview, and `bind_candidate` seals it into the subject and the forge's units (D2, D3, D15). `pr_merge` becomes supported behind a protection floor, a head auto-delete check and PR and base prechecks, then makes one guarded `gh pr merge … --match-head-commit` (D4–D6, D13). With `merge`, `tag` and `release` target the PR's merge commit (D7, D8), and a park names the refused invoke (D12). The skill opens the release PR (D1, D9), and a `tests/` harness certifies the merge against a live sandbox (D10, D11, D19, D20).

**Tech stack:** Python 3 standard library, `gh`, `git`, Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-554-forge-pr-merge-invoke-design.md`. A bare "Dn" cites its `## Decision ledger`; "124 Dn", "128 Dn" and "547 Dn" cite the specs those issues name. Issue: https://github.com/fagenorn/nix-config/issues/554.

## Global Constraints

- Base `e692c968` (`origin/main`). Spec commit `61c438ff`, plus the planning commits that append D15–D21.
- Not edited: every `transaction_*.py`, `home/common/claude-code/lifecycle_guard.py`, `guard_policy.py`, `release.py`, `release_cutover.py`, the `launchd-agent`, `codesigned-artifact` and `github-actions-health` adapters, `.agents/project.json`, `lib/agent-tools.nix`, `CLAUDE.md`, `AGENTS.md`, `ship-release/CHANGELOG.md` and the ship-release evals.
- No test reaches GitHub: every adapter, verification and driver test runs inside `tests/forge_world.py`'s `ForgeWorld`. Only Task 7's harness run makes live calls, and it mutates only `fagenorn/release-merge-sandbox`; nothing in this plan mutates `fagenorn/nix-config` or `elevenyellow/jarbird`, or changes any real repository's protection.
- New code and docs cite "issue 554 Dn", because a bare `Dn` in `forge_adapter.py` or `release_driver.py` means 124's or 128's. Comments, docstrings and README sentences describe the code as it behaves at the task's commit; no `TODO` or `FIXME`.
- `python/README.md` lines run to 4 KB. Edit only the sentences each task names, so the cumulative README record stays inside one review member.
- The instruction ceilings stay unchanged; never apply or request `instruction-budget-raise` (D9).
- Commit messages say "issue 554", never `#554`, and no gate command or commit message pairs `git` with `push`.
- Commits go through `launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. They are signed by inherited config, with subject `feat(issue-554/T<n>): …`, and end with the session's trailer.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch goes under `launch-scope scratch`. Never `just switch`, and never push.
- **Focused tests** (timeout 600 s), from the worktree root: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <files> [-k <pattern>] 2>&1 | tail -4'`.
- `just build` (timeout 3600 s) import-checks every git-tracked `agent_tools` module, so a task that changes `python/agent_tools/` runs it after `git add`. sdd's final gate runs `just build` and `just agent-workflow-tests` (timeout 3600 s each) once, on the final head.

## Test seams

The spec's § Test seams, unchanged; a task needing another seam is a plan bug.

## Delivery estimate and boundaries

Rationale only; the numbers are in the forecast blocks.

- `all` (Tasks 1–7) is the one boundary and review package. If ship's `diff-scope` reports the branch over the review limit, split after Task 3 (binding and adapter).
- Bounds are padded (README context per edited region; one fix round per record).
- Task 7 is last: it alone has external effects, so its human gate blocks nothing else.

## Task index

Task 1 — The candidate's `merge` binding — `python/agent_tools/release_adapter.py`, `python/agent_tools/release_profile.py`, `tests/release_test_support.py`, `tests/release_driver_support.py`, `tests/test_release_profile.py`, `python/README.md` — full — [task-1.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-1.md)

Task 2 — `pr_merge` supported: descriptor, floor, prechecks, guarded merge — `python/agent_tools/forge_adapter.py`, `tests/fixtures/forge-adapter-spellings.json`, `tests/forge_world.py`, `tests/test_forge_adapter.py`, `tests/release_test_support.py`, `tests/test_release_profile.py`, `tests/test_release_grammar.py`, `tests/test_release_adapter_core.py`, `tests/test_release_command.py`, `tests/test_claude_permission_guard.py`, `python/README.md` — full — [task-2.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-2.md)

Task 3 — `tag` and `release` target the merge commit — `python/agent_tools/forge_adapter.py`, `tests/fixtures/forge-adapter-spellings.json`, `tests/forge_world.py`, `tests/test_forge_adapter.py`, `python/README.md` — full — [task-3.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-3.md)

Task 4 — The preview observes the merge binding — `python/agent_tools/release_verification.py`, `python/agent_tools/release_driver.py`, `tests/forge_world.py`, `tests/test_release_verification.py`, `tests/test_release_driver.py`, `tests/test_release_command.py`, `python/README.md` — full — [task-4.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-4.md)

Task 5 — The two-branch run, its park reason and crash resume — `python/agent_tools/release_driver.py`, `tests/release_driver_support.py`, `tests/test_release_crash_matrix.py`, `python/README.md` — full — [task-5.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-5.md)

Task 6 — `ship-release` opens the release PR within the budget — `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/tests/test_ship_release_contracts.py` — full — [task-6.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-6.md)

Task 7 — Native certification against the sandbox — `tests/release_merge_certification.py`, `justfile`, `.agents/artifacts/evidence/release-554-native-certification.json`, `tests/test_release_evidence.py`, `home/common/claude-code/README.md` — full — [task-7.md](2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-7.md)

## Acceptance map

The issue's criteria are untagged and are classified here.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 4 | `tests/test_release_driver.py::MergePreviewTest::test_a_two_branch_profile_passes_the_shape_gate_and_lists_three_confirmations`, with Task 2's `tests/test_release_grammar.py::DescriptorTest::test_forge_descriptor_pins_pr_merge_supported` and `::MergeProfileTest::test_the_jarbird_shaped_profile_compiles` |
| AC2 | code (classified) | Task 5 | Rows 1, 2 and 15 (Task 2) and row 16 (Task 5) of the race-row index |
| AC3 | code (classified) | Task 5 | `tests/test_release_crash_matrix.py::TwoBranchMatrixTest::test_a_crash_after_the_merge_tags_the_merge_commit` (row 10) |
| AC4 | evidence (classified) | Task 7 | `just release-merge-certification --scratch <dir> --output <evidence>`, live against `fagenorn/release-merge-sandbox`, writes `result: passed` with rows a, b and c `passed` on classified refusals (D20); `tests/test_release_evidence.py::MergeCertificationEvidenceTest` pins it. Task 7's implementer fills row AC4, or names `blocked_on: human_gate` |
| AC5 | code (classified) | Task 5 | Every row of the race-row index below, each its named test |

**Race-row index** (spec § Race and denial matrix; each test's docstring starts `Issue 554 row <n>`):

| Row | Task | Test |
|---|---|---|
| 1 | 2 | `tests/test_forge_adapter.py::PrMergeInvokeTest::test_a_protection_floor_gap_refuses_before_the_guard` |
| 2 | 2 | `…::PrMergeInvokeTest::test_a_failed_protection_read_refuses_with_no_mutation` |
| 3 | 2 | `…::PrMergeInvokeTest::test_a_pr_not_open_on_another_base_or_head_refuses` |
| 4 | 2 | `…::PrMergeInvokeTest::test_a_moved_base_refuses_base_moved` |
| 5 | 2 | `…::PrMergeInvokeTest::test_a_guard_denial_is_authorization_denied` |
| 6, 7 | 5 | `tests/test_release_crash_matrix.py::TwoBranchMatrixTest::test_a_provider_refused_merge_parks_with_no_effect` |
| 8 | 5 | `…::TwoBranchMatrixTest::test_a_landed_merge_that_exits_non_zero_is_satisfied` |
| 9 | 2 | `tests/test_forge_adapter.py::PrMergeInspectTest::test_a_merge_onto_a_moved_base_is_diverged` |
| 10 | 5 | `tests/test_release_crash_matrix.py::TwoBranchMatrixTest::test_a_crash_after_the_merge_tags_the_merge_commit` |
| 11 | 4 | `tests/test_release_driver.py::MergePreviewTest::test_merge_observation_refusals_create_nothing`, `tests/test_release_command.py::TwoBranchCommandTest::test_preview_refuses_a_missing_release_pr` |
| 12 | 4 | `tests/test_release_driver.py::MergePreviewTest::test_a_moved_base_between_preview_and_run_is_stale` |
| 13 | 3 | `tests/test_forge_adapter.py::MergedTagTest::test_tag_invoke_refuses_before_the_pr_merged` |
| 14 | 3 | `…::MergedTagTest::test_a_tag_at_the_integration_tip_is_diverged` |
| 15 | 2 | `…::PrMergeInvokeTest::test_head_auto_delete_refuses_before_the_guard` |
| 16 | 5 | `tests/test_release_crash_matrix.py::TwoBranchMatrixTest::test_a_floor_refusal_parks_with_its_reason_and_abandons` |

## Decisions

| Decisions | Tasks |
|---|---|
| D2, D15 (identity member, alias-scoped binding, `candidate_problem`, `binds_merge`) | 1, 4 |
| D4, D6, D13 (floor, ordered prechecks, head auto-delete, no stderr parsing) | 2 |
| D5, D17 (spelling, fixture rows, guard unchanged, refusal references) | 2, 3 |
| D16 (descriptor and profile digests re-pinned) | 2 |
| D7, D8 (exact parents; tag at the merge commit, fetch only with merge) | 2, 3 |
| D3, D14 (preview observes `merge`; no second floor) | 4 |
| D12, D21 (park reason; crash resume re-confirms `merge`) | 5 |
| D1, D9, D18 (skill opens the PR; budget; contract test) | 6 |
| D10, D11, D19, D20 (harness, sandbox, evidence, refusal classes) | 7 |

Planning appended D15–D19, the standards review D20–D21, and attempt 2 D22.

## Standards review provenance

Reviewer Codex (gpt-6-astra, xhigh), isolated read-only, no focus; base `e692c9685c3e4b08f55c327c5f2b8c699fc95bc4`. 6 accepted (4 blocking, 2 should-fix), 0 rejected, 0 deferred, no fallback.

- Blocking: PR554-01 `StatefulForge` skips `merge_ready()`, two-branch tests register it (T5); PR554-02 crash resume re-confirms `merge`, inspects first (T5, D21); PR554-03 certification passes only on a classified merge-condition refusal (T7, D20); PR554-04 T2 and T5 subjects fit 64 bytes.
- Should fix: PR554-05 T2's obsolete-name grep spares the old-shape test; PR554-06 README spelling count (T2), `VerificationRefused` codes (T4).

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"e472765cc8d8306ee0637ad6bbe6ae8f6e82527a","kind":"git-range-ownership/v1","process_ranges":[{"base":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","boundaries":["all"],"head":"e97fba59a32a50274360a293c179ab7953dee9a7"},{"base":"50bd7d94178d72b5b6f80c6c92e50482b45d3a15","boundaries":["all"],"head":"2f00e5138d399c29a2851d953f526fa56191dbea"},{"base":"7f236840000d5ed15aae3467ee962f6124508496","boundaries":["all"],"head":"d0a11a23314e70ae9b1d9c9f947103ec2e9bdf07"}],"tree":"ce4c7bd1ac2bd5205e804bb9d4dbbbfa992f5abe"},"boundaries":[{"acceptance":"Issue 554 complete: AC1 to AC5 green under just agent-workflow-tests and just build, AC4 by its committed evidence","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4","t5","t6","t7"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.md","spec":".agents/artifacts/specs/2026-11-02-issue-554-forge-pr-merge-invoke-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-4.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-5.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-6.md",".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-7.md"]},"tasks":[1,2,3,4,5,6,7]}],"delivery_base":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":500,"boundary":"all","deleted_lines":0,"record_bytes":47104,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":7,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-554-forge-pr-merge-invoke-design.md"},{"bounds":[{"added_lines":190,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.md"},{"bounds":[{"added_lines":175,"boundary":"all","deleted_lines":0,"record_bytes":15360,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-1.md"},{"bounds":[{"added_lines":360,"boundary":"all","deleted_lines":0,"record_bytes":29696,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-2.md"},{"bounds":[{"added_lines":185,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-3.md"},{"bounds":[{"added_lines":265,"boundary":"all","deleted_lines":0,"record_bytes":19456,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-4.md"},{"bounds":[{"added_lines":190,"boundary":"all","deleted_lines":0,"record_bytes":14336,"support":{"covers":["t5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t5","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-5.md"},{"bounds":[{"added_lines":95,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["t6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-6.md"},{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["t7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t7","last_task":7,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-554-forge-pr-merge-invoke.tasks/task-7.md"}],"proposed_boundary":"all","schema_version":3}
```
