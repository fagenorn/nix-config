# Agent harness retrospective — September 19, 2026

Durability: **intentionally temporary** review document retained for the user's decisions; recommendations should be incorporated into the owning issues before this working audit is retired. No issues, runtime settings, branches, or harness code were changed by the audit.

## Assessment

The harness is buying useful correctness and recovery. It also spends too much effort managing itself. The strongest opportunities are to reduce coordination turns, prevent expensive late workflow failures, and make completion mean the user's deliverable is finished. Simply moving every role to a cheaper model would leave the largest structural problems intact and risk losing reviews that caught real bugs.

This conclusion is supported by recorded sessions and retained workflow state, not just by reading skill prose. It is not a measured before/after improvement over the previous harness: there is no matched baseline, reliable end-to-end issue-cost join, or complete record of every machine and isolated review runtime.

## Scope and confidence

The primary activity window is August 19–September 18 inclusive, using UTC timestamps; September 19 is the inspection date. The inventory contains **6,225 session files: 3,253 Claude and 2,972 Codex**, including child and platform-review sessions. This is an automated inventory, with selected sessions examined closely; it is not 6,225 independent user tasks or exhaustive manual reading. Arcwave, Nodo (`nodocom`), Argus and nix-config are the main projects; smaller projects appear in the inventory. Current source, six installed skill copies, recent repository history, retained workflow ledgers and all 18 currently open nix-config harness issues were examined.

Work was split into bounded assignments: Terra handled transcript inventory and measurement; Sol checked live issues against current implementation; the parent reviewed workflow policy, user corrections, high-volume cases and synthesis. Agents received task briefs rather than the full conversation. The independent evidence files are [session metrics](2026-09-19-harness-session-metrics.md), [session cases](2026-09-19-harness-session-cases.md), and [all-issue backlog audit](2026-09-19-harness-backlog-audit.md).

Confidence is high in cited observations and present source mismatches; medium in their likely mechanisms; unmeasured in fleet-wide savings, model quality differences and the causal contribution of any one rule. Tool errors, resumed attempts, long sessions and cached tokens are not automatically waste. Retained ledger states are not current GitHub status or completion rates.

## What is working

**Independent review finds meaningful defects.** In Nodo's issue 1316 migration, correctness review caught watchdog and cleanup code inheriting a cancelled test token. The harness's own evidence-gate work also caught duplicate trials satisfying a supposed exact-three gate. Those findings justify retaining independent correctness review for semantic changes. Short sampled Nodo and Argus task reviewers completed focused reads and returned useful verdicts with explicit scope limits. [Session cases, cases 5 and 9](2026-09-19-harness-session-cases.md).

**Recovery and reconciliation preserve completed work.** Nodo issue 1437's owner hit a session limit after delivery but before writing its terminal result; the dispatcher reconciled the actual merge and retained its review detail. That is a strong reason to keep durable ownership, handoffs, launch checks and observable delivery state. These mechanisms should be simpler to consume, not removed. [Session cases, case 7](2026-09-19-harness-session-cases.md).

**Several useful token-saving mechanisms are already present.** Task-scoped briefs, lighter verification lanes, phase-specific reference documents, single-wave fixes, bounded re-review and compact result transport all exist. They provide a useful base for improvements. Their existence is not proof of deployed savings: the question is whether actual dispatches follow them, and what overhead remains around them. [SDD final review](../../home/common/agent-skills/skills/sdd/final-review.md), [SDD lanes](../../home/common/agent-skills/skills/sdd/SKILL.md:140).

**Grounding and preflight can prevent unnecessary implementation.** Nodo issue 1314 was correctly recognized as already delivered and verified with tests. The failure was the remaining tracker reconciliation, not the decision to avoid rebuilding it. [Session cases, case 2](2026-09-19-harness-session-cases.md).

## The changes with the strongest evidence

### First, correct measurement before optimizing against it

The baseline `agent-costs.py` sums `last_token_usage` at every Codex token event, including repeated snapshots. The audit diagnostic sums each event’s `total_tokens` field and exceeds the final cumulative counters by 0.52% and 5.89% in two checked sessions. Follow-through verification found that the reporter’s separate input-plus-output sums differ slightly from those diagnostic sums: 185,922,225 for Nodo and 275,759,020 for Arcwave. The corrected selected-source totals are 185,069,427 and 261,290,381 respectively; Arcwave selects modern response records rather than the legacy cumulative counter. Modern per-response records and legacy counters also differ in coverage and can disagree; the audit therefore does not claim a complete monthly Codex token total or dollar cost. [Reproduction and source](2026-09-19-harness-session-cases.md).

