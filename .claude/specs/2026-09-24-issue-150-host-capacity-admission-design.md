# Host agent-slot admission for orchestration — issue 150

Design for [#150](https://github.com/fagenorn/nix-config/issues/150), 2026-09-24.
Grounded in the September 19 retrospective (§1), its session case 1 (the Arcwave
two-owner root), the workflow-safeguards slice (its D3: the control interface
owns capacity), the conformance engine's `host` domain (#122), and the temporary
host-admission prep note of 2026-09-20. That note's conclusions are recorded here
(D2, D3, D7, D9 and the honesty boundary), so the plan deletes it (D15).
Decisions D1–D17 bind the plan.

## Problem

An orchestrating session launches issue owners, and each owner launches its own
workers and independent reviewers. Today `workflow-state control` admits owners
against `max_parallel` alone: it counts live owner custody and never asks
whether the host can also run the workers and reviewers those owners will need.
The measured failure is the Arcwave Codex root of September 15: four agent slots
including the root, two admitted owners, and one remaining slot the two owners
passed back and forth. That root recorded 215 spawn attempts, 976 agent waits and
211 execution waits; the two wait tools were 50.85% of its recorded request
tokens (99.22% cached, so this is concentration, not proven waste). The top model
had become the scheduler.

PR #156 added a prose guard (do not improvise competing owners or retry
rejected spawns; use a direct route or report unsupported). No runtime reserves
anything, nothing reports capacity, and nothing makes a refused launch bounded.
A Codex user can still ask for `orchestrate-issues`, which Codex does not have,
and receives an improvisation rather than an answer.

## Solution

Discrete agent-slot admission in the lifecycle runtime:

1. **The host declares its slots.** One Nix-managed host declaration names each
   orchestration route and whether it is supported; a supported route declares
   its agent slots per root session. Nothing else is an input: no CPU, memory,
   Nix-daemon or load figure (D2).
2. **Admission reserves the whole role set before launch.** Every owner dispatch
   `control` returns has already claimed one owner, one worker and one reviewer
   slot in the run ledger, beside the run's one controller slot. An owner that
   cannot get the whole set is not dispatched: it waits (D4, D6).
3. **Release is part of the lifecycle write.** The transaction that records an
   owner's finish, suspension, handoff, reap or supersession also releases that
   owner's claim, in the same atomic state write (D5).
4. **Waking is event-driven.** The owner's exit produces the host completion
   notification the adapter already turns into one `control` call; that call
   admits the next waiting owner. No polling, no new wake event (D6).
5. **A refused launch is bounded.** A host refusal parks the owner and releases
   its claim. It is re-dispatched only after another claim has been released,
   within the existing anti-zombie bound (D7).
6. **Each entry path gets a typed answer.** `workflow-state host-route` returns
   a supported or explicitly unsupported result. Claude's `orchestrate-issues`
   asks first, then drives admission. Codex gets a Codex-only `orchestrate-issues`
   stub that returns the unsupported result and names `/from-issue <n> --auto`
   (D3, D9, D10).
7. **A deterministic replay proves it and records a baseline** over the real
   runtime commands, using the measured slot shape (D12).

## Terms

The repo has no glossary file, so this block defines the canonical terms (D17).

- **Agent slot**: capacity for one concurrent agent in a root session (the
  controller, an owner, a worker or a reviewer). It is never CPU, memory or a
  build job.
- **Root session**: the top-level agent session whose agents share one declared
  budget. For an orchestration, that is the controller's session.
- **Host declaration**: the authored document that states each route's support
  and its `agent_slots`.
- **Host route**: a named way of launching owners (`claude-code`, `codex`) or
  the reserved `direct`.
- **Role set**: the fixed slots one owner launch needs (owner, worker,
  reviewer).
- **Claim**: a ledger record that a holder occupies a role set (or the
  controller slot), from acquisition until release. _Avoid_: "reservation" as a
  noun, "lease", "ticket".
- **Admission**: the control-time decision to dispatch an owner only with its
  whole role set claimed.
- **Waiting**: an issue whose dispatch this sweep withheld for agent slots, not
  for `max_parallel`. Its summary state is unchanged (`queued` for a fresh
  issue).

## Decisions

### The host declaration (D2, D3, D16)

A versioned JSON document, authored once in the agent-skills tree and installed
next to the other shared policy data (the artifact-budget policy, the platform
manifest). The runtime reads the installed copy under `$HOME`, as the platform
library reads its manifest. That is also the test seam: tests point `HOME` at a
fixture. Shape, schema version 1, exact members at every level:

```json
{
  "schema_version": 1,
  "routes": {
    "claude-code": {"support": "supported", "agent_slots": 7},
    "codex": {"support": "unsupported"}
  }
}
```

