# Control-plane cutover to core state, issue 339

Design for [issue 339][i339], package 3 of 3 of [issue 125][i125], executing the
[issue 117 decision](2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md) (cited below as
"the record") on top of [package 1](2026-10-09-issue-337-attempt-identity-migration-design.md) ("P1")
and [package 2](2026-10-10-issue-338-fenced-custody-receipts-design.md) ("P2").
Base: main `079b835c`. Decisions were taken autonomously under `from-issue --auto`; each non-obvious
one is a ledger row.

[i125]: https://github.com/fagenorn/nix-config/issues/125
[i132]: https://github.com/fagenorn/nix-config/issues/132
[i133]: https://github.com/fagenorn/nix-config/issues/133
[i150]: https://github.com/fagenorn/nix-config/issues/150
[i151]: https://github.com/fagenorn/nix-config/issues/151
[i339]: https://github.com/fagenorn/nix-config/issues/339

## Problem

After packages 1 and 2 every run has a core identity and every implementation attempt has fenced
custody in the core, but the orchestration control plane still works from a second set of facts:

- **Which runs exist** is answered by listing `.superpowers/workflows/`. `direct-owner` scans it for
  `direct-<issue>-*`, `build-delivery` scans it for the ledger that installed a contract, and the
  orchestrate-issues skill tells the dispatcher to look through it for a run to reuse. A stray or
  copied directory changes the answer, and nothing in the core is consulted.
- **Who occupies an agent slot** ([issue 150][i150]) is a list in the run ledger. It is released by
  ledger code that runs beside the custody settle step, not by the custody transition, and the
  `host_capacity` gate compares sequence numbers that exist only in that list.
- **What was delivered** ([issue 151][i151]) lives only in the ledger: the contract, the authorization
  chain, the observations and the remainders. A delivery remainder has no custody in the core, so
  the fence of package 2 does not cover it, and a `merged` attempt can never seal because the core
  holds no proof of delivery.

So the core is the authority for custody and a bystander for everything the dispatcher decides with.

## Solution

Make the attempt store the one place these facts are held, and keep the ledger as the projection
package 2 made it.

1. **Runs are found by key.** The three listings are replaced by lookups in the core's creation-key
   index under the explicit ledger root (`--repo-root`). A directory the index does not name is not
   a run.
2. **A slot claim is a custody span.** A held owner claim is an open span that carries the claim, so
   it ends in the same core operation that ends the custody. Control counts occupied slots from the
   store.
3. **A wake is a recorded event.** The write that frees capacity records it on the custody
   transactions it concerns. The next sweep reads that state; no sweep re-derives it from sequence
   numbers, and nothing polls.
4. **Delivery has a transaction.** Each installed contract gets a delivery transaction whose subject
   is the contract and whose history holds the delivery objects as submitted. When the four
   postconditions are settled it seals `succeeded` with them as its proof, and the custody
   transactions of that issue seal after it.
5. **Remainders get custody.** A delivery remainder has a custody transaction like an attempt's.

Ledger schema becomes 10. Its field sets do not change, replies do not change, and `check-launch`
stays read-only.

## Decisions

### What control reads from the store

The ledger stays the projection of P2 D4: every committed write passes the settle step in
`commit_state`, the core goes first and can refuse. This package adds what a control decision reads
from the store at its locked read, before it decides (per D12):

| Decision input | Read from |
|---|---|
| Which run a handle, an issue set, a direct issue or an installed contract names | the creation-key index |
| The run's identity | the run transaction (P1, unchanged) |
| Which launches occupy a role set | open custody spans that carry a claim |
| Whether a `host_capacity` suspension may resume | the custody transaction's parked or woken state |

An attempt's state, deadline, phase, stall counter, progress marker, lane and handoff path are still
read from the ledger and compared with the core by the settle step at commit, as in package 2.
Phases, markers, lanes, worker registrations, the bound route and the controller's own seat are
adapter facts: the core has no word for them and they need none (the issue: a gate the core cannot
express "is an adapter concern, not a reason for a side ledger").

Where the store and the ledger disagree at a read, the store's answer is used. A disagreement is
normally the trace of a write that was cut between its core operations and its ledger publish, and
the next commit's settle step converges it; refusing at the read would strand the run. Refusals stay
where P2 put them, in the settle step.

A record the store does not know yet is decided from the ledger, as at the base: a launch with no
custody transaction or whose open span carries no claim entry, a `host_capacity` suspension with no
custody transaction, a contract with no delivery transaction. The commit of that same command binds
it (P2 D19 did the same for a live attempt with no transaction), so the fallback lasts one write.

