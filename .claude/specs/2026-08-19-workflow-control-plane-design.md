# Deepen workflow-state into the orchestration control plane

Issue: https://github.com/fagenorn/nix-config/issues/47

Amends, without replacing, the durable lifecycle defined by
`2026-08-13-durable-workflow-lifecycle-design.md` and hardened by
`2026-08-17-workflow-lifecycle-hardening-design.md`.

## Problem

The durable workflow ledger remembers what happened, but the Claude dispatcher still has to
reconstruct what should happen next. It reads full attempt histories, counts occupied slots,
chooses resume before retry, decides whether a recorded worktree can be reused, calculates the
earliest deadline, arms and re-arms wake-ups, and decides when the run has drained. Those rules are
spread across prose and are coupled to the dispatcher's conversation state. A restart therefore
asks a model to rebuild lifecycle policy from raw records before it can safely act.

This is a shallow module. `workflow-state` already owns locking, durable attempt identity, fixed
deadlines, provisional expiry, late owner results, the two-attempt cap, worktree retention, and
phase-budget decisions, but its dispatcher-facing interface exposes those details rather than
providing leverage over them. `orchestrate-issues` has to know almost as much as the helper's
implementation.

The failure is visible in recent multi-issue runs: a late success can race a synthetic expiry; a
silent owner needs a retry; that retry may need the existing worktree; two owners can finish at
once; and an unrelated issue must keep moving while all of that happens. The current tests prove
the individual ledger transitions, but not that one restarted dispatcher can follow a compact,
deterministic control-plane response through the whole sequence.

The desired interface must not absorb the external world. GitHub queries, worktree inspection,
one-shot waiting, and background owner spawning remain outside the helper. The helper consumes
normalized facts from those adapters, applies lifecycle policy atomically to durable state, and
returns the side effects the dispatcher should perform.

## Solution

Add one dispatcher-facing `control` command to the existing `workflow-state` module:

```text
workflow-state control \
  --repo-root <ledger_repo_root> \
  --run-id <run-id> \
  --request-file <absolute-json-path>
```

`control` is the external seam for orchestration. In one locked transaction it validates a
versioned observation request, incorporates owner and deadline events, applies resume/retry/queue
precedence, persists every accepted launch before exposing it, and returns a compact versioned
response. The response has current issue summaries, only the transitions made by this invocation,
typed next-action envelopes, and the earliest outstanding deadline. It never returns attempts,
launch histories, phase inputs, or prior results.

The existing `init-run`, `progress`, and `finish` commands remain. They are distinct lifecycle
operations: run creation plus bounded restart bootstrap, owner phase-boundary state, and owner
terminal truth. `init-run` no longer prints the raw ledger; it returns a compact versioned
projection naming only the current recorded worktree and owner requirement for each issue that has
an attempt. Dispatcher-side `launch` and `reconcile` are removed from the public CLI after their
in-repository consumers and tests move to `control`; their behavior becomes implementation inside
the deeper module. The durable ledger stays at schema version 1, so existing run files remain
readable and no persisted state migration is introduced.

`orchestrate-issues` becomes an adapter loop with no lifecycle decision tree:

1. Invoke `init-run` and read its bounded current requirements.
2. Query the tracker, inspect exactly the returned worktrees, and verify an absent candidate for
   every requested issue without a bootstrap requirement plus every absent/mismatched returned
   path.
3. Normalize those facts and any owner-exit notification into one request.
4. Invoke `workflow-state control`.
5. Spawn owners for `spawn`, `resume`, and `retry` envelopes; perform the one-shot wait described
   by `wait`; or render the final report described by `finalize`.
6. Re-enter only on an owner notification, a tracker change/resume, or the current returned wait ID.

The helper does not call GitHub, inspect Git worktrees, spawn agents, sleep, poll, merge pull
requests, or change permissions. Its only side effect remains the atomically locked ledger.

## Decisions

### Module and seam

The deep module is the durable lifecycle control plane. Its interface consists of four commands:

