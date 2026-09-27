# Durable, restart-safe direct autonomous issue ownership

Issue: https://github.com/fagenorn/nix-config/issues/73

This design amends, without replacing, the durable lifecycle and control-plane
contracts accepted for issues 14, 33, and 47.

## Problem

A dispatcher-owned `from-issue --auto` run is durable because the dispatcher
creates the ledger and supplies a complete owner envelope. The more common direct
autonomous invocation has no caller-supplied run ID, so it follows the standalone
path and remains ledger-free. A process restart can therefore lose its attempt,
deadline, worktree, handoff, and retry history. Starting the command again may
duplicate an owner or silently grant another two attempts.

The fix must not move orchestration back into skill prose. The existing
`workflow-state control` policy already owns handoff resume, owner-unavailable
resume, expiry, retry, refusal, fixed deadlines, and atomic persistence. Direct
ownership needs a narrow acquisition interface that discovers its own retained
run, obtains any external facts it still needs, and applies that same policy.

## Solution

Add one `workflow-state direct-owner` command. It accepts one issue and no run ID,
serializes discovery with a stable per-issue lock, discovers or creates a retained
`direct-<issue>-<six-digit-sequence>` ledger, and then uses the existing per-run
transaction and one-issue control implementation. It returns exactly one of three
strict version-1 response variants:

- `observe` names only the tracker or worktree facts still required;
- `owner` returns the complete, already-persisted lifecycle envelope for this
  process to adopt; or
- `terminal` replays the latest durable outcome or reports why current tracker
  facts prohibit ownership.

Direct autonomous `from-issue --auto` uses this command by default whenever no
dispatcher envelope was supplied. It answers `observe` requests through its
existing tracker and Git adapters, adopts `owner`, and returns `terminal` without
installing a waiter. It never asserts takeover or new-run authorization on the
user's behalf.

Dispatcher-owned runs keep `init-run` plus `control`. Interactive direct calls
remain ledger-free unless the user selects their existing explicit durable
standalone route. Owner-side `progress` and `finish` remain the only post-
acquisition lifecycle calls.

## Decisions

### Module and command boundary

The public command is:

```text
workflow-state direct-owner \
  --repo-root <absolute-ledger-repository-root> \
  --request-file <absolute-json-path>
```

The helper remains Python standard-library-only. It performs no tracker query,
Git inspection, owner spawn, wait installation, or clock read. The request file
supplies normalized observations and an injected timestamp; the only external
side effect is the same locked, atomic lifecycle persistence already owned by the
module.

`direct-owner` is an acquisition seam, not a second policy engine. Refactor the
current one-issue transition/action derivation behind `control` into an internal
operation that both commands call while holding the selected run lock. The
dispatcher request and response, action ordering, lifecycle schema version, and
owner-side `progress`/`finish` contracts do not change.

### Strict request

The direct-owner interface has its own version constant. Version 1 requires
exactly these fields, including nullable observation slots and explicit boolean
authorizations:

```json
{
  "interface_version": 1,
  "issue": 73,
  "now": "2026-08-20T10:00:00Z",
  "attempt_budget_minutes": 180,
  "new_run": false,
  "owner_unavailable": false,
  "tracker": null,
  "worktree": null
}
```

`issue` and `attempt_budget_minutes` are positive plain integers, `now` is
RFC3339 UTC, and both authorization fields are literal JSON booleans. `tracker`
is null or the existing exact tracker-observation shape for this issue.
`worktree` is null or the existing exact worktree-observation shape for this
issue, including its nullable `recorded` and `candidate` members. Reusing these
validators keeps tracker readiness, recorded-path matching, and candidate-path
meaning single-sourced. Unknown fields, versions, enum members, mismatched issue
numbers, relative paths, or malformed observations fail before ledger mutation.

The two booleans authorize distinct exceptional transitions. They may not both
be true, and a true flag that is not applicable to the discovered state fails
loudly. `owner_unavailable` is applicable only to the latest unexpired `active`
attempt. `new_run` is applicable only when retained history exists and its latest
run is terminal. The initial run needs neither authorization.

### Closed responses

All responses are canonical, newline-terminated JSON and strict by variant.
`kind` is the closed discriminator `observe | owner | terminal`.

An observation response has exactly:

```json
{
  "interface_version": 1,
  "kind": "observe",
  "issue": 73,
  "run_id": "direct-73-000001",
  "requirements": [
    {"kind": "recorded_worktree", "path": "/absolute/worktree-issue-73"}
  ]
}
```

