# Guard Head, BEHIND and Transient Refusals Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard refuses a merge whose PR is `BEHIND` its base and a `--match-head-commit` that is not the PR's head commit, a row-check timeout refusal says it is transient and asks for a rerun, and the global guidance states the accepted lifecycle-verb form.

**Architecture:** `validate_merge`'s one PR lookup reads two more fields, `headRefOid` and `mergeStateStatus`. A new function, `mergeability_problem`, judges them, and both merge arms call it after their own shape judgment and before their first gate (D1–D5). `row_check_problem` swaps its closing clause for `transient: rerun the command` only on a timeout (D6, D10). One paragraph of `home/common/agent-guidance/AGENTS.md` states the accepted verb form inside the Instruction Budget (D7).

**Tech stack:** Python 3 standard library (`json`, `re`, `subprocess`, `unittest`), the built guard behind the generated Claude settings, Markdown under the Instruction Budget gate, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-30-issue-476-guard-head-behind-transient-design.md`. A bare "Dn" cites its `## Decision ledger`, and this plan appends D9 and D10. Issue: https://github.com/fagenorn/nix-config/issues/476.

## Global Constraints

- Base `46c616ef` (`origin/main` at planning). Spec commit `4ab6b0cc`. Tasks land in index order, each on top of the one before.
- `home/common/claude-code/lifecycle_guard.py` stays one standalone standard-library file. It imports nothing from `agent_tools`, gains no import and starts no new child process. `FORM_TABLE` is unchanged. The PR lookup stays one `gh pr view` call with the same argv shape, and only its `--json` value changes.
- Verdict invariant: every command keeps the exit status and message it has at base, with three exceptions. A merge whose PR is `BEHIND` or has an unreadable merge state is refused (Task 1). A merge whose `--match-head-commit` is not the PR's `headRefOid`, or whose `headRefOid` is unreadable while that flag is present, is refused (Task 1). A row-check timeout refusal ends in the transient marker (Task 2).
- The adversarial table in `tests/test_claude_permission_guard.py` (from `# Adversarial table.` to `# Release arm: the declared integration branch`) stays green. Its only edit is D9's `"mergeStateStatus":"CLEAN",` in three payloads.
- Not edited: every skill document, `home/common/claude-code/default.nix`, `CLAUDE.md`, `AGENTS.md` at the repository root, `.agents/project.json`, `tests/fixtures/guarded-command-shapes.json`, `tests/fixtures/forge-adapter-spellings.json`, `python/agent_tools/forge_adapter.py`, and the 5 s child bound, 15 s row-check bound and 27 s invocation deadline.
- Instruction load: never add the `instruction-budget-raise` label, and never edit `home/common/agent-skills/instruction-load.json`.
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 476", never a bare `#476`. No `TODO` or `FIXME`.
- The live lifecycle guard reads a `bash -c` source as raw text. It refuses the source when `git` and `push` (or `branch -d`, or `gh` and `pr merge`) occur in order, so a shell gate never pairs those words. The guard also adjudicates any command that names the raise label, so no gate names it. The guard's verdicts are tested only through the Guard suite.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Guard suite** (timeout 3600 s; the build is warm). `just build` evaluates the working tree's tracked files, so the suite runs the guard as edited. The suite is not part of `just agent-workflow-tests`. Append `-k <pattern>` (repeatable) after the test file to focus it:

  ```bash
  bash -c 'set -e -o pipefail
  just build 2>&1 | tail -3
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-code-settings\.json$") \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-bash-lifecycle-guard-base-policy\.json$") \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4'
  ```

  At base it ends `Ran 89 tests` and `OK` (about 165 s, plus about 60 s for a build after a guard edit).
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`. A passing run ends `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Guard suite and the Budget run, which neither recipe covers.

## Test seams

