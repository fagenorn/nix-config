# Guard Merge Floor Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A project's contract may declare its required checks, and the lifecycle guard judges a feature merge into a default branch that the forge cannot protect (the plan-gated 403) against those checks on the PR's own rollup. Every other verdict stays as it is (issue 552 AC1, AC2).

**Architecture:** The resolver accepts the optional `bindings.vcs.merge.required_checks` (D1). `guard-policy` copies it, sorted, into each derived row under `derivation.schema_version` 3, and the guard's loader and row check demand and confirm it (D4, D5). In the feature arm, a failed protection read whose stdout is the plan-gated body, for a confirmed row that declares checks, goes to a Python floor over the PR facts already parsed. The floor checks the reviewed head, a readable rollup and each declared check green, by one green rule from which the release arm's jq program is rendered (D2, D3, D6, D11).

**Tech stack:** Python 3 standard library (`json`, `unittest`), the built guard behind the generated Claude settings, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-11-02-issue-552-guard-merge-floor-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/552.

## Global Constraints

- Base `e692c968` (`origin/main`). Spec commit `45b1432d`, plus the planning commit that appends D12–D14. Tasks land in index order, each on top of the one before.
- `home/common/claude-code/lifecycle_guard.py` stays one standalone standard-library file: no new import and no new child process. `FORM_TABLE`, the PR lookup argv and the 5 s, 15 s and 27 s bounds are unchanged.
- Verdict invariant: every command keeps the exit status and message it has at base, with three exceptions. A compiled row whose `required_checks` is missing or malformed contributes no row (Task 2). A row whose checks the row check does not confirm is refused (Task 2). A feature merge into the default branch that gets the plan-gated answer, in a repository whose confirmed row declares checks, is judged by the floor (Task 3).
- The guard suite's adversarial table (from `# Adversarial table.` to `# Release arm: the declared integration branch`) keeps every assertion. Its only edit is `NODO_ROW`'s data-only `"required_checks": []` (D10).
- Not edited: `.agents/project.json` (nix-config declares no checks), `home/common/claude-code/default.nix`, `CLAUDE.md`, `AGENTS.md`, every skill document, `tests/guard_policy_world.py`, `tests/fixtures/`, `forge_adapter.py` and the release core.
- No central policy source names Argus: `default.nix`, the built base policy, `lifecycle_guard.py` and `python/agent_tools/*.py` hold no `argus` in any case. Argus values appear only in Task 4's test, and the guard README names only that test (D14).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit, with no `TODO` or `FIXME`. New code cites "issue 552 Dn", because a bare `Dn` in the guard means another spec's. Commit messages say "issue 552", never a bare `#552`.
- The live guard reads a `bash -c` source as raw text and refuses it when `git` and `push`, `git` and `branch -d`, or `gh` and `pr merge` occur in order. It also judges any command that names the raise label. No gate spells those words, and no task adds that label.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Scratch files go under the directory `launch-scope scratch` prints. Commit through `launch-commit … -- <git commit args>`, SSH-signed, with subject `feat(issue-552/T<n>): …` (Task 4: `test(…)`) and the session's `Co-Authored-By` trailer. Never run `just switch`, and never push.
- **Focused tests** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <files> [-k <pattern>] 2>&1 | tail -4'`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`. It import-checks every tracked `agent_tools` module, so run it after `git add` in a task that changes `python/agent_tools/`.
- **Guard suite** (timeout 3600 s). It is not part of `just agent-workflow-tests`. `just build` sees tracked files as edited, so the suite judges the guard as edited. Append `-k <pattern>` (repeatable) after the test file to focus it:

  ```bash
  bash -c 'set -e -o pipefail
  just build 2>&1 | tail -3
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-code-settings\.json$") \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-bash-lifecycle-guard-base-policy\.json$") \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the full Guard suite, which neither recipe runs.

## Test seams

The spec's § Test seams (D10). A task that needs another seam is a plan bug.

1. The built guard, run as registered, through `run_guard` against the fake `gh` (new mode `http_error`) and the fake row check (`rows_env`). No test imports the guard. D13's one-off gate loads it from a scratch script, never from a committed test.
2. `guard-policy compile` and `derive` from source over `GuardPolicyWorld`, with `project(..., mutate=)`.
3. `resolve-project resolve` through `home/common/agent-skills/tests/test_resolve_project.py`.
4. One real compile and row-check round trip in the guard suite (AC1).

## Delivery estimate and boundaries

- `all` (Tasks 1–4) is the one boundary: one branch and one review package. Its largest record is the guard README's whole diff, which measured about 54.7 KB in a planning simulation of the dictated text, under the 64 KiB member limit (D14). The guard suite's diff measured about 38 KB.
- If a split is ever forced, Tasks 1–2 (contract and row) stand alone, because the guard confirms a row it does not yet use. Tasks 3–4 then form the second package.

## Task index

Task 1 — The contract member `bindings.vcs.merge.required_checks` — `python/agent_tools/resolve_project.py`, `home/common/agent-skills/tests/test_resolve_project.py`, `python/README.md` — full — [task-1.md](2026-11-02-issue-552-guard-merge-floor.tasks/task-1.md)

Task 2 — The derived row carries the declared checks, and the row check confirms them — `python/agent_tools/guard_policy.py`, `home/common/claude-code/lifecycle_guard.py`, `tests/test_guard_policy.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md`, `python/README.md` — full — [task-2.md](2026-11-02-issue-552-guard-merge-floor.tasks/task-2.md)

Task 3 — The plan-gated merge floor — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-3.md](2026-11-02-issue-552-guard-merge-floor.tasks/task-3.md)

Task 4 — An Argus-shaped project merges under the floor, end to end (AC1) — `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-4.md](2026-11-02-issue-552-guard-merge-floor.tasks/task-4.md)