- `agent_slots` counts every concurrent agent in one **root session**: the
  controller, its owners and their workers and reviewers. It is a declared
  budget, not an observation. No supported host exposes a capacity query or an
  atomic claim (prep-note inventory), so the declaration is the budget
  admission reasons over.
- A supported route must declare at least `4` slots: one controller plus one
  full owner role set (D4). The validator refuses smaller values, so no
  declaration can admit an owner without its reviewer.
- `claude-code` is declared at `7` = 1 controller + 2 × 3. That keeps today's
  default `max_parallel` of 2 able to run two owners, each with reserved
  capacity. A project that resolves a higher `maxParallel` is capped at two
  concurrent owners until the declaration is raised. The value is host policy
  and can be changed in one place (D16).
- `codex` is declared `unsupported`. The route names are closed by the
  document. `direct` is a runtime-reserved route name that never appears in the
  document (D3).

### Routes (D3)

| Route | Who calls it | Admission |
|---|---|---|
| `claude-code` | Claude's `orchestrate-issues` adapter | Full admission: a controller claim plus a role-set claim per owner dispatch |
| `direct` | `from-issue`'s explicit durable interactive acquisition (the caller *is* the one owner) | Not applicable: control requires exactly one requested issue and `max_parallel` 1, reads no declaration, records no claims, and reports the route |
| `codex` | the Codex `orchestrate-issues` stub, through `host-route` only | Unsupported: `host-route` returns the explicit result; `control` refuses the route with no write |

A run binds its route on its first control sweep under the new schema, and the
binding is immutable. A later sweep naming another route is refused, following
the immutable-delivery-contract precedent. `workflow-state direct-owner` (the
`from-issue --auto` direct path) and every owner-side command keep their
interfaces. A run without admission (`direct`, or any direct-owner run) carries
no claims.

### Claims and the ledger block (D4, D5, D11)

The ledger schema goes from 3 to 4. The run gains one member, `admission`:
`null` until the first v4 control sweep, then

```json
{"route": "claude-code", "releases": 3, "claims": [
  {"holder": "controller", "roles": {"controller": 1},
   "acquired_at": "…", "released_at": null, "release_event": null, "release_seq": null},
  {"holder": "12:1:1", "roles": {"owner": 1, "worker": 1, "reviewer": 1},
   "acquired_at": "…", "released_at": "…", "release_event": "finished", "release_seq": 3}
]}
```

- **Holder.** `controller` (one per run) or a custody launch `action_id`
  (`issue:attempt:launch` or `issue:rN:launch`), which is unique per launch.
  Host task handles never appear. They stay adapter-side correlation data, as
  they are today.
- **Role set.** Fixed in the runtime rather than declared: controller 1; every
  owner launch, whether implementation or delivery remainder, claims owner 1,
  worker 1 and reviewer 1. Slots are interchangeable at the host, so the two
  support slots also cover the two-axis review (conformance ∥ correctness), the
  owner's widest concurrent fan-out. `sdd` never runs parallel implementers.
  Admission is all-or-nothing per owner.
- **Release events** are a closed set: `finished`, `suspended`, `handed_off`,
  `superseded`, `owner_unavailable`, `launch_refused`, `finalized`.
  `release_seq` takes the next value of the run's `releases` counter, so
  releases are totally ordered even when timestamps tie.
- **Invariants** checked by state validation: exact members; at most one held
  controller claim; no two held claims share a holder; every held owner claim
  names its issue's current live launch. Released claims are kept as the audit
  trail the replay reads.

**Release is one step at one site (D5).** Every committed state write passes
one boundary. Most writers reach it through the shared transaction; the
direct-owner writer reaches it without one. At that boundary, just before the
write, a single `settle` step runs. `settle` releases
every held owner claim whose holder is no longer its issue's current `active`
launch, stamps the commit's `updated_at`, and derives the event from the
holder record:

- terminal record (merged, stopped, failed, completed) → `finished`;
- `suspended` with `blocked_on: host_capacity` → `launch_refused`;
- any other `suspended` → `suspended`;
- `handed_off` → `handed_off`;
- a newer launch on the same record → `superseded`.

So `finish`, `suspend`, `progress` (handoff), the reaper, forge reconciliation,
the third-attempt refusal and the delivery commands all release in the same
write that records their transition, with no per-writer hook to forget.
`settle` is idempotent and does nothing when `admission` is `null` or the route
is `direct`. `control` adds the two releases no ledger state implies: a
current-launch `unavailable` owner observation releases that launch's claim
(`owner_unavailable`), and a `finalize` response releases the controller claim
(`finalized`).

