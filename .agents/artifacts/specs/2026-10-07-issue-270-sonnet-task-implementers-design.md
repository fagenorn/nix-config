# Issue #270 — Route sdd task implementers to Sonnet, keep Opus reviewers and escalation

## Problem

Every non-mechanical sdd task is implemented on Opus/high, and so is every fix
round that task needs. A controlled replay on 2026-10-06 (8 tasks) showed Sonnet
at the same effort matching Opus on 6 tasks and beating it on 2, at 39% lower
cost. A companion replay showed the opposite for review: Sonnet reviewers caught
0 of 10 seeded defects against Opus's 6 of 10. So the cheap model is good enough
to write a planned task, and not good enough to judge one. Today the matrix cannot
express that split: the `implementer` role carries one tier, and every sdd
implementation and fix site inherits it.

## Solution

Give planned, per-task implementation its own Sonnet/high role, and keep Opus/high
as the escalation tier for a task that is stuck. Reviewers, owners, design,
planning and the final-review fixer are untouched. Record when and how to judge
the change, so a later reviewer can revert it without this issue's thread.

## Decisions

**Role model (per D1).** The matrix gains one role, `task-implementer`:
Sonnet/high, dispatched on the existing `implementer` subagent type, eligible for
"planned task implementation" and "task fix rounds 1–3", prohibited from
"deterministic mechanical work" and "stuck-task escalation". The `implementer`
role keeps Opus/high and is now the escalation tier. Its agent definition is
unchanged, so an `implementer` dispatch that somehow omitted its model still runs
on Opus. The validator's closed role table and subagent-type table each gain the
row; the custom-agent set does not (no new agent file), exactly as for
`conformance-reviewer`.

**Which sites move (per D2, D3).**

| Dispatch | Role → tier after this change |
|---|---|
| per-task non-mechanical implementation (existing id kept) | `task-implementer`, Sonnet/high |
| fresh re-dispatch for fix rounds 1–3 when the original cannot be resumed (new marked site) | `task-implementer`, Sonnet/high |
| round 4 post-rescue, round 4 rescue fallback, round 5 | `implementer`, Opus/high (unchanged) |
| re-dispatch after a BLOCKED report that is a reasoning problem (new marked site) | `implementer`, Opus/high |
| final-review fix wave | `implementer`, Opus/high (unchanged) |
| every reviewer, reviewer-lite, owner, design, plan, plan-review, ship, mechanic, Codex transport site | unchanged |

A resumed implementer in rounds 1–3 keeps the model it was launched with, so it
needs no marker. The two new markers make dispatches that are today unmarked
explicit, because the agent definition's default is Opus and an unmarked
fresh re-dispatch would silently undo the routing.

**Escalation wording.** The fix loop's round-4 and round-5 text states that the
original implementer ran on Sonnet and that the stuck-breaker and the last round
escalate to Opus/high — a model change, not only a fresh context. The sdd
skill's "stuck tasks escalate across models" bullet names Sonnet → Opus, and the
BLOCKED handling names the Opus escalation in place of "or bump the model". A
context-problem BLOCKED still re-dispatches at the same tier (Sonnet).

**Re-evaluation rule (per D4).** The sdd skill's agent-tier section carries the
rule verbatim enough to apply alone:

- *Metric:* first-pass approval rate of full-lane task reviews for tasks
  implemented by `task-implementer` — the share whose first-pass review needed no
  fix round (spec ✅ and no Critical or Important finding).
- *Baseline:* Opus implementers, ~84% first-pass approval across 153 full-lane
  first-pass reviews (measured before 2026-10-07).
- *When:* after about 10 delivered issues under this routing, and only once at
  least 30 full-lane first-pass reviews are in the sample; until then, keep going.
- *Decision:* below 74% (ten points under baseline) is "clearly worse": revert by
  pointing the two `task-implementer` sites back at `implementer` and retiring the
  role. At or above 74%, keep Sonnet. A rate between 74% and 84% is reported but
  is not a revert trigger.

**Cost telemetry (per D5).** The cost tool's hard-coded canonical role set gains
`task-implementer`. Because the `implementer` subagent type now serves two roles,
it joins `reviewer` and `mechanic` as a shared type: an observation that names
only `subagent_type="implementer"` is `role_ambiguous`, never inferred as
`implementer`.

**Instruction-load profiles.** The instruction-load model requires every matrix
site to be claimed by exactly one profile. The new fix-round re-dispatch joins
the existing sdd fix-implementer profile (same prompt file, same agent
definition). The new BLOCKED escalation lives in the sdd skill file, so it gets
its own profile with that file as its prompt and the implementer agent
definition as its hot read, at the existing implementer ceiling.