### Run resolution by index

No command of the control plane lists a directory. `workflow-state migrate` keeps its inventory
listing: it is the migration's dry run over retained ledgers, which the record requires, and it is
not a control decision (per D7).

- **`direct-owner`** (per D9) drops its prefix scan. The runs of an issue are the index entries
  `attempt-run/v1:direct:<issue>:<s>` for `s` from 1 to the first miss. Each entry's ledger is at
  the handle its run transaction's subject names (the legacy alias, else the transaction id) and
  is checked as today (non-symlink directory, ledger holding exactly that issue, identity equal to
  the entry). An entry
  whose ledger is absent ends the list and is the reserved id of the next mint (P1). At the first
  miss the helper probes one name, `workflows/direct-<issue>-<s, six digits>`. If it exists, a
  legacy ledger was never bound: the call is refused as
  `unmigrated direct run: run workflow-state migrate --apply`, with nothing written. Any other
  directory entry is not read.
- **`build-delivery`** (per D10) finds the ledgers that installed a contract by probing the
  delivery transactions `attempt-delivery/v1:<issue>:<contract digest>:<n>` for `n` from 1 to the
  first miss. Each names its run; the ledger at that run's handle is then read and validated
  exactly as today. One match serves the root intent and the current selection; two or more keep today's
  refusal for the current selection, naming the runs in install order, and the root intent is taken
  from the first. No match keeps today's answers. A ledger still at schema 9 has no delivery
  transaction and is not found until its next write or `migrate --apply` binds it.
- **Run reuse** (per D11) moves from skill prose into `init-run`, which takes exactly one of
  `--run-id`, `--creation-key` and the new `--issue-set <n>-<n>…`. For an issue set the helper
  sorts and de-duplicates the numbers and probes the run transactions under caller key
  `issue-set:<numbers joined by ->:<k>` for `k` from 1 upward. It returns the bootstrap of the first
  run that is *reusable*: its ledger is absent, or some requested issue has no entry, a null
  `outcome`, or a latest attempt or remainder that is `active`, `handed_off` or `suspended`. A
  probed ledger that does not validate refuses the call, naming the run. At the first miss it
  mints under that key. This is the skill's rule ("the same issue set with a
  non-final attempt or missing outcome") stated on ledger fields. The orchestrate-issues skill's
  bootstrap text loses the listing sentence and the `<unix-ts>` key and calls
  `init-run --issue-set`. `--creation-key` stays for from-issue's durable acquisition.
- **`control`**, owner transports and `check-launch` already address one run by handle and verify it
  against its run transaction (P1). They are unchanged.

### Custody for delivery remainders

Per D3. A remainder record gets a custody transaction under creation key
`attempt-custody/v1:<run>:<issue>:r<n>`, authority class `attempt-custody`, the empty plans and the
one concurrency key `attempt-worktree:<worktree>`. A remainder runs in its source attempt's worktree,
so the lease already enforces the record's rule of one nonterminal custody across both lineages.

- **Subject `remainder-custody/v1`**, closed: `schema`, `run`, `issue`, `remainder`, `worktree`,
  `prior` (the custody transaction id of the source attempt for remainder 1 or of remainder 1 for
  remainder 2, null when that record has none), `bound_launch`.
- A launch `issue:r<n>:<launch>` is the span whose executor is that action id. The settle planner
  of P2 plans a remainder record through the same rows; a remainder has the `state`, `launches`,
  `deadline_at`, `blocked_on`, `result` and `result_source` members an attempt has. The remainder's
  one extra suspension cause, `owner_unavailable`, joins the vocabulary in
  `agent_tools.attempt_custody`.
- A record that ends in the write that launches its successor releases its span before the
  successor acquires (extends P2 D24 to the attempt-to-remainder and remainder-to-remainder steps).
- The misbinding check and the launch fence of P2 already address remainders by action id; they now
  find a lease holder for them.
- The remainder lane's window rule is not changed (see Out of scope).

### Admission claims on custody

Per D1. The ledger's `admission` block keeps its shape and stays the rendering the replies and the
replay metrics are built from.

- **A held owner claim** is an open custody span that carries a claim: one `snapshot` evidence
  entry `admission-claim:<action id>:<epoch>` whose reference is the canonical JSON of
  `{"roles": …, "route": …}`. The settle step records it right after the acquisition, or on an
  already open span at the sweep that binds the route, whenever the block holds a claim for that
  launch. A launch with no claim in the block (a direct route, a remainder minted by an owner's
  `finish`) gets none.
