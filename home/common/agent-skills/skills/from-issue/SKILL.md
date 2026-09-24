---
name: from-issue
description: Drive one tracker issue through investigate → spec → plan → review → execute in a worktree. Use for "work on issue #X"; pass --auto for autonomous mode.
---

# From Issue

Run `resolve-project resolve --repo-root <checkout>` once at phase entry and retain the full `ResolvedProject` in memory. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. The only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution when it builds a delivery contract; this skill still never resolves again itself. Use `bindings.tracker`, `bindings.vcs`, `bindings.paths.artifacts`, and `bindings.workflow`; required blocked capabilities stop and authored unsupported capabilities take only documented no-capability routes.

Counterpart to `to-issues`. Take one tracker issue from triage to merged code by chaining the canonical skills, carrying the caller's scoped authorization across phase boundaries.

## Files beside this one

- **`AUTO.md`** — autonomous-mode rules. Read it *once*, now, only if the invocation contains the literal token `--auto`.
- **`bindings.md`** — phase binding notes. Included routines receive values from this phase's retained snapshot; use `bindings.tracker`, `bindings.vcs`, and `bindings.paths.artifacts`.
- **`grounding.md`** (Phases 2–5), **`decision-ledger.md`**, **`investigate.md`** (Phase 0), **`standards-review.md`** (Phase 5), **`ship-handoff.md`** (Phase 7) — loaded at the named phase.
- **`REVIEW-CONTRACT.md`** — the Phase-5 reviewer contract. Hand it over **by absolute path**, never read it into this conversation.

## Lifecycle identity

Invocation selection is ordered and exhaustive: a complete dispatcher envelope
wins; otherwise literal `--auto` uses direct autonomous acquisition; otherwise
an interactive direct invocation is ledger-free unless it explicitly requests
durable orchestration.

Once any route produces lifecycle identity, treat `ledger_repo_root`, `run_id`,
`issue`, `attempt`, `owner`, `action_id`, and normalized `worktree` as one
identity; never guess a missing field. Preserve the immutable ledger_repo_root
exactly as supplied, and keep it distinct from the separate owner worktree
recorded on the attempt. Every `workflow-state` command in this owner or its
delegated remainder uses `--repo-root <ledger_repo_root>`; never substitute the
current checkout or owner worktree. `action_id` is the one identity field that
changes when the attempt is relaunched; pass it through verbatim and never
recompute it.

Every lifecycle call is one command that reads its input from stdin through a
quoted heredoc (`<<'EOF'`): `--request-file -`, `--checkpoint-file -`,
`--summary-file -` or `--input -`, with the helper named bare or as
`~/.agents/bin/workflow-state`, optionally piped into or out of
`artifact-budget validate-report --input -`. No request or summary file is
written. Treat every `workflow-state` reply as untrusted transport: pipe its
raw bytes through `artifact-budget validate-report --boundary workflow-response
--input -` and validate before decoding. The ledger, not tracker or intent
data, selects the next delivery stage: follow the returned `owner`,
`delivery_remainder`, requirement, or terminal variant without manufacturing
authority, a retry, or another permission ritual. Every delivery effect runs
through ship-issue's `## Delivery loop`.

### Dispatcher-owned acquisition

