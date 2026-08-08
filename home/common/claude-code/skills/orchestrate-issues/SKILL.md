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

For each remaining issue: `TaskCreate` a ledger entry, then spawn one **background
agent** (fresh context, `run_in_background: true`) whose entire prompt is:

> Invoke the `from-issue` skill via the Skill tool with arguments
> `<num> --auto`, in <repo-root>. Work autonomously to completion (from-issue
> hands off to ship-issue itself). Then report back exactly this JSON and
> nothing else: `{"issue": <num>, "state": "merged|stopped|failed",
> "pr_url": ..., "merge_sha": ..., "discussion_items": [...],
> "blocked_reason": ...}`. Details belong in the worktree and the PR, not
> the report.

Never inline issue bodies, specs, or plans into a dispatch prompt — the
child fetches its own issue; the worktree is the shared memory.

## 4. Wait on notifications — never poll

Background agents notify on exit. Do not `sleep`, run no-op commands, or
re-check task state on a loop; each poll is a full model turn. On each
notification: update the ledger entry, record `discussion_items` verbatim,
dispatch the next queued issue if a slot is free.

**Budget guard:** if an agent has been silent past a wall-clock budget
(default 90 min; `orchestration.agentBudgetMinutes` overrides), surface it
to the user with its issue number and worktree path for inspection — don't
silently wait forever, and don't kill it on your own.

## 5. Failure policy

- **Content-level stops are verdicts, not errors** — wrong issue type,
  existing PR/worktree found in pre-flight, fog-gate abort. Record the
  child's stated reason verbatim in the ledger and never retry.
- **`fogged` is a verdict too** — never retried in this run; it clears when
  the decision tickets blocking it close.
- **Transient failures** (CI flake, network, harness death) → retry the
  issue once with a fresh agent; then record `failed`.
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
