---
name: orchestrate-issues
description: Dispatch a set of tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".
argument-hint: "<issue numbers... | --label X | --milestone Y>"
---

# orchestrate-issues — a control adapter, not a manager

You are an external adapter around `workflow-state`. You resolve bindings,
normalize tracker, host-owner, and worktree facts, invoke the helper, and execute
its typed actions. You never read issue content, code, specs, plans, diffs, or
review findings. Do not retain a second task ledger or reconstruct lifecycle
policy. Context stays flat regardless of issue count.

Lifecycle commands run the helper at `~/.agents/bin/workflow-state`; if the bare
`workflow-state` name does not resolve on PATH, use that full path.

## 1. Resolve issue set and bindings

- Explicit numbers: preserve the caller's order, and set request
  `human_directed` to `true` for this run. Naming an issue is the caller
  authorizing that issue by name, exactly as `/from-issue <num>` does.
- `--label X` / `--milestone Y`: resolve the ordered issue numbers with one
  configured tracker-list call, and set request `human_directed` to `false`. A
  set the caller never enumerated carries no per-issue authorization. The
  tracker CLI and `unsetGithubToken` come from `.claude/skills.config.json`,
  through the same bindings used by `from-issue`.
- Call `~/.agents/bin/resolve-bindings` once for both orchestration limits. Put
  the resolved `agentBudgetMinutes` as request `attempt_budget_minutes` and the
  resolved `maxParallel` as request `max_parallel`. Do not copy either default
  or calculate capacity in this adapter.
- Resolve the dispatcher's absolute repository root once as `ledger_repo_root`;
  it remains the exact immutable value for the run, independent of any issue
  worktree. Then select the `run_id` per the run-reuse rule in §2 — reuse an
  existing non-final run for the same issue set before minting a new one.

## 2. Bootstrap and observe

Before `init-run`, list `<ledger_repo_root>/.superpowers/workflows/` for an existing run whose state covers the same issue set and still has any non-final attempt or a missing outcome; reuse that run id.
Only when none matches do you mint a new one (per D13) — a re-invocation over a run with suspended attempts is the sweep asking to resume them, not a fresh fan-out.

At the start of a run or after adapter restart, call:

```text
workflow-state init-run --repo-root <ledger_repo_root> --run-id <run-id> --now <RFC3339-now>
```

Consume only the strict version-1 response's bounded `requirements`. Never
print, read, retain, or reconstruct raw ledger state. Each requirement supplies
the exact `issue`, `attempt`, lifecycle `owner`, `action_id`, and
`recorded_worktree` needed to rebuild external observations. Inspect exactly
every returned `recorded_worktree` and report its durable path with the exact
normalized state `matching_issue_branch | absent | mismatch`. Use
`matching_issue_branch` only when the path is the live worktree for that issue's
branch. When a returned path is absent or mismatched, also verify and report a
collision-free absent replacement candidate; never omit the recorded-path
observation.

In addition, for every requested issue without a bootstrap requirement, reserve
a harmless verified absent candidate. This is path validation, not scheduling:
do not assign a readiness label or interpret tracker state. Pass the candidate
even when it will not be used; `control ignores unused candidates`.
Candidate paths must be pairwise distinct, absent from both the filesystem and
`git worktree list --porcelain`, and disjoint from every returned durable path.

Use one tracker read for the requested set to normalize, per issue, only
`state`, `open_blockers`, and `decision_blockers` (decision blockers carry issue
and URL). The adapter does not decide what those facts mean. Correlate a current
host owner notification only with the returned lifecycle owner and `action_id`;
then normalize it as the bounded owner event for that exact issue, attempt, and
launch identity. Host task IDs are correlation data outside the lifecycle
contract. Ignore unrelated or stale host notifications rather than inventing
an owner result.

For every control call, write one temporary absolute JSON request containing
exactly the version-1 fields `interface_version`, `now`, `max_parallel`,
`attempt_budget_minutes`, `human_directed`, ordered `issues`, and the
normalized `tracker`, `owners`, and `worktrees` arrays. Do not add raw issue
text or helper history.
At start/resume and after each current owner notification, tracker change, or
current wait-ID wake, refresh the external facts needed by that request.

On a full dispatcher restart, the host reaps or cancels inherited detached wait observers
before the restarted adapter can rearm from a returned wait ID. The
two wait fields below are process-local and cannot discover or adopt an
inherited handle.

## 3. Decide

Invoke the helper with a new absolute temporary request file beneath
`${TMPDIR:-/tmp}`:

```text
workflow-state control --repo-root <ledger_repo_root> --run-id <run-id> --request-file <absolute-json-path>
```

Call `workflow-state control` at start/resume and for every normalized current
owner, tracker, or current wait-ID event. Its response is the only source of action order, kind, and lifecycle identity.
Do not infer, reorder, omit, or add another action. The helper owns readiness, precedence, retryability, capacity,
deadline, and completion decisions; the dispatcher only applies the returned
envelopes.

Accept only the strict version-1 control response with its bounded `run_id`,
`now`, summaries, deltas, actions, and next-deadline fields. It omits `attempts`,
`launches`, `phase_inputs`, and older results. Use those values only for
rendering and action execution; do not rebuild policy from them.

