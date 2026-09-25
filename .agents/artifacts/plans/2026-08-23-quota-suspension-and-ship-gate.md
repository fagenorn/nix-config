# Quota Suspension and Ship-Gate Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make environmental interruptions (quota walls, transport failures, human-only gates) non-terminal, freely resumable checkpoints in the workflow-state lifecycle, and give ship-phase push/PR/merge guard-gated standing authorization — per the spec `.claude/specs/2026-08-23-quota-suspension-and-ship-gate-design.md` (issue fagenorn/nix-config#101 extended per D1).

**Architecture:** A new non-terminal `suspended` attempt state flows through the durable control plane (`workflow-state.py`): owners and the expiry reaper write it, `direct-owner` and `control` resume it without authorization phrases, and a stall counter bounds zombie loops. The acquisition ladder gains a forge observation so the ledger reconciles with GitHub before granting ownership. The PreToolUse lifecycle guard is rewritten from substring dispatch to command-position segment matching and extended to validate `git push`/`gh pr create`/generalized merge for fagenorn-owned repos. Skill prose states the single authorization truth and the canonical re-entry line; the cost reporter learns an `interrupted` outcome.

**Tech stack:** Python 3 stdlib only (helper, guard, tests — `unittest` via subprocess CLI calls); Nix (inline guard derivation + settings attrset in `home/common/claude-code/default.nix`); Markdown skill prose under contract tests.

## Global Constraints

- Python 3 standard library only; no new dependencies anywhere.
- `workflow-state.py` state files keep strict exact-field validation. `schema_version` increments once; prior-version states are upgraded in memory (new attempt fields defaulted: `blocked_on=None`, `suspend_phase=None`, `stalled_resumes=0`) and persisted on next write; unknown future versions are rejected (per D15). Legacy `stopped`/`result_source="expiry"` records remain loadable and valid.
- Closed vocabularies after this plan: `ATTEMPT_STATES = {active, handed_off, suspended, stopped, failed, merged}`; `RESULT_SOURCES = {owner, expiry, superseded, refused, stalled}`; `BLOCKED_ON_VALUES = {usage_limit, transport, human_gate, external, unknown}` (per D2, D11).
- Synthetic result sources are exactly `{expiry, stalled}`; `superseded` marks forge-reconciled records; an owner `finish` may overwrite a synthetic record only, never `owner`/`refused`/`superseded` (per D3, D11).
- Canonical suspension stop line (per D14): `Suspended (blocked_on=<value>). Resume: <command>`. The helper's suspend envelope carries `reentry` = `/from-issue <issue> --auto` for direct runs; orchestrate prose composes its own re-entry line; the cost reporter matches the `Suspended (blocked_on=` prefix.
- The two-attempt cap, `new_run`/`owner_unavailable` denial-of-inference rules, and `handoff` semantics are unchanged (per D5, D7).
- Guard contract: exit 0 = allow, exit 2 = block with reason on stderr prefixed `lifecycle guard: `; fail-closed on every uncertainty; a real guarded-verb command is never passed through with exit 0 for the allowlist to auto-approve (per D16). Guarded verbs never match inside heredoc bodies, quoted string interiors, or comments (per D10).
- The helper emits compact JSON only (`print_json`); human-facing lines are composed by skill prose from envelope fields.
- Run all verification from the worktree root `/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-101-quota-suspension-and-ship-gate` unless a step says otherwise.

## Test seams

- Workflow-state suite: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py` — all lifecycle behavior (subprocess CLI + `--now` time injection; no fixture transcripts).
- Skill-contract suite: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py` — prose truths via literal anchors.
- Permission-guard suite: `just show-claude-settings > "$TMPDIR/settings.json" && CLAUDE_SETTINGS_PATH="$TMPDIR/settings.json" python3 tests/test_claude_permission_guard.py -v` — guard grammar and live-check behavior via `fake-gh` and disposable git repos.
- Cost-reporter suite: `python3 -m unittest -v tests/test_agent_costs.py`.
- Whole-repo gates: `just agent-workflow-tests` and `just build` (Nix eval is the CI-required check).

No other seams; a task needing a new one is a plan bug.

## Task index

Task 1 — Suspension state core (schema, suspend verb, reaper demotion) — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-1.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-1.md)
Task 2 — Direct-owner resume of suspended attempts — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-2.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-2.md)
Task 3 — Run lineage, forge reconciliation, finish supersede — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-3.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-3.md)
Task 4 — Control sweep, wait policy, resume-gate widening — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-4.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-4.md)
Task 5 — Lifecycle guard rewrite and allow surface — home/common/claude-code/default.nix, tests/test_claude_permission_guard.py, CLAUDE.md — full — [task-5.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-5.md)
Task 6 — Cost reporter `interrupted` outcome — scripts/agent-costs.py, tests/test_agent_costs.py — low-risk — [task-6.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-6.md)
Task 7 — Prose single truth, re-entry lines, contract tests — home/common/agent-skills/skills/{ship-issue,from-issue}/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/claude-code/skills/orchestrate-issues/{SKILL.md,evals/evals.json}, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-7.md](2026-08-23-quota-suspension-and-ship-gate.tasks/task-7.md)

Order: 1 → 2 → 3 → 4 (each builds on the previous schema/flow); 5 and 6 are independent of 1–4; 7 last (its prose names behavior 1–5 introduce).

## Decisions

The spec `.claude/specs/2026-08-23-quota-suspension-and-ship-gate-design.md` owns the decision ledger (D1–D16). Tasks cite rows inline; planning appended D11–D16 (result-source reuse, finalize-over-yield, run-id reuse, canonical stop line, schema upgrade, guard defer removal).

---