- `init-run` creates or validates the run ledger and returns its bounded bootstrap projection.
- `control` consumes normalized dispatcher observations and returns orchestration actions.
- `progress` persists the existing owner-side phase-budget decision.
- `finish` persists the existing compact owner result, including truthful late results.

The seam is the CLI plus JSON files/stdout, which is already the interface used by skills and by
tests. The implementation may retain internal transition functions, but callers and tests do not
reach around `control` to invoke dispatcher-specific launch or reconciliation primitives.

The helper remains a Python standard-library program. It needs no tracker adapter, Git library,
queue, daemon, background thread, or new package. Its current lock and atomic replace transaction
still serialize concurrent owner finishes with control decisions.

### Versioned init-run bootstrap

`init-run` keeps its existing CLI arguments. Version 1 prints exactly:

```json
{
  "interface_version": 1,
  "run_id": "orchestrate-47-51",
  "requirements": [
    {
      "issue": 47,
      "attempt": 1,
      "owner": "47:1",
      "action_id": "47:1:1",
      "recorded_worktree": "/absolute/worktree-issue-47"
    }
  ]
}
```

The top-level object and every requirement item are strict closed shapes. `requirements` contains
one item per durable issue that has an attempt, sorted by positive issue number, and each item is a
projection of only the latest attempt. A fresh run returns an empty list. The projection never
contains attempts, launches, deadlines, phase fields, handoffs, results, result provenance, or
prior owners/worktrees. `action_id` is the current launch handle, not launch history; together with
`owner` it lets a restarted adapter correlate and normalize a host notification. JSON remains
canonical and newline-terminated.

On restart, the dispatcher already has the requested issue set from its invocation. It calls
`init-run`, inspects exactly each returned `recorded_worktree`, and reports that path's normalized
state in the next control request. For a returned path that is absent or mismatched, it also
reserves a verified absent candidate. For every requested issue with no bootstrap requirement, it
reserves and reports a harmless verified absent candidate without first classifying that issue as
ready, blocked, fogged, or closed. Extra candidates that policy does not use are valid observations
and `control` ignores them. The helper still validates every supplied recorded path against the
ledger inside `control`; the projection is discovery, not authority.

### Versioned control request

The request is a strict JSON object. `interface_version` versions the caller contract independently
from the durable `schema_version`. Version 1 has exactly these top-level fields:

```json
{
  "interface_version": 1,
  "now": "2026-08-19T12:00:00Z",
  "max_parallel": 2,
  "attempt_budget_minutes": 180,
  "issues": [47],
  "tracker": [
    {
      "issue": 47,
      "state": "open",
      "open_blockers": [],
      "decision_blockers": []
    }
  ],
  "owners": [
    {
      "event_id": "task-47-a1-exit",
      "issue": 47,
      "attempt": 1,
      "launch": 1,
      "state": "unavailable"
    }
  ],
  "worktrees": [
    {
      "issue": 47,
      "recorded": {
        "path": "/absolute/worktree-issue-47",
        "state": "matching_issue_branch"
      },
      "candidate": null
    }
  ]
}
```

The fields mean:

- `now` is the injected decision instant. All deadline comparisons and newly persisted launch
  times use it; the command never consults the wall clock itself.
- `max_parallel` and `attempt_budget_minutes` are positive integers resolved by the caller from the
  authoritative project bindings on every request. An existing attempt keeps its persisted fixed
  deadline; the budget value applies only when `control` creates a fresh attempt.
- `issues` is the requested run order, with unique positive issue numbers. It is the stable
  scheduling tie-breaker and bounds every returned collection.
- `tracker` has exactly one item per requested issue. `state` is `open | closed`.
  `open_blockers` contains the already-normalized numbers of blockers that are currently open.
  `decision_blockers` contains zero or more exact `{ "issue": <positive-int>, "url": <string> }`
  objects for open `wayfinder:*` decisions. The helper decides blocked/fogged readiness from these
  facts; it does not know how GitHub represents edges or labels.
