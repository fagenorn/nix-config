# Issue 100: Strict Project Resolver Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `ResolvedProject` the only living project-policy interface, remove the legacy resolver and defaults, and prove the same strict behavior in source and activated installations.

**Architecture:** Each workflow phase resolves once at entry, retains the returned immutable snapshot, and passes its namespaces to included documents and nested routines. One assertion matrix describes canonical and installed surfaces; the managed build removes the legacy helper, the authored `nix-activate` command materializes the reviewed generation, and the complete suite verifies the installed user-facing paths.

**Tech stack:** Python 3 standard-library `unittest`, Markdown skills and support documents, Bash evaluation harnesses, Nix/Home Manager, JSON project contracts, `resolve-project`, `just`.

## Global Constraints

- Resolve exactly once at each phase entry, retain one in-memory `ResolvedProject`, and stop on every resolver refusal before artifact mutation or external side effects (D1).
- Included documents, nested routines, and commands consume the retained snapshot; they never resolve again, read `.agents/project.json`, persist the snapshot, infer policy from Git or manifests, or supply defaults (D1, D3).
- Optional knowledge declared `unsupported` is skipped; a `blocked` capability stops an operation that requires it. Tracker-free and release-free behavior exists only where the workflow already defines that route (D1, D3).
- Migrate every living source, support document, fixture, evaluation, installation declaration, and policy comment in one cutover; delete the legacy resolver, its tests, its managed installation, the obsolete configuration, and every living legacy reference (D2).
- Historical `.claude/specs/**` and `.claude/plans/**` artifacts remain byte-unchanged. Do not touch the primary checkout's untracked audit files or the retained issue-121/issue-127 worktrees (D2).
- The assertion matrix applies the same expected-consumer, one-resolution, snapshot-field, fatal-error, and no-legacy checks to canonical and installed surfaces; installed mode is mandatory when either managed root exists (D4).
- Missing-contract, malformed-contract, non-repository, and stale-projection fixtures exit 2 with the exact closed error identity, no snapshot fields, no fallback, and no filesystem mutation (D5).
- Author `nix-activate` with argv `["just", "switch"]`, cwd `.`, and env `[]`; invoke exactly the resolved entry after the managed build and source checks, while deploy remains unsupported (D6).
- Review commands use their resolved IDs and base argv plus D7's explicit direct Codex invocation. A real bounded review must validate selected model/effort and output before the route or Codex identity is accepted; a capacity rejection is binding, surfaced, and never bypassed (D7).
- Activation is local to this nix-config generation. Nodo, Argus, and Arcwave remain unonboarded and fail closed; do not discover, modify, or adopt external repositories, and do not alter retained recovery generations from issue 130.
- Broader lifecycle-guard architecture remains owned by issue 116; update only living obsolete policy comments and tests needed for this migration.
- Carry the writing-plans payload discipline: targeted searches, bounded reads, compact command output, paths rather than artifact contents, and no persisted `ResolvedProject` snapshot.

## Test seams

- **Resolver subprocess:** `home/common/agent-skills/tests/test_resolve_project.py` owns exact exit-2 refusal shapes and read-only fixture behavior.
- **Workflow instruction matrix:** `home/common/agent-skills/tests/test_workflow_skill_contracts.py` owns canonical and installed surface descriptors and applies one assertion function to both.
- **Configured review command:** a real bounded plan/diff review validates selected Codex metadata and terminal output; command availability, requested argv, and exit zero alone are insufficient (D7).
- **Evaluation fixture:** `home/common/agent-skills/evals/fixture-repo/` is a strict-schema onboarded repository with current projections; `run-eval.sh` resolves it once per trial.
- **Managed installation:** `just build` proves the generation contains current skills and `resolve-project` without `resolve-bindings`; resolved `nix-activate` installs that generation.
- **Whole workflow:** the retained verification IDs run `just build` before activation and `just agent-workflow-tests` after activation; the latter must execute installed mode on this host.

## Task index

Task 1 — Pin workflow-facing resolver refusals — `home/common/agent-skills/tests/test_resolve_project.py` — full — [task-1.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-1.md)
Task 2 — Migrate shared workflow consumers to one snapshot — `home/common/agent-skills/skills/**`, `home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-2.md)
Task 3 — Migrate Claude-only consumers and live evaluations — `home/common/claude-code/skills/**`, `home/common/agent-skills/skills/*/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-3.md)
Task 4 — Onboard the eval fixture and remove the legacy surface — `.claude/skills.config.json`, `CLAUDE.md`, `home/common/agent-skills/{evals,scripts,tests,default.nix}`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py` — full — [task-4.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-4.md)
Task 5 — Author activation policy and prove the reviewed source generation — `.agents/project.json`, `home/common/agent-skills/tests/test_resolve_project.py`, generated instruction projections only if required — full — [task-5.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-5.md)
Task 6 — Activate and verify the exact installed migration — managed `~/.agents` and `~/.claude` paths through resolved commands; no repository source edits — full — [task-6.md](2026-09-19-issue-100-strict-project-resolver.tasks/task-6.md)

## Decisions

- Resolution, namespace use, capability handling, and phase ownership follow D1 and D3.
- Migration scope and historical-artifact preservation follow D2.
- The shared source/installed assertion matrix follows D4.
- Closed refusal fixtures follow D5.
- The bootstrap contract patch, activation command, and unsupported deploy state follow D6.
- Configured direct reviews and their binding capacity/metadata gate follow D7.

---