- **Release is the span closing.** No separate release operation exists in the core: the reap, the
  release, the parking or the seal that ends the launch's custody ends the claim. The block's
  `release_event`, `release_seq`, `released_at` and the `releases` counter are written as today and
  are the adapter's account of that one core event.
- **`owner_unavailable`** (per D15). When control releases a claim because the host reports the
  owner gone, the settle step releases that launch's span in the same write. The projection table
  of P2 gains one row: ledger `active`, claim released `owner_unavailable` ↔ transaction `created`,
  no span. A later takeover acquires as any resume does.
- **Occupancy.** Control's `available` and `reserved` are computed from the store: a launch
  occupies its role set when its span is open, has not lapsed at the sweep's time and carries the
  claim, and the host has not reported its owner unavailable in this request. A claim the block
  holds for a launch the store has not bound yet (see above) also occupies. A claim the block holds
  for a launch whose span the store shows closed does not. Role-set sizes, the
  declaration and the route stay in `agent_tools.host_admission`.
- **The controller's seat and the route** are adapter rendering. The controller claim has no
  custody behind it and is derived each sweep from whether a deadline is armed; the route is host
  policy the record keeps outside the core.

Admission still covers agent slots only. Nothing here reads load, and the declaration is not a
scheduler.

### Wakeups

Per D4. The helper has no daemon. "Event-driven" means the write that changes capacity records the
fact where the next sweep reads it, and a sweep is started by the host's notification, not by a
timer.

- **The events** are custody span closings: an owner's own `finish`, `suspend` or handoff (owner
  exit), a reap or a control release (settle, release), and a delivery completing (capacity
  completion). Each is written by the command that caused it, through the settle step.
- **Slot shortage.** An issue withheld for want of a role set is reported `waiting`, as today. It
  has no attempt, no launch and no custody transaction: nothing is created for it, so no attempt is
  spent. The next sweep admits it when the store shows a free role set.
- **The `host_capacity` gate.** A host-refused launch parks its custody transaction with reason
  `suspended:host_capacity`. When a later write adds a release to the block that is not
  `launch_refused`, the settle step of that same write advances every custody transaction of the
  run parked for that reason back to `created` with reason `capacity_released`. Releases are applied
  in `release_seq` order, so a refusal and a release in one write keep today's order. The gate is
  then one read: parked means `waiting`, woken means it may resume. Within a sweep, a release the
  sweep itself adds after the refusal also opens the gate, as today. Projection row: ledger
  `suspended` on `host_capacity` ↔ `attention_required`, or `created` with no span after the wake.
- **Unchanged.** The `wait` action, its `wake_on` set (`owner_notification`, `tracker_change`,
  `deadline`), the `admission` report and the lane order. `waiting` is never persisted and no queue
  order is introduced. A sweep that finds nothing to change writes nothing.

### Delivery transaction and its journal

Per D2. Created by the settle step in the write that installs a contract.

- **Creation key** `attempt-delivery/v1:<issue>:<contract digest>:<n>`, where `n` is the first
  ordinal whose key is unused or whose transaction names this run, chosen under the store lock.
  Authority class `attempt-delivery`, concurrency key `attempt-delivery:<run>:<issue>`, the empty
  recovery plan. Its bound subject path is the ledger root.
- **Subject `attempt-delivery/v1`**, closed: `schema`, `run`, `issue`, `contract_digest`,
  `contract`. The installed contract is immutable in the engine, and the subject makes it so in the
  core.
- **Proof plan**, compiled at creation from the contract: one deterministic collector, and one
  required `event` obligation per postcondition the contract marks `required`, with the
  postcondition's name as its id and predicate. A postcondition the contract marks `not_applicable`
  has no obligation: applicability is declared at creation, never inferred later.
- **Journal.** Every object in the ledger's `authorization_intents`, `authority_observations`,
  `reevaluation_evidence`, `authority_evaluation_consumptions`, `delivery_observations` and
  `selected_outputs` is one `event` evidence entry `<kind>:<id>` whose reference is the object's
  canonical JSON text, in the delivery model's own canonical form. The objects are the shipped wire
  objects; no parallel grammar is defined. The settle step appends the entries the transaction
  lacks under a span it takes and releases within the write (executor `delivery:<issue>`), as the
  last core operations before the ledger is published. `stage_facts` and `postconditions` are not
  journaled: the delivery model derives them from the journaled objects.
- **No read-time comparison.** Every journaled object's `id` is the digest of its own content,
  which the delivery model verifies on every read, so a ledger object cannot differ from the entry
  under its id. An entry the ledger lacks is the trace of an interrupted write; it is evidence the
  core received and nothing reads it as a decision.