`run_id` is null before a run has been selected or created. Requirements preserve
policy order and use only three exact item shapes: `{"kind":"tracker"}`;
`{"kind":"recorded_worktree","path":"<absolute recorded path>"}`; and
`{"kind":"candidate_worktree"}`. The last asks the adapter to reserve and
verify an absent candidate; it does not let the helper choose a path. Only facts
needed by the current state are requested. Supplying one round may reveal the
next requirement—for example, an absent recorded retry worktree then requires a
candidate—without changing the ledger.

An owner response has exactly:

```json
{
  "interface_version": 1,
  "kind": "owner",
  "ledger_repo_root": "/absolute/repository-root",
  "run_id": "direct-73-000001",
  "issue": 73,
  "attempt": 1,
  "owner": "73:1",
  "action_id": "73:1:1",
  "launch_kind": "spawn",
  "worktree": "/absolute/worktree-issue-73",
  "handoff_path": null,
  "deadline_at": "2026-08-20T13:00:00Z"
}
```

`launch_kind` is `spawn | resume | retry`. Every identity and path is projected
from the persisted action; callers never provide or reconstruct them. The
repository root is the validated immutable absolute root used for all later
`progress` and `finish` calls. `owner` is printed only after the attempt or resume
launch has been durably written.

A terminal response has exactly:

```json
{
  "interface_version": 1,
  "kind": "terminal",
  "issue": 73,
  "run_id": "direct-73-000001",
  "source": "lifecycle",
  "reason": "merged",
  "blockers": [],
  "result": {"issue": 73, "state": "merged", "pr_url": null, "merge_sha": null,
             "issue_closed": true, "discussion_items": [], "detail_state": "none",
             "report_path": null, "notes": ""}
}
```

`source` is `lifecycle | tracker`. A lifecycle terminal has a non-null run ID,
empty blockers, `reason` equal to `merged | stopped | failed`, and the existing
compact terminal result. A tracker terminal has `reason` equal to
`closed | blocked | fogged`, a null result, the current normalized blockers, and
a nullable run ID. It names an adopted nonterminal run when one exists; it is
null when blocked facts prevent an initial or explicitly requested next run from
being created. Tracker precedence matches `control`: closed first, then a
decision blocker makes the issue fogged, then an ordinary open blocker makes it
blocked. No direct response contains a wait action or installs a waiter.

### Discovery, reservation, and locking

Direct IDs are module-owned and exactly match
`direct-<canonical-positive-issue>-<six decimal digits>`. Sequence `000001` is
first; a later explicitly authorized run uses one plus the greatest retained
sequence. Exhaustion after `999999` fails loudly. Terminal directories and their
ledgers are never removed or overwritten, so each new run receives a fresh
two-attempt allowance without erasing earlier evidence. There is no active-run
index or mutable pointer.

The stable discovery lock is a non-symlink regular file in the workflows
directory named `.direct-<issue>.lock`. `direct-owner` validates the workflows
directory and this lock with the existing hardened open routines, obtains an
exclusive `flock`, and keeps it through discovery and the selected run
transaction. It then acquires existing `state.lock` files in the fixed order
issue lock → run lock. `progress` and `finish` still take only the run lock and
cannot invert this order.

While holding the issue lock, discovery scans the workflows directory rather
than consulting an index. Any entry beginning with this issue's
`direct-<issue>-` namespace must have the exact six-digit name. Every matching
entry must be a non-symlink directory whose lock and state are safe regular
files; its state must validate against its run ID and contain only the named
issue. A malformed name, symlink, missing/corrupt state, wrong issue, or invalid
ledger fails loudly. Discovery classifies runs using the existing retry policy,
not merely `outcome != null`: an empty run, an active/handoff attempt, an
attempt-1 expiry, or an owner-failed attempt still has lifecycle work remaining.
More than one such nonterminal run is ambiguous and fails without mutation. The
single nonterminal run, when present, must also have the greatest retained
sequence; a newer terminal run beside it is impossible through the module-owned
creation order and is rejected as corrupted history.

