# Durable workflow lifecycle design

## Problem

Long-running issue orchestration currently treats an agent exit notification as the only authoritative completion signal. A delayed or missing notification leaves the dispatcher unable to distinguish completed work from an abandoned attempt, so a retry can duplicate work that already shipped. The existing retry, silence, and context-budget rules are prose: they describe good operator behavior but do not leave reconstructable state or mechanically refuse an unsafe launch.

Issue [#14](https://github.com/fagenorn/nix-config/issues/14) requires one recoverable lifecycle for both the multi-issue dispatcher and each `from-issue --auto` owner. The result must stay compact enough for an orchestrator ledger, preserve worktrees after failures, and make all time/context decisions deterministic and testable without real sleeps or full agent runs.

## Solution

Add one project-agnostic `workflow-state` helper beside the shared agent-skill scripts. It owns a versioned, atomically written run ledger under the established git-ignored `.superpowers/workflows/<run-id>/` convention. Skills call the helper at lifecycle boundaries rather than hand-editing JSON.

The helper is a Python standard-library CLI with four operations:

1. `init-run` creates or validates a run ledger.
2. `launch` records either a same-owner/worktree resume or a fresh attempt, enforcing the two-attempt cap.
3. `progress` advances the last-progress timestamp and phase-boundary decision, optionally recording a durable handoff path.
4. `finish` records a terminal result before the owner exits; `reconcile` reconstructs the compact dispatcher outcome from durable state and expires overdue active attempts.

`orchestrate-issues` creates one run, records every launch, and reconciles durable state whenever it starts/resumes and before dispatching a retry. Notifications remain the fast path, but their payload is checked against the durable terminal result; the file is authoritative if a notification is missing or late.

`from-issue --auto` receives the run/attempt identity in the dispatch prompt. At every phase boundary it runs the budget decision, persists the result, and obeys the returned closed-set action. Before returning to its caller, including stopped and failed paths, it persists the compact terminal result and then sends the same fields to the caller.

`handoff` gains an optional caller-supplied durable destination. Its default temporary-file behavior remains unchanged for interactive use; `from-issue` supplies the per-run handoff path so a fresh session can resume.

## Decisions

### One authoritative per-run ledger

Each orchestrator invocation has a stable `run_id` and one `state.json`:

```json
{
  "schema_version": 1,
  "run_id": "20260813T200000Z-a1b2c3d4",
  "repo_root": "/absolute/repo/path",
  "created_at": "2026-08-13T20:00:00Z",
  "issues": {
    "14": {
      "attempts": [],
      "authoritative_attempt": null,
      "outcome": null
    }
  }
}
```

One state file avoids split-brain between an attempt record and a result record. Every read–validate–mutate–replace transaction holds an exclusive advisory lock on the run's stable `state.lock`; read-only inspection holds a shared lock. With the lock held, the helper writes a sibling temporary file, flushes and closes it, replaces `state.json` atomically, and syncs the directory. Every mutation rereads and validates the current schema first. Unknown schema versions, states, transition names, actions, attempt identities, or lock failures fail loudly without rewriting the ledger. The supported hosts are macOS and Linux, so standard-library `fcntl.flock` is the framework-first cross-process guard; there is no unlocked fallback.

The runtime directory also contains `handoffs/<issue>-<attempt>.md`; handoff prose is separate because it can be larger than the compact ledger. `.superpowers/workflows/.gitignore` ignores all run artifacts while retaining the directory convention.

### Attempt schema and identity

Every attempt contains:

```json
{
  "attempt": 1,
  "issue": 14,
  "owner": "agent-handle",
  "worktree": "/absolute/worktree/path",
  "launch_kind": "fresh",
  "launches": [
    {
      "kind": "fresh",
      "owner": "agent-handle",
      "worktree": "/absolute/worktree/path",
      "at": "2026-08-13T20:00:00Z"
    }
  ],
  "started_at": "2026-08-13T20:00:00Z",
  "last_progress_at": "2026-08-13T20:12:00Z",
  "deadline_at": "2026-08-13T21:30:00Z",
  "state": "active",
  "phase": 3,
  "phase_action": "continue",
  "handoff_path": null,
  "prior_attempt": null,
  "terminal_result": null
}
```

Attempt number is the fresh-launch ordinal, not a process count. Every accepted launch appends a `launches` event and updates `launch_kind`, making fresh-versus-resume reconstructable after either process exits. A launch with the same issue, owner, and normalized worktree as the current nonterminal attempt is `resume`: it appends a resume event to the existing attempt and does not change its original start or fixed deadline. A different owner or worktree is `fresh`; it creates attempt 2 and links `prior_attempt: 1`. Any request for attempt 3 is refused, the issue outcome becomes `failed`, and the terminal result identifies both prior attempts. Resuming a terminal attempt returns its terminal result instead of relaunching work and does not append an event.

The deadline is fixed at fresh launch (`started_at + agentBudgetMinutes`). Progress changes `last_progress_at`, never the deadline. This prevents activity from extending an abandoned run indefinitely.

### Lifecycle state machine

Attempt states are `active`, `handed_off`, `stopped`, `failed`, and `merged`. Only `active` is nonterminal for deadline purposes; `handed_off` is resumable but cannot be dispatched as a fresh retry until its durable handoff is explicitly resumed.

Allowed transitions are:

- fresh launch → `active`
- `active` → `active` on progress
- `active` → `handed_off` after a durable handoff is written
- `handed_off` → `active` only through a same-owner/worktree resume using the handoff
- `active` → `stopped`, `failed`, or `merged` through `finish`
- overdue `active` → `stopped` through `reconcile`

All terminal transitions preserve the worktree path. The helper never removes a worktree. `finish` requires the compact result schema and stores it before printing the exact same normalized JSON for the caller to send. A second identical `finish` is idempotent; a conflicting terminal result fails loudly.

The compact terminal result is:

```json
{
  "issue": 14,
  "state": "merged",
  "pr_url": "https://github.com/fagenorn/nix-config/pull/15",
  "merge_sha": "0123456789abcdef",
  "issue_closed": true,
  "discussion_items": [],
  "notes": ""
}
```

`state` is `merged`, `stopped`, or `failed`. Non-applicable URL/SHA values are `null`. Notes are capped at 500 characters. The dispatcher copies this object into its issue ledger and never invents a second summary shape.

### Notification reconciliation

On startup, after any owner notification, and before any retry, the dispatcher calls `reconcile`:

- A durable terminal result wins over missing or delayed notification state.
- A notification matching the durable result is acknowledged and causes no state change.
- A delayed notification for an older attempt cannot replace a newer authoritative terminal result.
- An active attempt before its deadline stays active; it is neither retried nor marked complete.
- An active attempt at/after its deadline becomes `stopped`, with the worktree in its result notes for inspection.
- A handed-off attempt remains resumable while its fixed fresh-launch deadline
  remains. It is never silently expired by `reconcile`: an explicit matching
  resume at or after that deadline instead records a visible `stopped` result with
  the worktree retained, so the dispatcher can apply its one-fresh-retry policy.

Only after reconciliation reports a recoverable transient terminal failure may the dispatcher request one fresh attempt. The helper, not the prompt, enforces the cap.

### Executable phase-boundary budget decision

At each `from-issue` phase boundary, the helper evaluates explicit inputs instead of estimating from prose:

- current assistant turn count,
- current context/token count when the harness exposes it,
- configured turn ceiling (default 120),
- configured context ceiling (default 150,000),
- whether the next phase needs the current conversation,
- whether all remaining work is self-contained for a full subagent.

It returns exactly one action before either ceiling is crossed:

1. `continue` when the next phase needs this context and both budgets remain below a reserved headroom threshold;
2. `fresh_start` when all required state already lives in committed artifacts and a new session can reconstruct it;
3. `handoff` when non-artifact state must travel; the caller invokes `handoff` at the ledger's durable path and then persists `handed_off`;
4. `delegate` when the entire remainder is self-contained for a fresh subagent.

The default headroom is one orchestration turn plus the next phase's dispatch/report boundary, represented as a conservative configurable integer in the helper rather than an implicit “near the limit” judgment. At or above the threshold, `continue` is invalid. Missing usage data selects a durable `handoff` rather than assuming room. The decision and measured inputs are stored on the attempt for audit.

### Skill integration

`orchestrate-issues` documents the exact helper calls in dispatch, wait, retry, and drain order. It remains a dispatcher: it reads compact reconciliation output, never specs, plans, diffs, or review transcripts. Its owner prompt supplies `run_id`, `attempt`, `owner`, and `worktree` and requires `from-issue 14 --auto` to finish durably before returning.

`from-issue` adds executable state checks to Phase 0 and every later phase boundary. The existing qualitative five-way context strategy remains explanatory, but the helper's action is the gate. Phase 7's shipping subagent receives the attempt identity and finishes the terminal record after merge/close/cleanup results are known. Early content-level stops also finish a durable `stopped` result when a run identity exists.

`AUTO.md` retains its two mandatory content stops and adds that autonomous checkpoints never bypass lifecycle writes. A handoff is a terminal outcome for the current owner, not a failure and not a fresh retry.

`handoff` accepts a durable output path only when its caller provides one. It validates that the destination is within the current run's `.superpowers/workflows/<run-id>/handoffs/` directory, reads before writing as today, writes atomically, and returns the path. General interactive callers still use `mktemp`.

### Evaluation strategy

Add a deterministic Python unittest suite for the helper. Tests inject ISO timestamps and budget counters; no sleeps, wall-clock polling, agent processes, GitHub calls, or network access occur.

The public test seam is the CLI plus the resulting `state.json`, because that is the same boundary skills use. Fixtures exercise:

- a persisted terminal result recovered before a delayed notification arrives;
- an active owner that dies and crosses its injected deadline, becoming visibly stopped with worktree retained;
- same-owner/worktree resume preserving attempt 1 and its deadline;
- one distinct fresh retry creating linked attempt 2, followed by mechanically refused attempt 3 and failed issue outcome;
- boundary actions for continue, fresh start, durable handoff, and full delegation, including the at-threshold case that must not continue;
- a handed-off attempt resuming from a durable path without consuming a retry;
- idempotent matching finish and rejection of conflicting/unknown transitions.
- two concurrent owner processes updating distinct issues while the per-run lock preserves both outcomes;
- one combined controller fixture in which a delayed completion, an expired silent owner, and a near-ceiling handoff produce one authoritative outcome per issue, no third attempt, and a resumable handoff.

Add lightweight skill-contract assertions that check `orchestrate-issues`, `from-issue`, `AUTO.md`, and `handoff` name the helper and preserve the write-before-notify/order invariants. Wire these tests into a repository-owned `just` recipe and include that recipe plus `just build` in verification. Full deployed-agent pipeline evals remain valuable but are not the primary correctness proof for deterministic lifecycle policy.

## Test seams

- **Lifecycle CLI seam:** invoke the helper as a subprocess with a temporary repo root, injected timestamps, and JSON output; assert exit code, normalized result, and durable state. This follows the existing shell-facing `sdd/scripts/*` pattern while keeping policy testable in Python.
- **Filesystem seam:** reopen the run ledger after every mutation to prove recovery is independent of process memory.
- **Skill contract seam:** assert the skill prose calls lifecycle operations in the required order and carries the exact compact schema. This follows the repository's eval assertion style without paying for an agent transcript.
- **Build seam:** `just agent-workflow-tests` runs deterministic tests; `just build` validates the Nix configuration and installed skill files.

## Out of scope

- Persisting arbitrary agent transcripts or review content in the dispatcher ledger.
- Replacing the collaboration/Agent tool, adding a daemon, or polling background-agent state.
- Automatically deleting, resetting, or repairing abandoned worktrees.
- Supporting concurrent writers on network filesystems or distributed databases; the lifecycle is local to one repository/worktree orchestration run.
- Retrofitting SDD's task ledger or unrelated release/deployment workflows to the new schema.
- Changing issue tracker APIs, host configuration, or the existing PR merge policy.

## Auto-resolved decisions

### Durable state location
- **Question:** Where should reconstructable workflow state live without becoming committed project content?
- **Choice:** Store versioned per-run state under git-ignored `.superpowers/workflows/<run-id>/`.
- **Grounding:** `sdd/SKILL.md` and `sdd/scripts/sdd-workspace` already establish `.superpowers` as the per-worktree durable agent-state convention, and the repository git exclude covers it.
- **Alternative considered:** A platform temp directory was rejected because cleanup/reboot can erase it and a fresh session cannot reliably discover it.

### State ownership and atomicity
- **Question:** Should attempts/results be separate files managed by prompt instructions or one helper-owned ledger?
- **Choice:** Use one versioned JSON ledger mutated atomically through a standard-library CLI.
- **Grounding:** The Bar requires one authoritative home per contract, fail-loud closed sets, and truthful recoverable state.
- **Alternative considered:** Separate prompt-authored files were rejected because partial writes and divergent summaries create split-brain recovery.

### Resume identity
- **Question:** What mechanically distinguishes a resume from a fresh retry?
- **Choice:** A resume must match issue, owner handle, and normalized worktree of the current attempt; any different owner or worktree is fresh.
- **Grounding:** Issue #14 explicitly defines same owner/worktree as resume and requires fresh launches to consume the allowance.
- **Alternative considered:** Matching only issue or branch was rejected because a replacement owner could accidentally inherit a retry-free identity.

### Retry ceiling
- **Question:** Where should the one-fresh-retry policy be enforced?
- **Choice:** Enforce it in the lifecycle helper and persist refusal as the issue's failed outcome.
- **Grounding:** Issue #14 requires the cap to be mechanical; `orchestrate-issues` currently states the rule only in prose.
- **Alternative considered:** Dispatcher-only counting was rejected because notification loss/context loss can also lose the count.

### Fixed wall deadline
- **Question:** Should progress extend the attempt deadline?
- **Choice:** Keep the deadline fixed from fresh launch; progress updates observability but not budget.
- **Grounding:** The issue calls for a configured wall-clock budget that ends an abandoned attempt, while the existing 90-minute rule must become enforceable.
- **Alternative considered:** Sliding inactivity expiry was rejected because periodic low-value progress could extend a run without bound.

### Terminal handoff semantics
- **Question:** Is a context-budget handoff a failure, an active attempt, or a resumable terminal state for the current owner?
- **Choice:** Persist `handed_off` with a durable path; resume the same attempt without consuming retry.
- **Grounding:** `from-issue` requires a fresh session to resume before crossing its ceiling, and `AUTO.md` says handoff stops the current orchestrator while artifacts carry continuation.
- **Alternative considered:** Treating it as failure would spend the retry allowance on planned context control; leaving it active would make owner silence indistinguishable from successful handoff.

### Budget behavior when usage is unknown
- **Question:** What should the phase gate do if the runtime cannot report a reliable context count?
- **Choice:** Select durable handoff rather than authorize `continue`.
- **Grounding:** The acceptance criterion says the ceiling must not be crossed; the Bar requires truth rather than optimistic status.
- **Alternative considered:** Estimating from conversation length was rejected because it cannot falsifiably enforce the configured ceiling.

### Test implementation seam
- **Question:** Should acceptance be demonstrated with full real-time agent runs or deterministic policy fixtures?
- **Choice:** Test the helper CLI and reopened ledger with injected timestamps/counters, plus small skill-contract assertions.
- **Grounding:** The Bar requires tests that fail for one observable reason, and the existing eval harness supports deterministic filesystem assertions.
- **Alternative considered:** Sleep-based background-agent demos were rejected as slow, flaky, and unable to isolate policy errors from harness/network failures.

### Documentation home
- **Question:** Does this cross-workflow decision require creating a new repository context map and ADR tree?
- **Choice:** Keep the tradeoff record in this committed design spec.
- **Grounding:** The repository currently has no project context/ADR convention; prior cross-skill designs live under `.claude/specs`, and `grill-with-docs` says to create documentation lazily.
- **Alternative considered:** Bootstrapping a full docs architecture was rejected as unrelated scope and duplication of this design record.

### B1: Persist every accepted launch
- **Question:** The reviewer found that returning `launch_kind: resume` without changing durable state does not let a reconstructed ledger prove that a resume occurred. What durable representation should replace it?
- **Choice:** Store the issue on every attempt, append one `{kind, owner, worktree, at}` event per accepted launch, and update the attempt's current `launch_kind`; preserve the original start and deadline.
- **Grounding:** Issue #14 requires durable attempt state to identify the issue and whether a launch is a resume or fresh retry. The previous schema recorded only the original fresh launch.
- **Alternative considered:** Updating only `launch_kind` was rejected because it would erase the original launch chronology and could not distinguish one resume from repeated resumes.

### B2: Serialize per-run ledger mutations
- **Question:** The reviewer found that atomic replacement prevents torn files but still permits lost updates when parallel issue owners read the same version and replace it independently. How should concurrent writers be serialized?
- **Choice:** Hold `fcntl.flock` on a stable per-run lock file across the complete read–validate–mutate–replace transaction, and fail loudly if locking fails.
- **Grounding:** `orchestrate-issues` defaults to two parallel owners; a shared ledger must retain both. The Bar requires framework-first primitives and truthful durable state. Python on the repository's macOS/Linux targets supplies `fcntl`.
- **Alternative considered:** Per-issue state files were rejected because they would reverse the approved one-ledger contract and require a second aggregation consistency model.

### S2: Combined acceptance demo
- **Question:** Are isolated unit scenarios sufficient for the issue's requested demo of delayed notification, silent owner, and context handoff in one final ledger?
- **Choice:** Add one deterministic combined controller fixture in addition to focused tests.
- **Grounding:** Issue #14 explicitly describes a final-ledger demo with all three conditions and one authoritative outcome per issue.
- **Alternative considered:** Relying only on separate unit cases was rejected because their individual success would not prove reconciliation and outcome uniqueness coexist in one run.