- An issue with no contract has no delivery transaction.

### Sealing

Per D5. The seal goes last, after the ledger is published, and is completed by the run's next
write, an unchanged repeat or `migrate --apply`, exactly as P2 D24 completes a custody seal.

- **Delivery.** When the ledger is delivery-complete and the delivery transaction is not terminal,
  the settle step takes a span, advances the transaction to `proving`, opens the cohort, collects
  each obligation from the ledger's postcondition (outcome `satisfied`, reference the bound
  observation's id) and calls `settle_proof`. The transaction seals `succeeded`; its receipt's
  `evaluations` are the applicable postconditions with their observations. The rule is on state,
  not on the transition, so a ledger that was already complete when it reached schema 10 seals at
  its bind.
- **Custody over a delivery.** After that seal, every custody transaction of the issue that is not
  terminal seals `succeeded` through the core's empty-plan path, under a span taken for the seal
  (executor `<issue>:<attempt or r<n>>:seal`), after one `event` evidence entry
  `delivery-receipt` whose reference is the delivery receipt's digest. Its receipt lists that
  record's stops and owner results. A span that cannot be taken because another custody holds the
  worktree leaves the seal pending. A seal cut partway resumes from the state it reached: the
  planner accepts the core's forward states on a record that is awaiting its seal, and on no
  other.
- **Unchanged from package 2.** A verdict with no merge recorded seals `abandoned`, now for a
  remainder too; a synthesized stop parks. A record over a recorded merge whose delivery never
  completes stays parked or unsealed: unknown reality parks. A `merged` attempt of an issue with
  no contract has no delivery proof and stays unsealed.
- **After a seal** (per D6). A delivery object, an owner result or a reconciled merge that arrives
  for a sealed transaction is recorded with the core's `record_post_terminal` on that receipt
  (outcome `satisfied` for a delivery object or a reconciled merge, `unknown` for an owner result;
  reference the object's canonical text or the report's digest). The receipt never changes and
  nothing is refused for being late. A supplement counts as that object's journal entry. This replaces P2 D18's "writes nothing to the core" and P2's unretained post-seal
  result.

### Schema 10 and migration 9 → 10

Per D7. Schema 10 means "this ledger's claims, delivery objects and remainder custody are held in
the core". No field is added or removed, so no reply and no reader changes.

- **Dry run first.** `workflow-state migrate` reports a schema-9 ledger with verdict `migrate` and
  no new field or refusal reason; `attempt-migration-report/v1` is unchanged. A 9 → 10 plan cannot
  be refused for a reason an 8 → 9 plan could not.
- **Adjacent and on write.** The step composes after 8 → 9 in the locked read, and is committed by
  the ledger's next write or by `migrate --apply`, under that ledger's lock.
- **What the bind does**, through the same settle step every later write runs, so repeating it
  changes nothing:
  - each nonterminal remainder gets its custody transaction, with a span only when it is `active`
    and unexpired and `bound_launch` set to its launch count (P2 D11 for remainders);
  - each held owner claim whose launch has an open span gets its claim entry;
  - each `host_capacity` suspension is parked or woken as the block's sequence rule says at that
    write;
  - each installed contract gets its delivery transaction and its whole journal, and seals if the
    delivery is already complete, followed by that issue's unsealed custody transactions.
  No launch, stop or result is replayed into a custody transaction (P2 D11). Journal entries are
  the stored objects themselves, with their own times.
- **Atomic.** The ledger file is replaced once. A bind cut before that leaves a schema-9 ledger and
  core entries the next attempt finds and skips.
- **No dual writable store.** The package-2 helper refuses schema 10 through its existing version
  check, with the ledger unchanged. There is no reverse transform.
- **Activation.** After the switch, `workflow-state migrate --repo-root <root>` then `--apply` per
  ledger root binds every ledger, so that a contract installed before the cutover is found by
  `build-delivery` and a legacy direct ledger is not refused. An orchestration started before the
  cutover is re-entered with `init-run --run-id`; its run is not under an `issue-set` key. Both
  facts go in the README.

### Packaging and prose

- `agent_tools.attempt_delivery` (new, pure): the delivery subject, key and proof plan, the journal
  entries of a ledger `delivery`, and the remainder subject. It imports nothing from
  the skill scripts; workflow-state passes the delivery model's canonical-text function in
  (per D14).
- `agent_tools.attempt_custody`: the planner gains the claim entry, the `owner_unavailable` row,
  the wake and the `succeeded` seal. `agent_tools.attempt_store`: applying them, the index probes
  for direct runs, issue sets and installed contracts, the occupancy read and the supplement call.