With one nonterminal run, it is adopted. With none, the greatest-sequence
terminal run is replayed unless `new_run` is true. A permitted new or initial
run is initialized and its first accepted action is persisted in the same
selected per-run transaction, so a crash cannot expose an initialized ledger
that falsely claims an owner. Concurrent first calls serialize: one creates
`direct-73-000001` and
attempt 1; the other observes that unexpired active attempt and fails unless it
carried prior explicit takeover authorization. It cannot create a second run or
append a duplicate attempt.

The public `init-run` and `control` commands reject every reserved direct ID
before creating or opening its directory. This prevents callers from fabricating
or taking over a direct namespace through the dispatcher seam. `progress` and
`finish` deliberately accept a returned direct identity so its owner can advance
and complete the lifecycle.

### Acquisition policy

After discovery and fact completion, direct acquisition applies the existing
one-issue control rules with effective capacity one:

1. A latest unexpired `handed_off` attempt resumes automatically after its
   recorded worktree is observed matching. It retains attempt, owner, worktree,
   original start, fixed deadline, and handoff path and appends one resume launch.

   (**amended by issue 74's direct autonomous implementation owner rollover
   design** — The matching-worktree requirement has one exact pre-worktree
   exception: only a reserved direct run's latest unexpired `handed_off` Phase-0
   attempt with a valid durable handoff may resume when its exact recorded path
   is observed `absent`. It uses that recorded reservation even if an alternate
   absent candidate is also supplied, preserves the same attempt, owner,
   worktree, original start, fixed deadline, and handoff path, and appends exactly
   one resume launch. Every other acquisition still requires the matching
   recorded worktree stated above.)

2. A latest unexpired `active` attempt is presumed owned. With
   `owner_unavailable: false`, `direct-owner` fails loudly before mutation even
   if all other facts are absent. With explicit authorization, it derives the
   current attempt, owner, and launch ordinal, supplies the internal unavailable
   event, requires the matching recorded worktree, and resumes that same attempt.
   Caller-supplied owner or action identity is impossible.
3. At or after the fixed deadline, the existing provisional expiry transition
   applies. Attempt 1 gets its one fresh retry; attempt 2 gets the existing
   durable refusal. An owner-reported `failed` result follows the same retry and
   refusal policy. A retry reuses a matching recorded worktree or requires a
   verified absent candidate exactly as `control` does.
4. Owner-reported `stopped`, `merged`, and the durable refusal are terminal.
   They replay byte-equivalent compact outcomes on later processes unless
   `new_run` explicitly authorizes the next retained run. For that new run, the
   latest terminal attempt's recorded worktree is observed first and reused when
   it still matches the issue branch; otherwise an absent candidate is required.
   This is the existing retry path rule applied across the explicit run boundary:
   the allowance resets, but retained issue work is not discarded.
5. Before a first attempt or retry, tracker `closed`, `fogged`, or `blocked`
   suppresses ownership and returns the compact tracker terminal. A currently
   nonterminal attempt remains lifecycle-authoritative just as it does under
   `control`; tracker facts do not kill an active owner.

Every failed validation, ambiguous discovery, inapplicable authorization, and
unavailable-owner refusal leaves every existing `state.json` byte-unchanged.
Creating the stable issue lock is not a lifecycle mutation.

### Skill adapter contract

`from-issue` selects acquisition by invocation shape:

- dispatcher envelope supplied: adopt it unchanged and never call
  `direct-owner`;
- direct `--auto`, no envelope: acquire only through `direct-owner`, satisfying
  returned observation requirements with existing tracker/worktree adapters;
- interactive direct, no explicit durability request: keep the ordinary
  ledger-free path;
- interactive direct with the existing explicit durable standalone request:
  keep its `init-run`/`control` route unchanged.

The direct autonomous adapter always sends both authorization fields. Their
default is false, and it may send true only when the current user instruction
explicitly authorizes that exact takeover or new run. It never infers
`owner_unavailable` from a restart, missing process handle, silence, or an active
ledger; it never infers `new_run` from a terminal replay, reopened tracker, or a
desire to continue. A loud active-owner error and a terminal replay are returned
to the caller rather than bypassed through `init-run`, `control`, or a fabricated
envelope.

On `observe`, the adapter gathers only the requested current facts and calls
`direct-owner` again. On `owner`, it adopts the returned envelope and continues
the existing Phase 0–7 flow; later phase gates and terminal writes use
`progress`/`finish`. On `terminal`, it returns the compact response and stops.
No branch installs or interprets the dispatcher's wait envelope.

## Test seams

