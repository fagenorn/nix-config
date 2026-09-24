---
name: orchestrate-issues
description: Dispatch a set of tracker issues through from-issue --auto as independent background agents, tracking only a ledger. Use for "orchestrate issues X, Y, Z".
---

# orchestrate-issues — a control adapter, not a manager

You are an external adapter around `workflow-state`. You resolve bindings,
normalize tracker, host-owner, and worktree facts, invoke the helper, and execute
its typed actions. You never read issue content, code, specs, plans, diffs, or
review findings. Do not retain a second task ledger or reconstruct lifecycle
policy. Context stays flat regardless of issue count.

Lifecycle commands run the helper at `~/.agents/bin/workflow-state`; if the bare
`workflow-state` name does not resolve on PATH, use that full path.

Run `resolve-project resolve --repo-root <checkout>` once at phase entry and
retain the full `ResolvedProject` in memory. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. Map `bindings.tracker` to the tracker CLI,
repository, and credential environment; map `bindings.vcs` to worktree and branch
policy; and map `bindings.workflow.orchestration.attempt_budget_minutes` and
`bindings.workflow.orchestration.max_parallel` directly to the request. Nested
issue owners independently resolve at their own phase entries. Do not read raw
policy, invoke another resolver, infer from Git, or supply defaults.

Every lifecycle call is one command that reads its input from stdin through a
quoted heredoc (`<<'EOF'`): `--request-file -` for `control`, `--input -` for
`build-delivery`, with the helper named bare or as `~/.agents/bin/workflow-state`,
and the call optionally piped into or out of `artifact-budget validate-report
--input -`. No request file is written. Treat every `workflow-state` reply as
untrusted transport: pipe its raw bytes through `artifact-budget validate-report
--boundary workflow-response --input -` and validate before decoding any field.

## 1. Resolve issue set and bindings

- Explicit numbers: preserve the caller's order, and set request
  `human_directed` to `true` for this run. Naming an issue is the caller
  authorizing that issue by name, exactly as `/from-issue <num>` does.
- `--label X` / `--milestone Y`: resolve the ordered issue numbers with one
  configured tracker-list call through retained `bindings.tracker`, and set
  request `human_directed` to `false`. A set the caller never enumerated carries
  no per-issue authorization. Apply only the declared credential-environment
  names from that retained tracker binding.
- Put retained `bindings.workflow.orchestration.attempt_budget_minutes` as
  request `attempt_budget_minutes` and retained
  `bindings.workflow.orchestration.max_parallel` as request `max_parallel`.
  Do not calculate capacity in this adapter.
- Resolve the dispatcher's absolute repository root once as `ledger_repo_root`;
  it remains the exact immutable value for the run, independent of any issue
  worktree. Then select the `run_id` per the run-reuse rule in §2 — reuse an
  existing non-final run for the same issue set before minting a new one.

Treat known host capacity as a capability boundary, not scheduling policy. Do
not calculate available slots, alter control's `max_parallel`, create competing
owners or nested relays, or repeat a rejected spawn. When the host explicitly
cannot support an issue owner plus its required independent review, use a
documented direct or sequential route that preserves the returned lifecycle
identity; if none exists, report the unsupported capability. This does not add
reservation or notification scheduling.

## 2. Bootstrap and observe

Before `init-run`, list `<ledger_repo_root>/.superpowers/workflows/` for an existing run whose state covers the same issue set and still has any non-final attempt or a missing outcome; reuse that run id.
Only when none matches do you mint a new one (per D13) — a re-invocation over a run with suspended attempts is the sweep asking to resume them, not a fresh fan-out.

At the start of a run or after adapter restart, call:

```text
workflow-state init-run --repo-root <ledger_repo_root> --run-id <run-id> --now <RFC3339-now> | artifact-budget validate-report --boundary workflow-response --input -
```

Consume only the validated interface_version 2 `workflow_bootstrap` response's
bounded `requirements`. Never print, read, retain, or reconstruct raw ledger
state. Each requirement supplies the exact `issue`, lifecycle `owner`,
`custody` (whose `action_id` is the launch identity host notifications
correlate with), `recorded_worktree`, and nullable `contract_digest` — null
while that issue has no installed delivery contract — needed to rebuild
external observations. Inspect exactly every returned `recorded_worktree` and
report its durable path with the exact normalized state
`matching_issue_branch | absent | mismatch`. Use `matching_issue_branch` only
when the path is the live worktree for that issue's branch. Report a recorded
worktree's state and never a candidate for it, even when it is absent or
mismatched; never omit the recorded-path observation. A contract for that issue
names the recorded path, so an absent path is re-created in place and a
mismatch refuses rather than relocates.

