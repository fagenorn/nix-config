# Guarded Remote Branch Deletion Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard accepts `git push origin --delete refs/heads/<branch>` for a non-permanent branch in an authorized repository, `ship-issue` spells exactly that form, and a delivery remainder parked on a cause only a person clears is relaunched only by a human-directed sweep, which an explicit `orchestrate-control` session sends on its first sweep alone.

**Architecture:** `FORM_TABLE["push"]` gains a third form, `delete`, which `validate_push` judges after the branch arm's name rule with a permanent-branch state refusal (D1, D2); the shape fixture's `branch.remote` row and the two `ship-issue` sites then move to that spelling inside the instruction budget (D6, D7). `remainder_policy` parks a remainder suspended on a `HUMAN_GATED_BLOCKED_ON` cause unless the request is `human_directed` (D3, D8), and `orchestrate-control step` sends `human_directed` only on an explicit session's first sweep (D4).

**Tech stack:** Python 3 standard library (`shlex`, `re`, `subprocess`, `unittest`), the built guard behind the generated Claude settings, the legacy flat `workflow-state`/`workflow_delivery` scripts and the `agent_tools` package, Markdown skill documents under the Instruction Budget gate, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-26-issue-458-guarded-remote-branch-delete-design.md` (spec commits `69e732df`, `7a92d5b4`; a bare "Dn" cites its `## Decision ledger`; this plan appends D8 and D9). Issue: https://github.com/fagenorn/nix-config/issues/458.

## Global Constraints

- Base `b3236d3f` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- `home/common/claude-code/lifecycle_guard.py` stays one standalone standard-library file that imports nothing from `agent_tools` and starts no new child process; `FORM_TABLE` stays a literal and nothing new runs at module level. A closed-set dispatch on a push form id ends in a branch that raises.
- Verdict invariant: every command keeps base `b3236d3f`'s exit status except `git push origin --delete refs/heads/<branch>` (allowed per D2); refusal text changes only for a push carrying `--delete` (now a known flag) and in the accepted-forms clause, which gains the third push form.
- The adversarial table in `tests/test_claude_permission_guard.py` stays green and unedited (`CLAUDE.md`).
- Instruction load: never add the `instruction-budget-raise` label, never edit `home/common/agent-skills/instruction-load.json`. Headroom at base: `ship-owner` conditional (holds `HUMAN-GATE.md`) 6 B on claude and codex, `ship-owner` hot (holds `SKILL.md`) 1,619 B (D7).
- Not edited: `home/common/claude-code/default.nix`, `CLAUDE.md`, `AGENTS.md`, `.agents/project.json`, `.agents/instructions/`, `DELIVERY-LOOP.md`, `REMAINDER.md`, every `orchestrate-issues` and `from-issue` document, `STALL_LIMIT`, the #351 and #402 specs.
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 458", never a bare `#458`. No `TODO`/`FIXME`.
- The live lifecycle guard reads `bash -c`/`sh -c` source as raw text and refuses it when `git` and `push` (or `branch -d`) occur in order, so a shell gate never pairs those words; the guard's verdicts are tested only through the Guard suite, never by a Bash call that runs a push.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, SSH-signed, ending with the session's trailer lines. Scratch files live under the root `launch-scope scratch` prints. Never run `just switch`; never push.
- **Guard suite** (timeout 3600 s; the build is warm after its first run). `just build` evaluates the working tree's tracked files, so the suite runs the guard as edited; it is not part of `just agent-workflow-tests`. Append `-k <pattern>` (repeatable) after the test file to focus it:

  ```bash
  bash -c 'set -e -o pipefail
  just build 2>&1 | tail -3
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-code-settings\.json$") \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf "%s\n" "$REQ" | grep -- "-claude-bash-lifecycle-guard-base-policy\.json$") \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4'
  ```

- **Skill contracts** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -4'`.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`; passing output ends `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Guard suite and the Budget run, which neither recipe covers.

## Test seams

- Guard process boundary only (spec § Test seams): hook JSON in, exit status and one stderr line out, through `run_guard`/`refusal_line` with the fixture compiled policy (one `NODO` row, `main`/`dev`) and `make_repo`. No test imports `lifecycle_guard.py`. One git-level test runs the fixture's filled `branch.remote` template against a local bare remote (D5).
- `tests/fixtures/guarded-command-shapes.json`: `skill_forms` and `invocation_shapes` read by the guard suite; `skill_forms` read by `test_shell_example_contracts.py` (R1–R3); the `SHIP_ISSUE_MACHINE_TEXT` pins in `test_workflow_skill_contracts.py`; size through the Budget run (D6, D7).
- `workflow-state control` through the 190 `remainder_sweeps` fixture in `test_delivery_workflow.py`; direct `delivery_policy`/`remainder_policy` calls in `test_workflow_delivery.py` and `test_delivery_model.py`; `VocabularyTest` in `tests/test_attempt_custody.py` (D6, D9).
- `orchestrate-control step` through `OrchestrateWorld` request capture in `tests/test_orchestrate_control.py`.