- No `transaction_*` module changes; every operation used is already public (per D14).
- Contract prose goes to the transaction-core paragraph of `python/README.md` and to
  `home/common/agent-skills/README.md` § Lifecycle helpers (build-delivery, Host admission, Run
  identity and migrate, Attempt custody and fencing). Root `CLAUDE.md` gains no detail. The skill
  edit must leave the instruction budget gate green without a raise.

## Control decisions of the current interface

Read from `_apply_one_issue_policy`, `command_control` and the delivery runtime's policies at the
base. A *control decision* is one policy operation, one sweep-level action or one admission outcome.
Each row is one case of AC3: the reply is validated at the `workflow-response` boundary and equals
the reply the base produces for the same request, and the store is read back.

| # | Decision | Reply at interface 3 | Store on the migrated path |
|---|---|---|---|
| 1 | `spawn` | action `spawn`, delta `spawned` | custody transaction created, span 1 open with a claim; delivery transaction created with its journal |
| 2 | `resume` (handoff, suspension, dead owner) | action `resume`, delta `resumed` | new span at the next epoch, transaction `created`, claim on the new span |
| 3 | `retry` | action `retry`, delta `retried` | second custody transaction with `prior` set |
| 4 | remainder launch (`resume` or `spawn` with remainder custody) | action `delivery_remainder` | remainder custody transaction, span open with a claim |
| 5 | `recover` | action `delivery_remainder` for remainder 2 | second remainder custody transaction, `prior` remainder 1 |
| 6 | `refuse` | delta `retry_refused`, no action | attempt 2's transaction sealed `abandoned` |
| 7 | `reconcile` | no action, no delta; summary `merged` | a live span released; `pr_merged` observation journaled |
| 8 | `terminal` (lifecycle, tracker halt, delivered) | summary only | unchanged |
| 9 | `idle` | summary only | unchanged |
| 10 | `observe` that ends one resume | summary requirement `worktree_fact` | the reap of row 12 only |
| 11 | `contract` | summary requirement `delivery_contract_required`; action `delivery_contract` when no deadline is armed | nothing created |
| 12 | reap of an expired launch | delta `expired` | `lease_lapse_detected`, `stop_synthesized`, parked; or `stalled` at the bound |
| 13 | withheld for a role set | `admission.waiting` | nothing created for the issue |
| 14 | withheld at `max_parallel` | no action, not `waiting` | nothing created for the issue |
| 15 | `launch_refused` report | summary `suspended` on `host_capacity`, `admission.waiting` | parked `suspended:host_capacity`, span closed |
| 16 | gate opened by a later release | action `resume` | `capacity_released`, then row 2 |
| 17 | `owner_unavailable` report | claim released; takeover as row 2 when admitted | span released in that write |
| 18 | `wait` | action `wait` with `wake_on` and `wait_seconds` | unchanged |
| 19 | `finalize` | action `finalize` | unchanged; the controller seat is not in the store |

`direct-owner` runs the same policy for one issue and is covered by the regression floor.

## Test seams

Two seams, both already in `just agent-workflow-tests`; the new test files are added to that
recipe's list. No other seam may be invented.

1. **The workflow-state CLI**, driven from source as `LifecycleHarness`, `BuilderHarness`,
   `DeliveredControlHarness` and `AdmissionReplayTest` do, in a new
   `home/common/agent-skills/tests/test_control_cutover.py`. Observable behaviour is output and exit
   code, the ledger's bytes, and the store read through the core's public readers (`lookup`,
   `load`, `inspect_lease`, `read_receipt`, `post_terminal_observations`). A "tree snapshot" is
   `LifecycleHarness.tree_snapshot`.
2. **Pure functions** of `agent_tools.attempt_delivery` and the extended planner, imported normally
   by `tests/test_attempt_delivery.py` and the existing `tests/test_attempt_custody.py`.