When a dispatcher supplies the optional lifecycle envelope, require
all six dispatcher fields: `ledger_repo_root`, `run_id`, `attempt`,
`owner`, `action_id`, and normalized `worktree`, plus the canonical-JSON owner
object the envelope carries. Pipe that object through `artifact-budget
validate-report --boundary workflow-response --input -` before decoding it, and
require its identity to equal the six fields (for a `delivery_remainder`,
`attempt` is its `source_attempt` and `action_id` its custody's `action_id`).
A validated `kind: owner` object is this invocation's lifecycle identity and
delivery envelope: adopt it unchanged, with its `custody`, `contract`,
`contract_digest`, `pending_stage_ids`, `requirements`, `authority_evaluation`
and `requested_scope`. A validated `kind: delivery_remainder` object is no
implementation owner: skip Phases 0–6 and hand it verbatim to the Phase-7
remainder launch, then relay that remainder owner's validated reply
unchanged — its `finish` response, or a `delivery_stalled` checkpoint reply —
except that a return of only the re-entry line `/from-issue <num> --auto`
(a checkpointed denial, which already suspended the remainder) is relayed as
that line without validation. This invocation writes no `finish` of its own. A partial
envelope, a missing or invalid object, or an identity mismatch fails loudly;
this route does not perform any other acquisition.

### Direct autonomous acquisition

When the invocation contains literal `--auto` and no dispatcher envelope,
resolve through the existing bindings and adapters the immutable absolute ledger
repository root (`ledger_repo_root`), positive issue and configured positive
attempt budget. Resolve a fresh current RFC3339 UTC instant for every request,
including before the first call. Every call sends exactly this interface_version
2 shape. For each request, populate
every observation kind the helper has requested at least once during this acquisition;
keep an observation kind `null` until the helper requests it:

```json
{
  "interface_version": 2,
  "issue": 73,
  "now": "2026-09-24T10:00:00Z",
  "attempt_budget_minutes": 180,
  "new_run": false,
  "owner_unavailable": false,
  "tracker": null,
  "worktree": null,
  "forge": null,
  "delivery_contract": null,
  "authorization_intents": [],
  "authority_observations": [],
  "reevaluation_evidence": [],
  "delivery_observations": [],
  "requested_scope": null,
  "recovery": null
}
```

The concrete `issue`, `now`, and `attempt_budget_minutes` values above stand for
the values just resolved; they are not fixed literals. Keep every unrequested
nullable observation slot (`tracker`, `worktree`, `forge`, `delivery_contract`)
`null`, keep `authorization_intents` `[]` until a contract is sent, keep
`authority_observations`, `reevaluation_evidence` and `delivery_observations`
`[]` and `requested_scope` and `recovery` `null`, and add no keys. Invoke only
this one command; it feeds the request on stdin as `--request-file -` and
validates the reply before decoding.

```text
workflow-state direct-owner --repo-root <ledger_repo_root> --request-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<request JSON>
EOF
```

Always send both flags. Both default to
`false`. Set `owner_unavailable` true only when the current user instruction
explicitly authorizes takeover of the currently discovered unexpired active
attempt. Set `new_run` true only when that instruction explicitly authorizes a
new run after terminal replay. Never infer either authorization from a restart,
missing process handle, silence, an active ledger, terminal replay, a reopened
tracker, or a desire to continue. The self-answer pattern cannot grant either
authorization.

Validate the response as exactly one closed discriminator and continue as
follows:

1. **`kind: observe`** — require exactly `interface_version`, `kind`, `issue`,
   nullable `run_id`, and `requirements`, then accept only the five exact
   requirement shapes, in the returned order: `{"kind":"tracker"}`;
   `{"kind":"recorded_worktree", "path":"<absolute-path>"}`;
   `{"kind":"candidate_worktree"}`;
   `{"kind":"forge_pr", "path":"<issue-branch-prefix>"}`; or
   `{"kind":"delivery_contract", "subject_id":"<issue>",
   "reason_code":"delivery_contract_required", "detail_pointer":null}`. For
   `tracker`, query the existing tracker adapter only. For
   `recorded_worktree`, inspect exactly the returned path only. For
   `candidate_worktree`, reserve and verify one absent issue-branch candidate
   only. For `forge_pr`, observe only the issue branch's pull request at the
   returned prefix and populate the request's `forge` slot. For
   `delivery_contract`, which the helper asks last, where a dispatch would
   follow, build the contract with one command:

   ```text
   workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract --input - <<'EOF'
   {"issue": <num>, "worktree": "<absolute-worktree>", "source_kind": "explicit_user", "source_reference": "invocation:/from-issue <num> --auto", "now": "<RFC3339-now>"}
   EOF
   ```

   `worktree` is the recorded worktree when the helper named one, else the
   reserved candidate: the contract binds custody to that exact path, and the
   helper refuses a contract naming any other. Put the printed `contract` in
   `delivery_contract` and its `initial_intent` as the only member of
   `authorization_intents`. A builder refusal (exit 2, empty stdout) fails
   loudly. For the duration of this acquisition, retain every fact previously requested during this acquisition;
   carry all collected facts into each later strict request, refreshing a value
   when its external state may have changed; never send a fact kind before the helper requests it.
   Resend with every retained fact and call `direct-owner` again. Unknown,
   duplicate, or malformed requirements fail loudly.
2. **`kind: owner`** — validate the exact closed response shape, then adopt its
   `ledger_repo_root`, `run_id`, `issue`, `attempt`, `owner`, `action_id`,
   `launch_kind`, `worktree`, `handoff_path`, and `deadline_at` as this
   invocation's complete persisted lifecycle identity, and keep its `custody`,
   installed `contract`, `contract_digest`, `pending_stage_ids`,
   `requirements`, `authority_evaluation` and `requested_scope` for the Phase-7
   handoff. Continue the existing Phase 0–7 owner flow. Do not spawn or reserve
   another owner or worktree.
3. **`kind: delivery_remainder`** — the validated object names a delivery
   remainder, not an implementation owner. Skip Phases 0–6: launch ship-issue
   remainder mode through the existing `from-issue-ship-owner` site with
   `ship-handoff.md`'s `## Remainder owner prompt`, carrying the object
   verbatim. The remainder owner writes its own `finish --summary-file -`;
   validate its returned bytes at the `workflow-response` boundary (a
   `finish` response or a `delivery_stalled` checkpoint reply) and relay them
   unchanged. A return of only the re-entry line `/from-issue <num> --auto`
   means a checkpointed denial already suspended the remainder: relay that
   line without validation. This invocation writes no `finish` of its own.
4. **`kind: terminal`** — require exactly `interface_version`, `kind`, `issue`,
   nullable `run_id`, `source`, `reason`, `blockers`, nullable `result`, and
   `reentry`; return the compact response unchanged to the caller, stop before
   Phase 1, and install no waiter.

Clear the retained observation set on `owner`, `delivery_remainder`,
`terminal`, or any failure. A later re-entry sends `delivery_contract` null
again: once installed, the ledger's contract governs.

An unknown response kind, invalid shape, or loud helper error fails loudly and
ends acquisition. It is never a signal to fall back to another lifecycle or
ledger-free route. This acquisition consumes no dispatcher summaries, deltas,
wait IDs, `wait`, or `finalize` actions.

### Interactive direct acquisition

Without literal `--auto`, a dispatcher envelope, or an explicit durability
request, retain the ordinary ledger-free worktree flow and compact direct
return.

### Explicit durable interactive acquisition

Only when an interactive user explicitly requests durable standalone orchestration,
resolve an immutable `ledger_repo_root` and stable run ID, call
bounded `workflow-state init-run`, and consume only its bounded `requirements`
from the validated `workflow_bootstrap`. Gather normalized tracker and forge
facts and a verified worktree observation for this one issue. Build its
contract with `workflow-state build-delivery --kind contract` (source
`explicit_user`, reference `invocation:/from-issue <num>`) under
orchestrate-issues' per-issue contract rule: from the requirement's
`recorded_worktree` when the bootstrap requirement's `contract_digest` is null;
with no requirement, from the reserved candidate, on the first call only when this invocation created the run,
and on a reused run only once a control summary carries
`delivery_contract_required` (send null until then). Then send the interface-3 control request — orchestrate-issues' exact
18-key shape, with `host_route: "direct"`, `max_parallel: 1`, `human_directed: true`, the resolved
attempt budget, the contract and `[initial_intent]` (null and `[]` once a
contract is installed) — and call `workflow-state control` with
`--request-file -`. Require exactly one dispatch action and require that the
first `spawn` envelope is for this issue, then project it into the owner object
as orchestrate-issues does and adopt its run, issue, attempt, owner token,
action ID, custody, contract and exact worktree as this invocation's lifecycle
identity; do not spawn another owner. Missing,
wrong-kind, wrong-issue, or multiple dispatch actions fail loudly before Phase
1. The helper may also return its one trailing `wait` action; this
already-running owner does not install the dispatcher's observer.

The `workflow-state` executable is `~/.agents/bin/workflow-state`; if the bare
name does not resolve on PATH, invoke it by that full path.

## The flow

```
0. Investigate        → summary + open questions (no files yet)
1. Worktree (skill)   → isolated workspace off origin/<integration-branch>
2. Brainstorm (skill) → <specification-directory>/<date>-<topic>-design.md
3. Grill (skill)      → spec refinements + context-doc / ADR updates
4. Plan (skill)       → <plan-directory>/<date>-<feature>.md
5. Standards review   → Codex plan review, native fallback, or self-grade
6. Execute (skill)    → subagent-driven-development
7. Ship (skill)       → ship-issue: PR, review, CI, merge, cleanup
```

**Checkpoints.** At every phase boundary, state the artifact produced and the next
action. Continue when the user's existing explicit authorization covers that
action and its target; a phase transition or fresh session does not erase that
authorization and does not imply literal `--auto`. Ask only for a concrete
missing decision when scope or authority changes. An actual permission denial
stops the denied action and is never routed around. With literal `--auto`, also
apply `AUTO.md`'s lifecycle and decision-ledger rules.

## Decision ledger (artifact discipline)

Non-obvious decisions this flow makes instead of the user live in **one issue-level ledger table** in the spec, under a section named exactly `## Decision ledger` — format and rules in `decision-ledger.md` beside this file. The plan and ADRs cite rows by ID ("per D3") and never restate them. Log only non-obvious decisions (scope, interface, behavioral, test-seam, irreversible, user-preference); consolidation of related rows is permitted and encouraged. Mandatory under `--auto`; expected interactively too.

## Risk lanes

Assigned per task at planning time (Phase 4), recorded in the plan's `## Task index`, and applied by `sdd` during execution:

- **mechanical** — deletion/renaming with **no** behavioral, configuration, interface, generated-output, or semantic-documentation effect; file and line counts never qualify a change on their own.
- **low-risk** — small semantic changes: bounded, locally-verifiable behavior changes, **excluding** anything touching concurrency, lifecycle, destructive operations, security, release, migration, or public contracts.
- **full** — everything else.

Mechanical and low-risk tasks get scoped (inline or reviewer-lite) verification; full-lane tasks get a full per-task review. The independent final two-axis review is mandatory for **every** lane.

## Skill-tool invocations

Sub-skills named here — `worktrees`, `design`, `grill-with-docs`, `writing-plans`, `doc-grounded-questions`, `codex-collaboration`, `sdd`, `ship-issue` — go through the `Skill` tool, never paraphrased from memory. `codex-collaboration` is Claude-only, so native Codex sessions take the Phase-5 native-reviewer path.

**Never hard-fail on a missing sibling** — run the phase inline: brainstorm as intent + requirements + ≥2 options; grill against the map's areas and `adr/` dirs; plan as numbered tasks with a verification gate each; execute task-by-task with the verify commands; ship per the Phase-7 fallback.

## Dispatch, phase-budget and attempt-budget rules

**Structured report-backs.** A subagent's final message is re-read by its caller on every later turn, so every `Agent` dispatch states the applicable fixed JSON return schema; details live in budgeted worktree files. Prefer the tiered agent types over `general-purpose`.

**Leaf-agent clauses.** Every prompt this skill or a file beside it composes for an `Agent` dispatch carries these two sentences verbatim, as a paragraph of their own; a prompt built from `ship-handoff.md` already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see.

**Artifact report boundary (D5, D6, D11, D14).** At every producer boundary,
preserve the received stdout bytes and pipe them unchanged through
`artifact-budget validate-report --boundary producer --input -`; only after that
succeeds may you decode JSON or validate the returned state. For both the native
and Codex Phase-5 plan-review routes, this validation happens before any state access or reviewer dispatch.
For a non-null artifact, independently run the checker
as `artifact-budget check --kind <reported-kind> --root <reported-path> --format
json`, require the reported kind/path, and compare all four metrics byte-for-byte
by integer value. A missing or non-integer metric (booleans included), checker exit 2,
validator exit 2, path/kind/metric mismatch, or complete with anything other than within_budget
is a contract error and becomes `failed`. An accepted
over-budget state follows only its owning producer's remediation and never
advances. The orchestrator retains only the root and compact metrics: never a
member list and never artifact contents. Perform this entire gate before the
corresponding `workflow-state progress` call.

**Executable phase gate.** At every phase boundary, including Phase 0 through
Phase 7, call `workflow-state progress` when lifecycle identity exists. Pass the
observed turn count and context tokens when available, the completed phase, and
truthful booleans for next-phase context need, artifact sufficiency, and
remainder self-containment. Do not fabricate usage:
omit unavailable `--turn-count` or `--context-tokens`. Use the
defaults `--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2
--context-headroom 10000`. Obey the returned action exactly; the closed set is
`continue | fresh_start | handoff | delegate`:

1. **`continue`** — proceed in this conversation.
2. **`fresh_start`** — start a fresh conversation from committed artifacts; do
   not carry conversational state.
3. **`handoff`** — beneath `ledger_repo_root`, create only the run's non-symlink
   `handoffs/` directory if missing; never pre-create the destination leaf (the
   `handoff` skill owns safe first-file creation). Invoke `handoff` with a
   destination beneath `.superpowers/workflows/<run-id>/handoffs/`, repeat
   `workflow-state progress` with `--handoff-path <exact-path>` to finalize
   `handed_off` on the same attempt, persist the handoff, and stop. For a
   dispatcher-owned acquisition, the dispatcher later relaunches the same
   lifecycle owner, exact worktree, and handoff path only from `control`'s
   returned `resume` envelope. A direct autonomous restart instead reacquires
   that same attempt, worktree, and handoff through the persisted `direct-owner` owner envelope.
   Neither acquisition creates an ordinary replacement
   worktree.
4. **`delegate`** —
<!-- agent-dispatch: id=from-issue-phase-delegate role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") delegates the entire remainder to a fresh issue owner with the lifecycle envelope and artifact paths.
   This is a fresh agent; it reconstructs context from those artifacts rather than inheriting conversation history.
   Exception — **ledger-only remainder**: when every content artifact is final and only `workflow-state` transitions plus verbatim result relay remain, delegate to the cheap bookkeeper instead:
<!-- agent-dispatch: id=from-issue-ledger-remainder role=bookkeeper model=haiku effort=low -->
Agent(subagent_type="mechanic", model="haiku", effort="low") executes the ledger-only remainder: the exact workflow-state commands and verbatim JSON relay, with no content judgment.
   Give it the exact commands, identities, and paths inline; it decides nothing and edits nothing.

For the direct-autonomous Phase-5 `delegate` case, the
mandatory direct-autonomous Phase-5 rollover in `AUTO.md` replaces the generic delegation
behavior above. Its post-rollover Phase-6 and Phase-7 gates also use the narrow
routes defined there: Phase-6 `delegate` launches the existing fresh ship owner,
and Phase-7 `delegate` launches only the ledger-only finish bookkeeper. The
behavior for all other acquisition modes retains the existing generic action
semantics unchanged.

If `workflow-state progress` is rejected because the
attempt budget's deadline has passed — either
`cannot record progress at or after attempt deadline`, or
`progress requires an active attempt` when the lazy reaper demoted the attempt
to `suspended(unknown)` first — that is an environmental interruption, not a
semantic verdict, not a harness fault, and not a reason to retry it or to doubt
your identity: the expired attempt is usually now a resumable suspension, so
follow the suspension procedure — print the canonical re-entry line and stop,
and never write a terminal `workflow-state finish` for it (the helper rejects a
finish on a non-active attempt). That rejection carries one outcome more than
the suspension it usually means. At the anti-zombie bound — an attempt parked
at the same recorded phase too many times in a row — the reaper ends the work
instead of parking it: the attempt becomes a `stopped(stalled)` terminal and
the run is over, not paused. The rejection reads the same either way, so print
the re-entry line and stop without asserting which one you got; the reaper has
already recorded it, and the re-entry either resumes the attempt or replays
that terminal. Persistence precedes notification: the reaper's
suspension is already durable before you print. Expiry is wall-clock only:
the reaper compares the current instant against the attempt's `deadline_at`
and never consults `last_progress_at`, so an attempt that is actively
working — blocked on a CI watch, say — expires exactly like one whose owner
is gone. A deadline bounds how long an owner may hold the issue; it says
nothing about whether that owner is still running. The reaper's suspension
consumes no attempt: re-entry resumes the same attempt in place, on the same
worktree, with a fresh full `attempt_budget_minutes` window and one more
launch recorded against it. A deadline therefore never opens a second
attempt, and the one fresh retry stays reserved for an attempt that reported
a terminal — an owner-reported `failed`, or a legacy expiry-sourced `stopped`
from before the suspension model.

Without lifecycle identity, apply the same action order locally with the
120-turn/150000-token ceilings and default interactive handoff behavior.

## Terminal return procedure

Use this one procedure for Phase-0 content stops, attempt budget stops, execution
failure, and Phase-7 success whenever lifecycle identity exists. The terminal
result is one `ship-summary/v2` bound to the exact current custody and
contract digest. After Phase 7 it is the ship owner's returned summary, which
carries the fresh delivery, authority, and reevaluation observations that establish the
reported delivery state (`delivery_complete` with the legacy `merged` row as
`historical_owner_result`, or `terminal_failed` with a `stopped`/`failed` row
and its partial observations). For a stop before Phase 7, assemble it here:
`state: terminal_failed`, the owner object's `custody`, its `contract_digest` as
`delivery_contract_digest`, the validated legacy `stopped` or `failed` row only
as `historical_owner_result`, and empty delivery, authority, and reevaluation
arrays. Validate the raw candidate with `artifact-budget validate-report
--boundary ship-summary --input -` before decoding, and use only its canonical
stdout as the summary bytes. The policy's `phase_reports.notes_max_characters`
is authoritative. After the `check-launch` fence of this owner's own
`action_id`, feed those bytes on stdin as `--summary-file -` to
`workflow-state finish` using the exact run and current time, in one command
whose reply is validated before decoding:

```text
workflow-state finish --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --summary-file - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
<canonical ship-summary/v2>
EOF
```

Only after that durable write succeeds, send those canonical bytes — the
validated `finish` reply — unchanged to the caller. A `terminal_failed` summary
after selection may come back as a `delivery_remainder` reply: delivery
continues under a remainder custody. Relay it unchanged all the same; the next
acquisition or control sweep launches it.
The legacy `--issue/--attempt/--result-file` transport is historical input only: it records a v1 owner's result for an attempt launched before interface 2 and is never used by a new run.

The earlier direct-autonomous controller that delegated at the mandatory
Phase-5 rollover does not run this procedure after receiving the fresh owner's
canonical terminal bytes. Its only terminal work is the validate-and-relay stop
defined in `AUTO.md`; the delegated owner already performed the single durable
`finish`.

When acquisition returns a terminal replay (`kind: terminal`) rather than an owner, print that envelope's `reentry` field to the user verbatim on its own line before relaying the compact response unchanged; a replay writes no `finish`.

The rule is: failure to persist is a failure to finish. Surface it and never report the issue as merged or completed.
Without lifecycle identity, send the same compact schema directly.

## Suspension procedure

Suspend — do not finish — when an environmental interruption pauses the work
rather than resolving it: an imminent quota or session limit, a repeated
transport failure, a permission prompt only a human can approve, or an external
wait. A suspension parks the attempt without ending it — it consumes no attempt,
needs no authorization phrase, and re-entry resumes it in place. Call:

```text
workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --issue <n> --attempt <k> --blocked-on <value>
```

with `<value>` one of `usage_limit`, `transport`, `human_gate`, or `external`
(the reaper alone owns `unknown`). Then print the canonical line as the final
user-facing output:

```text
Suspended (blocked_on=<value>). Resume: <reentry from the envelope>
```

That line is the last thing you emit — stop there, make no `finish` call, and
emit no result JSON. Suspension is NOT a terminal return.
Handoff is the deliberate context rollover with a handoff document; suspension is the environmental pause with none.

## Phase 0 — Investigate

Build a shared mental model *before* the brainstorm. No files yet. Read `investigate.md` for the pre-flight queries and the note structure. (When the retained tracker capability is unsupported, skip the fetch and PR pre-flight.)

**Pre-flight** — two sessions racing on one issue is the most expensive failure this flow produces. Run the PR pre-flight per `investigate.md`: exact matching open or merged work is reconciled within existing authorization; unknown, competing, or differently scoped work stops for the specific missing decision. Then `git worktree list | grep <bindings.vcs.worktree.prefix>issue-<num>-`:

- none → continue;
- one → **inspect before touching it**; a "clean" tree can still hold committed work that only ships at Phase 7. Check four signals: unpushed commits (`git log origin/<integration-branch>..<branch> --oneline`); workflow-state ledger attempts naming it that are `active` or `handed_off`; tracker/PR state referencing the branch; spec/plan artifacts under the retained specification and plan directories inside it. If **any** exist → prefer resume: resume that worktree when existing authorization covers the exact continuation; otherwise ask for the missing decision. On conflicting signals stop as blocked through the terminal return procedure. Deletion (`git worktree remove` + `git branch -D`) only when **provably disposable**: zero commits ahead, no active or handed-off ledger attempt, no spec/plan artifacts, no uncommitted work;
- one with uncommitted work → **stop and ask the user**; their in-progress state isn't yours to discard;
- several → stop and ask which to resume or discard.

Investigate per `investigate.md` and post the note. Several issues bundled → stop, suggest `to-issues`. Question or duplicate → report and stop. Every Phase-0 early stop uses the terminal return procedure when lifecycle identity
exists: write a `terminal_failed` summary carrying the `stopped` or `failed` row through `workflow-state finish` before notifying the caller.

**Open questions is mandatory even in `--auto`** — self-answering happens in the spec's `## Decision ledger`, not by dropping the section. With nothing open, write "None — Phase 2 will surface anything missed".

**Mechanical-only shortcut.** Declare `mechanical-only` only when the **entire** change fits the mechanical lane (§Risk lanes). Then Phase 5 self-grades against `REVIEW-CONTRACT.md` and Phase 6 dispatches one mechanic+reviewer pair for the whole change. Every phase still runs; skip manufactured TDD framing.

**CHECKPOINT** — Record the restatement and scope. Every open question needs a
disposition: an answer, "defer to brainstorm", or "agent-choose". Apply the
shared checkpoint rule; ask only for a disposition that existing authorization
does not cover.

## Phase 1 — Worktree

Create the workspace before any spec/plan/grill commit lands; those commits go *in the worktree*, never on the integration branch.

When a dispatcher-owned or direct-autonomous lifecycle envelope exists—or the
explicit durable interactive route has produced its owner envelope—use its exact absolute `worktree`,
and decide by what is actually there:

- **Absent** from both the filesystem and `git worktree list` → create it from
  `origin/<integration-branch>` at that exact path. Invoke `worktrees` only if it
  accepts the envelope's exact path; otherwise use `git worktree add -b <branch>
  <exact-envelope-path> origin/<integration-branch>`.
- **Already a git worktree checked out on this issue's branch** → **adopt it**:
  `cd` in and continue. Do not re-create it, do not move it, do not reset it. This
  is the normal shape of a handoff or retry, whose acquisition envelope returns
  the persisted attempt's worktree. Phase 0's resume-signal inspection governs
  what to do with its contents.
- **Anything else** — occupied by a non-worktree path, or a worktree checked out on
  a different branch → fail the attempt through the terminal return procedure,
  naming both the envelope path and what was found, so its acquisition owner can
  correct the reservation.

Never remove unknown contents and never choose another path. The envelope identity
stays bound to this path through shipping and cleanup. No lifecycle acquisition falls through to ordinary worktree creation.

A ledger-free interactive direct invocation keeps the standard `worktrees` flow:

1. `git fetch origin`. Invoke `worktrees` (it encodes the destructive-ops carve-out, the prefix contract, and the position checks before `EnterWorktree`/`ExitWorktree`). Branch names come from retained `bindings.vcs`; both configured forms are accepted downstream, don't strip them.
2. **Base on `origin/<integration-branch>`**, never the local branch, which may carry other agents' in-flight commits. The merge happens later, in `ship-issue`.
3. `cd` into the worktree; every later phase runs inside it. Verify `git rev-parse --git-common-dir` ≠ `git rev-parse --git-dir`.

**CHECKPOINT** — Record the worktree path and base; in `--auto` log the base SHA in the investigation note. Apply the shared checkpoint rule.

## Phase 2 — Brainstorm

Invoke `design` for a design doc under the retained specifications directory, committed in the worktree. Ground first per `grounding.md`. Resolve every Phase-0 carryover before opening a new question.

**CHECKPOINT** — Record the spec path and approval source. Apply the shared checkpoint rule; existing authorization for autonomous design decisions suffices within its scope.

## Phase 3 — Grill

Invoke `grill-with-docs`. It sharpens the spec against the context doc, surfaces glossary conflicts, and may produce ADRs; those and any context-doc edits commit in the worktree and ship when the PR merges.

**CHECKPOINT** — Record all doc updates and the refined spec. Apply the shared checkpoint rule.

## Phase 4 — Plan

Invoke `writing-plans` for a plan under the retained plans directory, committed in the worktree. The plan header carries a `## Task index` — one line per task: ID, title, files touched, and risk lane assigned here per §Risk lanes. The plan cites ledger rows by ID and appends new non-obvious plan-level decisions to the specification's ledger.

**Plan-prose ≠ code-prose.** Prose the plan dictates verbatim into the codebase (docstrings, comments, doc sentences, ADR clauses) must describe how the live code *will actually behave*; if you can't say precisely yet, write a TODO and let the execute phase rewrite it from the implemented code.

**CHECKPOINT** — Record the plan path and review state. Apply the shared checkpoint rule.

## Phase 5 — Standards review

Read `standards-review.md` and follow it: Codex `plan-review` when enabled and available, the native reviewer dispatch otherwise, the mechanical-only self-grade, and the finding-disposition rules (verify against the live worktree; ledger rows for applied findings; contract by path, never inlined).

Both routes consume the planning producer's received stdout bytes through the
Artifact report boundary above before decoding JSON or dispatching. This caller
validation is required even when the producer already validated its own candidate.

**CHECKPOINT** — Record that standards review is clean. Apply the shared checkpoint rule.

## Phase 6 — Execute

Invoke `sdd`: it reads the plan header, dispatches an implementer per task, and reviews each output by risk lane.

If the plan is `mechanical-only`, use one mechanic plus one first-pass reviewer for the whole change:

<!-- agent-dispatch: id=from-issue-mechanical-implementation role=mechanic model=sonnet effort=high -->
Agent(subagent_type="mechanic", model="sonnet", effort="high") executes the fully specified mechanical change.
<!-- agent-dispatch: id=from-issue-mechanical-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs its first-pass review.

**CHECKPOINT** — Record the implementation commit on the feature branch. Apply the shared checkpoint rule.

sdd returns only canonical JSON. Pipe the received bytes through
`artifact-budget validate-report --boundary sdd --input -` before decoding any
field. Revalidate a `present` delivery-detail package with `artifact-budget check
--kind review-package`; for `unpublished`, validate the named retained source
with `artifact-budget validate-detail-input`, consume canonical stdout, keep the
workspace and worktree, and fail without Phase 7. Never inline the report.
After these gates, sdd's `review_state` (`clean | residuals | unknown`) and
`report_path` may be used to construct the Phase-7 handoff — ship-issue's Phase-5
degradation decision reads them.

## Phase 7 — Ship

<!-- agent-dispatch: id=from-issue-ship-owner role=ship-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") launches `ship-issue` as a fresh ship owner, not inline via `Skill`. By now this conversation carries every artifact of the flow; a fresh ~10k subagent returns one summary instead of ~100 turns over a 200–300k prefix.

Read `ship-handoff.md` for the exact subagent prompt — with lifecycle identity it carries the `ship-handoff/v2` candidate built from the owner object (`ledger_repo_root`, run, owner, `custody`, the installed contract and its builder-regenerated initial intent), branch, worktree, artifact paths, `review_state`, and the fixed `ship-summary/v2` report schema; ledger-free it carries the legacy handoff. When `ship-issue` is absent, the same file's inline fallback applies. The same site launches ship-issue remainder mode for a validated `delivery_remainder` object, with that file's `## Remainder owner prompt`; the remainder owner writes its own `finish`, so its validated reply is relayed unchanged and none of the terminal write below applies to it.

After receiving the ship report, from-issue owns the terminal durable write.
A report that is only the re-entry line `/from-issue <num> --auto` means the
ship owner checkpointed a denial, which already suspended this attempt: relay
that line and write nothing. A report that validates at `--boundary
workflow-response` as `delivery_stalled` means the checkpoint already ended the
custody: relay it and write nothing.
Pipe its received bytes through `artifact-budget validate-report --boundary
ship-summary --input -`, decode only canonical stdout, consume a durable
`report_path` before advancing, and never inline either durable or retained
detail; never inline the report. For `unpublished`, independently re-read the retained candidate through
`validate-detail-input`, require non-empty findings, keep the worktree, and accept
only `terminal_failed` with a `stopped`/`failed` historical row. Resolve that `report_path` against the owner worktree,
not `ledger_repo_root` — only a `present` path is primary-checkout-relative, and
`workflow-state finish` resolves the two the same way.
Before that terminal write, run
`~/.agents/bin/workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <issue:attempt:launch>`
with this owner's own `action_id`: the ship owner and this parent share one
launch identity, so a ship report from a superseded launch means this launch is
superseded too. On `current: false` or any helper failure, write nothing, print
the canonical re-entry line `/from-issue <num> --auto` on its own line, and
stop. Then call `workflow-state finish --summary-file -` with the validated
`ship-summary/v2` bytes on stdin, per the terminal return procedure, and
validate its raw response before sending the canonical JSON unchanged. A fresh
ship agent writes only `checkpoint-delivery` under this custody, never the owner's final ledger result. Apply the same procedure to any Phase-6 execution
failure or Phase-7 stopped/failed report. `ship-issue` runs its own Phase 0–8; prefix its phases `ship-Phase-N` when narrating so the two sequences stay distinguishable.

## Notes

- Standing local-commit authorization covers spec, plan, doc, and fix commits
  where project policy or an explicit scoped user grant covers the concrete
  action, target, and effect. Apply the same rule to push, PR, merge, and cleanup
  actions. When neither source grants the action, suspend with
  `blocked_on=human_gate` and print the re-entry line. An actual permission or
  launch-guard denial stops the action and is never routed around.
- Append `Co-Authored-By` when retained `bindings.vcs.commit.co_authored_by` is true. **Never disable GPG signing defensively** — no `-c commit.gpgsign=false`, no `--no-gpg-sign`; surface signing failures.
- **PR bodies, comments, and subagent prompts use full URLs, not bare `#N`**; use retained `bindings.tracker.repo_slug`.
- If a phase reveals the previous one was wrong, back up to that phase and redo it. Don't paper over it.