- `owners` contains only new host notifications. Version 1 admits one tagged state,
  `unavailable`, meaning the named attempt's process exited without a durable terminal result.
  `event_id` is a non-empty diagnostic identity and `launch` is the positive launch ordinal from
  the dispatch action that created the unavailable host process. A stale event for an older
  attempt or launch is ignored. For the latest active attempt, an event naming its current launch
  makes it eligible for one resume. The resume appends the next durable launch ordinal at `now`, so
  replaying the same observation cannot append or emit another launch. An event naming a future or
  nonexistent launch fails loudly.
- `worktrees` contains only filesystem facts, never filesystem instructions. `recorded` is null
  when no attempt owns a path; otherwise its path must equal the latest attempt's durable worktree
  and its state is `matching_issue_branch | absent | mismatch`. `candidate` is null or the exact
  `{ "path": <absolute-path>, "state": "absent" }` path the dispatcher verified is free in both
  the filesystem and `git worktree list`. A ready action that needs a candidate and lacks one fails
  loudly instead of choosing a path inside the helper. Candidate paths consumed by distinct
  accepted actions must be pairwise distinct, and no consumed candidate may equal another issue's
  durable recorded path. The helper checks these exclusivity rules against the locked ledger and
  the complete proposed action set before any mutation.

Unknown versions, fields, enum members, duplicate issue observations, non-monotonic timestamps,
relative paths, mismatched recorded paths, and incomplete facts required by a ready action fail
without rewriting the ledger. Extra tracker issues or worktree observations outside `issues` also
fail. Empty `owners`, a worktree omission for an issue that needs no action, and a verified absent
candidate for a requested issue that policy does not dispatch are valid.

If two otherwise-ready issues would consume the same candidate, or a candidate-consuming action
would alias another issue's durable recorded worktree, `control` rejects the complete request and
leaves the ledger byte-unchanged. Duplicate unused candidate facts remain harmless; exclusivity is
about paths selected for accepted actions, not adapter readiness classification.

One narrow replay exception preserves the identical-request guarantee: a candidate that was absent
in the request may equal the latest attempt's now-recorded worktree only when that attempt's first
launch was created by this same request instant at that exact path, the latest attempt remains
active, no current `unavailable` observation names that launch, and accepting the fact can produce
no lifecycle transition or dispatch for the issue. The helper treats it only as the already-
consumed candidate observation and emits no duplicate action. A wrong instant or path, a same-
instant terminal attempt, a current-unavailable attempt, or any other durable collision remains
invalid. A request that could resume, retry, or otherwise dispatch must supply current recorded or
candidate facts; this exception does not weaken worktree validation for a new action.

### Versioned control response

Version 1 returns exactly these top-level fields:

```json
{
  "interface_version": 1,
  "run_id": "orchestrate-47-51",
  "now": "2026-08-19T12:00:00Z",
  "summaries": [],
  "deltas": [],
  "actions": [],
  "next_deadline": null
}
```

Collections follow `issues` order, then attempt number where needed. JSON serialization remains
canonical and newline-terminated so identical snapshots and requests are byte-comparable.

Each `summaries` item has exactly:

```json
{
  "issue": 47,
  "state": "active",
  "attempt": 1,
  "owner": "47:1",
  "worktree": "/absolute/worktree-issue-47",
  "deadline_at": "2026-08-19T15:00:00Z",
  "blockers": [],
  "result": null
}
```

Summary `state` is the closed set `queued | blocked | fogged | active | handed_off | merged |
stopped | failed | closed`. Attempt identity fields are null before any attempt and for a tracker-
closed issue with no attempt. `blockers` is a homogeneous list of exact
`{ "kind": "issue | decision", "issue": <positive-int>, "url": <string-or-null> }` objects;
ordinary issue blockers have a null URL and decision blockers retain their tracker URL. `result` is
null or the one existing compact terminal result for the latest attempt. A summary never contains
`launches`, `prior_attempt`, phase fields, result provenance, or an older attempt.

`deltas` contains only durable transitions performed by this `control` invocation. Each item has
exactly `issue`, `attempt`, `kind`, and `state`. `kind` is the closed set `expired | spawned |
resumed | retried | retry_refused`. Terminal writes performed earlier by `finish`, and tracker
states derived from the request, appear in summaries rather than being replayed as synthetic
deltas. Re-running against the advanced ledger therefore returns no duplicate delta.

