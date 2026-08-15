# The fix loop (controller instructions)

Loaded by `SKILL.md` when a task review fails: spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap.

A round is one fix dispatch plus one scoped re-review. Five rounds maximum:

- **Rounds 1–3 — resume the original implementer** with the open findings verbatim; its context is intact. (Can't resume? Fresh dispatch carrying brief path, report path, findings — the report file is the persistent memory.)
- **Round 4 — the stuck-breaker.** Three same-context rounds failing usually means the implementer cannot see its own problem, and another same-model retry re-runs the blindness. Use the bounded Codex transport with the failing command or test, the diff so far (`BASE..HEAD`), the brief and report paths, and the open findings:

<!-- agent-dispatch: id=sdd-codex-rescue-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports the bounded stuck-breaker diagnosis to the external Codex runtime without selecting that runtime's model.

  **Verify its diagnosis against the live worktree before acting on it**, then use a fresh judgment-bearing implementer:

<!-- agent-dispatch: id=sdd-post-rescue-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") applies the verified rescue diagnosis plus the open findings.

  Codex unavailable → the same tier, framed "a prior implementer attempted this task 3 times; you own it now — read the report file for what was tried":

<!-- agent-dispatch: id=sdd-rescue-fallback-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fresh-context rescue fallback.
- **Round 5 — last round**, same packet plus round 4's findings:

<!-- agent-dispatch: id=sdd-round-five-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fifth and final fix round.

Every round: the implementer fixes, re-runs the covering tests, appends a fix report (what changed, covering tests, command, output) to the same report file, and returns the short contract. Confirm all three fix-report elements before dispatching the re-review — reviewers do not re-run tests.

The re-review is scoped: `scripts/review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head the previous review saw), template [re-review-prompt.md](re-review-prompt.md), with the findings list, brief, and report paths. Its explicit `reviewer-lite` selection verdicts each finding ADDRESSED / NOT ADDRESSED and flags new breakage in the fix diff only; out-of-scope observations go to the ledger as deferred minors. A result that requires ambiguous adjudication or branch-wide review escapes reviewer-lite through this explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-task-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide task re-review escape.

Record the escalation and selected full-review role in this plan's SDD ledger. After each round, append: `Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <one-liners>; commits <a7>..<b7>)`.

**The breaker.** When round 5's re-review still leaves findings open, stop dispatching and adjudicate each yourself:

- Reviewer wrong, or contestable → park it: `Task <N>: parked — <finding> — ruling: <why the code stands>`.
- Real but nothing downstream builds on it → park it, ruling says real-and-deferred.
- Real and load-bearing (a later task builds on it, or it reveals a plan defect) → STOP: `Task <N>: BLOCKED — <reason>`, report to the human with the finding, the colliding plan text, and the fix history.

Adjudicate only at the cap — earlier is pre-judging with a different name. Every adjudication is a ledger entry; silent discards are forbidden.

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Close enough on spec compliance" | Spec gaps = not done. Fix, or hit the cap and adjudicate. |
| "I'll fix it myself" | Controller fixes pollute context and skip review. Resume the implementer. |
| "One more round will converge" | Past the cap the failure is structural. Adjudicate and route. |
| "This finding is obviously wrong, I'll drop it" | Adjudicate only at the cap; every ruling is a ledger entry. |
| "The fix was small, skip the re-review" | Unreviewed fixes are how regressions land. |
| "Ledger bookkeeping is overhead" | The ledger survives compaction; without it, controllers have re-executed whole plans. |