Keep the structured interface delivered by #120, but add version-aware record selection, deduplication and coverage metadata. This is a correctness follow-up, not evidence that the original #97 feature never shipped. Fixtures must cover repeated snapshots, cumulative resets, missing records and sessions crossing the selected time window.

### 1. Make orchestration aware of available worker capacity

An Arcwave Codex root recorded 215 spawn attempts, 269 follow-ups, 976 agent waits and 211 execution waits. Responses issuing the two wait tools account for 50.85% of that root's 261.29 million recorded request tokens. Input was 99.22% cached, so this is not a claim that half the bill was wasted. Its messages explicitly describe two owners repeatedly sharing one remaining worker/reviewer slot. [Measured case and counting method](2026-09-19-harness-session-cases.md).

Use one issue owner when the host cannot fit another owner plus its workers. Reserve execution capacity before launching an owner. Prefer host completion notifications and a small explicit queue to model-driven slot handovers. Flatten delegation where a controller exists only to relay another controller's messages. Preserve independent review even when capacity forces sequential execution.

Treat this as a focused host-scheduling change with a replayable scenario, not as a reason to increase global fan-out or build a broad replacement orchestrator. The repository still documents `orchestrate-issues` as Claude-only while sessions show Codex users invoking it. A supported host route and an explicit capability check should replace improvised emulation.

**Acceptance:** replay the two-owner/limited-slot scenario; no capacity-induced spawn retry loop; report controller turns, wait-producing responses, worker utilization and time to first useful result. An initial target can be set after this baseline replay, rather than inventing a percentage saving now.

### 2. Move budget feasibility and shared blockers earlier

Three retained nix-config attempts reached late work before final review packaging failed. Issue 121 has tasks 1–6 reviewed with 873 tests and a passing build, but its 589,625-byte aggregate package exceeds a 524,288-byte cap. Issue 122 needed its large engine split after all seven tasks were implemented; issue 115 needed research evidence repackaged. [Session cases, case 6](2026-09-19-harness-session-cases.md).

Project the full review package at planning, and check its growth after each meaningful task. Split delivery before the last gate when feasible; preserve the coverage guarantee. Do not automatically raise caps or hide changed lines.

For environment failures, attach a shared blocker identity and the observation needed to resume. Nodo's retained terminal report describes the browser-image failure on unrelated branches; Arcwave's report identifies a lockfile breaking Linux CI independently of the current changes. Their histories show repeated launches, although the evidence does not attribute every launch to those failures. Rechecking unchanged infrastructure independently in each owner is an avoidable pattern to target. [Session cases, case 7](2026-09-19-harness-session-cases.md).

**Acceptance:** oversized-package and repo-wide-CI fixtures fail before the full implementation/review investment; a relevant dependency or environment change enables resume without discarding reviewed work.

### 3. Finish the user's task and carry authorization across phases

Two explicit user corrections expose missing completion semantics. Nodo stopped an already-delivered issue without reconciling its open tracker state. Arcwave closed a wayfind decision and then told the user to launch a fresh shipping session for its repository record. In Argus, a long experiment repeatedly paused at design and permission gates; some were skill checkpoints and others were actual runtime approval boundaries. Those categories need separate handling. [Session cases, cases 2–4](2026-09-19-harness-session-cases.md).

Carry a concise deliverable and authorization scope with each handoff. Before returning, check whether the authorized deliverable is implemented, verified, durably recorded and delivered to the expected place. Add an already-delivered reconciliation path. Apply existing authorization to bounded experiment iterations; ask only when the next action adds a real decision or a runtime boundary requires it. Do not bypass automatic approval review or silently broaden permissions.

**Acceptance:** replay the specific Nodo, Arcwave and Argus corrections; complete the already-authorized remainder; avoid repeated design approvals within unchanged scope; retain a clear pause for genuinely new authority.

### 4. Complete configuration migration and shrink the hot instructions

The current bootstrap says to resolve project policy once, fail closed, and use the resulting contract. Several installed shared skills still describe legacy configuration, defaults and permissive fallback. Six installed/source comparisons matched, so this is a source-level coexistence problem, not simply an old install.

Meanwhile, since the mid-August diet, the root from-issue skill grew from 2,301 to 4,300 whitespace words; SDD from 1,603 to 2,519; ship-issue from 1,992 to 3,572; writing-plans from 1,614 to 2,395. These are word counts, not estimated marginal token charges. [Comparison method and source references](2026-09-19-harness-session-cases.md).