- **Direct-owner CLI seam:** subprocess tests send strict request files and
  injected times, assert canonical closed responses and errors, and reopen
  `state.json` after every accepted action. They cover first creation as
  `direct-73-000001`, observation rounds, handoff resume, explicit unavailable
  takeover, expiry and owner-failure retry, attempt-2 refusal, terminal replay,
  explicit new run, and retained earlier histories.
- **Durable/concurrency seam:** reopened-process fixtures use no in-memory helper
  state. Concurrent first calls prove one retained run and one attempt; byte
  snapshots prove an unexpired active refusal and all discovery/corruption
  failures do not rewrite state. Separate fixtures reject symlinked or malformed
  matching entries and multiple nonterminal runs.
- **Public capability seam:** CLI tests prove `init-run` and `control` cannot
  create or open reserved direct IDs while `progress` and `finish` accept the
  exact identity emitted by `direct-owner`.
- **Policy-equivalence seam:** the existing one-issue control scenarios and new
  direct scenarios assert the same attempt/deadline/worktree outcomes, guarding
  the shared internal implementation rather than testing private functions.
- **Skill contract seam:** assertions prove direct autonomous acquisition names
  only `direct-owner`, both flags default false and are never auto-asserted,
  `observe` loops through external adapters, `terminal` installs no waiter, and
  dispatcher-owned plus interactive-direct behavior remains unchanged.
- **Repository gates:** `just agent-workflow-tests` is deterministic and
  `just build` verifies the helper and skill are distributed by the existing Nix
  wiring.

## Out of scope

- Changing the dispatcher `control` request/response or dispatcher lifecycle
  envelope.
- Making ordinary interactive direct work durable by default or removing its
  existing explicitly requested durable route.
- Adding tracker, Git, spawn, wait, process-liveness, or wall-clock I/O to
  `workflow-state`.
- Adding an active-run index, daemon, scheduler, polling loop, migration
  framework, ledger cleanup, or automatic worktree deletion/repair.
- Changing the two-attempt cap, fixed-deadline semantics, late-finish authority,
  terminal result schema, handoff storage, or retained-worktree rules.
- Providing a general historical-query API; retained direct ledgers remain
  filesystem evidence used only for discovery and debugging.