In addition, for every requested issue without a bootstrap requirement, reserve
a harmless verified absent candidate. This is path validation, not scheduling:
do not assign a readiness label or interpret tracker state. Pass the candidate
even when it will not be used; `control ignores unused candidates`.
Candidate paths must be pairwise distinct, absent from both the filesystem and
`git worktree list --porcelain`, and disjoint from every returned durable path.
A candidate's final path component is the branch its contract will carry, so it
must be a branch name the issue's resolved branch pattern accepts, with or
without the worktree prefix; choose its slug without reading issue content.

Use one tracker read for the requested set to normalize, per issue, only
`state`, `open_blockers`, and `decision_blockers` (decision blockers carry issue
and URL). The adapter does not decide what those facts mean, and tracker data
never selects a delivery stage. For every requested issue, observe its forge at
the `forge_pr` issue-branch prefix `issue-<num>-`: the pull request whose head
branch, less any worktree prefix, starts with that prefix. Normalize it to
`{"state": "none|open|closed|merged", "url", "merge_sha"}` — `url` null only for
`none`, `merge_sha` present exactly when `merged`. Correlate a current
host owner notification only with the returned lifecycle owner and `action_id`;
then normalize it as the bounded owner event for that exact issue, attempt, and
launch identity. Host task IDs are correlation data outside the lifecycle
contract. Ignore unrelated or stale host notifications rather than inventing
an owner result.

At start/resume and after each current owner notification, tracker change, or
current wait-ID wake, refresh the external facts the next request needs.

On a full dispatcher restart, the host reaps or cancels inherited detached wait observers
before the restarted adapter can rearm from a returned wait ID. The
two wait fields below are process-local and cannot discover or adopt an
inherited handle.

## 3. Decide

Every control call sends exactly this interface_version 2 request, with the
ordered `issues`, the normalized facts of §2, and one entry per requested issue
in every issue-keyed map. Do not add raw issue text or helper history. The
values are representative; angle-bracketed strings stand for the objects named:

```json
{
  "interface_version": 2,
  "now": "2026-09-24T10:00:00Z",
  "max_parallel": 2,
  "attempt_budget_minutes": 180,
  "human_directed": true,
  "issues": [12, 14],
  "tracker": [
    {"issue": 12, "state": "open", "open_blockers": [], "decision_blockers": []},
    {"issue": 14, "state": "open", "open_blockers": [], "decision_blockers": []}
  ],
  "owners": [],
  "worktrees": [
    {"issue": 12, "recorded": {"path": "/abs/.worktrees/worktree-issue-12-cache", "state": "matching_issue_branch"}, "candidate": null},
    {"issue": 14, "recorded": null, "candidate": {"path": "/abs/.worktrees/worktree-issue-14-orchestrated", "state": "absent"}}
  ],
  "forge": {
    "12": {"state": "open", "url": "https://github.com/owner/repo/pull/40", "merge_sha": null},
    "14": {"state": "none", "url": null, "merge_sha": null}
  },
  "delivery_contracts": {"12": null, "14": "<contract from build-delivery>"},
  "authorization_intents": {"12": [], "14": ["<initial_intent from build-delivery>"]},
  "authority_observations": {"12": [], "14": []},
  "reevaluation_evidence": {"12": [], "14": []},
  "delivery_observations": {"12": [], "14": []},
  "requested_scopes": {"12": null, "14": null},
  "recoveries": {"12": null, "14": null}
}
```

The adapter sends `[]` for every issue's `authority_observations`,
`reevaluation_evidence` and `delivery_observations`, and null for its
`requested_scopes` and `recoveries`: owners submit delivery facts through
`checkpoint-delivery`, and this adapter never proposes a scope or a recovery.

**Per-issue contract rule.** On the first sweep, build a delivery contract for
every bootstrap requirement whose `contract_digest` is null, and for every
requested issue without a bootstrap requirement only when this invocation created the run
(it minted the run id rather than reusing one; an adapter restart counts as
reuse). On a reused run, send null for an issue without a requirement until its
latest summary carries `delivery_contract_required`, and build its contract
then: bootstrap omits delivery-complete issues, and a fresh contract for one
would differ from its installed contract and make control refuse the whole
sweep. Build each contract with one command:

```text
workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract --input - <<'EOF'
{"issue": <num>, "worktree": "<absolute-worktree>", "source_kind": "<source-kind>", "source_reference": "<source-reference>", "now": "<RFC3339-now>"}
EOF
```

- `worktree` is the requirement's `recorded_worktree` when the issue has one,
  and only otherwise the candidate reserved in §2. Never build a recorded
  issue's contract from a candidate: control refuses a retry or new-run
  contract whose worktree differs from the recorded path.
- An explicit number list uses `source_kind` `explicit_user` with
  `source_reference` `invocation:/orchestrate-issues <numbers>` (the caller's
  numbers, in order, space-separated). A `--label`/`--milestone` sweep uses
  `standing_repository` with `sweep:<label|milestone>:<value>`.