There are five action envelopes. Dispatch actions have one common shape:

```json
{
  "id": "47:1:1",
  "kind": "spawn",
  "issue": 47,
  "attempt": 1,
  "owner": "47:1",
  "worktree": "/absolute/worktree-issue-47",
  "handoff_path": null,
  "deadline_at": "2026-08-19T15:00:00Z"
}
```

- `spawn` is the first fresh attempt.
- `resume` is another launch of the latest nonterminal attempt with the same owner and worktree;
  `handoff_path` carries the stored durable handoff when the attempt was handed off.
- `retry` is attempt 2 with a new owner. It uses the recorded path when its normalized state is
  `matching_issue_branch`, otherwise it uses the verified absent candidate.

The helper generates lifecycle owner tokens as `<issue>:<attempt>`. They are not host task IDs.
Action IDs are `<issue>:<attempt>:<launch-ordinal>` within the top-level run identity, so a dispatch
envelope is stable and short. The dispatcher passes the owner token unchanged in the lifecycle
envelope and does not invent attempt identity.

Every response ends its `actions` array with exactly one control action. A waiting run uses:

```json
{
  "id": "wait:2026-08-19T15:00:00Z",
  "kind": "wait",
  "wake_on": ["owner_notification", "tracker_change", "deadline"],
  "deadline_at": "2026-08-19T15:00:00Z"
}
```

If no deadline is armed, the id is `wait:external`, `deadline_at` is null, and `deadline` is absent
from `wake_on`. `next_deadline` equals the wait envelope's deadline and is the minimum deadline of
all current active or handed-off latest attempts. The adapter schedules at most one one-shot wake
for the returned wait ID. On a different returned wait ID, it first publishes the new current ID,
then cancels the old observer and arms/stores the new one; the observer reports its wait ID when it
wakes, and the adapter ignores that wake if the ID is no longer current. Repeating the current wait
ID does not arm a second observer. A missing or already-exited old handle is an idempotent cancel
outcome and does not prevent arming the replacement. Before publishing a new ID, the adapter saves
the old ID/handle pair. If old-observer cancellation then fails unexpectedly, it restores that old
pair, does not arm the replacement, and fails loudly; the next identical response therefore sees
the old ID and may retry replacement instead of deduplicating on a half-installed new ID. If
replacement arming fails after successful/idempotent cancellation, the adapter clears both
`current_wait_id` and `current_wait_handle` (or marks their equivalent state as uninstalled) and
fails loudly that no wake is installed. It never leaves a new ID paired with the old handle.
`finalize` first clears the current ID, then cancels and clears any outstanding observer, so a
racing old wake is stale.

The adapter's wait-handle state is process-local. On a full dispatcher restart, the host is
responsible for reaping or cancelling every inherited detached wait observer before the restarted
dispatcher rearms from the next returned wait ID. This external-edge cleanup is the assumption
under which “at most one one-shot wake” remains truthful across process restarts. The ledger does
not discover or own detached host processes. This is event-driven scheduling, not a polling
interval or a resident daemon.

A drained run uses:

```json
{
  "id": "finalize",
  "kind": "finalize"
}
```

`next_deadline` is null for `finalize`. The dispatcher renders its report from the same response's
summaries, including each current compact result and discussion items. The response is bounded to
one summary per requested issue, at most one current transition per affected attempt, at most
`max_parallel` dispatch actions, and one control action. Durable attempt histories remain in the
ledger and never enter dispatcher context.

### Deterministic transition and action order

Within the single control transaction, policy executes in this order:

1. Validate the full request and current ledger before mutation. Derive the proposed accepted
   actions under the ledger lock and reject before writing if two candidate-consuming actions
   select the same path or one selects another issue's durable recorded path.
2. Treat a durable owner result as authoritative. A matching or stale notification cannot replace
   it. The existing `finish` rules still allow a late owner result to supersede a provisional
   expiry only while that attempt remains the latest.