Finish the canonical resolver migration in existing issues. Move mechanical lifecycle and artifact validation steps into the commands that already own them, leaving a compact decision surface in each phase. Keep one authoritative explanation of each rule. Track root instruction size and what each role actually loads so prose growth becomes visible before the next audit.

**Acceptance:** no onboarded consumer reads a second policy source or silently defaults refused values; a trace identifies one policy resolution per owner; hot-path instruction size does not grow without an explicit reason.

### 5. Route models explicitly, then measure outcomes

Use a host-specific role map. A reasonable candidate for Codex trials is Luna for bounded enumeration and ledger formatting, Terra for bounded analysis and implementation, Sol for ambiguous issue ownership and synthesis, and Astra for the hardest correctness or architecture judgments. This is a proposed experiment, not evidence that a specific model will preserve this project's quality.

Avoid inherited top-tier models for bookkeeping, but do not downgrade ambiguous semantic review solely because the patch is small. A cheap pass that has to reconstruct an unclear brief or be redone can cost more overall. Keep a strong owner on the task that needs broad judgment; give supporting agents narrow inputs and compact outputs. OpenAI's current documentation supports explicit model/effort selection and notes that unconfigured subagents inherit the parent's settings. [Official OpenAI subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).

**Acceptance:** record requested and observed host/model/effort per role, escalation reason, accepted review findings, rework and final outcome. Compare like-for-like issue classes, not raw averages across experiments and mechanical edits.

## Backlog decisions

The [complete 18-issue table](2026-09-19-harness-backlog-audit.md) contains the evidence and concrete changes for each ticket. Recommended ordering:

1. **Close-candidate #97, after validation:** its original machine-readable telemetry capability was delivered through #120. Map the acceptance criteria to that interface and correct the counting problem before retiring its blocker on #98. Do not leave the old description implying the capability is absent.
2. **Split #121:** preserve the substantial reviewed work and create reviewable delivery slices. Recover existing implementation before rebuilding adoption tooling.
3. **Reframe #100:** the need is now migration to the authoritative resolver and elimination of conflicting consumer behavior, not just louder provenance for the legacy path.
4. **Refresh #98 and #99:** validate runtime model routing on both hosts and reduce actual hot-path prose. Separate the 417 observed recurring errors (119 + 64 + 37 + 197 across categories) from instruction-size and workflow-semantics changes so each can be evaluated; 417 is a count, not an HTTP status.
5. **Resolve #116 and #117 before their dependents:** preserve the decision tickets as decisions; give each a bounded scenario set informed by this audit. Add terminal reconciliation and authorization propagation to lifecycle acceptance.
6. **Keep #123–#130 staged:** transaction core, release/profile/forge adapters, lifecycle, project adoption, learning promotion and strict cutover remain distinct concerns. Revise dependencies and acceptance against current code; do not push a large cross-project migration before small traces demonstrate value. Host scheduling deserves a separate bounded item rather than being hidden in the release adapter's scope.
7. **Finish small backlog items deliberately:** retain #38's path-normalization fix, narrow #39 to its outstanding work, and add #37's workflow test coverage to CI in an affordable/advisory form before making it a mandatory expensive gate.

The audit does not justify closing most strategic issues as obsolete. It does justify changing their scope, sequence and evidence requirements. Live GitHub writes were not made.

## How to tell whether the next iteration improves things

Start with a small, fixed cohort spanning a routine Nodo change, an Arcwave coordinated task, an Argus experiment and a harness-maintenance change. Compare within task class and host/version. Record input fresh/cache-write/cache-read, output/reasoning semantics, controller versus worker versus review usage, role/model, compactions, retries with reasons, approval origins, final delivery and accepted defects. Keep guardian/platform activity separate; unknown billing remains unknown.

Prioritize **useful completion per unit of work**: controller responses per delivered issue, avoidable restarts, repeated approvals within unchanged scope, re-review scope, time blocked on known infrastructure, and review findings verified and fixed. Use elapsed time alongside tokens, accounting for rate-limit pauses. Retained ledgers alone cannot supply these measures: 185 of 198 recorded `phase_inputs` objects in the local scan have no context-token observation.

Make the first implementation pass small: measurement correctness, one slot-aware scheduling scenario, the two completion semantics regressions, and an early package-budget check. Broader migrations should inherit those tested behaviors. This keeps the next month focused on completing more useful work with less coordination overhead.