- The guard's process boundary only (spec § Test seams, D8): hook JSON goes in, and an exit status and one stderr line come out, through `run_guard` and `refusal_line`. The fake `gh` matches the PR lookup's exact argv. A `FAKE_PR_JSON` override replaces the whole payload. The fake row check runs with `FAKE_DERIVE_MODE`, and repositories come from `make_repo`. No test imports `lifecycle_guard.py`.
- The guidance paragraph is checked by the Budget run (`python -m agent_tools.instruction_load check` against `origin/main`) and by `home/common/agent-skills/tests/test_dispatch_contracts.py`, which scans the guidance for stray contract clauses.

## Delivery estimate and boundaries

All figures are estimates. Four changed files, plus this package and two spec ledger rows, about +260/−20 lines:

| File | Change |
|------|--------|
| `lifecycle_guard.py` | about +45/−5 |
| `tests/test_claude_permission_guard.py` | about +175/−12 |
| `home/common/claude-code/README.md` | one new paragraph and three phrase edits, about +2.5 KB |
| `home/common/agent-guidance/AGENTS.md` | +6 lines, 302 B |

This is one review package. If a split is forced, each task is its own slice: S1 = Task 1 (AC1, AC2, AC5), S2 = Task 2 (AC3), S3 = Task 3 (AC4).

## Task index

Task 1 — Merge mergeability check: BEHIND and head commit — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-30-issue-476-guard-head-behind-transient.tasks/task-1.md)
Task 2 — Row-check timeout refusal marked transient — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-30-issue-476-guard-head-behind-transient.tasks/task-2.md)
Task 3 — Global guidance states the accepted lifecycle-verb form — `home/common/agent-guidance/AGENTS.md` — full — [task-3.md](2026-10-30-issue-476-guard-head-behind-transient.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_a_wrong_head_commit_is_refused_naming_the_pr_head` (three paths per D1; at base each wrong-head merge exits 0), run by the Guard suite |
| AC2 | code | Task 1 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_a_pr_behind_its_base_is_refused_naming_the_sync`, run by the Guard suite |
| AC3 | code | Task 2 | `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_a_row_check_past_its_bound_is_killed_with_its_process_group` (the marker present), and `assert_unconfirmed` (the marker absent) through `test_a_failing_row_check_refuses_with_no_fallback`, `test_a_row_for_an_unregistered_repository_is_refused_at_use` and `test_a_row_whose_branches_differ_from_the_derivation_is_refused`, all run by the Guard suite |
| AC4 | code | Task 3 | The Budget run (`just agent-instruction-budget` ends `check: pass`) on Task 3's commit, and CI `Instruction Budget` on the PR |
| AC5 | code | Task 1 | The whole Guard suite (`OK`, 94 tests), with the adversarial table touched only as D9 allows, by Task 1's Step 4 gate. sdd's final gate runs the Guard suite and `just agent-workflow-tests` again |

## Decisions

- Task 1 rests on D1, D2, D3, D4, D5, D8 and D9. Task 2 rests on D6, D8 and D10. Task 3 rests on D7.
- Planning appended D9 (the two-step test sequence and the adversarial table's data-only edit) and D10 (a timeout of a row check whose bound the deadline clipped still carries the marker).
- A planning trial ran at `4ab6b0cc` in a scratch worktree, which was then discarded. It measured the claims the tasks make. Task 1's new rows, run against the base guard, gave 22 failing subtests, every one `2 != 0`, while the arm-order row passed. After Tasks 1 and 2 were applied and the guard rebuilt, the Guard suite ran 93 tests, all `OK` (before Phase 5 added the release-order row PR476-S1, which makes it 94). Both row-check timeout tests passed in about 29 s. The Task 3 paragraph gave `check: pass`, and `test_dispatch_contracts.py` stayed `OK`.

---

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus override; base SHA `46c616eff853e3a12b6ca8813da0c166206aaf18`; no fallback.
- Findings: 0 blocking, 1 should-fix, 0 discussion. Accepted 1, rejected 0, deferred 0.
- PR476-S1 (accepted, verified against the live `RELEASE_PR` fixture, which is green): Task 1 gains `test_the_release_mergeability_check_precedes_the_rollup_predicate`, pinning D1's release-arm order against an empty and a failing rollup; it stays outside D9's red-run selection, and the Guard-suite totals become 94.