| Criterion | Deterministic check (seam) |
|---|---|
| AC1 run identity from the index | **Unreadable:** the `workflows` directory is set to mode `0300` (entries can be opened by name, the directory cannot be listed) and the test first shows that listing it raises. `init-run --issue-set`, two `control` sweeps, an owner `progress`, `check-launch`, `direct-owner` and `build-delivery --kind current-selection` then print the bytes they print with the directory readable. **Contradicts:** with stray `direct-41-000009` and `direct-41-bad` directories, `direct-owner` returns the reply and leaves the tree it does without them; with the run's ledger directory copied to `zz-copy`, the current selection is served from the indexed ledger and `init-run --issue-set` returns the indexed run. **Lacks:** an index entry with no ledger is reused by `direct-owner` and by `init-run --issue-set`; a legacy `direct-41-000001` ledger with no index entry is refused as `unmigrated direct run` with the tree unchanged, and admitted after `migrate --apply`. **Occupancy:** with the held claim deleted from the ledger's block by hand, a sweep still reports the second issue `waiting` and the reserved counts of the store. (1) |
| AC2 wakeups and admission, no launch or expiry regression | `AdmissionReplayTest`'s `measured`, `seven_slots` and `scripted_refusal` replays equal the committed baseline, and the baseline file is not edited. **Queue:** with four slots and issues 12 and 14, after the first sweep the store holds 12's custody transaction with an open claimed span and no creation key for 14, whose ledger entry has no attempt. A second sweep with no event between leaves the tree snapshot unchanged and 14 `waiting`. 12's owner delivers; the tree then shows 12's span closed by that command, and the next sweep spawns 14 as attempt 1, launch 1. **Refusal:** with seven slots both are launched and 14's launch is refused: its transaction is parked `suspended:host_capacity`; a sweep with no release leaves it parked and the tree unchanged; after 12's owner finishes, 14's transaction is `created` with reason `capacity_released` before any sweep runs, and the next sweep resumes it. **Read-only:** `check-launch` over an `active` row whose deadline has passed, an unknown run, issue and attempt, and a schema-9 ledger leaves the tree snapshot, store included, unchanged and prints the base's bytes (1) |
| AC3 every control decision has an equivalent | One case per row of the decision table: reply validated at the boundary and equal to the base's, store read back as the row says (1). The planner's new rows are checked as pure plans (2) |
| AC4 regression floor | The whole `just agent-workflow-tests` suite is green at the package head, with `just build`, `just agent-installed-skill-tests` and `just agent-instruction-budget`. Declared changes to the floor are those of D16 and nothing else. The package-2 helper, extracted with `git archive` from the pinned base `079b835c54fabe6baf550097c40debc595a81bda`, exits 2 on a schema-10 ledger with the tree unchanged, and a missing commit fails the test. Sealing: a contracted issue delivered through a remainder ends with a `succeeded` delivery receipt whose evaluations are its required postconditions, `succeeded` custody receipts for the merged attempt and the remainder, and a later tracker observation recorded as a supplement with every receipt's bytes unchanged (1) |

Schema-9 fixtures are made by the real package-2 helper from the pinned base, driving a run to the
shape under test (per D16).

## Out of scope

- Host-load scheduling of any kind: CPU, memory, Nix daemon or test hosts. A persisted queue or a
  queue order.
- New control decisions, reply fields or wake events; the `wait` action and interface versions.
- Reading an attempt's state or deadline from the lease at the locked read. They stay
  commit-checked projection (D12).
- The close-before-merge hold on handed-off resumes, dead-owner resumes, remainders and live-custody
  merges (the record's D15 and D18), and the fresh window on every remainder resume (the record's
  D12). Neither is in this issue's criteria, and both change dispatch.
- The delivery runtime and the delivery model: not edited. Compare-and-set at the forge and
  enforcement inside the mutation guard.
- Ship-release's move onto the core, any layout move of ledgers or runtime roots, moving
  workflow-state into the package, any reverse migration, and replaying pre-migration history.
- Human disposition of a parked transaction (`dispose_failed`) and cleanup of terminal store
  entries.

## Triage