## Acceptance map

The issue's criteria are untagged, and both are classified `code`.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 4 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_an_argus_shaped_project_merges_under_the_plan_gated_floor`, run by the Guard suite. It covers the real compile and row check, the ship-issue merge allowed with the declared check green and refused with it missing or red, and no `argus` in the base policy, `default.nix` or the guard. The live merge on `fagenorn/argus` belongs to https://github.com/fagenorn/nix-config/issues/129 (D8). |
| AC2 | code (classified) | Task 3 | The whole Guard suite `OK` with the adversarial table's assertions unchanged, including Task 3's `test_every_other_protection_answer_keeps_its_refusal`, `test_the_plan_gated_answer_without_declared_checks_keeps_its_refusal` and `test_declared_checks_leave_the_integration_base_and_the_release_arm_alone`, and the existing `test_merge_protection_demand_follows_the_base_branch`. sdd's final gate runs it again on the final head. |

## Decisions

- Task 1 rests on D1. Task 2 rests on D4, D5 and D10. Task 3 rests on D2, D3, D6, D7, D9, D11, D12 and D13. Task 4 rests on D8 and D14.
- Planning appended D12 (how `<observed>` shows a fact that is not a string), D13 (the one-off gate for the release predicate's byte identity) and D14 (where the AC1 test is named, under the review-record limit).
- A planning simulation applied the dictated README text and test code to scratch copies and measured the cumulative `-U10` diffs: the guard README at 22.2, 54.5 and 54.7 KB after Tasks 2, 3 and 4, the guard suite at 17.0, 33.4 and 37.9 KB, and `python/README.md` at 8.4 and 13.8 KB after Tasks 1 and 2.

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, `codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus.
- Base SHA e692c9685c3e4b08f55c327c5f2b8c699fc95bc4; reviewed plan head 7ddb0b162d8d82e850757bd4b6a2d823a29b5d36. No fallback.
- Findings: 1 blocking, 2 should-fix, 0 discussion items; 3 accepted, 0 rejected, 0 deferred.
  - PR-552-01 (blocking, accepted): Task 1 Step 4 read `.agents/project.json` directly; it now checks the file is untouched with `git diff --exit-code` against the base.
  - PR-552-02 (should-fix, accepted, D15): Task 2's loader invariant now separates the missing-member reason (the existing closed-key check) from the malformed-value reason.
  - PR-552-03 (should-fix, accepted): Task 3 Step 3 item 6 corrects the integration-exemption comment that said the default branch keeps the full protection demand.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","kind":"git-range-ownership/v1","process_ranges":[],"tree":"587dbde15f26f7d6f05713cb7d6848f20041b2e2"},"boundaries":[{"acceptance":"Issue 552 complete: AC1 and AC2 green under the Guard suite, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3","t4"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.md","spec":".agents/artifacts/specs/2026-11-02-issue-552-guard-merge-floor-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-3.md",".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-4.md"]},"tasks":[1,2,3,4]}],"delivery_base":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":330,"boundary":"all","deleted_lines":0,"record_bytes":34816,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":4,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-552-guard-merge-floor-design.md"},{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.md"},{"bounds":[{"added_lines":170,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-1.md"},{"bounds":[{"added_lines":195,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-2.md"},{"bounds":[{"added_lines":385,"boundary":"all","deleted_lines":0,"record_bytes":36864,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-3.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["t4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-552-guard-merge-floor.tasks/task-4.md"}],"proposed_boundary":"all","schema_version":3}
```
