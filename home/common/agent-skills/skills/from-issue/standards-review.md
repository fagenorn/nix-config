# Phase 5 detail — standards review

Loaded from `SKILL.md` at Phase 5. A plan reviewed only by its author risks blind spots, and you are the author. Unless Phase 0 marked the issue `mechanical-only`:

1. Resolve `codex.planReview.enabled` (default `true`) and `.focus` (default `null`; when set, pass its emphasis alongside `projectHints`).
2. **Enabled and `codex-collaboration` available** → invoke its `plan-review` operation. It assembles the packet itself (its SKILL.md enumerates the contents) and owns foreground execution, isolation, read-only enforcement, validation, and a one-time native fallback on a real Codex failure — a busy or concurrent reviewer is never a fallback condition. Supply the issue and acceptance criteria, the Phase-0 investigation and open questions, the worktree base SHA, the spec and plan paths, the optional focus, and — as the review contract — **the absolute path to `REVIEW-CONTRACT.md` beside `SKILL.md`**, which it reads into the packet.
3. **Disabled or unavailable** (including when this skill runs natively in Codex) →

<!-- agent-dispatch: id=from-issue-plan-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches one fresh plan reviewer with no inherited context, the same inputs, and the same `REVIEW-CONTRACT.md` path, told to read that file first.

**The contract travels by path, never inlined** — pasting reviewer text here costs the orchestrator its full length for the rest of the session.

**Mechanical-only:** replace the dispatch with a self-grade — read the issue, spec, plan, live files, and `REVIEW-CONTRACT.md`, then grade against the same Blocking / Should-fix / Discussion buckets. Any behavioral, configuration, interface, generated-output, or semantic-documentation consequence disqualifies the shortcut.

## Dispositioning findings

Verify every actionable finding against the live worktree before touching the plan; stale or unsupported ones are recorded as rejected, not silently applied. Record provenance in the plan (reviewer, job id, base SHA, whether fallback was used) plus each disposition, and never copy a raw reviewer transcript into project artifacts.

Apply blocking fixes inline to the plan (standing local-commit authorization). Bring should-fix items to the user; in `--auto`, apply them too. Append one ledger row per applied **non-obvious** finding — Choice = the edit, Grounding = the reviewer's rationale plus any doc cite, Rejected alternative = what you weighed (or "reviewer's call accepted as-is") — and a row that reverses an earlier decision names it.
