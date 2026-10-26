# Issue-Owner Agent Type Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Issue owners launched by from-issue and orchestrate-issues run as a new body-less `issue-owner` agent type that blocks the Artifact, ArtifactComments and ArtifactData tools and the claude.ai Docs connector, with probe evidence that it still spawns and dispatches and a recorded route to the 11k-token AC.

**Architecture:** Task 1 confirms, before any code lands, that Claude Code 2.1.310 honours the definition: one `claude -p` probe in a scratch clone dispatches a `general-purpose` control and an `issue-owner` (foreground and background) with one brief, and writes the acceptance record. Task 2 adds `home/common/claude-code/agents/issue-owner.md` byte-identical to the probed copy and registers it with `agent_model_matrix` and the frontmatter and carrier tests. Task 3 renames the five owner dispatch sites, the matrix call strings and the role-to-type mapping, and pins them with a site test.

**Tech stack:** Claude Code 2.1.310 agent definitions (`disallowedTools` frontmatter), Markdown skill text, JSON (`model-matrix.json`), Python 3 standard library `unittest`, Nix (home-manager comment only), Just, `agent-costs --report cache` (issue 421).

Spec: `.agents/artifacts/specs/2026-10-26-issue-447-issue-owner-agent-design.md` (this plan appends ledger rows D7–D8). Its `## Decision ledger` rows are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/447.

## Global Constraints

- Base `ca6ba1ae2b37e56c1361a8656c29af1f39b89348` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- Out of scope and unchanged: the `improve-architecture-scan-owner`, `ship-release-owner` and `research-background-researcher` sites and their skills (`home/common/agent-skills/skills/{improve-codebase-architecture,ship-release,research}/`), every non-owner site, `CLAUDE.md`, `home/common/claude-code/README.md`, launch flags, `claude-orchestrate`, settings, permissions, `lifecycle_guard.py`, `agent_costs.py`, `instruction-load.json`, every owner prompt and every skill sentence other than the five call lines (spec § Out of scope, D4).
- Named tools, never a `tools:` allowlist; the definition has no body and is listed in no instruction-load profile (D1, D2). A probe failure never adds a body or a launch flag (D2, D7).
- No ceiling is raised; `just agent-instruction-budget` must end in `check: pass` without `--raise-label`.
- Never run `just switch`, never edit `~/.claude/settings.json`, `~/.claude/agents` or anything under `~/.claude-accounts` (D6).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit; write "issue 447", never a bare `#447`, in code and docs; no `TODO` or `FIXME`.
- Every long command, each test and build command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers. Scratch files and sandboxes live under the root `launch-scope scratch …` prints.
- **Matrix tests** (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -4'`. At base: `Ran 195 tests`, `OK (skipped=2)`.
- **Budget gate** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`; passing ends in `check: pass` (it does at base).
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build mbp 2>&1 | tail -3'`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each). The anis-desktop evaluation is CI's required `Nix Eval` job on the PR.

## Test seams

- Definition frontmatter and body through `test_agent_model_matrix.py`'s `frontmatter()` helper (spec seam 1, D5).
- Owner dispatch sites through the matrix and the two skills' source directories in `test_agent_model_matrix.py`; the `ALLOWED_SUBAGENT_TYPES` mirror; `agent_model_matrix.validate()` on the repository (seam 2, D4, D5).
- Carrier declaration in `test_dispatch_contracts.py`: enrolled agent carriers equal the definitions with a body (seam 3, D2).
- The orchestrate owner call anchor in `test_workflow_skill_contracts.py` (seam 4).
- Gates: `just agent-workflow-tests`, `just agent-instruction-budget`, `just build mbp`, CI `Nix Eval` (seam 5).
- Evidence only: one sandbox `claude -p` probe read through its stream-json init line, `agent_tools.transcript_calls.read_transcript`, subagent `meta.json` files and `just agent-costs --report cache` (Task 1, D6, D7); the post-merge start-up comparison (D8).

## Delivery estimate and boundaries

Estimates only: nine changed files plus the acceptance record, this plan and the spec ledger. `issue-owner.md` about 230 bytes (corpus slack 8,840); five skill lines 4 bytes shorter each; `agent_model_matrix.py` 4 lines; `test_agent_model_matrix.py` about +45 lines; `test_dispatch_contracts.py` about +8 lines; `model-matrix.json` 5 lines; `default.nix` a 3-line comment growth. One review package. Task 1 commits only the record; Task 2 is independently deliverable; Task 3 needs Task 2's type.

## Task index

Task 1 — Probe the body-less `issue-owner` before code lands; acceptance record — `.agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md` — low-risk — [task-1.md](2026-10-26-issue-447-issue-owner-agent.tasks/task-1.md)
Task 2 — The `issue-owner` definition, registered and pinned — `home/common/claude-code/agents/issue-owner.md`, `python/agent_tools/agent_model_matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/tests/test_dispatch_contracts.py` — full — [task-2.md](2026-10-26-issue-447-issue-owner-agent.tasks/task-2.md)
Task 3 — Owner dispatch sites launch `issue-owner` — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/model-matrix.json`, `python/agent_tools/agent_model_matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/claude-code/default.nix` — full — [task-3.md](2026-10-26-issue-447-issue-owner-agent.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_issue_owner_blocks_exactly_the_listed_tools` (`disallowedTools` is exactly `Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs`, no Agent, Skill, Bash or file tool among them, frontmatter fields exactly `name, description, model, effort, disallowedTools`, empty body), run by `just agent-workflow-tests` in sdd's final gate. |
| AC2 | code | Task 3 | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_from_issue_and_orchestration_owner_sites_launch_issue_owner` (the five owner site ids, each call `Agent(subagent_type="issue-owner", …`, no `subagent_type="general-purpose"` in either skill directory) and `::test_executable_subagent_type_mapping_is_exhaustive`, run by `just agent-workflow-tests`; plus `just agent-instruction-budget` ending `check: pass` with no `--raise-label` and `just build` exit 0 on the final head; anis-desktop by the PR's `Nix Eval`. |
| AC3 | evidence | Task 1 | Pre-merge, on mbp with no activation: the Task 1 probe (`claude -p`, one brief to a `general-purpose` control and a foreground `issue-owner`), first request = input + cache write + cache read of each subagent's first call; threshold: control minus `issue-owner` ≥ 11,000 tokens and the `issue-owner`'s Explore child returned `anis`. If the probe's root pool has no `Artifact` (expected, D8), the row records the probe's delta and dispatch and stays pending on the post-merge check written into the record: after the user's `just switch`, `just agent-costs --report cache` start-up median (1st write + 1st read) of `issue-owner` since the switch at least 11,000 below `general-purpose` in the 7 days before it, and no blocked name in those `issue-owner` transcripts' `deferred_tools_delta` (D6, D8). Acceptance-record row `AC3`. |

The one check outside the worktree before merge is the anis-desktop evaluation (CI `Nix Eval`). AC3's post-merge check needs the user's `just switch`; ship-issue holds the issue open until it is recorded (D8).

## Decisions

- The definition's fields and the server-level Docs entry per D1; body-less and unlisted per D2; tiers per D3 (Task 2).
- The role-to-type mapping and the sites kept on `general-purpose` per D4; both new tests in the matrix module per D5 (Tasks 2, 3).
- Evidence before activation per D6; the probe as Task 1, its stop rules and the byte-identical commit per D7; the post-merge route for the Artifact trio and the 11k threshold per D8 (Task 1).

---
