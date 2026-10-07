# Sonnet Task Implementers Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Route sdd's planned per-task implementation and fix rounds 1–3 to a new Sonnet/high `task-implementer` role, keep Opus/high as the `implementer` escalation tier, record the re-evaluation rule, and classify the now-shared `implementer` agent type correctly in cost telemetry.

**Architecture:** The model matrix (`home/common/agent-skills/model-matrix.json`) gains a `task-implementer` role on the existing `implementer` subagent type; its closed tables in `python/agent_tools/agent_model_matrix.py` and the matrix tests pin it. sdd's marked dispatch sites are re-pointed or added, `instruction-load.json` claims each site exactly once, and the sdd skill prose names Sonnet → Opus escalation and carries the re-evaluation rule. Spec: `.agents/artifacts/specs/2026-10-07-issue-270-sonnet-task-implementers-design.md` (authoritative; ledger D1–D6).

**Tech stack:** Python 3 standard library (`unittest`), JSON contracts, Markdown skill files, Nix (home-manager build).

## Global Constraints

- Tiers: `task-implementer` = model `sonnet`, effort `high`; `implementer` = model `opus`, effort `high` (unchanged). The `implementer` agent definition `home/common/claude-code/agents/implementer.md` is never edited (per D1).
- Every marker is exactly `<!-- agent-dispatch: id=<id> role=<role> model=<model> effort=<effort> -->` on its own line, immediately followed by its call line, which is unique in its file and is the only kind of line in a manifested file that may contain `Agent(`.
- Edit JSON files by hand in their existing 2-space style; keep non-ASCII characters (`–`) as raw UTF-8, never `\u` escapes.
- **Ceiling procedure** — `orchestrated-issue-owner` and `implementation-owner` in `home/common/agent-skills/instruction-load.json` sit at zero headroom and count `sdd/SKILL.md` and `sdd/implementer-prompt.md` as hot members. After any edit to those two files, print the breaches with
  `PYTHONPATH=python python3 -c 'from pathlib import Path; from agent_tools import instruction_load as il; r=il.tree_reader(Path(".")); m=il.load_model(r(il.MODEL_PATH)); s=il.measure(m,r); [print(p["id"],h,s["profiles"][p["id"]][h]["hot"]["bytes"],p["ceiling_bytes"][h]) for p in m["profiles"] for h in p["hosts"] if s["profiles"][p["id"]][h]["hot"]["bytes"]>p["ceiling_bytes"][h]]'`
  then set each printed profile's `ceiling_bytes.<host>` to the printed measured value and append one sentence to that profile's `note`: `Ceiling raised for #270: <what grew> (#155 D10).` Re-run until it prints nothing.
- Focused test runner: `PYTHONPATH=python python3 -m unittest <test files>` from the worktree root.
- Matrix CLI: `PYTHONPATH=python python3 -m agent_tools.agent_model_matrix validate --root .` must print `agent model matrix: valid`.
- Declared verification: the full set, `just build` together with `just agent-workflow-tests`, runs at the final gate and ship only, never as a per-task gate. A task's own `just build` step is its brief's build check (sdd `implementer-prompt.md`: run it when the task changes files the build evaluates) and stays required; it is not the declared set. Each runs in the foreground with an explicit timeout of 3000000 ms.
- Commits are SSH-signed and go through the caller's `launch-commit` when a `Lifecycle worker:` line is present; never disable signing.

## Test seams

- Matrix validator and `home/common/agent-skills/tests/test_agent_model_matrix.py` (role-tier, subagent-type and sdd-site tables; live-repository validation).
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (fix-loop escalation wording; sdd re-evaluation rule).
- `home/common/agent-skills/tests/test_instruction_load.py` live completeness and ceiling checks.
- `tests/test_agent_costs.py` (`agent_costs._declaration`).

## Delivery estimate and boundaries

Estimate: about 14 changed files, ~250 added lines, most in tests and JSON. The two JSON contracts and `sdd/SKILL.md` are touched by several tasks, so tasks run in index order. One deliverable slice; well inside one review package.

## Task index

Task 1 — Add the Sonnet task-implementer role and route the per-task dispatch to it — python/agent_tools/agent_model_matrix.py, home/common/agent-skills/model-matrix.json, home/common/agent-skills/skills/sdd/implementer-prompt.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_agent_model_matrix.py — full — [task-1.md](2026-10-07-issue-270-sonnet-task-implementers.tasks/task-1.md)
Task 2 — Mark the Sonnet fix re-dispatch and the Opus escalations in the fix loop and BLOCKED handling — home/common/agent-skills/model-matrix.json, home/common/agent-skills/skills/sdd/fix-loop.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_agent_model_matrix.py, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-2.md](2026-10-07-issue-270-sonnet-task-implementers.tasks/task-2.md)
Task 3 — Rewrite sdd's agent tiers and record the re-evaluation rule — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-3.md](2026-10-07-issue-270-sonnet-task-implementers.tasks/task-3.md)
Task 4 — Treat the implementer agent type as shared in cost telemetry — python/agent_tools/agent_costs.py, tests/test_agent_costs.py — low-risk — [task-4.md](2026-10-07-issue-270-sonnet-task-implementers.tasks/task-4.md)
Task 5 — Update the living tier docs — home/common/claude-code/default.nix, home/common/agent-skills/skills/sdd/evals/evals.json — low-risk — [task-5.md](2026-10-07-issue-270-sonnet-task-implementers.tasks/task-5.md)

## Decisions

Role model per D1; site routing per D2 and D3; re-evaluation rule placement and thresholds per D4; cost-telemetry ambiguity per D5; new site and profile ids, scenario-trace scope and the `implementer` eligibility line per D6. All rows live in the spec's `## Decision ledger`.

## Standards review provenance

Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra/xhigh), isolated read-only, base 3b911376cfbb47f3480956daa571097d53f4715d, no focus, no fallback. Findings: 0 Blocking; 1 Should fix accepted (build-gate wording in Global Constraints reconciled with the per-task build check); 0 rejected; 0 deferred.