**Migration and adoption (D11).** The 3→4 step writes `admission: null`.
Adoption happens once, in the sweep that first binds the block. At that point,
live custody with no claim (an in-flight v3 run) is adopted as held claims,
even when that exceeds the declaration, and new admission waits until the run
drains below it. After binding, only a control dispatch creates an owner
claim. A launch that `finish` records without a dispatch, such as the first
delivery remainder of a failed-after-selection summary, holds no claim until a
control dispatch actually launches it. A released claim is never re-acquired
for the same launch.

### Admission inside control (D6)

One `control` transaction, in order:

1. Validate `host_route` and resolve the declaration. An unsupported or
   undeclared route, or a missing or invalid declaration, is refused as a
   `WorkflowError` with nothing written. That is the inner check; `host-route`
   gives the typed answer (D9).
2. Bind or verify the run's route, adopting only at first binding (D11). Apply
   `launch_refused` observations (D7), settle, then release the claims of
   `unavailable` launches.
3. Acquire the controller claim if the run holds none. Compute availability:
   `agent_slots` minus the roles of held claims whose holder is live at `now`.
   Expired or unavailable holders do not count, which is the same liveness
   predicate owner occupancy uses today.
4. Run the existing lanes in their existing order: remainder, recover, resume,
   retry, spawn. Every dispatch lane now requires **both** a remaining
   `max_parallel` unit and a free role set, and acquires the role-set claim in
   the same step it creates the launch. An issue whose dispatch is withheld for
   slots while `max_parallel` still had room joins `waiting`. So do issues held
   back by the refusal gate (D7). `max_parallel` keeps its meaning as the
   workflow-level issue ceiling.
5. At `finalize`, release the controller claim. The commit-time settle then
   records the releases of any attempts reaped in this sweep.

There is no persisted queue. The waiting set is recomputed every sweep from
the request's issue order and the lane precedence, so the ledger holds one fact
once. The `wait` action keeps `wake_on: [deadline, owner_notification,
tracker_change]`. A slot frees only when an owner's custody ends, and every such
end is either an owner exit, which the host reports as an owner notification,
or a deadline, which the wait already arms. When work waits for slots, some
live claim is holding them, so its end will wake the adapter. A run with no
live claim can always admit one owner, because of the declaration floor. That
leaves one case where work waits with nothing live: refusal-gated work. That
sweep finalizes and reports the issue as waiting (D7).

### Launch refusal (D7)

The adapter reports a host refusal of an owner launch with a new owner
observation state, `launch_refused`, for that action's custody launch. `control`
then suspends that custody at its current phase with a new blocking cause,
`host_capacity`. Implementation attempts and delivery remainders both support
suspension. The claim is released through the settle derivation. `host_capacity`
is auto-resumable but **gated**: its resume is withheld until some *other*
claim has a `release_seq` greater than the refused claim's. It is a
control-only cause: owners cannot report it through `suspend`.

The run is bounded in two ways. No re-dispatch happens without an intervening
release, so refusals cannot drive a loop. The existing anti-zombie bound (three
consecutive same-phase resumes) stops a custody that keeps being refused. The
existing `unavailable` state is kept for a launched owner that died. It still
takes over at once, subject to admission.

### Interfaces (D8, D9)

**Control interface 3.** The request gains one member, `host_route`, with value
`claude-code` or `direct`. The response gains one member:

```json
"admission": {"route": "claude-code", "declared_slots": 4,
  "reserved": {"controller": 1, "owner": 1, "worker": 1, "reviewer": 1},
  "available": 0, "waiting": [14]}
```

`reserved` and `available` are computed *after* this sweep's acquisitions, so
the response that carries a spawn already reports the capacity reserved for
that owner. `waiting` preserves request order. For `direct`, `declared_slots`
and `available` are `null`, every `reserved` count is `0` and `waiting` is
empty. Summaries, deltas, the `wait` and `finalize` actions, and the
interface-2 owner and remainder objects are unchanged. The request and the
response move to 3 together, so a stale adapter fails loudly on the version
rather than silently dropping capacity. The owner observation's closed state set
becomes `unavailable | launch_refused`.

**`workflow-state host-route --route <name>`.** Read-only: it takes no ledger,
lock, clock or repository root. It prints one of these exact-member results,
each accepted at the `workflow-response` boundary:

```json
{"interface_version": 1, "kind": "host_route", "route": "claude-code",
 "support": "supported", "agent_slots": 7, "reason_code": null, "alternative": null}
{"interface_version": 1, "kind": "host_route", "route": "codex",
 "support": "unsupported", "agent_slots": null,
 "reason_code": "declared_unsupported", "alternative": "/from-issue <issue> --auto"}
```

The closed `reason_code` values are `declared_unsupported`, `route_undeclared`,
`declaration_missing` and `declaration_invalid`. Any well-formed answer, even
an unsupported one, exits 0. Only usage errors exit 2. The result shape lives
here only; neither skill restates it.