3. Expire each latest active or handed-off attempt at or after its fixed deadline, using the
   existing provisional `expiry` result source and retained worktree.
4. Derive tracker-closed, fogged, blocked, and queued eligibility from normalized tracker facts.
   These facts suppress a new spawn or retry; they never terminate an already-active attempt,
   whose durable lifecycle remains authoritative until owner finish or expiry.
5. Compute `occupied` as the number of latest `active` attempts that do not have a current
   `unavailable` observation naming their latest launch. Latest `handed_off` attempts and active
   attempts with that current unavailable observation occupy no external-owner slot.
   `available = max(0, max_parallel - occupied)`. Each accepted resume, retry, or spawn consumes one
   available slot. Fill those slots in three passes: resumable attempts, retryable terminal
   attempts, then never-launched queued issues. Each pass preserves `issues` order.
6. Resume a handed-off attempt, or an active attempt with one unconsumed `unavailable` event,
   without changing its attempt number, owner, worktree, original start, or fixed deadline.
7. Retry an `expiry` result or owner-reported `failed` result once. Owner-reported `stopped` is a
   content verdict and is never retried. `merged`, and tracker `closed` or `fogged` when no attempt
   remains nonterminal, are also final for this run. A retry request after attempt 2 persists the
   existing refused/failed outcome and emits `retry_refused`; no third attempt exists.
8. Start queued issues in request order until capacity is full. Failure of one issue never blocks
   an unrelated ready issue.
9. Recompute current summaries and the earliest deadline, then append exactly one `wait` or
   `finalize` action.

Accepted spawn/resume/retry actions are persisted before stdout, retaining the current
launch-before-spawn safety property. A crash after persistence but before host spawning can delay
that attempt until its fixed deadline; it cannot create duplicate work. A pure replay from an
identical copied ledger snapshot and identical request is byte-identical. Repeating `control`
against the already-advanced ledger emits no second launch and returns the then-current wait or
finalize decision. Exactly-once host process creation is not claimed across the CLI/process seam.

### Dispatcher migration

The Claude dispatcher keeps only adapter mechanics and rendering:

- resolve the issue set and configured bindings, placing `maxParallel` in request
  `max_parallel` and `agentBudgetMinutes` in request `attempt_budget_minutes`;
- call `init-run`, then inspect exactly its returned recorded worktree requirements;
- query current tracker state, open blockers, and decision blockers;
- reserve a verified absent candidate for every requested issue with no bootstrap requirement and
  for every returned path observed absent or mismatched, without classifying tracker readiness;
- normalize host owner-exit notifications;
- invoke `control` on start/resume and each event;
- execute dispatch action envelopes in order with the existing background owner prompt;
- replace the one outstanding wait observer by returned wait ID, applying the idempotent-cancel and
  fail-loud arm rules above and ignoring stale wake IDs;
- render the final table and discussion items from a finalize response.

Before a full dispatcher restart enters this loop, its host reaps or cancels inherited detached
wait observers. The restarted adapter does not infer their existence from the ledger or attempt to
adopt them.

It deletes prose that counts attempts, chooses resume versus retry, checks whether expiry permits a
retry, chooses recorded versus candidate worktrees, calculates deadline minima, decides whether to
re-arm, counts occupied slots, or decides whether the run is drained. It does not maintain a second
authoritative task ledger; any local table is a rendering of the latest summaries.

The owner prompt remains compact: immutable ledger root, run, attempt, lifecycle owner token,
worktree, and literal `from-issue <num> --auto`. `from-issue` keeps its Phase 1 exact-path adoption,
phase-budget `progress`, and write-before-notify `finish` behavior. Its handoff text changes only to
say that the dispatcher resumes it from a returned `resume` envelope; owners do not invoke a
dispatcher launch command themselves.