## Delivery estimate and boundaries

Estimates only: 17 changed files plus this package and the spec ledger, about +260/−20 lines. `lifecycle_guard.py` about +12; `tests/test_claude_permission_guard.py` about +110; the fixture about 10 lines; the guard README one new paragraph and three phrase edits; two `ship-issue` lines (+15 bytes net, measured, D7); `workflow_delivery.py` about +12; `workflow-state.py` about +6; delivery tests about +60; `orchestrate_control.py` about +5; `tests/test_orchestrate_control.py` about +20; `python/README.md` one sentence. One review package. Independently deliverable slices if a split is forced: S1 = Tasks 1–2 (the guard form and its one spelling: AC1, AC2), S2 = Tasks 3–4 (the remainder consent rule and first-sweep direction: AC3).

## Task index

Task 1 — The guard's remote-deletion push arm — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-26-issue-458-guarded-remote-branch-delete.tasks/task-1.md)
Task 2 — One remote-deletion spelling in the fixture and `ship-issue` — `tests/fixtures/guarded-command-shapes.json`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-26-issue-458-guarded-remote-branch-delete.tasks/task-2.md)
Task 3 — Remainders parked on a gated cause wait for direction — `python/agent_tools/attempt_custody.py`, `tests/test_attempt_custody.py`, `home/common/agent-skills/scripts/workflow_delivery.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_workflow_delivery.py`, `home/common/agent-skills/tests/test_delivery_model.py` — full — [task-3.md](2026-10-26-issue-458-guarded-remote-branch-delete.tasks/task-3.md)
Task 4 — `orchestrate-control` spends direction on the first sweep — `python/agent_tools/orchestrate_control.py`, `tests/test_orchestrate_control.py`, `python/README.md`, `home/common/agent-skills/scripts/workflow-state.py` — full — [task-4.md](2026-10-26-issue-458-guarded-remote-branch-delete.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | Composition per D5: `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_every_guarded_command_shape_gets_its_verdict` (`branch.remote`, exit 0 bare, `unset GITHUB_TOKEN && ` and `env -u GITHUB_TOKEN `), `::test_the_remote_deletion_form_deletes_only_the_named_branch` (the filled form deletes the branch and keeps a same-named tag on a local bare remote) and Task 1's `::test_remote_branch_deletion_arm`, run by the Guard suite in sdd's final gate |
| AC2 | code (classified) | Task 2 | The flipped `branch.remote` row read by `::test_every_guarded_command_shape_gets_its_verdict` and by `home/common/agent-skills/tests/test_shell_example_contracts.py::ShipIssueGuardedCommandSweepTest::test_every_guarded_command_is_a_cited_form` (R1–R3 at `SKILL.md` and `HUMAN-GATE.md`), plus the `SHIP_ISSUE_HUMAN_GATE` pin read by `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_ship_issue_documents_carry_their_machine_text` |
| AC3 | code (classified) | Task 4 | Composition per D3, D4: `home/common/agent-skills/tests/test_delivery_workflow.py::DeliveryAdmissionTest::test_an_undirected_sweep_parks_a_gated_remainder_until_a_directed_one` (Task 3) and `tests/test_orchestrate_control.py::FactsTest::test_direction_is_spent_on_the_first_sweep`, both run by `just agent-workflow-tests` |

## Decisions

- Task 1 per D1, D2; Task 2 per D1, D5, D6, D7; Task 3 per D3, D6, D8, D9; Task 4 per D4.
- Planning appended D8 (the gated set's home, the required `human_directed` keyword, the import and the park position) and D9 (the test seams the spec left open: the vocabulary pin, the direct-call and helper consent, the `owner_unavailable` ledger rewrite).
- Planning trials at `7a92d5b4` (scratch worktree, discarded) measured the claims the tasks carry: the delete form's refusal texts through the matcher, the arm's verdicts through a scratch copy of the guard, the guard suite's three push-form expectations, the 11 workflow tests that relied on an undirected resume, the parked-remainder and first-sweep tests red at base and green after (the auto-resumable test green at both), and `check: pass` for the two `ship-issue` edits.

## Standards review provenance

Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus, base `b3236d3f`, no fallback. Accepted 1 (SF-1: Task 1 Step 3 also amends the tag-push arm's "any other namespaced push keeps its refusal" clause), rejected 0, deferred 0. The one Discussion item recorded only that the reviewer's sandbox could not reach the GitHub API; the packet carried the issue summary and acceptance criteria, so no plan change.

---
