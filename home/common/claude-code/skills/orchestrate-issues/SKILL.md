---
name: orchestrate-issues
description: Dispatch a set of tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".
argument-hint: "<issue numbers... | --label X | --milestone Y>"
---

# orchestrate-issues — a dispatcher, not a manager

You are a dispatcher. You hold a ledger of issue → state; you never hold
specs, plans, diffs, or review content. If you find yourself reading code,
a spec, or a review finding, you have left your role — the intelligence
belongs inside each issue's own agent, not here. Your context should stay
flat (~10-20k tokens) regardless of issue count.

## 1. Resolve the issue set

- Explicit numbers → use them, in the given order.
- `--label X` / `--milestone Y` → resolve with ONE
  `<tracker-cli> issue list --label X --json number,title` call
  (tracker CLI and `unsetGithubToken` come from `.claude/skills.config.json`,
  same bindings from-issue uses).
- Read `orchestration.maxParallel` from the config (default **2**). More
  parallelism mostly buys merge conflicts: every ship-issue merge serializes
  on the integration branch anyway.

## 2. Order

Respect tracker `blocked_by` edges when they exist (query them; to-issues
emits them) — dispatch only issues whose blockers are closed, and re-check
the frontier as issues complete. No edges → the given order. Never serialize
by reading code yourself; overlap risk is the edges' job.

## 3. Dispatch

**Fog pre-check first — one query for the whole set.** List the repo's open
`wayfinder:*` decision tickets once (GitHub: `gh issue list --state open
--search 'label:wayfinder:grilling,wayfinder:research,wayfinder:prototype,wayfinder:task'
--json number,url`) and intersect them with the `blocked_by` numbers §2 already
read. An issue blocked by any of them is **fogged**: a human has to decide
before an agent can spec it. Record it `fogged` in the ledger with the count
and links of the open decisions, dispatch nothing for it, and carry that link
list into the final report. from-issue's Phase-0 fog gate stays the deep check
for fog nobody has charted yet; this only avoids paying a whole agent run to
rediscover fog already declared on a map.

### Durable run ledger

Before dispatch, choose a stable `run_id` for this issue set (or resume the one
supplied by the caller). Resolve the dispatcher's absolute repository root once
as `ledger_repo_root`; it is the exact immutable value used by every lifecycle
command and is independent of any issue worktree. Run `workflow-state init-run
--repo-root <ledger_repo_root>
--run-id <run-id> --now <RFC3339-now>`, then `workflow-state reconcile` with the
same `--repo-root <ledger_repo_root>`, run identity, and current time. The returned
ledger is authoritative; rebuild the local task ledger from it before deciding
what is queued or active.

For each remaining issue: `TaskCreate` a ledger entry, choose the owner identity
and separate attempt worktree, then call `workflow-state launch --repo-root <ledger_repo_root> --run-id
<run-id> --issue <num> --owner <owner> --worktree <absolute-worktree>
--budget-minutes <budget> --now <RFC3339-now>` before spawning. Spawn only when
the returned attempt is active. Spawn one **background agent** (fresh context,
`run_in_background: true`) whose entire prompt is:

> Lifecycle envelope: `ledger_repo_root=<ledger_repo_root>`, `run_id=<run-id>`,
> `attempt=<attempt>`, `owner=<owner>`, `worktree=<absolute-worktree>`. Invoke the `from-issue` skill via the Skill tool
> with the literal arguments `from-issue <num> --auto`, in <repo-root>. Persist
> the normalized compact result before returning it, then return exactly the JSON
> printed by `workflow-state finish` and nothing else.

Never inline issue bodies, specs, or plans into a dispatch prompt — the
child fetches its own issue; the worktree is the shared memory. Pass only the
`ledger_repo_root`, `run_id`, attempt, owner, worktree, and literal invocation above.

## 4. Wait on notifications and reconcile durable state

Background agents notify on exit. Never poll continuously: do not `sleep`, run
no-op commands, or re-check task state on a loop. Reconciliation is event-driven
and mandatory on **dispatcher resume**, **notification receipt**, **before retry**,
and **before final drain**: call `workflow-state reconcile`, then update the local
ledger from the durable result before acting. This reconstructs completion after
a delayed or missing notification.

The durable result takes precedence over notification text. Ignore a stale older-attempt notification
when a newer attempt or terminal outcome is recorded.
Record `discussion_items` from the durable compact outcome verbatim and dispatch
the next queued issue only after reconciliation frees a slot.

**Budget guard:** if an agent has been silent past a wall-clock budget
(default 90 min; `orchestration.agentBudgetMinutes` overrides), `workflow-state
reconcile` persists a `stopped` outcome that retains the worktree. Surface it for
inspection. It is not automatically relaunched: first apply the failure policy,
then let `workflow-state launch` enforce the fresh-attempt cap.

## 5. Failure policy

- **Content-level stops are verdicts, not errors** — wrong issue type,
  existing PR/worktree found in pre-flight, fog-gate abort. Record the
  child's stated reason verbatim in the ledger and never retry.
- **`fogged` is a verdict too** — never retried in this run; it clears when
  the decision tickets blocking it close.
- **Transient failures** (CI flake, network, harness death) → call
  `workflow-state reconcile` first. If the durable outcome still permits a retry,
  call `workflow-state launch` with a fresh owner/worktree and spawn only from its
  accepted result. The helper allows attempts 1 and 2 only and refuses a third fresh attempt;
  record its durable failed outcome instead of counting in prose.
- A failed issue never blocks unrelated issues.

## 6. Final report

When the set drains: a per-issue table (issue, state, PR, one-line reason
for any non-merge), then every `discussion_items` entry grouped by issue,
then anything needing a human. Re-running `/orchestrate-issues` with the
same set is safe — from-issue's pre-flight detects merged/open PRs and
no-ops at the cost of one tracker call per issue.

## Notes

Claude-only skill (depends on background agents + task notifications; the
Codex harness lacks both) — it lives outside the shared skills tree, and
Codex users run `/from-issue` per issue as today.