Issue 73 supersedes only the blanket direct-standalone statement in this
paragraph. A direct autonomous `from-issue <issue> --auto` invocation without a
dispatcher envelope now acquires durable lifecycle identity only through
`workflow-state direct-owner`, adopts its exact returned owner identity and
worktree, and returns a terminal replay without entering the owner flow. An
interactive direct invocation remains ledger-free. When an interactive user
explicitly requests durable standalone orchestration, `from-issue` still calls
`init-run`, gathers one issue's normalized tracker/worktree facts, calls
`control` with `max_parallel: 1`, and adopts the returned first `spawn` envelope
as its lifecycle identity and exact Phase-1 worktree. It does not spawn another
owner or issue a second control call for that launch. A non-`spawn` response or
an action for a different issue fails loudly instead of inventing identity.

The deployed orchestrator eval expectations change with the skill contract. They grade normalized
observations, envelope execution, and the absence of hand-assembled precedence rather than pinning
the retired `reconcile`/`launch` narrative.

### Scenario replay

One deterministic CLI scenario uses injected timestamps and temporary worktrees to replay the
multi-issue failure pattern in a single run:

1. Control starts two issues and returns the earliest deadline while another ready issue waits.
2. The first owner reports `merged` after its deadline through `finish`; the result remains merged.
3. The second owner stays silent. Control expires it, emits a retry with a new owner and the same
   normalized matching worktree, and uses the freed capacity for an unrelated queued issue.
4. The retried owner and another active owner finish concurrently. Reopening the ledger preserves
   both results.
5. Control observes both completions, continues the unrelated issue set, and eventually returns
   one finalize action with one current summary per issue.
6. Replaying the same control request against the advanced state emits no duplicate dispatch;
   replaying from a copied pre-decision state produces the same canonical action IDs, deltas, next
   deadline, and summaries.

The scenario asserts that no response contains `attempts`, `launches`, `phase_inputs`, or older
results. Focused cases separately pin malformed observation rejection, resume-before-retry-before-
spawn ordering, max-parallel accounting, handed-off resume, owner-stopped non-retry, second-failure
refusal, tracker blockers/fog, no-deadline waiting, and finalize behavior.

## Test seams

- **Control CLI seam:** invoke `init-run`, `control`, `progress`, and `finish` as subprocesses with
  request/result files and injected times. Assert the exact bounded bootstrap projection, canonical
  stdout, exit status, and typed action envelopes. Bootstrap checks include the latest launch
  identity after resume and retry. Consumed-candidate checks distinguish actionless replay from
  wrong-instant, wrong-path, terminal, and current-unavailable requests that need current facts.
  A two-ready-issue request with distinct observations sharing one candidate proves atomic,
  byte-unchanged exclusivity rejection. This is the same interface the skills use.
- **Durable filesystem seam:** reopen `state.json` after every decision and run concurrent `finish`
  subprocesses. Assert the helper persisted accepted actions before emitting them and retained both
  concurrent outcomes. Tests do not call internal transition functions.
- **Scenario seam:** extend the existing workflow-state test module with the combined replay above,
  so the repository's existing `agent-workflow-tests` recipe discovers it without new wiring.
- **Skill contract seam:** replace assertions for manual reconcile/launch/retry/deadline prose with
  assertions that the dispatcher normalizes external facts, calls `control`, executes only the five
  action kinds, fails loudly on an unknown kind, replaces/cancels waits by ID, ignores stale wake
  IDs, treats missing/exited cancellation idempotently, restores old adapter state after unexpected
  cancellation failure, reports failed arming truthfully, maps configured limits to their request
  fields, performs restart-host observer cleanup, and does not contain retired policy anchors. Pin
  the minimal `from-issue` handoff wording, its direct/durable standalone routes, and updated
  orchestrator eval expectations.
- **Build seam:** `just agent-workflow-tests` is the deterministic behavioral gate and `just build`
  verifies that the modified helper and skills still distribute through the unchanged Nix module.

## Out of scope

- GitHub or other tracker clients inside the helper, including GraphQL shapes, label parsing, PR
  lookup, merge checks, and issue mutation.
- Git worktree discovery, creation, movement, reset, cleanup, or branch-name inference inside the
  helper. The caller supplies normalized exact-path facts.
- Agent spawning, host task lookup, cancellation, exactly-once process creation, or notification
  transport. The helper owns lifecycle tokens, not host process IDs.