**Living docs.** The Nix comment that lists pipeline agent tiers, the sdd eval
expectation that mentions the round-4 tier, and the sdd agent-tier list are
updated to name Sonnet task implementers and Opus escalation. Point-in-time
plans and specs are not edited.

## Test seams

All seams already exist; no new ones.

1. **Matrix validator + its test suite** (`agent_model_matrix` and its tests):
   the expected role-tier table, the expected subagent-type table and the
   expected sdd-site table pin `task-implementer` as Sonnet/high on the two task
   sites, and `implementer` as Opus/high on the four escalation sites plus the
   final-review fixer. Running the validator over the live repository is the
   integration seam — it already checks every marker/call pair against the
   matrix and rejects unmarked `Agent(` lines.
2. **Workflow skill contract tests**: a contract test pins that the fix loop
   names Opus as the escalation target from a Sonnet implementer, and that the
   sdd skill carries the re-evaluation rule's metric, baseline (84%, 153),
   sample floor and revert threshold.
3. **Instruction-load validation** (its existing completeness check over the
   live matrix): proves each new site is claimed exactly once.
4. **Cost tool tests**: pin that `subagent_type="implementer"` alone is
   `role_ambiguous`, and that a declared `task-implementer` role is accepted.

Prior art: the `conformance-reviewer` split (a Sonnet role on the `reviewer`
type) and #223's tier change were pinned at these same seams.

## Out of scope

- Every reviewer, reviewer-lite, conformance, plan-review, ship-review, design,
  planning, owner and mechanic dispatch, in sdd and everywhere else.
- The final-review fixer (per D3) and the round-4/5 escalation sites, which stay
  Opus.
- The `implementer` agent definition and its default tier.
- Codex sessions' own model choice and the Codex rescue transport.
- Any skill other than sdd; any automated collection of the re-evaluation metric.
- Re-sealing drift baselines: the matrix digest changes, and any external
  baseline must be re-captured by its owner as for every matrix change.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Add a Sonnet/high `task-implementer` role on the `implementer` subagent type; `implementer` stays Opus/high as the escalation tier and its agent definition is unchanged. | The validator requires site tier = role tier; `conformance-reviewer` is the precedent for a second tier on one agent type; an Opus default fails expensive, not weak. | Retier `implementer` to Sonnet and add an Opus escalation role — same ripple, but flips the agent-definition default to Sonnet and makes every escalation site change. |
| D2 | Sonnet sites are the per-task implementation and a new marked fresh re-dispatch for rounds 1–3; round-4 (both), round-5 and a new marked BLOCKED reasoning-problem re-dispatch are Opus/high. | Issue: fix-loop task fixes move, "BLOCKED or round-4/5 task escalates to Opus"; fix-loop resumes the original in rounds 1–3. | Leave the two fallback dispatches unmarked — they would inherit the Opus agent default and the routing would be untested. |
| D3 | The final-review fixer stays Opus/high. | Issue scopes "task fixes in the fix loop"; the fixer handles cross-task whole-branch findings in one wave with no second wave; the replay measured only per-task work. | Move it to Sonnet — no evidence for whole-branch fixes, and a weak single wave surfaces residuals to the caller. |
| D4 | The re-evaluation rule lives in the sdd skill's agent-tier section, with a 30-review sample floor and a revert threshold of < 74% first-pass approval. | Standards README: process content is not a standard; issue asks for "revert if clearly worse" against 84%/153. | A standards shard (wrong layer); an unquantified "clearly worse" (not applicable without this thread). |
| D5 | The cost tool adds `task-implementer` to its canonical roles and treats the `implementer` type as shared (`role_ambiguous` without a declared role). | Its existing rule excludes shared types (`reviewer`, `mechanic`) from type-only inference. | Keep inferring `implementer` from the type — mislabels every Sonnet task dispatch. |
| D6 | The new sites are `sdd-task-fix-redispatch` (`task-implementer`, `fix-loop.md`) and `sdd-blocked-reasoning-escalation` (`implementer`, `sdd/SKILL.md`), the latter claimed by a new `sdd-blocked-escalation-implementer` profile; the `sdd` and `representative` scenario traces only re-point their existing per-task event, and the `implementer` role's eligible list gains "stuck-task escalation". | Plan phase: the rescue-fallback site is the precedent for a fallback branch absent from every trace; `sdd-lane-verifier` is the precedent for a profile prompted by `sdd/SKILL.md`. | Add both new sites to the `sdd` trace — conditional fallbacks would lengthen the happy-path trace with no new role coverage. |
