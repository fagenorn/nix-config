# The fix loop (controller instructions)

Loaded by `SKILL.md` when a task review fails.

A round is one fix dispatch plus one scoped re-review. Five rounds maximum:

- **Rounds 1–3 — resume the original implementer** with the open findings verbatim, at the tier it was launched with. Can't resume? Dispatch a fresh one at that same tier, carrying brief path, report path and findings. A task already escalated to Opus/high through a reasoning-problem BLOCKED stays on Opus/high: its fresh implementer is another `sdd-blocked-reasoning-escalation` dispatch (SKILL.md's BLOCKED route), never a step back to Sonnet. Otherwise:

<!-- agent-dispatch: id=sdd-task-fix-redispatch role=task-implementer model=sonnet effort=high -->
Agent(subagent_type="implementer", model="sonnet", effort="high") takes over fix rounds 1–3 when the original task implementer cannot be resumed.
- **Round 4 — the stuck-breaker.** Three failures on the same context escalate the model: from here every fix dispatch is Opus/high. Use the bounded Codex transport with the failing command or test, the diff so far (`BASE..HEAD`), the brief and report paths, and the open findings:

<!-- agent-dispatch: id=sdd-codex-rescue-transport role=codex-transport model=sonnet effort=medium -->
Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports the bounded stuck-breaker diagnosis to the external Codex runtime without selecting that runtime's model.

  **Verify its diagnosis against the live worktree before acting on it**, then escalate to a fresh Opus/high implementer:

<!-- agent-dispatch: id=sdd-post-rescue-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") applies the verified rescue diagnosis plus the open findings.

  Codex unavailable → the same Opus/high escalation, framed "a prior implementer attempted this task 3 times; you own it now — read the report file for what was tried":

<!-- agent-dispatch: id=sdd-rescue-fallback-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fresh-context rescue fallback.
- **Round 5 — last round**, still on Opus/high, same packet plus round 4's findings:

<!-- agent-dispatch: id=sdd-round-five-implementation role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") owns the fifth and final fix round.

Every round: the implementer fixes, re-runs the covering focused tests (plus the brief's build check when the fix changes files the build evaluates; never the full declared verification), appends a fix report (what changed, covering tests, command, output) to the same report file, and returns the short contract. Confirm the fix report carries all four elements before dispatching the re-review.

**Lifecycle workers.** Under a lifecycle identity, register every fix round's implementer, resumed or fresh, as SKILL.md's `### Lifecycle workers` says. Its `Lifecycle worker:` line goes in the prompt of a fresh implementer, or the resume message of a resumed one. Release it on return. A `launch fence refused` report ends the loop.

**Re-review.** Run `review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head the previous review saw) and apply `SKILL.md`'s `### Review-package gate` before dispatching. Supply [re-review-prompt.md](re-review-prompt.md) with the findings list, brief and report paths, and the manifest root path and all four metrics (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`), never shard lists or diff contents. The explicit `reviewer-lite` selection verdicts each finding ADDRESSED / NOT ADDRESSED and flags new breakage in the fix diff only; out-of-scope observations go to the ledger as deferred minors. A result that requires ambiguous adjudication or branch-wide review escapes reviewer-lite through this explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-task-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide task re-review escape.

Record the escalation and selected full-review role in this plan's SDD ledger. After each round, append: `Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <one-liners>; commits <a7>..<b7>)`.

**The breaker.** When round 5's re-review still leaves findings open, stop dispatching and adjudicate each yourself:

- Reviewer wrong, or contestable → park it: `Task <N>: parked — <finding> — ruling: <why the code stands>`.
- Real but nothing downstream builds on it → park it, ruling says real-and-deferred.
- Real and load-bearing (a later task builds on it, or it reveals a plan defect) → STOP: `Task <N>: BLOCKED — <reason>`, report to the human with the finding, the colliding plan text, and the fix history.

Adjudicate only at the cap; every adjudication is a ledger entry.