## 4. Execute control actions

Validate each action as one of the closed kinds `spawn`, `resume`, `retry`,
`wait`, or `finalize`, and execute actions in returned order. Any other kind is a contract error: stop without executing it and surface the unknown kind; fail loudly.

For `spawn`, `resume`, and `retry`, dispatch the returned owner in the background
using the action's identity and paths verbatim. Pass the helper-issued action ID
and owner token unchanged; never substitute a host task ID. The owner dispatch
envelope is:

```text
--repo-root <ledger_repo_root>
ledger_repo_root=<ledger_repo_root>
run_id=<run-id>
issue=<issue>
attempt=<attempt>
owner=<owner-token>
action_id=<action-id>
worktree=<absolute-worktree>
handoff_path=<exact-handoff-path>  # only when non-null
from-issue <num> --auto
```

The `ledger_repo_root` line carries the exact immutable value resolved for the
run and is independent of any issue worktree. The worktree is the exact returned
path. For `resume`, include the returned `handoff_path` when present. Record the
host task handle beside the returned action ID only for later notification
correlation; it is never an owner token or action identity.

<!-- agent-dispatch: id=orchestration-issue-owner role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high", run_in_background=true) launches the issue owner in a fresh context with this entire prompt:

> Immutable lifecycle envelope:
> `--repo-root <ledger_repo_root>`
> `ledger_repo_root=<ledger_repo_root>`
> `run_id=<run-id>`
> `issue=<issue>`
> `attempt=<attempt>`
> `owner=<owner-token>`
> `action_id=<action-id>`
> `worktree=<absolute-worktree>`
> `handoff_path=<exact-handoff-path>`
> Include `handoff_path` only when non-null.
> Invoke the `from-issue` skill via the Skill tool with the literal arguments
> `from-issue <num> --auto`. Preserve the lifecycle identity and exact worktree.
> Persist the compact result with `workflow-state finish`, then return exactly
> its JSON stdout and nothing else.

Never inline issue bodies or any content artifact in that prompt.

For `wait`, adapter state consists only of `current_wait_id` and
`current_wait_handle`:

- If the response carries the same wait ID as `current_wait_id`, keep the
  installed handle; the adapter does not arm another observer.
- For a different ID, save the old `current_wait_id` and `current_wait_handle` pair,
  publish the new wait ID with the handle marked uninstalled, cancel the old handle,
  then arm and store the new one-shot observer. This ordering must never leave the new wait ID paired with the old handle.
- A missing or already exited old handle is an idempotent cancellation outcome;
  continue to arm the replacement.
- On unexpected cancellation failure, restore the old `current_wait_id` and `current_wait_handle` pair,
  do not arm the replacement, and fail loudly. The next identical response retries replacement.
- If arming fails after cancellation, clear `current_wait_id`, clear `current_wait_handle`,
  surface that no wake is installed, and fail loudly.
- Each wake carries its wait ID; ignore it unless it equals `current_wait_id`;
  a stale wake cannot trigger control or disturb the replacement observer.

Arm the one-shot observer for the returned wake conditions and its `deadline_at`.
control never returns a deadline-less wait; every wait carries deadline_at, and when nothing can proceed without a human, control returns finalize instead.
No polling or repeated short sleeps are allowed.

For `finalize`, first clear `current_wait_id`, then cancel the outstanding handle
(a missing/already-exited handle is harmless), and clear
`current_wait_handle`. Do not issue another control call merely to prepare the
report.

## 5. Final report

Render a `finalize` action from the bounded summaries in the same control response.
Produce a per-issue table with issue, state, PR, one-line reason, `blocked_on`,
and a re-entry line — `/from-issue <issue> --auto` for an issue suspended on a
human gate, and the orchestrate re-invocation itself for the whole run — every
column sourced from those finalize summaries. Then group every `discussion_items`
entry by issue and call out anything needing a human. Do not perform a second
ledger read or reconstruct omitted history.

An `expired` delta is an interruption, not a verdict on the work: it consumes
no attempt, and the attempt number never advances because of it. Three things
can follow it. Usually it is a `resumed` on the same attempt in this same
sweep, or a `suspended` summary that a later eligible sweep resumes — eligible
meaning that sweep finds the tracker neither closed nor blocked, a dispatch
slot free, and that attempt's recorded worktree observed. But at the
anti-zombie bound, where the attempt has already been parked at the same phase
too many times in a row, the expiry ends the work instead of parking it: that
delta's own state reads `stopped`, the attempt is a `stopped(stalled)`
terminal, and no resume follows in this or any later sweep. A parked
suspension arms no deadline of its own, so once nothing else in the run is
still running the sweep renders `finalize` and the later sweep is the one a
re-invocation starts; report such an issue as paused, not as progressing, and
report a `stopped(stalled)` issue as finished. An expiry is never `retried`
and never `retry_refused`, so never report it as a spent attempt.

## Notes

Claude-only skill: it depends on background agents and host task notifications,
so it lives outside the shared skills tree. Codex users continue to run
`/from-issue` per issue.