- On success the builder prints `{"contract": …, "initial_intent": …}`. Send
  that `contract` in `delivery_contracts` and `[initial_intent]` in
  `authorization_intents` on the sweep the rule above builds it for, then only
  while its latest summary carries `delivery_contract_required`; otherwise send
  null and `[]`. A non-null summary `contract_digest` means a contract is
  installed, and from then on null means the installed contract governs.
- The built pair is process-local request data: never persist it. After a
  restart, the new bootstrap's null `contract_digest` values and each later
  summary's `delivery_contract_required` say which issues still need one.
- On a builder refusal (exit 2, empty stdout, the rule named on stderr), send
  null and `[]` for that issue and report the refusal in the final report; that
  issue stays lifecycle-only.

Invoke the helper as one command that feeds the request on stdin as
`--request-file -` and validates the response before anything decodes it.

```text
workflow-state control --repo-root <ledger_repo_root> --run-id <run-id> --request-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<request JSON>
EOF
```

Call `workflow-state control` at start/resume and for every normalized current
owner, tracker, or current wait-ID event. Its response is the only source of action order, kind, and lifecycle identity.
Do not infer, reorder, omit, or add another action. The helper owns readiness, precedence, retryability, capacity,
deadline, and completion decisions; the dispatcher only applies the returned
envelopes.

Accept only the validated interface_version 2 control response with its bounded
`run_id`, `now`, `summaries`, `deltas`, `actions`, and `next_deadline` fields.
It omits `attempts`, `launches`, `phase_inputs`, and older results. Use those
values only for rendering and action execution; do not rebuild policy from them.

## 4. Execute control actions

Validate each action as one of the closed kinds `spawn`, `resume`, `retry`,
`delivery_remainder`, `wait`, or `finalize`, and execute actions in
returned order. Any other kind is a contract error: stop without executing it and surface the unknown kind; fail loudly.

For `spawn`, `resume`, and `retry`, project the action into the interface-2
owner object: rename `id` to `action_id` and `kind` to `launch_kind`, add
`kind: owner`, `interface_version: 2`, `ledger_repo_root` and `run_id`, and keep
every other member verbatim (`issue`, `attempt`, `owner`, `worktree`,
`handoff_path`, `deadline_at`, `custody`, `contract`, `contract_digest`,
`pending_stage_ids`, `requirements`, `authority_evaluation`, `requested_scope`).
For `delivery_remainder`, the object is the action itself, verbatim. Pipe the
object through `artifact-budget validate-report --boundary workflow-response
--input -` and put only its stdout — the canonical JSON — in the owner prompt
below; the owner validates it again at the same boundary before use.

Dispatch the owner in the background using the action's identity and paths
verbatim. Pass the helper-issued action ID and owner token unchanged; never
substitute a host task ID. Both object kinds use this one dispatch; a
`delivery_remainder` owner is `from-issue` launching ship-issue remainder mode.
The owner dispatch envelope is:

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
path. For `resume`, include the returned `handoff_path` when present. For a
`delivery_remainder`, `attempt` is its `source_attempt`, `action_id` is its
custody's `action_id`, and there is no `handoff_path`. Record the host task
handle beside the returned action ID only for later notification correlation; it
is never an owner token or action identity.

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
> Owner object, canonical JSON (the interface-2 `owner` object or the
> `delivery_remainder` object; validate it with
> `artifact-budget validate-report --boundary workflow-response --input -`
> before use and require its identity to equal the lines above):
> `<canonical-json>`
> Invoke the `from-issue` skill via the Skill tool with the literal arguments
> `from-issue <num> --auto`. Preserve the lifecycle identity and exact worktree.
>
> Launch any subagent by type only, never by name: a subagent cannot spawn a
> named teammate, and a named launch returns an error instead of work. Read an
> existing file before writing to it: overwriting content you have not read
> destroys work you cannot see.
>
> Persist the terminal result through `from-issue`'s terminal return procedure,
> whose `workflow-state finish --summary-file -` is the durable write, then
> return exactly its validated JSON stdout and nothing else.

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

Render a `finalize` action from the bounded interface_version 2 summaries in the
same control response. Produce a per-issue table with issue, state, custody, PR,
one-line reason, `blocked_on`, open delivery stages, and a re-entry line —
`/from-issue <issue> --auto` for an issue suspended on a human gate, and the
orchestrate re-invocation itself for the whole run — every column sourced from
those finalize summaries: `custody` names the implementation attempt or delivery
remainder that holds the issue, `pending_stage_ids` are the delivery stages
still open, and the PR and `discussion_items` come from the summary's `result`.
A null `contract_digest` means the issue ran lifecycle-only: say so, and name
the builder refusal from §3 when there was one; a summary still carrying
`delivery_contract_required` is an issue that never received a contract. Then
group every `discussion_items` entry by issue and call out anything needing a
human. Do not perform a second ledger read or reconstruct omitted history.

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