> **Lane triage.** Input: `contract_change` hit (control decisions, claims and delivery objects move into core state; a schema step is expected); `concurrency_or_persistence` hit (persisted lifecycle state, store and ledger locks, claims released with custody); `open_design_questions` hit (the core expression of claims, delivery objects and wakeups is not settled by the body); `criteria_shape` no (four `[code]` criteria, each measured by `just agent-workflow-tests` or `just build`). Paths: `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_custody.py`, `python/agent_tools/host_admission.py`, `home/common/agent-skills/scripts/workflow_delivery.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_host_admission.py`, `home/common/agent-skills/README.md`, `python/README.md`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}`. `ran: full (shadow)`.

## Decision ledger

"Record" is the issue 117 decision record; "P1" and "P2" are the package 1 and 2 designs. The five
Phase-0 questions are answered by D1 and D2 (which core objects), D4 (wakeups), D5 (the merged
seal), D7 (the schema step and its dry run) and D8 (the unreadable fixture).

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A held owner claim is an open custody span carrying one claim entry; it is released by the span closing. The controller's seat, the route and the block's release bookkeeping stay adapter rendering. | Record: claims are "bound to custody and released atomically with the custody transition", and "route names, the declaration and role-set sizes stay host/adapter policy"; the engine already requires a held claim to be its issue's current launch; core evidence needs live custody and a `snapshot` is void once the fence moves. | A claims journal on a run-scoped transaction (a second structure to keep equal to the spans, and an interrupted write leaves a release the ledger never made under a sequence number it will reuse); a concurrency key per slot (keys are fixed at creation, and it would turn per-run accounting into a host-wide semaphore the record does not ask for). |
| D2 | Delivery objects are carried by one delivery transaction per installed contract: the contract is the subject, the appended objects are `event` evidence holding their canonical text, and the key is `(issue, contract digest, ordinal)`. | Record D13: `delivery-contract/v1` realizes the entry subject; record: "the core adopts #151's wire objects … rather than defining a parallel one"; the engine treats an installed contract as immutable; the index finds only creation keys, and `build-delivery` knows an issue and a digest but no run. | Fields or events of the custody transaction (subjects are immutable, and observations arrive when no launch holds custody); a key of `(run, issue)` (the installed-contract lookup would need a second index or a scan); digests only (the core would attest objects it does not hold). |
| D3 | A remainder gets its own custody transaction on the worktree key, planned by the P2 planner's rows. | P2 D1 put custody in one transaction per attempt because a key is fixed at creation; a remainder runs in its source attempt's worktree; claims are named by remainder action ids, so D1 needs a span for them. | The record's D12 letter, a second lineage in one transaction (already set aside by P2 D1 for attempts; two rules for one kind of record); leaving remainders in the ledger (their claims would have no custody to bind to). |
| D4 | A wake is a core event the next sweep reads: slot occupancy comes from open spans, and the `host_capacity` gate is a `capacity_released` transition written by the write that adds a non-refusal release. `waiting` is not persisted, no queue order exists, and `wake_on` is unchanged. | Record: reaping and resume stay next-touch, "not a new background timer"; "the owner-exit notification wakes the next sweep"; native wake transport is an adapter duty; two writes may carry one time (a supplied `--now` may repeat), so "a later release" cannot be read from event times; `advance` out of a parking needs no custody. | Comparing event times across transactions (ties between writes and inside one write change the shipped order); a persisted queue (a write on every sweep and a new admission order the replay baseline would not match); a polling timer (the thing the issue removes). |
| D5 | The delivery transaction seals `succeeded` on a plan of the contract's required postconditions; every unsealed custody transaction of the issue then seals `succeeded` by the empty-plan path with the delivery receipt's digest as evidence. A contractless `merged` attempt stays unsealed. | Record: "success needs the immutable plan's applicable proof", "applicability is predeclared", "cleanup required for deliverable success must be proved before that success", "the core seals these as receipt content"; P2 D5 left `merged` unsealed for want of that proof; the-bar truthful terminal states. | Sealing a merged custody `abandoned` (says no effect happened); sealing it at the merge (a delivered attempt would read as done while its remainder still fails); a proof plan on the custody transaction (plans are fixed at creation and existing transactions have the empty one); leaving custody unsealed for good (a store of transactions that never end). |
| D6 | What arrives for a sealed transaction is a post-terminal observation on its receipt, read as part of the journal. Replaces P2 D18's silence and P2's unretained post-seal result. | Record: "later observations use immutable linked evidence/receipt supplements, not replacement bytes or extra terminals"; P2 left supplements to this issue; `record_post_terminal` exists and needs no custody. | Refusing late objects (a held issue whose tracker closes later would be refused); delaying the delivery seal until nothing can arrive (no such moment). |
| D7 | Schema 10 is a marker with no field change. The bind is the ordinary settle step, so it is state-based and repeatable; the report gains nothing; `migrate` keeps its inventory listing. | Record: dry run first, "that identical transform on write under the owning module's lock: adjacent, atomic and idempotent", and "inventory all old dialects"; P2 D14 (exclusion by schema bump, tested with the real older helper); P2 D11 (no replay). | A report version with per-ledger counts (no reader, and no new way to be refused); a quiescent cutover (record D14 reversed it); an index of ledgers to replace the inventory (legacy ledgers are exactly the ones not in the index). |
| D8 | "Unreadable to the control plane" is exercised by mode `0300` on `workflows`, with a positive control that listing fails, and by contradicting and missing entries. | Issue demo; the-bar tests that can fail; the floor already uses a `chmod` fixture for an unreadable ledger; ledgers stay under `workflows`, so the directory must stay searchable. | Mocking the listing calls (asserts a call, not behaviour); moving ledgers out of the directory (a layout move, out of scope). |
| D9 | `direct-owner` takes its runs from the index alone and refuses, by one keyed probe at the frontier, a legacy direct ledger that was never bound. | P1 deferred the prefix scan's removal here; legacy direct sequences are contiguous from 1, so one name covers every unbound ledger; the-bar fail loud and defense in depth; `migrate --apply` binds legacy ledgers. | Binding the probed ledger on the spot (resolves a run from a directory name, the thing AC1 forbids); no probe (a second run would be minted beside an unbound live one). |
| D10 | The installed-contract lookup probes delivery transactions by `(issue, digest, ordinal)` and then reads the named ledger as today. A schema-9 ledger is found only once bound. | Issue: the lookup "moves to the same index"; D2's key; `build-delivery` is read-only and cannot bind; every lifecycle write and `migrate --apply` bind. | Answering from the journal alone (the current selection needs the derived stage facts, which the core does not hold); a fallback scan for schema-9 ledgers (keeps the scan). |
| D11 | Run reuse is `init-run --issue-set`, probing `issue-set:<sorted issues>:<k>` and applying the skill's reuse rule on ledger fields. Refines P1 D39 for orchestrate-issues. | P1 left the reuse listing here; P1 D39 rejected a counter only because finding the next one needed a scan, and an index probe needs none; the-bar token economy (the dispatcher emits the issue numbers and nothing else). | A separate `find-run` command (a second call and a race between find and mint); pointer transactions under the old keys (a second identity per run); keeping `<unix-ts>` keys (a restart cannot recompute them). |
| D12 | Control reads identity, occupancy and the gate from the store at its locked read, and the store wins a disagreement; delivery objects are content-addressed, so they are journaled and never compared. A record the store has not bound is decided from the ledger for the one write that binds it. Attempt state and deadlines stay ledger fields checked at commit. | Issue AC1 and AC2 name identity, admission and wakeups; P2 D4 (projection, core first, refusal at commit); P2 D19 (the settle step binds what has no transaction, because the floor hand-builds ledgers); P2 D24 (a cut write converges on the next commit). | Reading every attempt field from the core (rewrites the policy and the delivery runtime, far over one review); refusing any disagreement at the read (strands a run after a crash and refuses every hand-built fixture); comparing journal text at the read (the model's id check already makes a difference impossible, so no test could turn it red); union of both for occupancy (follows the ledger exactly when it is wrong). |
| D13 | A control decision is a policy operation, a sweep-level action or an admission outcome; the nineteen rows above are the closed list for AC3. | Read from the live policy and sweep code; the wire validator's action and delta sets; the-bar fail loud at closed sets. | Summary states as decisions (they render record state); one case per reply field (tests a shape the boundary validator already pins). |
| D14 | No `transaction_*` module changes. The new pure module takes the canonical-text function as an argument, and a delivery transaction's bound path is the ledger root. | Agent-helpers rules 1 and 3 (helpers in the package, no import machinery); the delivery model is loaded by file path in the skill scripts; the neutrality check; P2 D12 kept core additions to one; the core requires an absolute bound path, and a retry may move the worktree while the ledger root is fixed for the run. | Importing the delivery model into the package (path-derived import); an append-without-custody core call (a core change every consumer inherits). |
| D15 | An `owner_unavailable` release closes the launch's span in that write. Amends P2 D3's timing, not its outcome. | D1: the claim is the span; P2 D3: `owner_unavailable` is the host's observation that the holder is gone; a late report from that owner is still retained through the P2 intake. | Keeping the span open with the claim marked released (a held span with no claim, the state D1 removes). |
| D16 | The floor changes in declared ways only: the schema number and unknown-schema fixture; schema-9 fixtures made by the pinned package-2 helper; direct-discovery cases where a stray or malformed entry is now ignored, not refused; installing-ledger cases rebuilt on index entries; skill-contract cases for the `init-run` argv. | P2 D14 and D22; the-bar "shape fixtures like the values production actually carries"; D9 and D10 change what a stray directory means. | Hand-building schema-9 stores (the core cannot be written backward, and a shortcut fixture could match a shortcut bind). |
| D17 | Claim entries carry the span's epoch in their id, and journal entries are the last core operations before the ledger is published. | Core evidence ids are single-use per transaction and a launch can reacquire (P2 D16); the smaller the window, the fewer journal entries a cut write leaves ahead of the ledger. | One id per launch (a reacquired launch could not record its claim). |