- A polling loop, resident scheduler, queue daemon, long-running helper process, or sleep inside
  `workflow-state`. A wait action describes one event-driven wake horizon.
- Changing phase-budget thresholds or precedence, attempt-budget configuration, late-finish
  authority, the two-attempt cap, compact terminal-result fields, handoff file rules, or worktree
  retention delivered by issues 14 and 33.
- Changing tracker ordering semantics beyond the supplied open-blocker graph, or inferring overlap
  by reading code/specs in the dispatcher.
- Changing CI-required checks, branch protection, merge permissions, agent permission guards,
  release behavior, or adding the workflow suite to CI (tracked separately by issue 37).
- A new durable-ledger schema, migration framework, external event journal, or arbitrary historical
  query interface. Internal attempt history remains available on disk for recovery/debugging, not
  through the dispatcher response.
- New Nix distribution wiring: the installed script path is unchanged.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Make one versioned `control` command the dispatcher seam, retain owner-side `progress`/`finish`, and remove public dispatcher-side `launch`/`reconcile` after migration. | Issue 47 asks the helper to own orchestration decisions; the codebase-design deletion test says policy should reappear inside the deep module, not remain callable across shallow seams. | Layer a planner over public launch/reconcile — callers could still bypass the control plane and the interface would remain as complex as its implementation. |
| D2 | Keep durable schema version 1 and version the strict dispatcher-facing bootstrap and control request/response independently as `interface_version: 1`. | Existing schema already contains every lifecycle fact required by issues 14/33, while issue 47 asks for versioned compact interfaces rather than a ledger migration. | Bump/migrate the ledger to store dispatcher snapshots or action queues — adds irreversible state and migration risk without an acceptance need. |
| D3 | Normalize tracker, owner-exit, recorded-worktree, and absent-candidate facts in a single request; the helper performs no tracker, Git, spawn, or clock I/O. | Issue 47 explicitly keeps tracker queries and spawning outside and requires deterministic tests; The Bar's defense-in-depth/fail-loud rules support strict closed observations. | Let the helper invoke `gh`, `git worktree`, or the wall clock — couples policy to environment-specific adapters and makes replay nondeterministic. |
| D4 | Return one bounded current summary per issue, only current-invocation deltas, at most `max_parallel` typed dispatch actions, exactly one wait/finalize action, and the earliest deadline. | The acceptance criteria prohibit complete attempt histories and require spawn/resume/retry/wait/finalize envelopes plus next deadline; token economy favors one compact response. | Return the full ledger with a recommended action — preserves the dispatcher's reconstruction burden and unbounded history surface. |
| D5 | Persist accepted action identity before emitting it, derive short owner/action tokens from run-local issue/attempt/launch ordinals, and treat replay against advanced state as wait/finalize rather than another dispatch. | The existing lifecycle persists launch before spawning, and acceptance requires restart replay without duplicate launches. | Re-emit an unacknowledged pending spawn until receipt — a crash after real spawning but before acknowledgement can duplicate work because the host spawn primitive is not idempotent. |
| D6 | Apply global precedence `resume`, then one allowed retry, then first spawn in requested issue order, with owner-stopped/fogged/closed suppressing new work and expiry/owner-failed retryable. | The current orchestrator's issue-33 failure policy already gives resume precedence, treats content stops as verdicts, retries transient failures once, and lets unrelated issues continue. | Leave classification and precedence in skill prose — duplicates lifecycle policy and makes restart behavior model-dependent. |
| D7 | Reuse the recorded path for retry only when the normalized worktree state is `matching_issue_branch`; otherwise require a verified absent candidate. | Issue 33 made configured worktrees authoritative and established that a fresh owner, not a fresh path, defines retry identity. | Always allocate a fresh retry path or inspect Git inside the helper — the first loses existing work; the second crosses the adapter seam. |
| D8 | Test through the CLI/reopened ledger and one combined multi-issue replay in the existing helper test module; update skill contracts and deployed eval expectations at the same seam. | The prior lifecycle specs and The Bar require observable deterministic tests; the existing just recipe already names these test modules and current evals pin the behavior being retired. | Unit-test new planner functions or rely on prose/eval examples alone — tests past the interface or fail to prove concurrent durable behavior and bounded output. |
| D9 | Record no ADR or glossary change; keep this amendment in the issue design spec. | Grounding found no project context/ADR tree, and both prior lifecycle designs use `.claude/specs`; grill-with-docs creates domain docs and ADRs only when their admission gates are met. | Bootstrap a docs/ADR architecture for this change — unrelated scope and a duplicate home for the lifecycle rationale. |
| D10 | Make `init-run` return a strict version-1 latest-requirement projection (`issue`, current attempt/owner/action identity, recorded worktree) and use control's first `spawn` envelope for explicitly requested durable standalone ownership. | A restarted adapter must discover exact recorded paths and correlate current host notifications before it can normalize an action-ready control request, while direct standalone use must remain ledger-free and durable standalone use needs one nonduplicated identity after public `launch` removal. | Print the raw ledger, add a fifth bootstrap command, guess identity/paths, or let standalone initialization create identity outside `control` — each either leaks history, widens the interface, or bypasses policy. |
| D11 | Replace the adapter's sole outstanding wait by publishing the new wait ID before canceling the old handle; ignore stale wake IDs, avoid duplicate observers for the same ID, and clear the ID before finalize cancellation. | A prose-only “supersedes” rule leaves a cancellation race able to create extra control events; explicit ID comparison makes the one-shot event contract operational without durable scheduler state. | Persist observers in the ledger or let cancellation order make an old wake look current — the first crosses the adapter seam and the second violates the single-wake contract. |
| D12 | Count only currently active external owners as occupied: handed-off and current-unavailable attempts consume a slot only when their returned resume action is accepted. | The control plane must be able to resume interrupted work at full durable nonterminal count, and the request already distinguishes a current unavailable launch from a live owner. | Count every durable nonterminal attempt as occupied — handed-off and dead owners could fill all capacity and prevent their own resume. |
| D13 | Accept an absent-candidate fact only for actionless identical-request replay when the latest attempt remains active and its first launch at the same request instant consumed that exact path; reject wrong instant/path, terminal, and current-unavailable cases, and require current facts for any dispatch. | Persist-before-emission advances the ledger, so the request that created a first attempt necessarily carries a candidate that is no longer absent when replayed; the acceptance guarantee requires a causal exception that cannot authorize a new action. | Reject every consumed candidate or broadly trust stale candidate facts — the first breaks identical replay, while the second can hide a collision or authorize resume/retry from obsolete evidence. |
| D14 | Keep wait handles process-local: missing/already-exited cancellation is idempotent; unexpected cancellation failure restores the old ID/handle and fails before arming; failed replacement arming clears truthful adapter wait state; and the host reaps inherited detached observers before a full restart rearms. | Cancellation and arming are external process boundaries that can race or fail outside the ledger; explicit rollback/recovery ownership is required so a later identical response can retry replacement and the adapter never deduplicates on a new ID paired with an old handle. | Persist observer handles in schema v1, silently swallow boundary failure, retain the published new ID after failed cancellation, or assume a restarted process can cancel unknown inherited observers — each crosses the seam or reports false scheduler state. |
| D15 | Gather a verified absent candidate for every requested issue without an `init-run` requirement, plus every absent/mismatched returned path, and let `control` ignore unused candidates. | The adapter has filesystem responsibility but must not duplicate control's tracker-readiness classification; harmless extra normalized facts keep one action-ready request without a policy round trip. | Ask the adapter to decide ready/blocked/fogged or add a second helper requirements exchange — the first recreates policy outside control and the second widens the interface and loop. |
| D16 | Under the ledger lock and before mutation, require candidate paths consumed by distinct accepted actions to be pairwise distinct and disjoint from every other issue's durable recorded path. | A candidate observation is issue-scoped input but the selected path is an exclusive repository resource; independently valid facts can otherwise make one transaction launch two owners into the same worktree. | Trust per-observation absence checks or reject every duplicate unused candidate — the first permits cross-action aliasing, while the second rejects harmless facts that policy never consumes. |