## Decision ledger
| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Add a strict `direct-owner` acquisition seam and share `control`'s one-issue policy internally, leaving dispatcher and owner-mutation interfaces unchanged. | Issue 73 requires direct durability while the issue-47 spec makes `workflow-state` the sole lifecycle policy owner. | Compose public `init-run` and `control` in skill prose or duplicate their rules — either keeps restart policy model-owned or creates two policy homes. |
| D2 | Require nullable tracker/worktree observations plus explicit false-by-default `new_run` and `owner_unavailable` booleans in one versioned request, returning only `observe`, `owner`, or `terminal`. | The issue demands optional normalized facts, explicit exceptional authorization, and a three-variant closed response; The Bar requires fail-loud closed sets and token economy. | Infer flags or accept partial ad-hoc CLI arguments — a restart could silently duplicate ownership or reset the attempt allowance. |
| D3 | Reserve `direct-<issue>-<six-digit-sequence>`, discover by scanning retained ledgers under `.direct-<issue>.lock`, then acquire the existing run lock; keep no active index. | Issue 73 fixes module-owned IDs, lock order, retained terminal ledgers, and no index; the existing helper hardens non-symlink locks and atomic run transactions. | Use a mutable current-run pointer or timestamp/random IDs — introduces split-brain recovery state or nondeterministic identity. |
| D4 | Treat an unexpired active attempt as owned and fail byte-unchanged unless explicit `owner_unavailable` derives and resumes its current identity; auto-resume handed-off work. | The issue distinguishes authorized crash takeover from planned durable handoff, while issue 47 already makes unavailable and handoff resumptions preserve attempt/deadline identity. | Always resume on a new process or consume a fresh retry — the first can duplicate a live owner; the second spends retry allowance on process replacement. |
| D5 | Replay the latest durable terminal by default; only explicit `new_run` creates the next retained sequence and fresh two-attempt allowance, reusing its matching retained worktree or an absent candidate. | Issue 73 requires terminal replay, explicit renewal, and retained histories; issue 14 makes the retry cap per run, while issue 33 makes a fresh owner compatible with retained workspace reuse. | Reset the terminal ledger, allocate a fresh path unconditionally, or create on tracker reopening — erases evidence, strands retained work, or grants unrequested attempts. |
| D6 | Return a complete persisted owner envelope, but compact lifecycle/tracker terminal responses and no wait action. | `from-issue` needs immutable run/attempt/owner/action/worktree identity; direct acquisition has no dispatcher loop and acceptance requires terminal stops without a waiter. | Return raw control actions/ledger history — leaks dispatcher machinery and makes the direct skill reconstruct policy again. |
| D7 | Reserve direct IDs from public `init-run` and `control` while keeping `progress` and `finish` valid for emitted direct identities. | The namespace must be module-owned, but acquired owners must use the established phase and terminal write seams. | Ban all public commands on direct IDs or leave creation open — the former makes ownership unusable; the latter permits takeover outside discovery serialization. |
| D8 | Make direct autonomous `from-issue` use only `direct-owner`; preserve dispatcher-owned, ledger-free interactive, and explicitly durable interactive paths exactly. | Issue 73 states these adapter boundaries and forbids auto-asserting either authorization. | Route every direct invocation through the new command — changes interactive semantics beyond the issue. |
| D9 | Prove behavior at the CLI/reopened-ledger, concurrent-process, public-capability, and skill-contract seams; add no ADR/context tree. | Issues 14/47 and The Bar favor deterministic observable tests; prior lifecycle D9 records `.claude/specs` as the decision home because this repository has no domain-doc tree. | Test private planner functions or bootstrap new documentation architecture — misses the restart boundary or duplicates the accepted decision home. |
| D10 | Make lifecycle handoff and Phase-1 worktree prose acquisition-mode-specific: dispatcher owners resume from `control`, direct autonomous owners from `direct-owner`, and only ledger-free interactive direct calls create an ordinary worktree. | Phase-5 review found the live skill and contract tests still state dispatcher-only handoff and universal direct-worktree behavior, contradicting D4/D8. | Change only the Lifecycle identity subsection — leaves adjacent installed contracts internally inconsistent while all newly planned tests can still pass. |
| D11 | Pass an optional discovery-validated retained terminal worktree into the shared one-issue policy, which alone chooses it versus an absent candidate for a new run. | Phase-5 review found that existing `control` treats recorded paths only as existing-attempt facts, while D5 requires provenance-safe reuse for attempt 1 in a new retained ledger. | Let `command_direct_owner` choose the path before policy entry — creates a second worktree-selection policy home and can accept an unproven recorded path. |
| D12 | Extend public-contract tests across both missing and existing reserved runs, every new namespace trust boundary, and full lifecycle-terminal objects. | Phase-5 review identified takeover, issue-lock/non-directory, and response-leak regressions that the original plan's tests could not fail on. | Rely on creation-only, implementation-inspection, or selected-field assertions — misses the security/concurrency boundary and permits silent wire expansion. |
| D13 | Amend the accepted issue-47 spec inline and correct the helper's stale `launch` docstring in the implementing tasks. | Phase-5 review applied the repository's established inline-amendment convention and the review bar's adjacent-prose audit to behavior this issue deliberately changes. | Leave prior accepted prose contradictory or defer it — makes the merged documentation and live helper narration false at the implementing commit. |
| D14 | Pin every strict-request scalar boundary, boolean-as-integer trap, and at least one missing required member with mutation-free CLI tests. | Phase-5 re-review found the first strict-shape matrix could still admit permissive Python validation despite D2's closed contract; `require_plain_int` exists specifically to reject booleans. | Test only unknown fields and a few cross-field errors — lets truthiness coercion, `true == 1`, zero budgets, or incomplete requests reach the lifecycle boundary. |
| D15 | During one direct acquisition, retain and resend every observation kind `direct-owner` has already requested, refreshing values when needed, while never sending a kind it has not requested. | Task-2 review found the helper is intentionally request-stateless: tracker-first then worktree-only transmission alternates forever because the next request loses tracker readiness. | Send only the latest round's facts — cannot converge; make helper requirements cumulative — changes the reviewed Task-1 public protocol to compensate for an adapter-state defect. |
| D16 | Make the prose-contract test independently pin retention, resend in every later strict request, and the never-unrequested boundary in order. | Focused Phase-6 standards review found a retention-only substring can pass while the live adapter remains non-convergent or eagerly invents external facts. | Trust the implementation paragraph without executable guards — permits the exact D15 regression the correction exists to prevent. |