### Entry paths (D9, D10)

- **Claude, `orchestrate-issues`.** PR #156's capability paragraph is replaced.
  Before `init-run`, call `host-route --route claude-code` once and validate it
  at the boundary. `unsupported` → render that result plus its alternative as
  the final report and stop. `supported` → send `host_route: "claude-code"` on
  every control request (interface 3). Other changes: a rejected owner launch
  is never retried; it becomes one control call with a `launch_refused` owner
  observation for that action. The final report lists `waiting` issues as
  queued for agent slots. The adapter still never calculates slots or alters
  `max_parallel`; the admission report is rendering data only.
- **Claude and Codex, `from-issue`.** The explicit durable interactive path sends
  the interface-3 request with `host_route: "direct"`. Nothing else in
  `from-issue` changes.
- **Codex.** The Codex module links a Codex-only `orchestrate-issues` skill into
  the Codex skills directory. The name is exactly what a Codex user types, as the
  Arcwave root did. It stays outside the shared tree so it cannot collide with
  Claude's skill of the same name. Its whole instruction: run `host-route --route
  codex`, return the validated result verbatim, name `/from-issue <n> --auto` per
  issue, one at a time, as the supported sequential route, and never spawn owners,
  count threads, or retry.
- **Documentation**, written with the implementation, not before it. The project
  `CLAUDE.md` paragraph on skills that stay out of the shared tree gains the
  Codex-side stub. `CLAUDE.md` also records the declaration's authored home and
  its per-root-session meaning.

### Conformance discovery (D13)

One optional `host`-domain check, `host.admission.declaration`, is selected by
`local` and `doctor`. It validates the installed declaration through the same
library the runtime uses and reports bounded facts: the supported routes with
their `agent_slots`, and the unsupported routes. The check never reads or
writes a ledger or a claim. Failure reason codes are `declaration_missing` and
`declaration_invalid`, with a `user_action` repair that names the authored
declaration.

## Acceptance criteria → design → evidence

| Criterion | Design element | Proving evidence |
|---|---|---|
| Runtime schema records controller/owner/worker/reviewer claims and releases them atomically from observed lifecycle events | Schema-4 `admission` block; commit-time `settle`; control's `owner_unavailable` / `finalized` releases (D5) | CLI tests. After `finish`, one state read shows the terminal record and the claim `finished`, with `released_at` equal to that write's `updated_at`. Suspend, handoff, reap, reconcile, supersession, `unavailable` and `launch_refused` each release with their event. A refused write (e.g. backward time) leaves both the lifecycle record and the claim unchanged |
| Supported route reports available and reserved worker capacity before an owner launch | Interface-3 `admission` report computed after acquisition; `host-route` for the static budget (D8, D9) | The control response carrying a spawn reports that owner's claim in `reserved` and the reduced `available`. Adapter contract test: spawns execute only from that validated response |
| Admission reasons only about declared agent slots | Declaration with only `agent_slots`; exact-member validator (D2) | Validator refuses any extra member; the runtime takes no host metric input |
| Replay proves owner-only occupancy cannot over-admit; a `max_parallel` clamp does not satisfy it | Both limits per dispatch; `waiting` distinguishes slot-withheld work (D6, D12) | Fixture keeps `max_parallel` 2 with 4 declared slots. The first sweep admits A, and B is in `waiting` although owner occupancy 0 < 2. Same request with 7 slots admits both, so the fixture is not a hidden clamp. A mid-run tracker wake still withholds B |
| Two-owner fixture queues excess and has no capacity-induced spawn retry loop | Waiting set; refusal gate + anti-zombie bound (D7) | Replay: one dispatch per owner, zero host refusals, no identity dispatched twice without an intervening release. Scripted-refusal variant: B is dispatched at most once per release; the response to the refusal holds no dispatch for B |
| Host completion releases and wakes the next queued owner without model-driven polling | Release in `finish`'s write; completion notification → one control call (D5, D6) | Replay: A's claim is released in A's `finish` write. The single control call triggered by A's completion returns B's spawn. Control calls = 1 + delivered host events; none without an event |
| Independent review preserved when owners run sequentially | Fixed role set with reviewer; all-or-nothing admission; declaration floor of 4 (D4) | Replay: the admitted owner's reviewer step never waits for a slot and runs as a distinct agent. A 3-slot declaration is refused rather than admitting a reviewer-less owner |
| Replay reports controller turns, wait-producing responses, worker utilization, time to first useful result; baseline, no percentage target | Replay metrics and committed baseline fixture (D12) | Exact-match assertion against the committed baseline; no target field exists |
| Claude and Codex entry paths use the capability or fail with an explicit unsupported result | `host-route`; Claude adapter; Codex stub; `direct` for the single-owner path (D3, D9, D10) | `host-route` result tests per reason code. Skill contract tests pin the Claude adapter sequence and the Codex stub. The installed-tree check shows the stub only in the Codex skills tree |

**Demo.** The replay test itself: the measured two-owner shape on a
declaration with one usable worker/reviewer slot once both owners were
admitted under owner-only accounting (4 slots, controller included). One owner
runs, the other waits, and A's completion admits B with no retry.

### Replay definition (D12)

A deterministic test drives the real `workflow-state` commands (`control`,
`finish`, and `host-route` for the entry check). It runs against a simulated
host and a simulated adapter that follows the `orchestrate-issues` contract to
the letter: one control call at start and one per delivered host event, spawns
executed from returned actions, one-shot waits, no polling. Time is an injected
simulated clock in whole minutes.

- **Scenario (measured shape).** Route `claude-code`, fixture declaration 4
  slots, two ready issues A and B, `max_parallel` 2, attempt budget 180. Each
  owner runs two tasks, each a worker for 20 minutes then a distinct reviewer
  for 10 minutes. It then finishes `merged` with its delivery complete, using
  the lifecycle tests' existing terminal path, so no remainder custody follows.
  The simulated host refuses any launch beyond 4 live agents and counts
  refusals.
- **Metrics:**
  - `controller_turns`: control invocations. The one entry `host-route` call is
    not counted.
  - `wait_producing_responses`: control responses ending in `wait`.
  - `worker_utilization`: an integer pair. The numerator is busy worker and
    reviewer slot-minutes. The denominator is the slot-minutes not held by the
    controller or a live owner, summed over the makespan.
  - `time_to_first_useful_result`: minutes from the first control call to the
    first `merged` finish.
  - Also recorded: `owner_dispatches`, `host_refusals`, `makespan`.
- **Predicted baseline.** 3 controller turns; 2 wait-producing responses; 2
  owner dispatches; 0 refusals; first useful result at 60; makespan 120;
  utilization 120/240. The committed fixture records what the implementation
  measures. A deviation from this prediction is explained in the plan's review,
  never tuned away.
- **Variants:** the 7-slot run (both admitted); a scripted single refusal of
  B's launch; a 3-slot declaration (refused).
- **What the baseline is.** A future initial target is set against this
  baseline. The Arcwave counts are cited as the originating observation. They
  are not comparable: that was a different host, and it was model-driven.

## Honesty boundary (D14)

- The replay proves the runtime's state machine and the adapter contract it
  encodes. It is the demo, and it is labeled a fixture host.
- "Supported" for `claude-code` means an adapter exists that launches only
  admitted owners, has a host completion signal, and turns a refused launch into
  a bounded result. It does **not** mean Claude Code exposes or enforces the
  declared number. A live Claude-host orchestration is not acceptance evidence
  for this issue.
- Owners consume their reserved role set implicitly. An owner's own subagent
  launches are not individually claimed. Nested launches beyond one worker and
  one reviewer at a time, such as a design owner's explorer, are outside the
  accounting, which is only as true as the declaration.
- Accounting is per run, matching a per-root-session budget. Two concurrent
  orchestrations on one machine each assume their own declared budget.
- Codex is unsupported because no Codex adapter exists and native Codex
  collaboration exposes no pre-launch claim or completion event the runtime
  could bind. It is not unsupported because of a measured limit. No shim counts
  threads, archives sessions or starts an app-server.

## Test seams

- **S1 — the `workflow-state` CLI as a subprocess** (`control`, `finish`,
  `suspend`, `progress`, `host-route`), with `HOME` pointed at a temporary
  directory holding a fixture declaration. Prior art: the lifecycle suite's
  CLI runner and control-request helper, and the platform-manifest tests'
  `HOME` override.
- **S2 — the replay:** a test-local simulated host and adapter over S1, run by
  the workflow test recipe. Prior art: the combined single-ledger control replay
  and the demo tests. Its baseline is a committed JSON fixture beside the
  existing test fixtures.
- **S3 — the `workflow-response` boundary**
  (`artifact-budget validate-report`) for control interface 3 and `host_route`.
  Prior art: the delivery-model and artifact-budget boundary tests.
- **S4 — skill contract tests** over both the source skill trees and the
  installed trees: the Claude adapter's host-route-first sequence,
  `host_route`, `launch_refused`, no retry, no polling; the Codex stub present
  in the Codex tree and absent from Claude's; `from-issue`'s `direct` request. Prior art:
  the workflow-skill and dispatch-contract suites.
- **S5 — the conformance check** through the registry and checks suites.

No other seam: implementers do not unit-test private helpers in place of S1/S2.

## Out of scope

- CPU, memory, Nix-daemon, test-host or general load scheduling
  (`.out-of-scope/host-contention-scheduling.md` still stands for those).
- Cross-run or machine-wide slot accounting; per-host Nix options for the slot
  count; a separate route for the local-model `claude-local` wrapper.
- Claiming each subagent launch inside an owner, and guidance for owners on
  in-owner refusals.
- A Codex orchestration adapter, or reading Codex app-server or thread state.
- Raising global concurrency, changing `max_parallel`, redesigning the
  orchestrator or its lane precedence, and anything in the release adapter.
- Persisting owner `unavailable` observations beyond the sweep that reports
  them, which is today's behavior.
- A percentage target for any metric.

## Open questions resolved

- **Q1, where capacity is declared and what "supported route" means:** a Nix-managed
  host declaration read by the runtime, with the request naming only the route
  (D2). Claude's `orchestrate-issues` is the supported route, with the meaning
  given in the honesty boundary. Codex is explicitly unsupported (D3, D10).
- **Q2, claim shape:** a fixed role set of owner, worker and reviewer per owner
  launch, plus one controller slot per run. Admission is all-or-nothing, and the
  declaration floor of 4 preserves review under sequential execution (D4).
- **Q3, release events and atomicity:** one commit-time `settle` derives the
  event from the holder record, plus control's `owner_unavailable` and
  `finalized` releases (D5).
- **Q4, the replay:** a deterministic simulation over the real CLI, with the
  metrics defined above and a committed baseline fixture (D12).
- **Q5, the unsupported result:** the typed `host_route` result from one
  read-only command, relayed verbatim (D9).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One design for discrete agent-slot admission; the plan slices it (runtime → interfaces → entry paths → replay → conformance) | Issue scope; retrospective: one bounded scheduling scenario, no broad orchestrator | Decompose into separate issues now: the criteria are one capability and only prove out together |
| D2 | Host declaration: Nix-managed JSON under the shared-data location, read by the runtime via `$HOME`; per-route `support` and `agent_slots` per root session; nothing else | Criterion "only declared agent slots"; platform-manifest precedent; out-of-scope note: host truth is not project policy | Slot count in the control request from `resolve-bindings` (model-copied capacity; legacy resolver being retired in #100); project contract (a host is not a project) |
| D3 | Routes: `claude-code` supported; `codex` declared unsupported; reserved `direct` for single-owner control (one issue, `max_parallel` 1, no claims); route bound per run, immutable | CLAUDE.md: orchestrate-issues is Claude-only; prep note: no Codex claim/notification API; immutable-contract precedent | Treat native Codex as supported via thread counts or app-server (prep note forbids the shim); gate the direct path too (breaks Codex's durable `from-issue`) |
| D4 | Fixed role set per owner launch (implementation or remainder): owner 1, worker 1, reviewer 1; controller 1 per run; all-or-nothing; declaration floor 4 | Issue: reserve owner plus independent reviewer; sdd: no parallel implementers, two-axis review is the widest fan-out | Declared per-route role sets (YAGNI); owner-only claims (fail the fixture); one shared worker/reviewer slot (cannot host the two-axis review) |
| D5 | Claims recorded in a schema-4 run `admission` block keyed by launch `action_id`; release at the transaction commit by one `settle` step deriving the event; control releases `owner_unavailable` and `finalized` | Criterion: record and atomically release from observed events; the-bar: one authoritative home | Derive-only occupancy (no record, no release event); per-command release hooks (a new writer could forget one) |
| D6 | Admission composes with `max_parallel` in every dispatch lane; no persisted queue (`waiting` recomputed); existing `wait` seam and wake events reused | Safeguards D3 (control owns capacity); prep note (one-shot wake through the existing seam); issue: keep `max_parallel`'s meaning | A new slot-release host event (the host emits none, and every release already coincides with an owner exit or a deadline); a persisted queue (a second copy of lane order) |
| D7 | New `launch_refused` owner observation → custody suspended `host_capacity` (control-only cause), claim released, re-dispatch gated on a later release, anti-zombie bound applies; `unavailable` unchanged | Prep note: a rejected spawn is bounded, never a loop; D2 of the lifecycle: suspension is a parked interruption | Reuse `unavailable` (instant takeover re-launches into the same refusal: the measured loop); lowering a persisted ceiling (more state, same bound) |
| D8 | Control request and response move to interface 3 together (`host_route`, `admission` report computed after acquisition); summaries, actions, owner objects unchanged | Exact-member interfaces; version bumps make stale adapters fail loudly | Extend interface 2 in place (a stale adapter would silently drop capacity) |
| D9 | `workflow-state host-route` is the one home of the typed supported/unsupported result (closed reason codes, `alternative`), validated at the workflow-response boundary; control refuses unsupported routes as the inner check | the-bar: one authoritative home, defense in depth, fail loud | Result spelled in skill prose (two homes); control-only refusal (an error string, not a typed result) |
| D10 | Codex entry: a Codex-only `orchestrate-issues` stub linked by the Codex module that relays `host-route codex` and names `/from-issue <n> --auto` | Session case 1: a Codex user typed `@orchestrate-issues`; shared-tree skills also reach Claude | A shared-tree stub (collides with Claude's skill); a global AGENTS.md rule (hot-path prose, #99) |
| D11 | Migration writes `admission: null`; adoption only in the binding sweep (unclaimed live custody adopted even beyond the declaration, new admission waits for the drain); afterwards, claims come only from control dispatches, so an undispatched launch recorded by `finish` holds none | Versioned-state precedent; grill: `finish` records an `active` first remainder no dispatch launched | Ignore migrated owners (over-admits on upgrade); standing adoption (claims a phantom remainder and blocks waiting owners until its deadline) |
| D12 | Replay: deterministic simulated host and adapter over the real CLI; measured shape (4 slots including controller, 2 owners, `max_parallel` 2); four metrics defined here; baseline is a committed exact-match fixture; 7-slot, scripted-refusal and 3-slot variants | Retrospective acceptance; issue: baseline without a percentage target | A live host replay (not deterministic); percentage targets; replaying the Codex transcript (not the supported route) |
| D13 | One optional `host`-domain conformance check reports declaration validity and route support through the runtime's library; it never touches claims | Issue decisions cite #122; prep note: conformance discovers, never owns claims | No conformance surface (drops the host-truth domain the issue names); conformance-owned claims (not atomic, timeless reports) |
| D14 | Honesty boundary: `claude-code` "supported" = admitted-only launches, completion signal, bounded refusal; in-owner subagents not individually claimed; per-run accounting; no live-host evidence claimed | Prep note's closing warning; the-bar: truthful terminal states | Claim a supported native capacity integration the evidence cannot show |
| D15 | The plan deletes the 2026-09-20 host-admission prep note; its conclusions live in this spec | The prep note's own durability instruction | Keep it (a temporary note outliving its purpose) |
| D16 | `claude-code` declares 7 slots (1 controller + 2 × 3), preserving today's two-owner throughput under the default `max_parallel`; a project resolving more is capped at two owners until the declaration is raised | Resolved `maxParallel` default 2; retrospective: do not raise fan-out first; declaration is host policy | 4 (serializes every Claude run, a change nobody asked for); a larger value that never binds (admission would be nominal on the supported route) |
| D17 | No glossary or ADR file is created: this repo keeps its decisions in spec ledgers and has no context map. The Terms block is canonical; `CLAUDE.md` is updated with the implementation; the out-of-scope note gains its boundary line now | grill-with-docs: follow the repo's layout and create files lazily; ADR bar (hard to reverse, surprising, a real trade-off) is not met by versioned, reversible interfaces | Start a `docs/CONTEXT.md` or `adr/` tree for one issue (imposes a new layout mid-flight) |
| D18 | Homes: `scripts/host_admission.py` (installed `~/.agents/lib/python/host_admission.py`) owns the declaration schema, route-name grammar, role sets, slot floor and reason codes; the declaration is `home/common/agent-skills/host-declaration.json` (installed `~/.agents/share/host-declaration.json`); `workflow-state` and the conformance evaluator load the library as a source sibling in the repository and the installed copy otherwise, and read the declaration from `$HOME`; claim policy stays in `workflow-state.py`; `host-route --route` outside the grammar, or `direct`, is a usage error | D2 platform-manifest precedent; `_delivery()` loader precedent; D13 (conformance never owns claims) | Claim logic in the library (hands conformance a claim API); a new private workflow module (a third install surface for one feature) |
| D19 | Refines D5's derivation, in order: issue delivery complete → `finished` (a delivery-complete `finish` can leave its record `active`); a newer launch on the holder's record → `superseded` (an expired owner reaped and resumed in one sweep); terminal → `finished`; `host_capacity` → `launch_refused`; other suspension → `suspended`; `handed_off` → `handed_off`; anything else raises | `finish_outcome` keeps a null-historical record `active`; reaper and resume lane share one control transaction | Derive from record state alone (a delivery-complete record would hold its claim forever) |
| D20 | A controller claim is persisted only by a sweep ending in `wait`; a sweep ending in `finalize` counts it for availability, persists no new one and releases a held one `finalized`; the first interface-3 sweep persists the route binding even when it finalizes | Byte-stable actionless replays in the lifecycle suite; bounded audit trail; D3 immutable binding | A claim per sweep (every finalize replay would append two records and rewrite the ledger) |
| D21 | Slot withholding mirrors `max_parallel` withholding: a lane checks for a free role set before planning with dispatch permitted, and an issue it skips while `max_parallel` had room joins `waiting`; a claim is acquired for every dispatch that creates a launch holding no claim (never for a re-emitted recover); a `waiting` issue with no installed contract reports `delivery_contract_required` | Existing capacity idiom in `command_control`; #171 D31 (a null digest asks before a would-be dispatch); orchestrate-issues sends a contract only while its summary asks | Plan with dispatch, then re-plan (a second planning path per lane); a silent `waiting` summary (a letter-following adapter then sends null and the freed slot finalizes with the issue unrun) |
| D22 | `launch_refused` applies only to an issue's current `active` launch holding a held claim under a non-`direct` route; a stale identity is ignored like `unavailable`, any other is refused with no write; `validate_control_custody` returns the unavailable and refused identity sets; a remainder parks through a generalised remainder suspension with its existing stall bound | D7; exact-member, fail-loud validation | Accept refusals for unclaimed launches (nothing to release, no refused claim for the gate) |
| D23 | Test seams: the lifecycle helpers become a `LifecycleHarness` mixin whose CLI runs with `HOME` at a fixture declaring `claude-code` 64 slots, so pre-admission tests never bind a slot; other single-issue `max_parallel` 1 requests use `direct`; the replay's owners finish through builder-built contracts, `checkpoint-delivery` and a `delivery_complete` `finish --summary-file -`, because the suite's `finish` helper round-trips through schema 2 and discards `admission` | S1/S2 prior art; `BuilderHarness`, `DeliveryLoopTest.deliver` | Re-pin every existing test to real slot counts (churn without evidence); the schema-2 helper (loses the claims the replay reads) |
| D24 | Check `host.admission.declaration`: subject kind `capability`, no dependencies (a host fact independent of the contract), findings `declaration_missing`/`declaration_invalid` → repair `host.admission.declare` (`user_action`, null operation); passed facts `supported_routes` (`<route>=<slots>`) and `unsupported_routes`, failed facts `declaration_path`; `install_home` installs the committed declaration by default | D13; closed `SUBJECT_KINDS`; conformance D25 null operations; #147 D7 (one installed-layout home) | A new subject kind (widens the report schema for one check); depend on the contract ladder (a broken contract would hide a host fact) |
| D25 | The Codex stub lives at `home/common/codex/skills/orchestrate-issues/`, linked by the Codex module as the whole directory `~/.agents/skills/orchestrate-issues`; `agent-installed-skill-tests` also runs the skill-contract suite so the installed-tree check executes | CLAUDE.md skills layout (Codex reads whole-directory links under `~/.agents/skills/`; Nix never writes `~/.codex/skills/`) | `~/.codex/skills/` (runtime state Nix does not own); the shared tree (reaches Claude and collides with the adapter) |
| D26 | Refines D7's gate: any later release opens it, the controller's `finalized` release included, so refusal-gated work that finalized as `waiting` resumes once on the next orchestration invocation; pinned by a Task 5 test | Phase-5 standards review; D6 (refusal-gated work finalizes as waiting when nothing else is live); orchestrate §5 names the re-invocation as the run's re-entry | Only owner releases open the gate (a refusal-gated custody with nothing else live could never resume) |
| D27 | The replay's fixture host runs each owner's worker and reviewer steps as distinct support agents and asserts it never exceeds the declared agents, so "the reviewer step never waits and runs as a distinct agent" is measured; metrics and baseline unchanged | Phase-5 standards review; criterion "independent review preserved" evidence; D12, D14 | An owner launch that implicitly reserves one support slot (the evidence holds by construction) |
| D28 | The replay baseline keeps the independently derived prediction (the hand-simulated `measured`, `seven_slots` and `scripted_refusal` values) as its expected values; a measured mismatch is diagnosed as a Tasks 1–5 defect first, and a baseline value changes only when the task report shows the prediction itself was mis-derived, naming the cause per deviation | Execution-start package scan (rubric: no expected value taken from the code under test); D12 (the fixture records what the implementation measures, which a correct implementation makes equal to the prediction) | Overwrite the baseline with whatever the replay measures (the exact-match assertions would then restate the implementation's own output) |
| D29 | Task 8, although mechanical, ends with `just agent-workflow-tests` green like Tasks 1–7 | Plan Global Constraints ("every task ends with `just agent-workflow-tests` green"); a contract test may name the deleted prep note | Exempt Task 8 from the suite (the constraint names no exemption) |
| D30 | Task 5's refusal gate (per D26) widens the `waiting` set Task 4 introduces: after Task 5, `waiting` also holds refusal-gated issues while slots are free; Task 4 states its slot-only definition as the Task 4 behaviour and Task 5 amends that prose and its tests | Execution-start package scan; D6, D7, D26 | Keep Task 4's "exactly the issues skipped for want of a role set" as a permanent invariant (contradicts D26's gated waiting) |
